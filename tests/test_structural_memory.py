"""Conformance tests for the E0 structural-memory service."""

from __future__ import annotations

import pytest

from mailcpu.law_certifier import Law
from mailcpu.structural_memory import (
    StructuralMemoryAuthorizationError,
    StructuralMemoryConflict,
    StructuralMemoryError,
    StructuralMemoryRefused,
    StructuralMemoryRegistry,
    VerificationClass,
)


def _registry(policy=None):
    return StructuralMemoryRegistry(admission_policy=policy)


def _integer_law(verdict="GROUND", first_bad=None):
    return Law(
        family="int",
        params={"x0": 0, "step": 1, "mod": 97},
        order=1,
        verdict=verdict,
        first_bad=first_bad,
    )


def test_proposal_is_staged_until_explicit_host_admission():
    registry = _registry(lambda proposal: True)
    proposal = registry.propose(
        "counter",
        _integer_law(),
        {0: 0, 1: 1, 2: 2, 3: 3},
        context={"tenant": "alpha"},
    )

    assert registry.active_version("counter") is None
    assert proposal.spec.revision == 1
    assert proposal.spec.parent_digest is None
    assert proposal.certificate.verification_class is VerificationClass.WITNESS_GROUNDED
    with pytest.raises(StructuralMemoryRefused, match="no admitted version"):
        registry.read("counter", 10)

    admitted = registry.admit(proposal.proposal_id, expected_revision=0)
    assert admitted.spec.digest == proposal.spec.digest
    assert registry.active_version("counter") == admitted
    assert registry.read("counter", 10).value == 10


def test_read_receipt_binds_spec_certificate_context_and_value():
    registry = _registry(lambda proposal: True)
    proposal = registry.propose(
        "counter",
        _integer_law(),
        {0: 0, 1: 1, 2: 2, 3: 3},
        context={"tenant": "alpha", "partition": 7},
    )
    registry.admit(proposal.proposal_id, expected_revision=0)

    first = registry.read("counter", 12)
    repeated = registry.read("counter", 12)

    assert first.value == 12
    assert len(first.receipt_id) == 64
    assert len(first.spec_digest) == 64
    assert len(first.certificate_digest) == 64
    assert len(first.context_digest) == 64
    assert len(first.value_digest) == 64
    assert first.verification_class is VerificationClass.WITNESS_GROUNDED
    assert first.witness_digest == proposal.certificate.witness_digest
    assert first.cache_hit is False
    assert repeated.receipt_id == first.receipt_id
    assert repeated.cache_hit is True


def test_cache_hit_does_not_reinvoke_the_generator(monkeypatch):
    registry = _registry(lambda proposal: True)
    proposal = registry.propose(
        "counter",
        _integer_law(),
        {0: 0, 1: 1, 2: 2, 3: 3},
    )
    registry.admit(proposal.proposal_id, expected_revision=0)
    original = registry.read("counter", 8)

    def forbidden_navigation(*args, **kwargs):
        pytest.fail("a cache hit must not evaluate the generator again")

    monkeypatch.setattr(registry.generators, "navigate_guarded", forbidden_navigation)
    cached = registry.read("counter", 8)

    assert cached.value == original.value
    assert cached.receipt_id == original.receipt_id
    assert cached.cache_hit is True


def test_context_is_an_exact_revision_boundary():
    registry = _registry(lambda proposal: True)
    proposal = registry.propose(
        "counter",
        _integer_law(),
        {0: 0, 1: 1, 2: 2, 3: 3},
        context={"tenant": "alpha"},
    )
    registry.admit(proposal.proposal_id, expected_revision=0)

    with pytest.raises(StructuralMemoryRefused, match="context"):
        registry.read("counter", 2, context={"tenant": "beta"})

    assert registry.read("counter", 2, context={"tenant": "alpha"}).value == 2


