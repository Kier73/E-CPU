"""At-least-once reliable channel built above an unreliable MailCPU transport."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ._codec import decode_transport_value as _decode_value
from ._codec import encode_transport_value as _encode_value
from ._codec import message_from_record as _message_from_snapshot
from ._codec import message_to_record as _message_snapshot
from .model import Message
from .transport import Transport


@dataclass(frozen=True)
class ReliabilityPolicy:
    """Lease, retry, and in-flight window bounds for one reliable channel."""

    lease_ticks: int = 3
    max_attempts: int = 4
    window_size: int = 64


class ReliableChannelError(ValueError):
    """A reliable-channel admission or protocol invariant failed."""


class ReliableChannelWouldBlock(ReliableChannelError):
    """The bounded sender window has no free sequence slot."""


@dataclass
class PendingFrame:
    """Sender-side state for one sequence until its acknowledgement arrives."""

    frame: Message
    attempts: int
    last_sent_tick: int


class ReliableChannel:
    """Sequenced at-least-once channel with receiver deduplication and explicit retry failure."""

    def __init__(
        self,
        transport: Transport,
        source: str,
        destination: str,
        channel: str,
        policy: ReliabilityPolicy | None = None,
    ) -> None:
        """Mathematics: initialize sender sequence `n = 1`, receiver set `D = ∅`, pending map `P = ∅`, and tick `t = 0`, under invariant `|P| ≤ W`."""

        if not source or not destination or not channel:
            raise ValueError("source, destination, and channel must be non-empty")
        self.transport = transport
        self.source = source
        self.destination = destination
        self.channel = channel
        self.policy = policy or ReliabilityPolicy()
        if (
            self.policy.lease_ticks <= 0
            or self.policy.max_attempts <= 0
            or self.policy.window_size <= 0
        ):
            raise ValueError("lease_ticks, max_attempts, and window_size must be positive")
        self._next_sequence = 1
        self._pending: dict[int, PendingFrame] = {}
        self._delivered: set[int] = set()
        self._tick = 0
        self.failed_sequences: list[int] = []

    @property
    def ack_address(self) -> str:
        """Mathematics: derive the injective acknowledgement mailbox `ack(source, channel)`."""

        return f"ack:{self.source}:{self.channel}"

    def send(self, payload: Any) -> int:
        """Mathematics: admit only when `|P|<W`, then assign `s`, emit `F_s`, and insert `P[s]` until `ACK(s)` is observed."""

        if len(self._pending) >= self.policy.window_size:
            raise ReliableChannelWouldBlock(
                f"reliable channel window is full: {self.policy.window_size}"
            )

        sequence = self._next_sequence
        frame = Message(
            sender=self.source,
            recipient=self.destination,
            op="RDATA",
            addr=self.destination,
            body=(self.channel, sequence, payload),
        )
        self.transport.send(self.destination, frame)
        self._next_sequence += 1
        self._pending[sequence] = PendingFrame(frame, 1, self._tick)
        return sequence

    @property
    def available_window(self) -> int:
        """Mathematics: expose free sender capacity `A=max(0,W-|P|)` without changing channel state."""

        return max(0, self.policy.window_size - len(self._pending))

    def receive(self) -> tuple[int, Any] | None:
        """Mathematics: deliver `F_s` iff `s ∉ D`, always emit `ACK(s)`, and suppress duplicate payload delivery."""

        message = self.transport.poll(self.destination)
        if message is None:
            return None
        if message.op != "RDATA" or len(message.body) != 3:
            raise ValueError("unexpected frame on reliable data mailbox")
        channel, sequence, payload = message.body
        if channel != self.channel or not isinstance(sequence, int):
            raise ValueError("reliable frame channel or sequence mismatch")
        self.transport.send(
            self.ack_address_for(message.sender),
            Message(
                sender=self.destination,
                recipient=self.ack_address_for(message.sender),
                op="RACK",
                addr=self.ack_address_for(message.sender),
                body=(self.channel, sequence),
            ),
        )
        if sequence in self._delivered:
            return None
        self._delivered.add(sequence)
        return sequence, payload

    def process_ack(self) -> tuple[int, ...]:
        """Mathematics: remove acknowledged sequences `P := P \\ ACKS` and return the finite set of removed keys."""

        acknowledged: list[int] = []
        while True:
            message = self.transport.poll(self.ack_address)
            if message is None:
                break
            if message.op != "RACK" or len(message.body) != 2:
                raise ValueError("unexpected frame on reliable acknowledgement mailbox")
            channel, sequence = message.body
            if channel != self.channel or not isinstance(sequence, int):
                raise ValueError("reliable acknowledgement channel or sequence mismatch")
            if sequence in self._pending:
                del self._pending[sequence]
                acknowledged.append(sequence)
        return tuple(acknowledged)

    def tick(self) -> tuple[int, ...]:
        """Mathematics: advance `t := t + 1`; resend due `P[s]` until attempts exhaust, then classify `s` as failed."""

        self._tick += 1
        failed: list[int] = []
        for sequence, pending in list(self._pending.items()):
            if self._tick - pending.last_sent_tick < self.policy.lease_ticks:
                continue
            if pending.attempts >= self.policy.max_attempts:
                del self._pending[sequence]
                self.failed_sequences.append(sequence)
                failed.append(sequence)
                continue
            self.transport.send(self.destination, pending.frame)
            pending.attempts += 1
            pending.last_sent_tick = self._tick
        return tuple(failed)

    def pending_sequences(self) -> tuple[int, ...]:
        """Mathematics: expose the ordered domain `sort(dom(P))` of unacknowledged frames."""

        return tuple(sorted(self._pending))

    def ack_address_for(self, sender: str) -> str:
        """Mathematics: derive the receiver-selected acknowledgement route `ack(sender, channel)`."""

        return f"ack:{sender}:{self.channel}"

    def snapshot(self) -> dict[str, Any]:
        """Mathematics: serialize reliable state `(source,destination,channel,W,P,D,t,F,next)` for continuation."""

        return {
            "version": 2,
            "source": self.source,
            "destination": self.destination,
            "channel": self.channel,
            "policy": {
                "lease_ticks": self.policy.lease_ticks,
                "max_attempts": self.policy.max_attempts,
                "window_size": self.policy.window_size,
            },
            "next_sequence": self._next_sequence,
            "tick": self._tick,
            "pending": {
                str(sequence): {
                    "frame": _message_snapshot(pending.frame),
                    "attempts": pending.attempts,
                    "last_sent_tick": pending.last_sent_tick,
                }
                for sequence, pending in sorted(self._pending.items())
            },
            "delivered": sorted(self._delivered),
            "failed_sequences": list(self.failed_sequences),
        }

    @classmethod
    def from_snapshot(cls, payload: dict[str, Any], transport: Transport) -> "ReliableChannel":
        """Mathematics: reconstruct channel state and validate `P,D,F` sequence domains before accepting continuation."""

        version = int(payload.get("version", 1))
        if version not in (1, 2):
            raise ValueError("unsupported reliable channel snapshot version")
        policy_payload = dict(payload.get("policy", {}))
        channel = cls(
            transport,
            str(payload["source"]),
            str(payload["destination"]),
            str(payload["channel"]),
            ReliabilityPolicy(
                int(policy_payload.get("lease_ticks", 3)),
                int(policy_payload.get("max_attempts", 4)),
                int(policy_payload.get("window_size", 64)),
            ),
        )
        channel._next_sequence = int(payload["next_sequence"])
        channel._tick = int(payload["tick"])
        channel._pending = {}
        for raw_sequence, raw in payload.get("pending", {}).items():
            sequence = int(raw_sequence)
            if sequence <= 0 or sequence in channel._pending:
                raise ValueError(f"invalid pending sequence: {sequence}")
            attempts = int(raw["attempts"])
            last_sent_tick = int(raw["last_sent_tick"])
            if attempts <= 0 or last_sent_tick < 0:
                raise ValueError(f"invalid pending state: {sequence}")
            channel._pending[sequence] = PendingFrame(
                _message_from_snapshot(dict(raw["frame"])),
                attempts,
                last_sent_tick,
            )
        channel._delivered = {int(sequence) for sequence in payload.get("delivered", ())}
        channel.failed_sequences = [int(sequence) for sequence in payload.get("failed_sequences", ())]
        all_sequences = set(channel._pending) | channel._delivered | set(channel.failed_sequences)
        if any(sequence <= 0 for sequence in all_sequences):
            raise ValueError("reliable sequence identities must be positive")
        if channel._next_sequence <= max(all_sequences, default=0):
            raise ValueError("next sequence must exceed restored sequence identities")
        if len(channel._pending) > channel.policy.window_size:
            raise ValueError("restored pending sequences exceed reliable channel window")
        return channel
