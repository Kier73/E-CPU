from __future__ import annotations

import hashlib
import json
import subprocess
import sys

import pytest

from mailcpu import (
    DurableSeedCommitLedger,
    SeedCommitCertificate,
    SeedCommitLedgerError,
    SeedCommitMembership,
    SeedCommitProposal,
    SeedPrepareVote,
)


GENESIS = "0" * 64
NEXT = "1" * 64
OTHER = "2" * 64
REQUEST = "a" * 64


def _membership() -> SeedCommitMembership:
    """Mathematics: construct fixed configuration `M=(S,I,N,owner,term,g,q)` with strict majority `2q>|N|`."""

    return SeedCommitMembership("system-A", 1, ("A", "B", "C"), "A", 1, GENESIS)


def _proposal(
    membership: SeedCommitMembership,
    *,
    slot: int = 1,
    previous: str = GENESIS,
    result: str = NEXT,
    request: str = REQUEST,
) -> SeedCommitProposal:
    """Mathematics: bind one seed edge `e=(slot,previous,request,result)` to the canonical fixed membership digest."""

    return SeedCommitProposal(
        membership.digest,
        membership.system_id,
        membership.incarnation,
        membership.owner_id,
        membership.owner_term,
        slot,
        previous,
        request,
        result,
    )


def test_seed_commit_membership_digest_is_order_independent_and_majority_only() -> None:
    """Mathematics: canonical membership permutation preserves `d(M)`, while every admissible quorum satisfies `2q>|N|`."""

    first = SeedCommitMembership("system-A", 1, ("C", "A", "B"), "A", 1, GENESIS)
    second = SeedCommitMembership("system-A", 1, ("B", "C", "A"), "A", 1, GENESIS)
    assert first.digest == second.digest
    assert first.member_ids == ("A", "B", "C")
    with pytest.raises(SeedCommitLedgerError, match="strict majority"):
        SeedCommitMembership("system-A", 1, ("A", "B", "C"), "A", 1, GENESIS, quorum=1)
    for malformed_members in (None, "ABC", 17):
        with pytest.raises(SeedCommitLedgerError, match="finite sequence"):
            SeedCommitMembership("system-A", 1, malformed_members, "A", 1, GENESIS)


def test_prepare_vote_is_single_valued_across_restart_and_slot_conflict(tmp_path) -> None:
    """Mathematics: each `(membership,term,slot)` maps to at most one proposal digest, including after journal replay."""

    membership = _membership()
    proposal = _proposal(membership)
    ledger_path = tmp_path / "A.log"
    ledger = DurableSeedCommitLedger(ledger_path, "A", membership)
    vote = ledger.prepare(proposal)
    assert ledger.prepare(proposal) == vote
    assert ledger.verify()

    reopened = DurableSeedCommitLedger(ledger_path, "A", membership)
    assert reopened.prepare(proposal) == vote
    conflict = _proposal(membership, result=OTHER)
    with pytest.raises(SeedCommitLedgerError, match="already prepared"):
        reopened.prepare(conflict)
    assert reopened.snapshot()["sequence"] == 1


def test_independent_journal_instances_refresh_before_accepting_a_vote(tmp_path) -> None:
    """Mathematics: two handles to one serialized log observe the same winner and cannot append distinct values for one slot."""

    membership = _membership()
    path = tmp_path / "shared.log"
    first = DurableSeedCommitLedger(path, "A", membership)
    second = DurableSeedCommitLedger(path, "A", membership)
    chosen = _proposal(membership)
    conflict = _proposal(membership, result=OTHER)
    vote = first.prepare(chosen)
    with pytest.raises(SeedCommitLedgerError, match="already prepared"):
        second.prepare(conflict)
    assert second.prepare(chosen) == vote
    assert first.snapshot()["head_hex"] == second.snapshot()["head_hex"]


