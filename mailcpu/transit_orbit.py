"""Deterministic round-robin scheduling across independent transit computation paths.

The orbit scheduler owns only path-selection state. Each TransitComputeSession
continues to own its request, worker, hypervisor, replay, and response ledgers.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .classifier import HypervisorExecutionResult
from .transit_session import TransitComputeSession


_FORMAT = "mailcpu-transit-orbit-checkpoint-v1"
_RECEIPT_FORMAT = "mailcpu-transit-orbit-receipt-v1"
_ZERO_DIGEST = "0" * 64
_STATE_FIELDS = frozenset(
    {
        "version",
        "path_ids",
        "path_contract_digests",
        "session_checkpoint_digests",
        "cursor",
        "logical_tick",
        "dispatch_counts",
        "idle_ticks",
        "stale_ready_ticks",
        "receipt_head",
    }
)


class TransitOrbitSchedulerError(ValueError):
    """A transit path set, scheduling transition, or orbit checkpoint is invalid."""


def _canonical_bytes(value: Any) -> bytes:
    """Encode a value in the finite canonical JSON domain used by orbit receipts."""
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise TransitOrbitSchedulerError(
            f"orbit state is not canonical JSON: {exc}"
        ) from exc


def _digest(value: Any) -> str:
    """Return the SHA-256 digest of a canonical JSON value."""
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _require_digest(value: Any, label: str) -> str:
    """Validate one lowercase SHA-256 digest."""
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise TransitOrbitSchedulerError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _nonnegative_int(value: Any, label: str) -> int:
    """Require a non-negative integer while excluding Boolean values."""
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise TransitOrbitSchedulerError(f"{label} must be a non-negative integer")
    return value


def _path_label(value: Any) -> str:
    """Require a stable, non-empty logical path identifier."""
    if not isinstance(value, str) or not value.strip():
        raise TransitOrbitSchedulerError("path IDs must be non-empty strings")
    if len(value) > 128:
        raise TransitOrbitSchedulerError("path IDs must not exceed 128 characters")
    return value


def _session_contract(session: TransitComputeSession) -> dict[str, object]:
    """Project a session's logical channel identity without including its physical transport."""
    request = session.request.channel
    response = session.response.channel
    return {
        "request": {
            "source": request.source,
            "destination": request.destination,
            "peer": request.peer,
            "channel": request.channel,
        },
        "response": {
            "source": response.source,
            "destination": response.destination,
            "peer": response.peer,
            "channel": response.channel,
            "operation_source": session.response.operation_source,
            "operation_channel": session.response.operation_channel,
        },
    }


def _session_checkpoint_digest(session: TransitComputeSession) -> str:
    """Read the authoritative path checkpoint digest at a quiescent worker boundary."""
    checkpoint = session.snapshot()
    if not isinstance(checkpoint, Mapping):
        raise TransitOrbitSchedulerError("transit session snapshot must be a mapping")
    return _require_digest(checkpoint.get("digest"), "session checkpoint digest")


