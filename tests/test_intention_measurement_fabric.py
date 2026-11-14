"""IOS-003 native reliable mTLS measurement and durable refusal tests."""

from __future__ import annotations

from dataclasses import replace
import shutil
import socket
import ssl
import subprocess
import threading
import time

import pytest

from mailcpu.intention_sufficiency import (
    FiniteGround, FiniteState, MeasurementCapability, SufficiencyRefused,
    plan_sufficiency,
)
from mailcpu.intention_measurement_fabric import (
    HostedMeasurement, MeasurementPeerClient, MeasurementPeerServer,
    MeasurementReceiptLedger, _parse_request,
)
from mailcpu.intention_observer_bridge import issue_measurement_requests
from mailcpu.observer_orbit import ObserverContract
from mailcpu.semantic_translation import ObservationContract, RepresentationRef, canonical_value_digest
from mailcpu.socket_transport import SocketTransport
from mailcpu.temporal import SchedulerReading

AUTH = canonical_value_digest({"receiver": "authority-epoch-8"})
CHALLENGE = canonical_value_digest({"nonce": "example-unique-challenge-008"})
SCHED = SchedulerReading("measurement-scheduler", 117)


def _setup(*, state=3):
    """Keep the hidden physical phase private to the installed host reader."""
    subject = RepresentationRef.from_payload("ios.subject", 1, {"domain": "four-phase"})
    ground = RepresentationRef.from_payload("ios.ground", 1, {"law": "identity-mod4"})
    context = canonical_value_digest({"session": "ios-003", "revision": 8})
    public = ObservationContract.from_definition("threshold", 1, {"projection": "phase//2"})
    target = ObservationContract.from_definition("parity-target", 1, {"projection": "phase%2"})
    projection = ObservationContract.from_definition("parity", 1, {"projection": "phase%2"})
    contract = ObserverContract("observer.parity", 1, subject, ground, projection, context)
    model = FiniteGround(
        ground.content_digest, public.projection_digest, target.projection_digest,
        context,
        tuple(FiniteState.create(str(i), i // 2, i % 2, {"parity": i % 2}) for i in range(4)),
    )
    offers = (MeasurementCapability("parity", contract.digest, contract.observer_id, 1),)
    plan = plan_sufficiency(model, state // 2, offers, AUTH)
    assert plan["status"] == "MEASURE"
    return model, state // 2, offers, plan, {"parity": contract}, subject


def _requests(state=3, *, challenge=CHALLENGE):
    model, public, offers, plan, contracts, subject = _setup(state=state)
    return issue_measurement_requests(model, public, offers, AUTH, plan,
                                      contracts, subject, SCHED, challenge)


def _installed(state=3, *, reads=None, admissions=None, authority=lambda: AUTH):
    model, public, offers, plan, contracts, subject = _setup(state=state)

    def admit(request, peer):
        if admissions is not None:
            admissions.append((request["request_digest"], peer))
        return peer == "receiver-a" and request["model_digest"] == model.digest

    def read(request):
        if reads is not None:
            reads.append(request["request_digest"])
        return state % 2

    return {"parity": HostedMeasurement(
        contracts["parity"], model.digest, authority, admit, read, (0, 1),
    )}


def test_native_request_canonical_digest_reconstruction_and_mutations():
    req = _requests()[0]
    assert _parse_request({"kind": "mailcpu.intention.measurement.request.v1", "request": req}) == req
    changed = {**req, "feature_id": "full-state"}
    with pytest.raises(SufficiencyRefused, match="digest changed"):
