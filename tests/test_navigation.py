"""Conformance tests for contextual process resolution and bounded navigation."""

from __future__ import annotations

from dataclasses import replace

import pytest

from mailcpu.navigation import (
    ConditionOperator,
    ContextRef,
    ContextResolutionError,
    ContextualNavigator,
    NavigationError,
    NavigationStatus,
    ProcessContext,
    ProcessDescriptor,
    ReadinessContract,
    SemanticAddress,
    StateCondition,
    StatePattern,
    StateUpdate,
    TransitionRule,
    UpdateOperation,
    evaluate_readiness,
    verify_navigation_witness,
)
from mailcpu.temporal import ClockDomain, MonotonicReading, TemporalFrame


def _linear_process(*, readiness: ReadinessContract | None = None) -> ProcessDescriptor:
    """Build a finite counter process whose target is supplied by contextual binding."""
    return ProcessDescriptor(
        "counter-process",
        "1.0",
        (
            TransitionRule(
                "increment",
                StatePattern((StateCondition(("count",), ConditionOperator.LT, ContextRef("target")),)),
                (StateUpdate(("count",), UpdateOperation.INCREMENT, 1),),
                {"cpu": 1},
            ),
        ),
        {"count": 0},
        (StatePattern((StateCondition(("count",), ConditionOperator.GE, 0),)),),
        readiness or ReadinessContract(),
    )


def _linear_request(target: int = 3, **context_args: object) -> tuple[ProcessDescriptor, SemanticAddress, ProcessContext]:
    """Build a counter resolution request with target focus and one CPU unit."""
    descriptor = _linear_process()
    address = SemanticAddress(
        descriptor.process_id,
        descriptor.version,
        StatePattern((StateCondition(("count",), ConditionOperator.EQ, ContextRef("target")),)),
    )
    context = ProcessContext(
        descriptor.process_id,
        bindings={"target": target},
        resource_capacity={"cpu": 1},
        **context_args,
    )
    return descriptor, address, context


def test_context_renders_a_target_from_process_logic_without_embedding_target_in_descriptor() -> None:
    descriptor, address, context = _linear_request(4)

    result = ContextualNavigator().navigate(descriptor, address, context)

    assert result.status is NavigationStatus.FOUND
    assert result.path == ("increment", "increment", "increment", "increment")
    assert result.final_state == {"count": 4}
    assert result.resource_envelope == {"cpu": 1}
    assert result.expanded_states == 4
    assert context.current_state is None
    assert verify_navigation_witness(descriptor, address, context, result)


def test_descriptor_is_the_closed_description_and_round_trips_canonically() -> None:
    descriptor, _, _ = _linear_request()

    restored = ProcessDescriptor.from_dict(descriptor.to_dict())

    assert restored.to_dict() == descriptor.to_dict()
    assert restored.digest == descriptor.digest


def test_context_bound_value_is_resolved_by_the_address_and_transition_guard() -> None:
    descriptor, address, context = _linear_request(2)

    result = ContextualNavigator().navigate(descriptor, address, context)

    assert result.final_state == {"count": 2}
    assert result.path == ("increment", "increment")


def test_unresolved_context_reference_is_refused() -> None:
    descriptor, address, _ = _linear_request()
    context = ProcessContext(descriptor.process_id, resource_capacity={"cpu": 1})

    with pytest.raises(ContextResolutionError):
        ContextualNavigator().navigate(descriptor, address, context)


def test_current_materialized_state_takes_precedence_over_descriptor_initial_state() -> None:
    descriptor, address, original = _linear_request(5)
    context = replace(original, current_state={"count": 3})

    result = ContextualNavigator().navigate(descriptor, address, context)

    assert result.path == ("increment", "increment")
    assert result.final_state == {"count": 5}


def test_already_satisfied_state_returns_empty_replayable_path() -> None:
    descriptor, address, original = _linear_request(3)
    context = replace(original, current_state={"count": 3})

    result = ContextualNavigator().navigate(descriptor, address, context)

    assert result.status is NavigationStatus.ALREADY_SATISFIED
    assert result.path == ()
    assert result.expanded_states == 0
    assert verify_navigation_witness(descriptor, address, context, result)


