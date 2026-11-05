"""Adversarial tests for symbolic reachability, bisimulation, and causal dependency graphs."""

from __future__ import annotations

import pytest

from mailcpu.navigation_formal import (
    AbstractProgram,
    AbstractReachabilityAnalyzer,
    AbstractReachabilityStatus,
    AbstractState,
    AbstractTransition,
    BisimulationResult,
    CausalDependencyGraph,
    ConstraintDisposition,
    ConstraintRelation,
    FiniteTransitionSystem,
    FormalNavigationError,
    IntInterval,
    LabeledTransition,
    LinearConstraint,
    LinearExpression,
    compute_bisimulation,
    evaluate_causal_dependencies,
    verify_bisimulation_relation,
)
from mailcpu.temporal import CausalStamp


def test_linear_expression_normalizes_duplicate_terms_and_evaluates_exactly() -> None:
    """Canonical coefficient collection preserves exact integer affine evaluation."""
    expression = LinearExpression((("x", 2), ("y", -1), ("x", 3)), 4)

    assert expression.terms == (("x", 5), ("y", -1))
    assert expression.evaluate_exact({"x": 3, "y": 2}) == 17
    assert LinearExpression.from_dict(expression.to_dict()) == expression


def test_linear_interval_evaluation_is_sound_for_negative_coefficients() -> None:
    """Multiplication by a negative coefficient reverses interval endpoints."""
    expression = LinearExpression.variable("x").scale(-3) + 5
    interval = expression.evaluate({"x": IntInterval(2, 7)})

    assert interval == IntInterval(-16, -1)


def test_interval_hull_intersection_and_widening() -> None:
    """The interval domain joins paths and widens expanding loop bounds."""
    assert IntInterval(0, 2).hull(IntInterval(1, 5)) == IntInterval(0, 5)
    assert IntInterval(0, 10).intersect(IntInterval(5, 20)) == IntInterval(5, 10)
    assert IntInterval(0, 2).intersect(IntInterval(3, 8)) is None
    assert IntInterval(0, 2).widen(IntInterval(0, 3)) == IntInterval(0, None)
    assert IntInterval(2, 8).widen(IntInterval(1, 8)) == IntInterval(None, 8)


@pytest.mark.parametrize(
    ("relation", "bounds", "expected"),
    [
        (ConstraintRelation.EQ, {"x": IntInterval.point(0)}, ConstraintDisposition.ENTAILED),
        (ConstraintRelation.EQ, {"x": IntInterval(1, 4)}, ConstraintDisposition.REFUTED),
        (ConstraintRelation.NE, {"x": IntInterval(1, 4)}, ConstraintDisposition.ENTAILED),
        (ConstraintRelation.NE, {"x": IntInterval.point(0)}, ConstraintDisposition.REFUTED),
        (ConstraintRelation.LT, {"x": IntInterval(-4, -1)}, ConstraintDisposition.ENTAILED),
        (ConstraintRelation.LT, {"x": IntInterval(0, 4)}, ConstraintDisposition.REFUTED),
        (ConstraintRelation.LE, {"x": IntInterval(-4, 0)}, ConstraintDisposition.ENTAILED),
        (ConstraintRelation.GT, {"x": IntInterval(1, 4)}, ConstraintDisposition.ENTAILED),
        (ConstraintRelation.GE, {"x": IntInterval(-4, -1)}, ConstraintDisposition.REFUTED),
        (ConstraintRelation.GE, {"x": IntInterval(0, 4)}, ConstraintDisposition.ENTAILED),
        (ConstraintRelation.EQ, {"x": IntInterval(-1, 1)}, ConstraintDisposition.UNKNOWN),
    ],
)
def test_linear_constraint_interval_classification(relation, bounds, expected) -> None:
    """Constraint classification distinguishes entailment, contradiction, and uncertainty."""
    constraint = LinearConstraint(LinearExpression.variable("x"), relation)

    assert constraint.classify(bounds) is expected


def test_abstract_navigator_proves_guarded_branch_unreachable() -> None:
    """A guard contradicted by the current interval prevents abstract traversal."""
    program = AbstractProgram(
        "guarded",
        "1",
        "start",
        AbstractState.from_mapping({"x": IntInterval(0, 0)}),
        (
            AbstractTransition(
                "negative-only",
                "start",
                "accept",
                (LinearConstraint(LinearExpression.variable("x"), ConstraintRelation.LT),),
            ),
        ),
        ("accept",),
    )

    result = AbstractReachabilityAnalyzer().analyze(program)

    assert result.status is AbstractReachabilityStatus.PROVED_UNREACHABLE
    assert result.location_states == (("start", program.initial_state),)


