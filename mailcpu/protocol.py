"""Typed request/reply protocol for lifting kernel syscalls onto the MailCPU bus."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Protocol

from ._codec import decode_transport_value, encode_transport_value
from .bus import BusMessage, MailboxBus
from .bytecode import BytecodeError
from .datagram import DatagramError
from .elf import ElfError
from .fs import FsError
from .kernel import KernelError
from .memory import VirtualMemoryError
from .owned_network import OwnedNetworkError
from .signals import SignalError
from .stream import StreamError

# Convert known kernel domain errors to structured Err replies.
SYSCALL_ERRORS = (
    KernelError,
    FsError,
    VirtualMemoryError,
    DatagramError,
    StreamError,
    OwnedNetworkError,
    SignalError,
    BytecodeError,
    ElfError,
    KeyError,
    IndexError,
    ValueError,
    TypeError,
    OverflowError,
)


class SyscallDispatcher(Protocol):
    """The minimal process syscall surface that can sit behind the wire server."""

    def syscall(self, pid: int, syscall_name: str, **args: Any) -> Any:
        """Mathematics: evaluate `δ(pid,syscall_name,args)` and return a value or raise an explicit failure."""

        ...


@dataclass(frozen=True)
class SyscallRequest:
    """A structured syscall request encoded as a bus payload."""

    request_id: str
    pid: int
    name: str
    args: dict[str, Any]


@dataclass(frozen=True)
class SyscallResponse:
    """A structured syscall result or explicit failure response."""

    request_id: str
    ok: bool
    result: Any = None
    error: str | None = None




def encode_request(request: SyscallRequest) -> dict[str, Any]:
    """Mathematics: serialize request identity and arguments without changing the request tuple."""

    return {
        "request_id": request.request_id,
        "pid": request.pid,
        "name": request.name,
        "args": encode_transport_value(request.args),
    }


def decode_request(payload: dict[str, Any]) -> SyscallRequest:
    """Mathematics: invert `encode_request` on the typed request fields, rejecting missing identity components."""

    request = SyscallRequest(
        request_id=str(payload["request_id"]),
        pid=int(payload["pid"]),
        name=str(payload["name"]),
        args=dict(decode_transport_value(dict(payload.get("args", {})))),
    )
    if not request.request_id or request.pid <= 0 or not request.name:
        raise ValueError("syscall request identity is invalid")
    return request


def encode_response(response: SyscallResponse) -> dict[str, Any]:
    """Mathematics: serialize response sum type `Ok(result) | Err(error)` as a tagged payload."""

    return {
        "request_id": response.request_id,
        "ok": response.ok,
        "result": encode_transport_value(response.result),
        "error": response.error,
    }


def decode_response(payload: dict[str, Any]) -> SyscallResponse:
    """Mathematics: decode the tagged response and preserve its success/failure partition."""

    return SyscallResponse(
        request_id=str(payload["request_id"]),
        ok=bool(payload["ok"]),
        result=decode_transport_value(payload.get("result")),
        error=payload.get("error"),
    )


def _request_fingerprint(request: SyscallRequest) -> str:
    """Mathematics: compute request identity `f(r)=SHA256(JSON_canonical(encode(r)))` for duplicate detection."""

    canonical = json.dumps(encode_request(request), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


class SyscallClient:
    """Client-side syscall message producer and response consumer."""

    def __init__(self, bus: MailboxBus, pid: int, server_endpoint: str = "kernel") -> None:
        """Mathematics: bind client identity `endpoint = proc:pid` to the shared bus."""

        self.bus = bus
        self.pid = pid
        self.server_endpoint = server_endpoint
        self._next_request = 1

    def submit(self, name: str, **args: Any) -> str:
        """Mathematics: emit request `r_n` to `kernel` and return fresh request identity `req-n`."""

        request_id = f"req-{self._next_request:08d}"
        self._next_request += 1
        request = SyscallRequest(request_id, self.pid, name, args)
        self.bus.send(
            f"proc:{self.pid}",
            self.server_endpoint,
            "syscall.request",
            encode_request(request),
            reply_to=f"proc:{self.pid}",
        )
        return request_id

    def receive(self) -> SyscallResponse | None:
        """Mathematics: consume at most one response from `Q_proc:pid`, returning `⊥` when empty."""

        message = self.bus.receive(f"proc:{self.pid}")
        if message is None:
            return None
        if message.kind != "syscall.response":
            raise ValueError(f"unexpected client message kind: {message.kind}")
        if message.source != self.server_endpoint or message.destination != f"proc:{self.pid}":
            raise ValueError("syscall response identity mismatch")
        return decode_response(message.payload)


class SyscallServer:
    """Kernel-side request dispatcher over the virtual bus."""

    def __init__(self, bus: MailboxBus, kernel: SyscallDispatcher, endpoint: str = "kernel") -> None:
        """Mathematics: bind server endpoint `K` and the kernel transition function `δ_syscall`."""

        self.bus = bus
        self.kernel = kernel
        self.endpoint = endpoint
        self._responses: dict[str, tuple[str, SyscallResponse]] = {}

    def serve_once(self) -> SyscallResponse | None:
        """Mathematics: apply one request transition and emit exactly one `Ok | Err` reply when a request exists."""

        message = self.bus.receive(self.endpoint)
        if message is None:
            return None
        if message.kind != "syscall.request":
            raise ValueError(f"unexpected server message kind: {message.kind}")
        request = decode_request(message.payload)
        expected_source = f"proc:{request.pid}"
        if message.source != expected_source or message.destination != self.endpoint:
            raise ValueError("syscall request identity mismatch")
        if message.reply_to is not None and message.reply_to != expected_source:
            raise ValueError("syscall reply route is not owned by request source")
        fingerprint = _request_fingerprint(request)
        cached = self._responses.get(request.request_id)
        if cached is not None:
            if cached[0] == fingerprint:
                response = cached[1]
            else:
                response = SyscallResponse(
                    request.request_id,
                    False,
                    error="request id was reused with different contents",
                )
        else:
            try:
                result = self.kernel.syscall(request.pid, request.name, **request.args)
                response = SyscallResponse(request.request_id, True, result=result)
            except SYSCALL_ERRORS as exc:
                response = SyscallResponse(request.request_id, False, error=str(exc))
            self._responses[request.request_id] = (fingerprint, response)
        destination = expected_source
        self.bus.send(
            self.endpoint,
            destination,
            "syscall.response",
            encode_response(response),
            reply_to=message.message_id,
        )
        return response

    def snapshot(self) -> dict[str, Any]:
        """Mathematics: serialize idempotency relation `C[request_id]=(fingerprint,response)` for crash continuation."""

        return {
            "version": 1,
            "endpoint": self.endpoint,
            "responses": {
                request_id: {
                    "fingerprint": fingerprint,
                    "response": encode_response(response),
                }
                for request_id, (fingerprint, response) in sorted(self._responses.items())
            },
        }

    @classmethod
    def from_snapshot(
        cls,
        bus: MailboxBus,
        kernel: SyscallDispatcher,
        payload: dict[str, Any],
    ) -> "SyscallServer":
        """Mathematics: restore cache `C` and reject malformed request identities before serving retries."""

        if int(payload.get("version", 1)) != 1:
            raise ValueError("unsupported syscall server snapshot version")
        server = cls(bus, kernel, str(payload.get("endpoint", "kernel")))
        for request_id, raw in payload.get("responses", {}).items():
            fingerprint = str(raw["fingerprint"])
            if len(fingerprint) != 64:
                raise ValueError(f"invalid syscall request fingerprint: {request_id}")
            response = decode_response(dict(raw["response"]))
            if response.request_id != str(request_id):
                raise ValueError(f"syscall response request id mismatch: {request_id}")
            server._responses[str(request_id)] = (fingerprint, response)
        return server
