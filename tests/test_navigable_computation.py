"""Vertical integration experiment: Structural Memory -> Transit CPU -> evidence route."""

from __future__ import annotations

import time
from dataclasses import replace

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
    EvidencePathBlockerCode,
    EvidencePathCatalogue,
    EvidencePathError,
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
_CONTEXT = {"tenant": "alpha", "partition": 4}


def _tcp_pair(local: str, peer: str) -> tuple[SocketTransport, SocketTransport]:
    """Create reciprocal test transports over one loopback TCP connection."""
    listener = SocketTransport.listen("127.0.0.1", 0)
    port = listener.getsockname()[1]
    local_transport = SocketTransport.connect("127.0.0.1", port, local, peer)
    peer_transport = SocketTransport.accept(listener, peer, local)
    listener.close()
    return local_transport, peer_transport


def _wait_for_response(channel: HypervisorOperationResultChannel):
    """Wait for one typed result under a finite test deadline."""
    deadline = time.monotonic() + 3.0
    result = None
    while result is None and time.monotonic() < deadline:
        result = channel.receive()
        if result is None:
            time.sleep(0.005)
    assert result is not None, "navigable-computation result did not arrive"
    return result


def _wait_for_ack(channel: ReliableChannel, expected: tuple[int, ...]) -> None:
    """Require the exact acknowledgement cursor before the next experiment stage."""
    deadline = time.monotonic() + 3.0
    actual: tuple[int, ...] = ()
    while actual != expected and time.monotonic() < deadline:
        actual = channel.process_ack()
        if actual != expected:
            time.sleep(0.005)
    assert actual == expected


def _serve_and_ack(
    session: TransitComputeSession,
    request_client: HypervisorOperationChannel,
    response_client: HypervisorOperationResultChannel,
    request_worker: HypervisorOperationChannel,
    response_worker: HypervisorOperationResultChannel,
    event: HypervisorArbitrationEvent,
    transport_sequence: int,
):
    """Send, execute, receive, and acknowledge one operation through Transit."""
    assert request_client.send(event) == transport_sequence
    deadline = time.monotonic() + 3.0
    served = None
    while served is None and time.monotonic() < deadline:
        served = session.serve_once()
        if served is None:
            time.sleep(0.005)
    assert served is not None, "Transit worker did not serve the operation"

    returned = _wait_for_response(response_client)
    assert returned.effect == served.effect
    _wait_for_ack(request_client.channel, (transport_sequence,))
    _wait_for_ack(response_worker.channel, (transport_sequence,))
    assert session.phase == "idle"
    return served


class _CountingComputeHost(TransitComputeHost):
    """Count actual backend invocations independently of semantic replays."""

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def handle(self, event: HypervisorArbitrationEvent) -> dict[str, object]:
        self.calls += 1
        return super().handle(event)


