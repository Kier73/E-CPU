"""Deterministic fault-injecting transport over any substrate implementing `Transport`."""

from __future__ import annotations

from dataclasses import dataclass, replace

from .model import Message
from .transport import InMemoryTransport, Transport, _message_from_snapshot, _message_snapshot


@dataclass(frozen=True)
class FaultProfile:
    """Finite deterministic fault schedule indexed by one-based send order."""

    drop_indices: frozenset[int] = frozenset()
    duplicate_indices: frozenset[int] = frozenset()
    delays: tuple[tuple[int, int], ...] = ()
    reorder_ready_messages: bool = False

    def delay_for(self, index: int) -> int:
        """Mathematics: evaluate the finite delay function `d(i)`, defaulting to `0` when `i ∉ dom(d)`."""

        return dict(self.delays).get(index, 0)


@dataclass(frozen=True)
class FaultObservation:
    """Audit record for one injected transport decision."""

    send_index: int
    action: str
    delay: int
    copies: int


class FaultInjectingTransport:
    """A deterministic staged transport wrapper over the FIFO substrate."""

    def __init__(self, profile: FaultProfile, inner: Transport | None = None) -> None:
        """Mathematics: initialize staging multiset `S = ∅`, clock `t = 0`, and send index `i = 0`."""

        self.profile = profile
        self.inner = inner or InMemoryTransport()
        self._staged: list[tuple[int, int, str, Message]] = []
        self._clock = 0
        self._send_index = 0
        self.observations: list[FaultObservation] = []

    def send(self, addr: str, msg: Message) -> Message:
        """Mathematics: schedule `copies(i)` deliveries at `t + d(i)`, or erase them when `i ∈ drops`."""

        self._send_index += 1
        index = self._send_index
        delay = self.profile.delay_for(index)
        if delay < 0:
            raise ValueError("fault delay must be non-negative")
        if index in self.profile.drop_indices:
            self.observations.append(FaultObservation(index, "drop", delay, 0))
            return replace(msg, recipient=addr, message_id=f"dropped-{index:08d}")
        copies = 2 if index in self.profile.duplicate_indices else 1
        for copy in range(copies):
            self._staged.append((self._clock + delay, index, addr, msg))
        self.observations.append(FaultObservation(index, "deliver", delay, copies))
        self._flush()
        return replace(msg, recipient=addr, message_id=f"staged-{index:08d}")

    def poll(self, addr: str) -> Message | None:
        """Mathematics: advance time one unit `t := t + 1`, release due messages, then apply FIFO poll."""

        self.advance(1)
        return self.inner.poll(addr)

    def consume(self, msg: Message) -> bool:
        """Mathematics: delegate identity deletion to the delivered substrate queue, `Q := Q \\ {msg}`."""

        return self.inner.consume(msg)

    def list(self, addr: str) -> tuple[Message, ...]:
        """Mathematics: flush messages with `ready_time ≤ t` and observe the unchanged queue `Q_addr`."""

        self._flush()
        return self.inner.list(addr)

    def advance(self, steps: int = 1) -> None:
        """Mathematics: increment logical time by `steps` and deliver the staged subset `{s : ready(s) ≤ t}`."""

        if steps < 0:
            raise ValueError("steps must be non-negative")
        self._clock += steps
        self._flush()

    def pending_staged(self) -> int:
        """Mathematics: return the cardinality `|S|` of not-yet-delivered staged copies."""

        return len(self._staged)

    def _flush(self) -> None:
        """Mathematics: move all due staged messages into `Q`, sorting by `(ready,index)` or reverse index for reordering."""

        due = [item for item in self._staged if item[0] <= self._clock]
        self._staged = [item for item in self._staged if item[0] > self._clock]
        if self.profile.reorder_ready_messages:
            due.sort(key=lambda item: (item[0], -item[1]))
        else:
            due.sort(key=lambda item: (item[0], item[1]))
        for _, _, addr, message in due:
            self.inner.send(addr, message)

    def snapshot(self) -> dict[str, object]:
        """Mathematics: serialize fault state `(profile,S,t,i,O,Q)` so staged communication resumes exactly."""

        if not isinstance(self.inner, InMemoryTransport):
            raise ValueError("fault transport snapshot requires an InMemoryTransport inner substrate")
        return {
            "version": 1,
            "profile": {
                "drop_indices": sorted(self.profile.drop_indices),
                "duplicate_indices": sorted(self.profile.duplicate_indices),
                "delays": [list(item) for item in self.profile.delays],
                "reorder_ready_messages": self.profile.reorder_ready_messages,
            },
            "inner": self.inner.snapshot(),
            "staged": [
                {"ready": ready, "send_index": send_index, "address": address, "message": _message_snapshot(message)}
                for ready, send_index, address, message in self._staged
            ],
            "clock": self._clock,
            "send_index": self._send_index,
            "observations": [
                {
                    "send_index": observation.send_index,
                    "action": observation.action,
                    "delay": observation.delay,
                    "copies": observation.copies,
                }
                for observation in self.observations
            ],
        }

    @classmethod
    def from_snapshot(cls, payload: dict[str, object]) -> "FaultInjectingTransport":
        """Mathematics: reconstruct staged fault state and validate non-negative clock/index invariants."""

        if int(payload.get("version", 1)) != 1:
            raise ValueError("unsupported fault transport snapshot version")
        raw_profile = dict(payload["profile"])
        profile = FaultProfile(
            frozenset(int(item) for item in raw_profile.get("drop_indices", ())),
            frozenset(int(item) for item in raw_profile.get("duplicate_indices", ())),
            tuple((int(item[0]), int(item[1])) for item in raw_profile.get("delays", ())),
            bool(raw_profile.get("reorder_ready_messages", False)),
        )
        transport = cls(profile, InMemoryTransport.from_snapshot(dict(payload["inner"])))
        transport._clock = int(payload["clock"])
        transport._send_index = int(payload["send_index"])
        if transport._clock < 0 or transport._send_index < 0:
            raise ValueError("fault transport clock and send_index must be non-negative")
        transport._staged = [
            (
                int(raw["ready"]),
                int(raw["send_index"]),
                str(raw["address"]),
                _message_from_snapshot(dict(raw["message"])),
            )
            for raw in payload.get("staged", ())
        ]
        transport.observations = [
            FaultObservation(
                int(raw["send_index"]),
                str(raw["action"]),
                int(raw["delay"]),
                int(raw["copies"]),
            )
            for raw in payload.get("observations", ())
        ]
        return transport
