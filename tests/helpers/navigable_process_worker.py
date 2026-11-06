"""Child-process workload for the genuine Transit crash/restart integration test.

This file is launched by a separate Python interpreter.  The prepare phase
publishes a combined checkpoint at the receiver's execution-commit boundary,
then blocks inside the fault hook until the supervisor kills this process.
The restore phase starts in a new interpreter and reconstructs the full path.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from test_navigable_computation_recovery import (  # noqa: E402
    _CHANNEL,
    _CONTEXT,
    _CPU_OPERATION,
    _CPU_RESOURCE,
    _CountingHost,
    _channels,
    _router,
    _serve,
    _wait_for_ack,
    _wait_for_response,
)
from mailcpu import (  # noqa: E402
    Capability,
    CapabilityRequirement,
    EffectClass,
    HeadlessOS,
    HypervisorArbitrationEvent,
    HypervisorDomain,
    HypervisorPolicy,
    HypervisorRequest,
    NavigableComputationCheckpoint,
    TransitComputeSession,
    TransitComputeWorker,
    TransitOracleEvidence,
    TransitTranslationEvidence,
    canonical_value_digest,
    compare_projected_observations,
)
from mailcpu.computation_dag import ComputationNode, NavigableComputationDAG  # noqa: E402
from mailcpu.evidence_path_resolver import (  # noqa: E402
    EvidencePathCatalogue,
    EvidencePathEdge,
    EvidencePathRequest,
    EvidencePathResolver,
    EvidencePathStatus,
    EvidenceStrength,
    RouteMetric,
    RouteMetricKey,
)
from mailcpu.law_certifier import Law  # noqa: E402
from mailcpu.semantic_translation import ObservationContract, ReplayClass, RepresentationRef, ResourceBound, TranslationContract  # noqa: E402
from mailcpu.transit_structural_memory import (  # noqa: E402
    TRANSIT_STRUCTURAL_MEMORY_OPERATION,
    TRANSIT_STRUCTURAL_MEMORY_RESOURCE,
)


def _write_json_durable(path: Path, value: dict[str, Any]) -> None:
    """Publish one supervisor marker only after the complete JSON record is flushed."""
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, sort_keys=True, separators=(",", ":"))
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _build_scenario():
    """Construct the same receipt→three-branch→join graph used by the recovery proof."""
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
        "process-recovery-orbit",
        law,
        {0: 13, 1: 22, 2: 31, 3: 40},
        domain="integer-orbit",
        context=_CONTEXT,
    )
    admitted = receiver.structural_memory.admit(proposal.proposal_id, expected_revision=0)
    authority_pid = receiver.environment.kernel.spawn(
        "process-recovery-receiver",
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

    host = _CountingHost()
    transports, request_client, request_worker, response_worker, response_client = _channels()
    session = TransitComputeSession(
        TransitComputeWorker(receiver, authority_pid, _router(receiver, authority_pid, host)),
        request_worker,
        response_worker,
    )

    coordinate = 23
    memory_payload = {
        "memory_id": "process-recovery-orbit",
        "revision": admitted.spec.revision,
        "context": _CONTEXT,
        "coordinate": coordinate,
    }
    memory_event = HypervisorArbitrationEvent(
        "client",
        _CHANNEL,
        1,
        9501,
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
    assert memory_result.action.value == "allow"
    assert memory_result.domain is HypervisorDomain.FILESYSTEM
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
    memory_edge = EvidencePathEdge.from_execution_result(
        memory_result,
        (
            RouteMetric("latency_us", "us", 7),
            RouteMetric("energy_nj", "nJ", 35),
        ),
    )
    memory_context = canonical_value_digest({
        "operation": memory_event.request.operation,
        "resource": memory_event.request.resource,
        "payload": memory_payload,
    })

    branch_programs = {
        "branch-a": "\n".join((
            f"set structural_value {expected_value}",
            "set offset 19",
            "add answer structural_value offset",
            "halt",
        )),
        "branch-b": "\n".join((
            f"set structural_value {expected_value}",
            f"set answer {expected_value}",
            "add answer answer structural_value",
            "add answer answer structural_value",
            "halt",
        )),
        "branch-c": "\n".join((
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
            9500 + event_sequence,
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
    join_placeholder = {
        "source": "HALT",
        "initial_registers": {"join_pending": 1},
        "max_ticks": 8,
    }
    join_context = canonical_value_digest({
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
                node_id, 1, _CPU_OPERATION, _CPU_RESOURCE,
                branch_contexts[node_id], ("memory",), branch_payloads[node_id],
            )
            for node_id in ("branch-a", "branch-b", "branch-c")
        ),
        ComputationNode(
            "join", 1, "join verified branch results", "/computation/join",
            join_context, ("branch-a", "branch-b", "branch-c"), join_placeholder,
        ),
    ))
    graph.commit("memory", receipt)

    branch_a, _ = _serve(
        session, request_client, response_client,
        request_worker, response_worker, branch_events["branch-a"], 2,
    )
    assert branch_a.effect["registers"]["answer"] == 239
    branch_a_translation = TransitTranslationEvidence.from_dict(
        branch_a.effect["_semantic_translation"]
    )
    branch_a_oracle = TransitOracleEvidence.from_dict(
        branch_a.effect["_semantic_oracle"]
    )
    branch_a_translation.validate_execution_result(branch_a, require_oracle=True)
    assert branch_a_oracle.equivalent is True
    graph.commit("branch-a", branch_a.effect)
    assert host.calls == 1
    assert {node.node_id for node in graph.ready_nodes()} == {"branch-b", "branch-c"}

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
        contract_id="mailcpu.process-recovery.receipt-to-branch-b",
        revision=1,
        source=memory_edge.target,
        target=branch_b_ref,
        mapping=RepresentationRef.from_payload(
            "mailcpu.process-recovery.branch-b-adapter",
            1,
            {
                "receipt_digest": canonical_value_digest(receipt),
                "request_digest": canonical_value_digest(branch_b_event.to_dict()),
            },
        ),
        observation=ObservationContract.from_definition(
            "mailcpu.process-recovery.branch-b-operand",
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

    return {
        "receiver": receiver,
        "authority_pid": authority_pid,
        "host": host,
        "transports": transports,
        "request_client": request_client,
        "request_worker": request_worker,
        "response_worker": response_worker,
        "response_client": response_client,
        "session": session,
        "graph": graph,
        "catalogue": catalogue,
        "route_request": route_request,
        "route": route,
        "branch_events": branch_events,
    }


def prepare(checkpoint_path: Path, ready_path: Path) -> None:
    """Commit A and B, durably save at B's commit-before-publish cut, then await supervisor termination."""
    state = _build_scenario()
    session = state["session"]
    request_client = state["request_client"]
    response_client = state["response_client"]
    branch_b_event = state["branch_events"]["branch-b"]
    assert request_client.send(branch_b_event) == 3

    def pause_at_commit(stage: str) -> None:
        if stage != "after_execution_commit":
            return
        checkpoint = NavigableComputationCheckpoint.capture(
            session,
            request_client,
            response_client,
            state["catalogue"],
            state["route_request"],
            state["route"],
            branch_b_event,
            allow_inflight=True,
            computation_dag=state["graph"],
        )
        digest = NavigableComputationCheckpoint.save(checkpoint, checkpoint_path)
        _write_json_durable(ready_path, {
            "pid": os.getpid(),
            "checkpoint_digest": digest,
            "initial_backend_calls": state["host"].calls,
            "session_phase": session.phase,
            "client_request_pending": list(request_client.channel.pending_sequences()),
            "worker_request_sequence": (
                session.request.channel.peek()[0]
                if session.request.channel.peek() is not None
                else None
            ),
            "worker_response_pending": list(session.response.channel.pending_sequences()),
            "client_response_has_message": response_client.channel.peek() is not None,
            "committed_nodes": list(state["graph"].committed_nodes),
            "ready_nodes": [node.node_id for node in state["graph"].ready_nodes()],
        })
        # Do not return to receive_and_reply_event: response publication and
        # ACK are forbidden until the supervisor hard-terminates this process.
        while True:
            time.sleep(60)

    session.serve_once(fault_hook=pause_at_commit)
    raise AssertionError("the after_execution_commit fault hook did not hold the worker")


