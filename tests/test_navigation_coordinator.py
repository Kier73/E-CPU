"""Adversarial tests for coordinated formal and concrete navigation."""

from __future__ import annotations

import pytest

from mailcpu.navigation import (
    ConditionOperator,
    ContextRef,
    ProcessContext,
    ProcessDescriptor,
    ReadinessContract,
    SemanticAddress,
    StateCondition,
    StatePattern,
    StateUpdate,
    TransitionRule,
    UpdateOperation,
)
from mailcpu.navigation_bridge import AbstractNavigationCompiler, NavigationCompilationError
from mailcpu.navigation_coordinator import (
    CoordinationDisposition,
    NavigationCoordinationError,
    NavigationCoordinator,
    verify_navigation_coordination,
)
from mailcpu.navigation_formal import (
    CausalDependencyGraph,
    FiniteTransitionSystem,
    LabeledTransition,
)
from mailcpu.temporal import CausalStamp


def _eq(path: str, value: object) -> StateCondition:
    return StateCondition((path,), ConditionOperator.EQ, value)


def _counter(
    *,
    readiness: ReadinessContract | None = None,
    resource_requirements: dict[str, int] | None = None,
) -> tuple[ProcessDescriptor, SemanticAddress, ProcessContext]:
    descriptor = ProcessDescriptor(
        "counter",
        "1",
        (
            TransitionRule(
                "increment",
                StatePattern((StateCondition(("count",), ConditionOperator.LT, ContextRef("target")),)),
                (StateUpdate(("count",), UpdateOperation.INCREMENT, 1),),
                resource_requirements or {},
            ),
        ),
        {"count": 0},
        readiness=readiness or ReadinessContract(),
    )
    address = SemanticAddress("counter", "1", StatePattern((_eq("count", ContextRef("target")),)))
    context = ProcessContext("counter", bindings={"target": 4})
    return descriptor, address, context


def _equivalent_pair() -> tuple[FiniteTransitionSystem, FiniteTransitionSystem]:
    left = FiniteTransitionSystem(
        "scalar",
        "s0",
        {"s0": {"value": 0}, "s1": {"value": 1}},
        (LabeledTransition("s0", "step", "s1"),),
    )
    right = FiniteTransitionSystem(
        "simt",
        "lane0",
        {"lane0": {"value": 0}, "lane1": {"value": 1}},
        (LabeledTransition("lane0", "step", "lane1"),),
    )
    return left, right


def test_coordinator_combines_abstract_concrete_readiness_and_admission_evidence() -> None:
    descriptor, address, context = _counter()

    result = NavigationCoordinator().coordinate(descriptor, address, context)

    assert result.disposition is CoordinationDisposition.READY
    assert result.navigation.path == ("increment",) * 4
    assert result.abstract_reachability is not None
    assert result.abstract_reachability.status.value == "may_be_reachable"
    assert result.readiness.ready
    assert result.admission_request is not None
    assert result.admission_request.transition_ids == ("increment",) * 4
    assert result.admission_request.authoritative is False
    assert result.admission_request.final_state_digest == result.navigation.witness.final_state_digest


def test_coordinator_replays_the_complete_plan_and_rejects_changed_context() -> None:
    descriptor, address, context = _counter()
    result = NavigationCoordinator().coordinate(descriptor, address, context)

    assert verify_navigation_coordination(descriptor, address, context, result)
    changed = ProcessContext("counter", bindings={"target": 5})
    assert not verify_navigation_coordination(descriptor, address, changed, result)


def test_full_context_digest_binds_capabilities_and_temporal_coordinates() -> None:
    descriptor, address, context = _counter()
    baseline = NavigationCoordinator().coordinate(descriptor, address, context)
    with_capability = ProcessContext("counter", bindings={"target": 4}, capabilities={"execute"})
    changed = NavigationCoordinator().coordinate(descriptor, address, with_capability)

    assert baseline.disposition is CoordinationDisposition.READY
    assert changed.disposition is CoordinationDisposition.READY
    assert baseline.context_digest != changed.context_digest
    assert baseline.admission_request.digest != changed.admission_request.digest