def test_prefix_certificate_requires_matching_prefix_and_escape_at_first_bad():
    registry = _registry(lambda proposal: True)
    law = _integer_law(verdict="PREFIX-GROUND", first_bad=4)
    proposal = registry.propose(
        "prefix-counter",
        law,
        {0: 0, 1: 1, 2: 2, 3: 3, 4: 40},
    )

    assert proposal.certificate.verification_class is VerificationClass.PREFIX_GROUNDED
    assert proposal.certificate.first_bad == 4
    assert proposal.certificate.valid_before_exclusive == 4
    registry.admit(proposal.proposal_id, expected_revision=0)

    assert registry.read("prefix-counter", 3).value == 3
    with pytest.raises(StructuralMemoryRefused, match="horizon"):
        registry.read("prefix-counter", 4)
    with pytest.raises(StructuralMemoryRefused, match="horizon"):
        registry.read("prefix-counter", 100)


def test_prefix_certificate_rejects_a_non_escaping_boundary_witness():
    registry = _registry(lambda proposal: True)
    with pytest.raises(StructuralMemoryRefused, match="does not escape"):
        registry.propose(
            "bad-prefix",
            _integer_law(verdict="PREFIX-GROUND", first_bad=4),
            {0: 0, 1: 1, 2: 2, 3: 3, 4: 4},
        )


def test_prefix_certificate_rejects_witnesses_after_first_bad():
    registry = _registry(lambda proposal: True)
    with pytest.raises(StructuralMemoryRefused, match="beyond first_bad"):
        registry.propose(
            "bad-prefix",
            _integer_law(verdict="PREFIX-GROUND", first_bad=4),
            {0: 0, 1: 1, 2: 2, 3: 3, 4: 40, 5: 5},
        )


def test_fitted_tape_and_unregistered_families_are_not_admitted():
    registry = _registry(lambda proposal: True)
    fitted = Law(
        family="int",
        params={"x0": 0, "step": 1, "mod": 97},
        order=1,
        verdict="FITTED",
    )
    tape = Law(family="tape", params={}, order=0, verdict="TAPE")
    k_regular = Law(
        family="kreg",
        params={"k": 2, "rules": {}, "base_vals": {0: 0}},
        order=2,
        verdict="GROUND",
    )

    for memory_id, law in (
        ("fitted", fitted),
        ("tape", tape),
        ("kreg", k_regular),
    ):
        with pytest.raises(StructuralMemoryRefused):
            registry.propose(memory_id, law, {0: 0, 1: 1})


def test_host_admission_policy_is_mandatory_and_denial_preserves_active_state():
    registry = _registry(lambda proposal: False)
    proposal = registry.propose(
        "counter",
        _integer_law(),
        {0: 0, 1: 1, 2: 2},
    )

    with pytest.raises(StructuralMemoryAuthorizationError, match="literal True"):
        registry.admit(proposal.proposal_id, expected_revision=0)
    assert registry.active_version("counter") is None

    no_policy = StructuralMemoryRegistry()
    proposal_without_policy = no_policy.propose(
        "counter",
        _integer_law(),
        {0: 0, 1: 1, 2: 2},
    )
    with pytest.raises(StructuralMemoryAuthorizationError, match="explicit"):
        no_policy.admit(proposal_without_policy.proposal_id, expected_revision=0)


def test_stale_proposal_cannot_replace_newer_active_revision():
    registry = _registry(lambda proposal: True)
    first = registry.propose("counter", _integer_law(), {0: 0, 1: 1, 2: 2})
    competing = registry.propose("counter", _integer_law(), {0: 0, 1: 1, 2: 2})

    active = registry.admit(first.proposal_id, expected_revision=0)
    with pytest.raises(StructuralMemoryConflict):
        registry.admit(competing.proposal_id, expected_revision=0)
    with pytest.raises(StructuralMemoryConflict):
        registry.admit(competing.proposal_id, expected_revision=1)
    assert registry.active_version("counter") == active


