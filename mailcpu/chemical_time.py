r"""Chemical time coordinate, stream parsing difficulty metrics, and persistence horizons.

Mathematics:
Chemical time $\tau_{\text{chem}}$ measures the intrinsic parsing latency and
structural difficulty required to resolve the novelty of an incoming execution stream:
\[
\tau_{\text{chem}}(w) = w_H \cdot H(w) + w_u \cdot \frac{|\text{unique}(w)|}{|w|} + w_d \cdot \frac{1}{|w|-1}\sum_{i=0}^{|w|-2} |\Delta w_i| + w_z \cdot \frac{\text{gzip\_bits}(w)}{8 |w|}
\]
where $H(w) = -\sum_{i} p_i \log_2 p_i$ is the empirical Shannon entropy.

Difficulty acts as an intrinsic computational currency ("difficulty as storage"):
streams that demand significant computation to parse are allocated proportional
memory quotas and delay-loop retention horizons:
\[
\text{Quota}_{\text{bytes}} = \lfloor \text{base\_quota} \cdot (1 + \alpha \log(1 + \tau_{\text{chem}})) \rfloor
\]
\[
t_{\text{retention}} = \text{base\_retention} \cdot (1 + \beta \tau_{\text{chem}})
\]
The certified validity horizon $t_{\text{horizon}} = \text{first\_bad}$ acts as a
strict upper bound on non-ground extrapolations.
"""

from __future__ import annotations

import gzip
import math
from collections import Counter
from dataclasses import dataclass
from typing import Sequence

from mailcpu.law_certifier import HorizonExceeded


def shannon_entropy(vals: Sequence[int]) -> float:
    r"""Compute the empirical Shannon entropy of an integer sequence in bits.

    Mathematics:
    \[
    H(X) = -\sum_{x \in \mathcal{X}} P(x) \log_2 P(x), \quad P(x) = \frac{\text{count}(x)}{N}
    \]

    Args:
        vals: Sequence of observed integer samples.

    Returns:
        Entropy in bits ($H \ge 0.0$).
    """
    if not vals:
        return 0.0
    n = len(vals)
    counts = Counter(vals)
    ent = 0.0
    for c in counts.values():
        if c > 0:
            p = c / n
            ent -= p * math.log2(p)
    return max(0.0, ent)


def gzip_compressed_bits(vals: Sequence[int]) -> int:
    r"""Compute the Lempel-Ziv (gzip level 9) compressed size of a sequence in bits.

    Mathematics:
    Encodes the sequence into comma-separated decimal ASCII bytes and evaluates
    $8 \cdot |\text{gzip}(b, \text{level}=9)|$.

    Args:
        vals: Sequence of integer samples.

    Returns:
        Compressed length in bits.
    """
    if not vals:
        return 0
    raw_bytes = ",".join(str(v) for v in vals).encode("ascii")
    return len(gzip.compress(raw_bytes, 9)) * 8


def compute_chemical_difficulty(
    vals: Sequence[int],
    w_entropy: float = 1.0,
    w_unique: float = 0.5,
    w_diff: float = 0.2,
    w_gzip: float = 0.3,
) -> float:
    r"""Evaluate the chemical parsing difficulty $\tau_{\text{chem}}$ of an observation trace.

    Mathematics:
    Synthesizes Shannon information, distinct symbol ratio, first difference variation,
    and Lempel-Ziv redundancy:
    \[
    \tau_{\text{chem}} = w_E H(w) + w_u \frac{|\mathcal{U}|}{N} + w_d \overline{|\Delta w|} + w_z \frac{\text{bits}}{8 N}
    \]

    Args:
        vals: Sequence of observed integer samples.
        w_entropy: Weight for Shannon entropy.
        w_unique: Weight for distinct symbol ratio.
        w_diff: Weight for normalized difference magnitude.
        w_gzip: Weight for normalized compression density.

    Returns:
        Non-negative chemical difficulty metric.
    """
    n = len(vals)
    if n == 0:
        return 0.0
    h = shannon_entropy(vals)
    u = len(set(vals)) / n
    gz = gzip_compressed_bits(vals) / (8.0 * n)

    if n > 1:
        diff_avg = sum(abs(vals[i + 1] - vals[i]) for i in range(n - 1)) / (n - 1)
        # Log-scale difference variation to maintain comparable magnitude
        diff_metric = math.log1p(diff_avg)
    else:
        diff_metric = 0.0

    difficulty = (
        w_entropy * h + w_unique * u + w_diff * diff_metric + w_gzip * gz
    )
    return max(0.0, float(difficulty))


