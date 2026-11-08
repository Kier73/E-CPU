"""Mathematics: Execute one declared pure state transition against a quorum-verified session snapshot.

The adapter joins domain-owned interpretation with M3 persistence. It does not
interpret state bytes itself, import a particular runtime, or commit external
side effects. A backend receives a verified snapshot projection and must return
the exact successor bytes for publication through the existing session CAS.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from typing import Protocol

from .computational_session import (
    ComputationalSessionConflictError,
    ComputationalSessionError,
    ComputationalSessionSnapshot,
    ComputationalSessionStore,
)

_LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,255}\Z")
_HEX_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_INPUT_SCHEMA = "mailcpu.computational-transition-input.v1"


class ComputationalTransitionError(ComputationalSessionError):
    """Mathematics: A declared transition contract or local state-transform backend is invalid."""


def _label(value: object, name: str) -> str:
    """Mathematics: Require one bounded, path-independent transition identity."""
    if not isinstance(value, str) or _LABEL.fullmatch(value) is None:
        raise ComputationalTransitionError(f"{name} must be a non-empty bounded identifier")
    return value


def _digest(value: object, name: str) -> str:
    """Mathematics: Require one exact lowercase SHA-256 identity."""
    if not isinstance(value, str) or _HEX_DIGEST.fullmatch(value) is None:
        raise ComputationalTransitionError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _positive_integer(value: object, name: str) -> int:
    """Mathematics: Require a positive built-in integer without accepting Boolean values."""
    if type(value) is not int or value <= 0:
        raise ComputationalTransitionError(f"{name} must be a positive integer")
    return value


def _canonical_bytes(value: object) -> bytes:
    """Mathematics: Encode a finite transition commitment as deterministic UTF-8 JSON."""
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ComputationalTransitionError("transition commitment is not canonical JSON") from exc


def _sha256(data: bytes) -> str:
    """Mathematics: Return the SHA-256 identity of an exact byte sequence."""
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True, slots=True)
class ComputationalTransitionContract:
    """Immutable declaration of the state schema, interpretation, backend, and resource envelope."""

    transition_id: str
    state_schema_id: str
    input_schema_id: str
    interpretation_fingerprint: str
    backend_fingerprint: str
    max_input_bytes: int
    max_state_bytes: int
    deterministic: bool = True
    effect_mode: str = "pure"

    def __post_init__(self) -> None:
        """Validate transition identity, all referenced fingerprints, bounds, and declared effect class."""
        _label(self.transition_id, "transition_id")
        _label(self.state_schema_id, "state_schema_id")
        _label(self.input_schema_id, "input_schema_id")
        _digest(self.interpretation_fingerprint, "interpretation_fingerprint")
        _digest(self.backend_fingerprint, "backend_fingerprint")
        _positive_integer(self.max_input_bytes, "max_input_bytes")
        _positive_integer(self.max_state_bytes, "max_state_bytes")
        if not isinstance(self.deterministic, bool):
            raise ComputationalTransitionError("deterministic must be Boolean")
        if self.effect_mode not in {"pure", "idempotent", "transactional"}:
            raise ComputationalTransitionError("effect_mode must be pure, idempotent, or transactional")

    def to_dict(self) -> dict[str, object]:
        """Project the complete transition declaration into its canonical identity payload."""
        return {
            "schema": "mailcpu.computational-transition-contract.v1",
            "transition_id": self.transition_id,
            "state_schema_id": self.state_schema_id,
            "input_schema_id": self.input_schema_id,
            "interpretation_fingerprint": self.interpretation_fingerprint,
            "backend_fingerprint": self.backend_fingerprint,
            "max_input_bytes": self.max_input_bytes,
            "max_state_bytes": self.max_state_bytes,
            "deterministic": self.deterministic,
            "effect_mode": self.effect_mode,
        }

    @property
    def digest(self) -> str:
        """Identify the exact transition contract, including interpretation and resource bounds."""
        return _sha256(_canonical_bytes(self.to_dict()))


@dataclass(frozen=True, slots=True)
class ComputationalTransitionContext:
    """Read-only identity projection binding one backend call to an exact verified session revision."""

    session_id: str
    revision: int
    checkpoint_digest: str
    lineage_digest: str
    state_digest: str
    artifact_manifest_digest: str
    state_schema_id: str
    backend_fingerprint: str
    interpretation_fingerprint: str
    transition_contract_digest: str
    operation_id: str
    input_digest: str
    logical_time: int

    def __post_init__(self) -> None:
        """Validate the context coordinates before they are exposed to a local transition backend."""
        _label(self.session_id, "session_id")
        _label(self.state_schema_id, "state_schema_id")
        _label(self.operation_id, "operation_id")
        for name in (
            "checkpoint_digest",
            "lineage_digest",
            "state_digest",
            "artifact_manifest_digest",
            "backend_fingerprint",
            "interpretation_fingerprint",
            "transition_contract_digest",
            "input_digest",
        ):
            _digest(getattr(self, name), name)
        _positive_integer(self.revision, "revision")
        if type(self.logical_time) is not int or self.logical_time < 0:
            raise ComputationalTransitionError("logical_time must be a non-negative integer")

    def to_dict(self) -> dict[str, object]:
        """Project all current-state and request coordinates used by the backend into a stable mapping."""
        return {
            "schema": "mailcpu.computational-transition-context.v1",
            "session_id": self.session_id,
            "revision": self.revision,
            "checkpoint_digest": self.checkpoint_digest,
            "lineage_digest": self.lineage_digest,
            "state_digest": self.state_digest,
            "artifact_manifest_digest": self.artifact_manifest_digest,
            "state_schema_id": self.state_schema_id,
            "backend_fingerprint": self.backend_fingerprint,
            "interpretation_fingerprint": self.interpretation_fingerprint,
            "transition_contract_digest": self.transition_contract_digest,
            "operation_id": self.operation_id,
            "input_digest": self.input_digest,
            "logical_time": self.logical_time,
        }

    @property
    def binding_digest(self) -> str:
        """Commit the interpretation and operation to one exact quorum-verified session coordinate."""
        return _sha256(_canonical_bytes(self.to_dict()))


class ComputationalTransitionBackend(Protocol):
    """Trusted local state transformer identified by a stable backend-profile fingerprint."""

    @property
    def backend_fingerprint(self) -> str:
        """Return the exact backend profile identity declared by the transition contract."""
        ...

    def transition(
        self,
        state_bytes: bytes,
        input_bytes: bytes,
        context: ComputationalTransitionContext,
    ) -> bytes:
        """Return candidate successor state bytes without performing external effects."""
        ...


class ComputationalSessionTransitionAdapter:
    """Apply bounded pure transitions to verified sessions and publish successors through M3 compare-and-swap."""

    def __init__(
        self,
        session_store: ComputationalSessionStore,
        contract: ComputationalTransitionContract,
        backend: ComputationalTransitionBackend,
    ) -> None:
        """Bind one local backend to an exact M3 session, interpretation, state schema, and pure effect contract."""
        if not isinstance(session_store, ComputationalSessionStore):
            raise TypeError("session_store must be a ComputationalSessionStore")
        if not isinstance(contract, ComputationalTransitionContract):
            raise TypeError("contract must be a ComputationalTransitionContract")
        if contract.state_schema_id != session_store.state_schema_id:
            raise ComputationalTransitionError("transition state schema differs from the computational session")
        if contract.backend_fingerprint != session_store.backend_fingerprint:
            raise ComputationalTransitionError("transition backend fingerprint differs from the session backend")
        if contract.max_state_bytes > session_store.object_store.max_object_bytes:
            raise ComputationalTransitionError("max_state_bytes exceeds the M1 object-store bound")
        if contract.deterministic is not True or contract.effect_mode != "pure":
            raise ComputationalTransitionError(
                "session transition adapter admits only declared deterministic pure backends"
            )
        backend_fingerprint = getattr(backend, "backend_fingerprint", None)
        if backend_fingerprint != contract.backend_fingerprint:
            raise ComputationalTransitionError("local backend identity differs from the transition contract")
        if not callable(getattr(backend, "transition", None)):
            raise TypeError("backend must implement transition(state_bytes, input_bytes, context)")
        self.session_store = session_store
        self.contract = contract
        self.backend = backend

    def apply(
        self,
        input_bytes: bytes,
        *,
        operation_id: str,
        logical_time: int | None = None,
        expected_revision: int | None = None,
        expected_checkpoint_digest: str | None = None,
    ) -> ComputationalSessionSnapshot:
        """Interpret one input from a verified snapshot and CAS-anchor its exact bounded successor bytes."""
        if not isinstance(input_bytes, bytes):
            raise TypeError("input_bytes must be bytes")
        _label(operation_id, "operation_id")
        if len(input_bytes) > self.contract.max_input_bytes:
            raise ComputationalTransitionError("transition input exceeds max_input_bytes")
        if logical_time is not None and (type(logical_time) is not int or logical_time < 0):
            raise ComputationalTransitionError("logical_time must be a non-negative integer")
        if (expected_revision is None) != (expected_checkpoint_digest is None):
            raise ComputationalTransitionError("expected_revision and expected_checkpoint_digest must be supplied together")
        if expected_revision is not None:
            _positive_integer(expected_revision, "expected_revision")
            _digest(expected_checkpoint_digest, "expected_checkpoint_digest")
        if getattr(self.backend, "backend_fingerprint", None) != self.contract.backend_fingerprint:
            raise ComputationalTransitionError("local backend fingerprint changed after adapter admission")

        input_digest = _sha256(_canonical_bytes({
            "schema": _INPUT_SCHEMA,
            "transition_contract_digest": self.contract.digest,
            "input_schema_id": self.contract.input_schema_id,
            "payload_digest": _sha256(input_bytes),
        }))
        current = self.session_store.load_latest()
        if len(current.state_bytes) > self.contract.max_state_bytes:
            raise ComputationalTransitionError("current session state exceeds max_state_bytes")

        if current.checkpoint.operation_id == operation_id:
            checkpoint = current.checkpoint
            if (
                checkpoint.transition_id != self.contract.transition_id
                or checkpoint.input_digest != input_digest
                or checkpoint.backend_fingerprint != self.contract.backend_fingerprint
                or (logical_time is not None and checkpoint.logical_time != logical_time)
            ):
                raise ComputationalSessionConflictError(
                    "operation_id was reused with a different transition, input, backend, or logical time"
                )
            if expected_revision is not None and (
                checkpoint.revision != expected_revision + 1
                or checkpoint.predecessor_checkpoint_digest != expected_checkpoint_digest
            ):
                raise ComputationalSessionConflictError(
                    "retry base does not match the predecessor of the committed operation"
                )
            return replace(current, replayed=True)

        next_logical_time = current.checkpoint.logical_time + 1 if logical_time is None else logical_time
        if next_logical_time != current.checkpoint.logical_time + 1:
            raise ComputationalSessionConflictError(
                "new session transitions must advance logical_time by exactly one"
            )
        if expected_revision is not None and (
            current.revision != expected_revision
            or current.checkpoint_digest != expected_checkpoint_digest
        ):
            raise ComputationalSessionConflictError(
                "session revision or checkpoint digest differs from the expected transition base"
            )

        context = ComputationalTransitionContext(
            session_id=current.checkpoint.session_id,
            revision=current.revision,
            checkpoint_digest=current.checkpoint_digest,
            lineage_digest=current.lineage_manifest.digest,
            state_digest=current.checkpoint.state_digest,
            artifact_manifest_digest=current.checkpoint.artifact_manifest_digest,
            state_schema_id=current.checkpoint.state_schema_id,
            backend_fingerprint=current.checkpoint.backend_fingerprint,
            interpretation_fingerprint=self.contract.interpretation_fingerprint,
            transition_contract_digest=self.contract.digest,
            operation_id=operation_id,
            input_digest=input_digest,
            logical_time=next_logical_time,
        )
        try:
            candidate_state = self.backend.transition(current.state_bytes, input_bytes, context)
        except ComputationalTransitionError:
            raise
        except Exception as exc:
            raise ComputationalTransitionError(
                f"local pure transition backend failed: {type(exc).__name__}: {exc}"
            ) from exc
        if not isinstance(candidate_state, bytes):
            raise ComputationalTransitionError("transition backend must return exact successor bytes")
        if len(candidate_state) > self.contract.max_state_bytes:
            raise ComputationalTransitionError("candidate successor state exceeds max_state_bytes")

        return self.session_store.commit_state(
            candidate_state,
            expected_revision=current.revision,
            expected_checkpoint_digest=current.checkpoint_digest,
            transition_id=self.contract.transition_id,
            operation_id=operation_id,
            input_digest=input_digest,
            logical_time=next_logical_time,
        )