def test_revision_is_immutable_and_links_to_its_parent():
    registry = _registry(lambda proposal: True)
    original_law = _integer_law()
    first = registry.propose("counter", original_law, {0: 0, 1: 1, 2: 2})
    original = registry.admit(first.proposal_id, expected_revision=0)

    original_law.params["x0"] = 10
    second_law = _integer_law()
    second_law.params["x0"] = 5
    second = registry.propose(
        "counter",
        second_law,
        {0: 5, 1: 6, 2: 7},
        context={"boundary_revision": 2},
    )
    updated = registry.admit(second.proposal_id, expected_revision=1)

    assert updated.spec.revision == 2
    assert updated.spec.parent_digest == original.spec.digest
    assert original.spec.parameters["x0"] == 0
    assert updated.spec.parameters["x0"] == 5
    assert registry.read("counter", 0).value == 5
    assert original.spec.digest != updated.spec.digest


def test_trace_proposal_uses_known_law_recovery_and_withheld_witnesses():
    registry = _registry(lambda proposal: True)
    lane = [(65500 + 17 * coordinate) % 65536 for coordinate in range(50)]
    proposal = registry.propose_trace(
        "modular-counter",
        lane[:30],
        lane[30:],
        context={"stream": "test"},
    )

    assert proposal.spec.family == "int"
    assert proposal.certificate.verification_class is VerificationClass.WITNESS_GROUNDED
    assert proposal.certificate.witness_count == len(lane)
    registry.admit(proposal.proposal_id, expected_revision=0)
    for coordinate in (0, 17, 30, 49, 1000):
        expected = (65500 + 17 * coordinate) % 65536
        assert registry.read("modular-counter", coordinate).value == expected


def test_lcg_generator_adapter_navigates_the_affine_orbit():
    registry = _registry(lambda proposal: True)
    a, c, modulus, x0 = 5, 1, 256, 13
    lane = [x0]
    for _ in range(12):
        lane.append((a * lane[-1] + c) % modulus)
    law = Law(
        family="lcg",
        params={"a": a, "c": c, "mod": modulus, "x0": x0},
        order=1,
        verdict="GROUND",
    )
    proposal = registry.propose("lcg", law, {i: value for i, value in enumerate(lane)})
    registry.admit(proposal.proposal_id, expected_revision=0)
    assert registry.read("lcg", 12).value == lane[12]


def test_gf2_generator_adapter_navigates_a_linear_recurrence():
    registry = _registry(lambda proposal: True)
    lane = [1, 1]
    for _ in range(14):
        lane.append(lane[-1] ^ lane[-2])
    law = Law(
        family="gf2",
        params={"C": [1, 1, 1], "init": [1, 1]},
        order=2,
        verdict="GROUND",
    )
    proposal = registry.propose("gf2", law, {i: value for i, value in enumerate(lane)})
    registry.admit(proposal.proposal_id, expected_revision=0)
    assert registry.read("gf2", 12).value == lane[12]


def test_fgraph_generator_adapter_navigates_preperiod_and_cycle():
    registry = _registry(lambda proposal: True)
    law = Law(
        family="fgraph",
        params={"orbit": [10, 20, 30, 40, 50], "mu": 3, "lam": 2},
        order=2,
        verdict="GROUND",
    )
    lane = [10, 20, 30, 40, 50, 40, 50, 40, 50]
    proposal = registry.propose("fgraph", law, {i: value for i, value in enumerate(lane)})
    registry.admit(proposal.proposal_id, expected_revision=0)
    assert registry.read("fgraph", 8).value == 50


def test_boolean_coordinates_and_boolean_witnesses_are_rejected():
    registry = _registry(lambda proposal: True)
    with pytest.raises(StructuralMemoryError):
        registry.propose("counter", _integer_law(), {False: 0, 1: 1})
    proposal = registry.propose("counter", _integer_law(), {0: 0, 1: 1, 2: 2})
    registry.admit(proposal.proposal_id, expected_revision=0)
    with pytest.raises(StructuralMemoryError):
        registry.read("counter", True)
