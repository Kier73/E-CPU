"""Crash-recoverable append-only mailbox transport for MailCPU communication state."""

from __future__ import annotations

import hashlib
import json
import os
from collections import deque
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from ._codec import decode_canonical_value, encode_canonical_value
from .model import Message


def encode_canonical_value(value: Any) -> Any:
    """Mathematics: embed finite values injectively, tagging bytes, tuples, and lists so `decode(encode(x))=x`."""

    if isinstance(value, bytes):
        return {"bytes_hex": value.hex()}
    if isinstance(value, tuple):
        return {"tuple": [encode_canonical_value(item) for item in value]}
    if isinstance(value, list):
        return {"list": [encode_canonical_value(item) for item in value]}
    if isinstance(value, dict):
        return {
            "dict": [
                [str(key), encode_canonical_value(item)]
                for key, item in sorted(value.items(), key=lambda item: str(item[0]))
            ]
        }
    return value


def decode_canonical_value(value: Any) -> Any:
    """Mathematics: invert `encode_canonical_value` over its tagged finite value algebra."""

    if not isinstance(value, dict):
        return value
    if set(value) == {"bytes_hex"}:
        return bytes.fromhex(str(value["bytes_hex"]))
    if set(value) == {"tuple"}:
        return tuple(decode_canonical_value(item) for item in value["tuple"])
    if set(value) == {"list"}:
        return [decode_canonical_value(item) for item in value["list"]]
    if set(value) == {"dict"}:
        return {str(pair[0]): decode_canonical_value(pair[1]) for pair in value["dict"]}
    return {str(key): decode_canonical_value(item) for key, item in value.items()}


def _durable_message_snapshot(message: Message) -> dict[str, Any]:
    """Mathematics: project `Message` into a durable record while preserving structured body type identity."""

    return {
        "sender": message.sender,
        "recipient": message.recipient,
        "op": message.op,
        "addr": message.addr,
        "value": message.value,
        "seq": message.seq,
        "body": encode_canonical_value(message.body),
        "message_id": message.message_id,
    }


def _durable_message_from_snapshot(payload: dict[str, Any]) -> Message:
    """Mathematics: reconstruct exactly the message fields and body algebra represented by `_durable_message_snapshot`."""

    decoded = decode_canonical_value(payload.get("body", {"tuple": []}))
    if not isinstance(decoded, tuple):
        raise DurableTransportError("durable message body must decode to a tuple")
    return Message(
        sender=str(payload.get("sender", "")),
        recipient=str(payload.get("recipient", "")),
        op=str(payload.get("op", "")),
        addr=str(payload.get("addr", "")),
        value=None if payload.get("value") is None else int(payload["value"]),
        seq=int(payload.get("seq", 0)),
        body=decoded,
        message_id=str(payload.get("message_id", "")),
    )


class DurableTransportError(Exception):
    """A durable mailbox log is malformed, tampered with, or violates its replay invariant."""


