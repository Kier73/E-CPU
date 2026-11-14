"""IOS-002: native ObserverReceipt, freshness, authority and exact result conformance."""

from dataclasses import replace

import pytest

from mailcpu.intention_sufficiency import (
    FiniteGround, FiniteState, MeasurementCapability,
    SufficiencyRefused, plan_sufficiency,
)
from mailcpu.intention_observer_bridge import (
    issue_measurement_requests, resolve_observer_receipts, verify_observer_resolution,
)
from mailcpu.observer_orbit import ObserverContract, ObserverReceipt
from mailcpu.semantic_translation import ObservationContract, RepresentationRef, canonical_value_digest
from mailcpu.temporal import SchedulerReading, TemporalFrame


AUTHORITY = canonical_value_digest({"receiver": "trusted", "revision": 3})
CHALLENGE = canonical_value_digest({"request": "attempt-1", "nonce": "unique-per-session"})
OTHER_CHALLENGE = canonical_value_digest({"request": "attempt-2", "nonce": "different"})
SCHEDULER = SchedulerReading("test-receiver-scheduler", 41)


def fixture(*, target="parity", allowed=("parity", "low2"), at_state=2):
    subject = RepresentationRef.from_payload("test.subject", 1, {"ground": "finite", "role": "data"})
    ground = RepresentationRef.from_payload("test.ground", 1, {"transition": "identity-mod4"})
    context = canonical_value_digest({"tenant": "local", "epoch": 3})
    public = ObservationContract.from_definition("coarse", 1, {"projection": "state//2"})
    intention = ObservationContract.from_definition("intention", 1, {"projection": target})
    rows = tuple(FiniteState.create(
        str(i), i // 2, i % 2 if target == "parity" else i // 2,
        {"parity": i % 2, "low2": i % 4},
    ) for i in range(4))
    model = FiniteGround(ground.content_digest, public.projection_digest,
                         intention.projection_digest, context, rows)
    contracts = {}
    for feature in allowed:
        observation = ObservationContract.from_definition(feature, 1, {"projection": feature})
        contracts[feature] = ObserverContract(
            "observer." + feature, 1, subject, ground, observation, context,
        )
    offers = tuple(MeasurementCapability(feature, contracts[feature].digest,
                                        contracts[feature].observer_id,
                                        1 if feature == "parity" else 2)
                   for feature in allowed)
    return model, at_state // 2, offers, contracts, subject, at_state


def test_native_observer_receipt_reaches_resolution_after_trusted_receiver_acceptance():
    model, public, offers, contracts, subject, state = fixture()
    plan = plan_sufficiency(model, public, offers, AUTHORITY)
    assert plan["status"] == "MEASURE"
    assert plan["selected_features"] == ["parity"]
    selected = {"parity": contracts["parity"]}
    requests = issue_measurement_requests(model, public, offers, AUTHORITY, plan,
                                          selected, subject, SCHEDULER, CHALLENGE)
    assert len(requests) == 1
    req = requests[0]
    receipt = ObserverReceipt.issue(
        selected["parity"], operation_id="parity", input_digest=req["request_digest"],
        projection_value=state % 2,
        time_frame=TemporalFrame(selected["parity"].observer_id, scheduler=SCHEDULER),
    )
    trusted = {receipt.digest}
    def receiver_check(request, contract, evidence):
        return (request["challenge_digest"] == CHALLENGE
                and contract.observer_id == "observer.parity"
                and evidence.digest in trusted)
    report = resolve_observer_receipts(
        model, public, offers, AUTHORITY, plan, selected, subject,
        SCHEDULER, CHALLENGE, {"parity": receipt}, receiver_verify=receiver_check,
    )
    assert report["resolution"]["result"] == state % 2
    assert report["resolution"]["remaining_candidates"] == 1
    assert report["measurement_receipts"][0]["observer_receipt_digest"] == receipt.digest
    verify_observer_resolution(
        report, model, public, offers, AUTHORITY, plan, selected, subject,
        SCHEDULER, CHALLENGE, {"parity": receipt}, receiver_verify=receiver_check,
    )
    forged = {**report, "resolution": {**report["resolution"], "result": 1 - state % 2}}
    with pytest.raises(SufficiencyRefused, match="independent reconstruction"):
        verify_observer_resolution(
            forged, model, public, offers, AUTHORITY, plan, selected, subject,
            SCHEDULER, CHALLENGE, {"parity": receipt}, receiver_verify=receiver_check,
        )


def test_replayed_challenge_and_wrong_scheduler_are_rejected():
    model, public, offers, contracts, subject, state = fixture(at_state=3)
    plan = plan_sufficiency(model, public, offers, AUTHORITY)
    selected = {"parity": contracts["parity"]}
    req = issue_measurement_requests(model, public, offers, AUTHORITY, plan,
                                     selected, subject, SCHEDULER, CHALLENGE)[0]
    receipt = ObserverReceipt.issue(
        contracts["parity"], operation_id="parity", input_digest=req["request_digest"],
        projection_value=state % 2,
        time_frame=TemporalFrame(contracts["parity"].observer_id, scheduler=SCHEDULER),
    )
    with pytest.raises(SufficiencyRefused, match="another operation, request, or scheduler"):
        resolve_observer_receipts(model, public, offers, AUTHORITY, plan, selected, subject,
                                  SCHEDULER, OTHER_CHALLENGE, {"parity": receipt},
                                  receiver_verify=lambda *_: True)
    later = SchedulerReading("test-receiver-scheduler", 42)
    with pytest.raises(SufficiencyRefused, match="another operation, request, or scheduler"):
        resolve_observer_receipts(model, public, offers, AUTHORITY, plan, selected, subject,
                                  later, CHALLENGE, {"parity": receipt},
                                  receiver_verify=lambda *_: True)


