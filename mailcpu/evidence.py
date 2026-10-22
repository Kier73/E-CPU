"""Evidence provenance for reportable MailCPU results."""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from typing import Any


class EvidenceTier(str, Enum):
    """Mathematics: classify execution provenance in ordered substrate stages `E0 < E1`, with E2 reserved for public infrastructure."""

    E0 = "E0"
    E1 = "E1"


def with_evidence_tier(payload: Mapping[str, Any], tier: EvidenceTier) -> dict[str, Any]:
    """Mathematics: construct `R_t(P) = P ∪ {evidence_tier=t}` while rejecting a pre-existing conflicting annotation."""

    if not isinstance(payload, Mapping):
        raise TypeError("report payload must be a mapping")
    if not isinstance(tier, EvidenceTier):
        raise TypeError("report evidence tier must be an EvidenceTier")
    existing = payload.get("evidence_tier")
    if existing is not None and existing != tier.value:
        raise ValueError("report already carries a conflicting evidence tier")
    report = dict(payload)
    report["evidence_tier"] = tier.value
    return report