def test_readiness_failure_prevents_an_admission_proposal() -> None:
    contract = ReadinessContract(required_capabilities=frozenset({"execute"}))
    descriptor, address, context = _counter(readiness=contract)

    result = NavigationCoordinator().coordinate(descriptor, address, context)

    assert result.navigation.reached
    assert not result.readiness.ready
    assert result.readiness.blockers == ("capability:execute",)
    assert result.disposition is CoordinationDisposition.NOT_READY
    assert result.admission_request is None


def test_causal_dependency_graph_blocks_when_a_required_event_is_missing() -> None:
    descriptor, address, context = _counter()
    graph = CausalDependencyGraph(("request", "compute"), (("request", "compute"),))
    request = CausalStamp.create("client", 1, {"client": 1})

    result = NavigationCoordinator().coordinate(
        descriptor,
        address,
        context,
        causal_graph=graph,
        causal_observations={"request": request},
    )

    assert result.navigation.reached
    assert not result.causal_dependencies.ready
    assert result.causal_dependencies.blockers == ("event:missing:compute",)
    assert result.disposition is CoordinationDisposition.CAUSAL_BLOCKED
    assert result.admission_request is None


def test_causal_dependency_graph_requires_vector_clock_before_not_just_presence() -> None:
    descriptor, address, context = _counter()
    graph = CausalDependencyGraph(("request", "compute"), (("request", "compute"),))
    request = CausalStamp.create("client", 1, {"client": 1})
    concurrent = CausalStamp.create("worker", 1, {"worker": 1})

    result = NavigationCoordinator().coordinate(
        descriptor,
        address,
        context,
        causal_graph=graph,
        causal_observations={"request": request, "compute": concurrent},
    )

    assert result.causal_dependencies.blockers == ("causality:request:concurrent:compute",)
    assert result.disposition is CoordinationDisposition.CAUSAL_BLOCKED


def test_causal_dependencies_that_are_strictly_before_allow_a_plan() -> None:
    descriptor, address, context = _counter()
    graph = CausalDependencyGraph(("request", "compute"), (("request", "compute"),))
    request = CausalStamp.create("client", 1, {"client": 1})
    compute = CausalStamp.create("worker", 2, {"client": 1, "worker": 1})

    result = NavigationCoordinator().coordinate(
        descriptor,
        address,
        context,
        causal_graph=graph,
        causal_observations={"request": request, "compute": compute},
    )

    assert result.causal_dependencies.ready
    assert result.disposition is CoordinationDisposition.READY
    assert result.admission_request.causal_graph_digest == graph.digest


def test_required_representation_bisimulation_blocks_non_equivalent_systems() -> None:
    descriptor, address, context = _counter()
    left, _ = _equivalent_pair()
    different = FiniteTransitionSystem(
        "different",
        "x0",
        {"x0": {"value": 0}, "x1": {"value": 1}},
        (),
    )

    result = NavigationCoordinator().coordinate(
        descriptor,
        address,
        context,
        representation_pair=(left, different),
        require_representation_equivalence=True,
    )

    assert result.bisimulation is not None and not result.bisimulation.equivalent
    assert result.disposition is CoordinationDisposition.REPRESENTATION_MISMATCH
    assert result.admission_request is None


def test_equivalent_representation_pair_can_be_required_as_a_plan_gate() -> None:
    descriptor, address, context = _counter()

    result = NavigationCoordinator().coordinate(
        descriptor,
        address,
        context,
        representation_pair=_equivalent_pair(),
        require_representation_equivalence=True,
    )

    assert result.bisimulation is not None and result.bisimulation.equivalent
    assert result.disposition is CoordinationDisposition.READY
    assert result.admission_request.bisimulation_digest is not None
    assert result.admission_request.representation_equivalence_required


def test_optional_bisimulation_is_recorded_without_becoming_an_implicit_gate() -> None:
    descriptor, address, context = _counter()
    left, _ = _equivalent_pair()
    different = FiniteTransitionSystem("different", "x", {"x": {"value": 0}}, ())

    result = NavigationCoordinator().coordinate(
        descriptor,
        address,
        context,
        representation_pair=(left, different),
    )

    assert result.bisimulation is not None and not result.bisimulation.equivalent
    assert result.disposition is CoordinationDisposition.READY
    assert result.admission_request.bisimulation_digest is not None
    assert not result.admission_request.representation_equivalence_required


