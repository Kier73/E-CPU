"""Tests for conservative compilation between concrete and abstract navigation."""

from __future__ import annotations

from dataclasses import replace

import pytest

from mailcpu.navigation import (
    ConditionOperator,
    ContextRef,
    ContextualNavigator,
    ProcessContext,
    ProcessDescriptor,
    SemanticAddress,
    StateCondition,
    StatePattern,
    StateUpdate,
    TransitionRule,
    UpdateOperation,
    verify_navigation_witness,
)
from mailcpu.navigation_bridge import (
    AbstractNavigationCompiler,
    NavigationCompilationError,
    analyze_compiled_navigation,
    verify_abstract_compilation,
)
from mailcpu.navigation_formal import (
    AbstractReachabilityStatus,
    ConstraintDisposition,
    ConstraintRelation,
    LinearExpression,
)


def _eq(path: str, value: object) -> StateCondition:
    return StateCondition((path,), ConditionOperator.EQ, value)


def test_compiler_bridges_contextual_counter_and_abstract_reachability() -> None:
    descriptor = ProcessDescriptor(
        "counter",
        "1",
        (
            TransitionRule(
                "increment",
                StatePattern((StateCondition(("count",), ConditionOperator.LT, ContextRef("target")),)),
                (StateUpdate(("count",), UpdateOperation.INCREMENT, 1),),
            ),
        ),
        {"count": 0},
    )
    address = SemanticAddress(
        "counter",
        "1",
        StatePattern((_eq("count", ContextRef("target")),)),
    )
    context = ProcessContext("counter", bindings={"target": 4})

    compilation = AbstractNavigationCompiler().compile(descriptor, address, context)
    abstract_result = analyze_compiled_navigation(compilation)
    concrete_result = ContextualNavigator().navigate(descriptor, address, context)

    assert abstract_result.status is AbstractReachabilityStatus.MAY_BE_REACHABLE
    assert concrete_result.reached
    assert concrete_result.path == ("increment",) * 4
    assert verify_navigation_witness(descriptor, address, context, concrete_result)
    assert verify_abstract_compilation(descriptor, address, context, compilation)


def test_compiler_resolves_contextual_set_and_sequential_increment_updates() -> None:
    descriptor = ProcessDescriptor(
        "sequential",
        "1",
        (
            TransitionRule(
                "prepare",
                updates=(
                    StateUpdate(("count",), UpdateOperation.SET, ContextRef("base")),
                    StateUpdate(("count",), UpdateOperation.INCREMENT, 3),
                ),
            ),
        ),
        {"count": 0},
    )
    address = SemanticAddress("sequential", "1", StatePattern((_eq("count", 8),)))
    context = ProcessContext("sequential", bindings={"base": 5})

    compilation = AbstractNavigationCompiler().compile(descriptor, address, context)
    transition = compilation.program.transitions[0]
    expression = transition.assignments["count"]

    assert expression == LinearExpression.literal(8)
    assert analyze_compiled_navigation(compilation).status is AbstractReachabilityStatus.MAY_BE_REACHABLE


def test_compiler_uses_context_current_state_in_preference_to_descriptor_initial_state() -> None:
    descriptor = ProcessDescriptor(
        "current-state",
        "1",
        (TransitionRule("increment", updates=(StateUpdate(("count",), UpdateOperation.INCREMENT, 1),)),),
        {"count": 0},
    )
    address = SemanticAddress("current-state", "1", StatePattern((_eq("count", 3),)))
    context = ProcessContext("current-state", current_state={"count": 2})

    compilation = AbstractNavigationCompiler().compile(descriptor, address, context)

    assert compilation.program.initial_state.as_mapping()["count"].lower == 2
    assert compilation.program.initial_state.as_mapping()["count"].upper == 2
    assert analyze_compiled_navigation(compilation).status is AbstractReachabilityStatus.MAY_BE_REACHABLE


def test_compiler_proves_a_goal_unreachable_when_the_overapproximation_excludes_it() -> None:
    descriptor = ProcessDescriptor("fixed", "1", (), {"count": 0})
    address = SemanticAddress("fixed", "1", StatePattern((StateCondition(("count",), ConditionOperator.GE, 1),)))
    context = ProcessContext("fixed")

    result = analyze_compiled_navigation(AbstractNavigationCompiler().compile(descriptor, address, context))

    assert result.status is AbstractReachabilityStatus.PROVED_UNREACHABLE
    assert result.goal_dispositions == (("process", (ConstraintDisposition.REFUTED,)),)


def test_compiler_preserves_small_concrete_reachable_set_under_interval_widening() -> None:
    lower_bound = StateCondition(("x",), ConditionOperator.GE, -2)
    upper_bound = StateCondition(("x",), ConditionOperator.LE, 3)
    descriptor = ProcessDescriptor(
        "bounded-walk",
        "1",
        (
            TransitionRule(
                "decrement",
                StatePattern((StateCondition(("x",), ConditionOperator.GT, -2),)),
                (StateUpdate(("x",), UpdateOperation.INCREMENT, -1),),
            ),
            TransitionRule(
                "increment",
                StatePattern((StateCondition(("x",), ConditionOperator.LT, 3),)),
                (StateUpdate(("x",), UpdateOperation.INCREMENT, 1),),
            ),
        ),
        {"x": 0},
        invariants=(StatePattern((lower_bound, upper_bound)),),
    )
    address = SemanticAddress("bounded-walk", "1", StatePattern((StateCondition(("x",), ConditionOperator.EQ, 2),)))
    context = ProcessContext("bounded-walk")

    compilation = AbstractNavigationCompiler().compile(descriptor, address, context)
    result = analyze_compiled_navigation(compilation, widen_after=3)
    concrete = ContextualNavigator().navigate(descriptor, address, context)

    interval = dict(result.location_states)["process"].as_mapping()["x"]
    assert concrete.reached
    # The exact reachable integer states in this finite example are -2..3.
    assert interval.lower is None or interval.lower <= -2
    assert interval.upper is None or interval.upper >= 3
    assert result.status is AbstractReachabilityStatus.MAY_BE_REACHABLE
    assert result.goal_dispositions[0][1] == (ConstraintDisposition.UNKNOWN,)


