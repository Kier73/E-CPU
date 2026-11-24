"""ITR-001: pure audited timing and amortization math; no runtime dependencies.

This data cannot grant source admission, authorize a host, or establish a
semantic equivalence. Those are checked by the native E-CPU runtime.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

SCHEMA = "mailcpu.intention-time-to-verified-realization.v1"

@dataclass(frozen=True)
class IntentionReceipt:
    """Verified value and independently attributed formation/realization spans."""

    mode: str
    intention_digest: str
    source_witness_digest: str
    derived_source_digest: str
    machine_digest: str | None
    route_digest: str | None
    output: int
    source_probes: int
    measured_ns: Mapping[str, int]
    evidence_digest: str

    @property
    def total_ns(self) -> int:
        return sum(self.measured_ns.values())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA, "mode": self.mode,
            "intention_digest": self.intention_digest,
            "source_witness_digest": self.source_witness_digest,
            "derived_source_digest": self.derived_source_digest,
            "machine_digest": self.machine_digest,
            "route_digest": self.route_digest,
            "output": self.output,
            "source_probes": self.source_probes,
            "measured_ns": dict(self.measured_ns),
            "total_ns": self.total_ns,
            "evidence_digest": self.evidence_digest,
        }


def summarize_campaign(seed: IntentionReceipt,
                       cold: Sequence[IntentionReceipt],
                       warm: Sequence[IntentionReceipt]) -> dict[str, Any]:
    """Charge seed formation and report actual measured reuse break-even.

    The comparison uses *the same target goal* in cold and warm runs. The
    seed is a different earlier intention that first learned the source law.
    Values are local monotonic times, not predicted network costs; the median
    is intentionally robust to outliers and is NOT an optimality certificate.
    """
    from statistics import median
    if (not isinstance(seed, IntentionReceipt) or
            not 1 <= len(cold) == len(warm) <= 256 or
            any(not isinstance(x, IntentionReceipt) for x in (*cold, *warm))):
        raise ValueError("Paired bounded verified realization trials required")
    goal = cold[0].intention_digest
    if (any(c.intention_digest != goal or w.intention_digest != goal
            or c.output != w.output or c.derived_source_digest != w.derived_source_digest
            or c.source_probes <= 0 or w.source_probes != 0
            or c.mode != "cold-observation-formed"
            or w.mode not in ("verified-reformed-processor", "verified-retained-result")
            for c, w in zip(cold, warm))):
        raise ValueError("Cold/warm trial semantic equality or observation accounting failed")
    if any(x.total_ns < 0 or any(type(t) is not int or t < 0
            for t in x.measured_ns.values()) for x in (seed, *cold, *warm)):
        raise ValueError("Monotonic timing spans required")
    cold_median = int(median(c.total_ns for c in cold))
    warm_median = int(median(w.total_ns for w in warm))
    advantage = cold_median - warm_median
    # Integer ceiling for N*advantage > seed, i.e. strictly positive net gain.
    break_even = (seed.total_ns // advantage + 1) if advantage > 0 else None
    return {
        "schema": SCHEMA + ".benchmark",
        "source_qualification_scope": "finite-source-affine-mod-from-signed-observations",
        "goal": goal,
        "source": cold[0].derived_source_digest,
        "trials": len(cold),
        "seed_ns": seed.total_ns,
        "cold_median_ns": cold_median,
        "warm_median_ns": warm_median,
        "cold_source_probes_per_trial": [c.source_probes for c in cold],
        "warm_source_probes_per_trial": [w.source_probes for w in warm],
        "median_net_advantage_ns_per_goal": advantage,
        "seed_amortization_queries": break_even,
        "time_units": "perf_counter_ns local wall intervals",
    }