@dataclass(frozen=True)
class TransitOrbitReceipt:
    """Hash-linked evidence of one scheduler quantum, not a duplicate effect ledger."""

    tick: int
    path_id: str | None
    disposition: str
    action: str | None
    executed: bool | None
    replayed: bool | None
    session_state_digest: str | None
    previous_digest: str
    digest: str

    def __post_init__(self) -> None:
        """Validate the receipt's finite shape before it can enter a receipt chain."""
        _nonnegative_int(self.tick, "receipt tick")
        if self.tick == 0:
            raise TransitOrbitSchedulerError("receipt ticks start at one")
        if self.disposition not in {"processed", "idle", "stale-ready"}:
            raise TransitOrbitSchedulerError("receipt disposition is invalid")
        _require_digest(self.previous_digest, "receipt previous_digest")
        _require_digest(self.digest, "receipt digest")
        if self.path_id is not None:
            _path_label(self.path_id)
        if self.session_state_digest is not None:
            _require_digest(self.session_state_digest, "session_state_digest")
        if self.disposition == "idle":
            if any(
                value is not None
                for value in (
                    self.path_id,
                    self.action,
                    self.executed,
                    self.replayed,
                    self.session_state_digest,
                )
            ):
                raise TransitOrbitSchedulerError("idle receipts cannot identify a path or result")
        elif self.path_id is None or self.session_state_digest is None:
            raise TransitOrbitSchedulerError("selected-path receipts require a path and state digest")
        elif self.disposition == "processed":
            if (
                not isinstance(self.action, str)
                or not self.action
                or not isinstance(self.executed, bool)
                or not isinstance(self.replayed, bool)
            ):
                raise TransitOrbitSchedulerError("processed receipts require a typed execution result")
        elif any(value is not None for value in (self.action, self.executed, self.replayed)):
            raise TransitOrbitSchedulerError("stale-ready receipts cannot claim an execution result")

    def payload(self) -> dict[str, object]:
        """Return the canonical receipt fields covered by its digest."""
        return {
            "format": _RECEIPT_FORMAT,
            "tick": self.tick,
            "path_id": self.path_id,
            "disposition": self.disposition,
            "action": self.action,
            "executed": self.executed,
            "replayed": self.replayed,
            "session_state_digest": self.session_state_digest,
            "previous_digest": self.previous_digest,
        }

    def to_dict(self) -> dict[str, object]:
        """Serialize the receipt together with its integrity digest."""
        return {**self.payload(), "digest": self.digest}


@dataclass(frozen=True)
class TransitOrbitStep:
    """One scheduler quantum and the optional authoritative hypervisor result."""

    receipt: TransitOrbitReceipt
    result: HypervisorExecutionResult | None = None


def verify_transit_orbit_receipts(
    receipts: Sequence[TransitOrbitReceipt],
    *,
    initial_digest: str = _ZERO_DIGEST,
    initial_tick: int = 0,
) -> bool:
    """Verify a contiguous receipt suffix against its preceding digest and logical tick."""
    try:
        previous = _require_digest(initial_digest, "initial_digest")
        tick = _nonnegative_int(initial_tick, "initial_tick")
        for receipt in receipts:
            if not isinstance(receipt, TransitOrbitReceipt):
                return False
            if receipt.tick != tick + 1 or receipt.previous_digest != previous:
                return False
            if _digest(receipt.payload()) != receipt.digest:
                return False
            tick = receipt.tick
            previous = receipt.digest
    except (TransitOrbitSchedulerError, TypeError, ValueError):
        return False
    return True


