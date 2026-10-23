"""Fixed-membership seed-commit identities and durable participant decisions."""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterator, Mapping

from ._codec import decode_canonical_value, encode_canonical_value


class SeedCommitLedgerError(RuntimeError):
    """A fixed-membership seed proposal, vote, decision, or durable record is invalid."""


def _label(value: Any, field: str) -> str:
    """Mathematics: restrict protocol labels to `L={x∈String: |x|>0}`."""

    if not isinstance(value, str) or not value or "\x00" in value:
        raise SeedCommitLedgerError(f"{field} must be a non-empty string without NUL")
    return value


def _positive_integer(value: Any, field: str) -> int:
    """Mathematics: restrict coordinates to `N⁺={n∈Z | n>0}`, excluding booleans from Python's integer subtype."""

    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise SeedCommitLedgerError(f"{field} must be a positive integer")
    return value


def _digest(value: Any, field: str) -> str:
    """Mathematics: restrict digests to the lowercase SHA-256 codomain `D={0,…,f}⁶⁴`."""

    if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise SeedCommitLedgerError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    """Mathematics: map a finite JSON record to the unique byte string `C(x)=UTF8(JSON_sort,minsep(x))`."""

    try:
        return json.dumps(dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise SeedCommitLedgerError("record is outside the canonical JSON algebra") from exc


def _require_exact_fields(payload: Any, fields: frozenset[str], record_name: str) -> Mapping[str, Any]:
    """Mathematics: admit a record only when `dom(payload)=fields`, preventing ignored data from entering canonical identities."""

    if not isinstance(payload, Mapping) or set(payload) != fields:
        raise SeedCommitLedgerError(f"{record_name} snapshot fields are malformed")
    return payload


@dataclass(frozen=True)
class SeedCommitMembership:
    """Immutable owner configuration with a strict-intersection quorum."""

    system_id: str
    incarnation: int
    member_ids: tuple[str, ...]
    owner_id: str
    owner_term: int
    genesis_state_digest: str
    quorum: int | None = None

    def __post_init__(self) -> None:
        """Mathematics: normalize `N` and enforce `owner∈N`, `2q>|N|` so `|Q₁∩Q₂|≥2q−|N|>0`, and positive system coordinates."""

        _label(self.system_id, "membership system id")
        _positive_integer(self.incarnation, "membership incarnation")
        _positive_integer(self.owner_term, "membership owner term")
        _digest(self.genesis_state_digest, "membership genesis state digest")
        if not isinstance(self.member_ids, (list, tuple)):
            raise SeedCommitLedgerError("membership member ids must be a finite sequence")
        members = tuple(self.member_ids)
        if not members:
            raise SeedCommitLedgerError("membership requires at least one member")
        for member in members:
            _label(member, "membership member id")
        if len(set(members)) != len(members):
            raise SeedCommitLedgerError("membership member ids must be unique")
        members = tuple(sorted(members))
        object.__setattr__(self, "member_ids", members)
        _label(self.owner_id, "membership owner id")
        if self.owner_id not in members:
            raise SeedCommitLedgerError("membership owner must be a configured member")
        selected = len(members) // 2 + 1 if self.quorum is None else self.quorum
        _positive_integer(selected, "membership quorum")
        if selected > len(members):
            raise SeedCommitLedgerError("membership quorum exceeds member count")
        if 2 * selected <= len(members):
            raise SeedCommitLedgerError("membership quorum must be a strict majority")
        object.__setattr__(self, "quorum", selected)

    def snapshot(self) -> dict[str, object]:
        """Mathematics: project the configuration tuple `M=(S,I,N,O,T,G,q)` into its normalized finite record."""

        return {
            "system_id": self.system_id,
            "incarnation": self.incarnation,
            "member_ids": list(self.member_ids),
            "owner_id": self.owner_id,
            "owner_term": self.owner_term,
            "genesis_state_digest": self.genesis_state_digest,
            "quorum": self.quorum,
        }

    @property
    def digest(self) -> str:
        """Mathematics: identify fixed configuration `M` by `d(M)=SHA256(C(snapshot(M)))`."""

        return hashlib.sha256(_canonical_bytes(self.snapshot())).hexdigest()

    @classmethod
    def from_snapshot(cls, payload: Mapping[str, Any]) -> "SeedCommitMembership":
        """Mathematics: invert the membership projection only when all factors satisfy `M`'s constructor law."""

        payload = _require_exact_fields(
            payload,
            frozenset({"system_id", "incarnation", "member_ids", "owner_id", "owner_term", "genesis_state_digest", "quorum"}),
            "membership",
        )
        if not isinstance(payload.get("member_ids"), (list, tuple)):
            raise SeedCommitLedgerError("membership snapshot is malformed")
        try:
            return cls(
                payload.get("system_id"),
                payload.get("incarnation"),
                tuple(payload["member_ids"]),
                payload.get("owner_id"),
                payload.get("owner_term"),
                payload.get("genesis_state_digest"),
                payload.get("quorum"),
            )
        except (TypeError, ValueError) as exc:
            if isinstance(exc, SeedCommitLedgerError):
                raise
            raise SeedCommitLedgerError("membership snapshot fields are invalid") from exc


@dataclass(frozen=True)
class SeedCommitProposal:
    """One deterministic proposed edge from a predecessor seed state to a result state."""

    membership_digest: str
    system_id: str
    incarnation: int
    owner_id: str
    owner_term: int
    slot: int
    predecessor_state_digest: str
    request_fingerprint: str
    result_state_digest: str
    transition_artifact_digest: str | None = None

    def __post_init__(self) -> None:
        """Mathematics: validate edge identity `p=(M,S,I,O,T,k,d₋,f(q),d₊)` over positive coordinates and SHA-256 digests."""

        _digest(self.membership_digest, "proposal membership digest")
        _label(self.system_id, "proposal system id")
        _positive_integer(self.incarnation, "proposal incarnation")
        _label(self.owner_id, "proposal owner id")
        _positive_integer(self.owner_term, "proposal owner term")
        _positive_integer(self.slot, "proposal slot")
        _digest(self.predecessor_state_digest, "proposal predecessor state digest")
        _digest(self.request_fingerprint, "proposal request fingerprint")
        _digest(self.result_state_digest, "proposal result state digest")
        if self.transition_artifact_digest is not None:
            _digest(self.transition_artifact_digest, "proposal transition artifact digest")

    def snapshot(self) -> dict[str, object]:
        """Mathematics: serialize all factors that determine the slot's single permitted transition."""

        return {
            "membership_digest": self.membership_digest,
            "system_id": self.system_id,
            "incarnation": self.incarnation,
            "owner_id": self.owner_id,
            "owner_term": self.owner_term,
            "slot": self.slot,
            "predecessor_state_digest": self.predecessor_state_digest,
            "request_fingerprint": self.request_fingerprint,
            "result_state_digest": self.result_state_digest,
            "transition_artifact_digest": self.transition_artifact_digest,
        }

    @property
    def digest(self) -> str:
        """Mathematics: calculate proposal identity `d(p)=SHA256(C(snapshot(p)))`."""

        return hashlib.sha256(_canonical_bytes(self.snapshot())).hexdigest()

    @property
    def slot_key(self) -> tuple[str, int, str, int, int]:
        """Mathematics: project conflict coordinate `K(p)=(S,I,M,T,k)`, excluding mutable transition payload."""

        return (self.system_id, self.incarnation, self.membership_digest, self.owner_term, self.slot)

    @classmethod
    def from_snapshot(cls, payload: Mapping[str, Any]) -> "SeedCommitProposal":
        """Mathematics: reconstruct edge `p` only after every serialized coordinate and digest revalidates."""

        old_fields = frozenset({"membership_digest", "system_id", "incarnation", "owner_id", "owner_term", "slot", "predecessor_state_digest", "request_fingerprint", "result_state_digest"})
        new_fields = old_fields | {"transition_artifact_digest"}
        if not isinstance(payload, Mapping) or set(payload) not in (old_fields, new_fields):
            raise SeedCommitLedgerError("proposal snapshot fields are malformed")
        try:
            return cls(
                payload.get("membership_digest"),
                payload.get("system_id"),
                payload.get("incarnation"),
                payload.get("owner_id"),
                payload.get("owner_term"),
                payload.get("slot"),
                payload.get("predecessor_state_digest"),
                payload.get("request_fingerprint"),
                payload.get("result_state_digest"),
                payload.get("transition_artifact_digest"),
            )
        except (TypeError, ValueError) as exc:
            if isinstance(exc, SeedCommitLedgerError):
                raise
            raise SeedCommitLedgerError("proposal snapshot fields are invalid") from exc


@dataclass(frozen=True)
class SeedCommitTransitionArtifact:
    """Replayable result and complete host state bound to one prepared transition."""

    result: Mapping[str, Any]
    operating_system: Mapping[str, Any]

    def __post_init__(self) -> None:
        """Mathematics: require a finite canonical product `A=(result,OS)` so `decode(encode(A))=A`."""

        if not isinstance(self.result, Mapping) or not isinstance(self.operating_system, Mapping):
            raise SeedCommitLedgerError("transition artifact requires result and operating-system mappings")
        try:
            _canonical_bytes(self.snapshot())
        except (TypeError, ValueError) as exc:
            raise SeedCommitLedgerError("transition artifact is outside the canonical value algebra") from exc

    def snapshot(self) -> dict[str, object]:
        """Mathematics: encode the full transition factors injectively, preserving nested tuple identities."""

        return {
            "result": encode_canonical_value(deepcopy(dict(self.result))),
            "operating_system": encode_canonical_value(deepcopy(dict(self.operating_system))),
        }

    @property
    def digest(self) -> str:
        """Mathematics: identify the exact recovery artifact by `SHA256(C(encode(A)))`."""

        return hashlib.sha256(_canonical_bytes(self.snapshot())).hexdigest()

    @classmethod
    def from_snapshot(cls, payload: Mapping[str, Any]) -> "SeedCommitTransitionArtifact":
        """Mathematics: invert artifact encoding only for exact two-factor records and canonical values."""

        payload = _require_exact_fields(payload, frozenset({"result", "operating_system"}), "transition artifact")
        try:
            result = decode_canonical_value(payload["result"])
            operating_system = decode_canonical_value(payload["operating_system"])
        except (KeyError, TypeError, ValueError) as exc:
            raise SeedCommitLedgerError("transition artifact encoding is invalid") from exc
        if not isinstance(result, Mapping) or not isinstance(operating_system, Mapping):
            raise SeedCommitLedgerError("transition artifact decoded factors must be mappings")
        return cls(deepcopy(dict(result)), deepcopy(dict(operating_system)))


@dataclass(frozen=True)
class SeedPrepareVote:
    """Durable participant evidence for one proposal identity."""

    member_id: str
    membership_digest: str
    proposal_digest: str
    journal_receipt: str

    def __post_init__(self) -> None:
        """Mathematics: bind vote `v=(member,M,d(p),h_i)` to non-empty member identity and three SHA-256 digests."""

        _label(self.member_id, "prepare vote member id")
        _digest(self.membership_digest, "prepare vote membership digest")
        _digest(self.proposal_digest, "prepare vote proposal digest")
        _digest(self.journal_receipt, "prepare vote journal receipt")

    def snapshot(self) -> dict[str, object]:
        """Mathematics: project durable vote coordinates without changing its chain receipt."""

        return {
            "member_id": self.member_id,
            "membership_digest": self.membership_digest,
            "proposal_digest": self.proposal_digest,
            "journal_receipt": self.journal_receipt,
        }

    @classmethod
    def from_snapshot(cls, payload: Mapping[str, Any]) -> "SeedPrepareVote":
        """Mathematics: invert `snapshot(v)` through the vote's validated identity domain."""

        payload = _require_exact_fields(
            payload,
            frozenset({"member_id", "membership_digest", "proposal_digest", "journal_receipt"}),
            "prepare vote",
        )
        try:
            return cls(
                payload.get("member_id"),
                payload.get("membership_digest"),
                payload.get("proposal_digest"),
                payload.get("journal_receipt"),
            )
        except (TypeError, ValueError) as exc:
            if isinstance(exc, SeedCommitLedgerError):
                raise
            raise SeedCommitLedgerError("prepare vote snapshot fields are invalid") from exc


@dataclass(frozen=True)
class SeedCommitCertificate:
    """A fixed-membership majority set of durable votes for one proposal."""

    membership_digest: str
    proposal_digest: str
    votes: tuple[SeedPrepareVote, ...]

    def __post_init__(self) -> None:
        """Mathematics: bind certificate votes to one membership and proposal; quorum cardinality is checked at verification."""

        _digest(self.membership_digest, "certificate membership digest")
        _digest(self.proposal_digest, "certificate proposal digest")
        if not isinstance(self.votes, (list, tuple)):
            raise SeedCommitLedgerError("certificate votes must be a finite sequence")
        votes = tuple(self.votes)
        if any(not isinstance(vote, SeedPrepareVote) for vote in votes):
            raise SeedCommitLedgerError("certificate votes must be typed durable votes")
        object.__setattr__(self, "votes", votes)

    def snapshot(self) -> dict[str, object]:
        """Mathematics: serialize the vote multiset while leaving uniqueness and majority validation explicit."""

        return {
            "membership_digest": self.membership_digest,
            "proposal_digest": self.proposal_digest,
            "votes": [vote.snapshot() for vote in self.votes],
        }

    @classmethod
    def from_snapshot(cls, payload: Mapping[str, Any]) -> "SeedCommitCertificate":
        """Mathematics: reconstruct certificate `C` from a finite sequence of validated vote projections."""

        payload = _require_exact_fields(payload, frozenset({"membership_digest", "proposal_digest", "votes"}), "commit certificate")
        if not isinstance(payload.get("votes"), (list, tuple)):
            raise SeedCommitLedgerError("commit certificate snapshot is malformed")
        return cls(
            payload.get("membership_digest"),
            payload.get("proposal_digest"),
            tuple(SeedPrepareVote.from_snapshot(vote) for vote in payload["votes"]),
        )


@dataclass(frozen=True)
class SeedCommitDecision:
    """One locally durable commit decision and its verified quorum membership."""

    member_id: str
    proposal_digest: str
    slot: int
    state_digest: str
    certificate_members: tuple[str, ...]
    journal_receipt: str

    def __post_init__(self) -> None:
        """Mathematics: validate decision projection `D=(member,d(p),k,d₊,V,h_i)` and normalize voter set `V`."""

        _label(self.member_id, "decision member id")
        _digest(self.proposal_digest, "decision proposal digest")
        _positive_integer(self.slot, "decision slot")
        _digest(self.state_digest, "decision state digest")
        _digest(self.journal_receipt, "decision journal receipt")
        if not isinstance(self.certificate_members, (list, tuple)):
            raise SeedCommitLedgerError("decision certificate members must be a finite sequence")
        members = tuple(self.certificate_members)
        if any(not isinstance(member, str) or not member for member in members):
            raise SeedCommitLedgerError("decision certificate member ids are invalid")
        if len(set(members)) != len(members):
            raise SeedCommitLedgerError("decision certificate members must be unique")
        object.__setattr__(self, "certificate_members", tuple(sorted(members)))

    def snapshot(self) -> dict[str, object]:
        """Mathematics: expose immutable commit outcome `D` without the full replicated seed payload."""

        return {
            "member_id": self.member_id,
            "proposal_digest": self.proposal_digest,
            "slot": self.slot,
            "state_digest": self.state_digest,
            "certificate_members": list(self.certificate_members),
            "journal_receipt": self.journal_receipt,
        }

    @classmethod
    def from_snapshot(cls, payload: Mapping[str, Any]) -> "SeedCommitDecision":
        """Mathematics: reconstruct decision `D` only when its member set and all receipt coordinates validate."""

        payload = _require_exact_fields(
            payload,
            frozenset({"member_id", "proposal_digest", "slot", "state_digest", "certificate_members", "journal_receipt"}),
            "commit decision",
        )
        if not isinstance(payload.get("certificate_members"), (list, tuple)):
            raise SeedCommitLedgerError("commit decision snapshot members are malformed")
        try:
            return cls(
                payload.get("member_id"),
                payload.get("proposal_digest"),
                payload.get("slot"),
                payload.get("state_digest"),
                tuple(payload["certificate_members"]),
                payload.get("journal_receipt"),
            )
        except (TypeError, ValueError) as exc:
            if isinstance(exc, SeedCommitLedgerError):
                raise
            raise SeedCommitLedgerError("commit decision fields are invalid") from exc


class DurableSeedCommitLedger:
    """Hash-chained participant journal for fixed-membership prepare votes and commit decisions."""

    _VERSION = 4
    _GENESIS = b"\x00" * 32

    def __init__(self, path: str | Path, member_id: str, membership: SeedCommitMembership) -> None:
        """Mathematics: initialize participant state by replaying `L₀=∅; Lᵢ₊₁=apply(Lᵢ,Rᵢ)` under fixed membership `M`."""

        if not isinstance(membership, SeedCommitMembership):
            raise SeedCommitLedgerError("participant requires a typed fixed membership")
        self.member_id = _label(member_id, "participant member id")
        if self.member_id not in membership.member_ids:
            raise SeedCommitLedgerError("participant is not a configured membership member")
        self.membership = membership
        self.path = Path(path)
        self._lock_path = self.path.with_name(f"{self.path.name}.lock")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)
        self._prepared: dict[tuple[str, int, str, int, int], tuple[SeedCommitProposal, SeedPrepareVote]] = {}
        self._prepared_artifacts: dict[tuple[str, int, str, int, int], SeedCommitTransitionArtifact] = {}
        self._observed_votes: dict[tuple[str, int, str, int, int], dict[str, SeedPrepareVote]] = {}
        self._committed: dict[tuple[str, int, str, int, int], SeedCommitDecision] = {}
        self._certificates: dict[tuple[str, int, str, int, int], SeedCommitCertificate] = {}
        self._observed_decisions: dict[tuple[str, int, str, int, int], dict[str, SeedCommitDecision]] = {}
        self._sequence = 0
        self._head = self._GENESIS
        self._file_signature: tuple[int, int] | None = None
        with self._locked():
            self._replay(repair_torn_suffix=True)

    def prepare(
        self,
        proposal: SeedCommitProposal,
        artifact: SeedCommitTransitionArtifact | None = None,
    ) -> SeedPrepareVote:
        """Mathematics: fsync `A` before voting for `p`; retries preserve `d(A)` and unequal slot identities conflict."""

        self._validate_proposal(proposal)
        self._validate_transition_artifact(proposal, artifact)
        with self._locked():
            self._refresh_if_changed()
            existing = self._prepared.get(proposal.slot_key)
            if existing is not None:
                previous, vote = existing
                previous_artifact = self._prepared_artifacts.get(proposal.slot_key)
                if previous.digest != proposal.digest or (
                    None if previous_artifact is None else previous_artifact.digest
                ) != (None if artifact is None else artifact.digest):
                    raise SeedCommitLedgerError("slot already prepared a different proposal")
                return vote
            self._validate_next_slot(proposal)
            receipt = self._append_locked("prepare", proposal, None, artifact, None, None)
            vote = SeedPrepareVote(self.member_id, self.membership.digest, proposal.digest, receipt)
            self._prepared[proposal.slot_key] = (proposal, vote)
            if artifact is not None:
                self._prepared_artifacts[proposal.slot_key] = SeedCommitTransitionArtifact.from_snapshot(artifact.snapshot())
            return vote

    def commit(self, proposal: SeedCommitProposal, certificate: SeedCommitCertificate) -> SeedCommitDecision:
        """Mathematics: append `COMMIT(p)` only if local durable prepare exists and certificate has `q` unique matching voters."""

        self._validate_proposal(proposal)
        self._validate_certificate(proposal, certificate)
        with self._locked():
            self._refresh_if_changed()
            prepared = self._prepared.get(proposal.slot_key)
            if prepared is None or prepared[0].digest != proposal.digest:
                raise SeedCommitLedgerError("participant has not prepared this proposal")
            previous_decision = self._committed.get(proposal.slot_key)
            if previous_decision is not None:
                return previous_decision
            self._validate_next_slot(proposal)
            receipt = self._append_locked("commit", proposal, certificate, None, None, None)
            decision = SeedCommitDecision(
                self.member_id,
                proposal.digest,
                proposal.slot,
                proposal.result_state_digest,
                tuple(vote.member_id for vote in certificate.votes),
                receipt,
            )
            self._committed[proposal.slot_key] = decision
            self._certificates[proposal.slot_key] = certificate
            return decision

    def observe_vote(self, proposal: SeedCommitProposal, vote: SeedPrepareVote) -> bool:
        """Mathematics: fsync each configured remote `v_i` before its channel ACK; identical observations are idempotent."""

        self._validate_proposal(proposal)
        if not isinstance(vote, SeedPrepareVote):
            raise SeedCommitLedgerError("observed prepare evidence must be a typed vote")
        if (
            vote.member_id not in self.membership.member_ids
            or vote.member_id == self.member_id
            or vote.membership_digest != self.membership.digest
            or vote.proposal_digest != proposal.digest
        ):
            raise SeedCommitLedgerError("observed vote does not match a remote configured proposal member")
        with self._locked():
            self._refresh_if_changed()
            prepared = self._prepared.get(proposal.slot_key)
            if prepared is None or prepared[0].digest != proposal.digest:
                raise SeedCommitLedgerError("cannot observe a peer vote before matching local prepare")
            certificate = self._certificates.get(proposal.slot_key)
            if certificate is not None:
                certified = {item.member_id: item for item in certificate.votes}
                if vote.member_id in certified and certified[vote.member_id] != vote:
                    raise SeedCommitLedgerError("late observed vote conflicts with committed certificate")
            votes = self._observed_votes.setdefault(proposal.slot_key, {})
            previous = votes.get(vote.member_id)
            if previous is not None:
                if previous != vote:
                    raise SeedCommitLedgerError("peer returned conflicting durable votes")
                return False
            self._append_locked("observe", proposal, None, None, vote, None)
            votes[vote.member_id] = vote
            return True

    def observed_votes(self, proposal: SeedCommitProposal) -> tuple[SeedPrepareVote, ...]:
        """Mathematics: recover the sorted durable observation set `V_obs[K(p)]` only for the exact proposal digest."""

        self._validate_proposal(proposal)
        with self._locked():
            self._refresh_if_changed()
            prepared = self._prepared.get(proposal.slot_key)
            if prepared is not None and prepared[0].digest != proposal.digest:
                raise SeedCommitLedgerError("slot is prepared for a conflicting proposal")
            votes = self._observed_votes.get(proposal.slot_key, {})
            return tuple(votes[member] for member in sorted(votes))

    def observe_decision(self, proposal: SeedCommitProposal, decision: SeedCommitDecision) -> bool:
        """Mathematics: fsync each peer's matching durable decision before ACK; identical observations are idempotent."""

        self._validate_proposal(proposal)
        if not isinstance(decision, SeedCommitDecision):
            raise SeedCommitLedgerError("observed commit evidence must be a typed decision")
        if (
            decision.member_id not in self.membership.member_ids
            or decision.member_id == self.member_id
            or decision.proposal_digest != proposal.digest
            or decision.slot != proposal.slot
            or decision.state_digest != proposal.result_state_digest
        ):
            raise SeedCommitLedgerError("observed decision does not match a remote configured proposal member")
        with self._locked():
            self._refresh_if_changed()
            local = self._committed.get(proposal.slot_key)
            certificate = self._certificates.get(proposal.slot_key)
            if local is None or local.proposal_digest != proposal.digest or certificate is None:
                raise SeedCommitLedgerError("cannot observe a peer decision before local commit")
            expected_voters = tuple(sorted(vote.member_id for vote in certificate.votes))
            if decision.certificate_members != expected_voters:
                raise SeedCommitLedgerError("observed decision certificate members conflict with owner decision")
            decisions = self._observed_decisions.setdefault(proposal.slot_key, {})
            previous = decisions.get(decision.member_id)
            if previous is not None:
                if previous != decision:
                    raise SeedCommitLedgerError("peer returned conflicting durable commit decisions")
                return False
            self._append_locked("observe-decision", proposal, None, None, None, decision)
            decisions[decision.member_id] = decision
            return True

    def observed_decisions(self, proposal: SeedCommitProposal) -> tuple[SeedCommitDecision, ...]:
        """Mathematics: recover the sorted durable peer decision set `D_obs[K(p)]` only for the exact proposal digest."""

        self._validate_proposal(proposal)
        with self._locked():
            self._refresh_if_changed()
            prepared = self._prepared.get(proposal.slot_key)
            if prepared is not None and prepared[0].digest != proposal.digest:
                raise SeedCommitLedgerError("slot is prepared for a conflicting proposal")
            decisions = self._observed_decisions.get(proposal.slot_key, {})
            return tuple(decisions[member] for member in sorted(decisions))

    def transition_artifact(self, proposal: SeedCommitProposal) -> SeedCommitTransitionArtifact | None:
        """Mathematics: recover the fsynced prepare payload `A[K(p)]` only for the exact prepared proposal digest."""

        self._validate_proposal(proposal)
        with self._locked():
            self._refresh_if_changed()
            prepared = self._prepared.get(proposal.slot_key)
            if prepared is None:
                return None
            if prepared[0].digest != proposal.digest:
                raise SeedCommitLedgerError("slot is prepared for a conflicting proposal")
            artifact = self._prepared_artifacts.get(proposal.slot_key)
            return None if artifact is None else SeedCommitTransitionArtifact.from_snapshot(artifact.snapshot())

    def proposal_at(self, slot: int) -> SeedCommitProposal | None:
        """Mathematics: project the unique prepared edge `p_k` at slot `k`, or `∅` if no durable prepare exists."""

        _positive_integer(slot, "proposal lookup slot")
        with self._locked():
            self._refresh_if_changed()
            matches = [proposal for proposal, _vote in self._prepared.values() if proposal.slot == slot]
            if len(matches) > 1:
                raise SeedCommitLedgerError("journal contains multiple proposals for one slot")
            return None if not matches else matches[0]

    def proposal_for_request_identity(
        self,
        identity: tuple[str, str, int],
    ) -> tuple[SeedCommitProposal, SeedCommitTransitionArtifact | None] | None:
        """Mathematics: invert the durable artifact identity map `I(result)↦(p,A)` and reject non-unique preimages."""

        if (
            not isinstance(identity, tuple)
            or len(identity) != 3
            or any(not isinstance(item, str) or not item for item in identity[:2])
            or not isinstance(identity[2], int)
            or isinstance(identity[2], bool)
            or identity[2] <= 0
        ):
            raise SeedCommitLedgerError("request identity lookup is invalid")
        with self._locked():
            self._refresh_if_changed()
            matches: list[tuple[SeedCommitProposal, SeedCommitTransitionArtifact | None]] = []
            for slot_key, (proposal, _vote) in self._prepared.items():
                artifact = self._prepared_artifacts.get(slot_key)
                if artifact is None:
                    continue
                result = artifact.result
                result_identity = (
                    result.get("request_source"),
                    result.get("request_channel"),
                    result.get("request_sequence"),
                )
                if result_identity == identity:
                    matches.append((proposal, SeedCommitTransitionArtifact.from_snapshot(artifact.snapshot())))
            if len(matches) > 1:
                raise SeedCommitLedgerError("request identity maps to multiple prepared transitions")
            return None if not matches else matches[0]

    def committed_proposal_for_fingerprint(
        self,
        request_fingerprint: str,
    ) -> tuple[SeedCommitProposal, SeedCommitTransitionArtifact] | None:
        """Mathematics: project the unique committed transition `p` with `f(request)=h`, preserving its exact artifact."""

        _digest(request_fingerprint, "request fingerprint lookup")
        with self._locked():
            self._refresh_if_changed()
            matches: list[tuple[SeedCommitProposal, SeedCommitTransitionArtifact]] = []
            for slot_key, (proposal, _vote) in self._prepared.items():
                artifact = self._prepared_artifacts.get(slot_key)
                if (
                    artifact is None
                    or slot_key not in self._committed
                    or proposal.request_fingerprint != request_fingerprint
                    or artifact.result.get("request_fingerprint") != request_fingerprint
                ):
                    continue
                matches.append((proposal, SeedCommitTransitionArtifact.from_snapshot(artifact.snapshot())))
            if len(matches) > 1:
                raise SeedCommitLedgerError("request fingerprint maps to multiple committed transitions")
            return None if not matches else matches[0]

    def certificate(self, proposal: SeedCommitProposal) -> SeedCommitCertificate | None:
        """Mathematics: recover the exact durable certificate `C[K(p)]` that justified a local commit decision."""

        self._validate_proposal(proposal)
        with self._locked():
            self._refresh_if_changed()
            prepared = self._prepared.get(proposal.slot_key)
            if prepared is not None and prepared[0].digest != proposal.digest:
                raise SeedCommitLedgerError("slot is committed or prepared for a conflicting proposal")
            certificate = self._certificates.get(proposal.slot_key)
            return None if certificate is None else SeedCommitCertificate.from_snapshot(certificate.snapshot())

    def prepared_vote(self, proposal: SeedCommitProposal) -> SeedPrepareVote | None:
        """Mathematics: project the durable vote `V[K(p)]` iff its proposal digest equals `d(p)`."""

        self._validate_proposal(proposal)
        with self._locked():
            self._refresh_if_changed()
            prepared = self._prepared.get(proposal.slot_key)
            if prepared is None:
                return None
            if prepared[0].digest != proposal.digest:
                raise SeedCommitLedgerError("slot is prepared for a conflicting proposal")
            return prepared[1]

    def decision(self, proposal: SeedCommitProposal) -> SeedCommitDecision | None:
        """Mathematics: project committed decision `D[K(p)]` only when its identity is the requested `d(p)`."""

        self._validate_proposal(proposal)
        with self._locked():
            self._refresh_if_changed()
            prepared = self._prepared.get(proposal.slot_key)
            if prepared is not None and prepared[0].digest != proposal.digest:
                raise SeedCommitLedgerError("slot is committed or prepared for a conflicting proposal")
            return self._committed.get(proposal.slot_key)

    def committed_state(self) -> tuple[int, str] | None:
        """Mathematics: return maximal committed coordinate `(k,d₊)` or `∅` over this membership's ordered slot chain."""

        with self._locked():
            self._refresh_if_changed()
            if not self._committed:
                return None
            latest = max(self._committed, key=lambda key: key[-1])
            decision = self._committed[latest]
            return decision.slot, decision.state_digest

    def snapshot(self) -> dict[str, object]:
        """Mathematics: expose journal cursor `(member,M,n,H)` and participant ledger cardinalities without mutation."""

        with self._locked():
            self._refresh_if_changed()
            state = None
            if self._committed:
                latest_key = max(self._committed, key=lambda key: key[-1])
                latest = self._committed[latest_key]
                state = (latest.slot, latest.state_digest)
            return {
                "version": self._VERSION,
                "member_id": self.member_id,
                "membership_digest": self.membership.digest,
                "sequence": self._sequence,
                "head_hex": self._head.hex(),
                "prepared": len(self._prepared),
                "observed_votes": sum(len(votes) for votes in self._observed_votes.values()),
                "observed_decisions": sum(len(items) for items in self._observed_decisions.values()),
                "committed": len(self._committed),
                "committed_state": None if state is None else {"slot": state[0], "state_digest": state[1]},
            }

    def verify(self) -> bool:
        """Mathematics: independently replay the full chain and require candidate participant state `L'=L`."""

        try:
            candidate = type(self).__new__(type(self))
            candidate.member_id = self.member_id
            candidate.membership = self.membership
            candidate.path = self.path
            candidate._lock_path = self._lock_path
            candidate._prepared = {}
            candidate._prepared_artifacts = {}
            candidate._observed_votes = {}
            candidate._committed = {}
            candidate._certificates = {}
            candidate._observed_decisions = {}
            candidate._sequence = 0
            candidate._head = self._GENESIS
            candidate._file_signature = None
            with candidate._locked():
                candidate._replay(repair_torn_suffix=False)
        except (OSError, SeedCommitLedgerError, ValueError):
            return False
        return (
            candidate._prepared == self._prepared
            and candidate._prepared_artifacts == self._prepared_artifacts
            and candidate._observed_votes == self._observed_votes
            and candidate._committed == self._committed
            and candidate._certificates == self._certificates
            and candidate._observed_decisions == self._observed_decisions
            and candidate._sequence == self._sequence
            and candidate._head == self._head
        )

    def _validate_proposal(self, proposal: SeedCommitProposal) -> None:
        """Mathematics: require `p` to name this exact `(system,incarnation,membership,owner,term)` configuration."""

        if not isinstance(proposal, SeedCommitProposal):
            raise SeedCommitLedgerError("operation requires a typed seed commit proposal")
        if (
            proposal.membership_digest != self.membership.digest
            or proposal.system_id != self.membership.system_id
            or proposal.incarnation != self.membership.incarnation
            or proposal.owner_id != self.membership.owner_id
            or proposal.owner_term != self.membership.owner_term
        ):
            raise SeedCommitLedgerError("proposal does not match fixed membership identity")

    def _validate_transition_artifact(
        self,
        proposal: SeedCommitProposal,
        artifact: SeedCommitTransitionArtifact | None,
    ) -> None:
        """Mathematics: enforce `artifact is None ⇔ p.digest_artifact is None`; otherwise `SHA256(C(A))=p.digest_artifact`."""

        if artifact is not None and not isinstance(artifact, SeedCommitTransitionArtifact):
            raise SeedCommitLedgerError("prepare artifact must be a typed transition artifact")
        if proposal.transition_artifact_digest is None:
            if artifact is not None:
                raise SeedCommitLedgerError("proposal does not bind a transition artifact")
            return
        if artifact is None or artifact.digest != proposal.transition_artifact_digest:
            raise SeedCommitLedgerError("transition artifact digest does not match proposal")

    def _validate_certificate(self, proposal: SeedCommitProposal, certificate: SeedCommitCertificate) -> None:
        """Mathematics: accept `C` iff `V⊆N`, `|V|≥q`, owner `∈V`, identities match, and voters are unique; strict majority gives `|Q₁∩Q₂|≥2q−|N|>0`."""

        if not isinstance(certificate, SeedCommitCertificate):
            raise SeedCommitLedgerError("commit requires a typed prepare certificate")
        if certificate.membership_digest != self.membership.digest or certificate.proposal_digest != proposal.digest:
            raise SeedCommitLedgerError("commit certificate identity does not match proposal")
        member_ids = tuple(vote.member_id for vote in certificate.votes)
        if len(member_ids) != len(set(member_ids)):
            raise SeedCommitLedgerError("commit certificate voters must be unique")
        if any(
            vote.membership_digest != self.membership.digest or vote.proposal_digest != proposal.digest
            for vote in certificate.votes
        ):
            raise SeedCommitLedgerError("commit certificate contains a mismatched vote")
        if any(member_id not in self.membership.member_ids for member_id in member_ids):
            raise SeedCommitLedgerError("commit certificate contains a foreign voter")
        if len(member_ids) < self.membership.quorum or self.membership.owner_id not in member_ids:
            raise SeedCommitLedgerError("commit certificate does not establish configured quorum")

    def _validate_next_slot(self, proposal: SeedCommitProposal) -> None:
        """Mathematics: require `k=1,d₋=G` initially or `k=k_max+1,d₋=d₊(k_max)` after the committed prefix."""

        if self._committed:
            latest_key = max(self._committed, key=lambda key: key[-1])
            latest = self._prepared[latest_key][0]
            expected_slot = latest.slot + 1
            expected_digest = latest.result_state_digest
        else:
            expected_slot = 1
            expected_digest = self.membership.genesis_state_digest
        if proposal.slot != expected_slot or proposal.predecessor_state_digest != expected_digest:
            raise SeedCommitLedgerError("proposal predecessor or slot does not extend committed state")

    def _append_locked(
        self,
        kind: str,
        proposal: SeedCommitProposal,
        certificate: SeedCommitCertificate | None,
        artifact: SeedCommitTransitionArtifact | None,
        observed_vote: SeedPrepareVote | None,
        observed_decision: SeedCommitDecision | None,
    ) -> str:
        """Mathematics: fsync `Rᵢ=(kind,p,C,A,v,D)` with `hᵢ=SHA256(hᵢ₋₁∥JSON_canonical(Rᵢ))` before returning evidence."""

        unsigned: dict[str, Any] = {
            "version": self._VERSION,
            "sequence": self._sequence + 1,
            "previous": self._head.hex(),
            "member_id": self.member_id,
            "membership_digest": self.membership.digest,
            "kind": kind,
            "proposal": proposal.snapshot(),
            "certificate": None if certificate is None else certificate.snapshot(),
            "artifact": None if artifact is None else artifact.snapshot(),
            "observed_vote": None if observed_vote is None else observed_vote.snapshot(),
            "observed_decision": None if observed_decision is None else observed_decision.snapshot(),
        }
        receipt = hashlib.sha256(self._head + _canonical_bytes(unsigned)).hexdigest()
        record = dict(unsigned)
        record["receipt"] = receipt
        line = _canonical_bytes(record) + b"\n"
        with self.path.open("ab") as stream:
            written = stream.write(line)
            if written != len(line):
                raise OSError("seed commit journal append was incomplete")
            stream.flush()
            os.fsync(stream.fileno())
        self._sequence = unsigned["sequence"]
        self._head = bytes.fromhex(receipt)
        stat = self.path.stat()
        self._file_signature = (stat.st_size, stat.st_mtime_ns)
        return receipt

    def _refresh_if_changed(self) -> None:
        """Mathematics: replay the durable suffix exactly when `(file_size,mtime_ns)` differs from the cached cursor."""

        stat = self.path.stat()
        signature = (stat.st_size, stat.st_mtime_ns)
        if signature != self._file_signature:
            self._replay(repair_torn_suffix=True)

    def _replay(self, *, repair_torn_suffix: bool) -> None:
        """Mathematics: reconstruct `P,C,n,H` by strict chain fold and optionally truncate only an incomplete final line."""

        raw_data = self.path.read_bytes()
        if raw_data and not raw_data.endswith(b"\n"):
            complete_length = raw_data.rfind(b"\n") + 1
            if not repair_torn_suffix:
                raise SeedCommitLedgerError("journal append is incomplete after write")
            with self.path.open("r+b") as stream:
                stream.truncate(complete_length)
                stream.flush()
                os.fsync(stream.fileno())
            raw_data = raw_data[:complete_length]

        prepared: dict[tuple[str, int, str, int, int], tuple[SeedCommitProposal, SeedPrepareVote]] = {}
        prepared_artifacts: dict[tuple[str, int, str, int, int], SeedCommitTransitionArtifact] = {}
        observed_votes: dict[tuple[str, int, str, int, int], dict[str, SeedPrepareVote]] = {}
        committed: dict[tuple[str, int, str, int, int], SeedCommitDecision] = {}
        certificates: dict[tuple[str, int, str, int, int], SeedCommitCertificate] = {}
        observed_decisions: dict[tuple[str, int, str, int, int], dict[str, SeedCommitDecision]] = {}
        sequence = 0
        head = self._GENESIS
        legacy_keys = {"version", "sequence", "previous", "member_id", "membership_digest", "kind", "proposal", "certificate", "receipt"}
        version_two_keys = legacy_keys | {"artifact"}
        version_three_keys = version_two_keys | {"observed_vote"}
        current_keys = version_three_keys | {"observed_decision"}
        for line in raw_data.splitlines():
            try:
                record = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise SeedCommitLedgerError("journal contains invalid complete JSON") from exc
            if not isinstance(record, Mapping) or _canonical_bytes(record) + b"\n" != line + b"\n":
                raise SeedCommitLedgerError("journal record is malformed or not canonical")
            version = record.get("version")
            record_sequence = record.get("sequence")
            required_keys = (
                legacy_keys
                if version == 1
                else version_two_keys
                if version == 2
                else version_three_keys
                if version == 3
                else current_keys
            )
            if set(record) != required_keys:
                raise SeedCommitLedgerError("journal record fields are malformed")
            if (
                not isinstance(version, int)
                or isinstance(version, bool)
                or version not in (1, 2, 3, self._VERSION)
                or not isinstance(record_sequence, int)
                or isinstance(record_sequence, bool)
                or record_sequence != sequence + 1
            ):
                raise SeedCommitLedgerError("journal version or sequence is invalid")
            previous_text = record.get("previous")
            if not isinstance(previous_text, str) or previous_text != head.hex():
                raise SeedCommitLedgerError("journal predecessor chain is invalid")
            if record.get("member_id") != self.member_id or record.get("membership_digest") != self.membership.digest:
                raise SeedCommitLedgerError("journal participant or membership identity mismatch")
            unsigned = {key: record[key] for key in required_keys - {"receipt"}}
            expected_receipt = hashlib.sha256(head + _canonical_bytes(unsigned)).hexdigest()
            if record.get("receipt") != expected_receipt:
                raise SeedCommitLedgerError("journal receipt hash mismatch")
            proposal_payload = record.get("proposal")
            proposal = SeedCommitProposal.from_snapshot(proposal_payload)
            self._validate_proposal(proposal)
            key = proposal.slot_key
            kind = record.get("kind")
            if kind == "prepare":
                if (
                    record.get("certificate") is not None
                    or record.get("observed_vote") is not None
                    or record.get("observed_decision") is not None
                    or key in prepared
                ):
                    raise SeedCommitLedgerError("duplicate or malformed durable prepare vote")
                artifact_payload = record.get("artifact")
                artifact = None
                if artifact_payload is not None:
                    artifact = SeedCommitTransitionArtifact.from_snapshot(artifact_payload)
                self._validate_transition_artifact(proposal, artifact)
                self._validate_next_slot_in(proposal, committed, prepared)
                vote = SeedPrepareVote(self.member_id, self.membership.digest, proposal.digest, expected_receipt)
                prepared[key] = (proposal, vote)
                if artifact is not None:
                    prepared_artifacts[key] = artifact
            elif kind == "observe":
                raw_vote = record.get("observed_vote")
                if (
                    record.get("certificate") is not None
                    or record.get("artifact") is not None
                    or record.get("observed_decision") is not None
                    or key not in prepared
                    or prepared[key][0].digest != proposal.digest
                    or not isinstance(raw_vote, Mapping)
                ):
                    raise SeedCommitLedgerError("observed-vote record has no matching local prepare")
                vote = SeedPrepareVote.from_snapshot(raw_vote)
                if (
                    vote.member_id not in self.membership.member_ids
                    or vote.member_id == self.member_id
                    or vote.membership_digest != self.membership.digest
                    or vote.proposal_digest != proposal.digest
                ):
                    raise SeedCommitLedgerError("observed-vote record identity is invalid")
                certificate = certificates.get(key)
                if certificate is not None:
                    certified = {item.member_id: item for item in certificate.votes}
                    if vote.member_id in certified and certified[vote.member_id] != vote:
                        raise SeedCommitLedgerError("observed vote conflicts with committed certificate")
                votes = observed_votes.setdefault(key, {})
                if vote.member_id in votes:
                    raise SeedCommitLedgerError("duplicate observed-vote journal record")
                votes[vote.member_id] = vote
            elif kind == "observe-decision":
                raw_decision = record.get("observed_decision")
                certificate = certificates.get(key)
                if (
                    record.get("certificate") is not None
                    or record.get("artifact") is not None
                    or record.get("observed_vote") is not None
                    or key not in committed
                    or committed[key].proposal_digest != proposal.digest
                    or certificate is None
                    or not isinstance(raw_decision, Mapping)
                ):
                    raise SeedCommitLedgerError("observed-decision record has no matching durable local commit")
                decision = SeedCommitDecision.from_snapshot(raw_decision)
                expected_voters = tuple(sorted(vote.member_id for vote in certificate.votes))
                if (
                    decision.member_id not in self.membership.member_ids
                    or decision.member_id == self.member_id
                    or decision.proposal_digest != proposal.digest
                    or decision.slot != proposal.slot
                    or decision.state_digest != proposal.result_state_digest
                    or decision.certificate_members != expected_voters
                ):
                    raise SeedCommitLedgerError("observed-decision record identity is invalid")
                decisions = observed_decisions.setdefault(key, {})
                if decision.member_id in decisions:
                    raise SeedCommitLedgerError("duplicate observed-decision journal record")
                decisions[decision.member_id] = decision
            elif kind == "commit":
                certificate_payload = record.get("certificate")
                certificate = SeedCommitCertificate.from_snapshot(certificate_payload)
                if (
                    record.get("artifact") is not None
                    or record.get("observed_vote") is not None
                    or record.get("observed_decision") is not None
                    or key not in prepared
                    or prepared[key][0].digest != proposal.digest
                    or key in committed
                ):
                    raise SeedCommitLedgerError("commit record lacks one matching unique prepare vote")
                self._validate_certificate(proposal, certificate)
                self._validate_next_slot_in(proposal, committed, prepared)
                decision = SeedCommitDecision(
                    self.member_id,
                    proposal.digest,
                    proposal.slot,
                    proposal.result_state_digest,
                    tuple(vote.member_id for vote in certificate.votes),
                    expected_receipt,
                )
                committed[key] = decision
                certificates[key] = certificate
            else:
                raise SeedCommitLedgerError("journal record kind is unsupported")
            sequence = record_sequence
            head = bytes.fromhex(expected_receipt)
        self._prepared = prepared
        self._prepared_artifacts = prepared_artifacts
        self._observed_votes = observed_votes
        self._committed = committed
        self._certificates = certificates
        self._observed_decisions = observed_decisions
        self._sequence = sequence
        self._head = head
        stat = self.path.stat()
        self._file_signature = (stat.st_size, stat.st_mtime_ns)

    def _validate_next_slot_in(
        self,
        proposal: SeedCommitProposal,
        committed: Mapping[tuple[str, int, str, int, int], SeedCommitDecision],
        prepared: Mapping[tuple[str, int, str, int, int], tuple[SeedCommitProposal, SeedPrepareVote]],
    ) -> None:
        """Mathematics: validate transition extension over replay candidates, with no access to mutable live indexes."""

        if committed:
            latest_key = max(committed, key=lambda key: key[-1])
            latest = committed[latest_key]
            expected_slot = latest.slot + 1
            expected_digest = latest.state_digest
        else:
            expected_slot = 1
            expected_digest = self.membership.genesis_state_digest
        if proposal.slot != expected_slot or proposal.predecessor_state_digest != expected_digest:
            raise SeedCommitLedgerError("proposal predecessor or slot does not extend committed state")
        if any(
            prepared_key != proposal.slot_key and prepared_proposal.slot == proposal.slot
            for prepared_key, (prepared_proposal, _vote) in prepared.items()
        ):
            raise SeedCommitLedgerError("another slot proposal is already prepared")

    @contextmanager
    def _locked(self) -> Iterator[None]:
        """Mathematics: serialize replay and append with a cross-process exclusive lock `L`, releasing `L` on every exit."""

        self._lock_path.touch(exist_ok=True)
        with self._lock_path.open("a+b") as lock:
            lock.seek(0, os.SEEK_END)
            if lock.tell() == 0:
                lock.write(b"0")
                lock.flush()
            lock.seek(0)
            locking_module: Any = None
            try:
                import msvcrt as locking_module
            except ImportError:
                try:
                    import fcntl as locking_module
                except ImportError:
                    locking_module = None
            if locking_module is None or not (
                hasattr(locking_module, "locking") or hasattr(locking_module, "flock")
            ):
                raise SeedCommitLedgerError("platform does not provide cross-process journal locking")
            if hasattr(locking_module, "locking"):
                locking_module.locking(lock.fileno(), locking_module.LK_LOCK, 1)
            elif locking_module is not None:
                locking_module.flock(lock.fileno(), locking_module.LOCK_EX)
            try:
                yield
            finally:
                if hasattr(locking_module, "locking"):
                    lock.seek(0)
                    locking_module.locking(lock.fileno(), locking_module.LK_UNLCK, 1)
                else:
                    locking_module.flock(lock.fileno(), locking_module.LOCK_UN)
