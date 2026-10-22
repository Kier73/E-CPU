r"""Content-addressed page storage bridged through the replicated mailbox path.

For page bytes ``b`` the storage identity is ``h=SHA256(b)``.  Local files
provide crash-safe content persistence, while ``ReplicatedMailboxNode`` carries
page put/get requests and responses between participating hosts.  A response
is accepted only when its request identity and digest agree, so retransmission
can add time and energy to the path without adding a second page.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import tempfile
import threading
import time
from typing import Any, Callable, Mapping

from .model import Message
from .replicated_mailbox import ReplicatedMailboxError, ReplicatedMailboxNode


class RemotePageError(RuntimeError):
    """A remote page request, content identity, or local CAS transition failed."""


class RemotePageMissing(RemotePageError):
    """No local or remote provider supplied the requested page identity."""


class RemotePageTimeout(RemotePageError):
    """A remote page request remained unresolved through its bounded wait interval."""


class RemotePageStore:
    """Crash-safe local page CAS with durable mailbox-mediated remote transfer."""

    _VERSION = 1

    def __init__(
        self,
        root: str | Path,
        node: ReplicatedMailboxNode,
        *,
        page_size: int = 4096,
        default_peer: str | None = None,
        pump: Callable[[], None] | None = None,
        timeout: float = 5.0,
    ) -> None:
        """Mathematics: initialize `CAS[h]`, request set `P`, and response set `R` with `h=SHA256(b)` and `|b|=P` for every admitted page."""

        if page_size <= 0:
            raise RemotePageError("page_size must be positive")
        if timeout <= 0:
            raise RemotePageError("timeout must be positive")
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.node = node
        self.page_size = int(page_size)
        self.default_peer = default_peer
        self._pump = pump
        self.timeout = float(timeout)
        self._lock = threading.RLock()
        self._pending: dict[str, tuple[str, str]] = {}
        self._failures: dict[str, str] = {}

    @property
    def response_address(self) -> str:
        """Mathematics: derive the unique response mailbox `A_r=page:responses:node_id` for this requester."""

        return self._response_address(self.node.store.node_id)

    def put_page(self, data: bytes, peer: str | None = None) -> str:
        """Mathematics: store `b` at `CAS[SHA256(b)]`, then require remote mailbox quorum when `peer≠self`."""

        payload = self._validate_page(data)
        digest = self._digest(payload)
        self._write_local(digest, payload)
        selected_peer = self.default_peer if peer is None else peer
        if selected_peer and selected_peer != self.node.store.node_id:
            operation_id = self._send_message(
                selected_peer,
                "PAGE_PUT",
                (digest, payload),
            )
            self._wait_for_quorum(operation_id)
        return digest

    def get_page(self, digest: str, peer: str | None = None, timeout: float | None = None) -> bytes:
        """Mathematics: return `CAS[h]`, or complete request/response `GET(h)→DATA(h,b)` with `SHA256(b)=h`."""

        self._validate_digest(digest)
        local = self._read_local(digest)
        if local is not None:
            return local
        selected_peer = self.default_peer if peer is None else peer
        if not selected_peer or selected_peer == self.node.store.node_id:
            raise RemotePageMissing(f"page is not present locally and has no remote provider: {digest}")
        request_id = self.request_page(digest, selected_peer)
        deadline = time.monotonic() + (self.timeout if timeout is None else float(timeout))
        while True:
            self.service()
            local = self._read_local(digest)
            if local is not None:
                self._pending.pop(request_id, None)
                return local
            failure = self._failures.pop(request_id, None)
            if failure is not None:
                raise RemotePageMissing(failure)
            if time.monotonic() >= deadline:
                self._pending.pop(request_id, None)
                raise RemotePageTimeout(f"remote page request timed out: {digest}")
            if self._pump is not None:
                self._pump()
            time.sleep(min(0.001, max(0.0, deadline - time.monotonic())))

    def request_page(self, digest: str, peer: str | None = None) -> str:
        """Mathematics: create idempotent request `r=(node_id,digest)` and persist `GET(r,digest,response_address)` before waiting."""

        self._validate_digest(digest)
        selected_peer = self.default_peer if peer is None else peer
        if not selected_peer or selected_peer == self.node.store.node_id:
            raise RemotePageMissing(f"remote provider is required for page request: {digest}")
        request_id = self._request_id(digest)
        if request_id in self._pending:
            return request_id
        operation_id = self._send_message(
            selected_peer,
            "PAGE_GET",
            (request_id, digest, self.response_address),
        )
        self._pending[request_id] = (digest, selected_peer)
        try:
            self._wait_for_quorum(operation_id)
        except Exception:
            self._pending.pop(request_id, None)
            raise
        return request_id

    def service(self) -> int:
        """Mathematics: fold replicated mailbox frames, then apply each local request/response exactly once under `Q := poll(Q)` and CAS identity checks."""

        processed = self.node.service()
        inbox = self._inbox(self.node.store.node_id)
        while True:
            queued = self.node.list(inbox)
            if not queued:
                break
            message = queued[0]
            self._handle_request(message)
            if self.node.poll(inbox) is None:
                raise RemotePageError("page request disappeared before durable dequeue")
            processed += 1
        while True:
            queued = self.node.list(self.response_address)
            if not queued:
                break
            message = queued[0]
            self._handle_response(message)
            if self.node.poll(self.response_address) is None:
                raise RemotePageError("page response disappeared before durable dequeue")
            processed += 1
        return processed

    def has_page(self, digest: str) -> bool:
        """Mathematics: test membership `h∈dom(CAS)` while validating `CAS[h]=b` and `SHA256(b)=h` when present."""

        self._validate_digest(digest)
        return self._read_local(digest) is not None

    def drop_local_cache(self, digest: str) -> None:
        """Mathematics: remove local `CAS[h]` while preserving the remote equivalence class addressed by `h`."""

        self._validate_digest(digest)
        with self._lock:
            try:
                self._path(digest).unlink()
            except FileNotFoundError:
                return

    def page_ids(self) -> tuple[str, ...]:
        """Mathematics: expose `sort(dom(CAS))` after validating every local content identity."""

        result: list[str] = []
        for path in sorted(self.root.glob("*.page")):
            digest = path.stem
            self._validate_digest(digest)
            if self._read_local(digest) is None:
                raise RemotePageError(f"page path disappeared during enumeration: {digest}")
            result.append(digest)
        return tuple(result)

    def snapshot(self) -> dict[str, object]:
        """Mathematics: serialize provider identity and pending relation `P={r↦(h,peer)}` without duplicating CAS bytes."""

        return {
            "version": self._VERSION,
            "root": str(self.root),
            "page_size": self.page_size,
            "node_id": self.node.store.node_id,
            "default_peer": self.default_peer,
            "pending": {
                request_id: {"digest": digest, "peer": peer}
                for request_id, (digest, peer) in sorted(self._pending.items())
            },
        }

    @classmethod
    def from_snapshot(
        cls,
        payload: Mapping[str, Any],
        node: ReplicatedMailboxNode,
        *,
        root: str | Path | None = None,
        pump: Callable[[], None] | None = None,
        timeout: float = 5.0,
    ) -> "RemotePageStore":
        """Mathematics: restore `P` only when snapshot `(node,page_size,root)` agrees with the live provider identity."""

        if int(payload.get("version", -1)) != cls._VERSION:
            raise RemotePageError("unsupported remote page store snapshot")
        if str(payload.get("node_id")) != node.store.node_id:
            raise RemotePageError("remote page store node identity mismatch")
        selected_root = root if root is not None else str(payload["root"])
        store = cls(
            selected_root,
            node,
            page_size=int(payload["page_size"]),
            default_peer=None if payload.get("default_peer") is None else str(payload["default_peer"]),
            pump=pump,
            timeout=timeout,
        )
        for raw_request_id, raw in dict(payload.get("pending", {})).items():
            item = dict(raw)
            digest = str(item["digest"])
            peer = str(item["peer"])
            store._validate_digest(digest)
            if str(raw_request_id) != store._request_id(digest):
                raise RemotePageError("remote page request identity mismatch")
            store._pending[str(raw_request_id)] = (digest, peer)
        return store

    def _handle_request(self, message: Message) -> None:
        """Mathematics: apply `PAGE_PUT` or `PAGE_GET` only when message route and typed body satisfy the request precondition."""

        if message.op == "PAGE_PUT":
            if len(message.body) != 2:
                raise RemotePageError("PAGE_PUT body must be (digest,bytes)")
            digest, data = message.body
            if not isinstance(digest, str) or not isinstance(data, bytes):
                raise RemotePageError("PAGE_PUT body types are invalid")
            self._validate_digest(digest)
            self._validate_page(data)
            if self._digest(data) != digest:
                raise RemotePageError("PAGE_PUT digest mismatch")
            self._write_local(digest, data)
            return
        if message.op != "PAGE_GET" or len(message.body) != 3:
            raise RemotePageError(f"unsupported page request operation: {message.op}")
        request_id, digest, response_address = message.body
        if not isinstance(request_id, str) or not isinstance(digest, str) or not isinstance(response_address, str):
            raise RemotePageError("PAGE_GET body types are invalid")
        self._validate_digest(digest)
        if request_id != f"{message.sender}:page:{digest}" or response_address != self._response_address(message.sender):
            raise RemotePageError("PAGE_GET request identity mismatch")
        data = self._read_local(digest)
        if data is None:
            self._send_response(message.sender, "PAGE_MISS", (request_id, digest, None))
        else:
            self._send_response(message.sender, "PAGE_DATA", (request_id, digest, data))

    def _handle_response(self, message: Message) -> None:
        """Mathematics: accept `DATA(r,h,b)` iff `r↦(h,peer)` is pending and `SHA256(b)=h`; accept `MISS` as explicit absence."""

        if message.op not in {"PAGE_DATA", "PAGE_MISS"} or len(message.body) != 3:
            raise RemotePageError(f"unsupported page response operation: {message.op}")
        request_id, digest, data = message.body
        if not isinstance(request_id, str) or not isinstance(digest, str):
            raise RemotePageError("page response identity is invalid")
        pending = self._pending.get(request_id)
        if pending is None:
            return
        expected_digest, expected_peer = pending
        if message.sender != expected_peer or digest != expected_digest:
            raise RemotePageError("page response peer or digest mismatch")
        self._validate_digest(digest)
        if message.op == "PAGE_MISS":
            self._failures[request_id] = f"remote provider does not contain page: {digest}"
            self._pending.pop(request_id, None)
            return
        if not isinstance(data, bytes):
            raise RemotePageError("PAGE_DATA payload must be bytes")
        self._validate_page(data)
        if self._digest(data) != digest:
            raise RemotePageError("PAGE_DATA digest mismatch")
        self._write_local(digest, data)

    def _send_response(self, peer: str, operation: str, body: tuple[Any, ...]) -> str:
        """Mathematics: emit response `e=(peer,operation,body)` through the same durable replicated mailbox operation algebra."""

        return self._send_message(peer, operation, body, address=self._response_address(peer))

    def _send_message(
        self,
        peer: str,
        operation: str,
        body: tuple[Any, ...],
        *,
        address: str | None = None,
    ) -> str:
        """Mathematics: append one routed message and return its unique local operation identity `o` from the coordinator domain."""

        before = set(self.node.operation_ids())
        self.node.send(
            self._inbox(peer) if address is None else address,
            Message(
                sender=self.node.store.node_id,
                op=operation,
                body=body,
            ),
        )
        created = [operation_id for operation_id in self.node.operation_ids() if operation_id not in before]
        if len(created) != 1:
            raise ReplicatedMailboxError("page message did not create exactly one replication operation")
        return created[0]

    def _wait_for_quorum(self, operation_id: str) -> None:
        """Mathematics: wait until `1+|A(o)|≥q`, pumping the external peer when configured, or preserve the failure explicitly."""

        deadline = time.monotonic() + self.timeout
        while True:
            if self.node.receipt(operation_id).committed:
                return
            if self._pump is not None:
                self._pump()
            self.service()
            if time.monotonic() >= deadline:
                raise RemotePageTimeout(f"page operation did not reach quorum: {operation_id}")
            time.sleep(min(0.001, max(0.0, deadline - time.monotonic())))

    def _validate_page(self, data: bytes) -> bytes:
        """Mathematics: admit exactly the fixed-length page domain `B={b∈bytes:|b|=P}`."""

        if not isinstance(data, bytes) or len(data) != self.page_size:
            raise RemotePageError(f"page payload must contain exactly {self.page_size} bytes")
        return data

    def _validate_digest(self, digest: str) -> None:
        """Mathematics: require `digest∈{0,…,f}^{64}`, the textual SHA-256 domain."""

        if not isinstance(digest, str) or len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise RemotePageError("page digest must be a lowercase SHA-256 value")

    def _digest(self, data: bytes) -> str:
        """Mathematics: calculate the page identity `h=SHA256(data)`."""

        return hashlib.sha256(data).hexdigest()

    def _path(self, digest: str) -> Path:
        """Mathematics: map content identity `h` injectively to local path `root/(h.page)` within the CAS namespace."""

        return self.root / f"{digest}.page"

    def _read_local(self, digest: str) -> bytes | None:
        """Mathematics: resolve `CAS[h]`, returning `∅` for absence and rejecting any present `b` with `SHA256(b)≠h`."""

        path = self._path(digest)
        if not path.exists():
            return None
        try:
            data = path.read_bytes()
        except OSError as error:
            raise RemotePageError(f"cannot read page {digest}: {error}") from error
        self._validate_page(data)
        if self._digest(data) != digest:
            raise RemotePageError(f"local page digest mismatch: {digest}")
        return data

    def _write_local(self, digest: str, data: bytes) -> None:
        """Mathematics: publish `CAS[h]=b` by atomic replace only after `|b|=P` and `SHA256(b)=h` validation."""

        self._validate_digest(digest)
        payload = self._validate_page(data)
        if self._digest(payload) != digest:
            raise RemotePageError("local page write digest mismatch")
        with self._lock:
            existing = self._read_local(digest)
            if existing is not None:
                return
            descriptor, temporary_name = tempfile.mkstemp(prefix=".page-", suffix=".tmp", dir=str(self.root))
            temporary = Path(temporary_name)
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self._path(digest))
                try:
                    directory_descriptor = os.open(str(self.root), os.O_RDONLY)
                except OSError:
                    directory_descriptor = None
                if directory_descriptor is not None:
                    try:
                        os.fsync(directory_descriptor)
                    finally:
                        os.close(directory_descriptor)
            finally:
                if temporary.exists():
                    temporary.unlink()

    def _request_id(self, digest: str) -> str:
        """Mathematics: derive idempotent request identity `r=(requester,digest)` for one content address."""

        return f"{self.node.store.node_id}:page:{digest}"

    @staticmethod
    def _inbox(peer: str) -> str:
        """Mathematics: derive the provider mailbox `A_q(peer)=page:inbox:peer`."""

        return f"page:inbox:{peer}"

    @staticmethod
    def _response_address(peer: str) -> str:
        """Mathematics: derive requester response mailbox `A_r(peer)=page:responses:peer`."""

        return f"page:responses:{peer}"