def test_abstract_navigator_retains_possible_goal_without_claiming_concrete_reachability() -> None:
    """A widening loop retains an unbounded family as possible and emits no concrete path."""
    x = LinearExpression.variable("x")
    program = AbstractProgram(
        "increment-loop",
        "1",
        "loop",
        AbstractState.from_mapping({"x": 0}),
        (
            AbstractTransition(
                "increment",
                "loop",
                "loop",
                assignments={"x": x + 1},
            ),
        ),
        ("loop",),
        (LinearConstraint(x, ConstraintRelation.GE),),
    )
    goal = (LinearConstraint(x - 100, ConstraintRelation.GE),)

    result = AbstractReachabilityAnalyzer().analyze(program, goal)

    assert result.status is AbstractReachabilityStatus.MAY_BE_REACHABLE
    abstract_x = dict(result.location_states)["loop"].as_mapping()["x"]
    assert abstract_x.lower == 0
    assert abstract_x.upper is None
    assert result.goal_dispositions[0][1] == (ConstraintDisposition.UNKNOWN,)
    assert "path" not in result.to_dict()


def test_abstract_navigator_uses_simultaneous_assignments_from_pre_state() -> None:
    """Multiple affine assignments are evaluated against one common predecessor valuation."""
    program = AbstractProgram(
        "swap",
        "1",
        "start",
        AbstractState.from_mapping({"x": 1, "y": 9}),
        (
            AbstractTransition(
                "swap",
                "start",
                "accept",
                assignments={
                    "x": LinearExpression.variable("y"),
                    "y": LinearExpression.variable("x"),
                },
            ),
        ),
        ("accept",),
    )

    result = AbstractReachabilityAnalyzer().analyze(program)

    final = dict(result.location_states)["accept"].as_mapping()
    assert final == {"x": IntInterval.point(9), "y": IntInterval.point(1)}
    assert result.status is AbstractReachabilityStatus.MAY_BE_REACHABLE


def test_abstract_navigator_prunes_states_that_definitely_break_invariants() -> None:
    """An invariant is used for safe pruning only when interval analysis refutes it."""
    x = LinearExpression.variable("x")
    program = AbstractProgram(
        "positive",
        "1",
        "start",
        AbstractState.from_mapping({"x": 0}),
        (AbstractTransition("decrement", "start", "accept", assignments={"x": x - 1}),),
        ("accept",),
        (LinearConstraint(x, ConstraintRelation.GE),),
    )

    result = AbstractReachabilityAnalyzer().analyze(program)

    assert result.status is AbstractReachabilityStatus.PROVED_UNREACHABLE
    assert all(location != "accept" for location, _ in result.location_states)


def test_abstract_navigator_returns_inconclusive_at_update_budget() -> None:
    """An explicit analysis budget prevents a partially explored graph being called unreachable."""
    x = LinearExpression.variable("x")
    program = AbstractProgram(
        "branching",
        "1",
        "start",
        AbstractState.from_mapping({"x": 0}),
        (
            AbstractTransition("a", "start", "a", assignments={"x": x + 1}),
            AbstractTransition("b", "start", "b", assignments={"x": x + 2}),
        ),
        ("a", "b"),
    )

    result = AbstractReachabilityAnalyzer().analyze(program, max_updates=1)

    assert result.status is AbstractReachabilityStatus.INCONCLUSIVE


def test_abstract_program_digest_is_stable_under_transition_input_order() -> None:
    """Canonical rule sorting gives equivalent program descriptions the same digest."""
    initial = AbstractState.from_mapping({"x": 0})
    first = AbstractTransition("a", "start", "accept")
    second = AbstractTransition("b", "start", "accept")
    one = AbstractProgram("stable", "1", "start", initial, (first, second), ("accept",))
    two = AbstractProgram("stable", "1", "start", initial, (second, first), ("accept",))

    assert one.digest == two.digest


def test_strong_bisimulation_recognizes_different_internal_state_names() -> None:
    """Two differently named representations are equivalent when observations and labelled behavior match."""
    left = FiniteTransitionSystem(
        "left",
        "a",
        {"a": {"visible": 0}, "b": {"visible": 1}},
        (LabeledTransition("a", "advance", "b"),),
    )
    right = FiniteTransitionSystem(
        "right",
        "x",
        {"x": {"visible": 0}, "y": {"visible": 1}},
        (LabeledTransition("x", "advance", "y"),),
    )

    result = compute_bisimulation(left, right)

    assert result.equivalent
    assert result.relates("a", "x")
    assert result.relates("b", "y")
    assert verify_bisimulation_relation(left, right, result.relation)


def test_strong_bisimulation_detects_a_missing_observable_transition() -> None:
    """A representation is not equivalent when one side can perform an unmatched labelled action."""
    left = FiniteTransitionSystem(
        "left",
        "a",
        {"a": 0, "b": 1},
        (LabeledTransition("a", "advance", "b"),),
    )
    right = FiniteTransitionSystem(
        "right",
        "x",
        {"x": 0, "y": 1},
        (),
    )

    result = compute_bisimulation(left, right)

    assert not result.equivalent
    assert not result.relates("a", "x")


