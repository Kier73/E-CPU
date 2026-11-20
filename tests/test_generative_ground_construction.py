"""IPS-003: synthesize and locally realize a Ground from imposed behavior."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from itertools import product
import random

import pytest

from mailcpu.computation_dag import NavigableComputationDAG
from mailcpu.evidence_path_resolver import EvidencePathCatalogue, RouteMetric
from mailcpu.ground_native_realization import (
    RealizationPolicy, RealizationRefused, TwoPortArithmeticGate,
)
from mailcpu.inverse_architecture_synthesis import ProposedRelation
from mailcpu.semantic_translation import RepresentationRef, canonical_value_digest
from mailcpu.generative_ground_construction import (
    AffineBehaviorIntention, AffinePrimitive, GroundConstructionError,
    compile_ground_dag, execute_ground_construction, synthesize_ground,
    verify_ground_construction, verify_ground_plan,
)

GROUND = "b" * 64
CONTEXT = "c" * 64
VERIFIER = "d" * 64


def _relation() -> ProposedRelation:
    """Declare a missing IPS-002 relation without qualifying a native route."""
    return ProposedRelation(
        "e" * 64,
        RepresentationRef.from_payload("ips003.state", 1, {"form": "source"}),
        RepresentationRef.from_payload("ips003.state", 1, {"form": "target"}),
        GROUND, CONTEXT, VERIFIER, (RouteMetric("latency_us", "us", 2),),
    )


def _goal(a: int = 7, c: int = 4, m: int = 17, x: int = 9,
          challenges: tuple[tuple[int, int], ...] = ()) -> AffineBehaviorIntention:
    """Describe a finite affine system using two defining observations."""
    return AffineBehaviorIntention(
        _relation(), m, c % m, (a + c) % m, x % m, challenges
    )


def _palette() -> tuple[AffinePrimitive, ...]:
    """Offer two necessary, separately specified computational primitives."""
    return (
        AffinePrimitive("first", 17, 3, 2),
        AffinePrimitive("second", 17, 8, 5),
        AffinePrimitive("distractor", 17, 1, 1),
    )


def _policy(locus: str = "ips003-local") -> RealizationPolicy:
    """Allow this local simulated active port, without creating Hypervisor rights."""
    return RealizationPolicy(frozenset({(locus, "port")}), expires_at=10)


def test_intention_derives_missing_map_and_executable_dag() -> None:
    """Two imposed constraints generate a route-independent exact virtual map."""
    goal = _goal(challenges=((2, 1), (16, 14)))
    plan = synthesize_ground(goal, _palette())
    assert plan.status == "constructed_exact_affine_ground"
    assert (plan.target_multiplier, plan.target_offset) == (7, 4)
    assert plan.primitive_names == ("first", "second")
    assert plan.symbolic_cost == 2
    assert plan.optimal_within_palette
    assert not plan.authoritative
    assert verify_ground_plan(plan, goal, _palette())
    graph = compile_ground_dag(plan, goal, _palette())
    assert len(graph.nodes) == 2
    assert [node.node_id for node in graph.ready_nodes()] == ["ips003.stage.000"]
    assert graph.nodes[1].dependencies == ("ips003.stage.000",)

    catalogue = EvidencePathCatalogue()
    assert not catalogue.edges
    observed = execute_ground_construction(
        plan, goal, _palette(), TwoPortArithmeticGate("port", goal.modulus), _policy()
    )
    assert observed.output == (7 * 9 + 4) % 17
    assert len(observed.port_frames) == 2
    assert not observed.authoritative
    assert verify_ground_construction(observed, plan, goal, _palette(), _policy())
    assert NavigableComputationDAG.from_snapshot(observed.dag_snapshot).is_complete
    # The caller still has a missing native relation: a local mathematical
    # result is not evidence of a remote admitted communication path.
    assert len(catalogue.edges) == 0
    assert goal.relation.relation_id == "e" * 64


def test_receiver_permission_refusal_precedes_port_side_effects() -> None:
    """An unpermitted local realizer is never invoked by the construction."""
    goal = _goal()
    plan = synthesize_ground(goal, _palette())
    port = TwoPortArithmeticGate("port", goal.modulus)
    wrong = _policy("other-locus")
    with pytest.raises(RealizationRefused):
        execute_ground_construction(plan, goal, _palette(), port, wrong)
    assert port.sequence == 0


def test_host_modulus_and_reused_port_refuse() -> None:
    """A claim cannot silently execute against a different or dirty gate."""
    goal = _goal()
    plan = synthesize_ground(goal, _palette())
    with pytest.raises(GroundConstructionError):
        execute_ground_construction(
            plan, goal, _palette(), TwoPortArithmeticGate("bad", 19), _policy()
        )
    port = TwoPortArithmeticGate("port", goal.modulus)
    port.invoke("apply", {"map": [1, 0], "input": 1})
    with pytest.raises(GroundConstructionError):
        execute_ground_construction(plan, goal, _palette(), port, _policy())


def test_independent_challenge_rejects_contradictory_specification() -> None:
    """Two anchors do not justify an arbitrary non-affine extra constraint."""
    goal = _goal(challenges=((2, 0),))
    plan = synthesize_ground(goal, _palette())
    assert plan.status == "contradictory_description"
    with pytest.raises(GroundConstructionError):
        compile_ground_dag(plan, goal, _palette())


def test_incomplete_palette_and_budgets_are_distinct() -> None:
    """Closed palette failure differs from bounded search uncertainty."""
    goal = _goal()
    assert synthesize_ground(goal, ()).status == "not_derivable_in_supplied_palette"
    assert synthesize_ground(goal, _palette(), max_depth=1).status == "budget_exhausted"
    assert synthesize_ground(goal, _palette(), max_states=1).status == "budget_exhausted"
    with pytest.raises(GroundConstructionError):
        synthesize_ground(goal, _palette(), max_states=0)


def test_identity_system_is_constructed_without_unneeded_gate_steps() -> None:
    """A description of the identity system needs no invented work."""
    goal = _goal(a=1, c=0)
    plan = synthesize_ground(goal, ())
    assert plan.status == "constructed_exact_affine_ground"
    assert plan.primitive_names == ()
    graph = compile_ground_dag(plan, goal, ())
    assert graph.nodes[0].operation == "affine.identity"
    receipt = execute_ground_construction(
        plan, goal, (), TwoPortArithmeticGate("port", goal.modulus), _policy()
    )
    assert receipt.output == goal.query_input
    assert len(receipt.port_frames) == 0
    assert verify_ground_construction(receipt, plan, goal, (), _policy())


def test_tampered_and_rehashed_dag_rejected_against_desired_behavior() -> None:
    """A valid native DAG checksum does not make a false operation true."""
    goal, palette = _goal(), _palette()
    plan = synthesize_ground(goal, palette)
    observed = execute_ground_construction(
        plan, goal, palette, TwoPortArithmeticGate("port", goal.modulus), _policy()
    )
    altered_frame = list(deepcopy(observed.port_frames))
    altered_frame[0]["output_digest"] = "0" * 64
    assert not verify_ground_construction(
        replace(observed, port_frames=tuple(altered_frame)),
        plan, goal, palette, _policy()
    )
    altered_oracle = deepcopy(observed.ground_receipt)
    altered_oracle["output"]["value"] = 0
    assert not verify_ground_construction(
        replace(observed, ground_receipt=altered_oracle),
        plan, goal, palette, _policy()
    )

    # Forge an internally hash-consistent native DAG checkpoint using its
    # legitimate commit interface but with the WRONG first numeric result.
    forged = compile_ground_dag(plan, goal, palette)
    first = {p.name: p for p in palette}[plan.primitive_names[0]]
    fake = (first.multiplier * goal.query_input + first.offset + 1) % goal.modulus
    forged.commit("ips003.stage.000", {
        "input": goal.query_input, "value": fake, "primitive_digest": first.digest,
    })
    second = {p.name: p for p in palette}[plan.primitive_names[1]]
    forged.commit("ips003.stage.001", {
        "input": fake, "value": (second.multiplier * fake + second.offset) % goal.modulus,
        "primitive_digest": second.digest,
    })
    forged_snapshot = forged.snapshot()
    assert NavigableComputationDAG.from_snapshot(forged_snapshot).is_complete
    assert not verify_ground_construction(
        replace(observed, dag_snapshot=forged_snapshot),
        plan, goal, palette, _policy()
    )


def test_intention_or_primitive_revision_invalidates_plan_and_receipt() -> None:
    """Changing the needed behavior or primitive description changes the Ground."""
    goal, palette = _goal(), _palette()
    plan = synthesize_ground(goal, palette)
    observed = execute_ground_construction(
        plan, goal, palette, TwoPortArithmeticGate("port", goal.modulus), _policy()
    )
    changed_goal = _goal(a=5, c=4)
    assert not verify_ground_plan(plan, changed_goal, palette)
    assert not verify_ground_construction(observed, plan, changed_goal, palette, _policy())
    revised = (replace(palette[0], offset=3),) + palette[1:]
    assert not verify_ground_plan(plan, goal, revised)
    assert not verify_ground_construction(observed, plan, goal, revised, _policy())


def test_incompatible_modulus_and_duplicate_palette_reject() -> None:
    """Never combine operators over distinct Ground arithmetic domains."""
    goal, palette = _goal(), _palette()
    with pytest.raises(GroundConstructionError):
        synthesize_ground(goal, palette + (palette[0],))
    with pytest.raises(GroundConstructionError):
        synthesize_ground(goal, (replace(palette[0], modulus=19),))
    with pytest.raises(GroundConstructionError):
        AffineBehaviorIntention(_relation(), 1, 0, 0, 0)
    with pytest.raises(GroundConstructionError):
        AffinePrimitive("bad-name!", 17, 1, 2)


def test_randomized_independent_operator_word_oracle() -> None:
    """Compare 40 independently enumerated minimal constructions with native search."""
    rng = random.Random(1703)
    for trial in range(40):
        m = 7
        palette = tuple(
            AffinePrimitive(f"op{i}", m, rng.randrange(m), rng.randrange(m),
                            rng.randint(1, 3))
            for i in range(3)
        )
        target_word = tuple(rng.choice(palette) for _ in range(rng.randrange(4)))
        a, c = 1, 0
        for p in target_word:
            a, c = (p.multiplier * a) % m, (p.multiplier * c + p.offset) % m
        goal = _goal(a, c, m=m, x=rng.randrange(m))
        plan = synthesize_ground(goal, palette, max_depth=4, max_states=256)
        oracle = []
        for depth in range(5):
            for word in product(palette, repeat=depth):
                aa, cc = 1, 0
                for p in word:
                    aa, cc = (p.multiplier * aa) % m, (p.multiplier * cc + p.offset) % m
                if (aa, cc) == (a, c):
                    oracle.append((sum(p.symbolic_cost for p in word), depth,
                                   tuple(p.name for p in word)))
        assert oracle, trial
        expected = min(oracle)
        assert plan.status == "constructed_exact_affine_ground", trial
        assert (plan.symbolic_cost, len(plan.primitive_names),
                plan.primitive_names) == expected, trial
