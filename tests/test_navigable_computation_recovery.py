"""Crash/restart integration for structural-memory-driven navigable computation."""

from __future__ import annotations

import json
import time

import pytest

from mailcpu import (
    Capability,
    CapabilityRequirement,
    EffectClass,
    HeadlessOS,
    HypervisorArbitrationEvent,
    HypervisorDomain,
    HypervisorOperationChannel,
    HypervisorOperationResultChannel,
    HypervisorPolicy,
    HypervisorRequest,
    NavigableComputationCheckpoint,
    NavigableComputationCheckpointError,
    ObservationContract,
    ReliabilityPolicy,
    ReliableChannel,
    ReplayClass,
    RepresentationRef,
    ResourceBound,
    SocketTransport,
    TransitBackendRouter,
    TransitComputeHost,
    TransitComputeSession,
    TransitComputeWorker,
    TransitOracleEvidence,
    TransitStructuralMemoryHost,
    TransitTranslationEvidence,
    TranslationContract,
    canonical_value_digest,
    compare_projected_observations,
)
from mailcpu.evidence_path_resolver import (
    EvidencePathCatalogue,
    EvidencePathEdge,
    EvidencePathRequest,
    EvidencePathResolver,
    EvidencePathStatus,
    EvidenceStrength,
    RouteMetric,
    RouteMetricKey,
)
from mailcpu.law_certifier import Law
from mailcpu.transit_structural_memory import (
    TRANSIT_STRUCTURAL_MEMORY_OPERATION,
    TRANSIT_STRUCTURAL_MEMORY_RESOURCE,
)


_CPU_OPERATION = "execute deterministic CPU arithmetic program"
_CPU_RESOURCE = "/cpu/compute"
_CHANNEL = "navigable.recovery"
_CONTEXT = {"tenant": "recovery", "partition": 12}


def _tcp_pair(local: str, peer: str) -> tuple[SocketTransport, SocketTransport]:
    """Create reciprocal test transports over one loopback TCP connection."""
    listener = SocketTransport.listen("127.0.0.1", 0)
    port = listener.getsockname()[1]
    local_transport = SocketTransport.connect("127.0.0.1", port, local, peer)
    peer_transport = SocketTransport.accept(listener, peer, local)
    listener.close()
    return local_transport, peer_transport


def _channels():
    """Create requester and receiver channel pairs with aligned identities."""
    request_client_transport, request_worker_transport = _tcp_pair("client", "worker")
    response_worker_transport, response_client_transport = _tcp_pair("worker", "client")
    policy = ReliabilityPolicy(lease_ticks=1, max_attempts=3, window_size=4)
    request_client = HypervisorOperationChannel(
        ReliableChannel(
            request_client_transport,
            "client",
            "worker",
            _CHANNEL,
            policy,
        )
    )
    request_worker = HypervisorOperationChannel(
        ReliableChannel(
            request_worker_transport,
            "worker",
            "worker",
            _CHANNEL,
            policy,
            peer="client",
        )
    )
    response_worker = HypervisorOperationResultChannel(
        ReliableChannel(
            response_worker_transport,
            "worker",
            "client",
            _CHANNEL + ".result",
            policy,
        ),
        "client",
        _CHANNEL,
    )
    response_client = HypervisorOperationResultChannel(
        ReliableChannel(
            response_client_transport,
            "client",
            "client",
            _CHANNEL + ".result",
            policy,
            peer="worker",
        ),
        "client",
        _CHANNEL,
    )
    return (
        (request_client_transport, request_worker_transport,
         response_worker_transport, response_client_transport),
        request_client,
        request_worker,
        response_worker,
        response_client,
    )


def _wait_for_response(channel: HypervisorOperationResultChannel):
    """Wait for one typed result under a finite deadline."""
    deadline = time.monotonic() + 3.0
    result = None
    while result is None and time.monotonic() < deadline:
        result = channel.receive()
        if result is None:
            time.sleep(0.005)
    assert result is not None, "recovery test result did not arrive"
    return result


