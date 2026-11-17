"""Atomic file persistence for verified tensor prefixes using the existing checkpoint writer."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any, Mapping

from .checkpoint import _write_checkpoint_document
from .tensor_stream import TensorStreamError, _digest


class TensorCheckpointFile:
    """Single-writer tensor checkpoint storage; restored evidence is reverified by the coordinator.

    File replacement is atomic and content is fsynced before replacement.
    This supplies process-interruption recovery, not multi-writer fencing or
    guaranteed power-loss survival of directory metadata on every filesystem.
    """

    def __init__(self, path: str | Path, *, max_bytes: int = 64 * 1024 * 1024) -> None:
        """Mathematics: bind one checkpoint path and a positive serialized byte budget."""
        if type(max_bytes) is not int or max_bytes < 1:
            raise TensorStreamError("tensor checkpoint byte budget must be positive")
        self.path = Path(path)
        self.max_bytes = max_bytes

    @staticmethod
    def _validate(document: Any) -> dict[str, Any]:
        """Mathematics: require the v1 prefix envelope and its canonical content digest."""
        if not isinstance(document, dict) or set(document) != {
            "schema", "plan_digest", "tiles", "checkpoint_digest",
        }:
            raise TensorStreamError("tensor checkpoint fields are invalid")
        if document["schema"] != "mailcpu.tensor-matmul-checkpoint.v1":
            raise TensorStreamError("unsupported tensor checkpoint schema")
        plan = document["plan_digest"]
        if (not isinstance(plan, str) or len(plan) != 64
                or any(c not in "0123456789abcdef" for c in plan)
                or not isinstance(document["tiles"], list)):
            raise TensorStreamError("tensor checkpoint plan or prefix is invalid")
        if document["checkpoint_digest"] != _digest({
            key: value for key, value in document.items() if key != "checkpoint_digest"
        }):
            raise TensorStreamError("tensor checkpoint digest mismatch")
        return document

    def save(self, checkpoint: Mapping[str, Any]) -> None:
        """Mathematics: publish one bounded detached prefix through the shared atomic writer."""
        if not isinstance(checkpoint, Mapping):
            raise TensorStreamError("tensor checkpoint must be a mapping")
        document = self._validate(deepcopy(dict(checkpoint)))
        # Match the existing writer's exact encoding and formatting.
        encoded = (json.dumps(document, indent=2, sort_keys=True) + "\n").encode("utf-8")
        # Windows text output translates LF to CRLF; count that expansion too.
        import os
        size = len(encoded) + encoded.count(b"\n") * (len(os.linesep) - 1)
        if size > self.max_bytes:
            raise TensorStreamError("tensor checkpoint exceeds byte budget")
        _write_checkpoint_document(document, self.path)

    def load(self) -> dict[str, Any] | None:
        """Mathematics: read a bounded committed prefix, or return absence for a new calculation."""
        try:
            with self.path.open("rb") as stream:
                encoded = stream.read(self.max_bytes + 1)
        except FileNotFoundError:
            return None
        if len(encoded) > self.max_bytes:
            raise TensorStreamError("tensor checkpoint exceeds byte budget")
        try:
            document = json.loads(encoded)
        except (ValueError, UnicodeError) as exc:
            raise TensorStreamError("invalid tensor checkpoint JSON") from exc
        return self._validate(document)
