r"""Unit tests for the distilled neural lifter head and policy gate witness isolation.

Mathematics:
Verifies formal invariants across the neural-deterministic interface:
- Feature extraction normalization $\mathbf{v} \in [0.0, 1.0]^8$
- Softmax probability distributions $\sum_c P(c \mid \mathbf{v}) = 1.0$
- Advisory guidance: neural head speeds up certification without compromising truth
- Policy gate isolation: witness verification strictly prevents ungrounded hallucinations
"""

from __future__ import annotations

import math
import pytest

from mailcpu.neural_lifter import (
    DistilledRungHead,
    NeuralLifterPolicy,
    extract_lifter_features,
)


def test_extract_lifter_features_normalization() -> None:
    r"""Test that feature extraction produces normalized outputs in [0.0, 1.0]."""
    trace = [10, 20, 30, 40, 50, 60]
    feats = extract_lifter_features(trace)

    for key, val in feats.items():
        assert 0.0 <= val <= 1.0, f"feature {key} out of bounds: {val}"

    # Arithmetic progression: diff_constant_ratio == 1.0
    assert feats["diff_constant_ratio"] == 1.0
    assert feats["is_binary"] == 0.0

    # Binary trace
    bin_trace = [0, 1, 0, 1, 1, 0]
    bin_feats = extract_lifter_features(bin_trace)
    assert bin_feats["is_binary"] == 1.0

    # Empty trace edge case
    empty_feats = extract_lifter_features([])
    assert empty_feats["entropy"] == 0.0


def test_distilled_head_prediction_probabilities() -> None:
    r"""Test that DistilledRungHead outputs valid probability distributions."""
    head = DistilledRungHead()

    int_trace = [42 + 10 * i for i in range(30)]
    pred_int = head.predict(int_trace)

    assert pred_int.predicted_family in ("int", "lcg")
    assert math.isclose(sum(pred_int.probabilities.values()), 1.0, rel_tol=1e-5)
    assert pred_int.confidence > 0.3

    # Binary LFSR trace
    bin_trace = [0, 1, 1, 0, 1, 0, 0, 1, 1, 1, 0, 1]
    pred_bin = head.predict(bin_trace)
    assert pred_bin.predicted_family == "gf2"
    assert pred_bin.probabilities["gf2"] > 0.5


def test_policy_gate_isolation_truth_preservation() -> None:
    r"""Test policy gate isolation: candidate laws must pass deterministic witness verification.

    Mathematics:
    Ensures that an advisory neural prediction cannot bypass ground truth verification.
    """
    policy = NeuralLifterPolicy()

    # Lawful affine sequence
    m = 256
    s0 = 13
    lane = []
    cur = s0
    for _ in range(40):
        lane.append(cur)
        cur = (5 * cur + 1) % m

    window = lane[:25]
    truth = lane[25:]

    law, pred = policy.certify_stream(window, truth)
    assert law.verdict == "GROUND"
    assert law.family == "lcg"

    # Pseudorandom noise sequence
    noise = [(10007 * i * i + 37) % 65537 for i in range(40)]
    noise_window = noise[:25]
    noise_truth = noise[25:]

    law_noise, pred_noise = policy.certify_stream(noise_window, noise_truth)
    assert law_noise.verdict == "TAPE"


def test_policy_gate_fallback_on_model_mismatch() -> None:
    r"""Test that if a mock neural head predicts the wrong family, verifier falls back correctly."""
    class MisleadingHead(DistilledRungHead):
        r"""Mock head intentionally predicting the wrong family."""

        def predict(self, window):
            r"""Predict tape with low confidence to force ladder evaluation."""
            res = super().predict(window)
            res.predicted_family = "gf2"
            res.confidence = 0.4
            return res

    misleading_policy = NeuralLifterPolicy(head=MisleadingHead())

    # Pure arithmetic progression
    lane = [100 + 7 * i for i in range(30)]
    window = lane[:20]
    truth = lane[20:]

    law, pred = misleading_policy.certify_stream(window, truth)
    # The unwrapped progression is fitted, not ground: without an observed
    # modulus, extrapolation beyond the witness is not identified.
    assert law.verdict == "FITTED"
    assert law.family == "int"
    assert law.params["step"] == 7


def test_policy_never_vetoes_lawful_trace_with_high_confidence_tape_prediction() -> None:
    r"""Mathematics: advisory prediction cannot override deterministic witness recovery."""

    class TapeHead(DistilledRungHead):
        r"""Mathematics: construct a deliberately adversarial posterior."""

        def predict(self, window):
            r"""Mathematics: return $P(\mathrm{tape}\mid W)=0.999$ without changing $W$."""
            result = super().predict(window)
            result.predicted_family = "tape"
            result.confidence = 0.999
            result.probabilities = {name: 0.0 for name in result.probabilities}
            result.probabilities["tape"] = 0.999
            return result

    lane = []
    current = 13
    for _ in range(40):
        lane.append(current)
        current = (5 * current + 1) % 256

    policy = NeuralLifterPolicy(head=TapeHead())
    law, prediction = policy.certify_stream(lane[:25])

    assert prediction.predicted_family == "tape"
    assert law.verdict != "TAPE"
    assert law.family == "lcg"