@pytest.mark.parametrize("operation", [UpdateOperation.APPEND, UpdateOperation.COPY, UpdateOperation.DELETE])
def test_compiler_refuses_non_affine_update_operations(operation: UpdateOperation) -> None:
    kwargs = {"source_path": ("source",)} if operation is UpdateOperation.COPY else {}
    value = "item" if operation is UpdateOperation.APPEND else None
    descriptor = ProcessDescriptor(
        "unsupported-update",
        "1",
        (TransitionRule("mutate", updates=(StateUpdate(("items",), operation, value, **kwargs),)),),
        {"items": []},
    )
    address = SemanticAddress("unsupported-update", "1", StatePattern())
    context = ProcessContext("unsupported-update")

    with pytest.raises(NavigationCompilationError, match="outside the integer-affine subset"):
        AbstractNavigationCompiler().compile(descriptor, address, context)


def test_compiler_refuses_nested_paths_and_non_integer_comparisons() -> None:
    nested = ProcessDescriptor(
        "nested",
        "1",
        (),
        {"registers": {"r0": 0}},
    )
    nested_address = SemanticAddress("nested", "1", StatePattern((StateCondition(("registers", "r0"), ConditionOperator.EQ, 0),)))
    with pytest.raises(NavigationCompilationError, match="single-level"):
        AbstractNavigationCompiler().compile(nested, nested_address, ProcessContext("nested"))

    non_integer = ProcessDescriptor("non-integer", "1", (), {"mode": "cpu"})
    non_integer_address = SemanticAddress("non-integer", "1", StatePattern((_eq("mode", "cpu"),)))
    with pytest.raises(NavigationCompilationError, match="integer"):
        AbstractNavigationCompiler().compile(non_integer, non_integer_address, ProcessContext("non-integer"))


def test_compiler_rejects_boolean_and_float_numeric_operands() -> None:
    descriptor = ProcessDescriptor("typed", "1", (), {"count": 0})
    context = ProcessContext("typed")

    bool_address = SemanticAddress("typed", "1", StatePattern((_eq("count", True),)))
    float_address = SemanticAddress("typed", "1", StatePattern((_eq("count", 1.0),)))

    with pytest.raises(NavigationCompilationError, match="integer"):
        AbstractNavigationCompiler().compile(descriptor, bool_address, context)
    with pytest.raises(NavigationCompilationError, match="integer"):
        AbstractNavigationCompiler().compile(descriptor, float_address, context)


def test_compiler_refuses_referenced_non_integer_initial_state_fields() -> None:
    descriptor = ProcessDescriptor("float-state", "1", (), {"count": 0.5})
    address = SemanticAddress("float-state", "1", StatePattern((StateCondition(("count",), ConditionOperator.GT, 0),)))

    with pytest.raises(NavigationCompilationError, match="not an integer coordinate"):
        AbstractNavigationCompiler().compile(descriptor, address, ProcessContext("float-state"))


def test_compiler_allows_unreferenced_non_integer_json_fields() -> None:
    descriptor = ProcessDescriptor("projected", "1", (), {"count": 0, "metadata": {"mode": "cpu"}})
    address = SemanticAddress("projected", "1", StatePattern((_eq("count", 0),)))

    compilation = AbstractNavigationCompiler().compile(descriptor, address, ProcessContext("projected"))

    assert set(compilation.program.initial_state.as_mapping()) == {"count"}


def test_compilation_verifier_binds_context_and_source_descriptions() -> None:
    descriptor = ProcessDescriptor(
        "bound",
        "1",
        (TransitionRule("set", updates=(StateUpdate(("count",), UpdateOperation.SET, ContextRef("target")),)),),
        {"count": 0},
    )
    address = SemanticAddress("bound", "1", StatePattern((_eq("count", ContextRef("target")),)))
    context = ProcessContext("bound", bindings={"target": 7})
    compilation = AbstractNavigationCompiler().compile(descriptor, address, context)

    changed_context = ProcessContext("bound", bindings={"target": 8})
    changed_address = SemanticAddress("bound", "1", StatePattern((_eq("count", 8),)))

    assert verify_abstract_compilation(descriptor, address, context, compilation)
    assert not verify_abstract_compilation(descriptor, address, changed_context, compilation)
    assert not verify_abstract_compilation(descriptor, changed_address, context, compilation)
    assert not verify_abstract_compilation(replace(descriptor, version="2"), address, context, compilation)


def test_abstract_analysis_remains_distinct_from_concrete_path_and_execution_receipts() -> None:
    descriptor = ProcessDescriptor(
        "separate-evidence",
        "1",
        (TransitionRule("increment", updates=(StateUpdate(("count",), UpdateOperation.INCREMENT, 1),)),),
        {"count": 0},
    )
    address = SemanticAddress("separate-evidence", "1", StatePattern((_eq("count", 1),)))
    compilation = AbstractNavigationCompiler().compile(descriptor, address, ProcessContext("separate-evidence"))
    result = analyze_compiled_navigation(compilation)

    assert result.status is AbstractReachabilityStatus.MAY_BE_REACHABLE
    assert "path" not in result.to_dict()
    assert not hasattr(result, "witness")
