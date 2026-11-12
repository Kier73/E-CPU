"""Bridge stateful transition snapshots to E-CPU's indexed trajectory and event-journal formats.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .journal import EventJournal
from .stateful_transition import StatefulTransitionRuntime
from .transition_space import FiniteTransitionProgram
from .trajectory import TrajectoryError, TrajectoryReader, TrajectoryWriter


MANIFEST_SCHEMA = "mailcpu.stateful-transition-trajectory-manifest.v1"
FRAME_SCHEMA = "mailcpu.stateful-transition-trajectory-frame.v1"
ZERO_RECEIPT = "0" * 64


class StatefulTransitionTrajectoryError(ValueError):
    """A trajectory export, manifest, receipt chain, or runtime replay violates its contract.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""


@dataclass(frozen=True, slots=True)
class StatefulTransitionCheckpoint:
    """A verified state/model coordinate bound to one runtime event and trajectory frame.

    Mathematics: the record identifies q=(state,tick,revision,program_digest,model_digest)
    at the last committed event whose logical time equals the requested coordinate.
    """
    logical_time: int
    state: tuple[int, ...]
    revision: int
    program_digest: str
    model_digest: str
    event_kind: str
    runtime_event_sequence: int
    runtime_event_digest: str
    trajectory_sequence: int
    trajectory_receipt: str

    def __post_init__(self) -> None:
        """Validate the finite state coordinate and all content-addressed provenance fields.

        Mathematics: require logical_time, revision, and trajectory_sequence in N_0,
        runtime_event_sequence in N_plus, state in {0,1}^n, and all digests in SHA256.
        """
        integer_fields = (
            self.logical_time,
            self.revision,
            self.trajectory_sequence,
        )
        if any(type(value) is not int or value < 0 for value in integer_fields) or type(self.runtime_event_sequence) is not int or self.runtime_event_sequence <= 0:
            raise StatefulTransitionTrajectoryError(
                "checkpoint logical time, revision, and sequence fields must be non-negative integers"
            )
        state = tuple(
            int(value) if isinstance(value, bool) else value
            for value in self.state
        )
        if not state or any(type(value) is not int or value not in (0, 1) for value in state):
            raise StatefulTransitionTrajectoryError(
                "checkpoint state must be a nonempty Boolean bit vector"
            )
        object.__setattr__(self, "state", state)
        if self.event_kind not in ("step", "revision"):
            raise StatefulTransitionTrajectoryError("checkpoint event kind is invalid")
        for label, digest in (
            ("program_digest", self.program_digest),
            ("model_digest", self.model_digest),
            ("runtime_event_digest", self.runtime_event_digest),
            ("trajectory_receipt", self.trajectory_receipt),
        ):
            if (
                not isinstance(digest, str)
                or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)
            ):
                raise StatefulTransitionTrajectoryError(
                    f"checkpoint {label} must be a lowercase SHA-256 digest"
                )

    def to_dict(self) -> dict[str, Any]:
        """Serialize the checkpoint's state/time coordinate and linked event provenance.

        Mathematics: encode the checkpoint tuple as a versioned JSON mapping without
        changing its state, logical coordinate, model revision, or receipt identities.
        """
        return {
            "schema": "mailcpu.stateful-transition-checkpoint.v1",
            "logical_time": self.logical_time,
            "state": list(self.state),
            "revision": self.revision,
            "program_digest": self.program_digest,
            "model_digest": self.model_digest,
            "event_kind": self.event_kind,
            "runtime_event_sequence": self.runtime_event_sequence,
            "runtime_event_digest": self.runtime_event_digest,
            "trajectory_sequence": self.trajectory_sequence,
            "trajectory_receipt": self.trajectory_receipt,
        }


def _canonical_json(value: Any) -> str:
    """Mathematics: produce a unique compact JSON encoding c=JSON(sort_keys,compact)(value) for manifest identities."""
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise StatefulTransitionTrajectoryError(
            "trajectory metadata is not canonical JSON data"
        ) from exc