def test_commit_requires_majority_durable_prepare_votes_and_replays_after_restart(tmp_path) -> None:
    """Mathematics: commit is admitted only for `|V|≥q` matching durable votes, then every replay returns the same decision."""

    membership = _membership()
    proposal = _proposal(membership)
    ledgers = {
        member: DurableSeedCommitLedger(tmp_path / f"{member}.log", member, membership)
        for member in membership.member_ids
    }
    votes = tuple(ledgers[member].prepare(proposal) for member in ("A", "B"))
    certificate = SeedCommitCertificate(membership.digest, proposal.digest, votes)
    with pytest.raises(SeedCommitLedgerError, match="not prepared"):
        ledgers["C"].commit(proposal, certificate)
    decisions = tuple(ledgers[member].commit(proposal, certificate) for member in ("A", "B"))
    assert decisions[0].proposal_digest == proposal.digest
    assert decisions[0].state_digest == NEXT
    assert ledgers["A"].commit(proposal, certificate) == decisions[0]

    restored = DurableSeedCommitLedger(tmp_path / "A.log", "A", membership)
    assert restored.committed_state() == (1, NEXT)
    assert restored.commit(proposal, certificate) == decisions[0]
    assert restored.verify()


def test_majority_intersection_prevents_two_prepared_histories_at_one_slot(tmp_path) -> None:
    """Mathematics: for `2q>|N|`, any two quorums intersect, and an intersecting member's one-vote law blocks a second history."""

    membership = _membership()
    ledgers = {
        member: DurableSeedCommitLedger(tmp_path / f"{member}.log", member, membership)
        for member in membership.member_ids
    }
    first = _proposal(membership)
    conflict = _proposal(membership, result=OTHER)
    first_votes = tuple(ledgers[member].prepare(first) for member in ("A", "B"))
    conflict_votes = [ledgers["C"].prepare(conflict)]
    for member in ("A", "B"):
        with pytest.raises(SeedCommitLedgerError, match="already prepared"):
            ledgers[member].prepare(conflict)
    short_certificate = SeedCommitCertificate(membership.digest, conflict.digest, tuple(conflict_votes))
    with pytest.raises(SeedCommitLedgerError, match="quorum"):
        ledgers["C"].commit(conflict, short_certificate)
    first_certificate = SeedCommitCertificate(membership.digest, first.digest, first_votes)
    assert ledgers["A"].commit(first, first_certificate).state_digest == NEXT


def test_next_slot_requires_predecessor_commit_and_exact_state_digest(tmp_path) -> None:
    """Mathematics: slot `k+1` is admissible iff slot `k` is committed and its result equals the next edge's predecessor."""

    membership = _membership()
    ledger = DurableSeedCommitLedger(tmp_path / "A.log", "A", membership)
    first = _proposal(membership)
    with pytest.raises(SeedCommitLedgerError, match="predecessor"):
        ledger.prepare(_proposal(membership, slot=2, previous=NEXT))
    vote = ledger.prepare(first)
    peer = DurableSeedCommitLedger(tmp_path / "B.log", "B", membership)
    peer_vote = peer.prepare(first)
    certificate = SeedCommitCertificate(membership.digest, first.digest, (vote, peer_vote))
    ledger.commit(first, certificate)

    with pytest.raises(SeedCommitLedgerError, match="predecessor"):
        ledger.prepare(_proposal(membership, slot=2, previous=OTHER))
    second = _proposal(membership, slot=2, previous=NEXT, result=OTHER, request="b" * 64)
    assert ledger.prepare(second).proposal_digest == second.digest


def test_commit_certificate_rejects_duplicate_or_foreign_voters(tmp_path) -> None:
    """Mathematics: certificate voter projection is a subset of unique configured members and must satisfy `|V|≥q`."""

    membership = _membership()
    proposal = _proposal(membership)
    ledger = DurableSeedCommitLedger(tmp_path / "A.log", "A", membership)
    first = ledger.prepare(proposal)
    duplicate = SeedCommitCertificate(membership.digest, proposal.digest, (first, first))
    with pytest.raises(SeedCommitLedgerError, match="unique"):
        ledger.commit(proposal, duplicate)
    with pytest.raises(SeedCommitLedgerError, match="quorum"):
        ledger.commit(proposal, SeedCommitCertificate(membership.digest, proposal.digest, (first,)))

    peer_b = DurableSeedCommitLedger(tmp_path / "B.log", "B", membership)
    peer_c = DurableSeedCommitLedger(tmp_path / "C.log", "C", membership)
    vote_b = peer_b.prepare(proposal)
    vote_c = peer_c.prepare(proposal)
    without_owner = SeedCommitCertificate(membership.digest, proposal.digest, (vote_b, vote_c))
    with pytest.raises(SeedCommitLedgerError, match="configured quorum"):
        ledger.commit(proposal, without_owner)
    foreign = type(vote_b)("outsider", membership.digest, proposal.digest, "f" * 64)
    with pytest.raises(SeedCommitLedgerError, match="foreign"):
        ledger.commit(proposal, SeedCommitCertificate(membership.digest, proposal.digest, (first, foreign)))


