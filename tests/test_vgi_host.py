from __future__ import annotations

from dataclasses import replace

import pytest

from mailcpu import (
    Capability,
    HeadlessOS,
    HypervisorAction,
    HypervisorError,
    HypervisorPolicy,
    LexicalDecisionModel,
    OperatorRegistry,
    SystemIdentity,
    SystemSeed,
    SystemSeedEnvelope,
    VirtualBudget,
    VirtualGroundRef,
    VirtualLayerError,
    VirtualLayerRuntime,
    VirtualLayerWorkload,
    VirtualOperatorRef,
)
from mailcpu.vgi_host import (
    VGIHostError,
    VGI_SIGNAL8_OPERATOR_ID,
    make_vgi_signal8_operator,
    register_vgi_signal8_operator,
    vgi_signal8_implementation_fingerprint,
)
from mailcpu.transit_vgi import TransitVGIHost

vgi = pytest.importorskip("vgi")
from vgi import (
    SIGNAL8_GROUND,
    RuntimeErrorVGI,
    Signal8Backend,
    SignalStateMachine,
    TaskSpec,
    VirtualGroundInterpreter,
)


def _task() -> dict[str, object]:
    """Build an expression that adds two signal values and branches on identity."""
    return {
        "name": "add-then-select",
        "inputs": ["input.a", "input.b"],
        "outputs": [
            {
                "label": "selected",
                "expression": {
                    "type": "if",
                    "guard": {
                        "type": "is_identity",
                        "value": {
                            "type": "add",
                            "left": {"type": "input", "address": "input.a"},
                            "right": {"type": "input", "address": "input.b"},
                        },
                        "tolerance_rad": 1e-8,
                    },
                    "when_true": {"type": "input", "address": "input.b"},
                    "when_false": {"type": "input", "address": "input.a"},
                },
            }
        ],
    }


def _case():
    """Prepare an admitted E-CPU system Ground and a typed VGI workload."""
    operating_system = HeadlessOS()
    operating_system.hypervisor.classifier = LexicalDecisionModel()
    operating_system.hypervisor.policy = HypervisorPolicy(embedding_review_confidence=1.0)
    identity = SystemIdentity("vgi-hosted-system", 1)
    seed = SystemSeed.from_system(operating_system)
    envelope = SystemSeedEnvelope(identity, "executor", "vgi-hosted-test", seed)
    admission = operating_system.seed_admission.admit(envelope)
    assert admission.accepted
    system_ground = VirtualGroundRef.from_envelope(envelope)

    backend = Signal8Backend()
    initial_memory = {
        "input.a": backend.encode_symbol(3, observer=1).to_dict(),
        "input.b": backend.encode_symbol(5, observer=3).to_dict(),
    }
    request = {
        "schema": "vgi.signal8.request.v1",
        "ground_fingerprint": SIGNAL8_GROUND.fingerprint,
        "task": _task(),
        "initial_memory": initial_memory,
        "max_steps": 128,
    }
    workload = VirtualLayerWorkload(
        workload_id="vgi-workload-001",
        system=identity,
        ground=system_ground,
        intention={"goal": {"kind": "execute-vgi-task"}},
        operators=(VirtualOperatorRef(VGI_SIGNAL8_OPERATOR_ID, 1, "cpu"),),
        input_value=request,
        budget=VirtualBudget(
            max_energy=100_000,
            max_bytes=1_000_000,
            max_virtual_ticks=1_000,
        ),
        logical_time=7,
        eligible_nodes=("node-vgi",),
        max_hops=2,
    )
    registry = OperatorRegistry()
    spec, handler = make_vgi_signal8_operator(max_steps=256)
    calls: list[str] = []

    def counted_handler(value, current_workload):
        """Count local interpreter entry while preserving the registered operation."""
        calls.append(current_workload.workload_id)
        return handler(value, current_workload)

    registry.register(spec, counted_handler)
    runtime = VirtualLayerRuntime(registry, "node-vgi", frozenset({"cpu"}))
    pid = operating_system.environment.kernel.spawn(
        "vgi-operator-worker",
        capabilities=(Capability("/virtual-layer/operators", frozenset({"compute"})),),
        parent_pid=operating_system.environment.init_pid,
    )
    return operating_system, workload, registry, runtime, pid, calls, request