def _digest(value: Any) -> str:
    """Mathematics: bind one canonical JSON value with D=SHA256(UTF8(c))."""
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _copy_json(value: Any) -> Any:
    """Mathematics: detach JSON state by applying the identity-preserving round trip x'=decode(encode(x))."""
    return json.loads(_canonical_json(value))


def _logical_time(event: Mapping[str, Any]) -> int:
    """Mathematics: map a step to tick_after and a revision to its unchanged tick coordinate."""
    kind = event.get("kind")
    value = event.get("tick_after") if kind == "step" else event.get("tick")
    if kind not in ("step", "revision") or type(value) is not int or value < 0:
        raise StatefulTransitionTrajectoryError(
            "runtime event has no valid logical-time coordinate"
        )
    return value


def _event_journal_head(events: list[dict[str, Any]]) -> str:
    """Mathematics: project runtime events into EventJournal and return its last receipt J_n."""
    journal = EventJournal()
    for event in events:
        kind = event.get("kind")
        if kind not in ("step", "revision"):
            raise StatefulTransitionTrajectoryError("runtime event kind is invalid")
        payload = {
            key: value
            for key, value in event.items()
            if key not in ("sequence", "kind", "previous_event_digest", "event_digest")
        }
        journal.append(str(kind), payload)
    if not journal.verify():
        raise StatefulTransitionTrajectoryError(
            "EventJournal projection failed its own receipt-chain verification"
        )
    records = journal.records()
    return records[-1].digest if records else ZERO_RECEIPT


def _atomic_write_json(path: str | Path, document: Mapping[str, Any]) -> None:
    """Mathematics: publish manifest M by same-directory atomic replacement after writing canonical JSON."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        document,
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
        allow_nan=False,
    ) + "\n"
    temporary_path: Path | None = None
    try:
        descriptor, raw_path = tempfile.mkstemp(
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=str(destination.parent),
            text=True,
        )
        temporary_path = Path(raw_path)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, destination)
        temporary_path = None
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass


def export_stateful_transition_trajectory(
    runtime: StatefulTransitionRuntime,
    data_path: str | Path,
    index_path: str | Path,
    manifest_path: str | Path,
    *,
    stride: int = 64,
) -> dict[str, Any]:
    """Persist runtime events as indexed TrajectoryFrames and an EventJournal-bound manifest.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.

    Every runtime step/revision event is kept intact inside one binary trajectory
    frame. The frame receipt chain is verified by TrajectoryReader. Separately,
    the same event payloads are projected into the repository's EventJournal and
    its chain head is stored in the manifest. The original runtime event digest
    chain remains embedded in each frame and is revalidated when restoring.
    """
    if not isinstance(runtime, StatefulTransitionRuntime):
        raise StatefulTransitionTrajectoryError(
            "runtime must be a StatefulTransitionRuntime"
        )
    if type(stride) is not int or stride <= 0:
        raise StatefulTransitionTrajectoryError("stride must be a positive integer")

    snapshot = runtime.snapshot()
    events = snapshot.get("events")
    if not isinstance(events, list):
        raise StatefulTransitionTrajectoryError(
            "runtime snapshot must contain an ordered event array"
        )

    last_receipt = ZERO_RECEIPT
    try:
        with TrajectoryWriter(data_path, index_path, stride=stride) as writer:
            for event in events:
                if not isinstance(event, Mapping):
                    raise StatefulTransitionTrajectoryError(
                        "runtime event must be an object"
                    )
                event_copy = _copy_json(event)
                frame_payload = {
                    "schema": FRAME_SCHEMA,
                    "runtime_event": event_copy,
                    "runtime_event_sequence": event_copy["sequence"],
                    "runtime_event_digest": event_copy["event_digest"],
                    "runtime_genesis_digest": snapshot["genesis_digest"],
                    "runtime_chain_head_digest": snapshot["chain_head_digest"],
                }
                frame = writer.append(_logical_time(event_copy), frame_payload)
                last_receipt = frame.receipt.hex()
    except (TrajectoryError, OSError, KeyError, TypeError) as exc:
        raise StatefulTransitionTrajectoryError(
            "could not write stateful transition trajectory"
        ) from exc

    try:
        with TrajectoryReader(data_path, index_path) as reader:
            verified_count = reader.verify()
            observed_receipts: list[str] = []
            replayed_count = reader.replay(
                lambda frame: observed_receipts.append(frame.receipt.hex())
            )
    except (TrajectoryError, OSError) as exc:
        raise StatefulTransitionTrajectoryError(
            "newly written stateful trajectory failed receipt verification"
        ) from exc

    if (
        verified_count != len(events)
        or replayed_count != len(events)
        or (observed_receipts[-1] if observed_receipts else ZERO_RECEIPT) != last_receipt
    ):
        raise StatefulTransitionTrajectoryError(
            "trajectory writer/reader count or receipt-head mismatch"
        )

    runtime_snapshot = {
        key: value
        for key, value in snapshot.items()
        if key != "events"
    }
    manifest_payload = {
        "schema": MANIFEST_SCHEMA,
        "runtime_snapshot": runtime_snapshot,
        "trajectory": {
            "event_count": len(events),
            "stride": stride,
            "receipt_head": last_receipt,
            "journal_head_digest": _event_journal_head(events),
            "runtime_chain_head_digest": snapshot["chain_head_digest"],
            "runtime_genesis_digest": snapshot["genesis_digest"],
            "tick": runtime.tick,
            "revision": runtime.revision,
            "program_digest": runtime.program_digest,
            "model_digest": runtime.model_digest,
        },
    }
    manifest = {
        **manifest_payload,
        "manifest_digest": _digest(manifest_payload),
    }
    _atomic_write_json(manifest_path, manifest)
    return _copy_json(manifest)


def restore_stateful_transition_trajectory(
    manifest_path: str | Path,
    data_path: str | Path,
    index_path: str | Path,
) -> StatefulTransitionRuntime:
    """Restore a runtime by verifying trajectory receipts, EventJournal projection, and runtime replay.
