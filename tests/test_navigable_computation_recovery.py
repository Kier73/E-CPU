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
from mailcpu.computation_dag import (
    ComputationDAGError,
    ComputationNode,
    NavigableComputationDAG,
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
        restored_memory = restored.session.worker.operating_system.structural_memory.active_version(
            "recovery-orbit"
        )
        assert restored_memory is not None
        assert restored_memory.spec.digest == admitted.spec.digest
        assert restored_memory.certificate.digest == admitted.certificate.digest
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


@pytest.mark.parametrize(
    "cut",
    (
        "before_execution",
        "after_execution_commit",
        "after_response_publish",
        "after_request_ack",
    ),
)
def test_navigable_computation_recovers_at_each_transit_crash_cut(cut: str, tmp_path) -> None:
    """Restore the combined route and reliable ledgers from four deterministic in-flight cuts."""
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
    admitted = receiver.structural_memory.admit(proposal.proposal_id, expected_revision=0)
    authority_pid = receiver.environment.kernel.spawn(
        "crash-cut-receiver",
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

    initial_host = _CountingHost()
    transports, request_client, request_worker, response_worker, response_client = _channels()
    worker = TransitComputeWorker(
        receiver,
        authority_pid,
        _router(receiver, authority_pid, initial_host),
    )
    session = TransitComputeSession(worker, request_worker, response_worker)
    replacement_transports: tuple[SocketTransport, ...] = ()
    restored_hosts: list[_CountingHost] = []

    class SimulatedCrash(RuntimeError):
        """Stop the receiver synchronously at one named protocol boundary."""

    try:
        # Establish a receiver-committed Structural Memory receipt.
        coordinate = 23
        memory_event = HypervisorArbitrationEvent(
            "client",
            _CHANNEL,
            1,
            9101,
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
        memory_result, _memory_response = _serve(
            session,
            request_client,
            response_client,
            request_worker,
            response_worker,
            memory_event,
            1,
        )
        raw_receipt = {
            key: value
            for key, value in memory_result.effect.items()
            if key not in {"_semantic_translation", "_semantic_oracle"}
        }
        expected_value = (13 + 9 * coordinate) % 251
        assert raw_receipt["value"] == expected_value == 220

        memory_edge = EvidencePathEdge.from_execution_result(
            memory_result,
            (
                RouteMetric("latency_us", "us", 7),
                RouteMetric("energy_nj", "nJ", 35),
            ),
        )
        cpu_source = "\\n".join((
            f"set structural_value {expected_value}",
            "set bias 19",
            "add answer structural_value bias",
            "halt",
        ))
        cpu_event = HypervisorArbitrationEvent(
            "client",
            _CHANNEL,
            2,
            9102,
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
        authorized_event = receiver.hypervisor_authorize_event(authority_pid, cpu_event)
        cpu_request_ref = RepresentationRef.from_payload(
            "mailcpu.transit.authorized-event",
            1,
            authorized_event.to_dict(),
        )
        cpu_context_digest = canonical_value_digest({
            "operation": cpu_event.request.operation,
            "resource": cpu_event.request.resource,
            "payload": cpu_event.request.payload,
        })
        precondition = canonical_value_digest({"precondition": "receipt is oracle-verified"})
        invariant = canonical_value_digest({"invariant": "CPU operand equals receipt value"})
        bridge_contract = TranslationContract(
            contract_id="mailcpu.crash-cut.receipt-to-cpu",
            revision=1,
            source=memory_edge.target,
            target=cpu_request_ref,
            mapping=RepresentationRef.from_payload(
                "mailcpu.crash-cut.operand-adapter",
                1,
                {
                    "receipt_digest": canonical_value_digest(raw_receipt),
                    "request_digest": canonical_value_digest(cpu_event.to_dict()),
                },
            ),
            observation=ObservationContract.from_definition(
                "mailcpu.crash-cut.operand-equality",
                1,
                {"fields": ["value"], "comparison": "canonical-json-exact"},
            ),
            context_digest=cpu_context_digest,
            precondition_digests=(precondition,),
            invariant_digests=(invariant,),
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
            case_payload={"receipt_digest": canonical_value_digest(raw_receipt)},
            source_observation={"value": expected_value},
            target_observation={"value": expected_value},
        )
        assert bridge_comparison.equivalent is True
        catalogue = EvidencePathCatalogue()
        catalogue.register(memory_edge)
        catalogue.register(EvidencePathEdge(
            bridge_contract,
            bridge_comparison,
            (
                RouteMetric("latency_us", "us", 5),
                RouteMetric("energy_nj", "nJ", 18),
            ),
        ))
        route_request = EvidencePathRequest(
            source=memory_edge.source,
            target=cpu_request_ref,
            context_digest=cpu_context_digest,
            accepted_context_digests=tuple(sorted({
                memory_edge.contract.context_digest,
                cpu_context_digest,
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
                precondition,
                *memory_edge.contract.precondition_digests,
            })),
            satisfied_invariants=tuple(sorted({
                invariant,
                *memory_edge.contract.invariant_digests,
            })),
            minimum_evidence=EvidenceStrength.PAIRED_CASE,
            max_hops=3,
            max_expansions=12,
        )
        route = EvidencePathResolver().resolve(
            catalogue,
            route_request,
            receiver,
            authority_pid,
        )
        assert route.status is EvidencePathStatus.FOUND
        assert route_request.target == cpu_request_ref

        # The DAG is part of the same combined checkpoint as the receiver and
        # route: the memory receipt is committed, while the exact CPU request
        # remains the one ready node across every transaction crash cut.
        memory_context_digest = canonical_value_digest({
            "operation": memory_event.request.operation,
            "resource": memory_event.request.resource,
            "payload": memory_event.request.payload,
        })
        computation_dag = NavigableComputationDAG((
            ComputationNode(
                node_id="memory",
                revision=1,
                operation=memory_event.request.operation,
                resource=memory_event.request.resource,
                context_digest=memory_context_digest,
                dependencies=(),
                payload=memory_event.request.payload,
            ),
            ComputationNode(
                node_id="cpu-retry",
                revision=1,
                operation=cpu_event.request.operation,
                resource=cpu_event.request.resource,
                context_digest=cpu_context_digest,
                dependencies=("memory",),
                payload=cpu_event.request.payload,
            ),
        ))
        assert computation_dag.commit("memory", raw_receipt) is False
        assert tuple(node.node_id for node in computation_dag.ready_nodes()) == ("cpu-retry",)

        # A valid graph digest is not enough: the ready node must describe
        # this exact retry event, not merely another operation on the same CPU.
        unrelated_dag = NavigableComputationDAG((
            ComputationNode(
                node_id="memory",
                revision=1,
                operation=memory_event.request.operation,
                resource=memory_event.request.resource,
                context_digest=memory_context_digest,
                dependencies=(),
                payload=memory_event.request.payload,
            ),
            ComputationNode(
                node_id="different-cpu",
                revision=1,
                operation=cpu_event.request.operation,
                resource=cpu_event.request.resource,
                context_digest="0" * 64,
                dependencies=("memory",),
                payload={"source": "halt", "initial_registers": {}, "max_ticks": 1},
            ),
        ))
        unrelated_dag.commit("memory", raw_receipt)
        with pytest.raises(NavigableComputationCheckpointError, match="exact retry event"):
            NavigableComputationCheckpoint.capture(
                session,
                request_client,
                response_client,
                catalogue,
                route_request,
                route,
                cpu_event,
                allow_inflight=True,
                computation_dag=unrelated_dag,
            )

        checkpoint_path = tmp_path / f"{cut}.checkpoint.json"

        def stop_at_cut(stage: str) -> None:
            if stage == cut:
                captured = NavigableComputationCheckpoint.capture(
                    session,
                    request_client,
                    response_client,
                    catalogue,
                    route_request,
                    route,
                    cpu_event,
                    allow_inflight=True,
                    computation_dag=computation_dag,
                )
                NavigableComputationCheckpoint.save(captured, checkpoint_path)
                raise SimulatedCrash(stage)

        assert request_client.send(cpu_event) == 2
        with pytest.raises(SimulatedCrash, match=cut):
            session.serve_once(fault_hook=stop_at_cut)

        # The combined checkpoint is an atomic file, not an in-memory test-only object.
        persisted = NavigableComputationCheckpoint.load(checkpoint_path)
        assert persisted["state"]["version"] == 3
        assert persisted["state"]["capture_mode"] == "inflight"
        assert "computation_dag" in persisted["state"]
        committed_before_restart = initial_host.calls
        assert committed_before_restart == (0 if cut == "before_execution" else 1)

        # Drop every old stream and restore every endpoint over fresh TCP pairs.
        for transport in transports:
            if not transport.closed:
                transport.close()
        (
            replacement_transports,
            _new_client_request,
            _new_worker_request,
            _new_worker_response,
            _new_client_response,
        ) = _channels()
        (
            new_client_request_transport,
            new_worker_request_transport,
            new_worker_response_transport,
            new_client_response_transport,
        ) = replacement_transports

        def restored_factory(restored_os: HeadlessOS, restored_pid: int):
            host = _CountingHost()
            restored_hosts.append(host)
            return _router(restored_os, restored_pid, host)

        restored = NavigableComputationCheckpoint.restore(
            persisted,
            client_request_transport=new_client_request_transport,
            client_response_transport=new_client_response_transport,
            worker_request_transport=new_worker_request_transport,
            worker_response_transport=new_worker_response_transport,
            compute_host_factory=restored_factory,
        )
        assert restored.catalogue.digest == catalogue.digest
        assert restored.route_request.digest == route_request.digest
        assert restored.route_result == route.to_dict()
        assert restored.retry_event.identity == cpu_event.identity
        assert restored.computation_dag is not None
        assert restored.computation_dag.digest == computation_dag.digest
        assert restored.computation_dag.result("memory") == raw_receipt
        assert tuple(node.node_id for node in restored.computation_dag.ready_nodes()) == ("cpu-retry",)
        assert len(restored_hosts) == 1
        assert restored_hosts[0].calls == 0

        # Re-deliver a published result first, if the cut occurred after publication.
        server_response_channel = restored.session.response.channel
        if server_response_channel.pending_sequences():
            pending_result_sequence = server_response_channel.pending_sequences()[0]
            assert server_response_channel.retransmit(pending_result_sequence) is True
            first_response = _wait_for_response(restored.response_client)
            assert first_response.effect["registers"]["answer"] == expected_value + 19
            _wait_for_ack(server_response_channel, (pending_result_sequence,))

        # Retry the exact original request frame. The receiver ledger decides whether
        # to execute once or return the already-committed semantic effect.
        assert restored.request_client.channel.retransmit(2) is True
        replay_or_execution = restored.session.serve_once()
        assert replay_or_execution is not None
        assert replay_or_execution.effect["registers"]["answer"] == expected_value + 19
        assert replay_or_execution.executed is True
        assert replay_or_execution.replayed is (cut != "before_execution")

        final_response_sequence = max(server_response_channel.pending_sequences())
        returned = _wait_for_response(restored.response_client)
        assert returned.effect == replay_or_execution.effect
        assert restored.computation_dag is not None
        assert restored.computation_dag.commit("cpu-retry", replay_or_execution.effect) is False
        assert restored.computation_dag.is_complete
        assert restored.computation_dag.result("cpu-retry") == replay_or_execution.effect
        _wait_for_ack(restored.request_client.channel, (2,))
        _wait_for_ack(server_response_channel, (final_response_sequence,))
        assert restored.session.phase == "idle"

        # Exactly one backend invocation across both sides of the simulated restart.
        assert initial_host.calls + restored_hosts[0].calls == 1
        assert restored_hosts[0].calls == (1 if cut == "before_execution" else 0)
        assert restored.session.worker.operating_system.environment.kernel.journal.verify()
        translation = TransitTranslationEvidence.from_dict(
            replay_or_execution.effect["_semantic_translation"]
        )
        oracle = TransitOracleEvidence.from_dict(
            replay_or_execution.effect["_semantic_oracle"]
        )
        translation.validate_execution_result(replay_or_execution, require_oracle=True)
        assert oracle.equivalent is True
    finally:
        for transport in (*transports, *replacement_transports):
            if not transport.closed:
                transport.close()


def test_structural_memory_fans_out_to_independent_cpu_branches_and_joins_after_graph_restore() -> None:
    """Mathematics: execute a dependency DAG where shared receipt r unlocks three branches and join j only after all branch commits."""

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
        "branching-orbit",
        law,
        {0: 13, 1: 22, 2: 31, 3: 40},
        domain="integer-orbit",
        context=_CONTEXT,
    )
    admitted = receiver.structural_memory.admit(proposal.proposal_id, expected_revision=0)
    authority_pid = receiver.environment.kernel.spawn(
        "branching-transit-receiver",
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
    initial_host = _CountingHost()
    transports, request_client, request_worker, response_worker, response_client = _channels()
    worker = TransitComputeWorker(
        receiver,
        authority_pid,
        _router(receiver, authority_pid, initial_host),
    )
    session = TransitComputeSession(worker, request_worker, response_worker)

    replacement_transports: tuple[SocketTransport, ...] = ()
    try:
        coordinate = 23
        memory_payload = {
            "memory_id": "branching-orbit",
            "revision": admitted.spec.revision,
            "context": _CONTEXT,
            "coordinate": coordinate,
        }
        memory_event = HypervisorArbitrationEvent(
            "client",
            _CHANNEL,
            1,
            9201,
            HypervisorRequest(
                TRANSIT_STRUCTURAL_MEMORY_OPERATION,
                TRANSIT_STRUCTURAL_MEMORY_RESOURCE,
                memory_payload,
                frozenset({"read"}),
                frozenset(),
            ),
        )
        memory_result, _memory_response = _serve(
            session,
            request_client,
            response_client,
            request_worker,
            response_worker,
            memory_event,
            1,
        )
        memory_translation = TransitTranslationEvidence.from_dict(
            memory_result.effect["_semantic_translation"]
        )
        memory_oracle = TransitOracleEvidence.from_dict(
            memory_result.effect["_semantic_oracle"]
        )
        memory_translation.validate_execution_result(memory_result, require_oracle=True)
        assert memory_oracle.equivalent is True
        receipt = {
            key: value
            for key, value in memory_result.effect.items()
            if key not in {"_semantic_translation", "_semantic_oracle"}
        }
        expected_value = (13 + 9 * coordinate) % 251
        assert receipt["value"] == expected_value == 220

        memory_context = canonical_value_digest({
            "operation": TRANSIT_STRUCTURAL_MEMORY_OPERATION,
            "resource": TRANSIT_STRUCTURAL_MEMORY_RESOURCE,
            "payload": memory_payload,
        })
        branch_programs = {
            "plus-19": "\\n".join((
                f"set structural_value {expected_value}",
                "set offset 19",
                "add answer structural_value offset",
                "halt",
            )),
            "triple": "\\n".join((
                f"set structural_value {expected_value}",
                f"set answer {expected_value}",
                "add answer answer structural_value",
                "add answer answer structural_value",
                "halt",
            )),
            "double-plus-7": "\\n".join((
                f"set structural_value {expected_value}",
                f"set answer {expected_value}",
                "add answer answer structural_value",
                "set offset 7",
                "add answer answer offset",
                "halt",
            )),
        }
        branch_nodes = []
        for node_id, source in branch_programs.items():
            payload = {
                "source": source,
                "initial_registers": {
                    "memory_coordinate": coordinate,
                    "memory_revision": admitted.spec.revision,
                    "branch_index": len(branch_nodes),
                },
                "max_ticks": 20,
            }
            context_digest = canonical_value_digest({
                "operation": _CPU_OPERATION,
                "resource": _CPU_RESOURCE,
                "payload": payload,
            })
            branch_nodes.append(ComputationNode(
                node_id=node_id,
                revision=1,
                operation=_CPU_OPERATION,
                resource=_CPU_RESOURCE,
                context_digest=context_digest,
                dependencies=("memory",),
                payload=payload,
            ))

        join_payload = {
            "source": "HALT",
            "initial_registers": {"join_pending": 1},
            "max_ticks": 8,
        }
        join_context = canonical_value_digest({
            "operation": "join verified branch results",
            "resource": "/computation/join",
            "payload": join_payload,
        })
        graph = NavigableComputationDAG((
            ComputationNode(
                node_id="memory",
                revision=1,
                operation=TRANSIT_STRUCTURAL_MEMORY_OPERATION,
                resource=TRANSIT_STRUCTURAL_MEMORY_RESOURCE,
                context_digest=memory_context,
                dependencies=(),
                payload=memory_payload,
            ),
            *branch_nodes,
            ComputationNode(
                node_id="join",
                revision=1,
                operation="join verified branch results",
                resource="/computation/join",
                context_digest=join_context,
                dependencies=("plus-19", "triple", "double-plus-7"),
                payload=join_payload,
            ),
        ))
        graph.commit("memory", receipt)
        assert {node.node_id for node in graph.ready_nodes()} == set(branch_programs)
        assert "join" not in {node.node_id for node in graph.ready_nodes()}

        transport_sequence = 2
        event_sequence = 2

        def execute_branch(node_id: str) -> None:
            """Mathematics: map each ready DAG node to one receiver-authorized CPU event, then commit its evidence-bearing effect."""

            nonlocal transport_sequence, event_sequence
            node = next(item for item in graph.ready_nodes() if item.node_id == node_id)
            event = HypervisorArbitrationEvent(
                "client",
                _CHANNEL,
                event_sequence,
                9300 + event_sequence,
                HypervisorRequest(
                    node.operation,
                    node.resource,
                    node.payload,
                    frozenset({"execute"}),
                    frozenset(),
                ),
            )
            result, _returned = _serve(
                session,
                request_client,
                response_client,
                request_worker,
                response_worker,
                event,
                transport_sequence,
            )
            assert result.action.value == "allow"
            assert result.executed is True
            assert result.replayed is False
            translation = TransitTranslationEvidence.from_dict(
                result.effect["_semantic_translation"]
            )
            oracle = TransitOracleEvidence.from_dict(
                result.effect["_semantic_oracle"]
            )
            translation.validate_execution_result(result, require_oracle=True)
            assert oracle.equivalent is True
            assert result.effect["registers"]["answer"] == {
                "plus-19": 239,
                "triple": 660,
                "double-plus-7": 447,
            }[node_id]
            assert graph.commit(node_id, result.effect) is False
            transport_sequence += 1
            event_sequence += 1

        # Execute two independent branches, then serialize the graph while the
        # third branch remains ready and the join remains causally blocked.
        execute_branch("plus-19")
        execute_branch("triple")
        assert {node.node_id for node in graph.ready_nodes()} == {"double-plus-7"}
        assert not graph.is_complete
        checkpoint = json.loads(json.dumps(graph.snapshot(), sort_keys=True))
        restored_graph = NavigableComputationDAG.from_snapshot(checkpoint)
        assert restored_graph.digest == graph.digest
        assert restored_graph.committed_nodes == graph.committed_nodes
        assert {node.node_id for node in restored_graph.ready_nodes()} == {"double-plus-7"}
        graph = restored_graph

        execute_branch("double-plus-7")
        assert {node.node_id for node in graph.ready_nodes()} == {"join"}

        branch_values = {
            "plus-19": graph.result("plus-19")["registers"]["answer"],
            "triple": graph.result("triple")["registers"]["answer"],
            "double-plus-7": graph.result("double-plus-7")["registers"]["answer"],
        }
        joined_total = sum(branch_values.values())
        assert branch_values == {
            "plus-19": 239,
            "triple": 660,
            "double-plus-7": 447,
        }
        assert joined_total == 1346
        join_source = "\\n".join((
            f"set branch_a {branch_values['plus-19']}",
            f"set branch_b {branch_values['triple']}",
            f"set branch_c {branch_values['double-plus-7']}",
            "add partial branch_a branch_b",
            "add total partial branch_c",
            "halt",
        ))
        join_payload = {
            "source": join_source,
            "initial_registers": {"branch_count": 3},
            "max_ticks": 20,
        }
        # Revise the still-pending join node from its placeholder description
        # to the exact CPU operation formed from all three committed branch results.
        new_join = ComputationNode(
            node_id="join",
            revision=2,
            operation=_CPU_OPERATION,
            resource=_CPU_RESOURCE,
            context_digest=canonical_value_digest({
                "operation": _CPU_OPERATION,
                "resource": _CPU_RESOURCE,
                "payload": join_payload,
            }),
            dependencies=("plus-19", "triple", "double-plus-7"),
            payload=join_payload,
        )
        assert graph.revise_node(new_join) == new_join.digest
        join_event = HypervisorArbitrationEvent(
            "client",
            _CHANNEL,
            event_sequence,
            9300 + event_sequence,
            HypervisorRequest(
                _CPU_OPERATION,
                _CPU_RESOURCE,
                join_payload,
                frozenset({"execute"}),
                frozenset(),
            ),
        )
        join_result, _join_returned = _serve(
            session,
            request_client,
            response_client,
            request_worker,
            response_worker,
            join_event,
            transport_sequence,
        )
        assert join_result.effect["registers"]["total"] == joined_total
        assert join_result.effect["registers"]["total"] == 1346
        assert graph.commit("join", join_result.effect) is False
        assert graph.is_complete
        assert set(graph.lineage("join")) == {
            "memory", "plus-19", "triple", "double-plus-7"
        }
        assert graph.commit("join", join_result.effect) is True
        with pytest.raises(ComputationDAGError, match="conflicting result"):
            graph.commit("join", {"registers": {"total": -1}})
        final_snapshot = graph.snapshot()
        final_restored = NavigableComputationDAG.from_snapshot(
            json.loads(json.dumps(final_snapshot))
        )
        assert final_restored.is_complete
        assert final_restored.digest == graph.digest
        assert final_restored.result("join")["registers"]["total"] == 1346
        assert initial_host.calls == 4
        assert session.phase == "idle"
        assert receiver.environment.kernel.journal.verify()
    finally:
        for transport in (*transports, *replacement_transports):
            if not transport.closed:
                transport.close()


def test_navigable_computation_dag_resumes_only_unfinished_branches_after_crash() -> None:
    """Mathematics: restore G and receiver state after branch B commits but before response; replay B, execute only C, then join A+B+C."""

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
        "multi-branch-recovery",
        law,
        {0: 13, 1: 22, 2: 31, 3: 40},
        domain="integer-orbit",
        context=_CONTEXT,
    )
    admitted = receiver.structural_memory.admit(proposal.proposal_id, expected_revision=0)
    authority_pid = receiver.environment.kernel.spawn(
        "multi-branch-recovery-receiver",
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

    original_host = _CountingHost()
    transports, request_client, request_worker, response_worker, response_client = _channels()
    session = TransitComputeSession(
        TransitComputeWorker(
            receiver,
            authority_pid,
            _router(receiver, authority_pid, original_host),
        ),
        request_worker,
        response_worker,
    )
    replacement_transports: tuple[SocketTransport, ...] = ()
    restored_hosts: list[_CountingHost] = []

    class SimulatedCrash(RuntimeError):
        """Represent abrupt loss at the selected Transit commit boundary."""

    try:
        coordinate = 23
        memory_payload = {
            "memory_id": "multi-branch-recovery",
            "revision": admitted.spec.revision,
            "context": _CONTEXT,
            "coordinate": coordinate,
        }
        memory_event = HypervisorArbitrationEvent(
            "client",
            _CHANNEL,
            1,
            9401,
            HypervisorRequest(
                TRANSIT_STRUCTURAL_MEMORY_OPERATION,
                TRANSIT_STRUCTURAL_MEMORY_RESOURCE,
                memory_payload,
                frozenset({"read"}),
                frozenset(),
            ),
        )
        memory_result, _ = _serve(
            session, request_client, response_client,
            request_worker, response_worker, memory_event, 1,
        )
        receipt = {
            key: value
            for key, value in memory_result.effect.items()
            if key not in {"_semantic_translation", "_semantic_oracle"}
        }
        expected_value = (13 + 9 * coordinate) % 251
        assert receipt["value"] == expected_value == 220
        memory_translation = TransitTranslationEvidence.from_dict(
            memory_result.effect["_semantic_translation"]
        )
        memory_oracle = TransitOracleEvidence.from_dict(
            memory_result.effect["_semantic_oracle"]
        )
        memory_translation.validate_execution_result(memory_result, require_oracle=True)
        assert memory_oracle.equivalent is True
        memory_edge = EvidencePathEdge.from_execution_result(
            memory_result,
            (
                RouteMetric("latency_us", "us", 7),
                RouteMetric("energy_nj", "nJ", 35),
            ),
        )

        branch_programs = {
            "branch-a": "\\n".join((
                f"set structural_value {expected_value}",
                "set offset 19",
                "add answer structural_value offset",
                "halt",
            )),
            "branch-b": "\\n".join((
                f"set structural_value {expected_value}",
                f"set answer {expected_value}",
                "add answer answer structural_value",
                "add answer answer structural_value",
                "halt",
            )),
            "branch-c": "\\n".join((
                f"set structural_value {expected_value}",
                f"set answer {expected_value}",
                "add answer answer structural_value",
                "set offset 7",
                "add answer answer offset",
                "halt",
            )),
        }
        branch_payloads = {
            node_id: {
                "source": source,
                "initial_registers": {
                    "memory_coordinate": coordinate,
                    "memory_revision": admitted.spec.revision,
                },
                "max_ticks": 20,
            }
            for node_id, source in branch_programs.items()
        }
        branch_contexts = {
            node_id: canonical_value_digest({
                "operation": _CPU_OPERATION,
                "resource": _CPU_RESOURCE,
                "payload": payload,
            })
            for node_id, payload in branch_payloads.items()
        }
        branch_events = {
            node_id: HypervisorArbitrationEvent(
                "client",
                _CHANNEL,
                event_sequence,
                9400 + event_sequence,
                HypervisorRequest(
                    _CPU_OPERATION,
                    _CPU_RESOURCE,
                    branch_payloads[node_id],
                    frozenset({"execute"}),
                    frozenset(),
                ),
            )
            for node_id, event_sequence in (
                ("branch-a", 2),
                ("branch-b", 3),
                ("branch-c", 4),
            )
        }

        memory_context = canonical_value_digest({
            "operation": memory_event.request.operation,
            "resource": memory_event.request.resource,
            "payload": memory_payload,
        })
        join_placeholder = {
            "source": "HALT",
            "initial_registers": {"join_pending": 1},
            "max_ticks": 8,
        }
        join_placeholder_context = canonical_value_digest({
            "operation": "join verified branch results",
            "resource": "/computation/join",
            "payload": join_placeholder,
        })
        graph = NavigableComputationDAG((
            ComputationNode(
                "memory", 1, TRANSIT_STRUCTURAL_MEMORY_OPERATION,
                TRANSIT_STRUCTURAL_MEMORY_RESOURCE, memory_context, (), memory_payload,
            ),
            *(
                ComputationNode(
                    node_id,
                    1,
                    _CPU_OPERATION,
                    _CPU_RESOURCE,
                    branch_contexts[node_id],
                    ("memory",),
                    branch_payloads[node_id],
                )
                for node_id in ("branch-a", "branch-b", "branch-c")
            ),
            ComputationNode(
                "join", 1, "join verified branch results", "/computation/join",
                join_placeholder_context, ("branch-a", "branch-b", "branch-c"),
                join_placeholder,
            ),
        ))
        assert graph.commit("memory", receipt) is False
        assert {node.node_id for node in graph.ready_nodes()} == {
            "branch-a", "branch-b", "branch-c"
        }

        branch_a_result, _ = _serve(
            session, request_client, response_client,
            request_worker, response_worker, branch_events["branch-a"], 2,
        )
        assert branch_a_result.effect["registers"]["answer"] == 239
        branch_a_translation = TransitTranslationEvidence.from_dict(
            branch_a_result.effect["_semantic_translation"]
        )
        branch_a_oracle = TransitOracleEvidence.from_dict(
            branch_a_result.effect["_semantic_oracle"]
        )
        branch_a_translation.validate_execution_result(branch_a_result, require_oracle=True)
        assert branch_a_oracle.equivalent is True
        assert graph.commit("branch-a", branch_a_result.effect) is False
        assert original_host.calls == 1
        assert {node.node_id for node in graph.ready_nodes()} == {"branch-b", "branch-c"}
        assert "join" not in {node.node_id for node in graph.ready_nodes()}

        # Build the exact evidence route to branch B, the operation interrupted
        # after its hypervisor execution commit but before response publication.
        branch_b_event = branch_events["branch-b"]
        authorized_b = receiver.hypervisor_authorize_event(authority_pid, branch_b_event)
        branch_b_ref = RepresentationRef.from_payload(
            "mailcpu.transit.authorized-event", 1, authorized_b.to_dict()
        )
        branch_b_context = branch_contexts["branch-b"]
        handoff_precondition = canonical_value_digest({
            "precondition": "shared Structural Memory receipt is committed and oracle verified"
        })
        handoff_invariant = canonical_value_digest({
            "invariant": "branch B input equals the exact shared receipt value"
        })
        handoff = TranslationContract(
            contract_id="mailcpu.multibranch-recovery.receipt-to-branch-b",
            revision=1,
            source=memory_edge.target,
            target=branch_b_ref,
            mapping=RepresentationRef.from_payload(
                "mailcpu.multibranch-recovery.branch-b-adapter",
                1,
                {
                    "receipt_digest": canonical_value_digest(receipt),
                    "request_digest": canonical_value_digest(branch_b_event.to_dict()),
                },
            ),
            observation=ObservationContract.from_definition(
                "mailcpu.multibranch-recovery.branch-b-operand",
                1,
                {"fields": ["value"], "comparison": "canonical-json-exact"},
            ),
            context_digest=branch_b_context,
            precondition_digests=(handoff_precondition,),
            invariant_digests=(handoff_invariant,),
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
        handoff_comparison = compare_projected_observations(
            handoff,
            case_payload={"receipt_digest": canonical_value_digest(receipt)},
            source_observation={"value": expected_value},
            target_observation={"value": expected_value},
        )
        assert handoff_comparison.equivalent is True
        catalogue = EvidencePathCatalogue()
        catalogue.register(memory_edge)
        catalogue.register(EvidencePathEdge(
            handoff,
            handoff_comparison,
            (
                RouteMetric("latency_us", "us", 5),
                RouteMetric("energy_nj", "nJ", 18),
            ),
        ))
        route_request = EvidencePathRequest(
            source=memory_edge.source,
            target=branch_b_ref,
            context_digest=branch_b_context,
            accepted_context_digests=tuple(sorted({
                memory_edge.contract.context_digest,
                branch_b_context,
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
                handoff_precondition,
                *memory_edge.contract.precondition_digests,
            })),
            satisfied_invariants=tuple(sorted({
                handoff_invariant,
                *memory_edge.contract.invariant_digests,
            })),
            minimum_evidence=EvidenceStrength.PAIRED_CASE,
            max_hops=3,
            max_expansions=12,
        )
        route = EvidencePathResolver().resolve(
            catalogue, route_request, receiver, authority_pid
        )
        assert route.status is EvidencePathStatus.FOUND

        # Branch B's reliable request is in flight. The execution ledger commits
        # it, then the injected cut prevents publication/ACK.
        checkpoint_path = "multibranch-after-execution-commit.json"

        def stop_after_commit(stage: str) -> None:
            if stage == "after_execution_commit":
                checkpoint = NavigableComputationCheckpoint.capture(
                    session,
                    request_client,
                    response_client,
                    catalogue,
                    route_request,
                    route,
                    branch_b_event,
                    allow_inflight=True,
                    computation_dag=graph,
                )
                NavigableComputationCheckpoint.save(checkpoint, checkpoint_path)
                raise SimulatedCrash(stage)

        assert request_client.send(branch_b_event) == 3
        with pytest.raises(SimulatedCrash, match="after_execution_commit"):
            session.serve_once(fault_hook=stop_after_commit)
        assert original_host.calls == 2
        assert session.phase == "request-ready"

        checkpoint = NavigableComputationCheckpoint.load(checkpoint_path)
        assert checkpoint["state"]["version"] == 3
        assert checkpoint["state"]["capture_mode"] == "inflight"

        # Simulate the whole requester/receiver process replacement: close all
        # original sockets, then reconstruct every endpoint over new streams.
        for transport in transports:
            if not transport.closed:
                transport.close()
        (
            replacement_transports,
            _new_request_client,
            _new_request_worker,
            _new_response_worker,
            _new_response_client,
        ) = _channels()
        new_client_request_transport, new_worker_request_transport, new_worker_response_transport, new_client_response_transport = replacement_transports

        def restored_factory(restored_os: HeadlessOS, restored_pid: int):
            host = _CountingHost()
            restored_hosts.append(host)
            return _router(restored_os, restored_pid, host)

        restored = NavigableComputationCheckpoint.restore(
            checkpoint,
            client_request_transport=new_client_request_transport,
            client_response_transport=new_client_response_transport,
            worker_request_transport=new_worker_request_transport,
            worker_response_transport=new_worker_response_transport,
            compute_host_factory=restored_factory,
        )
        restored_graph = restored.computation_dag
        assert restored_graph is not None
        assert restored_graph.digest == graph.digest
        assert restored_graph.committed_nodes == ("branch-a", "memory")
        assert set(node.node_id for node in restored_graph.ready_nodes()) == {
            "branch-b", "branch-c"
        }
        assert "join" not in {node.node_id for node in restored_graph.ready_nodes()}
        assert restored.retry_event.identity == branch_b_event.identity
        assert restored.route_result == route.to_dict()
        assert len(restored_hosts) == 1
        assert restored_hosts[0].calls == 0

        # Re-deliver branch B's exact reliable frame. The receiver execution
        # ledger returns the committed effect and evidence without a backend call.
        assert restored.request_client.channel.retransmit(3) is True
        replay_b = restored.session.serve_once()
        assert replay_b is not None
        assert replay_b.executed is True
        assert replay_b.replayed is True
        returned_b = _wait_for_response(restored.response_client)
        assert returned_b.effect == replay_b.effect
        _wait_for_ack(restored.request_client.channel, (3,))
        _wait_for_ack(restored.session.response.channel, (3,))
        assert restored.session.phase == "idle"
        replay_b_translation = TransitTranslationEvidence.from_dict(
            replay_b.effect["_semantic_translation"]
        )
        replay_b_oracle = TransitOracleEvidence.from_dict(
            replay_b.effect["_semantic_oracle"]
        )
        assert replay_b_translation.validate_execution_result(replay_b, require_oracle=True)
        assert replay_b_oracle.equivalent is True
        assert restored_hosts[0].calls == 0
        assert restored_graph.commit("branch-b", replay_b.effect) is False
        assert set(node.node_id for node in restored_graph.ready_nodes()) == {"branch-c"}
        assert restored_graph.result("branch-a") == branch_a_result.effect

        # Only branch C is still executable as new work. Branch A is not resent,
        # and branch B is not re-entered after its semantic replay.
        branch_c_result, _ = _serve(
            restored.session,
            restored.request_client,
            restored.response_client,
            restored.session.request,
            restored.session.response,
            branch_events["branch-c"],
            4,
        )
        assert branch_c_result.effect["registers"]["answer"] == 447
        branch_c_translation = TransitTranslationEvidence.from_dict(
            branch_c_result.effect["_semantic_translation"]
        )
        branch_c_oracle = TransitOracleEvidence.from_dict(
            branch_c_result.effect["_semantic_oracle"]
        )
        branch_c_translation.validate_execution_result(branch_c_result, require_oracle=True)
        assert branch_c_oracle.equivalent is True
        assert restored_graph.commit("branch-c", branch_c_result.effect) is False
        assert {node.node_id for node in restored_graph.ready_nodes()} == {"join"}

        branch_values = {
            node_id: restored_graph.result(node_id)["registers"]["answer"]
            for node_id in ("branch-a", "branch-b", "branch-c")
        }
        assert branch_values == {"branch-a": 239, "branch-b": 660, "branch-c": 447}
        join_source = "\\n".join((
            f"set branch_a {branch_values['branch-a']}",
            f"set branch_b {branch_values['branch-b']}",
            f"set branch_c {branch_values['branch-c']}",
            "add partial branch_a branch_b",
            "add total partial branch_c",
            "halt",
        ))
        join_payload = {
            "source": join_source,
            "initial_registers": {"branch_count": 3},
            "max_ticks": 20,
        }
        join_node = ComputationNode(
            "join",
            2,
            _CPU_OPERATION,
            _CPU_RESOURCE,
            canonical_value_digest({
                "operation": _CPU_OPERATION,
                "resource": _CPU_RESOURCE,
                "payload": join_payload,
            }),
            ("branch-a", "branch-b", "branch-c"),
            join_payload,
        )
        assert restored_graph.revise_node(join_node) == join_node.digest
        join_event = HypervisorArbitrationEvent(
            "client",
            _CHANNEL,
            5,
            9405,
            HypervisorRequest(
                _CPU_OPERATION,
                _CPU_RESOURCE,
                join_payload,
                frozenset({"execute"}),
                frozenset(),
            ),
        )
        join_result, _ = _serve(
            restored.session,
            restored.request_client,
            restored.response_client,
            restored.session.request,
            restored.session.response,
            join_event,
            5,
        )
        assert join_result.effect["registers"]["total"] == 1346
        assert restored_graph.commit("join", join_result.effect) is False
        assert restored_graph.is_complete
        assert set(restored_graph.lineage("join")) == {
            "memory", "branch-a", "branch-b", "branch-c"
        }
        assert restored_graph.commit("join", join_result.effect) is True

        final_checkpoint = NavigableComputationCheckpoint.capture(
            restored.session,
            restored.request_client,
            restored.response_client,
            restored.catalogue,
            restored.route_request,
            EvidencePathResolver().resolve(
                restored.catalogue,
                restored.route_request,
                restored.session.worker.operating_system,
                restored.session.worker.authority_pid,
            ),
            restored.retry_event,
            computation_dag=restored_graph,
        )
        assert final_checkpoint["state"]["version"] == 3
        final_graph = NavigableComputationDAG.from_snapshot(
            final_checkpoint["state"]["computation_dag"]
        )
        assert final_graph.is_complete
        assert final_graph.result("join")["registers"]["total"] == 1346

        # Across the restart, A ran once before the cut, B ran once before the
        # cut and was replayed afterward, C ran once afterward, and the join
        # ran once. No committed sibling is executed a second time.
        assert original_host.calls == 2
        assert restored_hosts[0].calls == 2
        assert original_host.calls + restored_hosts[0].calls == 4
        assert restored.session.worker.operating_system.environment.kernel.journal.verify()
    finally:
        for transport in (*transports, *replacement_transports):
            if not transport.closed:
                transport.close()