def test_required_representation_comparison_without_pair_is_refused() -> None:
    descriptor, address, context = _counter()

    with pytest.raises(NavigationCoordinationError, match="representation pair is required"):
        NavigationCoordinator().coordinate(
            descriptor,
            address,
            context,
            require_representation_equivalence=True,
        )


def test_unsupported_abstract_compilation_does_not_erase_a_concrete_path() -> None:
    descriptor = ProcessDescriptor(
        "string-state",
        "1",
        (TransitionRule("select-cpu", updates=(StateUpdate(("mode",), UpdateOperation.SET, "cpu"),)),),
        {"mode": "unset"},
    )
    address = SemanticAddress("string-state", "1", StatePattern((_eq("mode", "cpu"),)))
    context = ProcessContext("string-state")

    result = NavigationCoordinator().coordinate(descriptor, address, context)

    assert result.compilation_digest is None
    assert "NavigationCompilationError" in result.compilation_error
    assert result.navigation.reached
    assert result.disposition is CoordinationDisposition.READY
    assert result.admission_request is not None


def test_abstract_unreachability_is_reported_without_a_plan() -> None:
    descriptor = ProcessDescriptor("fixed", "1", (), {"count": 0})
    address = SemanticAddress(
        "fixed",
        "1",
        StatePattern((StateCondition(("count",), ConditionOperator.GE, 1),)),
    )
    context = ProcessContext("fixed")

    result = NavigationCoordinator().coordinate(descriptor, address, context)

    assert result.abstract_reachability is not None
    assert result.abstract_reachability.status.value == "proved_unreachable"
    assert result.disposition is CoordinationDisposition.ABSTRACT_UNREACHABLE
    assert result.admission_request is None


def test_already_satisfied_target_does_not_create_an_execution_admission_request() -> None:
    descriptor = ProcessDescriptor("already", "1", (), {"count": 4})
    address = SemanticAddress("already", "1", StatePattern((_eq("count", 4),)))
    context = ProcessContext("already")

    result = NavigationCoordinator().coordinate(descriptor, address, context)

    assert result.disposition is CoordinationDisposition.ALREADY_SATISFIED
    assert result.navigation.status.value == "already_satisfied"
    assert result.admission_request is None


def test_transition_resource_block_is_distinct_from_logical_unreachability() -> None:
    descriptor, address, context = _counter(resource_requirements={"memory": 4})

    result = NavigationCoordinator().coordinate(descriptor, address, context)

    assert result.navigation.status.value == "resource_blocked"
    assert result.disposition is CoordinationDisposition.RESOURCE_BLOCKED
    assert result.admission_request is None


def test_search_budget_exhaustion_is_not_reported_as_unreachability() -> None:
    descriptor = ProcessDescriptor(
        "bounded-search",
        "1",
        (TransitionRule("increment", updates=(StateUpdate(("count",), UpdateOperation.INCREMENT, 1),)),),
        {"count": 0},
    )
    address = SemanticAddress("bounded-search", "1", StatePattern((_eq("count", 2),)))
    context = ProcessContext("bounded-search", max_expansions=1)

    result = NavigationCoordinator().coordinate(descriptor, address, context)

    assert result.navigation.status.value == "budget_exhausted"
    assert result.disposition is CoordinationDisposition.BUDGET_EXHAUSTED
    assert result.admission_request is None


def test_bridge_reports_non_affine_updates_before_rejecting_non_integer_projection() -> None:
    descriptor = ProcessDescriptor(
        "list-state",
        "1",
        (TransitionRule("append", updates=(StateUpdate(("items",), UpdateOperation.APPEND, "x"),)),),
        {"items": []},
    )
    address = SemanticAddress("list-state", "1", StatePattern())
    with pytest.raises(NavigationCompilationError, match="outside the integer-affine subset"):
        AbstractNavigationCompiler().compile(descriptor, address, ProcessContext("list-state"))