Mathematics: this callable implements the deterministic mapping or invariant stated in its contract, over the explicitly validated input domain.
"""
    try:
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StatefulTransitionTrajectoryError(
            "stateful trajectory manifest is unreadable"
        ) from exc

    required = {"schema", "runtime_snapshot", "trajectory", "manifest_digest"}
    if not isinstance(manifest, Mapping) or set(manifest) != required:
        raise StatefulTransitionTrajectoryError(
            "trajectory manifest fields do not match the schema"
        )
    if manifest["schema"] != MANIFEST_SCHEMA:
        raise StatefulTransitionTrajectoryError(
            "unsupported stateful trajectory manifest schema"
        )
    manifest_payload = {
        key: value for key, value in manifest.items() if key != "manifest_digest"
    }
    if manifest["manifest_digest"] != _digest(manifest_payload):
        raise StatefulTransitionTrajectoryError("trajectory manifest digest mismatch")

    snapshot = manifest["runtime_snapshot"]
    metadata = manifest["trajectory"]
    if not isinstance(snapshot, Mapping) or not isinstance(metadata, Mapping):
        raise StatefulTransitionTrajectoryError(
            "trajectory manifest runtime or trajectory metadata is invalid"
        )
    if "events" in snapshot:
        raise StatefulTransitionTrajectoryError(
            "trajectory runtime snapshot must store events in the binary stream"
        )
    if set(metadata) != {
        "event_count",
        "stride",
        "receipt_head",
        "journal_head_digest",
        "runtime_chain_head_digest",
        "runtime_genesis_digest",
        "tick",
        "revision",
        "program_digest",
        "model_digest",
    }:
        raise StatefulTransitionTrajectoryError(
            "trajectory metadata fields do not match the schema"
        )

    events: list[dict[str, Any]] = []
    observed_receipts: list[str] = []
    try:
        with TrajectoryReader(data_path, index_path) as reader:
            if reader.stride != metadata["stride"]:
                raise StatefulTransitionTrajectoryError(
                    "trajectory index stride does not match the manifest"
                )
            verified_count = reader.verify()

            def collect(frame) -> None:
                """Mathematics: preserve ordered frames F=(f_0,...,f_n) only after the reader verifies each receipt."""
                payload = frame.payload
                if (
                    not isinstance(payload, Mapping)
                    or set(payload) != {
                        "schema",
                        "runtime_event",
                        "runtime_event_sequence",
                        "runtime_event_digest",
                        "runtime_genesis_digest",
                        "runtime_chain_head_digest",
                    }
                    or payload["schema"] != FRAME_SCHEMA
                ):
                    raise StatefulTransitionTrajectoryError(
                        "trajectory frame fields or schema are invalid"
                    )
                event = payload["runtime_event"]
                if not isinstance(event, Mapping):
                    raise StatefulTransitionTrajectoryError(
                        "trajectory frame runtime event is invalid"
                    )
                event_copy = _copy_json(event)
                if (
                    type(payload["runtime_event_sequence"]) is not int
                    or payload["runtime_event_sequence"] != frame.sequence + 1
                    or event_copy.get("sequence") != frame.sequence + 1
                    or payload["runtime_event_digest"] != event_copy.get("event_digest")
                    or payload["runtime_genesis_digest"] != snapshot.get("genesis_digest")
                    or payload["runtime_chain_head_digest"]
                    != metadata["runtime_chain_head_digest"]
                    or frame.logical_time != _logical_time(event_copy)
                ):
                    raise StatefulTransitionTrajectoryError(
                        f"trajectory frame {frame.sequence} disagrees with its runtime event"
                    )
                events.append(event_copy)
                observed_receipts.append(frame.receipt.hex())

            replayed_count = reader.replay(collect)
    except (TrajectoryError, OSError, KeyError, TypeError) as exc:
        raise StatefulTransitionTrajectoryError(
            "stateful trajectory receipt or frame verification failed"
        ) from exc

    expected_count = metadata["event_count"]
    if (
        type(expected_count) is not int
        or expected_count < 0
        or verified_count != expected_count
        or replayed_count != expected_count
        or len(events) != expected_count
    ):
        raise StatefulTransitionTrajectoryError(
            "trajectory event count does not match the manifest"
        )

    receipt_head = observed_receipts[-1] if observed_receipts else ZERO_RECEIPT
    if receipt_head != metadata["receipt_head"]:
        raise StatefulTransitionTrajectoryError(
            "trajectory receipt head does not match the manifest"
        )
    try:
        current_program_digest = FiniteTransitionProgram.from_dict(
            snapshot["current_program"]
        ).digest
    except (KeyError, TypeError, ValueError) as exc:
        raise StatefulTransitionTrajectoryError(
            "trajectory manifest current transition program is invalid"
        ) from exc

    if (
        metadata["journal_head_digest"] != _event_journal_head(events)
        or metadata["runtime_genesis_digest"] != snapshot.get("genesis_digest")
        or metadata["runtime_chain_head_digest"] != snapshot.get("chain_head_digest")
        or metadata["tick"] != snapshot.get("tick")
        or metadata["revision"] != snapshot.get("revision")
        or metadata["program_digest"] != current_program_digest
        or metadata["model_digest"] != snapshot.get("current_model", {}).get("digest")
    ):
        raise StatefulTransitionTrajectoryError(
            "trajectory journal or runtime metadata does not match the manifest"
        )

    restored_snapshot = {
        **_copy_json(snapshot),
        "events": events,
    }
    try:
        runtime = StatefulTransitionRuntime.from_snapshot(restored_snapshot)
    except (ValueError, TypeError, KeyError) as exc:
        raise StatefulTransitionTrajectoryError(
            "runtime event replay failed after trajectory verification"
        ) from exc
    if runtime.snapshot() != restored_snapshot:
        raise StatefulTransitionTrajectoryError(
            "restored runtime snapshot differs from its trajectory manifest"
        )
    return runtime


def seek_stateful_transition_event(
    data_path: str | Path,
    index_path: str | Path,
    target_tick: int,
) -> dict[str, Any] | None:
    """Seek the last runtime event at an exact logical tick after verifying trajectory receipts.

    Mathematics: after receipt verification, return the last frame f_k for which
    logical_time(f_k) equals target_tick, including unindexed same-tick frames.
    """
    if type(target_tick) is not int or target_tick < 0:
        raise StatefulTransitionTrajectoryError(
            "target_tick must be a non-negative integer"
        )
    try:
        with TrajectoryReader(data_path, index_path) as reader:
            reader.verify()
            frame = reader.seek_time(target_tick)
            if frame is not None and frame.logical_time == target_tick:
                selected = frame
                while True:
                    following = reader.read_frame()
                    if following is None or following.logical_time != target_tick:
                        break
                    selected = following
                frame = selected
            else:
                frame = None
    except (TrajectoryError, OSError) as exc:
        raise StatefulTransitionTrajectoryError(
            "cannot seek an invalid stateful transition trajectory"
        ) from exc
    if frame is None:
        return None
    payload = frame.payload
    if (
        not isinstance(payload, Mapping)
        or payload.get("schema") != FRAME_SCHEMA
        or not isinstance(payload.get("runtime_event"), Mapping)
    ):
        raise StatefulTransitionTrajectoryError(
            "selected trajectory frame is not a stateful transition event"
        )
    return {
        "trajectory_sequence": frame.sequence,
        "logical_time": frame.logical_time,
        "runtime_event": _copy_json(payload["runtime_event"]),
        "trajectory_receipt": frame.receipt.hex(),
    }

def seek_stateful_transition_checkpoint(
    data_path: str | Path,
    index_path: str | Path,
    target_tick: int,
) -> dict[str, Any] | None:
    """Resolve a logical tick to the last event's exact state and active model revision.

    Mathematics: if e_k is the final event with logical_time(e_k)=target_tick,
    the checkpoint is q_k=(state_after_or_preserved(e_k), tick, revision,
    active_program_digest, active_model_digest), bound to the event and frame receipts.
    This is a state locator, not a fully reconstructed mutable runtime.
    """
    located = seek_stateful_transition_event(
        data_path,
        index_path,
        target_tick,
    )
    if located is None:
        return None
    event = located["runtime_event"]
    kind = event.get("kind")
    if kind == "step":
        state = event.get("state_after")
        logical_time = event.get("tick_after")
        revision = event.get("revision")
        program_digest = event.get("program_digest")
        model_digest = event.get("model_digest")
    elif kind == "revision":
        state = event.get("state_preserved")
        logical_time = event.get("tick")
        revision = event.get("revision_after")
        program_digest = event.get("target_program_digest")
        model_digest = event.get("target_model_digest")
    else:
        raise StatefulTransitionTrajectoryError(
            "selected runtime event cannot form a state checkpoint"
        )

    if logical_time != target_tick:
        raise StatefulTransitionTrajectoryError(
            "selected event logical time does not match the requested checkpoint"
        )
    try:
        checkpoint = StatefulTransitionCheckpoint(
            logical_time=logical_time,
            state=tuple(state),
            revision=revision,
            program_digest=program_digest,
            model_digest=model_digest,
            event_kind=kind,
            runtime_event_sequence=event["sequence"],
            runtime_event_digest=event["event_digest"],
            trajectory_sequence=located["trajectory_sequence"],
            trajectory_receipt=located["trajectory_receipt"],
        )
    except (KeyError, TypeError) as exc:
        raise StatefulTransitionTrajectoryError(
            "selected event lacks the fields required for a state checkpoint"
        ) from exc
    return checkpoint.to_dict()
