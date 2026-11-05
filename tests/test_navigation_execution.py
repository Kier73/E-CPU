"""Conformance tests for crash-recoverable hypervisor navigation execution."""

from __future__ import annotations

import copy
from dataclasses import replace

from mailcpu.classifier import (
    ChoiceAnswer,
    ClassifierHypervisor,
    DecisionBatch,
    HypervisorArbitrationLoop,
    HypervisorDomain,
    HypervisorPolicy,
    NoulAnswer,
)
from mailcpu.headless import HeadlessOS
from mailcpu.intent_embedding import IntentExample, IntentPrototypeModel
from mailcpu.kernel import Capability
from mailcpu.navigation import (
    ConditionOperator,
    ProcessContext,
    ProcessDescriptor,
    SemanticAddress,
    StateCondition,
    StatePattern,
    StateUpdate,
    TransitionRule,
    UpdateOperation,
)
from mailcpu.navigation_admission import (
    HypervisorNavigationAdmissionCoordinator,
    NavigationAdmissionStatus,
)
from mailcpu.navigation_coordinator import NavigationCoordinator
from mailcpu.navigation_execution import (
    HypervisorNavigationExecutionAdapter,
    NavigationCommitReceipt,
    NavigationExecutionStatus,
)
import hashlib
import json


def _digest(value):
    """Mathematics: calculate a deterministic SHA-256 state identity for the test backend."""
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(data).hexdigest()


class _FixedDomainModel:
    """Deterministic classifier fixture returning the CPU domain."""

    model = "test-fixed-cpu-domain"

    def evaluate(self, state, questions):
        """Mathematics: emit P(cpu)=1 and P(danger)=0 for every test request."""
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


def _system():
    """Mathematics: prepare one admitted CPU navigation path and an idempotent in-memory host CAS."""
    operating_system = HeadlessOS()
    pid = operating_system.environment.kernel.spawn(
        "navigation-executor-test",
        capabilities=(Capability("/jobs", frozenset({"execute"})),),
    )
    intent = IntentPrototypeModel.fit(
        (
            IntentExample(
                "cpu",
                {
                    "operation": "execute CPU navigation transition path",
                    "resource": "/jobs/counter",
                    "payload": {"operation_kind": "navigation.execution"},
                },
            ),
        )
    )
    operating_system.hypervisor = ClassifierHypervisor(
        classifier=_FixedDomainModel(),
        journal=operating_system.environment.kernel.journal,
        policy=HypervisorPolicy(),
        intent_model=intent,
    )
    operating_system.hypervisor_arbitration = HypervisorArbitrationLoop(
        operating_system.hypervisor
    )

    descriptor = ProcessDescriptor(
        "counter",
        "1",
        (
            TransitionRule(
                "increment",
                StatePattern(
                    (StateCondition(("count",), ConditionOperator.LT, 2),)
                ),
                (StateUpdate(("count",), UpdateOperation.INCREMENT, 1),),
                {"memory": 1},
            ),
        ),
        {"count": 0},
    )
    address = SemanticAddress(
        "counter",
        "1",
        StatePattern((StateCondition(("count",), ConditionOperator.EQ, 2),)),
    )
    store = {
        "state": {"count": 0},
        "revision": 0,
        "receipts": {},
        "commit_calls": 0,
    }

    def state_provider(_pid, _descriptor, _address):
        """Mathematics: expose one detached snapshot of the currently committed backend state."""
        return ProcessContext(
            "counter",
            current_state=copy.deepcopy(store["state"]),
            resource_capacity={"memory": 2},
        )

    context = state_provider(pid, descriptor, address)
    coordination = NavigationCoordinator().coordinate(descriptor, address, context)
    assert coordination.admission_request is not None

    admission_coordinator = HypervisorNavigationAdmissionCoordinator(
        operating_system,
        lambda _pid, _descriptor, _address: state_provider(_pid, _descriptor, _address),
    )
    admission = admission_coordinator.admit(
        pid=pid,
        source="execution-test",
        sequence=1,
        descriptor=descriptor,
        address=address,
        coordination=coordination,
        resource="/jobs/counter",
        grant_ttl_ticks=10,
    )
    assert admission.status is NavigationAdmissionStatus.ADMITTED

    def commit_callback(commit_pid, execution_id, expected_digest, candidate, grant):
        """Mathematics: implement an atomic compare-and-swap keyed by execution_id, returning prior receipts on retry."""
        if commit_pid != pid or grant.pid != pid:
            raise AssertionError("wrong target process")
        previous = store["receipts"].get(execution_id)
        if previous is not None:
            return replace(previous, replayed=True)
        observed = _digest(store["state"])
        if observed != expected_digest:
            rejected = NavigationCommitReceipt(
                execution_id,
                False,
                expected_digest,
                observed,
                store["revision"],
                False,
                "backend state changed before commit",
            )
            store["receipts"][execution_id] = rejected
            return rejected
        store["state"] = copy.deepcopy(dict(candidate))
        store["revision"] += 1
        store["commit_calls"] += 1
        accepted = NavigationCommitReceipt(
            execution_id,
            True,
            expected_digest,
            _digest(store["state"]),
            store["revision"],
        )
        store["receipts"][execution_id] = accepted
        return accepted

    def commit_lookup(execution_id):
        """Mathematics: recover the durable backend receipt by the same idempotency key without applying a state transition."""
        previous = store["receipts"].get(execution_id)
        return None if previous is None else replace(previous, replayed=True)

    adapter = HypervisorNavigationExecutionAdapter(
        operating_system,
        state_provider,
        commit_callback,
        commit_lookup,
    )
    return operating_system, pid, descriptor, address, store, admission, adapter