def test_prepare_vote_survives_real_process_exit_after_fsync(tmp_path) -> None:
    """Mathematics: an `os._exit` after durable prepare preserves the exact vote and prevents a second slot value."""

    journal = tmp_path / "child.log"
    child = r'''
import os, sys
from mailcpu import DurableSeedCommitLedger, SeedCommitMembership, SeedCommitProposal
zero = "0" * 64
membership = SeedCommitMembership("system-A", 1, ("A", "B", "C"), "A", 1, zero)
proposal = SeedCommitProposal(membership.digest, "system-A", 1, "A", 1, 1, zero, "a" * 64, "1" * 64)
ledger = DurableSeedCommitLedger(sys.argv[1], "A", membership)
ledger.prepare(proposal)
os._exit(0)
'''
    completed = subprocess.run([sys.executable, "-c", child, str(journal)], check=False, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    membership = _membership()
    ledger = DurableSeedCommitLedger(journal, "A", membership)
    assert ledger.prepare(_proposal(membership)).proposal_digest == _proposal(membership).digest
    assert ledger.snapshot()["sequence"] == 1


def test_transition_artifact_survives_real_process_exit_after_prepare_fsync(tmp_path) -> None:
    """Mathematics: abrupt exit after `fsync(PREPARE(p,A))` preserves both vote identity and exact recovery artifact `A`."""

    journal = tmp_path / "artifact-child.log"
    child = r'''
import os, sys
from mailcpu import (
    DurableSeedCommitLedger, SeedCommitMembership, SeedCommitProposal,
    SeedCommitTransitionArtifact,
)
zero = "0" * 64
membership = SeedCommitMembership("system-A", 1, ("A", "B", "C"), "A", 1, zero)
artifact = SeedCommitTransitionArtifact({"result": "stable"}, {"host": [1, 2, 3]})
proposal = SeedCommitProposal(
    membership.digest, "system-A", 1, "A", 1, 1, zero, "a" * 64,
    "1" * 64, artifact.digest,
)
ledger = DurableSeedCommitLedger(sys.argv[1], "A", membership)
ledger.prepare(proposal, artifact)
os._exit(0)
'''
    completed = subprocess.run([sys.executable, "-c", child, str(journal)], check=False, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    membership = _membership()
    ledger = DurableSeedCommitLedger(journal, "A", membership)
    recovered_proposal = ledger.proposal_at(1)
    assert recovered_proposal is not None
    artifact = ledger.transition_artifact(recovered_proposal)
    assert artifact is not None
    assert artifact.digest == recovered_proposal.transition_artifact_digest
    assert ledger.prepared_vote(recovered_proposal) is not None
    assert ledger.verify()


def test_observed_peer_vote_survives_real_process_exit_after_fsync(tmp_path) -> None:
    """Mathematics: owner crash after `fsync(OBSERVE(v_B))` preserves the peer receipt before its reliable response ACK."""

    journal = tmp_path / "observed-child.log"
    child = r'''
import os, sys
from mailcpu import DurableSeedCommitLedger, SeedCommitMembership, SeedCommitProposal, SeedPrepareVote
zero = "0" * 64
membership = SeedCommitMembership("system-A", 1, ("A", "B", "C"), "A", 1, zero)
proposal = SeedCommitProposal(membership.digest, "system-A", 1, "A", 1, 1, zero, "a" * 64, "1" * 64)
ledger = DurableSeedCommitLedger(sys.argv[1], "A", membership)
ledger.prepare(proposal)
vote = SeedPrepareVote("B", membership.digest, proposal.digest, "b" * 64)
ledger.observe_vote(proposal, vote)
os._exit(0)
'''
    completed = subprocess.run([sys.executable, "-c", child, str(journal)], check=False, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    membership = _membership()
    ledger = DurableSeedCommitLedger(journal, "A", membership)
    proposal = _proposal(membership)
    assert ledger.observed_votes(proposal) == (
        SeedPrepareVote("B", membership.digest, proposal.digest, "b" * 64),
    )
    assert ledger.verify()


def test_complete_journal_corruption_fails_closed_and_torn_tail_is_repaired(tmp_path) -> None:
    """Mathematics: replay accepts only the maximal complete hash-chain prefix and truncates only a non-newline suffix."""

    membership = _membership()
    path = tmp_path / "journal.log"
    ledger = DurableSeedCommitLedger(path, "A", membership)
    ledger.prepare(_proposal(membership))
    clean = path.read_bytes()

    path.write_bytes(clean + b'{"version":')
    repaired = DurableSeedCommitLedger(path, "A", membership)
    assert repaired.snapshot()["sequence"] == 1
    assert path.read_bytes() == clean

    record = json.loads(clean.splitlines()[0])
    record["proposal"]["request_fingerprint"] = "f" * 64
    path.write_bytes(json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n")
    with pytest.raises(SeedCommitLedgerError, match="receipt"):
        DurableSeedCommitLedger(path, "A", membership)

    record = json.loads(clean.splitlines()[0])
    record["proposal"]["ignored_extension"] = "not-in-the-proposal-algebra"
    unsigned = {key: value for key, value in record.items() if key != "receipt"}
    record["receipt"] = hashlib.sha256(b"\x00" * 32 + json.dumps(
        unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")).hexdigest()
    path.write_bytes(json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8") + b"\n")
    with pytest.raises(SeedCommitLedgerError, match="proposal snapshot fields"):
        DurableSeedCommitLedger(path, "A", membership)


def test_legacy_metadata_only_journal_remains_readable_without_fabricated_artifact(tmp_path) -> None:
    """Mathematics: version-1 durable prefix replays identically, with `A=∅` rather than inventing a transition payload."""

    membership = _membership()
    proposal_payload = _proposal(membership).snapshot()
    proposal_payload.pop("transition_artifact_digest")
    unsigned = {
        "version": 1,
        "sequence": 1,
        "previous": "00" * 32,
        "member_id": "A",
        "membership_digest": membership.digest,
        "kind": "prepare",
        "proposal": proposal_payload,
        "certificate": None,
    }
    canonical = json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    record = dict(unsigned)
    record["receipt"] = hashlib.sha256(bytes(32) + canonical).hexdigest()
    path = tmp_path / "legacy-v1.log"
    path.write_bytes(json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8") + b"\n")

    ledger = DurableSeedCommitLedger(path, "A", membership)
    recovered = ledger.proposal_at(1)
    assert recovered is not None and recovered.transition_artifact_digest is None
    assert ledger.transition_artifact(recovered) is None
    assert ledger.prepared_vote(recovered) is not None
    assert ledger.verify()


def test_artifact_journal_version_two_replays_before_observed_vote_extension(tmp_path) -> None:
    """Mathematics: version-2 prepare records retain their artifact slot when version 3 adds durable vote observations."""

    membership = _membership()
    proposal_payload = _proposal(membership).snapshot()
    unsigned = {
        "version": 2,
        "sequence": 1,
        "previous": "00" * 32,
        "member_id": "A",
        "membership_digest": membership.digest,
        "kind": "prepare",
        "proposal": proposal_payload,
        "certificate": None,
        "artifact": None,
    }
    canonical = json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    record = dict(unsigned)
    record["receipt"] = hashlib.sha256(bytes(32) + canonical).hexdigest()
    path = tmp_path / "legacy-v2.log"
    path.write_bytes(json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8") + b"\n")

    ledger = DurableSeedCommitLedger(path, "A", membership)
    recovered = ledger.proposal_at(1)
    assert recovered is not None and ledger.transition_artifact(recovered) is None
    assert ledger.prepared_vote(recovered) is not None
    assert ledger.verify()
