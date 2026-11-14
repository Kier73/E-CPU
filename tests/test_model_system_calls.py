"""USM-002 genuine model-issued E-CPU calls, guardrails and chain reconstruction."""

from __future__ import annotations

from copy import deepcopy

import pytest

from examples.model_ground_os import GroundPolicyModel, sample_stream
from examples.model_system_calls import (
    CALL_SCHEMA, GENESIS, GroundSystemCallSession, SystemCallRefused,
    run_model_system, verify_system_call_trace,
)
from mailcpu.structural_memory import StructuralMemoryRegistry

CONTEXT = {"tenant": "use-system", "purpose": "observed-computation"}
COORDINATE = 10**12 + 137


def registry(*, allowed=True):
    return StructuralMemoryRegistry(
        admission_policy=(
            lambda proposal: (
                proposal.spec.context == CONTEXT
                and proposal.spec.domain == "model-operated-observed-orbit"
            )
        ) if allowed else None
    )


def session(*, stream="affine", allowed=True, capabilities=frozenset({"observe", "propose", "read"})):
    reg = registry(allowed=allowed)
    s = GroundSystemCallSession(
        registry=reg, session_id="session-a", stream_id="test-ground",
        observations=sample_stream(stream, 201), coordinate=COORDINATE,
        training_count=24, context=CONTEXT, allowed_ops=capabilities,
    )
    return reg, s


def call(s, op, *, seq=None, previous_head=None, stream_id=None, coordinate=None):
    return {
        "schema": CALL_SCHEMA,
        "session_id": s.session_id,
        "stream_id": stream_id or s.stream_id,
        "seq": len(s.events) if seq is None else seq,
        "previous_head": s.head if previous_head is None else previous_head,
        "op": op,
        "coordinate": coordinate,
    }


def test_model_process_drives_real_observe_propose_read_sequence():
    model = GroundPolicyModel(bias=30.0)
    reg = registry()
    report = run_model_system(
        model, reg, "verified-source", sample_stream("affine", 201),
        coordinate=COORDINATE, session_id="model-syscall-good", context=CONTEXT,
    )
    assert report["status"] == "complete"
    trace = report["session"]
    assert verify_system_call_trace(trace)
    assert [event["call"]["op"] for event in trace["events"]] == [
        "observe", "propose", "read"
    ]
    assert trace["events"][-1]["output"]["value"] == (7 + 201 + 5 * COORDINATE) % 97
    assert len(trace["events"][-1]["output"]["read_receipt_id"]) == 64
    assert reg.active_version("verified-source") is not None


def test_model_can_choose_no_ground_without_host_mutation():
    model = GroundPolicyModel(bias=-30.0)
    reg = registry()
    result = run_model_system(
        model, reg, "deferred-source", sample_stream("affine", 19),
        coordinate=COORDINATE, session_id="model-syscall-deferred", context=CONTEXT,
    )
    assert result["status"] == "deferred"
    assert [event["call"]["op"] for event in result["session"]["events"]] == ["observe", "stop"]
    assert reg.active_version("deferred-source") is None


def test_model_false_positive_is_not_admission_authority():
    model = GroundPolicyModel(bias=30.0)
    reg = registry()
    result = run_model_system(
        model, reg, "nonlinear-source", sample_stream("nonlinear", 207),
        coordinate=COORDINATE, session_id="model-syscall-nonlinear", context=CONTEXT,
    )
    assert result["status"] == "refused"
    assert result["session"]["events"][-1]["output"]["status"] == "refused_by_ecpu"
    assert reg.active_version("nonlinear-source") is None
    assert verify_system_call_trace(result["session"])


def test_receiver_must_independently_authorize_the_admission():
    model = GroundPolicyModel(bias=30.0)
    reg = registry(allowed=False)
    result = run_model_system(
        model, reg, "denied-source", sample_stream("affine", 201),
        coordinate=COORDINATE, session_id="model-syscall-denied", context=CONTEXT,
    )
    assert result["status"] == "refused"
    assert result["session"]["events"][-1]["output"]["refusal"] == "StructuralMemoryAuthorizationError"
    assert reg.active_version("denied-source") is None


def test_receiver_refuses_injected_and_replayed_calls_before_side_effects():
    reg, s = session()
    unissued = call(s, "propose")
    with pytest.raises(SystemCallRefused, match="current phase"):
        s.apply(unissued)
    with pytest.raises(SystemCallRefused, match="cross-session"):
        s.apply(call(s, "observe", stream_id="other-stream"))
    first = call(s, "observe")
    s.apply(first)
    first_head = s.head
    with pytest.raises(SystemCallRefused, match="replayed"):
        s.apply(first)
    assert s.head == first_head
    with pytest.raises(SystemCallRefused, match="non-read"):
        s.apply(call(s, "propose", coordinate=99))
    assert reg.active_version("test-ground") is None


def test_capability_gate_precedes_ground_proposal():
    reg, s = session(capabilities=frozenset({"observe"}))
    s.apply(call(s, "observe"))
    with pytest.raises(SystemCallRefused, match="capability"):
        s.apply(call(s, "propose"))
    assert reg.active_version("test-ground") is None
    assert s.phase == "observed"


def test_user_owned_target_cannot_be_rewritten_by_model():
    _, s = session()
    s.apply(call(s, "observe"))
    assert s.apply(call(s, "propose"))["status"] == "admitted"
    with pytest.raises(SystemCallRefused, match="differs"):
        s.apply(call(s, "read", coordinate=COORDINATE + 1))
    assert s.phase == "admitted"
    assert s.apply(call(s, "read", coordinate=COORDINATE))["status"] == "completed"


def test_trace_reconstruction_rejects_mutated_result_and_links():
    _, s = session()
    s.apply(call(s, "observe"))
    s.apply(call(s, "propose"))
    s.apply(call(s, "read", coordinate=COORDINATE))
    trace = s.trace()
    assert trace["events"][0]["previous_head"] == GENESIS
    assert verify_system_call_trace(trace)
    altered = deepcopy(trace)
    altered["events"][-1]["output"]["value"] += 1
    assert not verify_system_call_trace(altered)
    altered = deepcopy(trace)
    altered["events"][1]["call"]["seq"] = 0
    assert not verify_system_call_trace(altered)
    altered = deepcopy(trace)
    altered["events"][-1]["call"]["op"] = "stop"
    assert not verify_system_call_trace(altered)
