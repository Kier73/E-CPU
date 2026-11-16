"""LENS-001 regression tests: finite witnesses, inverse, memory and recovery."""
from __future__ import annotations

import random

import pytest

from mailcpu.law_certifier import Law, Refused, find_guarded, lcg_navigate, navigate_guarded
from mailcpu.lens_ground import (
    FRAMES, MASK, MODULUS, INVERSE, backward_frames, find_lens,
    navigate_lens, recover_lens_law, transform,
)
from mailcpu.structural_memory import (
    StructuralMemoryError, StructuralMemoryRefused, StructuralMemoryRegistry,
)


def _gray_trace(length: int = 120) -> list[int]:
    origin = (1 << 40) + 23
    return [transform((origin + t) & MASK, "gray.encode") for t in range(length)]


def _two_frame_trace(length: int = 120) -> list[int]:
    frames = ["gray.decode", "rotate.left.7"]
    return [
        backward_frames(lcg_navigate(5, 1, MODULUS, 17, t), frames)
        for t in range(length)
    ]


@pytest.mark.parametrize("frame", FRAMES)
def test_every_frame_is_exactly_invertible(frame: str) -> None:
    for value in (0, 1, 7, 0x123456789ABCDEF0, MASK):
        assert transform(transform(value, frame), INVERSE[frame]) == value


def test_gray_counter_ground_direct_far_seek_and_inverse() -> None:
    trace = _gray_trace()
    law = recover_lens_law(trace[:80], trace[80:])
    assert law.family == "lens64"
    assert law.verdict == "GROUND"
    assert law.params["frames"] == ["gray.decode"]
    for t in (0, 3, 94, 1 << 50):
        expected = transform(((1 << 40) + 23 + t) & MASK, "gray.encode")
        assert navigate_guarded(law, t) == expected
    t = 34345
    assert find_guarded(law, navigate_guarded(law, t)) == t


def test_two_frames_preserve_hidden_affine_law() -> None:
    trace = _two_frame_trace()
    law = recover_lens_law(trace[:80], trace[80:])
    assert law.family == "lens64"
    assert len(law.params["frames"]) <= 2
    for t in (3, 110, (1 << 45) + 77):
        expected = backward_frames(
            lcg_navigate(5, 1, MODULUS, 17, t),
            ["gray.decode", "rotate.left.7"],
        )
        assert navigate_guarded(law, t) == expected
    assert find_guarded(law, navigate_guarded(law, 319)) == 319


def test_mutated_probe_and_random_control_are_refused() -> None:
    values = _gray_trace()
    wrong = list(values[80:])
    wrong[0] ^= 1 << 40
    assert recover_lens_law(values[:80], wrong).verdict == "TAPE"
    rng = random.Random(1337)
    random_values = [rng.getrandbits(64) for _ in range(100)]
    assert recover_lens_law(random_values[:70], random_values[70:]).verdict == "TAPE"


def test_structural_memory_opt_in_admission_receipt_and_snapshot() -> None:
    trace = _gray_trace()
    registry = StructuralMemoryRegistry(admission_policy=lambda proposal: True)
    with pytest.raises(StructuralMemoryRefused):
        registry.propose_trace("gray", trace[:80], trace[80:])
    proposal = registry.propose_trace(
        "gray", trace[:80], trace[80:],
        allow_lens=True, context={"source": "LENS-001"},
    )
    assert proposal.spec.family == "lens64"
    version = registry.admit(proposal.proposal_id, expected_revision=0)
    t = (1 << 50) + 987
    receipt = registry.read_revision("gray", version.spec.revision, t, context={"source": "LENS-001"})
    assert receipt.value == transform(((1 << 40) + 23 + t) & MASK, "gray.encode")
    assert receipt.spec_digest == version.spec.digest
    assert receipt.certificate_digest == version.certificate.digest
    assert len(receipt.receipt_id) == 64
    snapshot = registry.snapshot()
    restored = StructuralMemoryRegistry.from_snapshot(snapshot, admission_policy=lambda proposal: True)
    recovered_receipt = restored.read_revision("gray", version.spec.revision, t, context={"source": "LENS-001"})
    assert recovered_receipt.receipt_id == receipt.receipt_id
    with pytest.raises(StructuralMemoryRefused):
        restored.read_revision("gray", version.spec.revision, t, context={"source": "other"})


def test_reject_untrusted_lens_descriptors() -> None:
    registry = StructuralMemoryRegistry(admission_policy=lambda proposal: True)
    law = recover_lens_law(_gray_trace()[:80], _gray_trace()[80:])
    for params in (
        {**law.params, "frames": ["python.eval"]},
        {**law.params, "width": 63},
        {**law.params, "frames": ["gray.encode", "gray.decode"]},
        {**law.params, "c": -1},
    ):
        malicious = Law(family="lens64", params=params, order=1, verdict="GROUND")
        with pytest.raises(StructuralMemoryError):
            registry.propose("invalid", malicious, {0: 0, 1: 1})


def test_prefix_lens_horizon_rejects_escaped_reads() -> None:
    trace = _gray_trace()
    candidate = recover_lens_law(trace[:80], trace[80:])
    prefix = Law(
        family="lens64", params=candidate.params, order=1,
        verdict="PREFIX-GROUND", first_bad=20,
    )
    registry = StructuralMemoryRegistry(admission_policy=lambda proposal: True)
    witnesses = {i: trace[i] for i in range(20)}
    witnesses[20] = trace[20] ^ 1
    proposal = registry.propose("prefix", prefix, witnesses)
    registry.admit(proposal.proposal_id, expected_revision=0)
    assert registry.read("prefix", 19).value == trace[19]
    with pytest.raises(StructuralMemoryRefused):
        registry.read("prefix", 20)
    with pytest.raises(Refused):
        navigate_guarded(prefix, 20)


def test_non_full_period_inverse_is_refused_without_brute_force() -> None:
    params = {"width": 64, "frames": ["gray.decode"], "a": 3, "c": 2, "x0": 19}
    assert navigate_lens(params, 9) >= 0
    with pytest.raises(Refused, match="direct inverse"):
        find_lens(params, 19)