def _wait_for_ack(channel: ReliableChannel, expected: tuple[int, ...]) -> None:
    """Require the exact reliable acknowledgement cursor."""
    deadline = time.monotonic() + 3.0
    actual: tuple[int, ...] = ()
    while actual != expected and time.monotonic() < deadline:
        actual = channel.process_ack()
        if actual != expected:
            time.sleep(0.005)
    assert actual == expected


def _serve(
    session: TransitComputeSession,
    request_client: HypervisorOperationChannel,
    response_client: HypervisorOperationResultChannel,
    request_worker: HypervisorOperationChannel,
    response_worker: HypervisorOperationResultChannel,
    event: HypervisorArbitrationEvent,
    expected_transport_sequence: int,
):
    """Send and serve one operation through Transit, then acknowledge both directions."""
    assert request_client.send(event) == expected_transport_sequence
    deadline = time.monotonic() + 3.0
    result = None
    while result is None and time.monotonic() < deadline:
        result = session.serve_once()
        if result is None:
            time.sleep(0.005)
    assert result is not None, "Transit worker did not serve recovery workload"
    returned = _wait_for_response(response_client)
    assert returned.effect == result.effect
    _wait_for_ack(request_client.channel, (expected_transport_sequence,))
    _wait_for_ack(response_worker.channel, (expected_transport_sequence,))
    assert session.phase == "idle"
    return result, returned


class _CountingHost(TransitComputeHost):
    """Expose actual CPU backend invocations across receiver replacement."""

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def handle(self, event: HypervisorArbitrationEvent) -> dict[str, object]:
        self.calls += 1
        return super().handle(event)


def _router(
    operating_system: HeadlessOS,
    pid: int,
    cpu_host: _CountingHost,
) -> TransitBackendRouter:
    """Rebind the same exact CPU and Structural Memory backend manifest."""
    router = TransitBackendRouter(cpu_host)
    router.register_backend(TransitStructuralMemoryHost(operating_system, pid))
    return router


