"""Quorum-anchored portable claims for replay-safe computational result ownership.

A claim does not promise that only one physical processor can calculate a pure
operation. It makes result acceptance transferable: after a quorum-anchored
reassignment, only the current assignment epoch may commit the semantic result.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import threading
from copy import deepcopy
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from .recovery_lineage import (
    RecoveryLineageCoordinator,
    RecoveryLineageError,
    RecoveryLineageProof,
    RecoveryStateManifest,
)
from .virtual_layer import OperatorSpec


class TransferableExecutionClaimError(ValueError):
    """Mathematics: A portable execution claim, assignment transition, or quorum proof is invalid."""


REPLAY_POLICY_PURE = "pure-replay-safe/v1"
_CAPTURE_CUT = "transferable-execution-claims"
_MAX_CLAIMS = 16_384
_MAX_ASSIGNMENTS_PER_CLAIM = 64
_MAX_STATE_BYTES = 16 * 1024 * 1024
_MAX_TICKET_BYTES = 128 * 1024
_SCHEMA = "mailcpu.transferable-execution-claim-ledger.v1"
_HEX = frozenset("0123456789abcdef")


def _canonical_json(value: Mapping[str, Any]) -> bytes:
    """Mathematics: Encode a finite record into deterministic UTF-8 JSON bytes."""
    try:
        return json.dumps(
            dict(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise TransferableExecutionClaimError("execution claim record is outside canonical JSON") from exc


def _digest(value: Any, name: str) -> str:
    """Mathematics: Require one lowercase SHA-256 identity in the canonical digest domain."""
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in _HEX for character in value)
    ):
        raise TransferableExecutionClaimError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _label(value: Any, name: str, maximum: int = 256) -> str:
    """Mathematics: Validate one bounded, non-empty, trimmed identity label."""
    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or len(value) > maximum
        or any(ord(character) < 32 for character in value)
    ):
        raise TransferableExecutionClaimError(f"{name} must be bounded non-empty trimmed text")
    return value


def _fabric_id(value: Any, name: str) -> str:
    """Mathematics: Match the fabric's ASCII peer/logical-host identifier alphabet and 128-character bound."""
    selected = _label(value, name, 128)
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.:"
    if not selected[0].isalnum() or not selected.isascii() or any(character not in allowed for character in selected):
        raise TransferableExecutionClaimError(f"{name} is not a valid computational-fabric identity")
    return selected


def _positive(value: Any, name: str) -> int:
    """Mathematics: Require one strictly positive integer coordinate and exclude Boolean aliases."""
    if type(value) is not int or value <= 0:
        raise TransferableExecutionClaimError(f"{name} must be a positive strict integer")
    return value


def _read_bounded(path: Path, maximum: int, name: str) -> bytes:
    """Mathematics: Read at most maximum+1 bytes so an oversized persisted artifact is refused before unbounded allocation."""
    try:
        with path.open("rb") as stream:
            payload = stream.read(maximum + 1)
    except OSError as exc:
        raise TransferableExecutionClaimError(f"cannot read {name}: {exc}") from exc
    if len(payload) > maximum:
        raise TransferableExecutionClaimError(f"{name} exceeds its finite byte bound")
    return payload


def _fsync_directory(path: Path) -> None:
    """Mathematics: Persist directory-entry publication where the platform exposes directory fsync."""
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class ExecutionClaimStatus(str, Enum):
    """Mathematics: The claim state is assigned until one current-epoch result is quorum committed."""

    ASSIGNED = "assigned"
    COMPLETED = "completed"


