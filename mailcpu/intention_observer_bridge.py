"""IOS-002: bind finite intention plans to native receiver-admitted observer receipts.

No network dispatch, signature verification, authorization, Ground admission, or
one-time-nonce storage occurs here. A trusted receiver verifier must confirm
those obligations before the bridge consumes any measurement. ObserverReceipt
content identity alone is never treated as authenticity or authority.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence

from .intention_sufficiency import (
    FiniteGround,
    MeasurementCapability,
    SufficiencyRefused,
    _bytes,
    _fingerprint,
    _hash,
    resolve_sufficiency,
    verify_sufficiency_plan,
)
from .observer_orbit import ObserverContract, ObserverReceipt, verify_observer_receipt
from .semantic_translation import RepresentationRef
from .temporal import SchedulerReading


SCHEMA = "mailcpu.intention-observer-bridge.v1"
ReceiverVerifier = Callable[[Mapping[str, Any], ObserverContract, ObserverReceipt], bool]


def _contracts(
    model: FiniteGround,
    offers: Sequence[MeasurementCapability],
    selected: Sequence[str],
    contracts: Mapping[str, ObserverContract],
    subject: RepresentationRef,
) -> dict[str, ObserverContract]:
    """Mathematics: enforce an injective selected-feature to native-contract relation."""
    if not isinstance(subject, RepresentationRef):
        raise SufficiencyRefused("trusted subject must be a RepresentationRef")
    if type(contracts) is not dict or set(contracts) != set(selected):
        raise SufficiencyRefused("missing or extra selected observer contracts")
    by_id = {offer.feature_id: offer for offer in offers}
    result: dict[str, ObserverContract] = {}
    for feature_id in selected:
        offer = by_id[feature_id]
        contract = contracts[feature_id]
        if not isinstance(contract, ObserverContract):
            raise SufficiencyRefused("selected observer contract is not native and typed")
        if (
            offer.contract_digest != contract.digest
            or offer.provider_id != contract.observer_id
            or contract.observation.projection_id != feature_id
            or contract.subject != subject
            or contract.interpretation.content_digest != model.ground_digest
            or contract.context_digest != model.context_digest
        ):
            raise SufficiencyRefused("offered measurement and live observer contract differ")
        result[feature_id] = contract
    return result


def issue_measurement_requests(
    model: FiniteGround,
    public_value: Any,
    offers: Sequence[MeasurementCapability],
    authority_digest: str,
    plan: Mapping[str, Any],
    contracts: Mapping[str, ObserverContract],
    subject: RepresentationRef,
    scheduler: SchedulerReading,
    challenge_digest: str,
) -> tuple[dict[str, Any], ...]:
    """Mathematics: bind each selected feature to a unique context-challenged request.

    A fresh receiver-selected challenge binds an attempted observation epoch.
    The receiver must durably enforce uniqueness where replay matters.
    """
    verify_sufficiency_plan(plan, model, public_value, offers, authority_digest)
    if plan["status"] == "REFUSE":
        raise SufficiencyRefused("an insufficient intention cannot request measurements")
    if not isinstance(scheduler, SchedulerReading):
        raise SufficiencyRefused("a typed receiver scheduler coordinate is required")
    _hash(challenge_digest, "receiver challenge")
    selected = plan["selected_features"]
    selected_contracts = _contracts(model, offers, selected, contracts, subject)
    requests: list[dict[str, Any]] = []
    for feature_id in selected:
        contract = selected_contracts[feature_id]
        body = {
            "schema": SCHEMA + ".request",
            "model_digest": model.digest,
            "plan_digest": plan["plan_digest"],
            "authority_digest": authority_digest,
            "public_digest": plan["public_digest"],
            "feature_id": feature_id,
            "contract_digest": contract.digest,
            "subject": subject.to_dict(),
            "scheduler": {"scheduler_id": scheduler.scheduler_id, "tick": scheduler.tick},
            "challenge_digest": challenge_digest,
        }
        requests.append({**body, "request_digest": _fingerprint(body)})
    return tuple(requests)


def resolve_observer_receipts(
    model: FiniteGround,
    public_value: Any,
    offers: Sequence[MeasurementCapability],
    authority_digest: str,
    plan: Mapping[str, Any],
    contracts: Mapping[str, ObserverContract],
    subject: RepresentationRef,
    scheduler: SchedulerReading,
    challenge_digest: str,
    receipts: Mapping[str, ObserverReceipt],
    *,
    receiver_verify: ReceiverVerifier | None = None,
) -> dict[str, Any]:
    """Mathematics: resolve only from the exact set of receiver-admitted receipt projections.

    ``receiver_verify`` is a trusted receiver-side function, not one taken from
    a remote advertisement. It must validate authorization, peer provenance,
    request freshness, transport evidence, and any required semantic checks.
    A return value of exactly True is necessary for each measurement.
    """
    requests = issue_measurement_requests(
        model, public_value, offers, authority_digest, plan,
        contracts, subject, scheduler, challenge_digest,
    )
    selected = tuple(plan["selected_features"])
    if type(receipts) is not dict or set(receipts) != set(selected):
        raise SufficiencyRefused("missing, duplicate, or unsolicited receipt")
    if selected and not callable(receiver_verify):
        raise SufficiencyRefused("receiver-owned authorization and provenance verifier required")
    measured: dict[str, Any] = {}
    accepted: list[dict[str, Any]] = []
    for request in requests:
        feature_id = request["feature_id"]
        contract = contracts[feature_id]
        receipt = receipts[feature_id]
        if not isinstance(receipt, ObserverReceipt) or not verify_observer_receipt(contract, receipt):
            raise SufficiencyRefused("native observer receipt does not match live contract")
        if (
            receipt.operation_id != feature_id
            or receipt.input_digest != request["request_digest"]
            or receipt.time_frame is None
            or receipt.time_frame.scheduler != scheduler
        ):
            raise SufficiencyRefused("observer reading is from another operation, request, or scheduler coordinate")
        if receiver_verify(request, contract, receipt) is not True:
            raise SufficiencyRefused("receiver refused measurement admission or origin")
        projection = receipt.projection
        _bytes(projection)  # preserve IOS-001's strict finite JSON domain
        measured[feature_id] = projection
        accepted.append({
            "feature_id": feature_id,
            "request_digest": request["request_digest"],
            "observer_receipt_digest": receipt.digest,
            "observer_contract_digest": contract.digest,
        })
    receipt_digest = _fingerprint({"schema": SCHEMA + ".evidence", "accepted": accepted}) if accepted else None
    resolved = resolve_sufficiency(model, public_value, offers, authority_digest,
                                   plan, measured, receipt_digest)
    body = {
        "schema": SCHEMA + ".result",
        "plan_digest": plan["plan_digest"],
        "challenge_digest": challenge_digest,
        "scheduler": {"scheduler_id": scheduler.scheduler_id, "tick": scheduler.tick},
        "measurement_receipts": accepted,
        "resolution": resolved,
    }
    return {**body, "bridge_digest": _fingerprint(body)}


def verify_observer_resolution(
    report: Mapping[str, Any], model: FiniteGround, public_value: Any,
    offers: Sequence[MeasurementCapability], authority_digest: str,
    plan: Mapping[str, Any], contracts: Mapping[str, ObserverContract],
    subject: RepresentationRef, scheduler: SchedulerReading,
    challenge_digest: str, receipts: Mapping[str, ObserverReceipt],
    *, receiver_verify: ReceiverVerifier | None = None,
) -> None:
    """Mathematics: reconstruct the full result against pinned current inputs."""
    expected = resolve_observer_receipts(
        model, public_value, offers, authority_digest, plan,
        contracts, subject, scheduler, challenge_digest, receipts,
        receiver_verify=receiver_verify,
    )
    if type(report) is not dict or report != expected:
        raise SufficiencyRefused("observer-backed resolution differs from independent reconstruction")
