"""Conformance tests for the E0 structural-memory service."""

from __future__ import annotations

import pytest

from mailcpu.journal import EventJournal
from mailcpu.law_certifier import Law
from mailcpu.structural_memory import (
    StructuralMemoryAuthorizationError,
    StructuralMemoryConflict,
    StructuralMemoryError,
    StructuralMemoryRefused,
    StructuralMemoryRegistry,
    StructuralMemorySpec,
    StructuralMemoryVerifier,
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
    competing_law = _integer_law()
    competing_law.params["x0"] = 10
    competing = registry.propose("counter", competing_law, {0: 10, 1: 11, 2: 12})
    assert first.proposal_id != competing.proposal_id

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


def test_context_only_revision_preserves_generator_and_keeps_parent_readable():
    journal = EventJournal()
    registry = StructuralMemoryRegistry(
        admission_policy=lambda proposal: True,
        journal=journal,
    )
    parent_proposal = registry.propose(
        "scoped-counter",
        _integer_law(),
        {0: 0, 1: 1, 2: 2, 3: 3},
        context={"tenant": "alpha"},
    )
    parent = registry.admit(parent_proposal.proposal_id, expected_revision=0)

    with pytest.raises(StructuralMemoryRefused, match="must change"):
        registry.propose_context_revision(
            "scoped-counter",
            {"tenant": "alpha"},
            {10: 10, 11: 11, 12: 12},
        )
    with pytest.raises(StructuralMemoryRefused, match="witness mismatch"):
        registry.propose_context_revision(
            "scoped-counter",
            {"tenant": "beta"},
            {10: 0, 11: 1, 12: 2},
        )

    proposal = registry.propose_context_revision(
        "scoped-counter",
        {"tenant": "beta"},
        {10: 10, 11: 11, 12: 12},
    )
    assert registry.active_version("scoped-counter") == parent
    assert proposal.spec.revision == 2
    assert proposal.spec.parent_digest == parent.spec.digest
    assert proposal.spec.family == parent.spec.family
    assert proposal.spec.parameters == parent.spec.parameters
    assert proposal.spec.order == parent.spec.order
    assert proposal.spec.law_verdict == parent.spec.law_verdict
    assert proposal.spec.first_bad == parent.spec.first_bad
    assert proposal.spec.domain == parent.spec.domain
    assert proposal.spec.context == {"tenant": "beta"}

    with pytest.raises(StructuralMemoryRefused, match="context"):
        registry.read("scoped-counter", 20, context={"tenant": "beta"})
    assert registry.read("scoped-counter", 20, context={"tenant": "alpha"}).value == 20

    child = registry.admit(proposal.proposal_id, expected_revision=1)
    assert child.spec.digest != parent.spec.digest
    assert registry.active_version("scoped-counter") == child
    with pytest.raises(StructuralMemoryRefused, match="context"):
        registry.read("scoped-counter", 20, context={"tenant": "alpha"})

    latest = registry.read("scoped-counter", 20, context={"tenant": "beta"})
    historical = registry.read_revision(
        "scoped-counter",
        1,
        20,
        context={"tenant": "alpha"},
    )
    assert latest.revision == 2
    assert historical.revision == 1
    assert latest.value == historical.value == 20
    assert historical.spec_digest == parent.spec.digest

    snapshot = registry.snapshot()
    restored = StructuralMemoryRegistry.from_snapshot(
        snapshot,
        journal=EventJournal.from_snapshot(journal.snapshot()),
    )
    assert restored.active_version("scoped-counter") == child
    assert restored.read_revision(
        "scoped-counter",
        1,
        20,
        context={"tenant": "alpha"},
    ).value == 20
    assert restored.read(
        "scoped-counter",
        20,
        context={"tenant": "beta"},
    ).value == 20
    assert restored.journal.verify()


def test_context_only_revision_requires_an_active_parent():
    registry = _registry(lambda proposal: True)
    with pytest.raises(StructuralMemoryRefused, match="no admitted revision"):
        registry.propose_context_revision(
            "missing",
            {"tenant": "beta"},
            {10: 10, 11: 11},
        )


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


def test_verifier_rejects_boolean_coordinates_even_when_called_directly():
    spec = StructuralMemorySpec.from_law("counter", 1, "integer-orbit", _integer_law())
    verifier = StructuralMemoryVerifier()

    with pytest.raises(StructuralMemoryError):
        verifier.certify(spec, ((False, 0), (1, 1)))


def test_boolean_coordinates_and_boolean_witnesses_are_rejected():
    registry = _registry(lambda proposal: True)
    with pytest.raises(StructuralMemoryError):
        registry.propose("counter", _integer_law(), {False: 0, 1: 1})
    proposal = registry.propose("counter", _integer_law(), {0: 0, 1: 1, 2: 2})
    registry.admit(proposal.proposal_id, expected_revision=0)
    with pytest.raises(StructuralMemoryError):
        registry.read("counter", True)


def test_registry_snapshot_round_trips_active_history_staged_proposals_and_cache():
    registry = StructuralMemoryRegistry(admission_policy=lambda proposal: True, journal=EventJournal())
    first = registry.propose("persistent", _integer_law(), {0: 0, 1: 1, 2: 2})
    active = registry.admit(first.proposal_id, expected_revision=0)
    first_read = registry.read("persistent", 9)
    cached_read = registry.read("persistent", 9)

    next_law = _integer_law()
    next_law.params["x0"] = 5
    staged = registry.propose("persistent", next_law, {0: 5, 1: 6, 2: 7})
    snapshot = registry.snapshot()
    restored = StructuralMemoryRegistry.from_snapshot(
        snapshot,
        admission_policy=lambda proposal: True,
        journal=EventJournal.from_snapshot(registry.journal.snapshot()),
    )

    assert restored.active_version("persistent") == active
    assert restored.staged_proposal(staged.proposal_id) == staged
    resumed_read = restored.read("persistent", 9)
    assert resumed_read.value == first_read.value
    assert resumed_read.receipt_id == first_read.receipt_id
    assert resumed_read.cache_hit is True
    assert cached_read.cache_hit is True


def test_registry_snapshot_refuses_tampered_proposal_witnesses():
    registry = _registry(lambda proposal: True)
    proposal = registry.propose("persistent", _integer_law(), {0: 0, 1: 1, 2: 2})
    snapshot = registry.snapshot()
    snapshot["proposals"][0]["witnesses"][0][1] = 99

    with pytest.raises(StructuralMemoryError):
        StructuralMemoryRegistry.from_snapshot(snapshot)


def test_registry_journal_reconciles_proposal_admission_and_read_events():
    journal = EventJournal()
    registry = StructuralMemoryRegistry(admission_policy=lambda proposal: True, journal=journal)
    proposal = registry.propose("journaled", _integer_law(), {0: 0, 1: 1, 2: 2})
    registry.admit(proposal.proposal_id, expected_revision=0)
    registry.read("journaled", 7)
    registry.read("journaled", 7)

    kinds = [record.kind for record in journal.records()]
    assert kinds == [
        "structural_memory.propose",
        "structural_memory.admit",
        "structural_memory.read",
        "structural_memory.read",
    ]
    snapshot = registry.snapshot()
    restored = StructuralMemoryRegistry.from_snapshot(
        snapshot,
        journal=EventJournal.from_snapshot(journal.snapshot()),
    )
    assert restored.active_version("journaled") is not None

    snapshot["journal_anchor"]["digest"] = "0" * 64
    with pytest.raises(StructuralMemoryError, match="anchor"):
        StructuralMemoryRegistry.from_snapshot(
            snapshot,
            journal=EventJournal.from_snapshot(journal.snapshot()),
        )


def _reordered_journal(records, indices):
    """Mathematics: construct a newly valid hash chain over the selected event permutation."""
    journal = EventJournal()
    for index in indices:
        record = records[index]
        journal.append(record["kind"], record["payload"])
    return journal


def _bind_snapshot_to_journal(snapshot, journal):
    """Mathematics: set the registry anchor to the terminal identity of the supplied test journal."""
    records = journal.snapshot()
    snapshot["journal_anchor"] = {
        "sequence": len(records),
        "digest": "0" * 64 if not records else records[-1]["digest"],
    }


def test_restore_rejects_child_proposal_journaled_before_parent_admission():
    registry = StructuralMemoryRegistry(admission_policy=lambda proposal: True, journal=EventJournal())
    parent = registry.propose("ordered", _integer_law(), {0: 0, 1: 1, 2: 2})
    registry.admit(parent.proposal_id, expected_revision=0)
    child_law = _integer_law()
    child_law.params["x0"] = 5
    registry.propose("ordered", child_law, {0: 5, 1: 6, 2: 7})

    snapshot = registry.snapshot()
    records = registry.journal.snapshot()
    reordered = _reordered_journal(records, [0, 2, 1])
    _bind_snapshot_to_journal(snapshot, reordered)

    with pytest.raises(StructuralMemoryError, match="precedes parent admission"):
        StructuralMemoryRegistry.from_snapshot(snapshot, journal=reordered)


def test_restore_rejects_historical_read_after_new_revision_admission():
    registry = StructuralMemoryRegistry(admission_policy=lambda proposal: True, journal=EventJournal())
    first = registry.propose("ordered-read", _integer_law(), {0: 0, 1: 1, 2: 2})
    registry.admit(first.proposal_id, expected_revision=0)
    registry.read("ordered-read", 7)
    second_law = _integer_law()
    second_law.params["x0"] = 5
    second = registry.propose("ordered-read", second_law, {0: 5, 1: 6, 2: 7})
    registry.admit(second.proposal_id, expected_revision=1)

    snapshot = registry.snapshot()
    records = registry.journal.snapshot()
    reordered = _reordered_journal(records, [0, 1, 3, 4, 2])
    _bind_snapshot_to_journal(snapshot, reordered)

    with pytest.raises(StructuralMemoryError, match="after a newer revision"):
        StructuralMemoryRegistry.from_snapshot(snapshot, journal=reordered)


def test_registry_snapshot_persists_staged_proposal_without_serializing_admission_policy():
    policy = lambda proposal: True
    registry = StructuralMemoryRegistry(admission_policy=policy, journal=EventJournal())
    proposal = registry.propose("needs-policy", _integer_law(), {0: 0, 1: 1, 2: 2})
    snapshot = registry.snapshot()
    restored = StructuralMemoryRegistry.from_snapshot(
        snapshot,
        journal=EventJournal.from_snapshot(registry.journal.snapshot()),
    )

    assert restored.staged_proposal(proposal.proposal_id) == proposal
    with pytest.raises(StructuralMemoryAuthorizationError, match="explicit"):
        restored.admit(proposal.proposal_id, expected_revision=0)