class TransitOrbitScheduler:
    """Deterministically interleave independent TransitComputeSession paths.

    Path IDs define a stable logical order. Each call to step() admits at most
    one ready request. The physical transport is deliberately absent from the
    path contract, allowing a session restored from the same checkpoint to be
    rebound to a replacement transport without resetting the orbit cursor.
    """

    def __init__(self, sessions: Mapping[str, TransitComputeSession]) -> None:
        """Bind a non-empty set of named logical paths and initialize the orbit cursor."""
        if not isinstance(sessions, Mapping) or not sessions:
            raise TransitOrbitSchedulerError("orbit scheduler requires at least one named path")
        normalized: dict[str, TransitComputeSession] = {}
        for raw_path_id, session in sessions.items():
            path_id = _path_label(raw_path_id)
            if not isinstance(session, TransitComputeSession):
                raise TransitOrbitSchedulerError(
                    f"path {path_id!r} must bind a TransitComputeSession"
                )
            normalized[path_id] = session
        if len(normalized) != len(sessions):
            raise TransitOrbitSchedulerError("logical path IDs must be unique")

        self._sessions = normalized
        self._path_order = tuple(sorted(normalized))
        self._path_contract_digests = {
            path_id: _digest(_session_contract(normalized[path_id]))
            for path_id in self._path_order
        }
        self._cursor = 0
        self._logical_tick = 0
        self._dispatch_counts = {path_id: 0 for path_id in self._path_order}
        self._idle_ticks = 0
        self._stale_ready_ticks = 0
        self._receipt_head = _ZERO_DIGEST

    @property
    def path_ids(self) -> tuple[str, ...]:
        """Return the immutable canonical order of logical path IDs."""
        return self._path_order

    @property
    def logical_tick(self) -> int:
        """Return the number of scheduler quanta, including idle observations."""
        return self._logical_tick

    @property
    def cursor_path_id(self) -> str:
        """Return the path at which the next round-robin scan begins."""
        return self._path_order[self._cursor]

    @property
    def receipt_head(self) -> str:
        """Return the current rolling commitment to scheduler receipts."""
        return self._receipt_head

    @property
    def ready_paths(self) -> tuple[str, ...]:
        """Return ready paths in the order they would be considered by the next quantum."""
        count = len(self._path_order)
        ordered = (
            self._path_order[(self._cursor + offset) % count]
            for offset in range(count)
        )
        return tuple(
            path_id
            for path_id in ordered
            if self._sessions[path_id].phase == "request-ready"
        )

    def state(self) -> dict[str, object]:
        """Expose the scheduler projection without copying path execution ledgers."""
        return {
            "logical_tick": self._logical_tick,
            "cursor": self._cursor,
            "cursor_path_id": self.cursor_path_id,
            "path_ids": list(self._path_order),
            "ready_paths": list(self.ready_paths),
            "dispatch_counts": dict(self._dispatch_counts),
            "idle_ticks": self._idle_ticks,
            "stale_ready_ticks": self._stale_ready_ticks,
            "receipt_head": self._receipt_head,
        }

    def _receipt(
        self,
        *,
        tick: int,
        path_id: str | None,
        disposition: str,
        action: str | None = None,
        executed: bool | None = None,
        replayed: bool | None = None,
        session_state_digest: str | None = None,
    ) -> TransitOrbitReceipt:
        """Create and append one deterministic receipt to the scheduler's rolling chain."""
        payload = {
            "format": _RECEIPT_FORMAT,
            "tick": tick,
            "path_id": path_id,
            "disposition": disposition,
            "action": action,
            "executed": executed,
            "replayed": replayed,
            "session_state_digest": session_state_digest,
            "previous_digest": self._receipt_head,
        }
        receipt = TransitOrbitReceipt(
            tick=tick,
            path_id=path_id,
            disposition=disposition,
            action=action,
            executed=executed,
            replayed=replayed,
            session_state_digest=session_state_digest,
            previous_digest=self._receipt_head,
            digest=_digest(payload),
        )
        self._receipt_head = receipt.digest
        return receipt

    def step(self) -> TransitOrbitStep:
        """Advance at most one ready path by one request; an all-idle scan is one logical quantum."""
        count = len(self._path_order)
        selected_index: int | None = None
        for offset in range(count):
            index = (self._cursor + offset) % count
            path_id = self._path_order[index]
            if self._sessions[path_id].phase == "request-ready":
                selected_index = index
                break

        tick = self._logical_tick + 1
        if selected_index is None:
            self._logical_tick = tick
            self._idle_ticks += 1
            receipt = self._receipt(
                tick=tick,
                path_id=None,
                disposition="idle",
            )
            return TransitOrbitStep(receipt)

        path_id = self._path_order[selected_index]
        session = self._sessions[path_id]
        result = session.serve_once()
        self._cursor = (selected_index + 1) % count
        self._logical_tick = tick
        state_digest = _digest(session.state())

        if result is None:
            self._stale_ready_ticks += 1
            receipt = self._receipt(
                tick=tick,
                path_id=path_id,
                disposition="stale-ready",
                session_state_digest=state_digest,
            )
            return TransitOrbitStep(receipt)

        self._dispatch_counts[path_id] += 1
        action = getattr(result.action, "value", result.action)
        if not isinstance(action, str):
            action = str(action)
        receipt = self._receipt(
            tick=tick,
            path_id=path_id,
            disposition="processed",
            action=action,
            executed=bool(result.executed),
            replayed=bool(result.replayed),
            session_state_digest=state_digest,
        )
        return TransitOrbitStep(receipt, result)

    def run(self, max_quanta: int) -> tuple[TransitOrbitStep, ...]:
        """Run a bounded number of quanta, stopping early when every path is idle."""
        if (
            not isinstance(max_quanta, int)
            or isinstance(max_quanta, bool)
            or max_quanta <= 0
        ):
            raise TransitOrbitSchedulerError("max_quanta must be a positive integer")
        steps: list[TransitOrbitStep] = []
        for _ in range(max_quanta):
            current = self.step()
            steps.append(current)
            if current.receipt.disposition == "idle":
                break
        return tuple(steps)

    def replace_session(
        self,
        path_id: str,
        session: TransitComputeSession,
    ) -> None:
        """Rebind a logical path to a restored session only when its contract and checkpoint are identical."""
        path_id = _path_label(path_id)
        if path_id not in self._sessions:
            raise TransitOrbitSchedulerError(f"unknown logical path {path_id!r}")
        if not isinstance(session, TransitComputeSession):
            raise TransitOrbitSchedulerError("replacement must be a TransitComputeSession")
        contract_digest = _digest(_session_contract(session))
        if contract_digest != self._path_contract_digests[path_id]:
            raise TransitOrbitSchedulerError(
                "replacement session changes the logical path contract"
            )
        current_digest = _session_checkpoint_digest(self._sessions[path_id])
        replacement_digest = _session_checkpoint_digest(session)
        if replacement_digest != current_digest:
            raise TransitOrbitSchedulerError(
                "replacement session does not restore the current path checkpoint"
            )
        self._sessions[path_id] = session

    def snapshot(self) -> dict[str, object]:
        """Checkpoint scheduler arbitration and bind it to every quiescent authoritative path snapshot."""
        session_digests = {
            path_id: _session_checkpoint_digest(self._sessions[path_id])
            for path_id in self._path_order
        }
        state: dict[str, object] = {
            "version": 1,
            "path_ids": list(self._path_order),
            "path_contract_digests": dict(self._path_contract_digests),
            "session_checkpoint_digests": session_digests,
            "cursor": self._cursor,
            "logical_tick": self._logical_tick,
            "dispatch_counts": dict(self._dispatch_counts),
            "idle_ticks": self._idle_ticks,
            "stale_ready_ticks": self._stale_ready_ticks,
            "receipt_head": self._receipt_head,
        }
        return {
            "format": _FORMAT,
            "digest": _digest(state),
            "state": state,
        }

    @classmethod
    def from_snapshot(
        cls,
        payload: Mapping[str, Any],
        sessions: Mapping[str, TransitComputeSession],
    ) -> "TransitOrbitScheduler":
        """Restore scheduler state only when every supplied path matches its checkpoint and logical contract."""
        if not isinstance(payload, Mapping) or set(payload) != {"format", "digest", "state"}:
            raise TransitOrbitSchedulerError("orbit checkpoint envelope fields are invalid")
        if payload.get("format") != _FORMAT:
            raise TransitOrbitSchedulerError("unsupported transit orbit checkpoint format")
        state = payload.get("state")
        if not isinstance(state, Mapping) or set(state) != _STATE_FIELDS:
            raise TransitOrbitSchedulerError("orbit checkpoint state fields are invalid")
        if state.get("version") != 1:
            raise TransitOrbitSchedulerError("unsupported transit orbit checkpoint version")
        supplied_digest = _require_digest(payload.get("digest"), "orbit checkpoint digest")
        if _digest(dict(state)) != supplied_digest:
            raise TransitOrbitSchedulerError("orbit checkpoint digest mismatch")

        raw_path_ids = state.get("path_ids")
        if (
            not isinstance(raw_path_ids, list)
            or not raw_path_ids
            or any(not isinstance(item, str) for item in raw_path_ids)
        ):
            raise TransitOrbitSchedulerError("orbit checkpoint path IDs are invalid")
        scheduler = cls(sessions)
        if list(scheduler.path_ids) != raw_path_ids:
            raise TransitOrbitSchedulerError("restored logical path membership does not match checkpoint")

        raw_contracts = state.get("path_contract_digests")
        raw_sessions = state.get("session_checkpoint_digests")
        if not isinstance(raw_contracts, Mapping) or not isinstance(raw_sessions, Mapping):
            raise TransitOrbitSchedulerError("orbit checkpoint path digests are invalid")
        if set(raw_contracts) != set(scheduler.path_ids) or set(raw_sessions) != set(scheduler.path_ids):
            raise TransitOrbitSchedulerError("orbit checkpoint path digest membership is invalid")
        for path_id in scheduler.path_ids:
            if _require_digest(raw_contracts[path_id], "path contract digest") != scheduler._path_contract_digests[path_id]:
                raise TransitOrbitSchedulerError(
                    f"restored path {path_id!r} changes its logical channel contract"
                )
            current_session_digest = _session_checkpoint_digest(scheduler._sessions[path_id])
            if _require_digest(raw_sessions[path_id], "session checkpoint digest") != current_session_digest:
                raise TransitOrbitSchedulerError(
                    f"restored path {path_id!r} does not match its checkpoint"
                )

        cursor = _nonnegative_int(state.get("cursor"), "cursor")
        if cursor >= len(scheduler.path_ids):
            raise TransitOrbitSchedulerError("orbit checkpoint cursor is outside path order")
        logical_tick = _nonnegative_int(state.get("logical_tick"), "logical_tick")
        idle_ticks = _nonnegative_int(state.get("idle_ticks"), "idle_ticks")
        stale_ready_ticks = _nonnegative_int(state.get("stale_ready_ticks"), "stale_ready_ticks")
        raw_counts = state.get("dispatch_counts")
        if not isinstance(raw_counts, Mapping) or set(raw_counts) != set(scheduler.path_ids):
            raise TransitOrbitSchedulerError("orbit checkpoint dispatch counts are invalid")
        counts = {
            path_id: _nonnegative_int(raw_counts[path_id], f"dispatch_counts[{path_id}]")
            for path_id in scheduler.path_ids
        }
        if sum(counts.values()) + idle_ticks + stale_ready_ticks != logical_tick:
            raise TransitOrbitSchedulerError("orbit checkpoint counters do not conserve logical ticks")
        receipt_head = _require_digest(state.get("receipt_head"), "receipt_head")

        scheduler._cursor = cursor
        scheduler._logical_tick = logical_tick
        scheduler._dispatch_counts = counts
        scheduler._idle_ticks = idle_ticks
        scheduler._stale_ready_ticks = stale_ready_ticks
        scheduler._receipt_head = receipt_head
        return scheduler

    def save_checkpoint(self, path: str | os.PathLike[str]) -> str:
        """Atomically persist the scheduler checkpoint; each session checkpoint is persisted separately."""
        target = Path(path)
        if not str(target):
            raise TransitOrbitSchedulerError("orbit checkpoint path must be non-empty")
        payload = self.snapshot()
        encoded = _canonical_bytes(payload) + b"\n"
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=str(target.parent),
        )
        temporary = Path(temporary_name)
        try:
            if hasattr(os, "fchmod"):
                os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
            try:
                directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
                directory_fd = os.open(str(target.parent), directory_flags)
            except OSError:
                directory_fd = None
            if directory_fd is not None:
                try:
                    os.fsync(directory_fd)
                except OSError:
                    pass
                finally:
                    os.close(directory_fd)
        except Exception:
            try:
                os.close(descriptor)
            except OSError:
                pass
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
            raise
        return str(payload["digest"])

    @classmethod
    def from_checkpoint(
        cls,
        path: str | os.PathLike[str],
        sessions: Mapping[str, TransitComputeSession],
    ) -> "TransitOrbitScheduler":
        """Read a scheduler checkpoint and reattach already restored logical sessions."""
        source = Path(path)
        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TransitOrbitSchedulerError(
                f"cannot read transit orbit checkpoint: {exc}"
            ) from exc
        if not isinstance(payload, Mapping):
            raise TransitOrbitSchedulerError("orbit checkpoint root must be an object")
        return cls.from_snapshot(payload, sessions)