def test_structural_memory_value_navigates_into_oracle_checked_transit_computation():
    """A verified memory coordinate becomes a CPU operand and a two-edge route."""
    operating_system = HeadlessOS(
        structural_memory_admission_policy=lambda proposal: proposal.spec.domain == "integer-orbit"
    )
    law = Law(
        family="int",
        params={"x0": 7, "step": 5, "mod": 97},
        order=1,
        verdict="GROUND",
    )
    proposal = operating_system.structural_memory.propose(
        "navigable-orbit",
        law,
        {0: 7, 1: 12, 2: 17, 3: 22},
        domain="integer-orbit",
        context=_CONTEXT,
    )
    version = operating_system.structural_memory.admit(
        proposal.proposal_id,
        expected_revision=0,
    )

    authority_pid = operating_system.environment.kernel.spawn(
        "navigable-computation-receiver",
        capabilities=(
            Capability(TRANSIT_STRUCTURAL_MEMORY_RESOURCE, frozenset({"read"})),
            Capability(_CPU_RESOURCE, frozenset({"execute"})),
        ),
        parent_pid=operating_system.environment.init_pid,
    )
    operating_system.hypervisor.policy = HypervisorPolicy(
        review_confidence=0.0,
        automatic_confidence=0.0,
        destructive_confidence=0.0,
        danger_review_probability=1.0,
        embedding_review_confidence=1.0,
    )

    compute_host = _CountingComputeHost()
    router = TransitBackendRouter(compute_host)
    router.register_backend(TransitStructuralMemoryHost(operating_system, authority_pid))
    worker = TransitComputeWorker(operating_system, authority_pid, router)

    request_client_transport, request_worker_transport = _tcp_pair("client", "worker")
    response_worker_transport, response_client_transport = _tcp_pair("worker", "client")
    reliability = ReliabilityPolicy(lease_ticks=1, max_attempts=3, window_size=4)
    request_client = HypervisorOperationChannel(
        ReliableChannel(request_client_transport, "client", "worker", "navigable.job", reliability)
    )
    request_worker = HypervisorOperationChannel(
        ReliableChannel(
            request_worker_transport,
            "worker",
            "worker",
            "navigable.job",
            reliability,
            peer="client",
        )
    )
    response_worker = HypervisorOperationResultChannel(
        ReliableChannel(response_worker_transport, "worker", "client", "navigable.result", reliability),
        "client",
        "navigable.job",
    )
    response_client = HypervisorOperationResultChannel(
        ReliableChannel(
            response_client_transport,
            "client",
            "client",
            "navigable.result",
            reliability,
            peer="worker",
        ),
        "client",
        "navigable.job",
    )
    session = TransitComputeSession(worker, request_worker, response_worker)

    try:
        # Stage 1: ask the receiver to resolve one exact coordinate from its
        # admitted immutable revision. The requester supplies no grant.
        coordinate = 17
        memory_event = HypervisorArbitrationEvent(
            "client",
            "navigable.job",
            1,
            1001,
            HypervisorRequest(
                TRANSIT_STRUCTURAL_MEMORY_OPERATION,
                TRANSIT_STRUCTURAL_MEMORY_RESOURCE,
                {
                    "memory_id": "navigable-orbit",
                    "revision": version.spec.revision,
                    "context": _CONTEXT,
                    "coordinate": coordinate,
                },
                frozenset({"read"}),
                frozenset(),
            ),
        )
        memory_result = _serve_and_ack(
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
        memory_oracle = TransitOracleEvidence.from_dict(
            memory_result.effect["_semantic_oracle"]
        )
        memory_translation = TransitTranslationEvidence.from_dict(
            memory_result.effect["_semantic_translation"]
        )
        memory_translation.validate_execution_result(memory_result, require_oracle=True)
        assert memory_oracle.equivalent is True
        assert memory_oracle.work_units <= memory_oracle.work_limit
        memory_edge = EvidencePathEdge.from_execution_result(
            memory_result,
            (
                RouteMetric("latency_us", "us", 6),
                RouteMetric("energy_nj", "nJ", 30),
            ),
        )
        assert memory_edge.evidence_strength is EvidenceStrength.INDEPENDENT_ORACLE

        raw_memory_receipt = {
            key: value
            for key, value in memory_result.effect.items()
            if key not in {"_semantic_translation", "_semantic_oracle"}
        }
        assert raw_memory_receipt["memory_id"] == "navigable-orbit"
        assert raw_memory_receipt["revision"] == version.spec.revision
        assert raw_memory_receipt["coordinate"] == coordinate
        expected_memory_value = (7 + 5 * coordinate) % 97
        assert raw_memory_receipt["value"] == expected_memory_value
        assert raw_memory_receipt["spec_digest"] == version.spec.digest
        assert raw_memory_receipt["certificate_digest"] == version.certificate.digest
        assert raw_memory_receipt["context_digest"] == version.spec.context_digest

        # Stage 2: compile the returned value into a bounded CPU program.
        # The literal is taken from the verified receipt, not recomputed by
        # the sender from the original law.
        embedded_value = raw_memory_receipt["value"]
        cpu_source = "\n".join(
            (
                f"set memory_value {embedded_value}",
                "set offset 8",
                "add answer memory_value offset",
                "halt",
            )
        )
        cpu_event = HypervisorArbitrationEvent(
            "client",
            "navigable.job",
            2,
            1002,
            HypervisorRequest(
                _CPU_OPERATION,
                _CPU_RESOURCE,
                {
                    "source": cpu_source,
                    "initial_registers": {
                        "memory_coordinate": coordinate,
                        "memory_revision": version.spec.revision,
                    },
                    "max_ticks": 16,
                },
                frozenset({"execute"}),
                frozenset(),
            ),
        )
        cpu_result = _serve_and_ack(
            session,
            request_client,
            response_client,
            request_worker,
            response_worker,
            cpu_event,
            2,
        )
        assert cpu_result.action.value == "allow"
        assert cpu_result.domain is HypervisorDomain.CPU
        assert cpu_result.executed is True
        assert cpu_result.replayed is False
        assert cpu_result.effect["registers"]["memory_value"] == expected_memory_value
        assert cpu_result.effect["registers"]["answer"] == expected_memory_value + 8
        assert compute_host.calls == 1

        cpu_translation = TransitTranslationEvidence.from_dict(
            cpu_result.effect["_semantic_translation"]
        )
        cpu_oracle = TransitOracleEvidence.from_dict(cpu_result.effect["_semantic_oracle"])
        cpu_translation.validate_execution_result(cpu_result, require_oracle=True)
        assert cpu_oracle.equivalent is True
        assert cpu_oracle.work_units <= cpu_oracle.work_limit

        # Stage 3: make the handoff itself an exact, content-addressed
        # translation edge: structural receipt -> authorized CPU request.
        # The following edge is ingested only from the receiver-committed
        # execution result and carries the independent CPU oracle evidence.
        memory_ref = memory_edge.target
        assert memory_ref == memory_translation.contract.target
        cpu_request_ref = cpu_translation.contract.source
        cpu_result_ref = cpu_translation.contract.target

        bridge_precondition = canonical_value_digest(
            {"experiment_precondition": "structural receipt has independent oracle"}
        )
        bridge_invariant = canonical_value_digest(
            {"experiment_invariant": "CPU immediate equals structural receipt value"}
        )
        bridge_contract = TranslationContract(
            contract_id="mailcpu.experiment.structural-memory-to-cpu",
            revision=1,
            source=memory_ref,
            target=cpu_request_ref,
            mapping=RepresentationRef.from_payload(
                "mailcpu.experiment.mapping",
                1,
                {
                    "adapter": "embed-verified-structural-value-as-cpu-immediate.v1",
                    "memory_receipt_digest": canonical_value_digest(raw_memory_receipt),
                    "cpu_request_digest": canonical_value_digest(cpu_event.to_dict()),
                    "operand": "memory_value",
                },
            ),
            observation=ObservationContract.from_definition(
                "mailcpu.experiment.embedded-memory-value",
                1,
                {"visible_fields": ["value"], "comparison": "canonical-json-exact"},
            ),
            context_digest=cpu_translation.contract.context_digest,
            precondition_digests=(bridge_precondition,),
            invariant_digests=(bridge_invariant,),
            resource_bounds=(
                ResourceBound("latency_us", 8, "us"),
                ResourceBound("energy_nj", 32, "nJ"),
            ),
            authority_requirements=(
                CapabilityRequirement(TRANSIT_STRUCTURAL_MEMORY_RESOURCE, ("read",)),
                CapabilityRequirement(_CPU_RESOURCE, ("execute",)),
            ),
            effect_class=EffectClass.PURE,
            replay_class=ReplayClass.DETERMINISTIC,
        )
        source_observation = {"value": raw_memory_receipt["value"]}
        # The generated assembly contains one deterministic SET immediate.
        immediate_line = next(
            line for line in cpu_source.splitlines() if line.startswith("set memory_value ")
        )
        target_observation = {"value": int(immediate_line.split()[2])}
        bridge_comparison = compare_projected_observations(
            bridge_contract,
            case_payload={
                "memory_receipt_digest": canonical_value_digest(raw_memory_receipt),
                "cpu_request_digest": canonical_value_digest(cpu_event.to_dict()),
            },
            source_observation=source_observation,
            target_observation=target_observation,
        )
        assert bridge_comparison.equivalent is True
        bridge_edge = EvidencePathEdge(
            contract=bridge_contract,
            comparison=bridge_comparison,
            costs=(
                RouteMetric("latency_us", "us", 4),
                RouteMetric("energy_nj", "nJ", 12),
            ),
        )
        cpu_edge = EvidencePathEdge.from_execution_result(
            cpu_result,
            (
                RouteMetric("latency_us", "us", 18),
                RouteMetric("energy_nj", "nJ", 240),
            ),
        )
        assert cpu_edge.source == cpu_request_ref
        assert cpu_edge.target == cpu_result_ref
        assert cpu_edge.evidence_strength is EvidenceStrength.INDEPENDENT_ORACLE

        catalogue = EvidencePathCatalogue()
        memory_edge_id = catalogue.register(memory_edge)
        bridge_id = catalogue.register(bridge_edge)
        cpu_edge_id = catalogue.register(cpu_edge)
        restored_catalogue = EvidencePathCatalogue.from_dict(catalogue.to_dict())
        assert restored_catalogue.digest == catalogue.digest

        route_request = EvidencePathRequest(
            source=memory_edge.source,
            target=cpu_result_ref,
            context_digest=cpu_translation.contract.context_digest,
            accepted_context_digests=tuple(sorted({
                memory_edge.contract.context_digest,
                bridge_contract.context_digest,
                cpu_translation.contract.context_digest,
            })),
            metric_order=(
                RouteMetricKey("latency_us", "us"),
                RouteMetricKey("energy_nj", "nJ"),
            ),
            resource_ceilings=(
                RouteMetric("latency_us", "us", 40),
                RouteMetric("energy_nj", "nJ", 400),
            ),
            satisfied_preconditions=(
                bridge_precondition,
                *cpu_translation.contract.precondition_digests,
            ),
            satisfied_invariants=(
                bridge_invariant,
                *cpu_translation.contract.invariant_digests,
            ),
            minimum_evidence=EvidenceStrength.PAIRED_CASE,
            max_hops=4,
            max_expansions=16,
        )
        resolver = EvidencePathResolver()
        # Without an explicit operation-context set, the memory edge is
        # blocked rather than silently treated as having the CPU context.
        narrow_route = resolver.resolve(
            restored_catalogue,
            replace(route_request, accepted_context_digests=()),
            operating_system,
            authority_pid,
        )
        assert narrow_route.status is EvidencePathStatus.BLOCKED
        assert any(
            blocker.code is EvidencePathBlockerCode.CONTEXT_MISMATCH
            for blocker in narrow_route.blockers
        )

        route = resolver.resolve(
            restored_catalogue,
            route_request,
            operating_system,
            authority_pid,
        )
        assert route.status is EvidencePathStatus.FOUND
        assert route.edge_ids == (memory_edge_id, bridge_id, cpu_edge_id)
        assert route.authoritative is False
        assert route.evidence_strength is EvidenceStrength.PAIRED_CASE
        assert {item.name: item.amount for item in route.total_costs} == {
            "latency_us": 28,
            "energy_nj": 282,
        }

        # Negative control 1: a changed immediate no longer satisfies the
        # receipt-to-request observation and cannot become a route edge.
        mismatch = compare_projected_observations(
            bridge_contract,
            case_payload={
                "memory_receipt_digest": canonical_value_digest(raw_memory_receipt),
                "cpu_request_digest": canonical_value_digest(cpu_event.to_dict()),
            },
            source_observation={"value": expected_memory_value},
            target_observation={"value": expected_memory_value + 1},
        )
        assert mismatch.equivalent is False
        with pytest.raises(EvidencePathError, match="successful check"):
            EvidencePathEdge(
                contract=bridge_contract,
                comparison=mismatch,
                costs=(
                    RouteMetric("latency_us", "us", 4),
                    RouteMetric("energy_nj", "nJ", 12),
                ),
            )

        # Negative control 2: having CPU execution authority is insufficient
        # when the first edge also requires Structural Memory read authority.
        cpu_only_pid = operating_system.environment.kernel.spawn(
            "navigable-computation-cpu-only",
            capabilities=(Capability(_CPU_RESOURCE, frozenset({"execute"})),),
            parent_pid=operating_system.environment.init_pid,
        )
        denied_route = EvidencePathResolver().resolve(
            restored_catalogue,
            route_request,
            operating_system,
            cpu_only_pid,
        )
        assert denied_route.status is EvidencePathStatus.BLOCKED
        assert any(
            blocker.code is EvidencePathBlockerCode.AUTHORITY_MISSING
            for blocker in denied_route.blockers
        )

        # Stage 4: a new transport frame carrying the same semantic CPU
        # request must replay the committed effect and its exact evidence.
        replay = _serve_and_ack(
            session,
            request_client,
            response_client,
            request_worker,
            response_worker,
            cpu_event,
            3,
        )
        assert replay.replayed is True
        assert replay.effect == cpu_result.effect
        assert compute_host.calls == 1
        replay_edge = EvidencePathEdge.from_execution_result(
            replay,
            (
                RouteMetric("latency_us", "us", 18),
                RouteMetric("energy_nj", "nJ", 240),
            ),
        )
        assert replay_edge.edge_id == cpu_edge.edge_id
        assert operating_system.environment.kernel.journal.verify()
    finally:
        for transport in (
            request_client_transport,
            request_worker_transport,
            response_worker_transport,
            response_client_transport,
        ):
            if not transport.closed:
                transport.close()