def test_admitted_path_replays_and_commits_the_exact_target_state() -> None:
    operating_system, pid, descriptor, address, store, admission, adapter = _system()

    result = adapter.execute(admission, descriptor, address)

    assert result.status is NavigationExecutionStatus.EXECUTED
    assert result.completed
    assert result.transition_ids == ("increment", "increment")
    assert store["state"] == {"count": 2}
    assert store["revision"] == 1
    assert store["commit_calls"] == 1
    assert result.commit_receipt is not None
    assert result.commit_receipt.final_state_digest == admission.grant.final_state_digest
    assert result.execution_receipt is not None
    assert result.journal_receipt == result.execution_receipt
    assert operating_system.environment.kernel.journal.verify()


def test_completed_execution_replay_never_calls_backend_twice() -> None:
    _, _, descriptor, address, store, admission, adapter = _system()

    first = adapter.execute(admission, descriptor, address)
    second = adapter.execute(admission, descriptor, address)

    assert first.status is NavigationExecutionStatus.EXECUTED
    assert second.status is NavigationExecutionStatus.REPLAYED
    assert second.replayed
    assert first.execution_id == second.execution_id
    assert first.execution_receipt == second.execution_receipt
    assert store["commit_calls"] == 1
    assert store["revision"] == 1


def test_exact_admission_replay_maps_to_the_same_execution_id() -> None:
    operating_system, pid, descriptor, address, store, admission, adapter = _system()
    grant = admission.grant
    context_provider = lambda _pid, _descriptor, _address: ProcessContext(
        "counter",
        current_state=copy.deepcopy(store["state"]),
        resource_capacity={"memory": 2},
    )
    replayed_admission = HypervisorNavigationAdmissionCoordinator(
        operating_system, context_provider
    ).admit(
        pid=pid,
        source="execution-test",
        sequence=1,
        descriptor=descriptor,
        address=address,
        coordination=NavigationCoordinator().coordinate(
            descriptor, address, context_provider(pid, descriptor, address)
        ),
        resource="/jobs/counter",
        grant_ttl_ticks=10,
    )
    assert replayed_admission.status is NavigationAdmissionStatus.REPLAYED
    assert replayed_admission.grant.digest == grant.digest

    first = adapter.execute(admission, descriptor, address)
    replay = adapter.execute(replayed_admission, descriptor, address)

    assert first.execution_id == replay.execution_id
    assert replay.status is NavigationExecutionStatus.REPLAYED
    assert store["commit_calls"] == 1


