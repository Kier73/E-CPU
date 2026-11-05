"""Conformance tests for hypervisor-owned navigation admission."""

from __future__ import annotations

from mailcpu.classifier import (
    ChoiceAnswer,
    ClassifierHypervisor,
    DecisionBatch,
    HypervisorAction,
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


class _FixedDomainModel:
    """Deterministic classifier fixture returning one chosen hypervisor domain."""

    model = "test-fixed-domain"

    def __init__(self, domain: HypervisorDomain) -> None:
        """Mathematics: fix one domain label d for every input state."""
        self.domain = domain

    def evaluate(self, state, questions):
        """Mathematics: emit P(domain=d)=1 and P(danger=true)=0 for all fixture requests."""
        domain_question = questions["domain"]
        probabilities = {
            option: 1.0 if option == self.domain.value else 0.0
            for option, _ in domain_question.criteria
        }
        return DecisionBatch(
            {
                "domain": ChoiceAnswer(self.domain.value, probabilities, 1.0),
                "danger": NoulAnswer(0.0),
            },
            self.model,
        )


def _plan(target: int = 2):
    """Mathematics: construct a two-step counter process and its replayable ready plan."""
    descriptor = ProcessDescriptor(
        "counter",
        "1",
        (
            TransitionRule(
                "increment",
                StatePattern(
                    (StateCondition(("count",), ConditionOperator.LT, target),)
                ),
                (StateUpdate(("count",), UpdateOperation.INCREMENT, 1),),
            ),
        ),
        {"count": 0},
    )
    address = SemanticAddress(
        "counter",
        "1",
        StatePattern((StateCondition(("count",), ConditionOperator.EQ, target),)),
    )
    context = ProcessContext("counter")
    coordination = NavigationCoordinator().coordinate(descriptor, address, context)
    return descriptor, address, context, coordination


def _os(domain: HypervisorDomain = HypervisorDomain.CPU, *, capable: bool = True):
    """Mathematics: initialize a real HeadlessOS with one process and deterministic hypervisor models."""
    operating_system = HeadlessOS()
    rights = frozenset({"execute"}) if capable else frozenset()
    process_capabilities = (Capability("/jobs", rights),) if capable else ()
    pid = operating_system.environment.kernel.spawn(
        "navigation-test",
        capabilities=process_capabilities,
    )
    intent = IntentPrototypeModel.fit(
        (
            IntentExample(
                domain.value,
                {
                    "operation": "execute CPU navigation transition path",
                    "resource": "/jobs/counter",
                    "payload": {"operation_kind": "navigation.execution"},
                },
            ),
        )
    )
    operating_system.hypervisor = ClassifierHypervisor(
        classifier=_FixedDomainModel(domain),
        journal=operating_system.environment.kernel.journal,
        policy=HypervisorPolicy(),
        intent_model=intent,
    )
    operating_system.hypervisor_arbitration = HypervisorArbitrationLoop(
        operating_system.hypervisor
    )
    return operating_system, pid


def _admitter(operating_system, context):
    """Mathematics: bind the admission service to one trusted live-context projection."""
    return HypervisorNavigationAdmissionCoordinator(
        operating_system,
        lambda pid, descriptor, address: context,
    )


def test_hypervisor_admission_issues_bounded_cpu_grant_after_live_replay() -> None:
    descriptor, address, context, coordination = _plan()
    operating_system, pid = _os()

    result = _admitter(operating_system, context).admit(
        pid=pid,
        source="test-runner",
        sequence=1,
        descriptor=descriptor,
        address=address,
        coordination=coordination,
        resource="/jobs/counter",
        grant_ttl_ticks=12,
    )

    assert result.status is NavigationAdmissionStatus.ADMITTED
    assert result.accepted
    assert result.action is HypervisorAction.ALLOW
    assert result.domain is HypervisorDomain.CPU
    assert result.grant is not None
    assert result.grant.authoritative
    assert result.grant.pid == pid
    assert result.grant.transition_ids == ("increment", "increment")
    assert result.grant.start_state_digest == coordination.admission_request.start_state_digest
    assert result.grant.maximum_steps == 2
    assert result.grant.required_rights == ("execute",)
    assert result.grant.resource == "/jobs/counter"
    assert result.grant.valid_at(0)
    assert not result.grant.valid_at(12)
    assert result.decision_receipt is not None
    assert result.admission_receipt


def test_exact_admission_replay_returns_the_same_grant_identity() -> None:
    descriptor, address, context, coordination = _plan()
    operating_system, pid = _os()
    admitter = _admitter(operating_system, context)
    arguments = {
        "pid": pid,
        "source": "test-runner",
        "sequence": 4,
        "descriptor": descriptor,
        "address": address,
        "coordination": coordination,
        "resource": "/jobs/counter",
        "grant_ttl_ticks": 12,
    }

    first = admitter.admit(**arguments)
    replay = admitter.admit(**arguments)

    assert first.status is NavigationAdmissionStatus.ADMITTED
    assert replay.status is NavigationAdmissionStatus.REPLAYED
    assert replay.replayed
    assert first.grant is not None and replay.grant is not None
    assert first.grant.digest == replay.grant.digest
    assert first.decision_receipt == replay.decision_receipt


def test_live_context_change_refuses_stale_navigation_plan() -> None:
    descriptor, address, context, coordination = _plan()
    changed_context = ProcessContext("counter", bindings={"target": 3})
    operating_system, pid = _os()

    result = _admitter(operating_system, changed_context).admit(
        pid=pid,
        source="test-runner",
        sequence=1,
        descriptor=descriptor,
        address=address,
        coordination=coordination,
        resource="/jobs/counter",
    )

    assert result.status is NavigationAdmissionStatus.REFUSED_CONTEXT
    assert not result.accepted
    assert result.grant is None
    assert result.decision_receipt is None


def test_actual_kernel_capability_is_required_even_when_plan_is_ready() -> None:
    descriptor, address, context, coordination = _plan()
    operating_system, pid = _os(capable=False)

    result = _admitter(operating_system, context).admit(
        pid=pid,
        source="test-runner",
        sequence=1,
        descriptor=descriptor,
        address=address,
        coordination=coordination,
        resource="/jobs/counter",
    )

    assert result.status is NavigationAdmissionStatus.REFUSED_CAPABILITY
    assert result.action is HypervisorAction.DENY
    assert result.grant is None


def test_exact_replay_of_capability_denial_remains_a_typed_refusal() -> None:
    descriptor, address, context, coordination = _plan()
    operating_system, pid = _os(capable=False)
    admitter = _admitter(operating_system, context)
    arguments = {
        "pid": pid,
        "source": "test-runner",
        "sequence": 2,
        "descriptor": descriptor,
        "address": address,
        "coordination": coordination,
        "resource": "/jobs/counter",
    }

    first = admitter.admit(**arguments)
    replay = admitter.admit(**arguments)

    assert first.status is NavigationAdmissionStatus.REFUSED_CAPABILITY
    assert replay.status is NavigationAdmissionStatus.REFUSED_CAPABILITY
    assert replay.replayed
    assert replay.grant is None
    assert first.decision_receipt == replay.decision_receipt


def test_hypervisor_review_cannot_be_upgraded_by_navigation_proposal() -> None:
    descriptor, address, context, coordination = _plan()
    operating_system, pid = _os(HypervisorDomain.REVIEW)

    result = _admitter(operating_system, context).admit(
        pid=pid,
        source="test-runner",
        sequence=1,
        descriptor=descriptor,
        address=address,
        coordination=coordination,
        resource="/jobs/counter",
    )

    assert result.status is NavigationAdmissionStatus.REFUSED_POLICY
    assert result.action is HypervisorAction.REVIEW
    assert result.grant is None


def test_non_cpu_policy_domain_cannot_receive_navigation_execution_grant() -> None:
    descriptor, address, context, coordination = _plan()
    operating_system, pid = _os(HypervisorDomain.PROCESS)

    result = _admitter(operating_system, context).admit(
        pid=pid,
        source="test-runner",
        sequence=1,
        descriptor=descriptor,
        address=address,
        coordination=coordination,
        resource="/jobs/counter",
    )

    assert result.status is NavigationAdmissionStatus.REFUSED_DOMAIN
    assert result.action is HypervisorAction.ALLOW
    assert result.domain is HypervisorDomain.PROCESS
    assert result.grant is None


def test_context_provider_failure_fails_closed_and_is_journaled() -> None:
    descriptor, address, context, coordination = _plan()
    operating_system, pid = _os()
    admitter = HypervisorNavigationAdmissionCoordinator(
        operating_system,
        lambda pid, descriptor, address: (_ for _ in ()).throw(RuntimeError("state unavailable")),
    )

    result = admitter.admit(
        pid=pid,
        source="test-runner",
        sequence=1,
        descriptor=descriptor,
        address=address,
        coordination=coordination,
        resource="/jobs/counter",
    )

    assert result.status is NavigationAdmissionStatus.REFUSED_CONTEXT
    assert result.grant is None
    assert result.admission_receipt


def test_non_ready_navigation_result_cannot_receive_hypervisor_grant() -> None:
    descriptor, address, context, coordination = _plan()
    other_descriptor = ProcessDescriptor(
        "counter",
        "2",
        (),
        {"count": 0},
    )
    other_address = SemanticAddress(
        "counter",
        "2",
        StatePattern((StateCondition(("count",), ConditionOperator.EQ, 0),)),
    )
    non_ready = NavigationCoordinator().coordinate(
        other_descriptor, other_address, ProcessContext("counter")
    )
    operating_system, pid = _os()

    result = _admitter(operating_system, context).admit(
        pid=pid,
        source="test-runner",
        sequence=1,
        descriptor=other_descriptor,
        address=other_address,
        coordination=non_ready,
        resource="/jobs/counter",
    )

    assert result.status is NavigationAdmissionStatus.REFUSED_PLAN
    assert result.grant is None


def test_same_event_identity_cannot_be_rebound_to_another_plan() -> None:
    descriptor, address, context, coordination = _plan()
    operating_system, pid = _os()
    admitter = HypervisorNavigationAdmissionCoordinator(
        operating_system,
        lambda pid, descriptor, address: ProcessContext(descriptor.process_id),
    )
    first = admitter.admit(
        pid=pid,
        source="test-runner",
        sequence=9,
        descriptor=descriptor,
        address=address,
        coordination=coordination,
        resource="/jobs/counter",
    )
    changed_descriptor, changed_address, changed_context, changed_plan = _plan(3)
    second = admitter.admit(
        pid=pid,
        source="test-runner",
        sequence=9,
        descriptor=changed_descriptor,
        address=changed_address,
        coordination=changed_plan,
        resource="/jobs/counter",
    )

    assert first.accepted
    assert second.status is NavigationAdmissionStatus.REFUSED_ARBITRATION
    assert second.grant is None
