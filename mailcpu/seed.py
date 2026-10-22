r"""Canonical seeds for deterministic MailCPU system-state navigation.

Mathematics:
Let `S_0` be a complete `HeadlessOS` snapshot and `T` the deterministic
scheduler transition operator. A seed is

\[
  \Sigma = (S_0, d_0, k, d_k),
  \qquad d_i = SHA256(JSON_{canonical}(T^i(S_0))).
\]

Navigation evaluates `T^k(S_0)` from the immutable origin. Rewind is therefore
exact replay from `S_0`, not an invented inverse for effects such as filesystem
writes or process creation. A requested coordinate is admitted only when the
restored scheduler reaches its target tick and its canonical digest matches.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

from ._codec import decode_canonical_value, encode_canonical_value
from .headless import HeadlessOS
from .model import Message


SYSTEM_SEED_ENVELOPE_KIND = "mailcpu.system.seed.v1"


class SeedNavigationError(ValueError):
    """A seed is malformed, tampered with, unreachable, or inconsistent with its expected digest."""


class SeedEnvelopeError(SeedNavigationError):
    """A seed envelope is malformed, misrouted, tampered with, or stale for its system identity."""


def _validate_label(value: Any, label: str) -> str:
    """Mathematics: restrict a namespace label to the non-empty string domain `L={x∈String:|x|>0}`."""

    if not isinstance(value, str) or not value:
        raise SeedEnvelopeError(f"{label} must be a non-empty string")
    return value


@dataclass(frozen=True)
class SystemIdentity:
    """A namespace identity `I=(system_id,incarnation)` for one hosted emulated system."""

    system_id: str
    incarnation: int

    def __post_init__(self) -> None:
        """Mathematics: enforce `system_id∈L` and `incarnation∈N⁺` before routing or admission."""

        _validate_label(self.system_id, "system_id")
        if not isinstance(self.incarnation, int) or isinstance(self.incarnation, bool) or self.incarnation <= 0:
            raise SeedEnvelopeError("incarnation must be a positive integer")

    def route(self, role: str, channel: str) -> str:
        """Mathematics: encode injective mailbox route `ρ(I,r,c)=len(id):id:inc:len(r):r:len(c):c`."""

        role = _validate_label(role, "role")
        channel = _validate_label(channel, "channel")
        return (
            f"sys:{len(self.system_id)}:{self.system_id}:{self.incarnation}:"
            f"{len(role)}:{role}:{len(channel)}:{channel}"
        )

    def snapshot(self) -> dict[str, object]:
        """Mathematics: serialize identity product `I` without storage-specific fields."""

        return {"system_id": self.system_id, "incarnation": self.incarnation}

    @classmethod
    def from_snapshot(cls, payload: Mapping[str, Any]) -> "SystemIdentity":
        """Mathematics: reconstruct `I` only from a complete typed namespace mapping."""

        if not isinstance(payload, Mapping):
            raise SeedEnvelopeError("system identity must be a mapping")
        return cls(payload.get("system_id"), payload.get("incarnation"))


@dataclass(frozen=True)
class SeedInputReceipt:
    """One monotone external-input receipt `q=(source,sequence,digest)` at a seed frontier."""

    source: str
    sequence: int
    digest: str

    def __post_init__(self) -> None:
        """Mathematics: enforce `source∈L`, `sequence∈N⁺`, and `digest∈SHA256(String)`."""

        _validate_label(self.source, "input receipt source")
        if not isinstance(self.sequence, int) or isinstance(self.sequence, bool) or self.sequence <= 0:
            raise SeedEnvelopeError("input receipt sequence must be a positive integer")
        try:
            _validate_digest(self.digest, "input receipt digest")
        except SeedNavigationError as exc:
            raise SeedEnvelopeError("input receipt digest is invalid") from exc

    def snapshot(self) -> dict[str, object]:
        """Mathematics: serialize receipt `q` as canonical frontier data."""

        return {"source": self.source, "sequence": self.sequence, "digest": self.digest}

    @classmethod
    def from_snapshot(cls, payload: Mapping[str, Any]) -> "SeedInputReceipt":
        """Mathematics: reconstruct one receipt only from its complete source, sequence, and digest coordinates."""

        if not isinstance(payload, Mapping):
            raise SeedEnvelopeError("input receipt must be a mapping")
        return cls(payload.get("source"), payload.get("sequence"), payload.get("digest"))


def _canonical_state(state: Mapping[str, Any]) -> bytes:
    """Mathematics: encode state as `c=JSON(sort_keys,state)` so equal state products have equal bytes."""

    try:
        return json.dumps(dict(state), sort_keys=True, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise SeedNavigationError("seed state is outside the canonical JSON algebra") from exc


def _state_digest(state: Mapping[str, Any]) -> str:
    """Mathematics: compute the content identity `d(S)=SHA256(c(S))` for one complete system state."""

    return hashlib.sha256(_canonical_state(state)).hexdigest()


def _scheduler_tick(state: Mapping[str, Any]) -> int:
    """Mathematics: project logical coordinate `τ(S)=S.vm.scheduler.tick` from the checkpoint graph."""

    try:
        raw_vm = state["vm"]
        raw_scheduler = dict(raw_vm)["scheduler"]
        tick = int(dict(raw_scheduler)["tick"])
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise SeedNavigationError("seed origin has no valid scheduler coordinate") from exc
    if tick < 0:
        raise SeedNavigationError("seed scheduler coordinate must be non-negative")
    return tick


def _validate_digest(value: Any, label: str) -> str:
    """Mathematics: restrict a content identity to the hexadecimal image of `SHA256`, `D={0,…,f}^{64}`."""

    digest = str(value)
    if len(digest) != 64:
        raise SeedNavigationError(f"{label} must be a 64-character SHA-256 digest")
    try:
        int(digest, 16)
    except ValueError as exc:
        raise SeedNavigationError(f"{label} must be hexadecimal") from exc
    return digest


@dataclass(frozen=True)
class SystemSeed:
    """An immutable origin-and-coordinate seed for predictable system-state replay."""

    origin_state: dict[str, Any]
    origin_digest: str
    coordinate: int
    state_digest: str

    @classmethod
    def from_system(cls, operating_system: HeadlessOS) -> "SystemSeed":
        """Mathematics: construct `Σ=(S_0,d_0,0,d_0)` from one complete running system state."""

        if not isinstance(operating_system, HeadlessOS):
            raise SeedNavigationError("system seed requires a HeadlessOS")
        state = deepcopy(operating_system.snapshot())
        digest = _state_digest(state)
        return cls(state, digest, 0, digest)

    @classmethod
    def from_snapshot(cls, payload: Mapping[str, Any]) -> "SystemSeed":
        """Mathematics: admit a seed only when `d(origin_state)=origin_digest` and its coordinate is finite and non-negative."""

        if not isinstance(payload, Mapping) or payload.get("format") != "mailcpu-system-seed/1":
            raise SeedNavigationError("unsupported system seed format")
        origin_state = payload.get("origin_state")
        if not isinstance(origin_state, Mapping):
            raise SeedNavigationError("system seed origin_state must be a mapping")
        origin = deepcopy(dict(origin_state))
        origin_digest = _validate_digest(payload.get("origin_digest"), "origin digest")
        if _state_digest(origin) != origin_digest:
            raise SeedNavigationError("origin digest does not match origin state")
        raw_coordinate = payload.get("coordinate")
        if isinstance(raw_coordinate, bool):
            raise SeedNavigationError("system seed coordinate is invalid")
        try:
            coordinate = int(raw_coordinate)
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise SeedNavigationError("system seed coordinate is invalid") from exc
        if coordinate < 0:
            raise SeedNavigationError("system seed coordinate must be non-negative")
        state_digest = _validate_digest(payload.get("state_digest"), "state digest")
        return cls(origin, origin_digest, coordinate, state_digest)

    def snapshot(self) -> dict[str, object]:
        """Mathematics: serialize `Σ` with copied origin state so seed storage cannot alias live execution state."""

        return {
            "format": "mailcpu-system-seed/1",
            "origin_state": deepcopy(self.origin_state),
            "origin_digest": self.origin_digest,
            "coordinate": self.coordinate,
            "state_digest": self.state_digest,
        }

    def restore(self) -> HeadlessOS:
        """Mathematics: evaluate `restore(Σ)=T^k(S_0)` and verify the seed's recorded digest at coordinate `k`."""

        operating_system = self._replay(self.coordinate)
        digest = _state_digest(operating_system.snapshot())
        if digest != _validate_digest(self.state_digest, "state digest"):
            raise SeedNavigationError("state digest does not match replayed state")
        return operating_system

    def at(self, coordinate: int, *, expected_digest: str | None = None) -> "SystemSeed":
        """Mathematics: compute `Σ.at(k)=(S_0,d_0,k,d(T^k(S_0)))` by deterministic replay from the origin."""

        if not isinstance(coordinate, int) or isinstance(coordinate, bool) or coordinate < 0:
            raise SeedNavigationError("seed coordinate must be a non-negative integer")
        operating_system = self._replay(coordinate)
        state = deepcopy(operating_system.snapshot())
        digest = _state_digest(state)
        if expected_digest is not None and digest != _validate_digest(expected_digest, "state digest"):
            raise SeedNavigationError("state digest does not match replayed state")
        return type(self)(deepcopy(self.origin_state), self.origin_digest, coordinate, digest)

    def advance(self, distance: int = 1) -> "SystemSeed":
        """Mathematics: move forward on the seed orbit `k↦k+distance` for non-negative integer distance."""

        if not isinstance(distance, int) or isinstance(distance, bool) or distance < 0:
            raise SeedNavigationError("seed advance distance must be a non-negative integer")
        return self.at(self.coordinate + distance)

    def rewind(self, distance: int = 1) -> "SystemSeed":
        """Mathematics: move backward by replaying the origin at `k-distance`, requiring `distance≤k`."""

        if not isinstance(distance, int) or isinstance(distance, bool) or distance < 0:
            raise SeedNavigationError("seed rewind distance must be a non-negative integer")
        if distance > self.coordinate:
            raise SeedNavigationError("seed rewind exceeds origin coordinate")
        return self.at(self.coordinate - distance)

    def _replay(self, coordinate: int) -> HeadlessOS:
        """Mathematics: evaluate `T^(τ(S_0)+k)(S_0)` and refuse if the scheduler cannot reach the requested coordinate."""

        target_tick = _scheduler_tick(self.origin_state) + coordinate
        try:
            operating_system = HeadlessOS.from_snapshot(deepcopy(self.origin_state))
            operating_system.run(target_tick)
        except (KeyError, TypeError, ValueError, OSError, OverflowError) as exc:
            raise SeedNavigationError("seed origin cannot be replayed") from exc
        actual_tick = operating_system.vm.scheduler.tick
        if actual_tick != target_tick:
            raise SeedNavigationError(
                f"seed cannot reach coordinate {coordinate}: scheduler stopped at tick {actual_tick}"
            )
        return operating_system


