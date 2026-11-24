"""ITR-003 integration tests use actual CIG-019 proofs and E-CPU placement."""
import copy

import pytest

from mailcpu.shared_intention_realization import SharedIntentionSession, evaluate_slice
from mailcpu.inverse_nonlinear_realization import NonlinearRealizationRefused, SourceObservation
from mailcpu.substrate_bootstrap import BootstrapRefused
from test_inverse_nonlinear_realization import capacity, gate_source, state_for, source_chain, source_chain_model


def seed():
    """Two nonlinear dependent gates and their complementary target."""
    goal = gate_source()
    targets = ((3,), (5,), (-5,))
    return goal, targets, SharedIntentionSession(goal.variables, goal.source, goal.observations, targets)


def test_shared_family_all_codes_and_output_cones():
    """Different goals use one verified proof; slice matches full CIG evaluator."""
    from shared_proof import evaluate
    goal, targets, session = seed()
    circuit = session.receipt()["circuit"]
    for code in range(8):
        a, b, c = (code >> i & 1 for i in range(3))
        expected = [a & b, (a & b) | c, 1-((a & b) | c)]
        assert evaluate(circuit, code, 3) == expected
        for ids in ((0,), (1,), (2,), (2, 0), (0, 1, 2)):
            got = session.realize(state_for(a,b,c), ids, capacity())
            assert got["values"] == [expected[i] for i in ids]
            assert got["proof"] == session.proof_digest
            assert got["evaluated_gates"] <= got["total_gates"]
            assert evaluate_slice(circuit, code, 3, ids)[0] == got["values"]


def test_dependency_cone_skips_unrelated_gates():
    """An early chain intention uses fewer gates than the full family."""
    goal = source_chain(12)
    targets = ((13,), (18,), (23,))
    session = SharedIntentionSession(goal.variables, goal.source, goal.observations, targets)
    one = session.realize(source_chain_model(12, 0xB63), (0,), capacity())
    all_ = session.realize(source_chain_model(12, 0xB63), (0,1,2), capacity())
    assert one["values"] == all_["values"][:1]
    assert one["evaluated_gates"] < all_["evaluated_gates"]
    assert one["ground"] == all_["ground"]
    assert one["goal"] != all_["goal"]


def test_new_host_keeps_same_shared_ground():
    """Re-place the same mathematical intention with no proof reconstruction."""
    _, _, s = seed()
    a = s.realize(state_for(1,1,0), (0,1), capacity())
    b = s.realize(state_for(1,1,0), (0,1), capacity(alpha=False))
    assert a["ground"] == b["ground"] and a["proof"] == b["proof"]
    assert a["values"] == b["values"]
    assert a["plan_digest"] != b["plan_digest"]
    assert "alpha" in a["hosts"] and "beta" in b["hosts"]


def test_unapproved_host_cannot_execute():
    """A capacity advertisement remains inert without receiver authority."""
    _, _, s = seed()
    with pytest.raises(BootstrapRefused):
        s.realize(state_for(1,1,0), (0,), capacity(alpha=False,beta=False,shadow=True))


def test_restore_checks_proof_and_source_and_goal_order():
    """New process/session may restore bytes, never inherit unchecked admission."""
    goal, targets, s = seed()
    proof = s.receipt()
    restored = SharedIntentionSession(goal.variables, goal.source, goal.observations, targets, receipt=proof)
    assert restored.ground_digest == s.ground_digest
    bad = copy.deepcopy(proof)
    bad["circuit"]["outputs"][0] *= -1
    for source, fs, receipt in ((goal.source,targets,bad),
                                (goal.source+((-5,),),targets,proof),
                                (goal.source,targets[::-1],proof)):
        with pytest.raises(NonlinearRealizationRefused):
            SharedIntentionSession(goal.variables, source, goal.observations, fs, receipt=receipt)
    proof["circuit"]["outputs"][0] *= -1
    assert s.receipt() != proof
    assert s.realize(state_for(1,1,0),(0,),capacity())["values"] == [1]


def test_insufficient_target_is_not_promoted_but_sufficient_sibling_executes():
    """Mixed batch has exactly the independently proved usable outputs."""
    s = SharedIntentionSession(3, ((-1,2),(1,-2)), ((1,),), ((2,), (3,)))
    assert s.receipt()["goals"][1]["status"] == "INSUFFICIENT"
    assert s.realize(SourceObservation(3),(0,),capacity())["values"] == [1]
    with pytest.raises(NonlinearRealizationRefused,match="not source-proved"):
        s.realize(SourceObservation(3),(0,1),capacity())


def test_unresolved_budget_refused():
    """A prefix search budget refusal cannot be admitted as a proof."""
    goal = source_chain(12)
    with pytest.raises(NonlinearRealizationRefused):
        SharedIntentionSession(goal.variables, goal.source, goal.observations, ((18,), (23,)), max_pairs=1)


def test_virtual_code_without_hidden_state_and_reused_section():
    """Total-image section is independently checked once, then reused across targets."""
    _, _, s = seed()
    a=s.realize_code(3,(0,),capacity())
    b=s.realize_code(4,(1,),capacity(alpha=False))
    assert a["section_constructed"] and not b["section_constructed"]
    assert a["values"] == b["values"] == [1]
    assert a["ground"] == b["ground"]
    with pytest.raises(NonlinearRealizationRefused):
        s.realize_code(8,(0,),capacity())


def test_invalid_source_and_indices_refused():
    """Refuse an incorrect original source witness and duplicate/bool targets."""
    _, _, s=seed()
    with pytest.raises(NonlinearRealizationRefused):
        s.realize(SourceObservation(4),(0,),capacity())
    for ids in ((),(True,),(-1,),(3,),(0,0)):
        with pytest.raises(NonlinearRealizationRefused):
            s.realize(state_for(1,1,0),ids,capacity())


def test_non_surjective_observation_cannot_use_total_image_route():
    """Sufficiency does not imply every observation code has a source model."""
    s=SharedIntentionSession(2, ((1,),), ((1,),), ((1,),))
    assert s.realize(SourceObservation(1),(0,),capacity())["values"] == [1]
    with pytest.raises(NonlinearRealizationRefused):
        s.realize_code(0,(0,),capacity())
