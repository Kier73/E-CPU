"""Receiver-verified evidence for paths composed of passive carriers and observer-hosts.

This is an evidence adapter, not a new router, executor, or authority.  Native
SAB channel observations describe candidate edges; native ObserverReceipts
bind operational observations.  Neither is authenticated by its content digest.
Receiver-owned validators decide which reported deliveries and observations
may enter a path witness, and their policy/configuration is never serialized.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import re
from typing import Any, Callable, Mapping, Sequence

from .observer_orbit import ObserverContract, ObserverReceipt, verify_observer_receipt
from .semantic_translation import RepresentationRef
from .substrate_bootstrap import ChannelObservation

SCHEMA = "mailcpu.observer-host-path.v1"
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_MODES = frozenset({"carrier", "observe", "transform"})


class ObserverPathError(ValueError):
    """A path, observer, carrier, or receiver verification was not justified."""


def _integer(value: Any, label: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ObserverPathError(f"{label} must be an integer at least {minimum}")
    return value


def _name(value: Any, label: str) -> str:
    if type(value) is not str or _NAME.fullmatch(value) is None:
        raise ObserverPathError(f"{label} must be a bounded operational identifier")
    return value


def _hash(value: Any, label: str) -> str:
    if type(value) is not str or _HASH.fullmatch(value) is None:
        raise ObserverPathError(f"{label} must be lowercase SHA-256")
    return value


def _bytes(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ObserverPathError("path evidence is not finite canonical JSON") from exc


def _digest(value: Any) -> str:
    return sha256(_bytes(value)).hexdigest()


@dataclass(frozen=True, slots=True)
class ObserverPathStage:
    """One native carrier edge or local observer-host relation.

    A carrier transfers the *same* representation identity between loci. An
    observer operates at one locus. A transform may change representation only
    when its subject-state digests and an independent receiver validator agree.
    """

    mode: str
    source: str
    target: str
    input_ref: RepresentationRef
    output_ref: RepresentationRef
    channel: ChannelObservation | None = None
    contract: ObserverContract | None = None
    receipt: ObserverReceipt | None = None
    payload_bytes: int = 0

    def __post_init__(self) -> None:
        if self.mode not in _MODES:
            raise ObserverPathError("unknown path stage mode")
        _name(self.source, "stage source")
        _name(self.target, "stage target")
        if not isinstance(self.input_ref, RepresentationRef) or not isinstance(self.output_ref, RepresentationRef):
            raise ObserverPathError("stage requires native typed representation references")
        _integer(self.payload_bytes, "payload bytes")
        if self.mode == "carrier":
            if self.source == self.target or self.input_ref != self.output_ref:
                raise ObserverPathError("a passive carrier cannot transform content or loop locally")
            if not isinstance(self.channel, ChannelObservation) or self.contract is not None or self.receipt is not None:
                raise ObserverPathError("carrier requires only a native channel observation")
            if (self.channel.source, self.channel.target) != (self.source, self.target):
                raise ObserverPathError("channel direction differs from stage")
        else:
            if self.source != self.target:
                raise ObserverPathError("an observer operation occupies one locus")
            if self.channel is not None or not isinstance(self.contract, ObserverContract) or not isinstance(self.receipt, ObserverReceipt):
                raise ObserverPathError("active stage requires native observer contract and receipt")
            if self.contract.observer_id != self.source:
                raise ObserverPathError("observer identity differs from the occupied locus")
            if self.mode == "observe" and self.input_ref != self.output_ref:
                raise ObserverPathError("read-only observation cannot claim a content transformation")

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode, "source": self.source, "target": self.target,
            "input_ref": self.input_ref.to_dict(), "output_ref": self.output_ref.to_dict(),
            "channel": None if self.channel is None else self.channel.to_dict(),
            "contract": None if self.contract is None else self.contract.to_dict(),
            "receipt": None if self.receipt is None else self.receipt.to_dict(),
            "payload_bytes": self.payload_bytes,
        }


@dataclass(frozen=True, slots=True)
class VerifiedObserverPath:
    """Content-bound path witness after independently supplied receiver decisions."""

    source: str
    destination: str
    ground: RepresentationRef
    context_digest: str
    receiver_policy_digest: str
    observed_at: int
    input_ref: RepresentationRef
    output_ref: RepresentationRef
    stages: tuple[dict[str, Any], ...]
    path_digest: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA, "source": self.source, "destination": self.destination,
            "ground": self.ground.to_dict(), "context_digest": self.context_digest,
            "receiver_policy_digest": self.receiver_policy_digest, "observed_at": self.observed_at, "input_ref": self.input_ref.to_dict(),
            "output_ref": self.output_ref.to_dict(), "stages": list(self.stages),
            "path_digest": self.path_digest,
            "verification_scope": "receiver_callbacks_not_external_attestation",
        }


# These callbacks are trusted, receiver-installed and never read from a frame,
# channel advertisement, source-submitted certificate, or serialized witness.
CarrierVerifier = Callable[[ObserverPathStage], bool]
ObserverVerifier = Callable[[ObserverPathStage], bool]


def verify_observer_path(
    stages: Sequence[ObserverPathStage],
    *,
    ground: RepresentationRef,
    context_digest: str,
    receiver_policy_digest: str,
    observed_at: int,
    verify_carrier: CarrierVerifier,
    verify_observer: ObserverVerifier,
    max_stages: int = 64,
) -> VerifiedObserverPath:
    """Accept an exact route only when every edge/locus passes receiver checks.

    ChannelObservation is an *observed offer*, not delivery evidence. An
    ObserverReceipt is content evidence, not identity authentication. These
    objects are admitted only after receiver-owned callback decisions.
    The verifier neither executes transitions nor supplies capabilities.
    """
    if not isinstance(ground, RepresentationRef):
        raise ObserverPathError("a native computational-Ground reference is required")
    _hash(context_digest, "context digest")
    _hash(receiver_policy_digest, "receiver policy digest")
    now = _integer(observed_at, "observation coordinate")
    limit = _integer(max_stages, "max_stages", minimum=1)
    if not isinstance(stages, (list, tuple)) or not (1 <= len(stages) <= limit):
        raise ObserverPathError("path exceeds the finite stage budget")
    if not callable(verify_carrier) or not callable(verify_observer):
        raise ObserverPathError("receiver-owned verification functions are required")
    previous: ObserverPathStage | None = None
    accepted: list[dict[str, Any]] = []
    seen_receipts: set[str] = set()
    for index, stage in enumerate(stages):
        if not isinstance(stage, ObserverPathStage):
            raise ObserverPathError(f"path stage {index} is not native and typed")
        if previous is not None:
            if stage.source != previous.target or stage.input_ref != previous.output_ref:
                raise ObserverPathError("path adjacency or representation continuity is broken")
        if stage.mode == "carrier":
            edge = stage.channel
            assert edge is not None
            if not edge.observed_at <= now <= edge.expires_at:
                raise ObserverPathError("channel evidence is expired or not yet valid")
            if stage.input_ref.type_id not in edge.carries:
                raise ObserverPathError("channel cannot carry the declared representation type")
            if stage.payload_bytes > edge.max_payload_bytes:
                raise ObserverPathError("channel payload exceeds its observed bound")
            if verify_carrier(stage) is not True:
                raise ObserverPathError("receiver did not verify carrier delivery")
            stage_identity = edge.evidence_digest
        else:
            contract = stage.contract
            receipt = stage.receipt
            assert contract is not None and receipt is not None
            if contract.subject != stage.input_ref or contract.interpretation != ground:
                raise ObserverPathError("observer's subject or Ground is inconsistent with the path")
            if contract.context_digest != context_digest:
                raise ObserverPathError("observer context differs from the path")
            if not verify_observer_receipt(contract, receipt):
                raise ObserverPathError("native observer receipt does not match its contract")
            if receipt.input_digest != stage.input_ref.content_digest:
                raise ObserverPathError("receipt input does not match the path representation")
            if stage.mode == "transform":
                if (receipt.subject_state_before_digest != stage.input_ref.content_digest
                    or receipt.subject_state_after_digest != stage.output_ref.content_digest):
                    raise ObserverPathError("transformation lacks exact before/after content evidence")
            elif receipt.subject_state_before_digest is not None and (
                receipt.subject_state_before_digest != stage.input_ref.content_digest
                or receipt.subject_state_after_digest != stage.output_ref.content_digest
            ):
                raise ObserverPathError("observation claims inconsistent subject-state evidence")
            if receipt.digest in seen_receipts:
                raise ObserverPathError("one observer receipt cannot stand for two path transitions")
            seen_receipts.add(receipt.digest)
            if verify_observer(stage) is not True:
                raise ObserverPathError("receiver did not admit observer operation")
            stage_identity = receipt.digest
        accepted.append({"ordinal": index, "mode": stage.mode,
                         "source": stage.source, "target": stage.target,
                         "input_ref": stage.input_ref.to_dict(),
                         "output_ref": stage.output_ref.to_dict(),
                         "evidence_digest": stage_identity,
                         "stage_digest": _digest(stage.to_dict())})
        previous = stage
    assert previous is not None
    body = {"schema": SCHEMA, "source": stages[0].source,
            "destination": previous.target, "ground": ground.to_dict(),
            "context_digest": context_digest, "receiver_policy_digest": receiver_policy_digest, "observed_at": now,
            "input_ref": stages[0].input_ref.to_dict(),
            "output_ref": previous.output_ref.to_dict(), "stages": accepted,
            "verification_scope": "receiver_callbacks_not_external_attestation"}
    return VerifiedObserverPath(
        body["source"], body["destination"], ground, context_digest, receiver_policy_digest, now,
        stages[0].input_ref, previous.output_ref, tuple(accepted), _digest(body),
    )


def check_observer_path_receipt(receipt: VerifiedObserverPath, stages: Sequence[ObserverPathStage],
                                *, verify_carrier: CarrierVerifier, verify_observer: ObserverVerifier) -> bool:
    """Independently rebuild and compare exact content identity of path evidence."""
    if not isinstance(receipt, VerifiedObserverPath):
        return False
    try:
        other = verify_observer_path(stages, ground=receipt.ground,
                                     context_digest=receipt.context_digest,
                                     receiver_policy_digest=receipt.receiver_policy_digest,
                                     observed_at=receipt.observed_at,
                                     verify_carrier=verify_carrier,
                                     verify_observer=verify_observer)
        return other.to_dict() == receipt.to_dict()
    except (ObserverPathError, TypeError, ValueError):
        return False