class DurableMailboxTransport:
    """A single-writer, append-only mailbox transport with replayable queue state."""

    _VERSION = 1
    _GENESIS = b"\x00" * 32

    def __init__(self, path: str | Path) -> None:
        """Mathematics: initialize `Q=Π_addr []`, identity index `L=∅`, log head `H=0^256`, and sequence `n=0`, then replay `path`."""

        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self.path.with_name(self.path.name + ".lock")
        self._queues: dict[str, deque[Message]] = {}
        self._locations: dict[str, str] = {}
        self._next_id = 1
        self._sequence = 0
        self._head = self._GENESIS
        if not self.path.exists():
            self.path.touch()
        self._replay()

    def send(self, addr: str, msg: Message) -> Message:
        """Mathematics: allocate fresh identity `m_n`, durably append `ENQUEUE(m_n)`, then apply `Q_addr:=Q_addr||[m_n]`."""

        if not addr:
            raise ValueError("mailbox address must be non-empty")
        message_id = f"m{self._next_id:08d}"
        stored = Message(
            sender=msg.sender,
            recipient=addr,
            op=msg.op,
            addr=msg.addr,
            value=msg.value,
            seq=msg.seq,
            body=msg.body,
            message_id=message_id,
        )
        message_payload = {"addr": addr, "message": _durable_message_snapshot(stored)}
        self._commit("enqueue", message_payload)
        self._apply_event("enqueue", message_payload)
        return stored

    def poll(self, addr: str) -> Message | None:
        """Mathematics: if `Q_addr=[m]||R`, durably append `DEQUEUE(addr,m)` before returning `m`; otherwise return `⊥`."""

        queue = self._queues.get(addr)
        if not queue:
            return None
        message = queue[0]
        payload = {"addr": addr, "message_id": message.message_id}
        self._commit("dequeue", payload)
        self._apply_event("dequeue", payload)
        return message

    def consume(self, msg: Message) -> bool:
        """Mathematics: if `L[msg.id]=addr`, durably append `CONSUME(addr,msg.id)` and remove exactly that identity; otherwise return `False`."""

        addr = self._locations.get(msg.message_id)
        if addr is None:
            return False
        payload = {"addr": addr, "message_id": msg.message_id}
        self._commit("consume", payload)
        self._apply_event("consume", payload)
        return True

    def list(self, addr: str) -> tuple[Message, ...]:
        """Mathematics: project `Q_addr` without changing the durable state, yielding an immutable FIFO view."""

        return tuple(self._queues.get(addr, ()))

    def pending(self, addr: str | None = None) -> int:
        """Mathematics: calculate `|Q|=Σ_a|Q_a|`, or `|Q_addr|` when an address is supplied."""

        if addr is not None:
            return len(self._queues.get(addr, ()))
        return sum(len(queue) for queue in self._queues.values())

    def snapshot(self) -> dict[str, Any]:
        """Mathematics: expose durable identity metadata `(path,n,H,next_id)` without duplicating mailbox contents."""

        return {
            "version": self._VERSION,
            "path": str(self.path),
            "sequence": self._sequence,
            "head_hex": self._head.hex(),
            "next_id": self._next_id,
            "pending": self.pending(),
        }

    def verify(self) -> bool:
        """Mathematics: replay a fresh copy and require equal `(n,H,Q,L,next_id)` to certify the current log."""

        candidate = type(self)(self.path)
        return (
            candidate._sequence == self._sequence
            and candidate._head == self._head
            and candidate._next_id == self._next_id
            and candidate._queues == self._queues
            and candidate._locations == self._locations
        )

    def _replay(self) -> None:
        """Mathematics: fold complete log records `S_{i+1}=apply(S_i,event_i)` while checking sequence, hash-chain, and message identity invariants."""

        raw_data = self.path.read_bytes()
        complete_length = len(raw_data)
        if raw_data and not raw_data.endswith(b"\n"):
            complete_length = raw_data.rfind(b"\n") + 1
            self._truncate(complete_length)
            raw_data = raw_data[:complete_length]
        for line in raw_data.splitlines():
            if not line:
                continue
            try:
                record = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise DurableTransportError("durable mailbox contains an invalid complete record") from exc
            self._verify_record(record)
            event = str(record["event"])
            payload = dict(record["payload"])
            self._apply_event(event, payload)
            self._sequence = int(record["sequence"])
            self._head = bytes.fromhex(str(record["receipt"]))

    def _verify_record(self, record: Any) -> None:
        """Mathematics: require `seq=n+1`, `prev=H_n`, and `receipt=SHA256(prev||canonical(record_without_receipt))`."""

        if not isinstance(record, dict) or int(record.get("version", -1)) != self._VERSION:
            raise DurableTransportError("unsupported durable mailbox record")
        sequence = int(record.get("sequence", -1))
        if sequence != self._sequence + 1:
            raise DurableTransportError("durable mailbox sequence discontinuity")
        previous = bytes.fromhex(str(record.get("previous", "")))
        if previous != self._head:
            raise DurableTransportError("durable mailbox hash-chain predecessor mismatch")
        unsigned = {
            "event": str(record.get("event", "")),
            "payload": record.get("payload", {}),
            "previous": previous.hex(),
            "sequence": sequence,
            "version": self._VERSION,
        }
        canonical = json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode("utf-8")
        expected = hashlib.sha256(previous + canonical).hexdigest()
        if str(record.get("receipt", "")) != expected:
            raise DurableTransportError("durable mailbox receipt mismatch")

    def _commit(self, event: str, payload: dict[str, Any]) -> None:
        """Mathematics: append and fsync one receipt `H_{n+1}=SHA256(H_n||canonical(event,payload,n+1))` before exposing its state transition."""

        sequence = self._sequence + 1
        unsigned = {
            "event": event,
            "payload": payload,
            "previous": self._head.hex(),
            "sequence": sequence,
            "version": self._VERSION,
        }
        canonical = json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode("utf-8")
        receipt = hashlib.sha256(self._head + canonical).hexdigest()
        record = dict(unsigned)
        record["receipt"] = receipt
        line = json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
        with self._locked_append() as stream:
            stream.write(line)
            stream.flush()
            os.fsync(stream.fileno())
        self._sequence = sequence
        self._head = bytes.fromhex(receipt)

    def _apply_event(self, event: str, payload: dict[str, Any]) -> None:
        """Mathematics: apply one replay event to `(Q,L,next_id)`, rejecting duplicate identities and non-head dequeues."""

        addr = str(payload.get("addr", ""))
        if event == "enqueue":
            message = _durable_message_from_snapshot(dict(payload["message"]))
            if not addr or message.recipient != addr or not message.message_id:
                raise DurableTransportError("invalid enqueue event")
            if message.message_id in self._locations:
                raise DurableTransportError("duplicate durable message identity")
            self._queues.setdefault(addr, deque()).append(message)
            self._locations[message.message_id] = addr
            if not message.message_id.startswith("m"):
                raise DurableTransportError("invalid durable message identity")
            self._next_id = max(self._next_id, int(message.message_id[1:]) + 1)
            return
        if event not in {"dequeue", "consume"}:
            raise DurableTransportError(f"unknown durable mailbox event: {event}")
        message_id = str(payload.get("message_id", ""))
        if self._locations.get(message_id) != addr:
            raise DurableTransportError("durable removal references unknown message")
        queue = self._queues[addr]
        if event == "dequeue" and (not queue or queue[0].message_id != message_id):
            raise DurableTransportError("durable dequeue is not FIFO-head removal")
        for index, message in enumerate(queue):
            if message.message_id == message_id:
                del queue[index]
                break
        del self._locations[message_id]

    @contextmanager
    def _locked_append(self) -> Iterator[Any]:
        """Mathematics: serialize append critical section `A=(lock,append,flush)` so one writer emits one complete log record."""

        self._lock_path.touch(exist_ok=True)
        with self._lock_path.open("a+b") as lock:
            lock.seek(0)
            if lock.tell() == 0:
                lock.write(b"0")
                lock.flush()
            lock.seek(0)
            locking_module = None
            try:
                import msvcrt as locking_module
            except ImportError:
                try:
                    import fcntl as locking_module
                except ImportError:
                    locking_module = None
            if locking_module is not None and hasattr(locking_module, "locking"):
                locking_module.locking(lock.fileno(), locking_module.LK_LOCK, 1)
            elif locking_module is not None:
                locking_module.flock(lock.fileno(), locking_module.LOCK_EX)
            try:
                with self.path.open("ab") as stream:
                    yield stream
            finally:
                if locking_module is not None and hasattr(locking_module, "locking"):
                    lock.seek(0)
                    locking_module.locking(lock.fileno(), locking_module.LK_UNLCK, 1)
                elif locking_module is not None:
                    locking_module.flock(lock.fileno(), locking_module.LOCK_UN)

    def _truncate(self, length: int) -> None:
        """Mathematics: truncate the log file by replacing byte domain `[length,|log|)` with `∅`."""

        with self.path.open("r+b") as stream:
            stream.truncate(length)
            stream.flush()
            os.fsync(stream.fileno())

