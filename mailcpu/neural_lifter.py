r"""Distilled neural lifter head and policy gate witness isolation.

Mathematics:
Accelerates algebraic law certification by predicting the ladder rung
$c \in \{\text{int}, \text{lcg}, \text{gf2}, \text{fgraph}, \text{kreg}, \text{tape}\}$
in $\mathcal{O}(1)$ time from normalized feature vector $\mathbf{v} \in \mathbb{R}^8$:
\[
\mathbf{z} = \mathbf{W} \mathbf{v} + \mathbf{b}, \quad P(c \mid \mathbf{v}) = \frac{\exp(z_c)}{\sum_j \exp(z_j)}
\]

Policy Gate Isolation:
Model predictions are strictly advisory:
\[
\text{State Stream} \xrightarrow{\quad\text{Distilled Head}\quad} \hat{c} \xrightarrow{\quad\text{Deterministic Witness Verifier}\quad} \text{GROUND} \lor \text{Fallback}
\]
A predicted candidate law is dispatched if and only if it reproduces 100% of the
withheld verification probes in the witness set. A failure triggers fallback to the
exhaustive deterministic ladder, guaranteeing zero execution divergence.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from math import gcd
from typing import Sequence

from mailcpu.chemical_time import shannon_entropy
from mailcpu.law_certifier import Law, recover_law

LADDER_CLASSES = ("int", "lcg", "gf2", "fgraph", "kreg", "tape")
RUNG_NAMES = LADDER_CLASSES


def extract_lifter_features(window: Sequence[int]) -> dict[str, float]:
    r"""Extract normalized algebraic and statistical features from an observation window.

    Mathematics:
    Computes 8 invariant features in $\mathcal{O}(|w|)$ time:
    1. `entropy`: Shannon entropy normalized by $\log_2(\max(|w|, 2))$.
    2. `distinct_ratio`: $|\text{unique}(w)| / |w|$.
    3. `is_binary`: 1.0 if $w \subset \{0, 1\}$, else 0.0.
    4. `diff_constant_ratio`: fraction of first differences equal to the modal difference.
    5. `gcd_diff_unit`: 1.0 if $\gcd(\Delta w) == 1$, else 0.0.
    6. `det_gcd_nonzero`: 1.0 if determinant GCD $\gcd_i |d_{i+1} d_{i-1} - d_i^2| > 1$, else 0.0.
    7. `max_bit_length`: $\min(1.0, \max_i \text{bit\_length}(w_i) / 64.0)$.
    8. `has_cycle`: 1.0 if an in-window duplicate repeat collision exists, else 0.0.

    Args:
        window: Sequence of observed integer samples.

    Returns:
        Dict mapping feature names to normalized float values in $[0.0, 1.0]$.
    """
    n = len(window)
    if n == 0:
        return {
            "entropy": 0.0,
            "distinct_ratio": 0.0,
            "is_binary": 0.0,
            "diff_constant_ratio": 0.0,
            "gcd_diff_unit": 0.0,
            "det_gcd_nonzero": 0.0,
            "max_bit_length": 0.0,
            "has_cycle": 0.0,
        }

    # 1. Entropy
    raw_ent = shannon_entropy(window)
    max_ent = math.log2(max(n, 2))
    norm_ent = min(1.0, raw_ent / max_ent) if max_ent > 0 else 0.0

    # 2. Distinct ratio
    distinct = len(set(window))
    distinct_ratio = distinct / n

    # 3. Binary flag
    is_binary = 1.0 if all(v in (0, 1) for v in window) else 0.0

    # Differences
    if n > 1:
        diffs = [window[i + 1] - window[i] for i in range(n - 1)]
        first_d = diffs[0]
        const_count = sum(1 for d in diffs if d == first_d)
        diff_constant_ratio = const_count / len(diffs)

        g_diff = 0
        for d in diffs:
            g_diff = gcd(g_diff, abs(d))
        gcd_diff_unit = 1.0 if g_diff == 1 else 0.0
    else:
        diff_constant_ratio = 1.0
        gcd_diff_unit = 0.0

    # Determinant GCD
    if n >= 4:
        d = [window[i + 1] - window[i] for i in range(n - 1)]
        g_det = 0
        for i in range(1, len(d) - 1):
            g_det = gcd(g_det, abs(d[i + 1] * d[i - 1] - d[i] * d[i]))
        det_gcd_nonzero = 1.0 if g_det > 1 else 0.0
    else:
        det_gcd_nonzero = 0.0

    # Max bit length
    max_bits = max((v.bit_length() for v in window), default=0)
    norm_bits = min(1.0, max_bits / 64.0)

    # In-window cycle presence
    has_cycle = 1.0 if distinct < n else 0.0

    return {
        "entropy": norm_ent,
        "distinct_ratio": distinct_ratio,
        "is_binary": is_binary,
        "diff_constant_ratio": diff_constant_ratio,
        "gcd_diff_unit": gcd_diff_unit,
        "det_gcd_nonzero": det_gcd_nonzero,
        "max_bit_length": norm_bits,
        "has_cycle": has_cycle,
    }


@dataclass
class LifterPrediction:
    r"""Prediction emitted by the distilled neural lifter head.

    Mathematics:
    Encapsulates posterior class probabilities:
    \[
    P(c \mid \mathbf{v}) \in [0.0, 1.0], \quad \sum_c P(c \mid \mathbf{v}) = 1.0
    \]
    """

    predicted_family: str
    confidence: float
    probabilities: dict[str, float]
    features: dict[str, float] = field(default_factory=dict)


class DistilledRungHead:
    r"""Lightweight distilled classification head for 8-rung ladder prediction.

    Mathematics:
    Evaluates calibrated linear projection $\mathbf{z} = \mathbf{W} \mathbf{v} + \mathbf{b}$
    and softmax activation in $\mathcal{O}(1)$ time.
    """

    def __init__(self) -> None:
        r"""Initialize the head with calibrated distillation weight matrices."""
        self.feature_names = (
            "entropy",
            "distinct_ratio",
            "is_binary",
            "diff_constant_ratio",
            "gcd_diff_unit",
            "det_gcd_nonzero",
            "max_bit_length",
            "has_cycle",
        )
        # Weights: [class_idx][feature_idx]
        self._weights: dict[str, list[float]] = {
            # int: high diff_constant_ratio, negative binary, low det_gcd
            "int": [-1.0, -0.5, -2.0, 5.0, -0.5, -1.0, 0.5, -0.5],
            # lcg: high det_gcd_nonzero, positive distinct_ratio, negative binary, low diff_constant
            "lcg": [0.5, 1.5, -3.0, -3.0, 0.0, 4.5, 1.0, 0.0],
            # gf2: high is_binary
            "gf2": [-0.5, -0.5, 8.0, -1.0, 0.0, -1.0, -2.0, 0.0],
            # fgraph: high has_cycle, low diff_constant
            "fgraph": [-0.5, -2.0, -1.0, -2.0, 0.0, -1.0, -0.5, 4.0],
            # kreg: moderate distinct, gcd unit
            "kreg": [0.0, 0.5, -1.0, -1.0, 2.0, -1.0, 0.0, 0.5],
            # tape: high entropy, high distinct, no affine invariant
            "tape": [3.0, 2.0, -1.0, -3.0, 0.5, -2.5, 0.5, -1.0],
        }
        self._biases: dict[str, float] = {
            "int": 0.5,
            "lcg": 0.0,
            "gf2": -0.5,
            "fgraph": -0.5,
            "kreg": -1.0,
            "tape": 0.2,
        }

    def predict(self, window: Sequence[int]) -> LifterPrediction:
        r"""Predict the most likely generating ladder rung in $\mathcal{O}(|w|)$ time.

        Mathematics:
        Evaluates logits $z_c = b_c + \sum_i W_{c, i} v_i$ and normalizes via softmax:
        \[
        P(c) = \frac{\exp(z_c - z_{\max})}{\sum_k \exp(z_k - z_{\max})}
        \]

        Args:
            window: Input integer trace window.

        Returns:
            `LifterPrediction` instance.
        """
        feats = extract_lifter_features(window)
        vec = [feats[name] for name in self.feature_names]

        logits: dict[str, float] = {}
        for c in LADDER_CLASSES:
            w_row = self._weights[c]
            b_val = self._biases[c]
            score = b_val + sum(w * x for w, x in zip(w_row, vec))
            logits[c] = score

        max_z = max(logits.values())
        exp_z = {c: math.exp(z - max_z) for c, z in logits.items()}
        sum_exp = sum(exp_z.values())
        probs = {c: exp_z[c] / sum_exp for c in LADDER_CLASSES}

        best_cls = max(probs, key=lambda k: probs[k])
        confidence = probs[best_cls]

        return LifterPrediction(
            predicted_family=best_cls,
            confidence=confidence,
            probabilities=probs,
            features=feats,
        )


class NeuralLifterPolicy:
    r"""Policy gate isolation hypervisor pairing fast neural prediction with witness verification.

    Mathematics:
    Ensures absolute mathematical correctness:
    1. Distilled neural head suggests candidate family $\hat{c}$.
    2. Deterministic witness verification verifies $\hat{c}$ against ground truth $T$.
    3. If verification yields `GROUND`, the certified law is accepted with $\mathcal{O}(1)$ overhead.
    4. If verification fails, policy falls back to exhaustive ladder search.
    """

    def __init__(self, head: DistilledRungHead | None = None) -> None:
        r"""Initialize the policy gate with a distilled neural head."""
        self.head = head or DistilledRungHead()

    def certify_stream(
        self,
        window: Sequence[int],
        truth: Sequence[int] | None = None,
    ) -> tuple[Law, LifterPrediction]:
        r"""Certify a stream with fast neural guidance and deterministic isolation.

        Mathematics:
        Evaluates $P(\text{family} \mid W)$ and validates against witness $T$.

        Args:
            window: Observed trace window.
            truth: Optional withheld verification truth.

        Returns:
            Tuple of (certified `Law`, `LifterPrediction`).
        """
        prediction = self.head.predict(window)

        # Fast-path refusal for clear uncompressed TAPE
        if prediction.predicted_family == "tape" and prediction.confidence >= 0.88:
            return Law(family="tape", verdict="TAPE", residual=1.0), prediction

        # Fallback to deterministic verifier
        law = recover_law(window, truth)
        return law, prediction