def test_forged_or_missing_admission_receipt_cannot_execute() -> None:
    _, _, descriptor, address, store, admission, adapter = _system()
    forged = replace(admission, admission_receipt="0" * 64)

    result = adapter.execute(forged, descriptor, address)

    assert result.status is NavigationExecutionStatus.REFUSED_PROVENANCE
    assert result.commit_receipt is None
    assert store["commit_calls"] == 0


def test_expired_grant_is_refused_before_backend_callback() -> None:
    operating_system, _, descriptor, address, store, admission, adapter = _system()
    operating_system.vm.scheduler.tick = admission.grant.expires_at_tick

    result = adapter.execute(admission, descriptor, address)

    assert result.status is NavigationExecutionStatus.REFUSED_EXPIRED
    assert store["commit_calls"] == 0


def test_changed_live_start_state_refuses_stale_grant() -> None:
    _, _, descriptor, address, store, admission, adapter = _system()
    store["state"] = {"count": 1}

    result = adapter.execute(admission, descriptor, address)

    assert result.status is NavigationExecutionStatus.REFUSED_CONTEXT
    assert store["commit_calls"] == 0


def test_revoked_kernel_capability_refuses_execution() -> None:
    operating_system, pid, descriptor, address, store, admission, adapter = _system()
    operating_system.environment.kernel._process(pid).capabilities = ()

    result = adapter.execute(admission, descriptor, address)

    assert result.status is NavigationExecutionStatus.REFUSED_CAPABILITY
    assert store["commit_calls"] == 0


def test_changed_descriptor_cannot_reuse_an_admitted_path() -> None:
    _, _, descriptor, address, store, admission, adapter = _system()
    changed = ProcessDescriptor(
        "counter",
        "2",
        descriptor.transitions,
        {"count": 0},
    )

    result = adapter.execute(admission, changed, address)

    assert result.status is NavigationExecutionStatus.REFUSED_PATH
    assert store["commit_calls"] == 0


def test_backend_compare_and_swap_conflict_does_not_claim_execution() -> None:
    operating_system, pid, descriptor, address, store, admission, _ = _system()

    def conflicting_commit(commit_pid, execution_id, expected, candidate, grant):
        store["state"] = {"count": 1}
        return NavigationCommitReceipt(
            execution_id,
            False,
            expected,
            _digest(store["state"]),
            store["revision"],
            reason="concurrent writer won",
        )

    adapter = HypervisorNavigationExecutionAdapter(
        operating_system,
        lambda _pid, _descriptor, _address: ProcessContext(
            "counter",
            current_state=copy.deepcopy(store["state"]),
            resource_capacity={"memory": 2},
        ),
        conflicting_commit,
        lambda _execution_id: None,
    )

    result = adapter.execute(admission, descriptor, address)

    assert result.status is NavigationExecutionStatus.COMMIT_CONFLICT
    assert not result.completed
    assert result.commit_receipt is not None
    assert not result.commit_receipt.committed


