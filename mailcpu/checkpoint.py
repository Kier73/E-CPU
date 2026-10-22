"""Integrity-checked persistence for continuation-capable MailCPU headless systems."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .headless import HeadlessOS
    from .kernel import KernelError


class CheckpointError(ValueError):
    """Exception for an invalid checkpoint or failed content identity verification."""


def _canonical_state(state: dict[str, object]) -> bytes:
    """Mathematics: encode state as canonical bytes `c = JSON(sort_keys, compact)(state)` for stable hashing."""

    return json.dumps(state, sort_keys=True, separators=(",", ":")).encode("utf-8")


def save_checkpoint(operating_system: HeadlessOS, path: str | Path) -> str:
    """Mathematics: publish `C=(format,digest,S)` by same-directory atomic replacement after `SHA256(S)=digest`."""

    state = operating_system.snapshot()
    digest = hashlib.sha256(_canonical_state(state)).hexdigest()
    document = {"format": "mailcpu-checkpoint-v1", "digest": digest, "state": state}
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(document, indent=2, sort_keys=True) + "\n"
    temporary_path: Path | None = None
    try:
        descriptor, raw_temporary_path = tempfile.mkstemp(
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=str(destination.parent),
            text=True,
        )
        temporary_path = Path(raw_temporary_path)
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
    return digest


def load_checkpoint(path: str | Path) -> HeadlessOS:
    """Mathematics: parse `C`, require `format = v1` and `SHA256(state) = digest`, then restore its OS graph."""

    from .headless import HeadlessOS

    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CheckpointError(str(exc)) from exc
    if document.get("format") != "mailcpu-checkpoint-v1":
        raise CheckpointError("unsupported checkpoint format")
    state = document.get("state")
    if not isinstance(state, dict):
        raise CheckpointError("checkpoint state must be an object")
    expected = hashlib.sha256(_canonical_state(state)).hexdigest()
    if document.get("digest") != expected:
        raise CheckpointError("checkpoint digest mismatch")
    try:
        return HeadlessOS.from_snapshot(state)
    except (KeyError, TypeError, ValueError, OSError, KernelError) as exc:
        raise CheckpointError(str(exc)) from exc