def test_unreachable_goal_is_distinct_from_expansion_budget_exhaustion() -> None:
    descriptor, _, context = _linear_request(3)
    impossible = SemanticAddress(
        descriptor.process_id,
        descriptor.version,
        StatePattern((StateCondition(("count",), ConditionOperator.EQ, 99),)),
    )

    result = ContextualNavigator().navigate(descriptor, impossible, context)

    assert result.status is NavigationStatus.UNREACHABLE
    assert result.witness is None


def test_expansion_budget_is_explicit_and_never_silently_returns_partial_success() -> None:
    descriptor, address, original = _linear_request(3)
    context = replace(original, max_expansions=1)

    result = ContextualNavigator().navigate(descriptor, address, context)

    assert result.status is NavigationStatus.BUDGET_EXHAUSTED
    assert result.final_state is None
    assert result.witness is None


def test_depth_budget_is_distinct_from_unreachability() -> None:
    descriptor, address, original = _linear_request(3)
    context = replace(original, max_depth=2)

    result = ContextualNavigator().navigate(descriptor, address, context)

    assert result.status is NavigationStatus.BUDGET_EXHAUSTED


def test_resource_capacity_blocks_a_path_without_conflating_it_with_logic() -> None:
    descriptor, address, original = _linear_request(1)
    context = replace(original, resource_capacity={"cpu": 0})

    result = ContextualNavigator().navigate(descriptor, address, context)

    assert result.status is NavigationStatus.RESOURCE_BLOCKED


def test_invalid_start_state_is_rejected_by_process_invariants() -> None:
    descriptor, address, context = _linear_request(1)
    invalid = replace(context, current_state={"count": -1})

    with pytest.raises(NavigationError, match="invariant"):
        ContextualNavigator().navigate(descriptor, address, invalid)


def test_transition_that_breaks_an_invariant_is_not_admitted_to_the_state_space() -> None:
    descriptor = ProcessDescriptor(
        "bounded-counter",
        "1",
        (TransitionRule("overflow", updates=(StateUpdate(("count",), UpdateOperation.INCREMENT, 1),)),),
        {"count": 0},
        (StatePattern((StateCondition(("count",), ConditionOperator.LE, 0),)),),
    )
    address = SemanticAddress("bounded-counter", "1", StatePattern((StateCondition(("count",), ConditionOperator.EQ, 1),)))

    result = ContextualNavigator().navigate(descriptor, address, ProcessContext("bounded-counter"))

    assert result.status is NavigationStatus.UNREACHABLE


def test_context_and_address_must_name_the_same_process_version() -> None:
    descriptor, _, context = _linear_request()
    wrong_version = SemanticAddress(descriptor.process_id, "2", StatePattern())

    with pytest.raises(NavigationError):
        ContextualNavigator().navigate(descriptor, wrong_version, context)


def test_process_context_must_match_descriptor_identity() -> None:
    descriptor, address, _ = _linear_request()

    with pytest.raises(NavigationError):
        ContextualNavigator().navigate(descriptor, address, ProcessContext("another-process"))


def test_witness_detects_changed_final_state() -> None:
    descriptor, address, context = _linear_request(2)
    result = ContextualNavigator().navigate(descriptor, address, context)
    tampered = replace(result, final_state={"count": 99})

    assert not verify_navigation_witness(descriptor, address, context, tampered)


def test_witness_detects_changed_resource_context() -> None:
    descriptor, address, context = _linear_request(2)
    result = ContextualNavigator().navigate(descriptor, address, context)
    changed_context = replace(context, resource_capacity={"cpu": 0})

    assert not verify_navigation_witness(descriptor, address, changed_context, result)


def test_witness_detects_changed_descriptor_law() -> None:
    descriptor, address, context = _linear_request(2)
    result = ContextualNavigator().navigate(descriptor, address, context)
    changed = replace(descriptor, transitions=())

    assert not verify_navigation_witness(changed, address, context, result)