def test_vgi_host_execution_preserves_both_ground_identities(monkeypatch) -> None:
    """The operator must preserve system Ground and computational Ground independently."""
    operating_system, workload, _, runtime, pid, calls, _ = _case()

    def forbidden_decode(self, value):
        """Fail if the hosted execution decodes a semantic integer."""
        raise AssertionError("semantic integer decoding is forbidden during VGI execution")

    monkeypatch.setattr(Signal8Backend, "observe_symbol", forbidden_decode)
    result = runtime.execute_operator(
        operating_system,
        pid,
        "origin",
        "vgi",
        1,
        workload.logical_time,
        workload,
        VGI_SIGNAL8_OPERATOR_ID,
    )
    assert result.action is HypervisorAction.ALLOW
    assert result.executed is True
    assert result.effect["kind"] == "virtual_layer.operator_result"
    assert result.effect["ground"] == workload.ground.to_dict()

    receipt = result.effect["result"]
    assert receipt["kind"] == "vgi.signal8.execution"
    assert receipt["system_ground"] == workload.ground.to_dict()
    assert receipt["computation_ground"]["ground_id"] == SIGNAL8_GROUND.ground_id
    assert receipt["computation_ground"]["fingerprint"] == SIGNAL8_GROUND.fingerprint
    assert receipt["program"]["fingerprint"]
    assert receipt["implementation"]["source_fingerprint"] == (
        vgi_signal8_implementation_fingerprint()
    )
    assert len(receipt["implementation"]["source_fingerprint"]) == 64
    assert receipt["execution"]["halted"] is True
    assert receipt["execution"]["step_count"] == len(receipt["execution"]["trace"])
    assert any(
        event["opcode"] == "BRANCH_IDENTITY" and event["branch_result"] is True
        for event in receipt["execution"]["trace"]
    )
    assert receipt["execution"]["outputs"][0]["label"] == "selected"
    expected = Signal8Backend().encode_symbol(5, observer=3).to_dict()
    actual = receipt["execution"]["outputs"][0]["value"]
    assert actual["real"] == pytest.approx(expected["real"])
    assert actual["imag"] == pytest.approx(expected["imag"])
    assert actual["observer"] == expected["observer"]
    assert actual["phase_error_bound"] == expected["phase_error_bound"]
    assert receipt["checkpoint"]["ground_fingerprint"] == SIGNAL8_GROUND.fingerprint
    assert len(receipt["checkpoint"]["state_digest"]) == 64
    assert len(receipt["execution_digest"]) == 64
    assert calls == [workload.workload_id]
    assert operating_system.environment.kernel.journal.verify()


def test_vgi_host_replay_does_not_reenter_interpreter() -> None:
    """An exact semantic retry must return the committed VGI receipt without backend re-entry."""
    operating_system, workload, _, runtime, pid, calls, _ = _case()
    first = runtime.execute_operator(
        operating_system, pid, "origin", "vgi", 1,
        workload.logical_time, workload, VGI_SIGNAL8_OPERATOR_ID,
    )
    replay = runtime.execute_operator(
        operating_system, pid, "origin", "vgi", 1,
        workload.logical_time, workload, VGI_SIGNAL8_OPERATOR_ID,
    )
    assert first.action is HypervisorAction.ALLOW and first.executed is True
    assert replay.replayed is True
    assert replay.effect == first.effect
    assert calls == [workload.workload_id]
    assert operating_system.environment.kernel.journal.verify()


def test_vgi_host_rejects_computation_ground_mismatch_before_compile() -> None:
    """A request bound to another VGI Ground must fail before interpreter execution."""
    _, workload, _, _, _, _, request = _case()
    spec, handler = make_vgi_signal8_operator(max_steps=256)
    bad_request = dict(request)
    bad_request["ground_fingerprint"] = "0" * 64
    with pytest.raises(VGIHostError, match="fingerprint"):
        handler(bad_request, workload)


def test_vgi_host_rejects_memory_that_does_not_match_declared_task_inputs() -> None:
    """A task cannot smuggle undeclared or missing signal-memory addresses into VGI."""
    _, workload, _, _, _, _, request = _case()
    spec, handler = make_vgi_signal8_operator(max_steps=256)
    bad_request = dict(request)
    bad_request["initial_memory"] = {"input.a": request["initial_memory"]["input.a"]}
    with pytest.raises(VGIHostError, match="exactly match"):
        handler(bad_request, workload)



