"""BOOT-001B: scoped, immutable M1 pages and M3 records over native mTLS.

No latest pointer, execution rights, quorum replacement, or remote shell.
A receiver owns one namespace, one admitted client DNS identity, and
finite disk/request budgets. Each connection performs one pure GET or
immutable PUT. Only a readback-verified record may proceed to native seal.
"""
from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path
import re
import socket
import tempfile
import time

from .model import Message
from .mtls_transport import accept_mutual_tls, connect_mutual_tls
from .socket_transport import SocketTransportError

PAGE_SIZE = 4096
MAX_RECORD = 512 * 1024
MAX_FRAME = 1024 * 1024
MAX_BYTES = 64 * 1024 * 1024
MAX_ENTRIES = 4096
_KEY = re.compile(r"(?:p-[0-9a-f]{64}|r-generation-[0-9]{20}-[0-9a-f]{64}\.json)\Z")


class RetentionError(ValueError):
    """An immutable storage request was refused or not confirmed."""


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _validate(key, data=None):
    if type(key) is not str or not _KEY.fullmatch(key):
        raise RetentionError("invalid retained key")
    if data is not None:
        if type(data) is not bytes:
            raise RetentionError("retained value must be bytes")
        if key.startswith("p-"):
            if len(data) != PAGE_SIZE or _sha(data) != key[2:]:
                raise RetentionError("page geometry or digest mismatch")
        elif not 0 < len(data) <= MAX_RECORD:
            raise RetentionError("record extent exceeds bound")


class ImmutableRetention:
    """Single-writer durable storage root, owned by the receiver only."""

    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def get(self, key):
        _validate(key)
        path = self.root / key
        if path.is_symlink() or not path.is_file():
            raise RetentionError("retained object missing")
        if path.stat().st_size > MAX_RECORD:
            raise RetentionError("retained object over budget")
        data = path.read_bytes()
        _validate(key, data)
        return data

    def put(self, key, data):
        _validate(key, data)
        path = self.root / key
        if path.is_symlink():
            raise RetentionError("unsafe object path")
        if path.exists():
            if self.get(key) != data:
                raise RetentionError("immutable record conflict")
            return
        entries = list(self.root.iterdir())
        if len(entries) >= MAX_ENTRIES or sum(p.stat().st_size for p in entries) + len(data) > MAX_BYTES:
            raise RetentionError("retention budget exhausted")
        fd, name = tempfile.mkstemp(dir=self.root)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, path)
            if os.name == "posix":
                directory = os.open(self.root, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
        finally:
            if os.path.exists(name):
                os.unlink(name)


def _receive(transport, endpoint, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        msg = transport.poll(endpoint)
        if msg is not None:
            return msg
        if transport.closed:
            break
        time.sleep(0.002)
    raise RetentionError("retention response missing or timed out")


def serve_one(listener, context, storage, *, client_dns, timeout=5.0):
    """Accept one authenticated request; no arbitrary paths or authority ops."""
    transport = accept_mutual_tls(
        listener, "retention", "owner", context,
        expected_peer_dns=client_dns, handshake_timeout=timeout,
        max_frame_size=MAX_FRAME, send_timeout=timeout,
    )
    try:
        msg = _receive(transport, "retention", timeout)
        try:
            if msg.op not in ("GET", "PUT") or len(msg.body) != (1 if msg.op == "GET" else 2):
                raise RetentionError("invalid storage operation")
            key = msg.body[0]
            _validate(key)
            if msg.op == "PUT":
                encoded = msg.body[1]
                if type(encoded) is not str or len(encoded) > (MAX_RECORD + 2)//3*4:
                    raise RetentionError("invalid value extent")
                storage.put(key, base64.b64decode(encoded, validate=True))
                payload = _sha(storage.get(key))
            else:
                payload = base64.b64encode(storage.get(key)).decode("ascii")
            response = Message(sender="retention", op="OK", body=(key, payload))
        except (ValueError, OSError):
            response = Message(sender="retention", op="REFUSED", body=())
        transport.send("owner", response)
    finally:
        transport.close()


class NetworkRetention:
    """Native PageBacking and session-record backing with no local cache."""

    page_size = PAGE_SIZE

    def __init__(self, host, port, context, *, server_dns, timeout=5.0):
        self.host, self.port = host, port
        self.context, self.server_dns, self.timeout = context, server_dns, timeout

    def _request(self, key, data=None):
        _validate(key, data)
        transport = connect_mutual_tls(
            self.host, self.port, "owner", "retention", self.context,
            server_hostname=self.server_dns, timeout=self.timeout,
            handshake_timeout=self.timeout, max_frame_size=MAX_FRAME,
            send_timeout=self.timeout,
        )
        try:
            body = (key,) if data is None else (key, base64.b64encode(data).decode("ascii"))
            transport.send("retention", Message(sender="owner", op="GET" if data is None else "PUT", body=body))
            reply = _receive(transport, "owner", self.timeout)
            if reply.op != "OK" or len(reply.body) != 2 or reply.body[0] != key:
                raise RetentionError("receiver refused retention or returned wrong key")
            if data is not None:
                if reply.body[1] != _sha(data):
                    raise RetentionError("durable readback digest differs")
                return
            result = base64.b64decode(reply.body[1], validate=True)
            _validate(key, result)
            return result
        finally:
            transport.close()

    def put_page(self, data):
        key = _sha(data)
        self._request("p-" + key, data)
        return key

    def get_page(self, digest):
        return self._request("p-" + digest)

    def put_record(self, name, data):
        self._request("r-" + name, data)

    def get_record(self, name):
        return self._request("r-" + name)
