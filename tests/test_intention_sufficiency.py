"""State-complete and adversarial conformance for finite observation sufficiency."""

from dataclasses import replace
import itertools
import pytest

from mailcpu.intention_sufficiency import (
    FiniteGround, FiniteState, MeasurementCapability, SufficiencyRefused,
    plan_sufficiency, resolve_sufficiency, verify_sufficiency_plan,
    verify_sufficiency_resolution,
)

H, G, P, T, C, A = (char * 64 for char in "abcdef")
BIG = 10**15 + 137


def jump(x, steps):
    """Independent logarithmic-time affine navigation modulo eight."""
    a, b, m, c = 1, 0, 5, 1
    while steps:
        if steps & 1:
            a, b = (m * a) % 8, (m * b + c) % 8
        m, c = (m * m) % 8, (m * c + c) % 8
        steps >>= 1
    return (a * x + b) % 8


def case(kind="parity", horizon=BIG, allowed=("parity", "low2"), state=6):
    def feature(x):
        return {"parity": x & 1, "bit1": (x >> 1) & 1, "low2": x & 3}

    def target(x):
        future = jump(x, horizon)
        return {"threshold": int(future >= 4), "parity": (3 * future + 11) % 2,
                "full": (3 * future + 11) % 8}[kind]

    rows = tuple(FiniteState.create(str(i), int(i >= 4), target(i), feature(i)) for i in range(8))
    model = FiniteGround(G, P, T, C, rows)
    offers = tuple(MeasurementCapability(name, H, "receiver", {"low2": 2}.get(name, 1))
                   for name in allowed)
    return model, int(state >= 4), offers, feature(state), target(state)


def test_gci003_ready_periodic_intention_every_phase():
    for phase in range(8):
        model, public, offers, _, target = case("threshold", BIG - 1, (), phase)
        plan = plan_sufficiency(model, public, offers, A)
        assert plan["status"] == "READY" and plan["selected_features"] == []
        assert resolve_sufficiency(model, public, offers, A, plan, {})["result"] == target


def test_gci003_measure_parity_every_phase():
    for phase in range(8):
        model, public, offers, features, target = case(state=phase)
        plan = plan_sufficiency(model, public, offers, A)
        assert plan["status"] == "MEASURE" and plan["selected_features"] == ["parity"]
        readings = {"parity": features["parity"]}
        result = resolve_sufficiency(model, public, offers, A, plan, readings, H)
        assert result["result"] == target and result["remaining_candidates"] == 2
        verify_sufficiency_resolution(result, model, public, offers, A, plan, readings, H)


def test_gci003_tie_breaker_and_refusal_counterexample():
    model, public, offers, features, target = case("threshold", 1, ("bit1", "parity", "low2"))
    plan = plan_sufficiency(model, public, offers, A)
    assert plan["selected_features"] == ["low2"] and plan["declared_cost_units"] == 2
    assert resolve_sufficiency(model, public, offers, A, plan, {"low2": features["low2"]}, H)["result"] == target
    model, public, offers, _, _ = case("full", BIG, ("parity",))
    refused = plan_sufficiency(model, public, offers, A)
    assert refused["status"] == "REFUSE"
    x, y = refused["counterexample_state_ids"]
    rows = {row.state_id: row for row in model.states}
    assert rows[x].target_json != rows[y].target_json
    assert rows[x].features["parity"] == rows[y].features["parity"]
    with pytest.raises(SufficiencyRefused):
        resolve_sufficiency(model, public, offers, A, refused, {})


def test_stale_and_forged_plans_and_resolutions_are_refused():
    model, public, offers, features, _ = case()
    plan = plan_sufficiency(model, public, offers, A)
    for settings in ((model, public, offers, H),
                     (replace(model, ground_digest=H), public, offers, A),
                     (model, public, (replace(offers[0], provider_id="other"), offers[1]), A),
                     (model, public, (replace(offers[0], cost_units=99), offers[1]), A)):
        with pytest.raises(SufficiencyRefused):
            verify_sufficiency_plan(plan, *settings)
    forged = dict(plan, status="READY", ready_result=0, selected_features=[])
    from mailcpu.intention_sufficiency import _fingerprint
    forged["plan_digest"] = _fingerprint({k: v for k, v in forged.items() if k != "plan_digest"})
    with pytest.raises(SufficiencyRefused):
        verify_sufficiency_plan(forged, model, public, offers, A)
    readings = {"parity": features["parity"]}
    result = resolve_sufficiency(model, public, offers, A, plan, readings, H)
    with pytest.raises(SufficiencyRefused):
        verify_sufficiency_resolution(dict(result, result=77), model, public, offers, A, plan, readings, H)


def test_invalid_measurements_and_model_inputs_are_refused():
    model, public, offers, features, _ = case()
    plan = plan_sufficiency(model, public, offers, A)
    for readings, receipt in (({}, H), ({"parity": features["parity"]}, None),
                              ({"parity": 44}, H), ({"parity": False}, H),
                              ({"parity": 1, "low2": 1}, H)):
        with pytest.raises(SufficiencyRefused):
            resolve_sufficiency(model, public, offers, A, plan, readings, receipt)
    for illegal in (float("nan"), 2**64, 3.4, "\ud800"):
        with pytest.raises(SufficiencyRefused):
            FiniteState.create("a", "public", illegal, {"f": 1})
    with pytest.raises(SufficiencyRefused):
        FiniteGround(G, P, T, C, (model.states[0], model.states[0]))
    with pytest.raises(SufficiencyRefused):
        plan_sufficiency(model, 99, offers, A)


def test_minimum_set_against_independent_enumeration_all_16_boolean_targets():
    for mask in range(16):
        rows = tuple(FiniteState.create(str(i), "public", mask >> i & 1,
                                        {"a": i & 1, "b": i >> 1, "full": i}) for i in range(4))
        model = FiniteGround(G, P, T, C, rows)
        offers = [MeasurementCapability("b", H, "host", 1), MeasurementCapability("a", H, "host", 1),
                  MeasurementCapability("full", H, "host", 2)]
        plan = plan_sufficiency(model, "public", offers, A)
        possible = []
        for count in range(4):
            for subset in itertools.combinations(sorted(offers, key=lambda x: x.feature_id), count):
                names = tuple(x.feature_id for x in subset)
                partitions = {}
                for row in rows:
                    key = tuple(row.features[n] for n in names)
                    partitions.setdefault(key, set()).add(row.target_json)
                if all(len(values) == 1 for values in partitions.values()):
                    possible.append((sum(x.cost_units for x in subset), count, names))
        cost, _, names = min(possible)
        assert (plan["declared_cost_units"], plan["selected_features"]) == (cost, list(names))


def test_existing_ecpu_navigator_and_semantic_digest_conformance():
    from mailcpu.law_certifier import lcg_navigate
    from mailcpu.semantic_translation import canonical_value_digest
    for state in range(8):
        for h in (0, 1, 8, BIG - 1, BIG):
            assert jump(state, h) == lcg_navigate(5, 1, 8, state, h)
    model, public, offers, _, _ = case()
    assert model.digest == canonical_value_digest(model.to_dict())
    assert plan_sufficiency(model, public, offers, A)["public_digest"] == canonical_value_digest(public)
