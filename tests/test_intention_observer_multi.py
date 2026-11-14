"""IOS-002 multi-observer AND-sufficiency: both admitted measurements are necessary."""

import pytest

from mailcpu.intention_sufficiency import (
    FiniteGround, FiniteState, MeasurementCapability, SufficiencyRefused, plan_sufficiency,
)
from mailcpu.intention_observer_bridge import (
    issue_measurement_requests, resolve_observer_receipts, verify_observer_resolution,
)
from mailcpu.observer_orbit import ObserverContract, ObserverReceipt
from mailcpu.semantic_translation import (
    ObservationContract, RepresentationRef, canonical_value_digest,
)
from mailcpu.temporal import SchedulerReading, TemporalFrame


def test_two_separate_native_observers_required_to_determine_one_intention():
    """Mathematics: bit0 and bit1 together refine a four-state fiber to a unique target."""
    context = canonical_value_digest({"domain": "multi-observer", "revision": 1})
    authority = canonical_value_digest({"policy": "receiver-current"})
    challenge = canonical_value_digest({"measurement": "fresh-challenge"})
    scheduler = SchedulerReading("receiver-logic", 101)
    subject = RepresentationRef.from_payload("test.subject", 1, {"object": "four-state"})
    ground = RepresentationRef.from_payload("test.ground", 1, {"laws": "finite-identity"})
    rows = tuple(FiniteState.create(str(i), 0, i,
                                    {"bit0": i & 1, "bit1": (i >> 1) & 1})
                 for i in range(4))
    model = FiniteGround(
        ground.content_digest,
        canonical_value_digest({"public": "always zero"}),
        canonical_value_digest({"target": "full two-bit integer"}),
        context, rows,
    )
    contracts = {}
    offers = []
    for feature in ("bit0", "bit1"):
        projection = ObservationContract.from_definition(feature, 1, {"feature": feature})
        contract = ObserverContract("observer." + feature, 1, subject, ground, projection, context)
        contracts[feature] = contract
        offers.append(MeasurementCapability(feature, contract.digest, contract.observer_id, 1))

    plan = plan_sufficiency(model, 0, offers, authority)
    assert plan["status"] == "MEASURE"
    assert plan["selected_features"] == ["bit0", "bit1"]
    assert plan["declared_cost_units"] == 2
    requests = issue_measurement_requests(
        model, 0, offers, authority, plan, contracts, subject, scheduler, challenge,
    )
    assert {r["feature_id"] for r in requests} == {"bit0", "bit1"}
    hidden_state = 3
    receipts = {}
    for request in requests:
        feature = request["feature_id"]
        contract = contracts[feature]
        value = hidden_state & 1 if feature == "bit0" else (hidden_state >> 1) & 1
        receipts[feature] = ObserverReceipt.issue(
            contract, operation_id=feature, input_digest=request["request_digest"],
            projection_value=value,
            time_frame=TemporalFrame(contract.observer_id, scheduler=scheduler),
        )
    accepted_digests = {r.digest for r in receipts.values()}
    def receiver_check(request, contract, receipt):
        """Mathematics: permit only exact trusted receipt identities at the receiver."""
        return receipt.digest in accepted_digests and contract.observer_id == receipt.observer_id
    report = resolve_observer_receipts(
        model, 0, offers, authority, plan, contracts, subject, scheduler, challenge,
        receipts, receiver_verify=receiver_check,
    )
    assert report["resolution"]["result"] == hidden_state
    assert report["resolution"]["remaining_candidates"] == 1
    assert len(report["measurement_receipts"]) == 2
    verify_observer_resolution(
        report, model, 0, offers, authority, plan, contracts, subject, scheduler,
        challenge, receipts, receiver_verify=receiver_check,
    )
    with pytest.raises(SufficiencyRefused, match="missing, duplicate, or unsolicited"):
        resolve_observer_receipts(
            model, 0, offers, authority, plan, contracts, subject, scheduler,
            challenge, {"bit0": receipts["bit0"]}, receiver_verify=receiver_check,
        )
    with pytest.raises(SufficiencyRefused, match="native observer receipt"):
        resolve_observer_receipts(
            model, 0, offers, authority, plan, contracts, subject, scheduler,
            challenge, {"bit0": receipts["bit1"], "bit1": receipts["bit0"]},
            receiver_verify=receiver_check,
        )
