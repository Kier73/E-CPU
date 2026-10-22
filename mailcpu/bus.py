"""Structured mailbox bus with logical time for system calls and IPC."""

from __future__ import annotations

from collections import deque
import copy
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class BusMessage:
    """A typed request, reply, signal, or data event on the virtual interconnect."""

    message_id: str
    source: str
    destination: str
    kind: str
    payload: dict[str, Any]
    logical_time: int
    reply_to: str | None = None


class MailboxBus:
    """A deterministic address-indexed message bus with explicit logical time."""

    def __init__(self) -> None:
        """Mathematics: initialize `Q = Π_addr []`, message sequence `n = 0`, and logical time `t = 0`."""

        self._queues: dict[str, deque[BusMessage]] = {}
        self._next_id = 1
        self._logical_time = 0

    def send(
        self,
        source: str,
        destination: str,
        kind: str,
        payload: dict[str, Any],
        reply_to: str | None = None,
    ) -> BusMessage:
        """Mathematics: append `m` to `Q_destination` and advance logical time `t := t + 1`."""

        if not source or not destination or not kind:
            raise ValueError("source, destination, and kind must be non-empty")
        self._logical_time += 1
        message = BusMessage(
            message_id=f"b{self._next_id:08d}",
            source=source,
            destination=destination,
            kind=kind,
            payload=copy.deepcopy(dict(payload)),
            logical_time=self._logical_time,
            reply_to=reply_to,
        )
        self._next_id += 1
        self._queues.setdefault(destination, deque()).append(message)
        return message

    def receive(self, destination: str) -> BusMessage | None:
        """Mathematics: apply FIFO projection `Q_destination = [m] || R -> (m, R)`, or return `⊥` for empty `Q`."""

        queue = self._queues.get(destination)
        if not queue:
            return None
        return queue.popleft()

    def peek(self, destination: str) -> tuple[BusMessage, ...]:
        """Mathematics: observe `Q_destination` without mutation, so `Q' = Q`."""

        return tuple(
            BusMessage(
                message.message_id,
                message.source,
                message.destination,
                message.kind,
                copy.deepcopy(message.payload),
                message.logical_time,
                message.reply_to,
            )
            for message in self._queues.get(destination, ())
        )

    def pending(self, destination: str | None = None) -> int:
        """Mathematics: compute `|Q| = Σ_addr |Q_addr|`, optionally restricting the sum to one address."""

        if destination is not None:
            return len(self._queues.get(destination, ()))
        return sum(len(queue) for queue in self._queues.values())

    def remove_matching(self, destination: str, predicate: Callable[[BusMessage], bool]) -> tuple[BusMessage, ...]:
        """Mathematics: remove exactly `M={m∈Q_destination | predicate(m)}` while preserving the order of `Q_destination minus M`."""

        queue = self._queues.get(destination)
        if not queue:
            return ()
        removed: list[BusMessage] = []
        retained: deque[BusMessage] = deque()
        for message in queue:
            (removed if predicate(message) else retained).append(message)
        if retained:
            self._queues[destination] = retained
        else:
            self._queues.pop(destination, None)
        return tuple(removed)

    def snapshot(self) -> dict[str, Any]:
        """Mathematics: serialize the bus state `Q` and counters `(n, t)` for deterministic restoration."""

        return {
            "next_id": self._next_id,
            "logical_time": self._logical_time,
            "queues": {
                address: [
                    {
                        "message_id": message.message_id,
                        "source": message.source,
                        "destination": message.destination,
                        "kind": message.kind,
                        "payload": copy.deepcopy(message.payload),
                        "logical_time": message.logical_time,
                        "reply_to": message.reply_to,
                    }
                    for message in queue
                ]
                for address, queue in sorted(self._queues.items())
            },
        }

    @classmethod
    def from_snapshot(cls, payload: dict[str, Any]) -> "MailboxBus":
        """Mathematics: reconstruct queue product `Q` and counters `(n,t)` without changing message identity or order."""

        bus = cls()
        bus._next_id = int(payload["next_id"])
        bus._logical_time = int(payload["logical_time"])
        if bus._next_id <= 0 or bus._logical_time < 0:
            raise ValueError("bus counters must be positive/non-negative")
        maximum_id = 0
        maximum_time = 0
        for address, raw_queue in payload.get("queues", {}).items():
            address = str(address)
            if not address:
                raise ValueError("bus destination must be non-empty")
            queue: deque[BusMessage] = deque()
            for raw in raw_queue:
                message = BusMessage(
                    str(raw["message_id"]),
                    str(raw["source"]),
                    str(raw["destination"]),
                    str(raw["kind"]),
                    copy.deepcopy(dict(raw["payload"])),
                    int(raw["logical_time"]),
                    raw.get("reply_to"),
                )
                if (
                    not message.message_id.startswith("b")
                    or not message.message_id[1:].isdigit()
                    or int(message.message_id[1:]) <= 0
                    or message.destination != address
                    or not message.source
                    or not message.kind
                    or message.logical_time <= 0
                    or message.logical_time > bus._logical_time
                ):
                    raise ValueError("invalid bus message identity or route")
                maximum_id = max(maximum_id, int(message.message_id[1:]))
                maximum_time = max(maximum_time, message.logical_time)
                queue.append(message)
            bus._queues[address] = queue
        if bus._next_id <= maximum_id or bus._logical_time < maximum_time:
            raise ValueError("bus counters collide with restored messages")
        return bus
