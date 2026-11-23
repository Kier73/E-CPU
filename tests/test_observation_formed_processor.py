"""ONP-001: observation alone supplies the source law for processor construction.

The source coefficients belong exclusively to the private sensor fixture; the
constructor only sees an observer intention, qualified probe offers, a static
primitive palette and authenticated measured values.
"""
from __future__ import annotations

from dataclasses import replace
from copy import deepcopy

import pytest

from mailcpu.computation_dag import NavigableComputationDAG
from mailcpu.evidence_path_resolver import RouteMetric
from mailcpu.generative_ground_construction import AffinePrimitive
from mailcpu.ground_native_realization import RealizationPolicy, RealizationRefused
from mailcpu.inverse_architecture_synthesis import ProposedRelation
from mailcpu.observation_formed_processor import (
    ObservationFormationRefused, ObserverConstructionIntention, ProbeOffer,
    realize_observed_processor, sign_observation, verify_observation,
    verify_observed_processor,
)
from mailcpu.semantic_translation import RepresentationRef

SOURCE = "b"*64
AUTHORITY = "a"*64
KEY = bytes(range(32))


def relation():
    return ProposedRelation(
        "e"*64,
        RepresentationRef.from_payload("onp001.state", 1, {"form": "original"}),
        RepresentationRef.from_payload("onp001.state", 1, {"form": "realized"}),
        "f"*64, "c"*64, "d"*64,
        (RouteMetric("latency_us", "us", 2),),
    )


def request(modulus=13, query=9, source=SOURCE):
    return ObserverConstructionIntention(
        relation(), source, "intention-reader", AUTHORITY, modulus, query,
    )


def offers(req=None, *, positions=(0, 1, 2, 4), costs=(1, 1, 4, 6)):
    req = req or request()
    return tuple(
        ProbeOffer(req.source_digest, "signed-local-source", pos, cost)
        for pos, cost in zip(positions, costs)
    )


def palette(modulus=13):
    return (
        AffinePrimitive("pre", modulus, 3 % modulus, 2 % modulus),
        AffinePrimitive("post", modulus, 8 % modulus, 5 % modulus),
        AffinePrimitive("shift", modulus, 1, 1),
    )


def policy():
    return RealizationPolicy(frozenset({("onp001-local", "port")}), expires_at=10)


def sensors(*, modulus=13, a=11, c=8, tamper=None, key=KEY, counter=None):
    """Test-only actual sensor. Its law stays inside the measurement provider."""
    log = counter if counter is not None else []
    def sensor(intent, offer, nonce, timestamp):
        log.append(offer.point)
        value = (a*offer.point+c) % modulus
        if tamper is not None:
            value = tamper(offer.point, value) % modulus
        return sign_observation(
            intent, offer, nonce, value,
            issued_at=timestamp, expires_at=timestamp+20, secret=key,
        )
    return {"signed-local-source": sensor}, log


def run(*, req=None, primitive_palette=None, probe_offers=None,
        sensor=None, keys=None, local_policy=None):
    req = req or request()
    if sensor is None:
        sensor, _ = sensors(modulus=req.modulus)
    n = iter(range(1, 100))
    return realize_observed_processor(
        req, probe_offers or offers(req), sensor,
        keys or {"signed-local-source": KEY},
        primitive_palette if primitive_palette is not None else palette(req.modulus),
        local_policy or policy(),
        clock=lambda: 10,
        nonce_factory=lambda: f"{next(n):032x}",
    )


def verify(report, *, req=None, probe_offers=None, primitive_palette=None,
           keys=None, now=10):
    req = req or request()
    return verify_observed_processor(
        report, req, probe_offers or offers(req),
        primitive_palette if primitive_palette is not None else palette(req.modulus),
        policy(), keys or {"signed-local-source": KEY}, now=now,
    )


def test_observation_forms_program_and_executes_unobserved_target():
    """The constructor is not given the coefficients 11,8 or any chosen word."""
    sensor, touched = sensors()
    got = run(sensor=sensor)
    assert got.sufficiency_plan["status"] == "MEASURE"
    assert got.sufficiency_plan["candidate_count"] == 13**2
    assert got.sufficiency_plan["selected_features"] == [
        "affine.point.00", "affine.point.01",
    ]
    assert touched == [0, 1, 2]  # source was NOT queried at requested x=9
    assert got.sufficiency_resolution["remaining_candidates"] == 1
    assert got.sufficiency_resolution["result"] == {"multiplier": 11, "offset": 8}
    assert got.construction_plan.primitive_names == ("pre", "post")
    assert got.construction_plan.optimal_within_palette
    assert got.realization.output == (11*9+8)%13
    assert len(got.realization.port_frames) == 2
    assert NavigableComputationDAG.from_snapshot(got.realization.dag_snapshot).is_complete
    assert got.realization.ground_receipt["output"]["value"] == got.realization.output
    assert verify(got) is True
    assert got.digest == got.digest
    assert got.to_dict()["schema"] == "mailcpu.observation-formed-processor.v1.realization"


def test_observation_ground_has_no_algorithm_until_measured():
    """No source coefficients or selected operator word exist in the request."""
    intent = request()
    assert "multiplier" not in intent.to_dict()
    assert "offset" not in intent.to_dict()
    assert "pre" not in str(intent.to_dict())
    received = run()
    assert received.synthesized_intention.coefficients == (11, 8)
    assert received.construction_plan.primitive_names == ("pre", "post")


