"""Deterministic in-memory FIFO message substrate with explicit message identity."""

from __future__ import annotations

from collections import deque
from dataclasses import replace
from typing import Any, Protocol

from ._codec import decode_transport_value as _decode_value
from ._codec import encode_transport_value as _encode_value
from ._codec import message_from_record as _message_from_snapshot
from ._codec import message_to_record as _message_snapshot
from .model import Message


class Transport(Protocol):
    """Message substrate interface for sending, polling, and consuming messages."""

    def send(self, addr: str, msg: Message) -> Message:
        """Mathematics: enqueue `msg` so mailbox state changes by `Q_addr := Q_addr || [msg]`."""

        ...

    def poll(self, addr: str) -> Message | None:
        """Mathematics: FIFO polling applies `Q_addr = [m] || R -> (m, R)` and returns `None` for `Q_addr = []`."""

        ...

    def consume(self, msg: Message) -> bool:
        """Mathematics: remove exactly one message identity from its queue, implementing `Q := Q \\ {msg}`."""

        ...

    def list(self, addr: str) -> tuple[Message, ...]:
        """Mathematics: observe `Q_addr` without changing it, so `list(Q_addr) = Q_addr`."""

        ...


class InMemoryTransport:
    """A deterministic FIFO transport with explicit message identity."""

    def __init__(self) -> None:
        """Mathematics: initialize the empty product state `Q = Π_addr []` and an empty identity map."""

        self._queues: dict[str, deque[Message]] = {}
        self._locations: dict[str, str] = {}
        self._next_id = 1

    def send(self, addr: str, msg: Message) -> Message:
        """Mathematics: append one fresh identity to `Q_addr`, preserving FIFO order under repeated sends."""

        if not addr:
            raise ValueError("mailbox address must be non-empty")
        message_id = f"m{self._next_id:08d}"
        self._next_id += 1
        stored = replace(msg, recipient=addr, message_id=message_id)
        queue = self._queues.setdefault(addr, deque())
        queue.append(stored)
        self._locations[message_id] = addr
        return stored

    def poll(self, addr: str) -> Message | None:
        """Mathematics: compute the FIFO head projection `poll(Q_addr) = head(Q_addr)` and delete that head."""

        queue = self._queues.get(addr)
        if not queue:
            return None
        message = queue.popleft()
        self._locations.pop(message.message_id, None)
        return message

    def consume(self, msg: Message) -> bool:
        """Mathematics: satisfy the postcondition `msg ∉ Q` exactly when its identity is present in the queue product."""

        addr = self._locations.get(msg.message_id)
        if addr is None:
            return False
        queue = self._queues[addr]
        for queued in queue:
            if queued.message_id == msg.message_id:
                queue.remove(queued)
                del self._locations[msg.message_id]
                return True
        return False

    def list(self, addr: str) -> tuple[Message, ...]:
        """Mathematics: return a snapshot of `Q_addr` while preserving the identity `Q'_addr = Q_addr`."""

        return tuple(self._queues.get(addr, ()))

    def pending(self, addr: str | None = None) -> int:
        """Mathematics: compute queue cardinality `|Q| = Σ_addr |Q_addr|`, optionally restricted to one mailbox."""

        if addr is not None:
            return len(self._queues.get(addr, ()))
        return sum(len(queue) for queue in self._queues.values())

    def snapshot(self) -> dict[str, Any]:
        """Mathematics: serialize FIFO state `Q` and identity counter `n` for exact transport continuation."""

        return {
            "version": 1,
            "next_id": self._next_id,
            "queues": {
                address: [_message_snapshot(message) for message in queue]
                for address, queue in sorted(self._queues.items())
            },
        }

    @classmethod
    def from_snapshot(cls, payload: dict[str, Any]) -> "InMemoryTransport":
        """Mathematics: reconstruct `Q` and rebuild identity index `L={message_id↦address}` with duplicate rejection."""

        if int(payload.get("version", 1)) != 1:
            raise ValueError("unsupported transport snapshot version")
        transport = cls()
        transport._next_id = int(payload["next_id"])
        if transport._next_id <= 0:
            raise ValueError("transport next_id must be positive")
        maximum_id = 0
        for raw_address, raw_queue in payload.get("queues", {}).items():
            address = str(raw_address)
            if not address:
                raise ValueError("transport mailbox address must be non-empty")
            queue: deque[Message] = deque()
            for raw_message in raw_queue:
                message = _message_from_snapshot(dict(raw_message))
                if (
                    not message.message_id
                    or not message.message_id.startswith("m")
                    or not message.message_id[1:].isdigit()
                    or int(message.message_id[1:]) <= 0
                    or message.message_id in transport._locations
                ):
                    raise ValueError(f"duplicate or empty transport message id: {message.message_id}")
                if message.recipient != address:
                    raise ValueError("transport message recipient does not match mailbox")
                maximum_id = max(maximum_id, int(message.message_id[1:]))
                queue.append(message)
                transport._locations[message.message_id] = address
            transport._queues[address] = queue
        if transport._next_id <= maximum_id:
            raise ValueError("transport next_id collides with a restored message")
        return transport