def calculate_difficulty_quota(
    difficulty: float,
    base_quota: int = 65536,
    alpha: float = 0.5,
) -> int:
    r"""Scale virtual memory allocation quota proportionally to stream difficulty.

    Mathematics:
    \[
    Q = \lfloor \text{base\_quota} \cdot (1 + \alpha \log(1 + \tau_{\text{chem}})) \rfloor
    \]
    Implements difficulty-as-currency: complex streams receive larger workspaces.

    Args:
        difficulty: Non-negative chemical difficulty $\tau_{\text{chem}}$.
        base_quota: Default baseline memory quota in bytes.
        alpha: Elasticity scaling coefficient.

    Returns:
        Allocated memory quota in bytes.
    """
    if difficulty < 0.0:
        raise ValueError(f"difficulty must be non-negative, got {difficulty}")
    multiplier = 1.0 + alpha * math.log1p(difficulty)
    return int(base_quota * multiplier)


def calculate_retention_delay(
    difficulty: float,
    base_delay_ms: float = 100.0,
    beta: float = 0.25,
) -> float:
    r"""Scale physical delay-loop retention window proportionally to stream difficulty.

    Mathematics:
    \[
    t_{\text{retention}} = \text{base\_delay\_ms} \cdot (1 + \beta \tau_{\text{chem}})
    \]
    Protects computationally expensive state from premature eviction in circulating delay loops.

    Args:
        difficulty: Non-negative chemical difficulty $\tau_{\text{chem}}$.
        base_delay_ms: Baseline retention window in milliseconds.
        beta: Retention extension rate.

    Returns:
        Extended retention window in milliseconds.
    """
    if difficulty < 0.0:
        raise ValueError(f"difficulty must be non-negative, got {difficulty}")
    return float(base_delay_ms * (1.0 + beta * difficulty))


@dataclass
class HorizonTracker:
    r"""Track the certified validity horizon $t_{\text{horizon}} = \text{first\_bad}$.

    Mathematics:
    Maintains the invariant:
    \[
    t < t_{\text{horizon}}
    \]
    Raises `HorizonExceeded` whenever execution attempts to extrapolate beyond
    the verified validity boundary of a PREFIX-GROUND law.
    """

    task_id: int
    t_horizon: int | None
    family: str = "tape"

    def is_valid_coordinate(self, t: int) -> bool:
        r"""Check if coordinate $t$ lies strictly within the certified horizon."""
        if self.t_horizon is None:
            return True
        return t < self.t_horizon

    def assert_valid(self, t: int) -> None:
        r"""Assert that coordinate $t < t_{\text{horizon}}$, raising `HorizonExceeded` on breach."""
        if not self.is_valid_coordinate(t):
            raise HorizonExceeded(
                f"task {self.task_id} attempted navigation to coordinate t={t} "
                f"exceeding certified horizon t_horizon={self.t_horizon} (family={self.family})"
            )


@dataclass(frozen=True)
class SystemEpoch:
    r"""Harmonized tripartite temporal coordinate.

    Mathematics:
    Unifies three distinct physical and computational time coordinates:
    \[
    \tau_{\text{system}} = \langle \lambda_{\text{event}}, \; \tau_{\text{chronon}}, \; \tau_{\text{chem}} \rangle
    \]
    - $\lambda_{\text{event}} \in \mathbb{Z}_{\ge 0}$: Discrete integer sequence of accepted external events.
    - $\tau_{\text{chronon}} \in \mathbb{C}$: Discrete geometric phase accumulator $D = (-i)^{n_{\text{active}}}$ from reversible gates.
    - $\tau_{\text{chem}} \in \mathbb{R}_{\ge 0}$: Cumulative chemical parsing difficulty.
    """

    event_lambda: int
    chronon_phase: complex
    chemical_tau: float

    def advance_event(self) -> SystemEpoch:
        r"""Advance the discrete event counter by 1."""
        return SystemEpoch(
            event_lambda=self.event_lambda + 1,
            chronon_phase=self.chronon_phase,
            chemical_tau=self.chemical_tau,
        )

    def advance_chronon(self, active_bits: int) -> SystemEpoch:
        r"""Multiply chronon phase by discrete geometric factor $D = (-i)^{n_{\text{active}} \bmod 4}$."""
        phase_map = (1 + 0j, 0 - 1j, -1 + 0j, 0 + 1j)
        step_factor = phase_map[active_bits % 4]
        return SystemEpoch(
            event_lambda=self.event_lambda,
            chronon_phase=self.chronon_phase * step_factor,
            chemical_tau=self.chemical_tau,
        )

    def add_chemical_difficulty(self, diff: float) -> SystemEpoch:
        r"""Accumulate chemical parsing difficulty."""
        return SystemEpoch(
            event_lambda=self.event_lambda,
            chronon_phase=self.chronon_phase,
            chemical_tau=self.chemical_tau + max(0.0, diff),
        )
