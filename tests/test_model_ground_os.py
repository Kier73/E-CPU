"""USM-001 tests exercise a trained model as an actual E-CPU service client."""

from __future__ import annotations

from copy import deepcopy

import pytest

from examples.model_ground_os import (
    GroundPolicyModel, evidence_label, operate_ground, run_demo, sample_stream,
    train_example_model, worker_predict,
)
from mailcpu.structural_memory import StructuralMemoryRegistry


CONTEXT = {"tenant": "use-system", "purpose": "observed-computation"}


def _registry(authorized=True):
    return StructuralMemoryRegistry(
        admission_policy=(lambda proposal: proposal.spec.context == CONTEXT)
        if authorized else None
    )


def test_model_training_checkpoint_roundtrip_replays_inference():
    model, report = train_example_model()
    assert report["examples"] == 24
    assert report["teacher_label_counts"]["ground"] > 0
    assert report["teacher_label_counts"]["not_ground"] > 0
    assert 0 <= report["training_accuracy"] <= 1
    snapshot = model.snapshot()
    restored = GroundPolicyModel.from_snapshot(snapshot)
    assert restored.digest == model.digest
    for seed in (101, 202):
        window = sample_stream("affine", seed)[:24]
        assert restored.predict(window) == model.predict(window)


def test_altered_model_artifact_is_not_a_checkpoint():
    model = GroundPolicyModel()
    snapshot = model.snapshot()
    corrupted = deepcopy(snapshot)
    corrupted["bias"] = 99.0
    with pytest.raises(ValueError, match="digest"):
        GroundPolicyModel.from_snapshot(corrupted)
    with pytest.raises(ValueError):
        GroundPolicyModel((float("nan"),) * 8)


def test_subprocess_hosted_model_matches_reconstructed_checkpoint():
    model = GroundPolicyModel(bias=0.7)
    window = sample_stream("affine", 205)[:24]
    assert worker_predict(model, window) == model.predict(window)


def test_model_opens_real_ground_and_reads_trillion_coordinate():
    model = GroundPolicyModel(bias=30.0)  # only a proposal, never trusted
    registry = _registry()
    coordinate = 10**12 + 137
    sample = sample_stream("affine", 201)
    result = operate_ground(model, registry, "model-controller-affine",
                            sample, coordinate=coordinate, context=CONTEXT)
    assert result["status"] == "ground_read"
    assert result["value"] == (7 + 201 + 5 * coordinate) % 97
    assert result["verification_class"] == "witness_grounded"
    assert len(result["read_receipt_id"]) == 64
    assert registry.active_version("model-controller-affine") is not None


def test_model_cannot_invent_host_admission_authority():
    model = GroundPolicyModel(bias=30.0)
    registry = _registry(authorized=False)
    result = operate_ground(model, registry, "unauthorized-controller",
                            sample_stream("affine", 11), coordinate=999,
                            context=CONTEXT, force=True)
    assert result["status"] == "refused_by_ecpu"
    assert registry.active_version("unauthorized-controller") is None


def test_model_can_defer_but_explicit_request_still_requires_ecpu_ground():
    model = GroundPolicyModel(bias=-30.0)
    registry = _registry()
    stream = sample_stream("affine", 19)
    deferred = operate_ground(model, registry, "deferred", stream,
                              coordinate=1000, context=CONTEXT)
    assert deferred["status"] == "deferred_by_model"
    assert registry.active_version("deferred") is None
    forced = operate_ground(model, registry, "explicit-request", stream,
                            coordinate=1000, context=CONTEXT, force=True)
    assert forced["status"] == "ground_read"


def test_adversarial_high_confidence_model_cannot_make_false_far_read():
    model = GroundPolicyModel(bias=30.0)
    registry = _registry()
    manipulated = list(sample_stream("affine", 17))
    manipulated[27] = (manipulated[27] + 1) % 97
    result = operate_ground(model, registry, "corrupted-observation",
                            manipulated, coordinate=10**12,
                            context=CONTEXT)
    assert result["status"] == "refused_by_ecpu"
    assert "value" not in result


def test_demo_runs_training_then_uses_host_service():
    report = run_demo()
    first, second = report["episodes"]
    assert report["model"]["digest"] == report["training"]["model_digest"]
    assert first["status"] == "ground_read"
    assert first["model_runtime"] == "isolated-subprocess"
    assert all(item["status"] in {"ground_read", "refused_by_ecpu", "deferred_by_model"}
               for item in report["unforced_evaluation"])
    assert report["external_comparison"]["affine_source_oracle_match"]
    assert not report["external_comparison"]["nonlinear_admitted"]
    assert second["status"] == "refused_by_ecpu"
    assert len(report["report_digest"]) == 64
    assert report["evaluation_summary"]["cases"] == 8
    assert len(report["unforced_evaluation"]) == 8
    assert all((item["status"] == "deferred_by_model") == (not item["model_recommended"])
               for item in report["unforced_evaluation"])