def test_vgi_host_rejects_changed_input_under_the_same_execution_identity() -> None:
    """A committed event identity cannot be rebound to a different input or workload digest."""
    operating_system, workload, _, runtime, pid, calls, _ = _case()
    first = runtime.execute_operator(
        operating_system,
        pid,
        "origin",
        "vgi",
        1,
        workload.logical_time,
        workload,
        VGI_SIGNAL8_OPERATOR_ID,
    )
    assert first.executed is True

    changed_request = dict(workload.input_value)
    changed_memory = dict(changed_request["initial_memory"])
    changed_memory["input.a"] = Signal8Backend().encode_symbol(
        4, observer=1
    ).to_dict()
    changed_request["initial_memory"] = changed_memory
    changed_workload = replace(workload, input_value=changed_request)

    with pytest.raises(HypervisorError, match="conflicting execution retransmission"):
        runtime.execute_operator(
            operating_system,
            pid,
            "origin",
            "vgi",
            1,
            changed_workload.logical_time,
            changed_workload,
            VGI_SIGNAL8_OPERATOR_ID,
        )

    records = operating_system.environment.kernel.journal.snapshot()
    assert calls == [workload.workload_id]
    assert sum(item["kind"] == "hypervisor.execution.commit" for item in records) == 1
    assert sum(item["kind"] == "hypervisor.execution.conflict" for item in records) == 1
    assert operating_system.environment.kernel.journal.verify()


def test_vgi_host_rejects_mismatched_system_ground_before_execution() -> None:
    """A valid program and computational Ground cannot run from a stale E-CPU system Ground."""
    operating_system, workload, _, runtime, pid, calls, _ = _case()
    stale_ground = VirtualGroundRef(
        workload.ground.origin_digest,
        "f" * 64,
        workload.ground.coordinate,
        workload.ground.frontier_digest,
    )
    stale_workload = replace(workload, ground=stale_ground)

    with pytest.raises(VirtualLayerError, match="Virtual Ground or causal frontier is stale"):
        runtime.execute_operator(
            operating_system,
            pid,
            "origin",
            "vgi",
            1,
            stale_workload.logical_time,
            stale_workload,
            VGI_SIGNAL8_OPERATOR_ID,
        )

    records = operating_system.environment.kernel.journal.snapshot()
    assert calls == []
    assert not any(item["kind"] == "hypervisor.execution.commit" for item in records)
    assert operating_system.environment.kernel.journal.verify()

def test_vgi_host_checkpoint_restores_under_the_same_program_and_ground() -> None:
    """The returned VGI machine checkpoint must restore only under the identical program and Ground."""
    operating_system, workload, _, runtime, pid, _, _ = _case()
    execution = runtime.execute_operator(
        operating_system, pid, "origin", "vgi", 1,
        workload.logical_time, workload, VGI_SIGNAL8_OPERATOR_ID,
    )
    receipt = execution.effect["result"]
    interpreter = VirtualGroundInterpreter(ground=SIGNAL8_GROUND)
    task = TaskSpec.from_dict(workload.input_value["task"])
    program = interpreter.compile_task(task)
    restored = SignalStateMachine.restore(interpreter, program, receipt["checkpoint"])
    assert restored.halted is True
    assert restored.pc == receipt["checkpoint"]["pc"]
    assert restored.snapshot()["state_digest"] == receipt["checkpoint"]["state_digest"]

    corrupted = dict(receipt["checkpoint"])
    corrupted["state_digest"] = "0" * 64
    with pytest.raises(RuntimeErrorVGI, match="snapshot state digest mismatch"):
        SignalStateMachine.restore(interpreter, program, corrupted)

    changed_task = dict(workload.input_value["task"])
    changed_task["outputs"] = [{
        "label": "selected",
        "expression": {"type": "input", "address": "input.a"},
    }]
    changed_program = interpreter.compile_task(TaskSpec.from_dict(changed_task))
    with pytest.raises(RuntimeErrorVGI, match="different program"):
        SignalStateMachine.restore(interpreter, changed_program, receipt["checkpoint"])


def test_vgi_implementation_identity_binds_host_class_and_execution_profile() -> None:
    """The Transit implementation identity changes with the concrete host or its configured step ceiling."""

    base = vgi_signal8_implementation_fingerprint(
        TransitVGIHost,
        max_configured_steps=128,
    )
    wider_profile = vgi_signal8_implementation_fingerprint(
        TransitVGIHost,
        max_configured_steps=256,
    )
    adapter_only = vgi_signal8_implementation_fingerprint()

    assert len(base) == 64
    assert base != wider_profile
    assert base != adapter_only
