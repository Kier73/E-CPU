"""Persistent path session for receiver-side MailCPU transit computation."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Callable, Mapping

from .classifier import HypervisorExecutionResult
from .headless import HeadlessOS
from .hypervisor_transport import (
    HypervisorOperationChannel,
    HypervisorOperationResultChannel,
)
from .transit_compute import TransitComputeHost
from .transit_worker import TransitComputeWorker


class TransitComputeSession:
    """One receiver-side computation path with state derived from its protocol and execution ledgers."""

    def __init__(
        self,
        worker: TransitComputeWorker,
        request: HypervisorOperationChannel,
        response: HypervisorOperationResultChannel,
    ) -> None:
        """Mathematics: compose path state Σ=Σ_request×Σ_worker×Σ_response without duplicating any authoritative ledger."""

        if not isinstance(worker, TransitComputeWorker):
            raise TypeError("transit compute session requires a TransitComputeWorker")
        if not isinstance(request, HypervisorOperationChannel):
            raise TypeError("transit compute session requires a HypervisorOperationChannel request")
        if not isinstance(response, HypervisorOperationResultChannel):
            raise TypeError("transit compute session requires a HypervisorOperationResultChannel response")

        inbound = request.channel
        outbound = response.channel
        if inbound.destination != inbound.source:
            raise ValueError("transit session request channel must be receiver-bound")
        if outbound.source != inbound.source or outbound.destination != inbound.peer:
            raise ValueError("transit session response channel must return to the request peer")
        if response.operation_source != inbound.peer or response.operation_channel != inbound.channel:
            raise ValueError("transit session response identity must match the request peer and channel")

        self.worker = worker
        self.request = request
        self.response = response

    @property
    def phase(self) -> str:
        """Mathematics: classify path phase from live protocol state, with no duplicate session-side state variable."""

        if self.request.channel.peek() is not None:
            return "request-ready"
        if self.response.channel.pending_sequences():
            return "response-unacknowledged"
        return "idle"

    def state(self) -> dict[str, object]:
        """Mathematics: expose a diagnostic projection of causal cursors and pending effects, not a second source of truth."""

        request_channel = self.request.channel
        response_channel = self.response.channel
        return {
            "phase": self.phase,
            "request": {
                "source": request_channel.source,
                "peer": request_channel.peer,
                "channel": request_channel.channel,
                "next_receive_sequence": request_channel.next_receive_sequence,
            },
            "response": {
                "source": response_channel.source,
                "peer": response_channel.peer,
                "channel": response_channel.channel,
                "pending_sequences": list(response_channel.pending_sequences()),
            },
        }

    def serve_once(self) -> HypervisorExecutionResult | None:
        """Mathematics: apply at most one receiver transition T_q and let the existing response-before-ACK rule preserve retryability."""

        return self.worker.serve_once(self.request, self.response)

    def snapshot(self) -> dict[str, object]:
        """Mathematics: checkpoint the complete path product only when request and response channels satisfy the worker's quiescence invariant."""

        return self.worker.snapshot(self.request, self.response)

    def save_checkpoint(self, path: str | os.PathLike[str]) -> str:
        """Mathematics: atomically persist canonical checkpoint C only when Q=0, fsync(C), then replace the prior durable checkpoint."""

        target = Path(path)
        if not str(target):
            raise ValueError("transit session checkpoint path must be non-empty")
        payload = self.snapshot()
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8") + b"\n"
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
        digest = payload.get("digest")
        if not isinstance(digest, str):
            raise ValueError("transit worker checkpoint did not contain an integrity digest")
        return digest

    @classmethod
    def from_snapshot(
        cls,
        payload: Mapping[str, Any],
        request_transport: Any,
        response_transport: Any,
        compute_host_factory: Callable[[HeadlessOS, int], TransitComputeHost] | None = None,
    ) -> "TransitComputeSession":
        """Mathematics: restore path product Σ from its worker/channel checkpoint, reattaching the exact backend manifest and caller-rebound transports."""

        worker, request, response = TransitComputeWorker.from_snapshot(
            payload,
            request_transport,
            response_transport,
            compute_host_factory=compute_host_factory,
        )
        return cls(worker, request, response)

    @classmethod
    def from_checkpoint(
        cls,
        path: str | os.PathLike[str],
        request_transport: Any,
        response_transport: Any,
        compute_host_factory: Callable[[HeadlessOS, int], TransitComputeHost] | None = None,
    ) -> "TransitComputeSession":
        """Mathematics: parse persisted checkpoint C and admit continuation only after digest, schema, backend manifest, and channel invariants verify."""

        source = Path(path)
        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"cannot read transit session checkpoint: {exc}") from exc
        if not isinstance(payload, Mapping):
            raise ValueError("transit session checkpoint root must be a mapping")
        return cls.from_snapshot(payload, request_transport, response_transport, compute_host_factory)