def test_navigable_computation_restores_route_and_replays_without_reexecution() -> None:
    """Persist the full memory->CPU route, restart receiver, re-resolve it, and replay the CPU effect."""
    receiver = HeadlessOS(
        structural_memory_admission_policy=lambda proposal: proposal.spec.domain == "integer-orbit"
    )
    law = Law(
        family="int",
        params={"x0": 13, "step": 9, "mod": 251},
        order=1,
        verdict="GROUND",
    )
    proposal = receiver.structural_memory.propose(
        "recovery-orbit",
        law,
        {0: 13, 1: 22, 2: 31, 3: 40},
        domain="integer-orbit",
        context=_CONTEXT,
    )
    admitted = receiver.structural_memory.admit(
        proposal.proposal_id,
        expected_revision=0,
    )
    authority_pid = receiver.environment.kernel.spawn(
        "navigable-recovery-receiver",
        capabilities=(
            Capability(TRANSIT_STRUCTURAL_MEMORY_RESOURCE, frozenset({"read"})),
            Capability(_CPU_RESOURCE, frozenset({"execute"})),
        ),
        parent_pid=receiver.environment.init_pid,
    )
    receiver.hypervisor.policy = HypervisorPolicy(
        review_confidence=0.0,
        automatic_confidence=0.0,
        destructive_confidence=0.0,
        danger_review_probability=1.0,
        embedding_review_confidence=1.0,
    )

    initial_cpu_host = _CountingHost()
    transports, request_client, request_worker, response_worker, response_client = _channels()
    worker = TransitComputeWorker(
        receiver,
        authority_pid,
        _router(receiver, authority_pid, initial_cpu_host),
    )
    session = TransitComputeSession(worker, request_worker, response_worker)

    replacement_transports: tuple[SocketTransport, ...] = ()
    try:
        # 1. A receiver-side Structural Memory operation commits the value and evidence.
        coordinate = 23
        memory_event = HypervisorArbitrationEvent(
            "client",
            _CHANNEL,
            1,
            9001,
            HypervisorRequest(
                TRANSIT_STRUCTURAL_MEMORY_OPERATION,
                TRANSIT_STRUCTURAL_MEMORY_RESOURCE,
                {
                    "memory_id": "recovery-orbit",
                    "revision": admitted.spec.revision,
                    "context": _CONTEXT,
                    "coordinate": coordinate,
                },
                frozenset({"read"}),
                frozenset(),
            ),
        )
        memory_result, memory_response = _serve(
            session,
            request_client,
            response_client,
            request_worker,
            response_worker,
            memory_event,
            1,
        )
        assert memory_result.action.value == "allow"
        assert memory_result.domain is HypervisorDomain.FILESYSTEM
        assert memory_result.executed is True
        memory_translation = TransitTranslationEvidence.from_dict(
            memory_result.effect["_semantic_translation"]
        )
        memory_oracle = TransitOracleEvidence.from_dict(
            memory_result.effect["_semantic_oracle"]
        )
        memory_translation.validate_execution_result(memory_result, require_oracle=True)
        assert memory_oracle.equivalent is True
        raw_receipt = {
            key: value
            for key, value in memory_result.effect.items()
            if key not in {"_semantic_translation", "_semantic_oracle"}
        }
        expected_value = (13 + 9 * coordinate) % 251
        assert raw_receipt["value"] == expected_value
        assert raw_receipt["spec_digest"] == admitted.spec.digest
        assert raw_receipt["certificate_digest"] == admitted.certificate.digest

        memory_edge = EvidencePathEdge.from_execution_result(
            memory_result,
            (
                RouteMetric("latency_us", "us", 7),
                RouteMetric("energy_nj", "nJ", 35),
            ),
        )

        # 2. The verified value is compiled into the exact CPU request.
        cpu_source = "\n".join((
            f"set structural_value {raw_receipt['value']}",
            "set bias 19",
            "add answer structural_value bias",
            "halt",
        ))
        cpu_event = HypervisorArbitrationEvent(
            "client",
            _CHANNEL,
            2,
            9002,
            HypervisorRequest(
                _CPU_OPERATION,
                _CPU_RESOURCE,
                {
                    "source": cpu_source,
                    "initial_registers": {
                        "memory_coordinate": coordinate,
                        "memory_revision": admitted.spec.revision,
                    },
                    "max_ticks": 16,
                },
                frozenset({"execute"}),
                frozenset(),
            ),
        )
        authorized_cpu_event = receiver.hypervisor_authorize_event(authority_pid, cpu_event)
        cpu_request_ref = RepresentationRef.from_payload(
            "mailcpu.transit.authorized-event",
            1,
            authorized_cpu_event.to_dict(),
        )
        cpu_context_digest = canonical_value_digest({
            "operation": cpu_event.request.operation,
            "resource": cpu_event.request.resource,
            "payload": cpu_event.request.payload,
        })

        # 3. Register and verify the explicit receipt -> CPU-request handoff.
        bridge_precondition = canonical_value_digest({
            "recovery_precondition": "memory receipt has independent oracle"
        })
        bridge_invariant = canonical_value_digest({
            "recovery_invariant": "CPU immediate equals committed structural value"
        })
        bridge_contract = TranslationContract(
            contract_id="mailcpu.recovery.structural-to-cpu",
            revision=1,
            source=memory_edge.target,
            target=cpu_request_ref,
            mapping=RepresentationRef.from_payload(
                "mailcpu.recovery.operand-adapter",
                1,
                {
                    "adapter": "verified-receipt-to-cpu-immediate.v1",
                    "receipt_digest": canonical_value_digest(raw_receipt),
                    "cpu_request_digest": canonical_value_digest(cpu_event.to_dict()),
                },
            ),
            observation=ObservationContract.from_definition(
                "mailcpu.recovery.operand-equality",
                1,
                {"fields": ["value"], "comparison": "canonical-json-exact"},
            ),
            context_digest=cpu_context_digest,
            precondition_digests=(bridge_precondition,),
            invariant_digests=(bridge_invariant,),
            resource_bounds=(
                ResourceBound("latency_us", 9, "us"),
                ResourceBound("energy_nj", 36, "nJ"),
            ),
            authority_requirements=(
                CapabilityRequirement(TRANSIT_STRUCTURAL_MEMORY_RESOURCE, ("read",)),
                CapabilityRequirement(_CPU_RESOURCE, ("execute",)),
            ),
            effect_class=EffectClass.PURE,
            replay_class=ReplayClass.DETERMINISTIC,
        )
        bridge_comparison = compare_projected_observations(
            bridge_contract,
            case_payload={
                "receipt_digest": canonical_value_digest(raw_receipt),
                "request_digest": canonical_value_digest(cpu_event.to_dict()),
            },
            source_observation={"value": raw_receipt["value"]},
            target_observation={"value": raw_receipt["value"]},
        )
        assert bridge_comparison.equivalent is True
        bridge_edge = EvidencePathEdge(
            bridge_contract,
            bridge_comparison,
            (
                RouteMetric("latency_us", "us", 5),
                RouteMetric("energy_nj", "nJ", 18),
            ),
        )

        catalogue = EvidencePathCatalogue()
        memory_edge_id = catalogue.register(memory_edge)
        bridge_edge_id = catalogue.register(bridge_edge)
        preflight_request = EvidencePathRequest(
            source=memory_edge.source,
            target=cpu_request_ref,
            context_digest=cpu_context_digest,
            accepted_context_digests=tuple(sorted({
                memory_edge.contract.context_digest,
                bridge_contract.context_digest,
            })),
            metric_order=(
                RouteMetricKey("latency_us", "us"),
                RouteMetricKey("energy_nj", "nJ"),
            ),
            resource_ceilings=(
                RouteMetric("latency_us", "us", 50),
                RouteMetric("energy_nj", "nJ", 500),
            ),
            satisfied_preconditions=tuple(sorted({
                bridge_precondition,
                *memory_edge.contract.precondition_digests,
            })),
            satisfied_invariants=tuple(sorted({
                bridge_invariant,
                *memory_edge.contract.invariant_digests,
            })),
            minimum_evidence=EvidenceStrength.PAIRED_CASE,
            max_hops=3,
            max_expansions=12,
        )
        preflight = EvidencePathResolver().resolve(
            catalogue,
            preflight_request,
            receiver,
            authority_pid,
        )
        assert preflight.status is EvidencePathStatus.FOUND
        assert preflight.edge_ids == (memory_edge_id, bridge_edge_id)

        # 4. The CPU operation is submitted only after preflight has resolved.
        cpu_result, cpu_response = _serve(
            session,
            request_client,
            response_client,
            request_worker,
            response_worker,
            cpu_event,
            2,
        )
        assert cpu_result.action.value == "allow"
        assert cpu_result.executed is True
        assert cpu_result.replayed is False
        assert cpu_result.effect["registers"]["structural_value"] == expected_value
        assert cpu_result.effect["registers"]["answer"] == expected_value + 19
        assert initial_cpu_host.calls == 1
        cpu_translation = TransitTranslationEvidence.from_dict(
            cpu_result.effect["_semantic_translation"]
        )
        cpu_oracle = TransitOracleEvidence.from_dict(
            cpu_result.effect["_semantic_oracle"]
        )
        cpu_translation.validate_execution_result(cpu_result, require_oracle=True)
        assert cpu_oracle.equivalent is True
        cpu_edge = EvidencePathEdge.from_execution_result(
            cpu_result,
            (
                RouteMetric("latency_us", "us", 21),
                RouteMetric("energy_nj", "nJ", 260),
            ),
        )
        assert cpu_edge.source == cpu_request_ref
        cpu_edge_id = catalogue.register(cpu_edge)

        complete_request = EvidencePathRequest(
            source=memory_edge.source,
            target=cpu_edge.target,
            context_digest=cpu_context_digest,
            accepted_context_digests=preflight_request.accepted_context_digests,
            metric_order=preflight_request.metric_order,
            resource_ceilings=(
                RouteMetric("latency_us", "us", 50),
                RouteMetric("energy_nj", "nJ", 500),
            ),
            satisfied_preconditions=tuple(sorted({
                bridge_precondition,
                *memory_edge.contract.precondition_digests,
                *cpu_translation.contract.precondition_digests,
            })),
            satisfied_invariants=tuple(sorted({
                bridge_invariant,
                *memory_edge.contract.invariant_digests,
                *cpu_translation.contract.invariant_digests,
            })),
            minimum_evidence=EvidenceStrength.PAIRED_CASE,
            max_hops=4,
            max_expansions=16,
        )
        resolver = EvidencePathResolver()
        route = resolver.resolve(catalogue, complete_request, receiver, authority_pid)
        assert route.status is EvidencePathStatus.FOUND
        assert route.edge_ids == (memory_edge_id, bridge_edge_id, cpu_edge_id)
        assert {item.name: item.amount for item in route.total_costs} == {
            "latency_us": 33,
            "energy_nj": 313,
        }

        # 5. Capture one integrity-bound cut spanning the worker and client
        # channel cursors, receiver journal/registry, committed CPU ledger,
        # route catalogue, route request/result, and retry event.
        checkpoint = NavigableComputationCheckpoint.capture(
            session,
            request_client,
            response_client,
            catalogue,
            complete_request,
            route,
            cpu_event,
        )
        serialized = json.dumps(
            checkpoint,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        checkpoint = json.loads(serialized)
        assert checkpoint["format"] == "mailcpu-navigable-computation-checkpoint-v1"

        # Integrity must fail closed before any restore is attempted.
        tampered = json.loads(serialized)
        tampered["state"]["catalogue"]["edges"].pop()
        with pytest.raises(NavigableComputationCheckpointError, match="digest mismatch"):
            NavigableComputationCheckpoint.restore(
                tampered,
                client_request_transport=None,
                client_response_transport=None,
                worker_request_transport=None,
                worker_response_transport=None,
            )

        # 6. Destroy the original transports and reconstruct all protocol
        # endpoints over new TCP streams, as after a receiver process restart.
        for transport in transports:
            if not transport.closed:
                transport.close()
        (
            replacement_transports,
            _unused_request_client,
            _unused_request_worker,
            _unused_response_worker,
            _unused_response_client,
        ) = _channels()
        (
            new_request_client_transport,
            new_request_worker_transport,
            new_response_worker_transport,
            new_response_client_transport,
        ) = replacement_transports

        restarted_hosts: list[_CountingHost] = []

        def restored_factory(restored_os: HeadlessOS, restored_pid: int):
            host = _CountingHost()
            restarted_hosts.append(host)
            return _router(restored_os, restored_pid, host)

        restored = NavigableComputationCheckpoint.restore(
            checkpoint,
            client_request_transport=new_request_client_transport,
            client_response_transport=new_response_client_transport,
            worker_request_transport=new_request_worker_transport,
            worker_response_transport=new_response_worker_transport,
            compute_host_factory=restored_factory,
        )
        assert len(restarted_hosts) == 1
        assert restarted_hosts[0].calls == 0
        assert restored.catalogue.digest == catalogue.digest
        assert restored.route_request.digest == complete_request.digest
        assert restored.route_result == route.to_dict()
        assert restored.session.worker.operating_system.structural_memory.active_version(
            "recovery-orbit"
        ) == admitted
        assert restored.session.worker.operating_system.environment.kernel.journal.verify()

        # 7. Retry the original CPU semantic identity in a new transport
        # frame. The restored hypervisor ledger must return the exact effect
        # and evidence without entering the replacement CPU backend.
        replay, replay_response = _serve(
            restored.session,
            restored.request_client,
            restored.response_client,
            restored.session.request,
            restored.session.response,
            restored.retry_event,
            3,
        )
        assert replay.executed is True
        assert replay.replayed is True
        assert replay.effect == cpu_result.effect
        assert replay_response.replayed is True
        replay_translation = TransitTranslationEvidence.from_dict(
            replay.effect["_semantic_translation"]
        )
        replay_oracle = TransitOracleEvidence.from_dict(
            replay.effect["_semantic_oracle"]
        )
        assert replay_translation == cpu_translation
        assert replay_oracle == cpu_oracle
        assert restarted_hosts[0].calls == 0
        assert initial_cpu_host.calls == 1
        assert restored.session.worker.operating_system.environment.kernel.journal.verify()
        # Recovery must also preserve the route after the replay transition.
        replayed_route = EvidencePathResolver().resolve(
            restored.catalogue,
            restored.route_request,
            restored.session.worker.operating_system,
            restored.session.worker.authority_pid,
        )
        assert replayed_route.to_dict() == route.to_dict()
    finally:
        for transport in (*transports, *replacement_transports):
            if not transport.closed:
                transport.close()