def test_breadth_first_search_has_stable_transition_id_tie_breaking() -> None:
    descriptor = ProcessDescriptor(
        "choice",
        "1",
        (
            TransitionRule("z-path", updates=(StateUpdate(("done",), UpdateOperation.SET, True),)),
            TransitionRule("a-path", updates=(StateUpdate(("done",), UpdateOperation.SET, True),)),
        ),
        {"done": False},
    )
    address = SemanticAddress("choice", "1", StatePattern((StateCondition(("done",), ConditionOperator.EQ, True),)))

    result = ContextualNavigator().navigate(descriptor, address, ProcessContext("choice"))

    assert result.path == ("a-path",)


def test_condition_comparisons_do_not_equate_booleans_and_integers() -> None:
    state = {"flag": True}
    assert not StateCondition(("flag",), ConditionOperator.EQ, 1).matches(state, {})
    assert StateCondition(("flag",), ConditionOperator.EQ, True).matches(state, {})


def test_membership_condition_and_missing_path_semantics() -> None:
    state = {"mode": "compute"}
    assert StateCondition(("mode",), ConditionOperator.IN, ("compute", "memory")).matches(state, {})
    assert not StateCondition(("missing",), ConditionOperator.NE, 4).matches(state, {})
    assert StateCondition(("mode",), ConditionOperator.PRESENT).matches(state, {})
    assert StateCondition(("missing",), ConditionOperator.ABSENT).matches(state, {})


def test_contextual_set_update_can_render_a_value_into_the_state() -> None:
    descriptor = ProcessDescriptor(
        "renderer",
        "1",
        (TransitionRule("render", updates=(StateUpdate(("target",), UpdateOperation.SET, ContextRef("destination")),)),),
        {"target": "unset"},
    )
    address = SemanticAddress("renderer", "1", StatePattern((StateCondition(("target",), ConditionOperator.EQ, "north"),)))
    context = ProcessContext("renderer", bindings={"destination": "north"})

    result = ContextualNavigator().navigate(descriptor, address, context)

    assert result.final_state == {"target": "north"}
    assert verify_navigation_witness(descriptor, address, context, result)


def test_copy_append_and_delete_updates_preserve_json_state() -> None:
    descriptor = ProcessDescriptor(
        "updates",
        "1",
        (TransitionRule("mutate", updates=(
            StateUpdate(("copy",), UpdateOperation.COPY, source_path=("source",)),
            StateUpdate(("items",), UpdateOperation.APPEND, "b"),
            StateUpdate(("obsolete",), UpdateOperation.DELETE),
        )),),
        {"source": {"x": 1}, "items": ["a"], "obsolete": True, "done": False},
    )
    address = SemanticAddress("updates", "1", StatePattern((StateCondition(("done",), ConditionOperator.EQ, True),)))
    descriptor = replace(descriptor, transitions=descriptor.transitions + (TransitionRule(
        "finish", guard=StatePattern((StateCondition(("obsolete",), ConditionOperator.ABSENT),)),
        updates=(StateUpdate(("done",), UpdateOperation.SET, True),),
    ),))

    result = ContextualNavigator().navigate(descriptor, address, ProcessContext("updates"))

    assert result.status is NavigationStatus.FOUND
    assert result.to_dict()["final_state"] == {"source": {"x": 1}, "items": ["a", "b"], "copy": {"x": 1}, "done": True}
    assert verify_navigation_witness(descriptor, address, ProcessContext("updates"), result)


def test_increment_rejects_boolean_operands() -> None:
    update = StateUpdate(("count",), UpdateOperation.INCREMENT, True)
    rule = TransitionRule("bad-increment", updates=(update,))
    descriptor = ProcessDescriptor("numeric", "1", (rule,), {"count": 0})
    address = SemanticAddress("numeric", "1", StatePattern((StateCondition(("count",), ConditionOperator.EQ, 1),)))

    with pytest.raises(NavigationError, match="increment"):
        ContextualNavigator().navigate(descriptor, address, ProcessContext("numeric"))