def restore_and_finish(checkpoint_path: Path, result_path: Path) -> None:
    """Restore in a new interpreter, replay B without execution, then run C and the join."""
    checkpoint = NavigableComputationCheckpoint.load(checkpoint_path)
    (
        transports,
        _request_client_unused,
        _request_worker_unused,
        _response_worker_unused,
        _response_client_unused,
    ) = _channels()
    client_request_transport, worker_request_transport, worker_response_transport, client_response_transport = transports
    restored_hosts: list[_CountingHost] = []

    def restored_factory(restored_os: HeadlessOS, restored_pid: int):
        host = _CountingHost()
        restored_hosts.append(host)
        return _router(restored_os, restored_pid, host)

    try:
        restored = NavigableComputationCheckpoint.restore(
            checkpoint,
            client_request_transport=client_request_transport,
            client_response_transport=client_response_transport,
            worker_request_transport=worker_request_transport,
            worker_response_transport=worker_response_transport,
            compute_host_factory=restored_factory,
        )
        graph = restored.computation_dag
        assert graph is not None
        assert graph.committed_nodes == ("branch-a", "memory")
        assert {node.node_id for node in graph.ready_nodes()} == {"branch-b", "branch-c"}
        assert restored.session.phase == "request-ready"
        assert restored_hosts and restored_hosts[0].calls == 0

        # The request frame persisted in the checkpoint is retransmitted over
        # fresh sockets. The execution ledger returns B's effect as a replay.
        assert restored.request_client.channel.retransmit(3) is True
        replay_b = restored.session.serve_once()
        assert replay_b is not None and replay_b.executed is True and replay_b.replayed is True
        returned_b = _wait_for_response(restored.response_client)
        assert returned_b.effect == replay_b.effect and returned_b.replayed is True
        _wait_for_ack(restored.request_client.channel, (3,))
        _wait_for_ack(restored.session.response.channel, (3,))
        assert restored.session.phase == "idle"
        translation_b = TransitTranslationEvidence.from_dict(
            replay_b.effect["_semantic_translation"]
        )
        oracle_b = TransitOracleEvidence.from_dict(
            replay_b.effect["_semantic_oracle"]
        )
        translation_b.validate_execution_result(replay_b, require_oracle=True)
        assert oracle_b.equivalent is True
        assert restored_hosts[0].calls == 0
        graph.commit("branch-b", replay_b.effect)
        assert {node.node_id for node in graph.ready_nodes()} == {"branch-c"}

        # Only C remains genuinely unexecuted. A stays committed, B is a replay.
        branch_c_node = next(
            node for node in graph.ready_nodes() if node.node_id == "branch-c"
        )
        branch_c_event = HypervisorArbitrationEvent(
            "client",
            _CHANNEL,
            4,
            9504,
            HypervisorRequest(
                _CPU_OPERATION,
                _CPU_RESOURCE,
                branch_c_node.payload,
                frozenset({"execute"}),
                frozenset(),
            ),
        )
        branch_c, _ = _serve(
            restored.session,
            restored.request_client,
            restored.response_client,
            restored.session.request,
            restored.session.response,
            branch_c_event,
            4,
        )
        assert branch_c.effect["registers"]["answer"] == 447
        translation_c = TransitTranslationEvidence.from_dict(
            branch_c.effect["_semantic_translation"]
        )
        oracle_c = TransitOracleEvidence.from_dict(
            branch_c.effect["_semantic_oracle"]
        )
        translation_c.validate_execution_result(branch_c, require_oracle=True)
        assert oracle_c.equivalent is True
        graph.commit("branch-c", branch_c.effect)
        assert {node.node_id for node in graph.ready_nodes()} == {"join"}

        branch_values = {
            node_id: graph.result(node_id)["registers"]["answer"]
            for node_id in ("branch-a", "branch-b", "branch-c")
        }
        assert branch_values == {"branch-a": 239, "branch-b": 660, "branch-c": 447}
        join_source = "\n".join((
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
        graph.revise_node(join_node)
        join_event = HypervisorArbitrationEvent(
            "client",
            _CHANNEL,
            5,
            9505,
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
        graph.commit("join", join_result.effect)
        assert graph.is_complete
        assert graph.commit("join", join_result.effect) is True
        assert restored.session.worker.operating_system.environment.kernel.journal.verify()
        assert len(restored_hosts) == 1
        assert restored_hosts[0].calls == 2  # C and join; B was a ledger replay.

        _write_json_durable(result_path, {
            "pid": os.getpid(),
            "checkpoint_digest": checkpoint["digest"],
            "graph_digest": graph.snapshot()["digest"],
            "committed_nodes": list(graph.committed_nodes),
            "branch_values": branch_values,
            "branch_b_replayed": replay_b.replayed,
            "branch_b_backend_calls_after_restart": 0,
            "backend_calls_after_restart": restored_hosts[0].calls,
            "total_backend_calls": 2 + restored_hosts[0].calls,
            "join_total": join_result.effect["registers"]["total"],
            "journal_valid": restored.session.worker.operating_system.environment.kernel.journal.verify(),
        })
    finally:
        for transport in transports:
            if not transport.closed:
                transport.close()


def main(arguments: list[str]) -> int:
    """Run one supervised phase and return its process exit status."""
    if len(arguments) != 3:
        raise SystemExit("usage: navigable_process_worker.py prepare|restore CHECKPOINT_PATH MARKER_OR_RESULT_PATH")
    mode, checkpoint_text, output_text = arguments
    checkpoint_path = Path(checkpoint_text)
    output_path = Path(output_text)
    if mode == "prepare":
        prepare(checkpoint_path, output_path)
        return 0
    if mode == "restore":
        restore_and_finish(checkpoint_path, output_path)
        return 0
    raise SystemExit(f"unknown worker mode: {mode}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
