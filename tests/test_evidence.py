from __future__ import annotations

import pytest

from mailcpu import CommandResult, EvidenceTier, NetworkAddress, NetworkFrame, ProcessReport, with_evidence_tier


def test_evidence_annotation_is_copying_and_explicit() -> None:
    """Mathematics: `R_t(P)` preserves `P` and adds exactly one provenance coordinate without mutating `P`."""

    payload = {"status": "ok"}
    result = with_evidence_tier(payload, EvidenceTier.E0)
    assert payload == {"status": "ok"}
    assert result == {"status": "ok", "evidence_tier": "E0"}


def test_evidence_annotation_refuses_conflicting_or_unknown_tiers() -> None:
    """Mathematics: annotation is defined only for `t ∈ {E0,E1}` and rejects `R_t(P)` when `P.evidence_tier ≠ t`."""

    with pytest.raises(ValueError, match="conflicting"):
        with_evidence_tier({"evidence_tier": "E1"}, EvidenceTier.E0)
    with pytest.raises(TypeError, match="EvidenceTier"):
        with_evidence_tier({}, "E2")  # type: ignore[arg-type]


def test_virtual_command_results_carry_their_modelled_provenance() -> None:
    """Mathematics: every `CommandResult` over the local virtual environment has provenance `t=E0` by default."""

    assert CommandResult(0).evidence_tier is EvidenceTier.E0


def test_public_process_and_owned_frame_projections_carry_their_substrate_tiers() -> None:
    """Mathematics: `project(process) = E0` and `project(owned_frame) = E1`, preserving the semantic substrate distinction."""

    address = NetworkAddress("root", "eth0")
    frame = NetworkFrame(1, address, address, b"payload", 0, (address, address))
    process = ProcessReport(1, "init", "exited", 0, 0, {}, 0, 0, {})
    assert process.to_dict()["evidence_tier"] == "E0"
    assert frame.to_dict()["evidence_tier"] == "E1"