def test_readiness_is_independent_of_navigation_and_reports_each_blocker() -> None:
    contract = ReadinessContract(
        preconditions=StatePattern((StateCondition(("enabled",), ConditionOperator.EQ, True),)),
        dependency_ids=("input-ready",),
        resource_requirements={"memory": 4},
        required_capabilities=frozenset({"execute"}),
        required_temporal_domains=frozenset({ClockDomain.MONOTONIC}),
    )
    descriptor = ProcessDescriptor("ready-process", "1", (), {"enabled": False}, readiness=contract)
    context = ProcessContext("ready-process")

    result = evaluate_readiness(descriptor, context)

    assert not result.ready
    assert result.blockers == (
        "state:preconditions",
        "dependency:input-ready",
        "resource:memory",
        "capability:execute",
        "clock:monotonic",
    )


def test_readiness_accepts_satisfied_state_dependencies_resources_authority_and_clock_presence() -> None:
    contract = ReadinessContract(
        preconditions=StatePattern((StateCondition(("enabled",), ConditionOperator.EQ, True),)),
        dependency_ids=("input-ready",),
        resource_requirements={"memory": 4},
        required_capabilities=frozenset({"execute"}),
        required_temporal_domains=frozenset({ClockDomain.MONOTONIC}),
    )
    descriptor = ProcessDescriptor("ready-process", "1", (), {"enabled": True}, readiness=contract)
    frame = TemporalFrame("ready-process", monotonic=MonotonicReading("ready-process", 0, 0))
    context = ProcessContext(
        "ready-process",
        resolved_dependencies=frozenset({"input-ready"}),
        resource_capacity={"memory": 4},
        capabilities=frozenset({"execute"}),
        temporal_frame=frame,
    )

    result = evaluate_readiness(descriptor, context)

    assert result.ready
    assert result.blockers == ()


def test_transition_resource_envelope_is_peak_requirement_not_cumulative_consumption() -> None:
    descriptor = ProcessDescriptor(
        "resource-envelope",
        "1",
        (
            TransitionRule("first", guard=StatePattern((StateCondition(("step",), ConditionOperator.EQ, 0),)), updates=(StateUpdate(("step",), UpdateOperation.INCREMENT, 1),), resource_requirements={"memory": 2}),
            TransitionRule("second", guard=StatePattern((StateCondition(("step",), ConditionOperator.EQ, 1),)), updates=(StateUpdate(("step",), UpdateOperation.INCREMENT, 1),), resource_requirements={"memory": 3}),
        ),
        {"step": 0},
    )
    address = SemanticAddress("resource-envelope", "1", StatePattern((StateCondition(("step",), ConditionOperator.EQ, 2),)))
    context = ProcessContext("resource-envelope", resource_capacity={"memory": 3})

    result = ContextualNavigator().navigate(descriptor, address, context)

    assert result.resource_envelope == {"memory": 3}
    assert verify_navigation_witness(descriptor, address, context, result)


def test_descriptor_and_context_values_are_detached_from_caller_mutation() -> None:
    initial = {"count": 0}
    descriptor = ProcessDescriptor("immutable", "1", (), initial)
    context_values = {"target": 2}
    context = ProcessContext("immutable", bindings=context_values)
    initial["count"] = 9
    context_values["target"] = 99

    assert descriptor.initial_state == {"count": 0}
    assert context.bindings["target"] == 2


def test_semantic_address_round_trip_preserves_context_reference_tag() -> None:
    address = SemanticAddress("round-trip", "1", StatePattern((StateCondition(("x",), ConditionOperator.EQ, ContextRef("focus")),)))

    restored = SemanticAddress(
        address.process_id,
        address.version,
        StatePattern.from_dict(address.goal.to_dict()),
    )

    assert restored.digest == address.digest
    assert isinstance(restored.goal.conditions[0].value, ContextRef)


def test_transition_rule_ids_are_unique_and_process_identity_is_versioned() -> None:
    rule = TransitionRule("same")
    with pytest.raises(NavigationError, match="unique"):
        ProcessDescriptor("duplicate", "1", (rule, rule))
