"""Receiver-advertised recovery policy and reliable negotiation messages."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .reliability import ReliabilityPolicy, ReliableChannel


RECOVERY_POLICY_ADVERTISEMENT_KIND = "mailcpu.recovery.policy.advertisement"
RECOVERY_POLICY_OFFER_KIND = "mailcpu.recovery.policy.offer"
RECOVERY_POLICY_AGREEMENT_KIND = "mailcpu.recovery.policy.agreement"
DEFAULT_CHECKPOINT_KIND = "mailcpu.duplex-operation.v1"


class RecoveryPolicyError(ValueError):
    """A recovery policy, offer, agreement, or control-frame invariant failed."""


def _canonical(value: Any) -> bytes:
    """Mathematics: encode finite policy value `x` as `J(x)=JSON(sort_keys,compact)(x)` for identity hashing."""

    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise RecoveryPolicyError("recovery policy value is outside canonical JSON") from exc


def _labels(name: str, values: tuple[str, ...]) -> None:
    """Mathematics: require `values` to be a non-empty strictly increasing sequence in the finite label domain."""

    if not values or any(not isinstance(value, str) or not value for value in values) or tuple(sorted(set(values))) != values:
        raise RecoveryPolicyError(f"{name} must be a sorted unique non-empty tuple of labels")


def _positive(name: str, value: int) -> None:
    """Mathematics: require resource bound `value∈ℕ⁺` rather than allowing an empty recovery domain."""

    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise RecoveryPolicyError(f"{name} must be a positive integer")


@dataclass(frozen=True)
class RecoveryPolicyAdvertisement:
    """Receiver constraints for a future checkpoint and transport handoff."""

    protocol_version: int = 1
    checkpoint_kinds: tuple[str, ...] = (DEFAULT_CHECKPOINT_KIND,)
    transport_kinds: tuple[str, ...] = ("memory", "socket")
    max_window_size: int = 64
    min_lease_ticks: int = 1
    max_attempts: int = 4
    allow_cross_transport: bool = True
    supports_effect_ledger: bool = True

    def __post_init__(self) -> None:
        """Mathematics: validate `A=(v,K,T,W_max,L_min,A_max,X,E)` over finite protocol domains."""

        _positive("protocol_version", self.protocol_version)
        _labels("checkpoint_kinds", self.checkpoint_kinds)
        _labels("transport_kinds", self.transport_kinds)
        _positive("max_window_size", self.max_window_size)
        _positive("min_lease_ticks", self.min_lease_ticks)
        _positive("max_attempts", self.max_attempts)
        if not isinstance(self.allow_cross_transport, bool) or not isinstance(self.supports_effect_ledger, bool):
            raise RecoveryPolicyError("recovery advertisement feature flags must be boolean")

    def to_dict(self) -> dict[str, object]:
        """Mathematics: project advertisement `A` into stable wire coordinates without a mutable capability reference."""

        return {
            "protocol_version": self.protocol_version,
            "checkpoint_kinds": list(self.checkpoint_kinds),
            "transport_kinds": list(self.transport_kinds),
            "max_window_size": self.max_window_size,
            "min_lease_ticks": self.min_lease_ticks,
            "max_attempts": self.max_attempts,
            "allow_cross_transport": self.allow_cross_transport,
            "supports_effect_ledger": self.supports_effect_ledger,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RecoveryPolicyAdvertisement":
        """Mathematics: invert `J(A)` only when every discrete and numeric advertisement domain validates."""

        if not isinstance(payload, Mapping):
            raise RecoveryPolicyError("recovery advertisement must be a mapping")
        allow_cross_transport = payload.get("allow_cross_transport")
        supports_effect_ledger = payload.get("supports_effect_ledger")
        if not isinstance(allow_cross_transport, bool) or not isinstance(supports_effect_ledger, bool):
            raise RecoveryPolicyError("recovery advertisement feature flags must be boolean")
        try:
            return cls(
                int(payload["protocol_version"]),
                tuple(str(item) for item in payload["checkpoint_kinds"]),
                tuple(str(item) for item in payload["transport_kinds"]),
                int(payload["max_window_size"]),
                int(payload["min_lease_ticks"]),
                int(payload["max_attempts"]),
                allow_cross_transport,
                supports_effect_ledger,
            )
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise RecoveryPolicyError("recovery advertisement fields are invalid") from exc


@dataclass(frozen=True)
class RecoveryPolicyOffer:
    """Sender request for one checkpoint kind and target transport."""

    protocol_version: int
    checkpoint_kind: str
    source_transport: str
    target_transport: str
    reliability: ReliabilityPolicy
    requires_effect_ledger: bool = True

    def __post_init__(self) -> None:
        """Mathematics: validate offer `O=(v,k,T_s,T_t,W,L,A,E_req)` before intersection."""

        _positive("protocol_version", self.protocol_version)
        for name, value in (
            ("checkpoint_kind", self.checkpoint_kind),
            ("source_transport", self.source_transport),
            ("target_transport", self.target_transport),
        ):
            if not isinstance(value, str) or not value:
                raise RecoveryPolicyError(f"{name} must be a non-empty label")
        if not isinstance(self.reliability, ReliabilityPolicy):
            raise RecoveryPolicyError("recovery offer requires a ReliabilityPolicy")
        _positive("reliability.window_size", self.reliability.window_size)
        _positive("reliability.lease_ticks", self.reliability.lease_ticks)
        _positive("reliability.max_attempts", self.reliability.max_attempts)
        if not isinstance(self.requires_effect_ledger, bool):
            raise RecoveryPolicyError("requires_effect_ledger must be boolean")

    def to_dict(self) -> dict[str, object]:
        """Mathematics: project offer `O` with the sender's complete bounded reliability request."""

        return {
            "protocol_version": self.protocol_version,
            "checkpoint_kind": self.checkpoint_kind,
            "source_transport": self.source_transport,
            "target_transport": self.target_transport,
            "reliability": {
                "lease_ticks": self.reliability.lease_ticks,
                "max_attempts": self.reliability.max_attempts,
                "window_size": self.reliability.window_size,
            },
            "requires_effect_ledger": self.requires_effect_ledger,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RecoveryPolicyOffer":
        """Mathematics: reconstruct `O` only from typed transport labels and a positive reliability triple."""

        if not isinstance(payload, Mapping) or not isinstance(payload.get("reliability"), Mapping):
            raise RecoveryPolicyError("recovery offer fields are invalid")
        raw_policy = payload["reliability"]
        requires_effect_ledger = payload.get("requires_effect_ledger")
        if not isinstance(requires_effect_ledger, bool):
            raise RecoveryPolicyError("requires_effect_ledger must be boolean")
        try:
            return cls(
                int(payload["protocol_version"]),
                str(payload["checkpoint_kind"]),
                str(payload["source_transport"]),
                str(payload["target_transport"]),
                ReliabilityPolicy(
                    int(raw_policy["lease_ticks"]),
                    int(raw_policy["max_attempts"]),
                    int(raw_policy["window_size"]),
                ),
                requires_effect_ledger,
            )
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise RecoveryPolicyError("recovery offer fields are invalid") from exc


@dataclass(frozen=True)
class RecoveryPolicyAgreement:
    """Canonical receiver-approved intersection that a migration build can bind to a checkpoint."""

    protocol_version: int
    checkpoint_kind: str
    source_transport: str
    target_transport: str
    reliability: ReliabilityPolicy
    effect_ledger_required: bool
    advertisement_digest: str

    def __post_init__(self) -> None:
        """Mathematics: validate agreement `G=intersection(O,A)` and its 256-bit advertisement receipt."""

        _positive("protocol_version", self.protocol_version)
        for name, value in (
            ("checkpoint_kind", self.checkpoint_kind),
            ("source_transport", self.source_transport),
            ("target_transport", self.target_transport),
            ("advertisement_digest", self.advertisement_digest),
        ):
            if not isinstance(value, str) or not value:
                raise RecoveryPolicyError(f"{name} must be non-empty")
        if len(self.advertisement_digest) != 64 or any(char not in "0123456789abcdef" for char in self.advertisement_digest):
            raise RecoveryPolicyError("advertisement_digest must be lowercase SHA-256 hex")
        if not isinstance(self.reliability, ReliabilityPolicy):
            raise RecoveryPolicyError("agreement requires a ReliabilityPolicy")
        _positive("reliability.window_size", self.reliability.window_size)
        _positive("reliability.lease_ticks", self.reliability.lease_ticks)
        _positive("reliability.max_attempts", self.reliability.max_attempts)
        if not isinstance(self.effect_ledger_required, bool):
            raise RecoveryPolicyError("effect_ledger_required must be boolean")

    def to_dict(self) -> dict[str, object]:
        """Mathematics: project agreement `G` without including its derived self-fingerprint."""

        return {
            "protocol_version": self.protocol_version,
            "checkpoint_kind": self.checkpoint_kind,
            "source_transport": self.source_transport,
            "target_transport": self.target_transport,
            "reliability": {
                "lease_ticks": self.reliability.lease_ticks,
                "max_attempts": self.reliability.max_attempts,
                "window_size": self.reliability.window_size,
            },
            "effect_ledger_required": self.effect_ledger_required,
            "advertisement_digest": self.advertisement_digest,
        }

    @property
    def fingerprint(self) -> str:
        """Mathematics: calculate stable agreement identity `h(G)=SHA256(J(G))`."""

        return hashlib.sha256(_canonical(self.to_dict())).hexdigest()

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RecoveryPolicyAgreement":
        """Mathematics: invert agreement projection `J(G)` while preserving selected policy bounds."""

        if not isinstance(payload, Mapping) or not isinstance(payload.get("reliability"), Mapping):
            raise RecoveryPolicyError("recovery agreement fields are invalid")
        raw_policy = payload["reliability"]
        effect_ledger_required = payload.get("effect_ledger_required")
        if not isinstance(effect_ledger_required, bool):
            raise RecoveryPolicyError("effect_ledger_required must be boolean")
        try:
            return cls(
                int(payload["protocol_version"]),
                str(payload["checkpoint_kind"]),
                str(payload["source_transport"]),
                str(payload["target_transport"]),
                ReliabilityPolicy(
                    int(raw_policy["lease_ticks"]),
                    int(raw_policy["max_attempts"]),
                    int(raw_policy["window_size"]),
                ),
                effect_ledger_required,
                str(payload["advertisement_digest"]),
            )
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise RecoveryPolicyError("recovery agreement fields are invalid") from exc


def advertise_recovery_policy(
    *,
    checkpoint_kinds: tuple[str, ...] = (DEFAULT_CHECKPOINT_KIND,),
    transport_kinds: tuple[str, ...] = ("memory", "socket"),
    max_window_size: int = 64,
    min_lease_ticks: int = 1,
    max_attempts: int = 4,
    allow_cross_transport: bool = True,
    supports_effect_ledger: bool = True,
) -> RecoveryPolicyAdvertisement:
    """Mathematics: construct receiver capability vector `A` without granting it migration authority."""

    return RecoveryPolicyAdvertisement(
        1,
        checkpoint_kinds,
        transport_kinds,
        max_window_size,
        min_lease_ticks,
        max_attempts,
        allow_cross_transport,
        supports_effect_ledger,
    )


def negotiate_recovery_policy(
    offer: RecoveryPolicyOffer,
    advertisement: RecoveryPolicyAdvertisement,
) -> RecoveryPolicyAgreement:
    """Mathematics: admit `G=O∩A` iff discrete predicates hold and `(min(W),max(L),min(A))` is positive."""

    if not isinstance(offer, RecoveryPolicyOffer) or not isinstance(advertisement, RecoveryPolicyAdvertisement):
        raise RecoveryPolicyError("recovery negotiation requires typed offer and advertisement")
    if offer.protocol_version != advertisement.protocol_version:
        raise RecoveryPolicyError("recovery protocol versions do not intersect")
    if offer.checkpoint_kind not in advertisement.checkpoint_kinds:
        raise RecoveryPolicyError("receiver does not support the checkpoint kind")
    if offer.target_transport not in advertisement.transport_kinds:
        raise RecoveryPolicyError("receiver does not support the target transport")
    if offer.source_transport != offer.target_transport and not advertisement.allow_cross_transport:
        raise RecoveryPolicyError("receiver does not permit cross-transport migration")
    if offer.requires_effect_ledger and not advertisement.supports_effect_ledger:
        raise RecoveryPolicyError("receiver does not support the required effect ledger")
    window_size = min(offer.reliability.window_size, advertisement.max_window_size)
    lease_ticks = max(offer.reliability.lease_ticks, advertisement.min_lease_ticks)
    max_attempts = min(offer.reliability.max_attempts, advertisement.max_attempts)
    if min(window_size, lease_ticks, max_attempts) <= 0:
        raise RecoveryPolicyError("recovery policy intersection is empty")
    return RecoveryPolicyAgreement(
        offer.protocol_version,
        offer.checkpoint_kind,
        offer.source_transport,
        offer.target_transport,
        ReliabilityPolicy(lease_ticks, max_attempts, window_size),
        offer.requires_effect_ledger,
        hashlib.sha256(_canonical(advertisement.to_dict())).hexdigest(),
    )


class RecoveryPolicyChannel:
    """Carry receiver advertisements and sender offers/agreements through reliable peer-bound control frames."""

    def __init__(self, channel: ReliableChannel) -> None:
        """Mathematics: bind policy stream `P` to one reliable FIFO without adding a delivery ledger."""

        if not isinstance(channel, ReliableChannel):
            raise RecoveryPolicyError("policy channel requires a ReliableChannel")
        self.channel = channel

    def send_advertisement(self, advertisement: RecoveryPolicyAdvertisement) -> int:
        """Mathematics: emit `RDATA(advertisement)` only on an outbound policy FIFO."""

        if not isinstance(advertisement, RecoveryPolicyAdvertisement):
            raise RecoveryPolicyError("advertisement must be typed")
        return self._send(RECOVERY_POLICY_ADVERTISEMENT_KIND, advertisement.to_dict())

    def send_offer(self, offer: RecoveryPolicyOffer) -> int:
        """Mathematics: emit `RDATA(offer)` only on an outbound policy FIFO."""

        if not isinstance(offer, RecoveryPolicyOffer):
            raise RecoveryPolicyError("offer must be typed")
        return self._send(RECOVERY_POLICY_OFFER_KIND, offer.to_dict())

    def send_agreement(self, agreement: RecoveryPolicyAgreement) -> int:
        """Mathematics: emit `RDATA(agreement)` only on an outbound policy FIFO."""

        if not isinstance(agreement, RecoveryPolicyAgreement):
            raise RecoveryPolicyError("agreement must be typed")
        return self._send(RECOVERY_POLICY_AGREEMENT_KIND, agreement.to_dict())

    def receive_advertisement(self) -> RecoveryPolicyAdvertisement | None:
        """Mathematics: decode and consume `advertisement` only after kind and schema validation; refusal leaves `Q` unchanged."""

        return self._receive(RECOVERY_POLICY_ADVERTISEMENT_KIND, RecoveryPolicyAdvertisement.from_dict)

    def receive_offer(self) -> RecoveryPolicyOffer | None:
        """Mathematics: decode and consume `offer` only after kind and schema validation; refusal leaves `Q` unchanged."""

        return self._receive(RECOVERY_POLICY_OFFER_KIND, RecoveryPolicyOffer.from_dict)

    def receive_agreement(self) -> RecoveryPolicyAgreement | None:
        """Mathematics: decode and consume `agreement` only after kind and schema validation; refusal leaves `Q` unchanged."""

        return self._receive(RECOVERY_POLICY_AGREEMENT_KIND, RecoveryPolicyAgreement.from_dict)

    def service(self) -> tuple[int, ...]:
        """Mathematics: apply `P := P \\ ACKS` for the policy sender without changing policy semantics."""

        return self.channel.process_ack()

    def _send(self, kind: str, value: Mapping[str, Any]) -> int:
        """Mathematics: map typed control value `v` to `RDATA(kind,v)` while retaining sequence until `ACK`."""

        if self.channel.destination != self.channel.peer:
            raise RecoveryPolicyError("policy control send requires an outbound channel")
        return self.channel.send({"kind": kind, "value": dict(value)})

    def _receive(self, kind: str, parser: Callable[[Mapping[str, Any]], Any]) -> Any | None:
        """Mathematics: apply `peek→validate(kind, schema)→consume→ACK` and never acknowledge invalid control frames."""

        if self.channel.destination != self.channel.source:
            raise RecoveryPolicyError("policy control receive requires an inbound channel")
        peeked = self.channel.peek()
        if peeked is None:
            return None
        sequence, payload = peeked
        if not isinstance(payload, Mapping) or payload.get("kind") != kind or not isinstance(payload.get("value"), Mapping):
            raise RecoveryPolicyError("recovery policy control kind is invalid")
        parsed = parser(payload["value"])
        received = self.channel.receive()
        if received is not None and received[0] != sequence:
            raise RecoveryPolicyError("recovery policy sequence changed during validation")
        return parsed if received is not None else None

