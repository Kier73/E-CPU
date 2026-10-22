from __future__ import annotations

from dataclasses import replace

import pytest

from mailcpu import (
    HeadlessOS,
    SeedAdmissionError,
    SeedInputReceipt,
    SystemIdentity,
    SystemSeed,
    SystemSeedEnvelope,
)


PROGRAM = "set value 1\nset one 1\nadd value value one\nhalt\n"


def _machine() -> HeadlessOS:
    """Mathematics: construct a deterministic reachable orbit `S_k=T^k(S_0)` for admission progression witnesses."""

    machine = HeadlessOS()
    machine.launch_source(PROGRAM, "admission-orbit")
    return machine


def _envelope(
    system_id: str,
    seed: SystemSeed,
    *,
    incarnation: int = 1,
    sequence: int = 1,
    digest: str = "a" * 64,
    channel: str = "ops",
) -> SystemSeedEnvelope:
    """Mathematics: construct `E=(I,role,channel,Σ,F)` with one source frontier coordinate."""

    return SystemSeedEnvelope(
        SystemIdentity(system_id, incarnation),
        "origin",
        channel,
        seed,
        (SeedInputReceipt("resolver", sequence, digest),),
    )


def test_seed_admission_accepts_monotone_progress_and_replays_exact_bytes() -> None:
    """Mathematics: `R[s]:=E₂` iff `k₂>k₁` and `q₂≥q₁`; equal `f(E)` returns the original receipt."""

    operating_system = _machine()
    origin = SystemSeed.from_system(operating_system)
    first = _envelope("admission-system", origin)
    first_result = operating_system.seed_admission.admit(first)
    assert first_result.accepted and not first_result.replayed
    duplicate = operating_system.seed_admission.admit(first)
    assert duplicate.accepted and duplicate.replayed
    assert duplicate.admission_receipt == first_result.admission_receipt

    advanced = _envelope("admission-system", origin.at(1), sequence=2)
    advanced_result = operating_system.seed_admission.admit(advanced)
    assert advanced_result.accepted and not advanced_result.replayed
    assert operating_system.seed_admission.current("admission-system").snapshot() == advanced.snapshot()


def test_seed_admission_refuses_stale_frontier_incarnation_and_digest_conflicts_without_mutation() -> None:
    """Mathematics: every refusal preserves `R' = R`, including `q'<q`, `inc'<inc`, and equal-coordinate `d'≠d`."""

    operating_system = _machine()
    origin = SystemSeed.from_system(operating_system)
    admitted = _envelope("protected-system", origin, sequence=2)
    assert operating_system.seed_admission.admit(admitted).accepted
    before = operating_system.seed_admission.current("protected-system").snapshot()

    lower_frontier = _envelope("protected-system", origin.at(1), sequence=1, channel="lower-frontier")
    lower_result = operating_system.seed_admission.admit(lower_frontier)
    assert not lower_result.accepted and "frontier" in (lower_result.reason or "")

    stale_incarnation = _envelope("protected-system", origin.at(3), incarnation=1, sequence=3, channel="stale-route")
    newer = _envelope("protected-system", origin.at(3), incarnation=2, sequence=1, channel="new-incarnation")
    assert operating_system.seed_admission.admit(newer).accepted
    stale_result = operating_system.seed_admission.admit(stale_incarnation)
    assert not stale_result.accepted and "stale" in (stale_result.reason or "")

    same_coordinate_seed = replace(newer.seed, state_digest="1" * 64)
    same_coordinate = _envelope(
        "protected-system",
        same_coordinate_seed,
        incarnation=2,
        sequence=1,
        channel="same-coordinate",
    )
    same_coordinate_result = operating_system.seed_admission.admit(same_coordinate)
    assert not same_coordinate_result.accepted and "same-coordinate" in (same_coordinate_result.reason or "")

    conflict_host = _machine()
    conflict_host.install_source("/different-origin", "different origin")
    conflict_origin = SystemSeed.from_system(conflict_host)
    conflict = _envelope("protected-system", conflict_origin, incarnation=2, sequence=1, channel="conflict-origin")
    conflict_result = operating_system.seed_admission.admit(conflict)
    assert not conflict_result.accepted and "origin conflict" in (conflict_result.reason or "")
    assert operating_system.seed_admission.current("protected-system").snapshot() == newer.snapshot()
    assert before["identity"] != newer.snapshot()["identity"]


def test_seed_admission_shadow_restores_before_registry_mutation() -> None:
    """Mathematics: `restore(E)=⊥` implies `R' = R` and a refusal receipt, never partial registration."""

    operating_system = _machine()
    origin = SystemSeed.from_system(operating_system)
    invalid_seed = replace(origin, state_digest="0" * 64)
    result = operating_system.seed_admission.admit(_envelope("invalid-system", invalid_seed))
    assert not result.accepted
    assert "restore refused" in (result.reason or "")
    assert operating_system.seed_admission.current("invalid-system") is None


def test_seed_admission_checkpoint_restores_registry_and_replay_ledger() -> None:
    """Mathematics: `restore(snapshot(R,L))=(R,L)` and duplicate admission after restore returns the stored receipt."""

    operating_system = _machine()
    origin = SystemSeed.from_system(operating_system)
    envelope = _envelope("checkpointed-system", origin)
    result = operating_system.seed_admission.admit(envelope)
    assert result.accepted
    checkpoint = operating_system.snapshot()

    restored = HeadlessOS.from_snapshot(checkpoint)
    assert restored.seed_admission.snapshot() == operating_system.seed_admission.snapshot()
    replay = restored.seed_admission.admit(envelope)
    assert replay.accepted and replay.replayed
    assert replay.admission_receipt == result.admission_receipt


def test_seed_admission_supports_multiple_systems_in_one_hypervisor_registry() -> None:
    """Mathematics: registry projection is a keyed product `R={s₁↦E₁,s₂↦E₂}` with disjoint identities."""

    operating_system = _machine()
    origin = SystemSeed.from_system(operating_system)
    first = _envelope("system-a", origin)
    second = _envelope("system-b", origin, channel="other")
    assert operating_system.seed_admission.admit(first).accepted
    assert operating_system.seed_admission.admit(second).accepted
    assert [item.identity.system_id for item in operating_system.seed_admission.systems()] == ["system-a", "system-b"]


def test_seed_admission_rejects_invalid_public_inputs() -> None:
    """Mathematics: admission is defined only on the typed envelope domain `E`; values outside `E` fail closed."""

    operating_system = HeadlessOS()
    with pytest.raises(SeedAdmissionError, match="SystemSeedEnvelope"):
        operating_system.seed_admission.admit(object())