def test_bisimulation_relation_verifier_rejects_missing_state_pairs() -> None:
    """An explicit relation must include matching successors in both transition directions."""
    left = FiniteTransitionSystem(
        "left",
        "a",
        {"a": 0, "b": 1},
        (LabeledTransition("a", "go", "b"),),
    )
    right = FiniteTransitionSystem(
        "right",
        "x",
        {"x": 0, "y": 1},
        (LabeledTransition("x", "go", "y"),),
    )

    assert not verify_bisimulation_relation(left, right, (("a", "x"),))
    assert verify_bisimulation_relation(left, right, (("a", "x"), ("b", "y")))


def test_causal_dependency_graph_checks_vector_clock_precedence() -> None:
    """A dependency edge is ready only when its source stamp causally precedes its target stamp."""
    graph = CausalDependencyGraph(
        ("request", "compute", "reply"),
        (("request", "compute"), ("compute", "reply")),
    )
    request = CausalStamp.create("requester", 1, {"requester": 1})
    compute = CausalStamp.create("worker", 2, {"requester": 1, "worker": 1})
    reply = CausalStamp.create("requester", 3, {"requester": 2, "worker": 1})

    result = evaluate_causal_dependencies(
        graph,
        {"request": request, "compute": compute, "reply": reply},
    )

    assert result.ready
    assert result.topological_order == ("request", "compute", "reply")


def test_causal_dependency_graph_reports_missing_events() -> None:
    """An unobserved event remains a typed blocker rather than being inferred from elapsed time."""
    graph = CausalDependencyGraph(("request", "reply"), (("request", "reply"),))

    result = graph.evaluate({})

    assert not result.ready
    assert result.blockers == ("event:missing:reply", "event:missing:request")


def test_causal_dependency_graph_rejects_concurrent_or_reverse_edges() -> None:
    """Causal dependencies require BEFORE; concurrency and reverse order both fail closed."""
    graph = CausalDependencyGraph(("left", "right"), (("left", "right"),))
    left = CausalStamp.create("left", 1, {"left": 1})
    concurrent = CausalStamp.create("right", 1, {"right": 1})
    after = CausalStamp.create("left", 2, {"left": 2})

    result_concurrent = graph.evaluate({"left": left, "right": concurrent})
    result_reverse = graph.evaluate({"left": after, "right": left})

    assert not result_concurrent.ready
    assert result_concurrent.blockers == ("causality:left:concurrent:right",)
    assert not result_reverse.ready
    assert result_reverse.blockers == ("causality:left:after:right",)


def test_causal_dependency_graph_rejects_cycles_and_unknown_events() -> None:
    """Causal prerequisites must form a DAG over a closed event identity set."""
    with pytest.raises(FormalNavigationError, match="cycle"):
        CausalDependencyGraph(("a", "b"), (("a", "b"), ("b", "a")))
    graph = CausalDependencyGraph(("a",), ())
    with pytest.raises(FormalNavigationError, match="unknown"):
        graph.evaluate({"unknown": CausalStamp.create("actor", 1, {"actor": 1})})


def test_causal_dependency_graph_round_trips_deterministically() -> None:
    """Canonical event and edge ordering makes equivalent dependency graphs hash-identical."""
    left = CausalDependencyGraph(("c", "a", "b"), (("b", "c"), ("a", "b")))
    right = CausalDependencyGraph(("a", "b", "c"), (("a", "b"), ("b", "c")))

    assert left.to_dict() == right.to_dict()
    assert left.digest == right.digest


def test_interval_and_linear_expression_reject_boolean_coordinates() -> None:
    """Python Boolean values are excluded from every integer arithmetic primitive."""
    with pytest.raises(FormalNavigationError):
        IntInterval.point(True)
    with pytest.raises(FormalNavigationError):
        LinearExpression.literal(False)
    with pytest.raises(FormalNavigationError):
        AbstractState.from_mapping({"x": True})


def test_finite_transition_system_refuses_unknown_edge_endpoints_and_non_json_observations() -> None:
    """A finite LTS admits only closed state sets and finite JSON observations."""
    with pytest.raises(FormalNavigationError, match="unknown state"):
        FiniteTransitionSystem("bad", "a", {"a": 0}, (LabeledTransition("a", "go", "b"),))
    with pytest.raises(FormalNavigationError):
        FiniteTransitionSystem("bad", "a", {"a": float("nan")}, ())


def test_abstract_analyzer_does_not_claim_a_concrete_witness() -> None:
    """Abstract reachability results expose bounds and status but never a concrete path."""
    program = AbstractProgram(
        "one-step",
        "1",
        "start",
        AbstractState.from_mapping({"x": 0}),
        (AbstractTransition("go", "start", "accept", assignments={"x": LinearExpression.literal(5)}),),
        ("accept",),
    )

    result = AbstractReachabilityAnalyzer().analyze(program)

    assert result.status is AbstractReachabilityStatus.MAY_BE_REACHABLE
    assert "path" not in result.to_dict()