def test_backend_commit_then_process_loss_is_reconciled_without_reapplying() -> None:
    operating_system, pid, descriptor, address, store, admission, normal_adapter = _system()
    normal_commit = normal_adapter.commit_callback
    fail_once = {"value": True}

    def commit_then_crash(commit_pid, execution_id, expected, candidate, grant):
        receipt = normal_commit(commit_pid, execution_id, expected, candidate, grant)
        if fail_once["value"]:
            fail_once["value"] = False
            raise RuntimeError("simulated process loss after durable backend commit")
        return receipt

    adapter = HypervisorNavigationExecutionAdapter(
        operating_system,
        normal_adapter.state_provider,
        commit_then_crash,
        normal_adapter.commit_lookup,
    )
    first = adapter.execute(admission, descriptor, address)
    assert first.status is NavigationExecutionStatus.INDETERMINATE
    assert store["state"] == {"count": 2}
    assert store["commit_calls"] == 1

    recovered = adapter.execute(admission, descriptor, address)

    assert recovered.status is NavigationExecutionStatus.RECOVERED
    assert recovered.completed
    assert recovered.replayed
    assert store["state"] == {"count": 2}
    assert store["commit_calls"] == 1
    assert recovered.execution_receipt is not None
    assert operating_system.environment.kernel.journal.verify()


def test_recovery_can_use_an_exactly_replayed_admission_receipt() -> None:
    operating_system, pid, descriptor, address, store, admission, normal_adapter = _system()
    replayed_admission = HypervisorNavigationAdmissionCoordinator(
        operating_system,
        normal_adapter.state_provider,
    ).admit(
        pid=pid,
        source="execution-test",
        sequence=1,
        descriptor=descriptor,
        address=address,
        coordination=NavigationCoordinator().coordinate(
            descriptor, address,
            ProcessContext(
                "counter",
                current_state={"count": 0},
                resource_capacity={"memory": 2},
            ),
        ),
        resource="/jobs/counter",
        grant_ttl_ticks=10,
    )
    assert replayed_admission.status is NavigationAdmissionStatus.REPLAYED

    normal_commit = normal_adapter.commit_callback

    def commit_then_crash(commit_pid, execution_id, expected, candidate, grant):
        receipt = normal_commit(commit_pid, execution_id, expected, candidate, grant)
        raise RuntimeError("lost response after durable commit")

    adapter = HypervisorNavigationExecutionAdapter(
        operating_system,
        normal_adapter.state_provider,
        commit_then_crash,
        normal_adapter.commit_lookup,
    )
    first = adapter.execute(admission, descriptor, address)
    assert first.status is NavigationExecutionStatus.INDETERMINATE
    assert store["state"] == {"count": 2}

    recovered = adapter.execute(replayed_admission, descriptor, address)

    assert recovered.status is NavigationExecutionStatus.RECOVERED
    assert store["commit_calls"] == 1


def test_backend_receipt_for_wrong_final_state_is_not_accepted() -> None:
    operating_system, pid, descriptor, address, store, admission, _ = _system()

    def wrong_receipt(_pid, execution_id, expected, candidate, grant):
        return NavigationCommitReceipt(
            execution_id,
            True,
            expected,
            "f" * 64,
            1,
        )

    adapter = HypervisorNavigationExecutionAdapter(
        operating_system,
        lambda _pid, _descriptor, _address: ProcessContext(
            "counter",
            current_state=copy.deepcopy(store["state"]),
            resource_capacity={"memory": 2},
        ),
        wrong_receipt,
        lambda _execution_id: None,
    )
    result = adapter.execute(admission, descriptor, address)

    assert result.status is NavigationExecutionStatus.COMMIT_UNVERIFIED
    assert not result.completed


def test_write_ahead_intent_uses_one_stable_execution_identity() -> None:
    operating_system, _, descriptor, address, store, admission, adapter = _system()
    first = adapter.execute(admission, descriptor, address)
    records = operating_system.environment.kernel.journal.records()
    begin_records = [
        item for item in records
        if item.kind == "hypervisor.navigation.execute.begin"
        and item.payload["execution_id"] == first.execution_id
    ]

    assert len(begin_records) == 1
    assert begin_records[0].payload["maximum_steps"] == 2
    assert begin_records[0].payload["transition_ids"] == ["increment", "increment"]
    assert store["revision"] == 1
