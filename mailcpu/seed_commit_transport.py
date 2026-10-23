"""Reliable remote seed-input execution with semantic duplicate suppression."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
import hashlib
import json
from typing import Any

from ._codec import encode_canonical_value
from .headless import HeadlessOS
from .reliability import ReliableChannel
from .seed import SeedEnvelopeError, SeedNavigationError, SystemSeedEnvelope
from .seed_admission import SeedAdmissionError


SEED_COMMIT_REQUEST_KIND = "mailcpu.hypervisor.seed.commit"
SEED_COMMIT_RESULT_KIND = "mailcpu.hypervisor.seed.commit.result"


class SeedCommitTransportError(ValueError):
    """A remote seed commit is malformed, misbound, conflicting, or not safe to acknowledge."""


def _label(value: Any, name: str) -> str:
    """Mathematics: restrict a protocol label to `L={x∈String:|x|>0}`."""

    if not isinstance(value, str) or not value:
        raise SeedCommitTransportError(f"{name} must be a non-empty string")
    return value


def _digest(value: Any, name: str) -> str:
    """Mathematics: restrict an identity to the lowercase hexadecimal image `D={0,…,f}^{64}` of SHA-256."""

    if not isinstance(value, str) or len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise SeedCommitTransportError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    """Mathematics: encode a protocol product as `C(x)=JSON_sort(encode_canonical_value(x))`."""

    try:
        return json.dumps(
            encode_canonical_value(dict(value)),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise SeedCommitTransportError("seed commit payload is outside the canonical algebra") from exc


def _frontier_digest(envelope: SystemSeedEnvelope) -> str:
    """Mathematics: compute `d(F)=SHA256(JSON_sort(F))` for the finite frontier projection `F`."""

    canonical = json.dumps(
        envelope.snapshot()["input_frontier"],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


@dataclass(frozen=True)
class SeedCommitRequest:
    """One remote input operation `q=(system,source,sequence,pid,mailbox,values,d_before)`."""

    system_id: str
    source: str
    sequence: int
    pid: int
    mailbox: str
    values: tuple[int, ...]
    base_state_digest: str

    def __post_init__(self) -> None:
        """Mathematics: enforce `system,source,mailbox∈L`, positive coordinates, and `values∈Z^n`."""

        _label(self.system_id, "seed commit system id")
        _label(self.source, "seed commit input source")
        _label(self.mailbox, "seed commit mailbox")
        if "\x00" in self.mailbox:
            raise SeedCommitTransportError("seed commit mailbox cannot contain NUL")
        for name, value in (("sequence", self.sequence), ("pid", self.pid)):
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise SeedCommitTransportError(f"seed commit {name} must be a positive integer")
        values = tuple(self.values)
        if any(not isinstance(value, int) or isinstance(value, bool) for value in values):
            raise SeedCommitTransportError("seed commit values must be integers")
        _digest(self.base_state_digest, "seed commit base state digest")
        object.__setattr__(self, "values", values)

    def to_dict(self) -> dict[str, object]:
        """Mathematics: project request `q` into a canonical finite wire record without losing tuple contents."""

        return {
            "format": "mailcpu-seed-commit-request/1",
            "system_id": self.system_id,
            "source": self.source,
            "sequence": self.sequence,
            "pid": self.pid,
            "mailbox": self.mailbox,
            "values": list(self.values),
            "base_state_digest": self.base_state_digest,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "SeedCommitRequest":
        """Mathematics: invert request projection only when format, sequence, and digest domains are valid."""

        if not isinstance(payload, Mapping) or payload.get("format") != "mailcpu-seed-commit-request/1":
            raise SeedCommitTransportError("seed commit request format is invalid")
        raw_values = payload.get("values", ())
        if not isinstance(raw_values, (list, tuple)):
            raise SeedCommitTransportError("seed commit request values must be a sequence")
        try:
            return cls(
                payload.get("system_id"),
                payload.get("source"),
                payload.get("sequence"),
                payload.get("pid"),
                payload.get("mailbox"),
                tuple(raw_values),
                payload.get("base_state_digest"),
            )
        except (TypeError, ValueError) as exc:
            if isinstance(exc, SeedCommitTransportError):
                raise
            raise SeedCommitTransportError("seed commit request fields are invalid") from exc

    @property
    def fingerprint(self) -> str:
        """Mathematics: compute operation identity `f(q)=SHA256(C(q))` independently of transport sequence."""

        return hashlib.sha256(_canonical_bytes(self.to_dict())).hexdigest()


@dataclass(frozen=True)
class SeedCommitResult:
    """One remote commit outcome `r=(I,f,system,accepted,replayed,state,frontier,receipt,envelope,reason)`."""

    request_source: str
    request_channel: str
    request_sequence: int
    request_fingerprint: str
    system_id: str
    accepted: bool
    replayed: bool
    state_digest: str | None
    frontier_digest: str | None
    admission_receipt: str | None
    envelope: SystemSeedEnvelope | None
    reason: str | None = None

    def __post_init__(self) -> None:
        """Mathematics: validate result identity and require complete digest/envelope factors iff `accepted=1`."""

        _label(self.request_source, "seed commit result request source")
        _label(self.request_channel, "seed commit result request channel")
        if not isinstance(self.request_sequence, int) or isinstance(self.request_sequence, bool) or self.request_sequence <= 0:
            raise SeedCommitTransportError("seed commit result request sequence must be positive")
        _digest(self.request_fingerprint, "seed commit result request fingerprint")
        _label(self.system_id, "seed commit result system id")
        if not isinstance(self.accepted, bool) or not isinstance(self.replayed, bool):
            raise SeedCommitTransportError("seed commit result flags must be boolean")
        if self.accepted:
            if self.envelope is None or self.state_digest is None or self.frontier_digest is None or self.admission_receipt is None:
                raise SeedCommitTransportError("accepted seed commit result is incomplete")
            if self.envelope.identity.system_id != self.system_id:
                raise SeedCommitTransportError("accepted seed commit result system identity does not match envelope")
            _digest(self.state_digest, "seed commit result state digest")
            _digest(self.frontier_digest, "seed commit result frontier digest")
            _digest(self.admission_receipt, "seed commit result admission receipt")
            if self.envelope.state_digest != self.state_digest:
                raise SeedCommitTransportError("accepted seed commit result state digest does not match envelope")
            if _frontier_digest(self.envelope) != self.frontier_digest:
                raise SeedCommitTransportError("accepted seed commit result frontier digest does not match envelope")
        else:
            if self.reason is None or not isinstance(self.reason, str) or not self.reason:
                raise SeedCommitTransportError("refused seed commit result requires a reason")
        if self.state_digest is not None:
            _digest(self.state_digest, "seed commit result state digest")
        if self.frontier_digest is not None:
            _digest(self.frontier_digest, "seed commit result frontier digest")
        if self.admission_receipt is not None:
            _digest(self.admission_receipt, "seed commit result admission receipt")

    def to_dict(self) -> dict[str, object]:
        """Mathematics: serialize result `r` while retaining the full accepted seed as the next navigation state."""

        return {
            "format": "mailcpu-seed-commit-result/1",
            "request_source": self.request_source,
            "request_channel": self.request_channel,
            "request_sequence": self.request_sequence,
            "request_fingerprint": self.request_fingerprint,
            "system_id": self.system_id,
            "accepted": self.accepted,
            "replayed": self.replayed,
            "state_digest": self.state_digest,
            "frontier_digest": self.frontier_digest,
            "admission_receipt": self.admission_receipt,
            "envelope": None if self.envelope is None else self.envelope.snapshot(),
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "SeedCommitResult":
        """Mathematics: reconstruct typed result `r` only after envelope and identity factors validate."""

        if not isinstance(payload, Mapping) or payload.get("format") != "mailcpu-seed-commit-result/1":
            raise SeedCommitTransportError("seed commit result format is invalid")
        raw_envelope = payload.get("envelope")
        envelope = None
        if raw_envelope is not None:
            if not isinstance(raw_envelope, Mapping):
                raise SeedCommitTransportError("seed commit result envelope is invalid")
            envelope = SystemSeedEnvelope.from_snapshot(raw_envelope)
        try:
            return cls(
                payload.get("request_source"),
                payload.get("request_channel"),
                payload.get("request_sequence"),
                payload.get("request_fingerprint"),
                payload.get("system_id"),
                payload.get("accepted"),
                payload.get("replayed"),
                payload.get("state_digest"),
                payload.get("frontier_digest"),
                payload.get("admission_receipt"),
                envelope,
                None if payload.get("reason") is None else str(payload.get("reason")),
            )
        except (SeedEnvelopeError, SeedNavigationError, TypeError, ValueError) as exc:
            if isinstance(exc, SeedCommitTransportError):
                raise
            raise SeedCommitTransportError("seed commit result fields are invalid") from exc


class HypervisorSeedCommitChannel:
    """Carry remote seed input requests through one reliable channel and one receiver-side result ledger."""

    def __init__(self, channel: ReliableChannel) -> None:
        """Mathematics: bind request FIFO `Q` to reliable identity `(source,peer,c)` and initialize semantic ledger `L=∅`."""

        if not isinstance(channel, ReliableChannel):
            raise SeedCommitTransportError("seed commit request channel requires a ReliableChannel")
        self.channel = channel
        self._seen: dict[tuple[str, str, int], SeedCommitResult] = {}

    def send(self, request: SeedCommitRequest) -> int:
        """Mathematics: emit `RDATA(seed_request,q)` and retain it until `ACK(s)` while `|P|<W`."""

        if not isinstance(request, SeedCommitRequest):
            raise SeedCommitTransportError("seed commit request channel requires a SeedCommitRequest")
        return self.channel.send({"kind": SEED_COMMIT_REQUEST_KIND, "request": request.to_dict()})

    def receive_and_commit(
        self,
        operating_system: HeadlessOS,
        response: "HypervisorSeedCommitResultChannel",
        durable_journal: Any | None = None,
    ) -> SeedCommitResult | None:
        """Mathematics: compute `durable(cache(q)); reply(cache(q)); ACK(q)` so retry cannot repeat `T_q`."""

        if not isinstance(operating_system, HeadlessOS):
            raise SeedCommitTransportError("seed commit receiver requires a HeadlessOS")
        if not isinstance(response, HypervisorSeedCommitResultChannel):
            raise SeedCommitTransportError("seed commit receiver requires a typed result channel")
        peeked = self.channel.peek()
        if peeked is None:
            return None
        transport_sequence, payload = peeked
        request = self._decode_payload(payload)
        identity = (self.channel.peer, self.channel.channel, transport_sequence)
        cached = self._seen.get(identity)
        if cached is not None:
            if cached.request_fingerprint != request.fingerprint:
                raise SeedCommitTransportError("conflicting seed commit request at transport identity")
            result = replace(cached, replayed=True)
        else:
            result = None if durable_journal is None else durable_journal.lookup(identity, request.fingerprint)
            if result is not None:
                result = replace(result, replayed=True)
            else:
                before = None if durable_journal is None else operating_system.snapshot()
                trajectory_checkpoint = (
                    None
                    if durable_journal is None or operating_system.vm.trajectory is None
                    else operating_system.vm.trajectory.checkpoint()
                )
                result = self._execute(request, transport_sequence, operating_system)
                if durable_journal is not None:
                    try:
                        durable_journal.record(identity, request.fingerprint, result, operating_system)
                    except Exception:
                        operating_system._restore_snapshot_in_place(before)
                        if trajectory_checkpoint is not None:
                            operating_system.vm.trajectory.rollback(trajectory_checkpoint)
                        raise
            self._seen[identity] = result
        response.send(result)
        received = self.channel.receive()
        if received is not None and received[0] != transport_sequence:
            raise SeedCommitTransportError("seed commit request sequence changed after response")
        return result

    def snapshot(self) -> dict[str, object]:
        """Mathematics: serialize reliable request state and semantic cache `L` for exact remote recovery."""

        return {
            "version": 1,
            "channel": self.channel.snapshot(),
            "seen": [result.to_dict() for result in self._seen.values()],
        }

    @classmethod
    def from_snapshot(cls, payload: Mapping[str, Any], transport: Any) -> "HypervisorSeedCommitChannel":
        """Mathematics: restore `Q,P,L` only when every cached result is unique and peer-bound to the channel."""

        if not isinstance(payload, Mapping) or int(payload.get("version", -1)) != 1:
            raise SeedCommitTransportError("unsupported seed commit request snapshot")
        raw_channel = payload.get("channel")
        if not isinstance(raw_channel, Mapping):
            raise SeedCommitTransportError("seed commit request snapshot channel is invalid")
        adapter = cls(ReliableChannel.from_snapshot(dict(raw_channel), transport))
        for raw_result in payload.get("seen", ()):
            result = SeedCommitResult.from_dict(raw_result)
            identity = (result.request_source, result.request_channel, result.request_sequence)
            if identity in adapter._seen:
                raise SeedCommitTransportError("duplicate seed commit request result identity in snapshot")
            if result.request_source != adapter.channel.peer or result.request_channel != adapter.channel.channel:
                raise SeedCommitTransportError("seed commit request result is not peer-bound")
            adapter._seen[identity] = replace(result, replayed=False)
        return adapter

    def _decode_payload(self, payload: Any) -> SeedCommitRequest:
        """Mathematics: invert `W=(kind,q)` only for the exact request kind and typed request domain."""

        if not isinstance(payload, Mapping) or payload.get("kind") != SEED_COMMIT_REQUEST_KIND:
            raise SeedCommitTransportError("seed commit request payload kind is invalid")
        raw_request = payload.get("request")
        if not isinstance(raw_request, Mapping):
            raise SeedCommitTransportError("seed commit request payload is not a mapping")
        return SeedCommitRequest.from_dict(raw_request)

    def _execute(
        self,
        request: SeedCommitRequest,
        transport_sequence: int,
        operating_system: HeadlessOS,
    ) -> SeedCommitResult:
        """Mathematics: evaluate `commit(q)` only under `d_before(q)=d(host)` and turn expected refusal into a replayable result."""

        request_source = self.channel.peer
        request_channel = self.channel.channel
        current = operating_system.seed_admission.current(request.system_id)
        if current is None:
            return self._refusal(request, transport_sequence, "seed commit precondition system is not admitted")
        existing_input = any(
            event.source == request.source and event.sequence == request.sequence
            for event in current.seed.input_events
        )
        if not existing_input and current.state_digest != request.base_state_digest:
            return self._refusal(request, transport_sequence, "seed commit precondition state digest mismatch")
        try:
            admission, envelope = operating_system.commit_seed_input(
                request.system_id,
                request.source,
                request.sequence,
                request.pid,
                request.mailbox,
                request.values,
            )
        except (SeedAdmissionError, SeedEnvelopeError, SeedNavigationError, OSError, ValueError) as exc:
            return self._refusal(request, transport_sequence, f"seed commit refused: {type(exc).__name__}: {exc}")
        if not admission.accepted:
            return self._refusal(request, transport_sequence, admission.reason or "seed commit admission refused")
        return SeedCommitResult(
            request_source,
            request_channel,
            transport_sequence,
            request.fingerprint,
            request.system_id,
            True,
            admission.replayed,
            envelope.state_digest,
            _frontier_digest(envelope),
            admission.admission_receipt,
            envelope,
        )

    def _refusal(self, request: SeedCommitRequest, transport_sequence: int, reason: str) -> SeedCommitResult:
        """Mathematics: materialize deterministic refusal `R(q)=(accepted=0,reason)` without changing host state."""

        return SeedCommitResult(
            self.channel.peer,
            self.channel.channel,
            transport_sequence,
            request.fingerprint,
            request.system_id,
            False,
            False,
            None,
            None,
            None,
            None,
            reason,
        )


class HypervisorSeedCommitResultChannel:
    """Carry seed-commit outcomes back to the requester and suppress duplicate semantic results."""

    def __init__(self, channel: ReliableChannel, operation_source: str, operation_channel: str) -> None:
        """Mathematics: bind result FIFO `R` to request identity `(source,channel)` and initialize result ledger `S=∅`."""

        if not isinstance(channel, ReliableChannel):
            raise SeedCommitTransportError("seed commit result channel requires a ReliableChannel")
        self.channel = channel
        self.operation_source = _label(operation_source, "seed commit result operation source")
        self.operation_channel = _label(operation_channel, "seed commit result operation channel")
        self._seen: dict[tuple[str, str, int], SeedCommitResult] = {}
        self._sent: dict[tuple[str, str, int], tuple[str, int]] = {}

    def send(self, result: SeedCommitResult) -> int:
        """Mathematics: first reduce `P←P\\ACKS`, then retransmit pending identity `I` or allocate a fresh sequence; retain it until ACK."""

        self._validate_result(result)
        # An ACK may already be queued in the rebound transport even though the restored
        # channel still lists its sequence as pending. Reconcile that evidence before
        # deciding whether this semantic result needs a retransmission or a new frame.
        self.channel.process_ack()
        identity = (result.request_source, result.request_channel, result.request_sequence)
        previous = self._sent.get(identity)
        if previous is not None:
            previous_fingerprint, previous_sequence = previous
            if previous_fingerprint != result.request_fingerprint:
                raise SeedCommitTransportError("conflicting seed commit result identity")
            if previous_sequence in self.channel.pending_sequences():
                if not self.channel.retransmit(previous_sequence):
                    raise SeedCommitTransportError("seed commit result pending frame disappeared")
                return previous_sequence
        sequence = self.channel.send({"kind": SEED_COMMIT_RESULT_KIND, "result": result.to_dict()})
        self._sent[identity] = (result.request_fingerprint, sequence)
        return sequence

    def receive(self) -> SeedCommitResult | None:
        """Mathematics: return first result `r` or `replay(r)` while consuming and acknowledging each reliable frame."""

        peeked = self.channel.peek()
        if peeked is None:
            return None
        transport_sequence, payload = peeked
        incoming = self._decode_payload(payload)
        identity = (incoming.request_source, incoming.request_channel, incoming.request_sequence)
        previous = self._seen.get(identity)
        if previous is not None:
            if previous.request_fingerprint != incoming.request_fingerprint or previous.to_dict() | {"replayed": False} != incoming.to_dict() | {"replayed": False}:
                raise SeedCommitTransportError("conflicting seed commit result")
            result = replace(previous, replayed=True)
        else:
            self._seen[identity] = replace(incoming, replayed=False)
            result = incoming
        received = self.channel.receive()
        if received is not None and received[0] != transport_sequence:
            raise SeedCommitTransportError("seed commit result sequence changed during validation")
        return result

    def snapshot(self) -> dict[str, object]:
        """Mathematics: serialize reliable result state, operation binding, and semantic result ledger `S`."""

        return {
            "version": 1,
            "channel": self.channel.snapshot(),
            "operation_source": self.operation_source,
            "operation_channel": self.operation_channel,
            "seen": [result.to_dict() for result in self._seen.values()],
            "sent": [
                {
                    "request_source": source,
                    "request_channel": channel,
                    "request_sequence": sequence,
                    "request_fingerprint": fingerprint,
                    "transport_sequence": transport_sequence,
                }
                for (source, channel, sequence), (fingerprint, transport_sequence) in sorted(self._sent.items())
            ],
        }

    @classmethod
    def from_snapshot(cls, payload: Mapping[str, Any], transport: Any) -> "HypervisorSeedCommitResultChannel":
        """Mathematics: reconstruct `R,S` only when every cached result preserves its requester binding and identity."""

        if not isinstance(payload, Mapping) or int(payload.get("version", -1)) != 1:
            raise SeedCommitTransportError("unsupported seed commit result snapshot")
        raw_channel = payload.get("channel")
        if not isinstance(raw_channel, Mapping):
            raise SeedCommitTransportError("seed commit result snapshot channel is invalid")
        adapter = cls(
            ReliableChannel.from_snapshot(dict(raw_channel), transport),
            str(payload.get("operation_source", "")),
            str(payload.get("operation_channel", "")),
        )
        for raw_result in payload.get("seen", ()):
            result = SeedCommitResult.from_dict(raw_result)
            adapter._validate_result(result)
            identity = (result.request_source, result.request_channel, result.request_sequence)
            if identity in adapter._seen:
                raise SeedCommitTransportError("duplicate seed commit result identity in snapshot")
            adapter._seen[identity] = replace(result, replayed=False)
        for raw_sent in payload.get("sent", ()):
            if not isinstance(raw_sent, Mapping):
                raise SeedCommitTransportError("seed commit result sent ledger entry is invalid")
            identity = (
                str(raw_sent.get("request_source", "")),
                str(raw_sent.get("request_channel", "")),
                int(raw_sent.get("request_sequence", 0)),
            )
            fingerprint = _digest(raw_sent.get("request_fingerprint"), "seed commit sent request fingerprint")
            transport_sequence = int(raw_sent.get("transport_sequence", 0))
            if identity in adapter._sent or identity[0] != adapter.operation_source or identity[1] != adapter.operation_channel:
                raise SeedCommitTransportError("seed commit sent result identity is invalid")
            if identity[2] <= 0 or transport_sequence <= 0:
                raise SeedCommitTransportError("seed commit sent result sequence is invalid")
            adapter._sent[identity] = (fingerprint, transport_sequence)
        return adapter

    def _validate_result(self, result: SeedCommitResult) -> None:
        """Mathematics: require `I(result)=(operation_source,operation_channel,sequence)` before wire emission."""

        if not isinstance(result, SeedCommitResult):
            raise SeedCommitTransportError("seed commit result channel requires a SeedCommitResult")
        if result.request_source != self.operation_source or result.request_channel != self.operation_channel:
            raise SeedCommitTransportError("seed commit result identity is not requester-bound")

    def _decode_payload(self, payload: Any) -> SeedCommitResult:
        """Mathematics: invert `W=(kind,r)` only for the expected result kind and requester-bound result identity."""

        if not isinstance(payload, Mapping) or payload.get("kind") != SEED_COMMIT_RESULT_KIND:
            raise SeedCommitTransportError("seed commit result payload kind is invalid")
        raw_result = payload.get("result")
        if not isinstance(raw_result, Mapping):
            raise SeedCommitTransportError("seed commit result payload is not a mapping")
        result = SeedCommitResult.from_dict(raw_result)
        self._validate_result(result)
        return result
