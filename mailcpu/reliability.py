"""At-least-once reliable channel built above an unreliable MailCPU transport."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

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
        peer: str | None = None,
    ) -> None:
        """Mathematics: initialize sequence `n=1`, peer identity `peer`, delivered set `D=∅`, pending map `P=∅`, and tick `t=0`, under `|P|≤W`."""

        if not source or not destination or not channel:
            raise ValueError("source, destination, and channel must be non-empty")
        self.transport = transport
        self.source = source
        self.destination = destination
        self.channel = channel
        self.peer = destination if peer is None else peer
        if not self.peer:
            raise ValueError("peer must be non-empty")
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
        self._next_receive_sequence = 1
        self._tick = 0
        self.failed_sequences: list[int] = []

    @property
    def ack_address(self) -> str:
        r"""Mathematics: derive the unambiguous acknowledgement mailbox for `(source, channel)`."""

        return self.ack_address_for(self.source)

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

    @property
    def next_receive_sequence(self) -> int:
        """Mathematics: expose the logical FIFO cursor `r=min{s∈N⁺:s∉D}` without changing channel state."""

        return self._next_receive_sequence

    def receive(self, commit: Callable[[int, Any], None] | None = None) -> tuple[int, Any] | None:
        """Mathematics: commit new `F_s` before dequeue and `ACK(s)`, then advance `r`; duplicate `s<r` is acknowledged without reapplication."""

        peeked = self.peek()
        if peeked is None:
            return None
        sequence, payload = peeked
        message = next(
            (
                candidate
                for candidate in self._validated_queue()
                if candidate.body[1] == sequence and candidate.body[2] == payload
            ),
            None,
        )
        if message is None:
            raise ValueError("reliable frame disappeared between validation and consume")
        if sequence == self._next_receive_sequence and commit is not None:
            commit(sequence, payload)
        if not self.transport.consume(message):
            raise ValueError("reliable frame disappeared between validation and consume")
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
        if sequence < self._next_receive_sequence:
            return None
        if sequence != self._next_receive_sequence:
            raise ValueError("reliable receive cursor advanced unexpectedly")
        self._delivered.add(sequence)
        self._next_receive_sequence += 1
        return sequence, payload

    def peek(self) -> tuple[int, Any] | None:
        """Mathematics: validate `Q` and project the next logical frame `F_r`, or an older duplicate, without changing `Q,D`."""

        queued = self._validated_queue()
        if not queued:
            return None

        for message in queued:
            if message.body[1] == self._next_receive_sequence:
                return message.body[1], message.body[2]
        for message in queued:
            if message.body[1] < self._next_receive_sequence:
                return message.body[1], message.body[2]
        return None

    def _validated_queue(self) -> tuple[Message, ...]:
        """Mathematics: validate every queued frame in `Q_destination` and return the immutable sequence projection."""

        queued = self.transport.list(self.destination)
        for message in queued:
            if (
                message.sender != self.peer
                or message.recipient != self.destination
                or message.addr != self.destination
            ):
                raise ValueError("reliable frame mailbox identity mismatch")
            if message.op != "RDATA" or len(message.body) != 3:
                raise ValueError("unexpected frame on reliable data mailbox")
            channel, sequence, _payload = message.body
            if channel != self.channel or not isinstance(sequence, int) or isinstance(sequence, bool) or sequence <= 0:
                raise ValueError("reliable frame channel or sequence mismatch")
        return queued

    def process_ack(self) -> tuple[int, ...]:
        """Mathematics: remove acknowledged sequences `P := P \\ ACKS` and return the finite set of removed keys."""

        acknowledged: list[int] = []
        while True:
            queued = self.transport.list(self.ack_address)
            if not queued:
                break
            message = queued[0]
            if (
                message.sender != self.peer
                or message.recipient != self.ack_address
                or message.addr != self.ack_address
            ):
                raise ValueError("reliable acknowledgement sender or mailbox mismatch")
            if message.op != "RACK" or len(message.body) != 2:
                raise ValueError("unexpected frame on reliable acknowledgement mailbox")
            channel, sequence = message.body
            if channel != self.channel or not isinstance(sequence, int) or isinstance(sequence, bool):
                raise ValueError("reliable acknowledgement channel or sequence mismatch")
            self.transport.poll(self.ack_address)
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

    def retransmit(self, sequence: int) -> bool:
        """Mathematics: resend the exact pending frame `F_s` at its original sequence while preserving FIFO identity `s`."""

        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence <= 0:
            raise ReliableChannelError("retransmit sequence must be a positive integer")
        pending = self._pending.get(sequence)
        if pending is None:
            return False
        if pending.attempts >= self.policy.max_attempts:
            raise ReliableChannelError(f"retransmit attempts exhausted for sequence {sequence}")
        self.transport.send(self.destination, pending.frame)
        pending.attempts += 1
        pending.last_sent_tick = self._tick
        return True

    def pending_sequences(self) -> tuple[int, ...]:
        """Mathematics: expose the ordered domain `sort(dom(P))` of unacknowledged frames."""

        return tuple(sorted(self._pending))

    def ack_address_for(self, sender: str) -> str:
        r"""Mathematics: derive an unambiguous acknowledgement route by length-prefixing `(sender, channel)`."""

        return f"ack:{len(sender)}:{sender}:{len(self.channel)}:{self.channel}"

    def snapshot(self) -> dict[str, Any]:
        """Mathematics: serialize reliable state `(source,destination,peer,channel,W,P,D,r,t,F,next)` for continuation."""

        return {
            "version": 3,
            "source": self.source,
            "destination": self.destination,
            "channel": self.channel,
            "peer": self.peer,
            "policy": {
                "lease_ticks": self.policy.lease_ticks,
                "max_attempts": self.policy.max_attempts,
                "window_size": self.policy.window_size,
            },
            "next_sequence": self._next_sequence,
            "next_receive_sequence": self._next_receive_sequence,
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
        """Mathematics: reconstruct channel state, restore cursor `r`, reconcile queued `RDATA`, and validate `P,D,F` sequence domains before continuation."""

        version = int(payload.get("version", 1))
        if version not in (1, 2, 3):
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
            peer=None if payload.get("peer") is None else str(payload["peer"]),
        )
        channel._next_sequence = int(payload["next_sequence"])
        channel._tick = int(payload["tick"])
        if channel._next_sequence <= 0 or channel._tick < 0:
            raise ValueError("reliable sequence counter and tick must be valid")
        channel._pending = {}
        for raw_sequence, raw in payload.get("pending", {}).items():
            sequence = int(raw_sequence)
            if sequence <= 0 or sequence in channel._pending:
                raise ValueError(f"invalid pending sequence: {sequence}")
            attempts = int(raw["attempts"])
            last_sent_tick = int(raw["last_sent_tick"])
            if attempts <= 0 or attempts > channel.policy.max_attempts or last_sent_tick < 0 or last_sent_tick > channel._tick:
                raise ValueError(f"invalid pending state: {sequence}")
            frame = _message_from_snapshot(dict(raw["frame"]))
            if (
                frame.sender != channel.source
                or frame.recipient != channel.destination
                or frame.addr != channel.destination
                or frame.op != "RDATA"
                or len(frame.body) != 3
                or frame.body[0] != channel.channel
                or frame.body[1] != sequence
            ):
                raise ValueError(f"pending frame identity mismatch: {sequence}")
            channel._pending[sequence] = PendingFrame(
                frame,
                attempts,
                last_sent_tick,
            )
        raw_delivered = [int(sequence) for sequence in payload.get("delivered", ())]
        raw_failed = [int(sequence) for sequence in payload.get("failed_sequences", ())]
        if len(raw_delivered) != len(set(raw_delivered)) or len(raw_failed) != len(set(raw_failed)):
            raise ValueError("reliable delivered and failed sequences must be unique")
        channel._delivered = set(raw_delivered)
        channel.failed_sequences = raw_failed
        if version >= 3:
            channel._next_receive_sequence = int(payload["next_receive_sequence"])
        else:
            channel._next_receive_sequence = max(channel._delivered, default=0) + 1
        if channel._next_receive_sequence <= 0 or any(
            sequence >= channel._next_receive_sequence for sequence in channel._delivered
        ):
            raise ValueError("reliable receive cursor must exceed delivered sequences")
        all_sequences = set(channel._pending) | channel._delivered | set(channel.failed_sequences)
        if any(sequence <= 0 for sequence in all_sequences):
            raise ValueError("reliable sequence identities must be positive")
        if (set(channel._pending) & channel._delivered) or (set(channel._pending) & set(channel.failed_sequences)) or (channel._delivered & set(channel.failed_sequences)):
            raise ValueError("reliable sequence cannot be pending, delivered, and failed simultaneously")
        outbound_sequences = set(channel._pending) | set(channel.failed_sequences)
        if channel._next_sequence <= max(outbound_sequences, default=0):
            raise ValueError("next sequence must exceed restored sequence identities")
        channel._reconcile_outbound_queue()
        outbound_sequences = set(channel._pending) | set(channel.failed_sequences)
        if channel._next_sequence <= max(outbound_sequences, default=0):
            raise ValueError("next sequence must exceed restored sequence identities")
        if len(channel._pending) > channel.policy.window_size:
            raise ValueError("restored pending sequences exceed reliable channel window")
        return channel

    def _reconcile_outbound_queue(self) -> None:
        """Mathematics: for each queued exact-channel frame `F_s`, enforce `s∈P∪D∪F` and recover omitted `s` into `P` with `attempts=1` and `last_sent_tick=t`."""

        for message in self.transport.list(self.destination):
            if message.sender != self.source or message.op != "RDATA":
                continue
            if not isinstance(message.body, tuple) or not message.body or message.body[0] != self.channel:
                continue
            if (
                message.recipient != self.destination
                or message.addr != self.destination
                or len(message.body) != 3
            ):
                raise ValueError("queued reliable frame identity mismatch during restore")
            _, sequence, _ = message.body
            if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence <= 0:
                raise ValueError("queued reliable frame sequence must be a positive integer")
            if sequence in self._delivered or sequence in self.failed_sequences:
                raise ValueError("queued reliable frame contradicts delivered or failed state")
            restored = self._pending.get(sequence)
            if restored is None:
                self._pending[sequence] = PendingFrame(message, 1, self._tick)
            elif not self._same_protocol_frame(restored.frame, message):
                raise ValueError("queued reliable frame conflicts with restored pending state")
            self._next_sequence = max(self._next_sequence, sequence + 1)
        if len(self._pending) > self.policy.window_size:
            raise ValueError("queued reliable frames exceed reliable channel window")

    @staticmethod
    def _same_protocol_frame(left: Message, right: Message) -> bool:
        """Mathematics: compare protocol identity `I(F)=(sender,recipient,op,addr,value,seq,body)` while quotienting out storage-only `message_id`."""

        return (
            left.sender,
            left.recipient,
            left.op,
            left.addr,
            left.value,
            left.seq,
            left.body,
        ) == (
            right.sender,
            right.recipient,
            right.op,
            right.addr,
            right.value,
            right.seq,
            right.body,
        )