@dataclass(frozen=True)
class SystemSeedEnvelope:
    """A canonical transit product `E=(I,role,channel,Σ,F)` for one hosted system state."""

    identity: SystemIdentity
    role: str
    channel: str
    seed: SystemSeed
    input_frontier: tuple[SeedInputReceipt, ...] = ()

    def __post_init__(self) -> None:
        """Mathematics: enforce typed namespace, seed, and unique receipt-frontier factors before encoding."""

        if not isinstance(self.identity, SystemIdentity):
            raise SeedEnvelopeError("seed envelope identity is invalid")
        _validate_label(self.role, "seed envelope role")
        _validate_label(self.channel, "seed envelope channel")
        if not isinstance(self.seed, SystemSeed):
            raise SeedEnvelopeError("seed envelope seed is invalid")
        frontier = tuple(self.input_frontier)
        object.__setattr__(self, "input_frontier", frontier)
        if any(not isinstance(receipt, SeedInputReceipt) for receipt in frontier):
            raise SeedEnvelopeError("seed envelope input frontier contains an invalid receipt")
        keys = [(receipt.source, receipt.sequence) for receipt in frontier]
        if len(keys) != len(set(keys)):
            raise SeedEnvelopeError("seed envelope input frontier contains duplicate receipts")

    @property
    def state_digest(self) -> str:
        """Mathematics: project the seeded state identity `d(E)=d(Σ)` without decoding transit bytes."""

        return self.seed.state_digest

    def route(self) -> str:
        """Mathematics: project the namespace mailbox `ρ(E)=ρ(identity,role,channel)` with incarnation separation."""

        return self.identity.route(self.role, self.channel)

    def snapshot(self) -> dict[str, object]:
        """Mathematics: serialize payload `P(E)` with sorted receipt frontier and no transport-local message identity."""

        return {
            "format": "mailcpu-system-seed-envelope/1",
            "identity": self.identity.snapshot(),
            "role": self.role,
            "channel": self.channel,
            "seed": self.seed.snapshot(),
            "input_frontier": [
                receipt.snapshot()
                for receipt in sorted(self.input_frontier, key=lambda item: (item.source, item.sequence))
            ],
        }

    def to_bytes(self) -> bytes:
        """Mathematics: encode `B=JSON(encode_canonical(P(E))) || SHA256(JSON(encode_canonical(P(E))))` as transit bytes."""

        payload = self.snapshot()
        canonical_value = encode_canonical_value(payload)
        canonical = json.dumps(canonical_value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        document = {
            "format": SYSTEM_SEED_ENVELOPE_KIND,
            "payload": canonical_value,
            "digest": hashlib.sha256(canonical).hexdigest(),
        }
        return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

    @classmethod
    def from_bytes(cls, encoded: bytes) -> "SystemSeedEnvelope":
        """Mathematics: decode `E` only when UTF-8, envelope format, canonical payload, and digest all agree."""

        if not isinstance(encoded, bytes):
            raise SeedEnvelopeError("seed envelope encoding must be bytes")
        try:
            document = json.loads(encoded.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SeedEnvelopeError("seed envelope is not valid UTF-8 JSON") from exc
        if not isinstance(document, Mapping) or document.get("format") != SYSTEM_SEED_ENVELOPE_KIND:
            raise SeedEnvelopeError("unsupported seed envelope format")
        encoded_payload = document.get("payload")
        if not isinstance(encoded_payload, Mapping):
            raise SeedEnvelopeError("seed envelope payload must be a mapping")
        try:
            received_digest = _validate_digest(document.get("digest"), "seed envelope digest")
        except SeedNavigationError as exc:
            raise SeedEnvelopeError("seed envelope digest is invalid") from exc
        canonical = json.dumps(encoded_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        expected_digest = hashlib.sha256(canonical).hexdigest()
        if received_digest != expected_digest:
            raise SeedEnvelopeError("seed envelope digest mismatch")
        try:
            payload = decode_canonical_value(encoded_payload)
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            raise SeedEnvelopeError("seed envelope canonical payload is malformed") from exc
        if not isinstance(payload, Mapping):
            raise SeedEnvelopeError("decoded seed envelope payload must be a mapping")
        if encode_canonical_value(payload) != encoded_payload:
            raise SeedEnvelopeError("seed envelope canonical payload is not normalized")
        try:
            return cls._from_payload(payload)
        except SeedEnvelopeError:
            raise
        except SeedNavigationError as exc:
            raise SeedEnvelopeError("seed envelope seed payload is invalid") from exc

    @classmethod
    def _from_payload(cls, payload: Mapping[str, Any]) -> "SystemSeedEnvelope":
        """Mathematics: reconstruct `E` from verified payload coordinates and preserve the frontier as a finite set."""

        identity_payload = payload.get("identity")
        seed_payload = payload.get("seed")
        raw_frontier = payload.get("input_frontier", ())
        if not isinstance(identity_payload, Mapping) or not isinstance(seed_payload, Mapping):
            raise SeedEnvelopeError("seed envelope identity or seed is incomplete")
        if not isinstance(raw_frontier, (list, tuple)):
            raise SeedEnvelopeError("seed envelope input frontier must be a sequence")
        identity = SystemIdentity.from_snapshot(identity_payload)
        seed = SystemSeed.from_snapshot(seed_payload)
        frontier = tuple(SeedInputReceipt.from_snapshot(item) for item in raw_frontier)
        return cls(identity, payload.get("role"), payload.get("channel"), seed, frontier)

    def to_message(self, sender: str) -> Message:
        """Mathematics: lift envelope bytes into transport message `m=(sender,ρ(E),SEED,(kind,B))`."""

        _validate_label(sender, "seed envelope sender")
        route = self.route()
        return Message(
            sender=sender,
            recipient=route,
            op=SYSTEM_SEED_ENVELOPE_KIND,
            addr=route,
            body=(SYSTEM_SEED_ENVELOPE_KIND, self.to_bytes()),
        )

    @classmethod
    def from_message(cls, message: Message) -> "SystemSeedEnvelope":
        """Mathematics: invert the message lift only for exact operation kind and envelope body identity."""

        if not isinstance(message, Message):
            raise SeedEnvelopeError("seed envelope message must be a Message")
        if message.op != SYSTEM_SEED_ENVELOPE_KIND or len(message.body) != 2:
            raise SeedEnvelopeError("seed envelope message kind is invalid")
        kind, encoded = message.body
        if kind != SYSTEM_SEED_ENVELOPE_KIND or not isinstance(encoded, bytes):
            raise SeedEnvelopeError("seed envelope message body is invalid")
        envelope = cls.from_bytes(encoded)
        if message.recipient != envelope.route() or message.addr != envelope.route():
            raise SeedEnvelopeError("seed envelope message route does not match identity")
        return envelope

    def restore(self, expected_identity: SystemIdentity | None = None) -> HeadlessOS:
        """Mathematics: admit `restore(Σ)` only when an optional host identity equals `I`; then verify the seed digest."""

        if expected_identity is not None and expected_identity != self.identity:
            raise SeedEnvelopeError("seed envelope identity does not match host identity")
        try:
            return self.seed.restore()
        except SeedNavigationError as exc:
            raise SeedEnvelopeError("seed envelope seed cannot be restored") from exc
