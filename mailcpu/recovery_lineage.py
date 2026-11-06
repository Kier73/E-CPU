"""Quorum-anchored lineage for requester/receiver recovery checkpoints.

Checkpoint files remain the data plane. This module records their exact
content identities in a separate fixed-membership quorum ledger, allowing a
valid but older checkpoint to be distinguished from the latest one.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

from .seed_commit_quorum import (
    DurableSeedCommitLedger,
    SeedCommitCertificate,
    SeedCommitDecision,
    SeedCommitLedgerError,
    SeedCommitMembership,
    SeedCommitProposal,
    SeedPrepareVote,
)


class RecoveryLineageError(ValueError):
    """A checkpoint manifest, quorum anchor, or lineage transition is invalid."""


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    """Encode a finite record into deterministic UTF-8 JSON bytes."""

    try:
        return json.dumps(
            dict(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise RecoveryLineageError("recovery lineage record is outside canonical JSON") from exc


def _label(value: Any, name: str) -> str:
    """Validate one stable non-empty identity label."""

    if not isinstance(value, str) or not value or value.strip() != value:
        raise RecoveryLineageError(f"{name} must be non-empty, trimmed text")
    return value


def _positive(value: Any, name: str) -> int:
    """Validate one positive integer coordinate without accepting booleans."""

    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise RecoveryLineageError(f"{name} must be a positive integer")
    return value


def _digest(value: Any, name: str) -> str:
    """Validate and normalize a 256-bit hexadecimal content identity."""

    if not isinstance(value, str) or len(value) != 64:
        raise RecoveryLineageError(f"{name} must be a 64-character SHA-256 digest")
    try:
        raw = bytes.fromhex(value)
    except ValueError as exc:
        raise RecoveryLineageError(f"{name} is not hexadecimal") from exc
    if len(raw) != 32:
        raise RecoveryLineageError(f"{name} must encode exactly 32 bytes")
    return raw.hex()


@dataclass(frozen=True)
class RecoveryCheckpointManifest:
    """Exact content binding for one requester/receiver checkpoint generation."""

    machine_id: str
    incarnation: int
    owner_id: str
    owner_term: int
    membership_digest: str
    generation: int
    predecessor_digest: str
    requester_checkpoint_digest: str
    receiver_checkpoint_digest: str
    backend_manifest_digest: str
    capture_cut: str

    def __post_init__(self) -> None:
        """Validate machine, membership, monotonic slot, predecessor, and checkpoint content digests."""

        _label(self.machine_id, "machine id")
        _positive(self.incarnation, "machine incarnation")
        _label(self.owner_id, "lineage owner id")
        _positive(self.owner_term, "owner term")
        _positive(self.generation, "checkpoint generation")
        _label(self.capture_cut, "checkpoint capture cut")
        for field_name in (
            "membership_digest",
            "predecessor_digest",
            "requester_checkpoint_digest",
            "receiver_checkpoint_digest",
            "backend_manifest_digest",
        ):
            object.__setattr__(self, field_name, _digest(getattr(self, field_name), field_name))

    def snapshot(self) -> dict[str, object]:
        """Project every coordinate that determines this checkpoint generation's root digest."""

        return {
            "version": 1,
            "machine_id": self.machine_id,
            "incarnation": self.incarnation,
            "owner_id": self.owner_id,
            "owner_term": self.owner_term,
            "membership_digest": self.membership_digest,
            "generation": self.generation,
            "predecessor_digest": self.predecessor_digest,
            "requester_checkpoint_digest": self.requester_checkpoint_digest,
            "receiver_checkpoint_digest": self.receiver_checkpoint_digest,
            "backend_manifest_digest": self.backend_manifest_digest,
            "capture_cut": self.capture_cut,
        }

    @property
    def digest(self) -> str:
        """Compute the manifest root binding both endpoint checkpoints and backend identity."""

        return hashlib.sha256(_canonical_bytes(self.snapshot())).hexdigest()

    @property
    def request_fingerprint(self) -> str:
        """Domain-separate this recovery proposal from other fixed-membership log uses."""

        payload = {
            "kind": "mailcpu.recovery-lineage.manifest",
            "manifest_digest": self.digest,
            "machine_id": self.machine_id,
            "generation": self.generation,
        }
        return hashlib.sha256(_canonical_bytes(payload)).hexdigest()

    def verify_payloads(
        self,
        requester_checkpoint: bytes,
        receiver_checkpoint: bytes,
        backend_manifest: bytes,
    ) -> None:
        """Require supplied checkpoint bytes to match the exact digests sealed by this manifest."""

        materials = (
            ("requester checkpoint", requester_checkpoint, self.requester_checkpoint_digest),
            ("receiver checkpoint", receiver_checkpoint, self.receiver_checkpoint_digest),
            ("backend manifest", backend_manifest, self.backend_manifest_digest),
        )
        for name, material, expected in materials:
            if not isinstance(material, bytes):
                raise RecoveryLineageError(f"{name} material must be bytes")
            actual = hashlib.sha256(material).hexdigest()
            if actual != expected:
                raise RecoveryLineageError(f"{name} digest does not match the recovery manifest")

    @classmethod
    def from_snapshot(cls, payload: Mapping[str, Any]) -> "RecoveryCheckpointManifest":
        """Reconstruct a manifest only from its exact versioned field set."""

        fields = {
            "version",
            "machine_id",
            "incarnation",
            "owner_id",
            "owner_term",
            "membership_digest",
            "generation",
            "predecessor_digest",
            "requester_checkpoint_digest",
            "receiver_checkpoint_digest",
            "backend_manifest_digest",
            "capture_cut",
        }
        if not isinstance(payload, Mapping) or set(payload) != fields or payload.get("version") != 1:
            raise RecoveryLineageError("recovery checkpoint manifest fields or version are invalid")
        try:
            return cls(
                payload["machine_id"],
                payload["incarnation"],
                payload["owner_id"],
                payload["owner_term"],
                payload["membership_digest"],
                payload["generation"],
                payload["predecessor_digest"],
                payload["requester_checkpoint_digest"],
                payload["receiver_checkpoint_digest"],
                payload["backend_manifest_digest"],
                payload["capture_cut"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, RecoveryLineageError):
                raise
            raise RecoveryLineageError("recovery checkpoint manifest is malformed") from exc


@dataclass(frozen=True)
class RecoveryLineageProof:
    """Quorum certificate and durable commit decisions for one checkpoint manifest."""

    proposal: SeedCommitProposal
    certificate: SeedCommitCertificate
    decisions: tuple[SeedCommitDecision, ...]

    def __post_init__(self) -> None:
        """Require every durable decision and prepare certificate to refer to one exact proposal."""

        if not isinstance(self.proposal, SeedCommitProposal):
            raise RecoveryLineageError("lineage proof requires a typed seed-commit proposal")
        if not isinstance(self.certificate, SeedCommitCertificate):
            raise RecoveryLineageError("lineage proof requires a typed prepare certificate")
        if not isinstance(self.decisions, (list, tuple)) or not self.decisions:
            raise RecoveryLineageError("lineage proof requires a non-empty decision set")
        decisions = tuple(self.decisions)
        if any(not isinstance(item, SeedCommitDecision) for item in decisions):
            raise RecoveryLineageError("lineage proof decisions must be typed")
        members = tuple(item.member_id for item in decisions)
        if len(members) != len(set(members)):
            raise RecoveryLineageError("lineage proof decision members must be unique")
        if (
            self.certificate.membership_digest != self.proposal.membership_digest
            or self.certificate.proposal_digest != self.proposal.digest
        ):
            raise RecoveryLineageError("lineage proof certificate does not match its proposal")
        certificate_members = tuple(sorted(vote.member_id for vote in self.certificate.votes))
        if len(certificate_members) != len(set(certificate_members)):
            raise RecoveryLineageError("lineage proof certificate voters must be unique")
        for decision in decisions:
            if (
                decision.proposal_digest != self.proposal.digest
                or decision.slot != self.proposal.slot
                or decision.state_digest != self.proposal.result_state_digest
                or decision.certificate_members != certificate_members
            ):
                raise RecoveryLineageError("lineage proof contains a decision for another transition")
        object.__setattr__(self, "decisions", decisions)

    def snapshot(self) -> dict[str, object]:
        """Serialize the exact proposal, prepare certificate, and durable commit quorum."""

        return {
            "version": 1,
            "proposal": self.proposal.snapshot(),
            "certificate": self.certificate.snapshot(),
            "decisions": [item.snapshot() for item in self.decisions],
        }

    @classmethod
    def from_snapshot(cls, payload: Mapping[str, Any]) -> "RecoveryLineageProof":
        """Reconstruct a proof from validated proposal, certificate, and decision records."""

        if (
            not isinstance(payload, Mapping)
            or set(payload) != {"version", "proposal", "certificate", "decisions"}
            or payload.get("version") != 1
            or not isinstance(payload.get("decisions"), (list, tuple))
        ):
            raise RecoveryLineageError("recovery lineage proof fields or version are invalid")
        try:
            return cls(
                SeedCommitProposal.from_snapshot(payload["proposal"]),
                SeedCommitCertificate.from_snapshot(payload["certificate"]),
                tuple(SeedCommitDecision.from_snapshot(item) for item in payload["decisions"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, RecoveryLineageError):
                raise
            raise RecoveryLineageError("recovery lineage proof is malformed") from exc


class RecoveryLineageAuthority:
    """One durable fixed-membership participant in the independent recovery anchor."""

    def __init__(
        self,
        membership: SeedCommitMembership,
        member_id: str,
        journal_path: str,
    ) -> None:
        """Open the member's fsynced one-vote/commit journal under immutable quorum membership."""

        if not isinstance(membership, SeedCommitMembership):
            raise RecoveryLineageError("recovery authority requires a fixed seed-commit membership")
        try:
            self.ledger = DurableSeedCommitLedger(journal_path, member_id, membership)
        except (SeedCommitLedgerError, OSError, TypeError, ValueError) as exc:
            raise RecoveryLineageError(f"cannot open recovery authority journal: {exc}") from exc

    @property
    def member_id(self) -> str:
        """Return the configured identity of this durable authority member."""

        return self.ledger.member_id

    @property
    def membership(self) -> SeedCommitMembership:
        """Return the immutable membership that scopes this authority's votes."""

        return self.ledger.membership

    def prepare(self, proposal: SeedCommitProposal) -> SeedPrepareVote:
        """Fsync this member's single-valued vote for the exact checkpoint-generation proposal."""

        try:
            return self.ledger.prepare(proposal)
        except SeedCommitLedgerError as exc:
            raise RecoveryLineageError(f"authority {self.member_id} refused prepare: {exc}") from exc

    def commit(
        self,
        proposal: SeedCommitProposal,
        certificate: SeedCommitCertificate,
    ) -> SeedCommitDecision:
        """Fsync the proposal decision only after validating the fixed-membership majority certificate."""

        try:
            return self.ledger.commit(proposal, certificate)
        except SeedCommitLedgerError as exc:
            raise RecoveryLineageError(f"authority {self.member_id} refused commit: {exc}") from exc

    def committed_state(self) -> tuple[int, str] | None:
        """Return the highest locally committed lineage slot and checkpoint root."""

        try:
            return self.ledger.committed_state()
        except SeedCommitLedgerError as exc:
            raise RecoveryLineageError(f"authority {self.member_id} cannot read its committed state: {exc}") from exc

    def proposal_at(self, generation: int) -> SeedCommitProposal | None:
        """Read the one prepared proposal for a generation, if this authority has one."""

        try:
            return self.ledger.proposal_at(generation)
        except SeedCommitLedgerError as exc:
            raise RecoveryLineageError(f"authority {self.member_id} cannot read generation {generation}: {exc}") from exc

    def decision(self, proposal: SeedCommitProposal) -> SeedCommitDecision | None:
        """Read the durable local decision for an exact proposal."""

        try:
            return self.ledger.decision(proposal)
        except SeedCommitLedgerError as exc:
            raise RecoveryLineageError(f"authority {self.member_id} cannot read the proposal decision: {exc}") from exc

    def certificate(self, proposal: SeedCommitProposal) -> SeedCommitCertificate | None:
        """Read the durable majority certificate bound to an exact proposal."""

        try:
            return self.ledger.certificate(proposal)
        except SeedCommitLedgerError as exc:
            raise RecoveryLineageError(f"authority {self.member_id} cannot read the proposal certificate: {exc}") from exc

    def verify(self) -> bool:
        """Replay this participant journal and compare its recovered state with the live projection."""

        try:
            return self.ledger.verify()
        except SeedCommitLedgerError:
            return False


class RecoveryLineageCoordinator:
    """Fixed-membership quorum coordinator for monotonic checkpoint-generation anchors."""

    def __init__(
        self,
        membership: SeedCommitMembership,
        authorities: Mapping[str, RecoveryLineageAuthority],
    ) -> None:
        """Bind independent durable authority journals to one immutable strict-majority membership."""

        if not isinstance(membership, SeedCommitMembership):
            raise RecoveryLineageError("lineage coordinator requires a typed fixed membership")
        if not isinstance(authorities, Mapping) or not authorities:
            raise RecoveryLineageError("lineage coordinator requires at least one authority")
        selected: dict[str, RecoveryLineageAuthority] = {}
        for member_id, authority in authorities.items():
            if not isinstance(member_id, str) or not isinstance(authority, RecoveryLineageAuthority):
                raise RecoveryLineageError("lineage authority mapping must contain typed members")
            if member_id != authority.member_id or member_id not in membership.member_ids:
                raise RecoveryLineageError("lineage authority key does not match configured membership identity")
            if authority.membership.digest != membership.digest:
                raise RecoveryLineageError("lineage authority is bound to another membership")
            selected[member_id] = authority
        self.membership = membership
        self.authorities = dict(sorted(selected.items()))

    def proposal_for(self, manifest: RecoveryCheckpointManifest) -> SeedCommitProposal:
        """Translate one checkpoint manifest into the existing fixed-membership slot algebra."""

        if not isinstance(manifest, RecoveryCheckpointManifest):
            raise RecoveryLineageError("lineage proposal requires a typed checkpoint manifest")
        if (
            manifest.machine_id != self.membership.system_id
            or manifest.incarnation != self.membership.incarnation
            or manifest.owner_id != self.membership.owner_id
            or manifest.owner_term != self.membership.owner_term
            or manifest.membership_digest != self.membership.digest
        ):
            raise RecoveryLineageError("checkpoint manifest does not match configured machine membership")
        return SeedCommitProposal(
            self.membership.digest,
            self.membership.system_id,
            self.membership.incarnation,
            self.membership.owner_id,
            self.membership.owner_term,
            manifest.generation,
            manifest.predecessor_digest,
            manifest.request_fingerprint,
            manifest.digest,
        )

    def seal(self, manifest: RecoveryCheckpointManifest) -> RecoveryLineageProof:
        """Prepare, certify, and fsync one checkpoint root on a strict majority before issuing proof."""

        proposal = self.proposal_for(manifest)
        votes: dict[str, SeedPrepareVote] = {}
        refused: dict[str, str] = {}
        for member_id, authority in self.authorities.items():
            try:
                vote = authority.prepare(proposal)
            except RecoveryLineageError as exc:
                refused[member_id] = str(exc)
                continue
            if (
                vote.member_id != member_id
                or vote.membership_digest != self.membership.digest
                or vote.proposal_digest != proposal.digest
            ):
                raise RecoveryLineageError("authority returned a vote for another member or proposal")
            votes[member_id] = vote

        if len(votes) < self.membership.quorum or self.membership.owner_id not in votes:
            detail = "; ".join(f"{member}: {reason}" for member, reason in sorted(refused.items()))
            raise RecoveryLineageError(
                f"checkpoint generation {manifest.generation} lacks a strict-majority prepare quorum"
                + (f" ({detail})" if detail else "")
            )

        # A previous attempt may have fsynced COMMIT on fewer than a quorum
        # before the coordinator died. Reuse that exact certificate; creating a
        # larger new certificate would make the already-committed decision's
        # certificate-members projection differ from the retry.
        existing_certificate: SeedCommitCertificate | None = None
        for authority in self.authorities.values():
            if authority.decision(proposal) is None:
                continue
            stored = authority.certificate(proposal)
            if stored is None:
                raise RecoveryLineageError("committed recovery proposal has no durable certificate")
            if existing_certificate is not None and stored.snapshot() != existing_certificate.snapshot():
                raise RecoveryLineageError("authorities disagree on the certificate for an already-committed proposal")
            existing_certificate = stored

        certificate = existing_certificate or SeedCommitCertificate(
            self.membership.digest,
            proposal.digest,
            tuple(votes[member] for member in sorted(votes)),
        )
        certificate_members = tuple(vote.member_id for vote in certificate.votes)
        if (
            len(certificate_members) < self.membership.quorum
            or len(certificate_members) != len(set(certificate_members))
            or self.membership.owner_id not in certificate_members
            or any(member not in self.membership.member_ids for member in certificate_members)
            or any(
                vote.membership_digest != self.membership.digest
                or vote.proposal_digest != proposal.digest
                for vote in certificate.votes
            )
        ):
            raise RecoveryLineageError("recovery lineage prepare certificate is not a valid configured quorum")

        decisions: dict[str, SeedCommitDecision] = {}
        for member_id, authority in self.authorities.items():
            if member_id not in votes:
                continue
            try:
                decision = authority.commit(proposal, certificate)
            except RecoveryLineageError as exc:
                refused[member_id] = str(exc)
                continue
            decisions[member_id] = decision

        if len(decisions) < self.membership.quorum:
            detail = "; ".join(f"{member}: {reason}" for member, reason in sorted(refused.items()))
            raise RecoveryLineageError(
                f"checkpoint generation {manifest.generation} lacks a durable commit quorum"
                + (f" ({detail})" if detail else "")
            )
        proof = RecoveryLineageProof(
            proposal,
            certificate,
            tuple(decisions[member] for member in sorted(decisions)),
        )
        self._validate_proof_membership(proof)
        return proof

    def latest_proof(self) -> RecoveryLineageProof | None:
        """Read a quorum-supported high-water record; a minority-ahead journal never advances the admitted head."""

        states: dict[tuple[int, str], list[str]] = {}
        genesis = (0, self.membership.genesis_state_digest)
        for member_id, authority in self.authorities.items():
            state = authority.committed_state() or genesis
            states.setdefault(state, []).append(member_id)

        supported = [
            state for state, members in states.items()
            if len(members) >= self.membership.quorum
        ]
        if not supported:
            raise RecoveryLineageError("available recovery authorities do not agree on a read quorum")
        generation, state_digest = max(supported, key=lambda item: item[0])
        if generation == 0:
            return None

        proposal: SeedCommitProposal | None = None
        certificate: SeedCommitCertificate | None = None
        decisions: dict[str, SeedCommitDecision] = {}
        for member_id in states[(generation, state_digest)]:
            authority = self.authorities[member_id]
            candidate = authority.proposal_at(generation)
            if candidate is None or candidate.result_state_digest != state_digest:
                raise RecoveryLineageError("quorum high-water record has no matching prepared proposal")
            candidate_certificate = authority.certificate(candidate)
            candidate_decision = authority.decision(candidate)
            if candidate_certificate is None or candidate_decision is None:
                raise RecoveryLineageError("quorum high-water record lacks its durable certificate or decision")
            if proposal is None:
                proposal = candidate
                certificate = candidate_certificate
            elif (
                candidate.digest != proposal.digest
                or candidate_certificate.snapshot() != certificate.snapshot()
            ):
                raise RecoveryLineageError("authorities disagree on the high-water proposal or certificate")
            # This idempotent call re-runs the ledger's strict certificate,
            # membership, predecessor, and proposal validation.
            authority.commit(candidate, candidate_certificate)
            decisions[member_id] = candidate_decision

        if proposal is None or certificate is None or len(decisions) < self.membership.quorum:
            raise RecoveryLineageError("high-water record is not supported by a durable decision quorum")
        proof = RecoveryLineageProof(
            proposal,
            certificate,
            tuple(decisions[member] for member in sorted(decisions)),
        )
        self._validate_proof_membership(proof)
        return proof

    def high_water(self) -> tuple[int, str]:
        """Return the quorum-supported generation/root or the configured genesis coordinate."""

        proof = self.latest_proof()
        if proof is None:
            return 0, self.membership.genesis_state_digest
        return proof.proposal.slot, proof.proposal.result_state_digest

    def verify_checkpoint(self, manifest: RecoveryCheckpointManifest) -> RecoveryLineageProof:
        """Admit only the exact latest manifest; a valid but older checkpoint is rejected as rollback."""

        proposal = self.proposal_for(manifest)
        latest = self.latest_proof()
        if latest is None:
            raise RecoveryLineageError("no checkpoint generation has been quorum-anchored")
        if proposal.slot < latest.proposal.slot:
            raise RecoveryLineageError(
                f"checkpoint generation {proposal.slot} is stale; high-water generation is {latest.proposal.slot}"
            )
        if proposal.slot > latest.proposal.slot:
            raise RecoveryLineageError(
                f"checkpoint generation {proposal.slot} is ahead of committed high-water {latest.proposal.slot}"
            )
        if proposal.digest != latest.proposal.digest:
            raise RecoveryLineageError("checkpoint manifest conflicts with committed high-water generation")
        return latest

    def _validate_proof_membership(self, proof: RecoveryLineageProof) -> None:
        """Require prepare and commit sets to satisfy the configured fixed-membership quorum."""

        if (
            proof.proposal.membership_digest != self.membership.digest
            or proof.proposal.system_id != self.membership.system_id
            or proof.proposal.incarnation != self.membership.incarnation
            or proof.proposal.owner_id != self.membership.owner_id
            or proof.proposal.owner_term != self.membership.owner_term
        ):
            raise RecoveryLineageError("lineage proof proposal does not match configured membership")
        vote_members = tuple(vote.member_id for vote in proof.certificate.votes)
        decision_members = tuple(decision.member_id for decision in proof.decisions)
        if (
            len(vote_members) < self.membership.quorum
            or self.membership.owner_id not in vote_members
            or len(vote_members) != len(set(vote_members))
            or any(member not in self.membership.member_ids for member in vote_members)
        ):
            raise RecoveryLineageError("lineage proof does not contain a valid fixed-membership prepare quorum")
        if (
            len(decision_members) < self.membership.quorum
            or len(decision_members) != len(set(decision_members))
            or any(member not in self.membership.member_ids for member in decision_members)
        ):
            raise RecoveryLineageError("lineage proof does not contain a durable commit quorum")
