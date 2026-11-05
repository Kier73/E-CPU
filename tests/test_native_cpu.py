"""Native MailCPU CPU-context navigation and checkpoint recovery tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from mailcpu import (
    Capability,
    HeadlessOS,
    HypervisorNavigationAdmissionCoordinator,
    NavigationCoordinator,
    NativeCPUContextBackend,
    Instruction,
    ProcessDescriptor,
    Op,
    Program,
    SemanticAddress,
    StateCondition,
    StatePattern,
    StateUpdate,
    TransitionRule,
    UpdateOperation,
    ConditionOperator,
    NavigationExecutionStatus,
    load_checkpoint,
)
from mailcpu.classifier import (
    ChoiceAnswer,
    ClassifierHypervisor,
    DecisionBatch,
    HypervisorArbitrationLoop,
    HypervisorDomain,
    HypervisorPolicy,
    NoulAnswer,
)
from mailcpu.intent_embedding import IntentExample, IntentPrototypeModel


class _FixedCPUModel:
    """Deterministically classify the bounded native context operation into the CPU domain."""

    model = "native-cpu-test-model"

    def evaluate(self, state, questions):
        probabilities = {
            option: 1.0 if option == HypervisorDomain.CPU.value else 0.0
            for option, _ in questions["domain"].criteria
        }
        return DecisionBatch(
            {
                "domain": ChoiceAnswer(HypervisorDomain.CPU.value, probabilities, 1.0),
                "danger": NoulAnswer(0.0),
            },
            self.model,
        )


def _native_system(checkpoint_path: Path):
    """Create one suspended native task and a complete admitted PC/register navigation path."""
    operating_system = HeadlessOS()
    program = Program(
        (
            Instruction(Op.SET, ("rax", 0)),
            Instruction(Op.HALT),
        )
    )
    pid = operating_system.spawn(program, "native-vcpu-test", initial_registers={"rax": 1})
    operating_system.environment.kernel.processes[pid].capabilities = (
        Capability("/cpu/context", frozenset({"execute"})),
    )
    operating_system.suspend(pid)

    backend = NativeCPUContextBackend(
        operating_system,
        checkpoint_path,
        resource_path="/cpu/context",
    )
    descriptor = ProcessDescriptor(
        "native-cpu-test",
        "1",
        (
            TransitionRule(
                "advance-pc-and-rax",
                StatePattern((StateCondition(("pc",), ConditionOperator.EQ, 0),)),
                (
                    StateUpdate(("pc",), UpdateOperation.INCREMENT, 1),
                    StateUpdate(("registers", "rax"), UpdateOperation.INCREMENT, 7),
                ),
                {"cpu.context": 1, "cpu.registers": 1},
            ),
        ),
    )
    address = SemanticAddress(
        "native-cpu-test",
        "1",
        StatePattern(
            (
                StateCondition(("pc",), ConditionOperator.EQ, 1),
                StateCondition(("registers", "rax"), ConditionOperator.EQ, 8),
            )
        ),
    )
    context = backend.state_provider(pid, descriptor, address)
    coordination = NavigationCoordinator().coordinate(descriptor, address, context)
    assert coordination.admission_request is not None

    intent_model = IntentPrototypeModel.fit(
        (
            IntentExample(
                "cpu",
                {
                    "operation": "execute CPU navigation transition path",
                    "resource": backend.resource_path,
                    "payload": {"operation_kind": "navigation.execution"},
                },
            ),
        )
    )
    operating_system.hypervisor = ClassifierHypervisor(
        classifier=_FixedCPUModel(),
        journal=operating_system.environment.kernel.journal,
        policy=HypervisorPolicy(),
        intent_model=intent_model,
    )
    operating_system.hypervisor_arbitration = HypervisorArbitrationLoop(
        operating_system.hypervisor
    )
    admission_coordinator = HypervisorNavigationAdmissionCoordinator(
        operating_system,
        backend.state_provider,
    )
    admission = admission_coordinator.admit(
        pid=pid,
        source="native-cpu-test",
        sequence=1,
        descriptor=descriptor,
        address=address,
        coordination=coordination,
        resource=backend.resource_path,
        grant_ttl_ticks=10,
    )
    assert admission.accepted
    return operating_system, backend, pid, descriptor, address, admission


def test_native_backend_commits_real_pc_and_registers_at_a_suspended_safepoint(tmp_path):
    operating_system, backend, pid, descriptor, address, admission = _native_system(
        tmp_path / "native-cpu.json"
    )

    result = backend.execution_adapter().execute(admission, descriptor, address)

    assert result.status is NavigationExecutionStatus.EXECUTED
    assert result.completed
    task = operating_system.vm.scheduler.tasks[pid]
    assert task.state.pc == 1
    assert task.backend.snapshot_registers() == {"rax": 8}
    assert task.state.steps == 0
    assert task.status.value == "suspended"
    assert operating_system.vm.scheduler.native_cpu_revisions[pid] == 1
    assert operating_system.environment.kernel.journal.verify()


def test_native_cpu_checkpoint_persists_state_and_receipt_for_recovery(tmp_path):
    checkpoint = tmp_path / "native-cpu-recovery.json"
    operating_system, backend, pid, descriptor, address, admission = _native_system(checkpoint)

    first = backend.execution_adapter().execute(admission, descriptor, address)
    assert first.status is NavigationExecutionStatus.EXECUTED

    restored_os = load_checkpoint(checkpoint)
    restored_backend = NativeCPUContextBackend(
        restored_os,
        checkpoint,
        resource_path="/cpu/context",
    )
    restored_task = restored_os.vm.scheduler.tasks[pid]
    assert restored_task.state.pc == 1
    assert restored_task.backend.snapshot_registers() == {"rax": 8}
    assert restored_os.vm.scheduler.native_cpu_revisions[pid] == 1
    assert restored_backend.commit_lookup(first.execution_id) is not None

    recovered = restored_backend.execution_adapter().execute(admission, descriptor, address)
    assert recovered.status is NavigationExecutionStatus.RECOVERED
    assert recovered.completed
    assert restored_task.state.pc == 1
    assert restored_task.backend.snapshot_registers() == {"rax": 8}


def test_native_context_provider_refuses_a_runnable_task(tmp_path):
    operating_system = HeadlessOS()
    program = Program((Instruction(Op.HALT),))
    pid = operating_system.spawn(program, "running-vcpu-test")
    backend = NativeCPUContextBackend(operating_system, tmp_path / "running.json")
    descriptor = ProcessDescriptor("running-vcpu", "1", ())
    address = SemanticAddress("running-vcpu", "1", StatePattern())

    with pytest.raises(ValueError, match="suspended"):
        backend.state_provider(pid, descriptor, address)


def test_resumed_native_task_executes_from_the_navigated_program_counter(tmp_path):
    checkpoint = tmp_path / "native-cpu-resume.json"
    operating_system, backend, pid, descriptor, address, admission = _native_system(checkpoint)

    result = backend.execution_adapter().execute(admission, descriptor, address)
    assert result.completed

    operating_system.resume(pid)
    events = operating_system.run(max_ticks=operating_system.vm.scheduler.tick + 1)

    assert len(events) == 1
    assert events[0].pc_before == 1
    assert events[0].op == "HALT"
    assert operating_system.process(pid).status == "exited"