def test_verifier_is_mandatory_and_forged_reading_requires_receiver_approval():
    model, public, offers, contracts, subject, state = fixture()
    plan = plan_sufficiency(model, public, offers, AUTHORITY)
    selected = {"parity": contracts["parity"]}
    req = issue_measurement_requests(model, public, offers, AUTHORITY, plan,
                                     selected, subject, SCHEDULER, CHALLENGE)[0]
    fake = ObserverReceipt.issue(
        contracts["parity"], operation_id="parity", input_digest=req["request_digest"],
        projection_value=1 - state % 2,
        time_frame=TemporalFrame(contracts["parity"].observer_id, scheduler=SCHEDULER),
    )
    with pytest.raises(SufficiencyRefused, match="verifier required"):
        resolve_observer_receipts(model, public, offers, AUTHORITY, plan, selected, subject,
                                  SCHEDULER, CHALLENGE, {"parity": fake})
    with pytest.raises(SufficiencyRefused, match="receiver refused"):
        resolve_observer_receipts(model, public, offers, AUTHORITY, plan, selected, subject,
                                  SCHEDULER, CHALLENGE, {"parity": fake},
                                  receiver_verify=lambda *_: False)
    with pytest.raises(SufficiencyRefused, match="receiver refused"):
        resolve_observer_receipts(model, public, offers, AUTHORITY, plan, selected, subject,
                                  SCHEDULER, CHALLENGE, {"parity": fake},
                                  receiver_verify=lambda *_: 1)


def test_wrong_contract_ground_provider_or_injected_receipts_rejected():
    model, public, offers, contracts, subject, state = fixture()
    plan = plan_sufficiency(model, public, offers, AUTHORITY)
    selected = {"parity": contracts["parity"]}
    req = issue_measurement_requests(model, public, offers, AUTHORITY, plan,
                                     selected, subject, SCHEDULER, CHALLENGE)[0]
    receipt = ObserverReceipt.issue(contracts["parity"], operation_id="parity",
                                    input_digest=req["request_digest"], projection_value=state % 2,
                                    time_frame=TemporalFrame("observer.parity", scheduler=SCHEDULER))
    with pytest.raises(SufficiencyRefused, match="unsolicited receipt"):
        resolve_observer_receipts(model, public, offers, AUTHORITY, plan, selected, subject,
                                  SCHEDULER, CHALLENGE, {"parity": receipt, "low2": receipt},
                                  receiver_verify=lambda *_: True)
    with pytest.raises(SufficiencyRefused, match="live observer contract differ"):
        issue_measurement_requests(model, public, offers, AUTHORITY, plan,
                                   {"parity": replace(contracts["parity"], observer_id="another")},
                                   subject, SCHEDULER, CHALLENGE)
    wrong_ground = RepresentationRef.from_payload("wrong.ground", 1, {"not": "ours"})
    with pytest.raises(SufficiencyRefused, match="live observer contract differ"):
        issue_measurement_requests(model, public, offers, AUTHORITY, plan,
                                   {"parity": replace(contracts["parity"], interpretation=wrong_ground)},
                                   subject, SCHEDULER, CHALLENGE)
    with pytest.raises(SufficiencyRefused, match="stale"):
        issue_measurement_requests(model, public, offers, canonical_value_digest({"policy": "new"}),
                                   plan, selected, subject, SCHEDULER, CHALLENGE)


def test_ready_uses_no_receipts_and_refuse_issues_no_request():
    model, public, offers, contracts, subject, _ = fixture(target="coarse", allowed=())
    plan = plan_sufficiency(model, public, offers, AUTHORITY)
    assert plan["status"] == "READY"
    requests = issue_measurement_requests(model, public, offers, AUTHORITY, plan,
                                          {}, subject, SCHEDULER, CHALLENGE)
    assert not requests
    result = resolve_observer_receipts(model, public, offers, AUTHORITY, plan,
                                       {}, subject, SCHEDULER, CHALLENGE, {})
    assert result["resolution"]["status"] == "RESOLVED_WITHOUT_MEASUREMENT"
    assert result["measurement_receipts"] == []

    model, public, offers, contracts, subject, _ = fixture(target="parity", allowed=())
    plan = plan_sufficiency(model, public, offers, AUTHORITY)
    assert plan["status"] == "REFUSE"
    with pytest.raises(SufficiencyRefused, match="insufficient intention"):
        issue_measurement_requests(model, public, offers, AUTHORITY, plan,
                                   {}, subject, SCHEDULER, CHALLENGE)


def test_native_receipt_uses_typed_context_and_rejects_non_finite_values():
    model, public, offers, contracts, subject, state = fixture()
    plan = plan_sufficiency(model, public, offers, AUTHORITY)
    selected = {"parity": contracts["parity"]}
    req = issue_measurement_requests(model, public, offers, AUTHORITY, plan,
                                     selected, subject, SCHEDULER, CHALLENGE)[0]
    receipt = ObserverReceipt.issue(
        contracts["parity"], operation_id="parity", input_digest=req["request_digest"],
        projection_value=float(state % 2),
        time_frame=TemporalFrame("observer.parity", scheduler=SCHEDULER),
    )
    with pytest.raises(SufficiencyRefused, match="exact finite JSON"):
        resolve_observer_receipts(model, public, offers, AUTHORITY, plan, selected, subject,
                                  SCHEDULER, CHALLENGE, {"parity": receipt},
                                  receiver_verify=lambda *_: True)