@dataclass(frozen=True)
class ExecutionClaimAssignment:
    """Mathematics: One fenced assignment coordinate A=(epoch,peer,host,implementation,generation,evidence)."""

    epoch: int
    owner_peer_id: str
    owner_host_id: str
    implementation_fingerprint: str
    state_generation: int
    failure_evidence_digest: str | None = None

    def __post_init__(self) -> None:
        _positive(self.epoch, "assignment epoch")
        _fabric_id(self.owner_peer_id, "assignment peer id")
        _fabric_id(self.owner_host_id, "assignment host id")
        _digest(self.implementation_fingerprint, "assignment implementation fingerprint")
        _positive(self.state_generation, "assignment state generation")
        if self.epoch == 1 and self.failure_evidence_digest is not None:
            raise TransferableExecutionClaimError("initial assignment cannot carry reassignment evidence")
        if self.epoch > 1:
            _digest(self.failure_evidence_digest, "reassignment evidence digest")

    @property
    def digest(self) -> str:
        """Mathematics: Identify the exact owner/implementation/epoch assignment and its recovery evidence."""
        return hashlib.sha256(_canonical_json(self.to_dict())).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: Serialize every assignment coordinate needed to verify the fencing epoch."""
        return {
            "epoch": self.epoch,
            "owner_peer_id": self.owner_peer_id,
            "owner_host_id": self.owner_host_id,
            "implementation_fingerprint": self.implementation_fingerprint,
            "state_generation": self.state_generation,
            "failure_evidence_digest": self.failure_evidence_digest,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ExecutionClaimAssignment":
        """Mathematics: Reconstruct an assignment only from its exact versioned field set."""
        expected = {
            "epoch", "owner_peer_id", "owner_host_id",
            "implementation_fingerprint", "state_generation",
            "failure_evidence_digest",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise TransferableExecutionClaimError("execution claim assignment fields are malformed")
        try:
            return cls(
                payload["epoch"],
                payload["owner_peer_id"],
                payload["owner_host_id"],
                payload["implementation_fingerprint"],
                payload["state_generation"],
                payload["failure_evidence_digest"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, TransferableExecutionClaimError):
                raise
            raise TransferableExecutionClaimError("execution claim assignment is invalid") from exc


@dataclass(frozen=True)
class TransferableExecutionClaim:
    """Mathematics: Immutable operation identity plus an ordered assignment history and one terminal result commitment."""

    parent_request_digest: str
    child_request_digest: str
    address_digest: str
    operator_id: str
    operator_contract_digest: str
    operator_spec: OperatorSpec
    computational_ground_fingerprint: str
    replay_policy: str
    assignments: tuple[ExecutionClaimAssignment, ...]
    status: ExecutionClaimStatus = ExecutionClaimStatus.ASSIGNED
    result_digest: str | None = None
    child_receipt_digest: str | None = None
    completion_generation: int | None = None

    def __post_init__(self) -> None:
        for name in (
            "parent_request_digest",
            "child_request_digest",
            "address_digest",
            "operator_contract_digest",
            "computational_ground_fingerprint",
        ):
            _digest(getattr(self, name), name)
        _label(self.operator_id, "operator id", 256)
        if not isinstance(self.operator_spec, OperatorSpec):
            raise TransferableExecutionClaimError("transferable claim requires the exact typed OperatorSpec")
        if (
            self.operator_spec.operator_id != self.operator_id
            or self.operator_spec.digest != self.operator_contract_digest
            or not self.operator_spec.replay_safe
        ):
            raise TransferableExecutionClaimError(
                "transferable claim requires a matching deterministic pure OperatorSpec"
            )
        if self.replay_policy != REPLAY_POLICY_PURE:
            raise TransferableExecutionClaimError(
                "transferable claims currently admit only the pure replay-safe execution policy"
            )
        assignments = tuple(self.assignments)
        if not assignments or any(not isinstance(item, ExecutionClaimAssignment) for item in assignments):
            raise TransferableExecutionClaimError("execution claim requires a non-empty typed assignment history")
        if len(assignments) > _MAX_ASSIGNMENTS_PER_CLAIM:
            raise TransferableExecutionClaimError("assignment history exceeds the finite claim bound")
        if tuple(item.epoch for item in assignments) != tuple(range(1, len(assignments) + 1)):
            raise TransferableExecutionClaimError("assignment epochs must be contiguous and begin at one")
        generations = tuple(item.state_generation for item in assignments)
        if generations != tuple(sorted(set(generations))):
            raise TransferableExecutionClaimError("assignment generations must be strictly increasing")
        for previous, current in zip(assignments, assignments[1:]):
            if (previous.owner_peer_id, previous.owner_host_id) == (
                current.owner_peer_id, current.owner_host_id
            ):
                raise TransferableExecutionClaimError("reassignment must move to a different logical host")
            if current.failure_evidence_digest is None:
                raise TransferableExecutionClaimError("reassignment requires an evidence commitment")
        object.__setattr__(self, "assignments", assignments)
        if not isinstance(self.status, ExecutionClaimStatus):
            try:
                object.__setattr__(self, "status", ExecutionClaimStatus(self.status))
            except (TypeError, ValueError) as exc:
                raise TransferableExecutionClaimError("execution claim status is unsupported") from exc
        if self.status is ExecutionClaimStatus.ASSIGNED:
            if any(item is not None for item in (
                self.result_digest, self.child_receipt_digest, self.completion_generation
            )):
                raise TransferableExecutionClaimError("assigned claim cannot contain completion evidence")
        else:
            _digest(self.result_digest, "completed result digest")
            _digest(self.child_receipt_digest, "completed child receipt digest")
            _positive(self.completion_generation, "completion generation")
            if self.completion_generation <= assignments[-1].state_generation:
                raise TransferableExecutionClaimError("completion generation must follow the current assignment")

    @property
    def claim_id(self) -> str:
        """Mathematics: Derive stable claim identity from the immutable parent/child/address/operator/Ground tuple."""
        return hashlib.sha256(_canonical_json({
            "schema": "mailcpu.transferable-execution-claim-identity.v1",
            "parent_request_digest": self.parent_request_digest,
            "child_request_digest": self.child_request_digest,
            "address_digest": self.address_digest,
            "operator_id": self.operator_id,
            "operator_contract_digest": self.operator_contract_digest,
            "operator_spec": self.operator_spec.to_dict(),
            "computational_ground_fingerprint": self.computational_ground_fingerprint,
            "replay_policy": self.replay_policy,
        })).hexdigest()

    @property
    def current_assignment(self) -> ExecutionClaimAssignment:
        """Mathematics: Select the last assignment in the monotonic fencing sequence."""
        return self.assignments[-1]

    def _payload(self) -> dict[str, Any]:
        """Mathematics: Project the complete immutable semantic identity and current lifecycle state."""
        return {
            "schema": "mailcpu.transferable-execution-claim.v1",
            "parent_request_digest": self.parent_request_digest,
            "child_request_digest": self.child_request_digest,
            "address_digest": self.address_digest,
            "operator_id": self.operator_id,
            "operator_contract_digest": self.operator_contract_digest,
            "operator_spec": self.operator_spec.to_dict(),
            "computational_ground_fingerprint": self.computational_ground_fingerprint,
            "replay_policy": self.replay_policy,
            "assignments": [item.to_dict() for item in self.assignments],
            "status": self.status.value,
            "result_digest": self.result_digest,
            "child_receipt_digest": self.child_receipt_digest,
            "completion_generation": self.completion_generation,
        }

    @property
    def digest(self) -> str:
        """Mathematics: Identify the exact claim version, including assignment history and result completion."""
        return hashlib.sha256(_canonical_json(self._payload())).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: Serialize stable claim identity and all version-specific assignment/result evidence."""
        return {**self._payload(), "claim_id": self.claim_id, "digest": self.digest}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "TransferableExecutionClaim":
        """Mathematics: Restore a claim only after validating its exact schema, assignment sequence, stable id and digest."""
        expected = {
            "schema", "parent_request_digest", "child_request_digest", "address_digest",
            "operator_id", "operator_contract_digest", "operator_spec", "computational_ground_fingerprint",
            "replay_policy", "assignments", "status", "result_digest",
            "child_receipt_digest", "completion_generation", "claim_id", "digest",
        }
        if (
            not isinstance(payload, Mapping)
            or set(payload) != expected
            or payload.get("schema") != "mailcpu.transferable-execution-claim.v1"
            or not isinstance(payload.get("assignments"), list)
            or len(payload.get("assignments", [])) > _MAX_ASSIGNMENTS_PER_CLAIM
            or not isinstance(payload.get("operator_spec"), Mapping)
        ):
            raise TransferableExecutionClaimError("transferable execution claim fields or schema are invalid")
        try:
            operator_spec = OperatorSpec.from_dict(payload["operator_spec"])
            if operator_spec.to_dict() != dict(payload["operator_spec"]):
                raise TransferableExecutionClaimError("claim OperatorSpec is not in its exact canonical field form")
            claim = cls(
                parent_request_digest=payload["parent_request_digest"],
                child_request_digest=payload["child_request_digest"],
                address_digest=payload["address_digest"],
                operator_id=payload["operator_id"],
                operator_contract_digest=payload["operator_contract_digest"],
                operator_spec=operator_spec,
                computational_ground_fingerprint=payload["computational_ground_fingerprint"],
                replay_policy=payload["replay_policy"],
                assignments=tuple(ExecutionClaimAssignment.from_dict(item) for item in payload["assignments"]),
                status=ExecutionClaimStatus(payload["status"]),
                result_digest=payload["result_digest"],
                child_receipt_digest=payload["child_receipt_digest"],
                completion_generation=payload["completion_generation"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, TransferableExecutionClaimError):
                raise
            raise TransferableExecutionClaimError("transferable execution claim contains malformed nested fields") from exc
        if payload["claim_id"] != claim.claim_id or payload["digest"] != claim.digest:
            raise TransferableExecutionClaimError("transferable execution claim identity or digest mismatch")
        return claim


@dataclass(frozen=True)
class ExecutionClaimMerkleStep:
    """Mathematics: One domain-separated sibling commitment in a binary claim-state inclusion path."""

    side: str
    sibling_digest: str

    def __post_init__(self) -> None:
        """Mathematics: Restrict a Merkle path step to its exact left/right position and one SHA-256 sibling."""
        if not isinstance(self.side, str) or self.side not in {"left", "right"}:
            raise TransferableExecutionClaimError("claim Merkle step side must be left or right")
        _digest(self.sibling_digest, "claim Merkle sibling digest")

    def to_dict(self) -> dict[str, str]:
        """Mathematics: Serialize the exact side and sibling hash needed to reconstruct one parent node."""
        return {"side": self.side, "sibling_digest": self.sibling_digest}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ExecutionClaimMerkleStep":
        """Mathematics: Restore one Merkle sibling only from its exact two-field schema."""
        if not isinstance(payload, Mapping) or set(payload) != {"side", "sibling_digest"}:
            raise TransferableExecutionClaimError("claim Merkle step fields are malformed")
        return cls(payload["side"], payload["sibling_digest"])


def _claim_leaf_digest(claim: TransferableExecutionClaim) -> str:
    """Mathematics: Domain-separate a claim leaf from internal tree nodes and bind both stable ID and current claim digest."""
    if not isinstance(claim, TransferableExecutionClaim):
        raise TransferableExecutionClaimError("claim Merkle leaves require typed claims")
    payload = _canonical_json({
        "claim_id": claim.claim_id,
        "claim_digest": claim.digest,
    })
    return hashlib.sha256(b"\x00" + payload).hexdigest()


def _claim_parent_digest(left: str, right: str) -> str:
    """Mathematics: Domain-separate an internal node as H(0x01 || left || right)."""
    return hashlib.sha256(b"\x01" + bytes.fromhex(left) + bytes.fromhex(right)).hexdigest()


def _claim_merkle_paths(
    claims: Mapping[str, TransferableExecutionClaim],
) -> tuple[str, dict[str, tuple[int, tuple[ExecutionClaimMerkleStep, ...]]]]:
    """Mathematics: Build a deterministic sorted binary Merkle root and one O(log n) inclusion path per claim."""
    ordered = tuple(claims[key] for key in sorted(claims))
    if not ordered:
        return hashlib.sha256(b"\x02empty-claim-state").hexdigest(), {}
    levels: list[list[str]] = [[_claim_leaf_digest(item) for item in ordered]]
    while len(levels[-1]) > 1:
        current = levels[-1]
        next_level = [
            _claim_parent_digest(
                current[index],
                current[index + 1] if index + 1 < len(current) else current[index],
            )
            for index in range(0, len(current), 2)
        ]
        levels.append(next_level)
    paths: dict[str, tuple[int, tuple[ExecutionClaimMerkleStep, ...]]] = {}
    for original_index, claim in enumerate(ordered):
        index = original_index
        steps: list[ExecutionClaimMerkleStep] = []
        for level in levels[:-1]:
            if index % 2:
                sibling = level[index - 1]
                side = "left"
            else:
                sibling = level[index + 1] if index + 1 < len(level) else level[index]
                side = "right"
            steps.append(ExecutionClaimMerkleStep(side, sibling))
            index //= 2
        paths[claim.claim_id] = original_index, tuple(steps)
    return levels[-1][0], paths


def _verify_claim_merkle_path(
    claim: TransferableExecutionClaim,
    *,
    claim_index: int,
    claim_count: int,
    steps: tuple[ExecutionClaimMerkleStep, ...],
    expected_root: str,
) -> None:
    """Mathematics: Reconstruct the unique sorted-tree root from one claim leaf, index, finite count and ordered siblings."""
    if type(claim_count) is not int or not 1 <= claim_count <= _MAX_CLAIMS:
        raise TransferableExecutionClaimError("claim inclusion count is outside the finite state bound")
    if type(claim_index) is not int or not 0 <= claim_index < claim_count:
        raise TransferableExecutionClaimError("claim inclusion index is outside its state count")
    _digest(expected_root, "claim Merkle root")
    if len(steps) > 14:
        raise TransferableExecutionClaimError("claim inclusion path exceeds the maximum finite tree depth")
    if any(not isinstance(item, ExecutionClaimMerkleStep) for item in steps):
        raise TransferableExecutionClaimError("claim inclusion path must contain typed Merkle steps")
    current = _claim_leaf_digest(claim)
    index = claim_index
    width = claim_count
    cursor = 0
    while width > 1:
        if cursor >= len(steps):
            raise TransferableExecutionClaimError("claim inclusion path is truncated")
        step = steps[cursor]
        expected_side = "left" if index % 2 else "right"
        if step.side != expected_side:
            raise TransferableExecutionClaimError("claim inclusion path has an invalid sibling orientation")
        if index % 2 == 0 and index + 1 >= width and step.sibling_digest != current:
            raise TransferableExecutionClaimError("claim inclusion path has an invalid odd-leaf duplication")
        current = (
            _claim_parent_digest(step.sibling_digest, current)
            if step.side == "left"
            else _claim_parent_digest(current, step.sibling_digest)
        )
        index //= 2
        width = (width + 1) // 2
        cursor += 1
    if cursor != len(steps) or current != expected_root:
        raise TransferableExecutionClaimError("claim inclusion path does not reach the quorum-anchored state root")


def _state_commitment(
    generation: int,
    predecessor_digest: str,
    claim_count: int,
    claims_root: str,
) -> dict[str, Any]:
    """Mathematics: Commit the sorted claim-set Merkle root, count and lineage edge in a compact manifest payload."""
    return {
        "schema": "mailcpu.transferable-execution-claim-state-root.v1",
        "generation": generation,
        "predecessor_digest": predecessor_digest,
        "claim_count": claim_count,
        "claims_root": claims_root,
    }


def _validate_state_commitment(
    payload: Mapping[str, Any],
    manifest: RecoveryStateManifest,
) -> dict[str, Any]:
    """Mathematics: Require the compact Merkle-root envelope to be the exact bytes committed by the recovery manifest."""
    expected = {"schema", "generation", "predecessor_digest", "claim_count", "claims_root"}
    if not isinstance(payload, Mapping) or set(payload) != expected:
        raise TransferableExecutionClaimError("claim state-root commitment fields are malformed")
    if (
        payload["schema"] != "mailcpu.transferable-execution-claim-state-root.v1"
        or type(payload["generation"]) is not int
        or payload["generation"] != manifest.generation
        or payload["predecessor_digest"] != manifest.predecessor_digest
        or type(payload["claim_count"]) is not int
        or not 0 <= payload["claim_count"] <= _MAX_CLAIMS
    ):
        raise TransferableExecutionClaimError("claim state-root commitment does not match its recovery manifest")
    _digest(payload["claims_root"], "claim Merkle root")
    root_bytes = _canonical_json(dict(payload)) + b"\n"
    if len(root_bytes) > 64 * 1024 or hashlib.sha256(root_bytes).hexdigest() != manifest.state_digest:
        raise TransferableExecutionClaimError("claim state-root bytes do not match their quorum manifest digest")
    return dict(payload)


@dataclass(frozen=True)
class PortableExecutionClaimBundle:
    """Mathematics: Compact claim, Merkle inclusion path, recovery manifest and quorum proof form a portable result-ownership ticket."""

    claim: TransferableExecutionClaim
    manifest: RecoveryStateManifest
    proof: RecoveryLineageProof
    state_commitment: Mapping[str, Any]
    claim_index: int
    merkle_proof: tuple[ExecutionClaimMerkleStep, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.claim, TransferableExecutionClaim):
            raise TransferableExecutionClaimError("claim bundle requires a typed execution claim")
        if not isinstance(self.manifest, RecoveryStateManifest):
            raise TransferableExecutionClaimError("claim bundle requires a typed recovery state manifest")
        if not isinstance(self.proof, RecoveryLineageProof):
            raise TransferableExecutionClaimError("claim bundle requires a typed recovery lineage proof")
        if not isinstance(self.state_commitment, Mapping):
            raise TransferableExecutionClaimError("claim bundle state commitment must be a mapping")
        if len(self.merkle_proof) > 14:
            raise TransferableExecutionClaimError("claim inclusion path exceeds the maximum finite tree depth")
        commitment = _validate_state_commitment(deepcopy(dict(self.state_commitment)), self.manifest)
        steps = tuple(self.merkle_proof)
        _verify_claim_merkle_path(
            self.claim,
            claim_index=self.claim_index,
            claim_count=commitment["claim_count"],
            steps=steps,
            expected_root=commitment["claims_root"],
        )
        if self.manifest.capture_cut != _CAPTURE_CUT:
            raise TransferableExecutionClaimError("claim bundle manifest has the wrong capture cut")
        if (
            self.proof.proposal.slot != self.manifest.generation
            or self.proof.proposal.result_state_digest != self.manifest.digest
            or self.proof.proposal.request_fingerprint != self.manifest.request_fingerprint
            or self.proof.proposal.membership_digest != self.manifest.membership_digest
        ):
            raise TransferableExecutionClaimError("claim bundle quorum proof does not anchor its exact state-root manifest")
        object.__setattr__(self, "state_commitment", commitment)
        object.__setattr__(self, "merkle_proof", steps)

    def _validate_projection(self) -> dict[str, Any]:
        """Mathematics: Recheck mutable root projections, proof orientation, count and claim inclusion against the immutable manifest."""
        commitment = _validate_state_commitment(deepcopy(dict(self.state_commitment)), self.manifest)
        _verify_claim_merkle_path(
            self.claim,
            claim_index=self.claim_index,
            claim_count=commitment["claim_count"],
            steps=tuple(self.merkle_proof),
            expected_root=commitment["claims_root"],
        )
        return commitment

    @property
    def digest(self) -> str:
        """Mathematics: Identify the compact claim ticket, manifest, inclusion path and quorum proof."""
        return hashlib.sha256(_canonical_json(self.to_dict(include_digest=False))).hexdigest()

    def to_dict(self, *, include_digest: bool = True) -> dict[str, Any]:
        """Mathematics: Serialize only the claim leaf, compact quorum root and logarithmic inclusion path."""
        commitment = self._validate_projection()
        payload = {
            "schema": "mailcpu.portable-execution-claim-bundle.v2",
            "claim": self.claim.to_dict(),
            "manifest": self.manifest.snapshot(),
            "proof": self.proof.snapshot(),
            "state_commitment": commitment,
            "claim_index": self.claim_index,
            "merkle_proof": [item.to_dict() for item in self.merkle_proof],
        }
        encoded = _canonical_json(payload)
        if len(encoded) > _MAX_TICKET_BYTES:
            raise TransferableExecutionClaimError("portable claim ticket exceeds its finite byte bound")
        if include_digest:
            payload["digest"] = hashlib.sha256(encoded).hexdigest()
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "PortableExecutionClaimBundle":
        """Mathematics: Restore one compact claim ticket only after its Merkle path, root commitment and quorum proof validate."""
        expected = {
            "schema", "claim", "manifest", "proof", "state_commitment",
            "claim_index", "merkle_proof", "digest",
        }
        if (
            not isinstance(payload, Mapping)
            or set(payload) != expected
            or payload.get("schema") != "mailcpu.portable-execution-claim-bundle.v2"
            or not all(isinstance(payload.get(key), Mapping) for key in (
                "claim", "manifest", "proof", "state_commitment"
            ))
            or not isinstance(payload.get("merkle_proof"), list)
            or len(payload.get("merkle_proof", [])) > 14
        ):
            raise TransferableExecutionClaimError("portable execution claim ticket fields or schema are invalid")
        encoded_ticket = _canonical_json(payload)
        if len(encoded_ticket) > _MAX_TICKET_BYTES:
            raise TransferableExecutionClaimError("portable claim ticket exceeds its finite byte bound")
        projection = {key: payload[key] for key in (
            "schema", "claim", "manifest", "proof", "state_commitment",
            "claim_index", "merkle_proof",
        )}
        if payload["digest"] != hashlib.sha256(_canonical_json(projection)).hexdigest():
            raise TransferableExecutionClaimError("portable execution claim ticket digest mismatch")
        try:
            return cls(
                TransferableExecutionClaim.from_dict(payload["claim"]),
                RecoveryStateManifest.from_snapshot(payload["manifest"]),
                RecoveryLineageProof.from_snapshot(payload["proof"]),
                payload["state_commitment"],
                payload["claim_index"],
                tuple(ExecutionClaimMerkleStep.from_dict(item) for item in payload["merkle_proof"]),
            )
        except (KeyError, TypeError, ValueError, RecoveryLineageError) as exc:
            if isinstance(exc, TransferableExecutionClaimError):
                raise
            raise TransferableExecutionClaimError("portable execution claim ticket contains invalid proof material") from exc

    def verify_current(self, coordinator: RecoveryLineageCoordinator) -> None:
        """Mathematics: Admit the ticket only if live quorum high-water still matches its root manifest and exact commit proof."""
        if not isinstance(coordinator, RecoveryLineageCoordinator):
            raise TransferableExecutionClaimError("claim verification requires a RecoveryLineageCoordinator")
        self._validate_projection()
        try:
            proof = coordinator.verify_state(self.manifest)
        except RecoveryLineageError as exc:
            raise TransferableExecutionClaimError(f"portable execution claim is not current: {exc}") from exc
        if proof.snapshot() != self.proof.snapshot():
            raise TransferableExecutionClaimError("live quorum proof differs from the portable claim proof")

    def verify_for_target(
        self,
        coordinator: RecoveryLineageCoordinator,
        *,
        parent_request_digest: str,
        child_request_digest: str,
        address_digest: str,
        operator_spec: OperatorSpec,
        computational_ground_fingerprint: str,
        owner_peer_id: str,
        owner_host_id: str,
        implementation_fingerprint: str,
    ) -> None:
        """Mathematics: Verify live quorum ownership and exact typed semantic/address/implementation target binding."""
        self.verify_current(coordinator)
        if not isinstance(operator_spec, OperatorSpec) or not operator_spec.replay_safe:
            raise TransferableExecutionClaimError("target must provide a typed deterministic pure OperatorSpec")
        claim = self.claim
        assignment = claim.current_assignment
        expected = (
            (claim.parent_request_digest, _digest(parent_request_digest, "parent request digest")),
            (claim.child_request_digest, _digest(child_request_digest, "child request digest")),
            (claim.address_digest, _digest(address_digest, "ComputationalAddress digest")),
            (claim.operator_spec.to_dict(), operator_spec.to_dict()),
            (claim.computational_ground_fingerprint, _digest(computational_ground_fingerprint, "Computational Ground fingerprint")),
            (assignment.owner_peer_id, _fabric_id(owner_peer_id, "target peer id")),
            (assignment.owner_host_id, _fabric_id(owner_host_id, "target host id")),
            (assignment.implementation_fingerprint, _digest(implementation_fingerprint, "target implementation fingerprint")),
        )
        if any(actual != supplied for actual, supplied in expected):
            raise TransferableExecutionClaimError("portable execution claim does not authorize this exact target workload and implementation")
        if claim.status is not ExecutionClaimStatus.ASSIGNED:
            raise TransferableExecutionClaimError("completed execution claim cannot authorize a new computation")


class TransferableExecutionClaimStore:
    """Mathematics: Owner-side immutable claim-state generations, each admitted by one fixed-membership RecoveryLineage quorum."""

    def __init__(self, directory: str | os.PathLike[str], coordinator: RecoveryLineageCoordinator) -> None:
        """Mathematics: Bind one durable claim artifact directory to the existing fixed-membership recovery coordinator."""
        if not isinstance(coordinator, RecoveryLineageCoordinator):
            raise TransferableExecutionClaimError("claim store requires a RecoveryLineageCoordinator")
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.coordinator = coordinator
        self._lock = threading.RLock()
        self._lock_path = self.directory / ".claims.lock"

    @contextmanager
    def _locked(self) -> Iterator[None]:
        """Mathematics: Serialize local writers across threads/processes while quorum slots serialize distributed history."""
        with self._lock:
            self._lock_path.touch(exist_ok=True)
            with self._lock_path.open("a+b") as stream:
                stream.seek(0, os.SEEK_END)
                if stream.tell() == 0:
                    stream.write(b"0")
                    stream.flush()
                stream.seek(0)
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
                    raise TransferableExecutionClaimError("platform does not provide cross-process claim-store locking")
                if hasattr(locking_module, "locking"):
                    locking_module.locking(stream.fileno(), locking_module.LK_LOCK, 1)
                else:
                    locking_module.flock(stream.fileno(), locking_module.LOCK_EX)
                try:
                    yield
                finally:
                    if hasattr(locking_module, "locking"):
                        stream.seek(0)
                        locking_module.locking(stream.fileno(), locking_module.LK_UNLCK, 1)
                    else:
                        locking_module.flock(stream.fileno(), locking_module.LOCK_UN)

    def _generation_directory(self, generation: int) -> Path:
        """Mathematics: Map a positive quorum generation to one immutable claim-state directory."""
        _positive(generation, "claim state generation")
        return self.directory / f"generation-{generation:020d}"

    def _persist_generation(
        self,
        generation: int,
        state_bytes: bytes,
        state_root_bytes: bytes,
        manifest: RecoveryStateManifest,
    ) -> Path:
        """Mathematics: Fsync the full owner snapshot, compact state root and manifest before immutable directory publication."""
        target = self._generation_directory(generation)
        expected = {
            "claims.json": state_bytes,
            "state-root.json": state_root_bytes,
            "manifest.json": _canonical_json(manifest.snapshot()) + b"\n",
        }
        if target.exists():
            try:
                actual = {
                    name: _read_bounded(target / name, maximum, f"existing {name}")
                    for name, maximum in (
                        ("claims.json", _MAX_STATE_BYTES),
                        ("state-root.json", 64 * 1024),
                        ("manifest.json", 64 * 1024),
                    )
                }
            except (OSError, TransferableExecutionClaimError) as exc:
                raise TransferableExecutionClaimError("existing claim generation is incomplete") from exc
            if actual != expected:
                raise TransferableExecutionClaimError(
                    f"claim generation {generation} already contains different bytes"
                )
            return target
        staging = Path(tempfile.mkdtemp(prefix=f".generation-{generation:020d}.", dir=str(self.directory)))
        try:
            for name, payload in expected.items():
                path = staging / name
                with path.open("xb") as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
            _fsync_directory(staging)
            try:
                os.rename(staging, target)
            except FileExistsError:
                actual = {
                    name: _read_bounded(target / name, maximum, f"concurrent {name}")
                    for name, maximum in (
                        ("claims.json", _MAX_STATE_BYTES),
                        ("state-root.json", 64 * 1024),
                        ("manifest.json", 64 * 1024),
                    )
                }
                if actual != expected:
                    raise TransferableExecutionClaimError(
                        f"claim generation {generation} was concurrently published with different bytes"
                    )
            _fsync_directory(self.directory)
            return target
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)

    @staticmethod
    def _empty_snapshot() -> dict[str, Any]:
        """Mathematics: Return the unique empty claim registry at the configured lineage genesis."""
        return {"schema": _SCHEMA, "claims": []}

    @staticmethod
    def _claims_from_snapshot(snapshot: Mapping[str, Any]) -> dict[str, TransferableExecutionClaim]:
        """Mathematics: Reconstruct a unique claim-id map from one canonical sorted ledger state."""
        if (
            not isinstance(snapshot, Mapping)
            or set(snapshot) != {"schema", "claims"}
            or snapshot.get("schema") != _SCHEMA
            or not isinstance(snapshot.get("claims"), list)
            or len(snapshot.get("claims", [])) > _MAX_CLAIMS
        ):
            raise TransferableExecutionClaimError("claim ledger snapshot fields or schema are invalid")
        claims = tuple(TransferableExecutionClaim.from_dict(item) for item in snapshot["claims"])
        identifiers = tuple(item.claim_id for item in claims)
        if identifiers != tuple(sorted(set(identifiers))):
            raise TransferableExecutionClaimError("claim ledger entries must be unique and sorted by stable claim id")
        return {item.claim_id: item for item in claims}

    def _load_latest_locked(
        self,
    ) -> tuple[int, str, dict[str, Any], dict[str, TransferableExecutionClaim], RecoveryStateManifest | None, RecoveryLineageProof | None]:
        """Mathematics: Verify full owner state against its compact Merkle root and the exact durable quorum high-water."""
        try:
            proof = self.coordinator.latest_proof()
            generation, predecessor = self.coordinator.high_water()
        except RecoveryLineageError as exc:
            raise TransferableExecutionClaimError(f"cannot read execution claim quorum high-water: {exc}") from exc
        if proof is None:
            if generation != 0:
                raise TransferableExecutionClaimError("claim authority has a generation without a quorum proof")
            snapshot = self._empty_snapshot()
            return generation, predecessor, snapshot, {}, None, None
        directory = self._generation_directory(generation)
        try:
            state_bytes = _read_bounded(directory / "claims.json", _MAX_STATE_BYTES, "claim state snapshot")
            root_bytes = _read_bounded(directory / "state-root.json", 64 * 1024, "claim state-root commitment")
            manifest_bytes = _read_bounded(directory / "manifest.json", 64 * 1024, "claim state manifest")
            snapshot = json.loads(state_bytes.decode("utf-8"))
            raw_root = json.loads(root_bytes.decode("utf-8"))
            raw_manifest = json.loads(manifest_bytes.decode("utf-8"))
            manifest = RecoveryStateManifest.from_snapshot(raw_manifest)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecoveryLineageError) as exc:
            raise TransferableExecutionClaimError(f"claim generation {generation} is unavailable or malformed") from exc
        if (
            manifest.generation != generation
            or manifest.capture_cut != _CAPTURE_CUT
            or manifest.digest != proof.proposal.result_state_digest
            or manifest.membership_digest != self.coordinator.membership.digest
            or manifest_bytes != _canonical_json(manifest.snapshot()) + b"\n"
            or state_bytes != _canonical_json(snapshot) + b"\n"
            or root_bytes != _canonical_json(raw_root) + b"\n"
        ):
            raise TransferableExecutionClaimError("claim state, root or manifest does not match the quorum high-water")
        try:
            state_root = _validate_state_commitment(raw_root, manifest)
            claims = self._claims_from_snapshot(snapshot)
            claims_root, _paths = _claim_merkle_paths(claims)
            if (
                state_root["claim_count"] != len(claims)
                or state_root["claims_root"] != claims_root
            ):
                raise TransferableExecutionClaimError("full claim snapshot does not reproduce its committed Merkle root")
            manifest.verify_payload(root_bytes)
            verified = self.coordinator.verify_state(manifest)
        except RecoveryLineageError as exc:
            raise TransferableExecutionClaimError(f"claim generation {generation} failed quorum verification") from exc
        if verified.snapshot() != proof.snapshot():
            raise TransferableExecutionClaimError("claim authority proof changed during state verification")
        return generation, manifest.digest, snapshot, claims, manifest, proof

    def _bundle_for_claim(
        self,
        claim_id: str,
        claims: Mapping[str, TransferableExecutionClaim],
        manifest: RecoveryStateManifest,
        proof: RecoveryLineageProof,
    ) -> PortableExecutionClaimBundle:
        """Mathematics: Project one claim from the full owner state into its compact quorum-bound Merkle inclusion ticket."""
        claim = claims.get(claim_id)
        if claim is None:
            raise TransferableExecutionClaimError("requested claim is absent from the current committed state")
        root, paths = _claim_merkle_paths(claims)
        index, inclusion = paths[claim_id]
        commitment = _state_commitment(
            manifest.generation,
            manifest.predecessor_digest,
            len(claims),
            root,
        )
        return PortableExecutionClaimBundle(
            claim,
            manifest,
            proof,
            commitment,
            index,
            inclusion,
        )

    def _resume_pending_locked(self) -> bool:
        """Mathematics: Finish the exact persisted next-generation proposal after validating its full state against the compact root."""
        generation, predecessor, _snapshot, _claims, _manifest, _proof = self._load_latest_locked()
        next_generation = generation + 1
        target = self._generation_directory(next_generation)
        if not target.exists():
            return False
        try:
            state_bytes = _read_bounded(target / "claims.json", _MAX_STATE_BYTES, "pending claim state")
            root_bytes = _read_bounded(target / "state-root.json", 64 * 1024, "pending claim state root")
            manifest_bytes = _read_bounded(target / "manifest.json", 64 * 1024, "pending claim manifest")
            snapshot = json.loads(state_bytes.decode("utf-8"))
            raw_root = json.loads(root_bytes.decode("utf-8"))
            manifest = RecoveryStateManifest.from_snapshot(json.loads(manifest_bytes.decode("utf-8")))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecoveryLineageError) as exc:
            raise TransferableExecutionClaimError(
                f"pending claim generation {next_generation} is unavailable or malformed"
            ) from exc
        if (
            manifest.generation != next_generation
            or manifest.predecessor_digest != predecessor
            or manifest.membership_digest != self.coordinator.membership.digest
            or manifest.capture_cut != _CAPTURE_CUT
            or manifest_bytes != _canonical_json(manifest.snapshot()) + b"\n"
            or state_bytes != _canonical_json(snapshot) + b"\n"
            or root_bytes != _canonical_json(raw_root) + b"\n"
        ):
            raise TransferableExecutionClaimError("pending claim generation does not extend the exact current quorum state")
        claims = self._claims_from_snapshot(snapshot)
        state_root = _validate_state_commitment(raw_root, manifest)
        claims_root, _paths = _claim_merkle_paths(claims)
        if state_root["claim_count"] != len(claims) or state_root["claims_root"] != claims_root:
            raise TransferableExecutionClaimError("pending full claim state does not reproduce its committed Merkle root")
        try:
            manifest.verify_payload(root_bytes)
            proof = self.coordinator.seal(manifest)
            verified = self.coordinator.verify_state(manifest)
        except RecoveryLineageError as exc:
            raise TransferableExecutionClaimError(
                f"pending claim generation {next_generation} cannot yet reach a quorum: {exc}"
            ) from exc
        if proof.snapshot() != verified.snapshot():
            raise TransferableExecutionClaimError("resumed claim generation returned inconsistent quorum proofs")
        return True

    def resume_pending(self) -> bool:
        """Mathematics: Recover one exact fsynced but not yet quorum-anchored next generation, preserving its original proposal."""
        with self._locked():
            return self._resume_pending_locked()

    def _publish_locked(
        self,
        claims: Mapping[str, TransferableExecutionClaim],
        previous_generation: int,
        predecessor_digest: str,
        target_claim_id: str,
    ) -> PortableExecutionClaimBundle:
        """Mathematics: Publish full owner state plus a compact Merkle commitment before strict-majority quorum sealing."""
        if len(claims) > _MAX_CLAIMS:
            raise TransferableExecutionClaimError("claim ledger exceeds the finite claim-count bound")
        generation = previous_generation + 1
        snapshot = {
            "schema": _SCHEMA,
            "claims": [claims[key].to_dict() for key in sorted(claims)],
        }
        state_bytes = _canonical_json(snapshot) + b"\n"
        if len(state_bytes) > _MAX_STATE_BYTES:
            raise TransferableExecutionClaimError("claim ledger state exceeds its finite serialized-byte bound")
        claims_root, _paths = _claim_merkle_paths(claims)
        commitment = _state_commitment(
            generation,
            predecessor_digest,
            len(claims),
            claims_root,
        )
        root_bytes = _canonical_json(commitment) + b"\n"
        if len(root_bytes) > 64 * 1024:
            raise TransferableExecutionClaimError("claim state-root commitment exceeds its finite byte bound")
        membership = self.coordinator.membership
        manifest = RecoveryStateManifest(
            machine_id=membership.system_id,
            incarnation=membership.incarnation,
            owner_id=membership.owner_id,
            owner_term=membership.owner_term,
            membership_digest=membership.digest,
            generation=generation,
            predecessor_digest=predecessor_digest,
            state_digest=hashlib.sha256(root_bytes).hexdigest(),
            capture_cut=_CAPTURE_CUT,
        )
        self._persist_generation(generation, state_bytes, root_bytes, manifest)
        try:
            proof = self.coordinator.seal(manifest)
        except RecoveryLineageError as exc:
            raise TransferableExecutionClaimError(
                f"claim generation {generation} is durable locally but lacks a quorum commit: {exc}"
            ) from exc
        try:
            verified = self.coordinator.verify_state(manifest)
        except RecoveryLineageError as exc:
            raise TransferableExecutionClaimError(
                f"claim generation {generation} committed but failed live quorum verification: {exc}"
            ) from exc
        if proof.snapshot() != verified.snapshot():
            raise TransferableExecutionClaimError("claim commit proof differs from the live verified proof")
        return self._bundle_for_claim(target_claim_id, claims, manifest, proof)

    def create(
        self,
        *,
        parent_request_digest: str,
        child_request_digest: str,
        address_digest: str,
        operator_spec: OperatorSpec,
        computational_ground_fingerprint: str,
        owner_peer_id: str,
        owner_host_id: str,
        implementation_fingerprint: str,
        replay_policy: str = REPLAY_POLICY_PURE,
    ) -> PortableExecutionClaimBundle:
        """Mathematics: Create or return one exact assignment through the shared batch-generation authority."""
        return self.create_many(({
            "parent_request_digest": parent_request_digest,
            "child_request_digest": child_request_digest,
            "address_digest": address_digest,
            "operator_spec": operator_spec,
            "computational_ground_fingerprint": computational_ground_fingerprint,
            "owner_peer_id": owner_peer_id,
            "owner_host_id": owner_host_id,
            "implementation_fingerprint": implementation_fingerprint,
            "replay_policy": replay_policy,
        },))[0]

    def create_many(
        self,
        specifications: Sequence[Mapping[str, Any]],
    ) -> tuple[PortableExecutionClaimBundle, ...]:
        """Mathematics: Create a bounded set of child assignments in one quorum generation so every returned ticket shares the same live root."""
        if not isinstance(specifications, (list, tuple)) or not 1 <= len(specifications) <= 64:
            raise TransferableExecutionClaimError("claim batch must contain between one and 64 child specifications")
        required = {
            "parent_request_digest",
            "child_request_digest",
            "address_digest",
            "operator_spec",
            "computational_ground_fingerprint",
            "owner_peer_id",
            "owner_host_id",
            "implementation_fingerprint",
        }
        allowed = required | {"replay_policy"}
        candidates: list[tuple[TransferableExecutionClaim, ExecutionClaimAssignment]] = []
        for index, specification in enumerate(specifications):
            if not isinstance(specification, Mapping) or set(specification) not in (required, allowed):
                raise TransferableExecutionClaimError(
                    f"claim batch item {index} fields do not match the exact claim specification schema"
                )
            replay_policy = specification.get("replay_policy", REPLAY_POLICY_PURE)
            if replay_policy != REPLAY_POLICY_PURE:
                raise TransferableExecutionClaimError("only pure replay-safe operations are currently transferable")
            operator_spec = specification["operator_spec"]
            if not isinstance(operator_spec, OperatorSpec) or not operator_spec.replay_safe:
                raise TransferableExecutionClaimError(
                    "only a typed deterministic pure OperatorSpec may receive a transferable claim"
                )
            assignment = ExecutionClaimAssignment(
                1,
                specification["owner_peer_id"],
                specification["owner_host_id"],
                specification["implementation_fingerprint"],
                1,
            )
            candidate = TransferableExecutionClaim(
                specification["parent_request_digest"],
                specification["child_request_digest"],
                specification["address_digest"],
                operator_spec.operator_id,
                operator_spec.digest,
                operator_spec,
                specification["computational_ground_fingerprint"],
                replay_policy,
                (assignment,),
            )
            candidates.append((candidate, assignment))
        identifiers = tuple(item.claim_id for item, _assignment in candidates)
        if len(identifiers) != len(set(identifiers)):
            raise TransferableExecutionClaimError("claim batch contains duplicate semantic child identities")

        with self._locked():
            self._resume_pending_locked()
            generation, predecessor, _snapshot, claims, manifest, proof = self._load_latest_locked()
            next_generation = generation + 1
            changed = False
            for candidate, initial_assignment in candidates:
                existing = claims.get(candidate.claim_id)
                if existing is not None:
                    if existing.status is not ExecutionClaimStatus.ASSIGNED:
                        raise TransferableExecutionClaimError(
                            "completed execution claim cannot be reissued for computation"
                        )
                    current = existing.current_assignment
                    if (
                        current.owner_peer_id,
                        current.owner_host_id,
                        current.implementation_fingerprint,
                        existing.operator_spec.to_dict(),
                    ) != (
                        initial_assignment.owner_peer_id,
                        initial_assignment.owner_host_id,
                        initial_assignment.implementation_fingerprint,
                        candidate.operator_spec.to_dict(),
                    ):
                        raise TransferableExecutionClaimError(
                            "existing execution claim is assigned to another host; an explicit quorum reassignment is required"
                        )
                    continue

                assignment = ExecutionClaimAssignment(
                    1,
                    initial_assignment.owner_peer_id,
                    initial_assignment.owner_host_id,
                    initial_assignment.implementation_fingerprint,
                    next_generation,
                )
                claim = TransferableExecutionClaim(
                    candidate.parent_request_digest,
                    candidate.child_request_digest,
                    candidate.address_digest,
                    candidate.operator_id,
                    candidate.operator_contract_digest,
                    candidate.operator_spec,
                    candidate.computational_ground_fingerprint,
                    candidate.replay_policy,
                    (assignment,),
                )
                claims[claim.claim_id] = claim
                changed = True

            if changed:
                self._publish_locked(
                    claims,
                    generation,
                    predecessor,
                    candidates[0][0].claim_id,
                )
                _generation, _predecessor, _snapshot, claims, manifest, proof = self._load_latest_locked()
            if manifest is None or proof is None:
                raise TransferableExecutionClaimError("claim batch could not establish one committed state root")
            return tuple(
                self._bundle_for_claim(candidate.claim_id, claims, manifest, proof)
                for candidate, _assignment in candidates
            )

    def get_many(self, claim_ids: Sequence[str]) -> tuple[PortableExecutionClaimBundle, ...]:
        """Mathematics: Refresh a bounded ordered set of tickets from one exact distributed-quorum high-water generation."""
        if not isinstance(claim_ids, (list, tuple)) or not 1 <= len(claim_ids) <= 64:
            raise TransferableExecutionClaimError("claim status batch must contain between one and 64 identifiers")
        identifiers = tuple(_digest(item, "claim id") for item in claim_ids)
        if len(identifiers) != len(set(identifiers)):
            raise TransferableExecutionClaimError("claim status batch identifiers must be unique")
        with self._locked():
            self._resume_pending_locked()
            _generation, _predecessor, _snapshot, claims, manifest, proof = self._load_latest_locked()
            if manifest is None or proof is None:
                raise TransferableExecutionClaimError("claim status is unavailable before the first quorum-anchored generation")
            return tuple(
                self._bundle_for_claim(identifier, claims, manifest, proof)
                for identifier in identifiers
            )

    def get(self, claim_id: str) -> PortableExecutionClaimBundle:
        """Mathematics: Return the current claim and full portable quorum proof from the latest anchored state."""
        _digest(claim_id, "claim id")
        with self._locked():
            self._resume_pending_locked()
            _generation, _predecessor, snapshot, claims, manifest, proof = self._load_latest_locked()
            claim = claims.get(claim_id)
            if claim is None or manifest is None or proof is None:
                raise TransferableExecutionClaimError("execution claim does not exist in the quorum ledger")
            return self._bundle_for_claim(claim_id, claims, manifest, proof)

    def reassign(
        self,
        claim_id: str,
        *,
        expected_epoch: int,
        owner_peer_id: str,
        owner_host_id: str,
        implementation_fingerprint: str,
        failure_evidence_digest: str,
    ) -> PortableExecutionClaimBundle:
        """Mathematics: Revoke one prior result-acceptance epoch using the atomic batch reassignment transition."""
        return self.reassign_many(({
            "claim_id": claim_id,
            "expected_epoch": expected_epoch,
            "owner_peer_id": owner_peer_id,
            "owner_host_id": owner_host_id,
            "implementation_fingerprint": implementation_fingerprint,
            "failure_evidence_digest": failure_evidence_digest,
        },))[0]

    def reassign_many(
        self,
        reassignments: Sequence[Mapping[str, Any]],
    ) -> tuple[PortableExecutionClaimBundle, ...]:
        """Mathematics: Atomically revoke and replace a bounded set of failed child assignments in one quorum generation."""
        if not isinstance(reassignments, (list, tuple)) or not 1 <= len(reassignments) <= 64:
            raise TransferableExecutionClaimError("claim reassignment batch must contain between one and 64 children")
        expected_fields = {
            "claim_id",
            "expected_epoch",
            "owner_peer_id",
            "owner_host_id",
            "implementation_fingerprint",
            "failure_evidence_digest",
        }
        normalized: list[dict[str, Any]] = []
        for index, item in enumerate(reassignments):
            if not isinstance(item, Mapping) or set(item) != expected_fields:
                raise TransferableExecutionClaimError(
                    f"claim reassignment item {index} fields do not match the exact reassignment schema"
                )
            normalized.append({
                "claim_id": _digest(item["claim_id"], "claim id"),
                "expected_epoch": _positive(item["expected_epoch"], "expected assignment epoch"),
                "owner_peer_id": _fabric_id(item["owner_peer_id"], "new assignment peer id"),
                "owner_host_id": _fabric_id(item["owner_host_id"], "new assignment host id"),
                "implementation_fingerprint": _digest(item["implementation_fingerprint"], "new implementation fingerprint"),
                "failure_evidence_digest": _digest(item["failure_evidence_digest"], "reassignment evidence digest"),
            })
        claim_ids = tuple(item["claim_id"] for item in normalized)
        if len(claim_ids) != len(set(claim_ids)):
            raise TransferableExecutionClaimError("claim reassignment batch identifiers must be unique")
        target_hosts = tuple((item["owner_peer_id"], item["owner_host_id"]) for item in normalized)
        if len(target_hosts) != len(set(target_hosts)):
            raise TransferableExecutionClaimError("claim reassignment batch cannot assign two children to one logical Host")

        with self._locked():
            self._resume_pending_locked()
            generation, predecessor, _snapshot, claims, manifest, proof = self._load_latest_locked()
            if manifest is None or proof is None:
                raise TransferableExecutionClaimError("claim reassignment requires an existing quorum-anchored assignment generation")

            selected: list[TransferableExecutionClaim] = []
            already_reassigned = 0
            for item in normalized:
                current = claims.get(item["claim_id"])
                if current is None:
                    raise TransferableExecutionClaimError("claim reassignment batch references an unknown claim")
                if current.status is ExecutionClaimStatus.COMPLETED:
                    raise TransferableExecutionClaimError("completed execution claim cannot be reassigned")
                latest = current.current_assignment
                target = (
                    item["owner_peer_id"],
                    item["owner_host_id"],
                    item["implementation_fingerprint"],
                    item["failure_evidence_digest"],
                )
                actual_retry = (
                    latest.owner_peer_id,
                    latest.owner_host_id,
                    latest.implementation_fingerprint,
                    latest.failure_evidence_digest,
                )
                if latest.epoch == item["expected_epoch"] + 1 and actual_retry == target:
                    already_reassigned += 1
                elif latest.epoch != item["expected_epoch"]:
                    raise TransferableExecutionClaimError(
                        "stale assignment epoch cannot reassign the current execution claim"
                    )
                elif (latest.owner_peer_id, latest.owner_host_id) == (
                    item["owner_peer_id"], item["owner_host_id"]
                ):
                    raise TransferableExecutionClaimError("reassignment must target a different logical Host")
                selected.append(current)

            if already_reassigned not in (0, len(selected)):
                raise TransferableExecutionClaimError(
                    "claim reassignment retry cannot mix already-reassigned and still-assigned children"
                )
            if already_reassigned == len(selected):
                return tuple(
                    self._bundle_for_claim(item["claim_id"], claims, manifest, proof)
                    for item in normalized
                )

            next_generation = generation + 1
            for item, current in zip(normalized, selected):
                assignment = ExecutionClaimAssignment(
                    item["expected_epoch"] + 1,
                    item["owner_peer_id"],
                    item["owner_host_id"],
                    item["implementation_fingerprint"],
                    next_generation,
                    item["failure_evidence_digest"],
                )
                updated = TransferableExecutionClaim(
                    current.parent_request_digest,
                    current.child_request_digest,
                    current.address_digest,
                    current.operator_id,
                    current.operator_contract_digest,
                    current.operator_spec,
                    current.computational_ground_fingerprint,
                    current.replay_policy,
                    current.assignments + (assignment,),
                )
                claims[current.claim_id] = updated

            self._publish_locked(claims, generation, predecessor, claim_ids[0])
            _generation, _predecessor, _snapshot, claims, manifest, proof = self._load_latest_locked()
            if manifest is None or proof is None:
                raise TransferableExecutionClaimError("claim reassignment batch did not retain a quorum-committed state")
            return tuple(
                self._bundle_for_claim(identifier, claims, manifest, proof)
                for identifier in claim_ids
            )

    def complete(
        self,
        claim_id: str,
        *,
        expected_epoch: int,
        owner_peer_id: str,
        owner_host_id: str,
        implementation_fingerprint: str,
        result_digest: str,
        child_receipt_digest: str,
    ) -> PortableExecutionClaimBundle:
        """Mathematics: Commit one result through the same atomic batch completion path used by a parent frontier."""
        return self.complete_many(({
            "claim_id": claim_id,
            "expected_epoch": expected_epoch,
            "owner_peer_id": owner_peer_id,
            "owner_host_id": owner_host_id,
            "implementation_fingerprint": implementation_fingerprint,
            "result_digest": result_digest,
            "child_receipt_digest": child_receipt_digest,
        },))[0]

    def complete_many(
        self,
        completions: Sequence[Mapping[str, Any]],
    ) -> tuple[PortableExecutionClaimBundle, ...]:
        """Mathematics: Atomically complete one bounded set of child claims in one quorum generation or publish none."""
        if not isinstance(completions, (list, tuple)) or not 1 <= len(completions) <= 64:
            raise TransferableExecutionClaimError("claim completion batch must contain between one and 64 children")
        expected_fields = {
            "claim_id",
            "expected_epoch",
            "owner_peer_id",
            "owner_host_id",
            "implementation_fingerprint",
            "result_digest",
            "child_receipt_digest",
        }
        normalized: list[dict[str, Any]] = []
        for index, completion in enumerate(completions):
            if not isinstance(completion, Mapping) or set(completion) != expected_fields:
                raise TransferableExecutionClaimError(
                    f"claim completion item {index} fields do not match the exact completion schema"
                )
            normalized.append({
                "claim_id": _digest(completion["claim_id"], "claim id"),
                "expected_epoch": _positive(completion["expected_epoch"], "expected assignment epoch"),
                "owner_peer_id": _fabric_id(completion["owner_peer_id"], "completion peer id"),
                "owner_host_id": _fabric_id(completion["owner_host_id"], "completion host id"),
                "implementation_fingerprint": _digest(completion["implementation_fingerprint"], "completion implementation fingerprint"),
                "result_digest": _digest(completion["result_digest"], "result digest"),
                "child_receipt_digest": _digest(completion["child_receipt_digest"], "child receipt digest"),
            })
        claim_ids = tuple(item["claim_id"] for item in normalized)
        if len(claim_ids) != len(set(claim_ids)):
            raise TransferableExecutionClaimError("claim completion batch identifiers must be unique")

        with self._locked():
            self._resume_pending_locked()
            generation, predecessor, _snapshot, claims, manifest, proof = self._load_latest_locked()
            if manifest is None or proof is None:
                raise TransferableExecutionClaimError("claim completion requires an existing quorum-anchored assignment generation")
            selected: list[TransferableExecutionClaim] = []
            completed_count = 0
            for item in normalized:
                current = claims.get(item["claim_id"])
                if current is None:
                    raise TransferableExecutionClaimError("claim completion batch references an unknown claim")
                assignment = current.current_assignment
                actor = (
                    item["expected_epoch"],
                    item["owner_peer_id"],
                    item["owner_host_id"],
                    item["implementation_fingerprint"],
                )
                actual = (
                    assignment.epoch,
                    assignment.owner_peer_id,
                    assignment.owner_host_id,
                    assignment.implementation_fingerprint,
                )
                if actor != actual:
                    raise TransferableExecutionClaimError(
                        "claim completion producer is not the exact current assignment epoch/Host/implementation"
                    )
                if current.status is ExecutionClaimStatus.COMPLETED:
                    if (
                        current.result_digest != item["result_digest"]
                        or current.child_receipt_digest != item["child_receipt_digest"]
                    ):
                        raise TransferableExecutionClaimError(
                            "completed claim batch retry contains a conflicting result or child receipt"
                        )
                    completed_count += 1
                selected.append(current)

            if completed_count not in (0, len(selected)):
                raise TransferableExecutionClaimError(
                    "claim completion batch cannot mix already-completed and newly-assigned children"
                )
            if completed_count == len(selected):
                return tuple(
                    self._bundle_for_claim(item["claim_id"], claims, manifest, proof)
                    for item in normalized
                )

            next_generation = generation + 1
            for item, current in zip(normalized, selected):
                updated = TransferableExecutionClaim(
                    current.parent_request_digest,
                    current.child_request_digest,
                    current.address_digest,
                    current.operator_id,
                    current.operator_contract_digest,
                    current.operator_spec,
                    current.computational_ground_fingerprint,
                    current.replay_policy,
                    current.assignments,
                    ExecutionClaimStatus.COMPLETED,
                    item["result_digest"],
                    item["child_receipt_digest"],
                    next_generation,
                )
                claims[current.claim_id] = updated

            self._publish_locked(
                claims,
                generation,
                predecessor,
                claim_ids[0],
            )
            _generation, _predecessor, _snapshot, claims, manifest, proof = self._load_latest_locked()
            if manifest is None or proof is None:
                raise TransferableExecutionClaimError("claim completion batch did not retain a quorum-committed state")
            return tuple(
                self._bundle_for_claim(identifier, claims, manifest, proof)
                for identifier in claim_ids
            )

    @property
    def high_water(self) -> tuple[int, str]:
        """Mathematics: Expose the highest recovery generation and claim-state digest supported by the configured quorum."""
        try:
            return self.coordinator.high_water()
        except RecoveryLineageError as exc:
            raise TransferableExecutionClaimError(f"cannot read claim authority high-water: {exc}") from exc