def test_sufficiency_refuses_indistinguishable_one_coordinate():
    req = request()
    witness_offers = offers(req, positions=(0, 4, 8), costs=(1, 1, 1))
    sensor, log = sensors()
    with pytest.raises(ObservationFormationRefused, match="permitted observations"):
        run(req=req, probe_offers=witness_offers, sensor=sensor)
    assert log == []  # no demand for observations without a provable plan


def test_composite_modulus_requires_distinguishing_gcd_one_pair():
    req = request(12, 9)
    witness_offers = offers(req, positions=(0, 1, 2, 4), costs=(1, 5, 1, 1))
    primitive = (AffinePrimitive("law", 12, 5, 2),)
    sensor, log = sensors(modulus=12, a=5, c=2)
    got = run(req=req, probe_offers=witness_offers,
              primitive_palette=primitive, sensor=sensor)
    assert got.sufficiency_plan["selected_features"] == [
        "affine.point.00", "affine.point.01",
    ]
    assert log == [0, 1, 2]
    assert got.construction_plan.primitive_names == ("law",)
    assert got.realization.output == (5*9+2)%12
    assert verify(got, req=req, probe_offers=witness_offers,
                  primitive_palette=primitive)


def test_heldout_non_affine_sensor_refuses_before_native_execution():
    """Two anchors fit an affine model; a third active observation falsifies it."""
    sensor, log = sensors(tamper=lambda x, value: value+1 if x == 2 else value)
    with pytest.raises(ObservationFormationRefused, match="contradictory_description"):
        run(sensor=sensor)
    assert log == [0, 1, 2]


def test_bad_signature_source_pin_and_stale_measurement_are_rejected():
    wrong, log = sensors(key=b"X"*32)
    with pytest.raises(ObservationFormationRefused, match="authentication"):
        run(sensor=wrong)
    assert log == [0]
    intent = request()
    offer = offers(intent)[0]
    signed = sign_observation(intent, offer, "1"*32, 8,
                               issued_at=10, expires_at=20, secret=KEY)
    with pytest.raises(ObservationFormationRefused, match="unadmitted"):
        verify_observation(intent, offer, signed,
                           {"signed-local-source": KEY}, now=21)
    with pytest.raises(ObservationFormationRefused, match="unadmitted"):
        verify_observation(intent, offer, signed,
                           {"signed-local-source": KEY}, now=12,
                           expected_nonce="2"*32)
    wrong_intent = request(source="1"*64)
    with pytest.raises(ObservationFormationRefused, match="unadmitted"):
        verify_observation(wrong_intent, offer, signed,
                           {"signed-local-source": KEY}, now=12)


def test_native_permission_refuses_before_any_source_observation():
    sensor, log = sensors()
    with pytest.raises(RealizationRefused):
        run(sensor=sensor,
            local_policy=RealizationPolicy(frozenset(), expires_at=10))
    assert log == []


def test_unconstructible_palette_cannot_turn_measured_wish_into_execution():
    sensor, log = sensors()
    with pytest.raises(ObservationFormationRefused, match="not_derivable"):
        run(sensor=sensor, primitive_palette=())
    assert log == [0, 1, 2]


def test_duplicate_or_target_probe_disallowed_without_measurement():
    intent = request()
    sensor, log = sensors()
    with pytest.raises(ObservationFormationRefused, match="duplicate"):
        run(req=intent, sensor=sensor, probe_offers=offers(
            intent, positions=(0, 0, 2), costs=(1, 2, 3)))
    with pytest.raises(ObservationFormationRefused, match="direct-target"):
        run(req=intent, sensor=sensor, probe_offers=offers(
            intent, positions=(0, 1, 9), costs=(1, 2, 3)))
    assert log == []


def test_tampered_signed_witness_and_native_receipt_refused_by_reconstructor():
    good = run()
    modified = deepcopy(good.measurement_witnesses[0])
    modified["value"] = (modified["value"]+1)%13
    with pytest.raises(ObservationFormationRefused):
        verify(replace(good, measurement_witnesses=(
            modified, *good.measurement_witnesses[1:],
        )))
    wrong = deepcopy(good.realization.ground_receipt)
    wrong["output"]["value"] = (good.realization.output+1)%13
    with pytest.raises(ObservationFormationRefused):
        verify(replace(good, realization=replace(
            good.realization, ground_receipt=wrong,
        )))
    with pytest.raises(ObservationFormationRefused):
        verify(replace(good, model_digest="a"*64))
    with pytest.raises(ObservationFormationRefused):
        verify(good, keys={"signed-local-source": b"0"*32})


def test_observer_intention_changes_without_moving_source_law():
    """Different target coordinates form different execution intentions."""
    sensor1, observed1 = sensors()
    sensor2, observed2 = sensors()
    req1, req2 = request(query=9), request(query=10)
    # Destination cannot be one of the requested probe coordinates.
    first = run(req=req1, sensor=sensor1)
    second = run(req=req2, sensor=sensor2)
    assert observed1 == observed2 == [0, 1, 2]
    assert first.synthesized_intention.coefficients == second.synthesized_intention.coefficients
    assert first.intention.digest != second.intention.digest
    assert first.realization.output != second.realization.output
    assert first.construction_plan.primitive_names == second.construction_plan.primitive_names
