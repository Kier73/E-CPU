"""Composable observer receipts and mathematically addressed Virtual Ground projections.

This module connects existing E-CPU identities rather than introducing a second
memory, clock, or authority system.

A ContextualOrbitAddress binds:
    system identity + exact base Virtual Ground + Computational Ground
    + typed scheduler coordinate + one admitted Structural Memory revision.

The Structural Memory coordinate is relative to the base Virtual Ground. The
navigator reads that exact coordinate through the admitted generator. It does
not enumerate the intervening system ticks, synthesize a full OS snapshot, or
silently fall back to breadth-first search or SystemSeed replay.

A VirtualGroundProjection is intentionally a symbolic projection of one
coordinate/value under an exact system anchor. It is not a SystemSeed, an OS
snapshot, or a claim that one scalar reconstructs the hosted machine.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import json
import re
from typing import Any, Mapping, Sequence

from .law_certifier import (
    HorizonExceeded,
    Law,
    Refused,
    find_coordinate_gf2_bit,
    FiniteGraphInverseIndex,
    find_coordinate_int,
    find_coordinate_lcg_adic,
    navigate_guarded,
)
from .seed import SystemIdentity
from .semantic_translation import (
    ObservationContract,
    RepresentationRef,
    canonical_value_digest,
    structural_memory_spec_representation_ref,
)
from .structural_memory import (
    StructuralMemoryError,
    StructuralMemoryReadReceipt,
    StructuralMemoryRegistry,
)
from .temporal import CausalStamp, MonotonicReading, SchedulerReading, TemporalFrame, WallTimeReading
from .virtual_layer import VirtualGroundRef, VirtualStructuralMemoryRef


class ObserverOrbitError(ValueError):
    """An observer contract, receipt, composition, or contextual orbit address is invalid."""


_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_COMPLEXITY = {
    "int": "O(1)",
    "fgraph": "O(1)",
    "lcg": "O(log n)",
    "gf2": "O(log n)",
}


def _identifier(value: Any, label: str) -> str:
    """Mathematics: constrain observer and operation identities to a bounded safe identifier alphabet."""
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise ObserverOrbitError(f"{label} must be a safe 1-128 character identifier")
    return value


def _digest(value: Any, label: str) -> str:
    """Mathematics: require a lowercase 256-bit SHA-256 content digest."""
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise ObserverOrbitError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _positive_int(value: Any, label: str, *, minimum: int = 1) -> int:
    """Mathematics: require a strict integer at or above the declared lower bound, excluding Booleans."""
    if type(value) is not int or value < minimum:
        raise ObserverOrbitError(f"{label} must be an integer >= {minimum}")
    return value


def _canonical_json(value: Any, label: str) -> str:
    """Mathematics: encode finite JSON deterministically with sorted keys and compact separators."""
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ObserverOrbitError(f"{label} must be finite canonical JSON") from exc


def _clone_json(value: Any, label: str) -> Any:
    """Mathematics: detach a JSON value through canonical encoding and decoding."""
    encoded = _canonical_json(value, label)
    try:
        return json.loads(encoded)
    except json.JSONDecodeError as exc:
        raise ObserverOrbitError(f"{label} is not valid JSON") from exc


def _freeze_json(value: Any) -> Any:
    """Mathematics: recursively freeze mappings and sequences without changing their JSON meaning."""
    if isinstance(value, dict):
        return _FrozenDict({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    return value


def _thaw_json(value: Any) -> Any:
    """Mathematics: convert frozen mappings and tuples into detached JSON dictionaries and lists."""
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_thaw_json(item) for item in value]
    return value


class _FrozenDict(dict):
    """A JSON-compatible mapping that cannot be mutated after admission."""

    def _immutable(self, *args: Any, **kwargs: Any) -> None:
        """Mathematics: reject any mutation of a value after it has been admitted as immutable observer context."""
        raise TypeError("observer-orbit values are immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable
    __ior__ = _immutable


def _temporal_frame_from_dict(payload: Mapping[str, Any]) -> TemporalFrame:
    """Mathematics: reconstruct typed temporal readings without conflating scheduler, causal, wall, or monotonic coordinates."""
    expected = {
        "actor_id", "monotonic", "wall", "causal", "scheduler",
        "event_lambda", "chronon_phase", "chemical_tau",
    }
    if not isinstance(payload, Mapping) or set(payload) != expected:
        raise ObserverOrbitError("temporal frame fields are invalid")
    monotonic = payload["monotonic"]
    wall = payload["wall"]
    causal = payload["causal"]
    scheduler = payload["scheduler"]
    if monotonic is not None:
        if not isinstance(monotonic, Mapping) or set(monotonic) != {"actor_id", "segment", "elapsed_ns"}:
            raise ObserverOrbitError("monotonic reading fields are invalid")
        monotonic = MonotonicReading(monotonic["actor_id"], monotonic["segment"], monotonic["elapsed_ns"])
    if wall is not None:
        if not isinstance(wall, Mapping) or set(wall) != {"actor_id", "utc_ns", "sample_index"}:
            raise ObserverOrbitError("wall reading fields are invalid")
        wall = WallTimeReading(wall["actor_id"], wall["utc_ns"], wall["sample_index"])
    if causal is not None:
        if not isinstance(causal, Mapping):
            raise ObserverOrbitError("causal stamp must be an object")
        causal = CausalStamp.from_dict(causal)
    if scheduler is not None:
        if not isinstance(scheduler, Mapping) or set(scheduler) != {"scheduler_id", "tick"}:
            raise ObserverOrbitError("scheduler reading fields are invalid")
        scheduler = SchedulerReading(scheduler["scheduler_id"], scheduler["tick"])
    phase = payload["chronon_phase"]
    if phase is not None:
        if not isinstance(phase, (list, tuple)) or len(phase) != 2:
            raise ObserverOrbitError("chronon_phase must contain a real/imaginary pair")
        phase = (phase[0], phase[1])
    return TemporalFrame(
        actor_id=payload["actor_id"],
        monotonic=monotonic,
        wall=wall,
        causal=causal,
        scheduler=scheduler,
        event_lambda=payload["event_lambda"],
        chronon_phase=phase,
        chemical_tau=payload["chemical_tau"],
    )


@dataclass(frozen=True)
class ObserverContract:
    """Versioned observer identity and the exact semantics of its bounded projection.

    The subject identifies the representation being observed; interpretation
    names the Ground that gives that representation meaning. These identities
    are separate from the projection schema and from host authority.
    """

    observer_id: str
    revision: int
    subject: RepresentationRef
    interpretation: RepresentationRef
    observation: ObservationContract
    context_digest: str
    lineage_digest: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.observer_id, "observer_id")
        _positive_int(self.revision, "observer revision")
        if not isinstance(self.subject, RepresentationRef):
            raise ObserverOrbitError("observer subject must be a RepresentationRef")
        if not isinstance(self.interpretation, RepresentationRef):
            raise ObserverOrbitError("observer interpretation must be a RepresentationRef")
        if not isinstance(self.observation, ObservationContract):
            raise ObserverOrbitError("observer observation must be an ObservationContract")
        _digest(self.context_digest, "observer context_digest")
        if self.lineage_digest is not None:
            _digest(self.lineage_digest, "observer lineage_digest")

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize the validated value into its versioned JSON representation."""
        return {
            "schema": "mailcpu.observer.contract.v1",
            "observer_id": self.observer_id,
            "revision": self.revision,
            "subject": self.subject.to_dict(),
            "interpretation": self.interpretation.to_dict(),
            "observation": self.observation.to_dict(),
            "context_digest": self.context_digest,
            "lineage_digest": self.lineage_digest,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ObserverContract":
        """Mathematics: reconstruct the value from its exact versioned JSON representation and revalidate its invariants."""
        expected = {
            "schema", "observer_id", "revision", "subject", "interpretation",
            "observation", "context_digest", "lineage_digest",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ObserverOrbitError("observer contract fields are invalid")
        if payload["schema"] != "mailcpu.observer.contract.v1":
            raise ObserverOrbitError("unsupported observer contract schema")
        return cls(
            observer_id=payload["observer_id"],
            revision=payload["revision"],
            subject=RepresentationRef.from_dict(payload["subject"]),
            interpretation=RepresentationRef.from_dict(payload["interpretation"]),
            observation=ObservationContract.from_dict(payload["observation"]),
            context_digest=payload["context_digest"],
            lineage_digest=payload["lineage_digest"],
        )

    @property
    def digest(self) -> str:
        """Mathematics: compute SHA-256 identity over the canonical serialized representation."""
        return canonical_value_digest(self.to_dict())


@dataclass(frozen=True)
class ObserverReceipt:
    """Content-addressed evidence for one observer operation.

    Digests identify content and bind provenance. They are not signatures and
    do not authenticate a remote observer or confer execution authority.
    """

    observer_id: str
    revision: int
    contract_digest: str
    subject: RepresentationRef
    interpretation: RepresentationRef
    observation: ObservationContract
    operation_id: str
    input_digest: str
    context_digest: str
    projection_json: str
    projection_digest: str
    time_frame: TemporalFrame | None = None
    observer_state_before_digest: str | None = None
    observer_state_after_digest: str | None = None
    subject_state_before_digest: str | None = None
    subject_state_after_digest: str | None = None
    evidence: tuple[RepresentationRef, ...] = ()

    def __post_init__(self) -> None:
        _identifier(self.observer_id, "receipt observer_id")
        _positive_int(self.revision, "receipt revision")
        for name in ("contract_digest", "input_digest", "context_digest", "projection_digest"):
            _digest(getattr(self, name), name)
        if not isinstance(self.subject, RepresentationRef) or not isinstance(self.interpretation, RepresentationRef):
            raise ObserverOrbitError("receipt subject and interpretation must be RepresentationRef values")
        if not isinstance(self.observation, ObservationContract):
            raise ObserverOrbitError("receipt observation must be an ObservationContract")
        _identifier(self.operation_id, "operation_id")
        if not isinstance(self.projection_json, str):
            raise ObserverOrbitError("projection_json must be a string")
        try:
            projection = json.loads(self.projection_json)
        except json.JSONDecodeError as exc:
            raise ObserverOrbitError("projection_json is malformed") from exc
        if _canonical_json(projection, "projection") != self.projection_json:
            raise ObserverOrbitError("projection_json is not canonical")
        if canonical_value_digest(projection) != self.projection_digest:
            raise ObserverOrbitError("projection digest does not match projection content")
        for before, after, label in (
            (self.observer_state_before_digest, self.observer_state_after_digest, "observer state"),
            (self.subject_state_before_digest, self.subject_state_after_digest, "subject state"),
        ):
            if (before is None) != (after is None):
                raise ObserverOrbitError(f"{label} before/after digests must be supplied together")
            if before is not None:
                _digest(before, f"{label} before digest")
                _digest(after, f"{label} after digest")
        if self.time_frame is not None:
            if not isinstance(self.time_frame, TemporalFrame):
                raise ObserverOrbitError("receipt time_frame must be a TemporalFrame")
            if self.time_frame.actor_id != self.observer_id:
                raise ObserverOrbitError("receipt time frame belongs to another observer")
        if not isinstance(self.evidence, (tuple, list)) or any(not isinstance(item, RepresentationRef) for item in self.evidence):
            raise ObserverOrbitError("receipt evidence must contain RepresentationRef values")
        evidence = tuple(self.evidence)
        if len({(item.type_id, item.schema_version, item.content_digest) for item in evidence}) != len(evidence):
            raise ObserverOrbitError("receipt evidence references must be unique")
        object.__setattr__(self, "evidence", evidence)

    @classmethod
    def issue(
        cls,
        contract: ObserverContract,
        *,
        operation_id: str,
        input_digest: str,
        projection_value: Any,
        time_frame: TemporalFrame | None = None,
        observer_state_before_digest: str | None = None,
        observer_state_after_digest: str | None = None,
        subject_state_before_digest: str | None = None,
        subject_state_after_digest: str | None = None,
        evidence: Sequence[RepresentationRef] = (),
    ) -> "ObserverReceipt":
        """Mathematics: bind an observer operation, canonical projection, time frame, and evidence into one receipt."""
        if not isinstance(contract, ObserverContract):
            raise ObserverOrbitError("receipt issuance requires an ObserverContract")
        projection_json = _canonical_json(projection_value, "observer projection")
        return cls(
            observer_id=contract.observer_id,
            revision=contract.revision,
            contract_digest=contract.digest,
            subject=contract.subject,
            interpretation=contract.interpretation,
            observation=contract.observation,
            operation_id=operation_id,
            input_digest=input_digest,
            context_digest=contract.context_digest,
            projection_json=projection_json,
            projection_digest=canonical_value_digest(projection_value),
            time_frame=time_frame,
            observer_state_before_digest=observer_state_before_digest,
            observer_state_after_digest=observer_state_after_digest,
            subject_state_before_digest=subject_state_before_digest,
            subject_state_after_digest=subject_state_after_digest,
            evidence=tuple(evidence),
        )

    @property
    def projection(self) -> Any:
        """Mathematics: decode and return a detached JSON view of the stored projection."""
        return json.loads(self.projection_json)

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize the validated value into its versioned JSON representation."""
        return {
            "schema": "mailcpu.observer.receipt.v1",
            "observer_id": self.observer_id,
            "revision": self.revision,
            "contract_digest": self.contract_digest,
            "subject": self.subject.to_dict(),
            "interpretation": self.interpretation.to_dict(),
            "observation": self.observation.to_dict(),
            "operation_id": self.operation_id,
            "input_digest": self.input_digest,
            "context_digest": self.context_digest,
            "projection_json": self.projection_json,
            "projection_digest": self.projection_digest,
            "time_frame": None if self.time_frame is None else self.time_frame.to_dict(),
            "observer_state_before_digest": self.observer_state_before_digest,
            "observer_state_after_digest": self.observer_state_after_digest,
            "subject_state_before_digest": self.subject_state_before_digest,
            "subject_state_after_digest": self.subject_state_after_digest,
            "evidence": [item.to_dict() for item in self.evidence],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ObserverReceipt":
        """Mathematics: reconstruct the value from its exact versioned JSON representation and revalidate its invariants."""
        expected = {
            "schema", "observer_id", "revision", "contract_digest", "subject",
            "interpretation", "observation", "operation_id", "input_digest",
            "context_digest", "projection_json", "projection_digest", "time_frame",
            "observer_state_before_digest", "observer_state_after_digest",
            "subject_state_before_digest", "subject_state_after_digest", "evidence",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ObserverOrbitError("observer receipt fields are invalid")
        if payload["schema"] != "mailcpu.observer.receipt.v1":
            raise ObserverOrbitError("unsupported observer receipt schema")
        raw_frame = payload["time_frame"]
        if raw_frame is not None and not isinstance(raw_frame, Mapping):
            raise ObserverOrbitError("observer receipt time_frame must be an object")
        raw_evidence = payload["evidence"]
        if not isinstance(raw_evidence, list):
            raise ObserverOrbitError("observer receipt evidence must be an array")
        return cls(
            observer_id=payload["observer_id"],
            revision=payload["revision"],
            contract_digest=payload["contract_digest"],
            subject=RepresentationRef.from_dict(payload["subject"]),
            interpretation=RepresentationRef.from_dict(payload["interpretation"]),
            observation=ObservationContract.from_dict(payload["observation"]),
            operation_id=payload["operation_id"],
            input_digest=payload["input_digest"],
            context_digest=payload["context_digest"],
            projection_json=payload["projection_json"],
            projection_digest=payload["projection_digest"],
            time_frame=None if raw_frame is None else _temporal_frame_from_dict(raw_frame),
            observer_state_before_digest=payload["observer_state_before_digest"],
            observer_state_after_digest=payload["observer_state_after_digest"],
            subject_state_before_digest=payload["subject_state_before_digest"],
            subject_state_after_digest=payload["subject_state_after_digest"],
            evidence=tuple(RepresentationRef.from_dict(item) for item in raw_evidence),
        )

    @property
    def digest(self) -> str:
        """Mathematics: compute SHA-256 identity over the canonical serialized representation."""
        return canonical_value_digest(self.to_dict())


def verify_observer_receipt(contract: ObserverContract, receipt: ObserverReceipt) -> bool:
    """Mathematics: verify exact observer identity, revision, context, projection, and receipt digests."""
    if not isinstance(contract, ObserverContract) or not isinstance(receipt, ObserverReceipt):
        return False
    return (
        receipt.observer_id == contract.observer_id
        and receipt.revision == contract.revision
        and receipt.contract_digest == contract.digest
        and receipt.subject == contract.subject
        and receipt.interpretation == contract.interpretation
        and receipt.observation == contract.observation
        and receipt.context_digest == contract.context_digest
        and canonical_value_digest(receipt.projection) == receipt.projection_digest
    )


@dataclass(frozen=True)
class ObserverComposition:
    """A declared set of observers whose outputs may be collected for one request.

    Composition is aggregation, not consensus: member projections remain
    distinct and no equality, averaging, or majority rule is implied.
    """

    composition_id: str
    revision: int
    members: tuple[ObserverContract, ...]

    def __post_init__(self) -> None:
        _identifier(self.composition_id, "composition_id")
        _positive_int(self.revision, "composition revision")
        if not isinstance(self.members, (tuple, list)) or len(self.members) < 2:
            raise ObserverOrbitError("observer composition requires at least two contracts")
        members = tuple(self.members)
        if any(not isinstance(item, ObserverContract) for item in members):
            raise ObserverOrbitError("composition members must be ObserverContract values")
        if len({item.observer_id for item in members}) != len(members):
            raise ObserverOrbitError("composition observer identities must be unique")
        anchor = members[0]
        if any(
            item.subject != anchor.subject
            or item.interpretation != anchor.interpretation
            or item.context_digest != anchor.context_digest
            for item in members[1:]
        ):
            raise ObserverOrbitError("composition members must share subject, interpretation, and context")
        object.__setattr__(self, "members", members)

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize the validated value into its versioned JSON representation."""
        return {
            "schema": "mailcpu.observer.composition.v1",
            "composition_id": self.composition_id,
            "revision": self.revision,
            "members": [item.to_dict() for item in self.members],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ObserverComposition":
        """Mathematics: reconstruct the value from its exact versioned JSON representation and revalidate its invariants."""
        if (
            not isinstance(payload, Mapping)
            or set(payload) != {"schema", "composition_id", "revision", "members"}
            or payload["schema"] != "mailcpu.observer.composition.v1"
            or not isinstance(payload["members"], list)
        ):
            raise ObserverOrbitError("observer composition fields are invalid")
        return cls(
            payload["composition_id"],
            payload["revision"],
            tuple(ObserverContract.from_dict(item) for item in payload["members"]),
        )

    @property
    def digest(self) -> str:
        """Mathematics: compute SHA-256 identity over the canonical serialized representation."""
        return canonical_value_digest(self.to_dict())


@dataclass(frozen=True)
class ObserverMemberReceipt:
    """One independently preserved observer result inside an aggregate."""

    observer_id: str
    contract_digest: str
    receipt_digest: str
    projection_digest: str
    projection_json: str
    time_frame_digest: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.observer_id, "member observer_id")
        for name in ("contract_digest", "receipt_digest", "projection_digest"):
            _digest(getattr(self, name), name)
        if not isinstance(self.projection_json, str):
            raise ObserverOrbitError("member projection_json must be a string")
        try:
            projection = json.loads(self.projection_json)
        except json.JSONDecodeError as exc:
            raise ObserverOrbitError("member projection_json is malformed") from exc
        if _canonical_json(projection, "member projection") != self.projection_json:
            raise ObserverOrbitError("member projection_json is not canonical")
        if canonical_value_digest(projection) != self.projection_digest:
            raise ObserverOrbitError("member projection digest does not match content")
        if self.time_frame_digest is not None:
            _digest(self.time_frame_digest, "time_frame_digest")

    @property
    def projection(self) -> Any:
        """Mathematics: decode and return a detached JSON view of the stored projection."""
        return json.loads(self.projection_json)

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize the validated value into its versioned JSON representation."""
        return {
            "observer_id": self.observer_id,
            "contract_digest": self.contract_digest,
            "receipt_digest": self.receipt_digest,
            "projection_digest": self.projection_digest,
            "projection_json": self.projection_json,
            "time_frame_digest": self.time_frame_digest,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ObserverMemberReceipt":
        """Mathematics: reconstruct the value from its exact versioned JSON representation and revalidate its invariants."""
        expected = {
            "observer_id", "contract_digest", "receipt_digest", "projection_digest",
            "projection_json", "time_frame_digest",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ObserverOrbitError("observer member receipt fields are invalid")
        return cls(**dict(payload))


@dataclass(frozen=True)
class ObserverAggregateReceipt:
    """Evidence that a declared set of observer receipts was collected together."""

    composition_digest: str
    operation_id: str
    input_digest: str
    subject: RepresentationRef
    interpretation: RepresentationRef
    context_digest: str
    members: tuple[ObserverMemberReceipt, ...]

    def __post_init__(self) -> None:
        _digest(self.composition_digest, "composition_digest")
        _identifier(self.operation_id, "operation_id")
        _digest(self.input_digest, "input_digest")
        if not isinstance(self.subject, RepresentationRef) or not isinstance(self.interpretation, RepresentationRef):
            raise ObserverOrbitError("aggregate subject and interpretation must be RepresentationRef values")
        _digest(self.context_digest, "context_digest")
        if not isinstance(self.members, (tuple, list)) or len(self.members) < 2:
            raise ObserverOrbitError("aggregate requires at least two member receipts")
        members = tuple(self.members)
        if any(not isinstance(item, ObserverMemberReceipt) for item in members):
            raise ObserverOrbitError("aggregate members must be ObserverMemberReceipt values")
        if len({item.observer_id for item in members}) != len(members):
            raise ObserverOrbitError("aggregate observer identities must be unique")
        object.__setattr__(self, "members", members)

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize the validated value into its versioned JSON representation."""
        return {
            "schema": "mailcpu.observer.aggregate.v1",
            "composition_digest": self.composition_digest,
            "operation_id": self.operation_id,
            "input_digest": self.input_digest,
            "subject": self.subject.to_dict(),
            "interpretation": self.interpretation.to_dict(),
            "context_digest": self.context_digest,
            "members": [item.to_dict() for item in self.members],
            "semantics": "aggregation-not-consensus",
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ObserverAggregateReceipt":
        """Mathematics: reconstruct the value from its exact versioned JSON representation and revalidate its invariants."""
        expected = {
            "schema", "composition_digest", "operation_id", "input_digest",
            "subject", "interpretation", "context_digest", "members", "semantics",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ObserverOrbitError("observer aggregate fields are invalid")
        if payload["schema"] != "mailcpu.observer.aggregate.v1" or payload["semantics"] != "aggregation-not-consensus":
            raise ObserverOrbitError("unsupported observer aggregate semantics")
        if not isinstance(payload["members"], list):
            raise ObserverOrbitError("observer aggregate members must be an array")
        return cls(
            composition_digest=payload["composition_digest"],
            operation_id=payload["operation_id"],
            input_digest=payload["input_digest"],
            subject=RepresentationRef.from_dict(payload["subject"]),
            interpretation=RepresentationRef.from_dict(payload["interpretation"]),
            context_digest=payload["context_digest"],
            members=tuple(ObserverMemberReceipt.from_dict(item) for item in payload["members"]),
        )

    @property
    def digest(self) -> str:
        """Mathematics: compute SHA-256 identity over the canonical serialized representation."""
        return canonical_value_digest(self.to_dict())


def compose_observer_receipts(
    composition: ObserverComposition,
    receipts: Sequence[ObserverReceipt],
) -> ObserverAggregateReceipt:
    """Mathematics: aggregate a bijection from declared observer contracts to valid operation receipts."""
    if not isinstance(composition, ObserverComposition):
        raise ObserverOrbitError("composition must be an ObserverComposition")
    if not isinstance(receipts, (tuple, list)):
        raise ObserverOrbitError("receipts must be a finite sequence")
    supplied = {item.observer_id: item for item in receipts if isinstance(item, ObserverReceipt)}
    if len(supplied) != len(receipts):
        raise ObserverOrbitError("receipts must contain valid ObserverReceipt values without duplicate identities")
    expected_ids = {item.observer_id for item in composition.members}
    if set(supplied) != expected_ids:
        raise ObserverOrbitError("receipt set must exactly match the declared observer composition")

    operation_id: str | None = None
    input_digest: str | None = None
    subject_state: tuple[str | None, str | None] | None = None
    scheduler: SchedulerReading | None = None
    member_receipts: list[ObserverMemberReceipt] = []

    for contract in composition.members:
        receipt = supplied[contract.observer_id]
        if not verify_observer_receipt(contract, receipt):
            raise ObserverOrbitError(f"receipt does not verify for observer {contract.observer_id!r}")
        if operation_id is None:
            operation_id = receipt.operation_id
            input_digest = receipt.input_digest
            subject_state = (receipt.subject_state_before_digest, receipt.subject_state_after_digest)
        elif receipt.operation_id != operation_id or receipt.input_digest != input_digest:
            raise ObserverOrbitError("observer receipts do not describe the same operation and input")
        elif (receipt.subject_state_before_digest, receipt.subject_state_after_digest) != subject_state:
            raise ObserverOrbitError("observer receipts do not share one subject state interval")
        if receipt.time_frame is not None and receipt.time_frame.scheduler is not None:
            if scheduler is None:
                scheduler = receipt.time_frame.scheduler
            elif receipt.time_frame.scheduler != scheduler:
                raise ObserverOrbitError("observer scheduler coordinates disagree")
        frame_digest = None if receipt.time_frame is None else canonical_value_digest(receipt.time_frame.to_dict())
        member_receipts.append(ObserverMemberReceipt(
            observer_id=receipt.observer_id,
            contract_digest=contract.digest,
            receipt_digest=receipt.digest,
            projection_digest=receipt.projection_digest,
            projection_json=receipt.projection_json,
            time_frame_digest=frame_digest,
        ))

    first = composition.members[0]
    return ObserverAggregateReceipt(
        composition_digest=composition.digest,
        operation_id=operation_id or "",
        input_digest=input_digest or "",
        subject=first.subject,
        interpretation=first.interpretation,
        context_digest=first.context_digest,
        members=tuple(member_receipts),
    )


def contextual_orbit_context(
    system_identity: SystemIdentity,
    base_ground: VirtualGroundRef,
    computational_ground: RepresentationRef,
    *,
    scheduler_id: str,
    extensions: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Mathematics: construct the canonical product context binding system, Virtual Ground, semantic Ground, and scheduler domain."""
    if not isinstance(system_identity, SystemIdentity):
        raise ObserverOrbitError("system_identity must be a SystemIdentity")
    if not isinstance(base_ground, VirtualGroundRef):
        raise ObserverOrbitError("base_ground must be a VirtualGroundRef")
    if not isinstance(computational_ground, RepresentationRef):
        raise ObserverOrbitError("computational_ground must be a RepresentationRef")
    _identifier(scheduler_id, "scheduler_id")
    raw_extensions = {} if extensions is None else extensions
    if not isinstance(raw_extensions, Mapping):
        raise ObserverOrbitError("context extensions must be an object")
    detached_extensions = _clone_json(dict(raw_extensions), "context extensions")
    return {
        "schema": "mailcpu.contextual-orbit-context.v1",
        "system_identity": system_identity.snapshot(),
        "base_ground": base_ground.to_dict(),
        "computational_ground": computational_ground.to_dict(),
        "scheduler_id": scheduler_id,
        "extensions": detached_extensions,
    }


@dataclass(frozen=True)
class ContextualOrbitAddress:
    """Absolute typed scheduler location under a pinned base Virtual Ground.

    The pinned structural-memory coordinate is the relative orbit offset:
        offset = target_scheduler_tick - base_ground.coordinate.

    The scheduler identity is bound into the immutable memory context because
    VirtualGroundRef v1 stores a numeric coordinate but no scheduler identifier.
    """

    system_identity: SystemIdentity
    base_ground: VirtualGroundRef
    computational_ground: RepresentationRef
    coordinate: SchedulerReading
    structural_memory: VirtualStructuralMemoryRef
    context_extensions: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.system_identity, SystemIdentity):
            raise ObserverOrbitError("address system_identity must be a SystemIdentity")
        if not isinstance(self.base_ground, VirtualGroundRef):
            raise ObserverOrbitError("address base_ground must be a VirtualGroundRef")
        if not isinstance(self.computational_ground, RepresentationRef):
            raise ObserverOrbitError("address computational_ground must be a RepresentationRef")
        if not isinstance(self.coordinate, SchedulerReading):
            raise ObserverOrbitError("address coordinate must be a SchedulerReading")
        if not isinstance(self.structural_memory, VirtualStructuralMemoryRef):
            raise ObserverOrbitError("address structural_memory must be a VirtualStructuralMemoryRef")
        if self.coordinate.tick < self.base_ground.coordinate:
            raise ObserverOrbitError("target scheduler coordinate precedes the base Virtual Ground")
        offset = self.coordinate.tick - self.base_ground.coordinate
        if self.structural_memory.coordinate != offset:
            raise ObserverOrbitError("structural-memory coordinate must equal the base-relative orbit offset")
        if not isinstance(self.context_extensions, Mapping):
            raise ObserverOrbitError("context_extensions must be an object")
        extensions = _clone_json(dict(self.context_extensions), "context_extensions")
        expected_context = contextual_orbit_context(
            self.system_identity,
            self.base_ground,
            self.computational_ground,
            scheduler_id=self.coordinate.scheduler_id,
            extensions=extensions,
        )
        actual_context = _thaw_json(self.structural_memory.context)
        if actual_context != expected_context:
            raise ObserverOrbitError("structural-memory context is not bound to this system, ground, interpretation, and scheduler")
        object.__setattr__(self, "context_extensions", _freeze_json(extensions))

    @property
    def orbit_offset(self) -> int:
        """Mathematics: compute the target scheduler tick relative to the pinned base Virtual Ground coordinate."""
        return self.coordinate.tick - self.base_ground.coordinate

    @property
    def context_digest(self) -> str:
        """Mathematics: compute content identity for the exact immutable orbit context."""
        return canonical_value_digest(_thaw_json(self.structural_memory.context))

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize the validated value into its versioned JSON representation."""
        return {
            "schema": "mailcpu.contextual-orbit-address.v1",
            "system_identity": self.system_identity.snapshot(),
            "base_ground": self.base_ground.to_dict(),
            "computational_ground": self.computational_ground.to_dict(),
            "coordinate": self.coordinate.to_dict(),
            "structural_memory": self.structural_memory.to_dict(),
            "context_extensions": _thaw_json(self.context_extensions),
            "orbit_offset": self.orbit_offset,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ContextualOrbitAddress":
        """Mathematics: reconstruct the value from its exact versioned JSON representation and revalidate its invariants."""
        expected = {
            "schema", "system_identity", "base_ground", "computational_ground",
            "coordinate", "structural_memory", "context_extensions", "orbit_offset",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ObserverOrbitError("contextual orbit address fields are invalid")
        if payload["schema"] != "mailcpu.contextual-orbit-address.v1":
            raise ObserverOrbitError("unsupported contextual orbit address schema")
        coordinate_payload = payload["coordinate"]
        if not isinstance(coordinate_payload, Mapping) or set(coordinate_payload) != {"scheduler_id", "tick"}:
            raise ObserverOrbitError("scheduler coordinate fields are invalid")
        address = cls(
            system_identity=SystemIdentity.from_snapshot(payload["system_identity"]),
            base_ground=VirtualGroundRef.from_dict(payload["base_ground"]),
            computational_ground=RepresentationRef.from_dict(payload["computational_ground"]),
            coordinate=SchedulerReading(coordinate_payload["scheduler_id"], coordinate_payload["tick"]),
            structural_memory=VirtualStructuralMemoryRef.from_dict(payload["structural_memory"]),
            context_extensions=payload["context_extensions"],
        )
        if payload["orbit_offset"] != address.orbit_offset:
            raise ObserverOrbitError("stored orbit_offset does not match address coordinates")
        return address

    @property
    def digest(self) -> str:
        """Mathematics: compute SHA-256 identity over the canonical serialized representation."""
        return canonical_value_digest(self.to_dict())


@dataclass(frozen=True)
class VirtualGroundProjection:
    """One symbolic state projection anchored to a full system Virtual Ground.

    This is not a complete machine state or SystemSeed. It denotes one value
    produced by one certified structural generator at one relative coordinate.
    """

    system_identity: SystemIdentity
    base_ground: VirtualGroundRef
    computational_ground: RepresentationRef
    transition: RepresentationRef
    coordinate: SchedulerReading
    orbit_offset: int
    structural_memory: VirtualStructuralMemoryRef
    value: int
    value_digest: str
    read_receipt: StructuralMemoryReadReceipt

    def __post_init__(self) -> None:
        if not isinstance(self.system_identity, SystemIdentity):
            raise ObserverOrbitError("projection system_identity is invalid")
        if not isinstance(self.base_ground, VirtualGroundRef):
            raise ObserverOrbitError("projection base_ground is invalid")
        if not isinstance(self.computational_ground, RepresentationRef):
            raise ObserverOrbitError("projection computational_ground is invalid")
        if not isinstance(self.transition, RepresentationRef):
            raise ObserverOrbitError("projection transition must be a RepresentationRef")
        if not isinstance(self.coordinate, SchedulerReading):
            raise ObserverOrbitError("projection coordinate must be a SchedulerReading")
        _positive_int(self.orbit_offset, "orbit_offset", minimum=0)
        if self.coordinate.tick != self.base_ground.coordinate + self.orbit_offset:
            raise ObserverOrbitError("projection coordinate and base-relative offset disagree")
        if self.structural_memory.coordinate != self.orbit_offset:
            raise ObserverOrbitError("projection structural-memory coordinate is not the orbit offset")
        if type(self.value) is not int:
            raise ObserverOrbitError("projection value must be a strict integer")
        _digest(self.value_digest, "value_digest")
        if canonical_value_digest({"type": "integer", "value": self.value}) != self.value_digest:
            raise ObserverOrbitError("projection value digest does not match Structural Memory integer digest")
        if not isinstance(self.read_receipt, StructuralMemoryReadReceipt):
            raise ObserverOrbitError("projection read_receipt is invalid")
        ref = self.structural_memory
        ref_context = _thaw_json(ref.context)
        if not isinstance(ref_context, Mapping):
            raise ObserverOrbitError("projection Structural Memory context is invalid")
        extensions = ref_context.get("extensions")
        if not isinstance(extensions, Mapping):
            raise ObserverOrbitError("projection context extensions are invalid")
        expected_context = contextual_orbit_context(
            self.system_identity,
            self.base_ground,
            self.computational_ground,
            scheduler_id=self.coordinate.scheduler_id,
            extensions=extensions,
        )
        if ref_context != expected_context:
            raise ObserverOrbitError("projection Structural Memory context is not bound to its system, grounds, and scheduler")
        receipt = self.read_receipt
        if self.transition.content_digest != ref.spec_digest:
            raise ObserverOrbitError("projection transition does not identify the referenced Structural Memory spec")
        if (
            receipt.memory_id != ref.memory_id
            or receipt.revision != ref.revision
            or receipt.spec_digest != ref.spec_digest
            or receipt.certificate_digest != ref.certificate_digest
            or receipt.coordinate != ref.coordinate
            or receipt.context_digest != canonical_value_digest(_thaw_json(ref.context))
            or receipt.value != self.value
            or receipt.value_digest != self.value_digest
        ):
            raise ObserverOrbitError("Structural Memory read receipt does not verify the projection address")

    def identity_payload(self) -> dict[str, Any]:
        """Mathematics: derive stable projection identity while quotienting out per-read receipt and cache metadata."""
        ref = self.structural_memory
        return {
            "schema": "mailcpu.virtual-ground.projection.v1",
            "scope": "structural-memory-projection-not-full-system-snapshot",
            "system_identity": self.system_identity.snapshot(),
            "base_ground": self.base_ground.to_dict(),
            "computational_ground": self.computational_ground.to_dict(),
            "transition": self.transition.to_dict(),
            "coordinate": self.coordinate.to_dict(),
            "orbit_offset": self.orbit_offset,
            "structural_memory": {
                "binding": ref.binding,
                "memory_id": ref.memory_id,
                "revision": ref.revision,
                "context_digest": canonical_value_digest(_thaw_json(ref.context)),
                "coordinate": ref.coordinate,
                "spec_digest": ref.spec_digest,
                "certificate_digest": ref.certificate_digest,
            },
            "value": self.value,
            "value_digest": self.value_digest,
        }

    @property
    def projection_digest(self) -> str:
        """Mathematics: identify the symbolic projection independently of per-read cache and receipt metadata."""
        return canonical_value_digest(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize the validated value into its versioned JSON representation."""
        return {
            **self.identity_payload(),
            "structural_memory_ref": self.structural_memory.to_dict(),
            "projection_digest": self.projection_digest,
            "read_receipt": self.read_receipt.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "VirtualGroundProjection":
        """Mathematics: reconstruct the value from its exact versioned JSON representation and revalidate its invariants."""
        if not isinstance(payload, Mapping):
            raise ObserverOrbitError("Virtual Ground projection must be an object")
        coordinate_payload = payload.get("coordinate")
        if not isinstance(coordinate_payload, Mapping) or set(coordinate_payload) != {"scheduler_id", "tick"}:
            raise ObserverOrbitError("projection scheduler coordinate fields are invalid")
        projection = cls(
            system_identity=SystemIdentity.from_snapshot(payload.get("system_identity")),
            base_ground=VirtualGroundRef.from_dict(payload.get("base_ground")),
            computational_ground=RepresentationRef.from_dict(payload.get("computational_ground")),
            transition=RepresentationRef.from_dict(payload.get("transition")),
            coordinate=SchedulerReading(coordinate_payload["scheduler_id"], coordinate_payload["tick"]),
            orbit_offset=payload.get("orbit_offset"),
            structural_memory=VirtualStructuralMemoryRef.from_dict(payload.get("structural_memory_ref")),
            value=payload.get("value"),
            value_digest=payload.get("value_digest"),
            read_receipt=StructuralMemoryReadReceipt.from_dict(payload.get("read_receipt")),
        )
        expected = {
            **projection.identity_payload(),
            "structural_memory_ref": projection.structural_memory.to_dict(),
            "projection_digest": projection.projection_digest,
            "read_receipt": projection.read_receipt.to_dict(),
        }
        if dict(payload) != expected:
            raise ObserverOrbitError("Virtual Ground projection digest or canonical payload does not match")
        if payload.get("scope") != "structural-memory-projection-not-full-system-snapshot":
            raise ObserverOrbitError("unsupported Virtual Ground projection scope")
        return projection


@dataclass(frozen=True)
class OrbitNavigationResult:
    """Direct symbolic location result; no intermediate states are expanded."""

    projection: VirtualGroundProjection
    observation: ObserverReceipt
    generator_family: str
    complexity_bound: str
    expanded_states: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.projection, VirtualGroundProjection):
            raise ObserverOrbitError("orbit result projection is invalid")
        if not isinstance(self.observation, ObserverReceipt):
            raise ObserverOrbitError("orbit result observation is invalid")
        _identifier(self.generator_family, "generator_family")
        if self.complexity_bound != _COMPLEXITY.get(self.generator_family):
            raise ObserverOrbitError("complexity bound does not match the admitted generator family")
        if type(self.expanded_states) is not int or self.expanded_states != 0:
            raise ObserverOrbitError("symbolic orbit navigation must not expand intermediate states")

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize the validated value into its versioned JSON representation."""
        return {
            "schema": "mailcpu.orbit-navigation-result.v1",
            "projection": self.projection.to_dict(),
            "observation": self.observation.to_dict(),
            "generator_family": self.generator_family,
            "complexity_bound": self.complexity_bound,
            "expanded_states": self.expanded_states,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "OrbitNavigationResult":
        """Mathematics: reconstruct the value from its exact versioned JSON representation and revalidate its invariants."""
        expected = {
            "schema", "projection", "observation", "generator_family",
            "complexity_bound", "expanded_states",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ObserverOrbitError("orbit navigation result fields are invalid")
        if payload["schema"] != "mailcpu.orbit-navigation-result.v1":
            raise ObserverOrbitError("unsupported orbit navigation result schema")
        return cls(
            projection=VirtualGroundProjection.from_dict(payload["projection"]),
            observation=ObserverReceipt.from_dict(payload["observation"]),
            generator_family=payload["generator_family"],
            complexity_bound=payload["complexity_bound"],
            expanded_states=payload["expanded_states"],
        )


@dataclass(frozen=True)
class OrbitValueResult:
    """First mathematically located coordinate for one requested generator value."""

    target_value: int
    orbit_coordinate: int
    inverse_complexity_bound: str
    navigation: OrbitNavigationResult
    expanded_states: int = 0

    def __post_init__(self) -> None:
        if type(self.target_value) is not int:
            raise ObserverOrbitError("target_value must be a strict integer")
        _positive_int(self.orbit_coordinate, "orbit_coordinate", minimum=0)
        if not isinstance(self.navigation, OrbitNavigationResult):
            raise ObserverOrbitError("inverse result navigation payload is invalid")
        if self.navigation.projection.orbit_offset != self.orbit_coordinate:
            raise ObserverOrbitError("inverse coordinate differs from the located projection")
        if self.navigation.projection.value != self.target_value:
            raise ObserverOrbitError("located projection does not match the requested target value")
        expected_inverse_bound = {
            "int": "O(1)",
            "lcg": "O(log m)",
            "gf2": "O(L)",
            "fgraph": "O(1) after O(N) index compilation",
        }.get(self.navigation.generator_family)
        if self.inverse_complexity_bound != expected_inverse_bound:
            raise ObserverOrbitError("inverse complexity bound does not match the supported generator family")
        if type(self.expanded_states) is not int or self.expanded_states != 0:
            raise ObserverOrbitError("inverse navigation must not expand intermediate states")

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize the validated value into its versioned JSON representation."""
        return {
            "schema": "mailcpu.orbit-value-result.v1",
            "target_value": self.target_value,
            "orbit_coordinate": self.orbit_coordinate,
            "inverse_complexity_bound": self.inverse_complexity_bound,
            "navigation": self.navigation.to_dict(),
            "expanded_states": self.expanded_states,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "OrbitValueResult":
        """Mathematics: reconstruct the value from its exact versioned JSON representation and revalidate its invariants."""
        expected = {
            "schema", "target_value", "orbit_coordinate",
            "inverse_complexity_bound", "navigation", "expanded_states",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ObserverOrbitError("orbit value result fields are invalid")
        if payload["schema"] != "mailcpu.orbit-value-result.v1":
            raise ObserverOrbitError("unsupported orbit value result schema")
        return cls(
            target_value=payload["target_value"],
            orbit_coordinate=payload["orbit_coordinate"],
            inverse_complexity_bound=payload["inverse_complexity_bound"],
            navigation=OrbitNavigationResult.from_dict(payload["navigation"]),
            expanded_states=payload["expanded_states"],
        )


class ContextualOrbitNavigator:
    """Resolve a ContextualOrbitAddress through admitted Structural Memory only.

    The registry's guarded generator is the navigation engine. A failed
    identity, context, or evidence check is a refusal, not an invitation to
    silently enumerate the trajectory through another subsystem.
    """

    def __init__(self, registry: StructuralMemoryRegistry) -> None:
        """Mathematics: bind the navigator to one receiver-local Structural Memory registry and its reusable inverse indexes."""
        if not isinstance(registry, StructuralMemoryRegistry):
            raise ObserverOrbitError("ContextualOrbitNavigator requires a StructuralMemoryRegistry")
        self.registry = registry
        self._fgraph_inverse_indexes: dict[str, FiniteGraphInverseIndex] = {}

    def _find_fgraph_coordinate(self, spec_digest: str, orbit: Sequence[int], target: int) -> int | None:
        """Mathematics: compile each pinned finite orbit once per navigator, then answer later lookups in expected O(1)."""
        index = self._fgraph_inverse_indexes.get(spec_digest)
        if index is None:
            index = FiniteGraphInverseIndex(orbit)
            self._fgraph_inverse_indexes[spec_digest] = index
        return index.find(target)

    def _version_for_address(self, address: ContextualOrbitAddress):
        """Mathematics: resolve the exact admitted memory revision and recheck its spec and certificate digests."""
        memory_ref = address.structural_memory
        try:
            version = self.registry.version_for_revision(memory_ref.memory_id, memory_ref.revision)
        except StructuralMemoryError as exc:
            raise ObserverOrbitError("referenced Structural Memory revision is not admitted") from exc
        if (
            version.spec.digest != memory_ref.spec_digest
            or version.certificate.digest != memory_ref.certificate_digest
        ):
            raise ObserverOrbitError("Structural Memory version or certificate identity does not match the address")
        return version

    def locate(
        self,
        address: ContextualOrbitAddress,
        observer: ObserverContract,
        *,
        operation_id: str = "mailcpu.orbit.locate",
        time_frame: TemporalFrame | None = None,
        expected_value: int | None = None,
    ) -> OrbitNavigationResult:
        """Mathematics: evaluate one certified generator at the addressed relative coordinate without expanding intermediate states."""
        if not isinstance(address, ContextualOrbitAddress):
            raise ObserverOrbitError("locate requires a ContextualOrbitAddress")
        if not isinstance(observer, ObserverContract):
            raise ObserverOrbitError("locate requires an ObserverContract")
        _identifier(operation_id, "operation_id")
        if observer.context_digest != address.context_digest:
            raise ObserverOrbitError("observer context does not match the contextual orbit address")

        memory_ref = address.structural_memory
        version = self._version_for_address(address)

        transition = structural_memory_spec_representation_ref(version.spec)
        if observer.subject != transition:
            raise ObserverOrbitError("observer subject does not identify the pinned Structural Memory law")
        if observer.interpretation != address.computational_ground:
            raise ObserverOrbitError("observer interpretation does not match the Computational Ground")

        if time_frame is None:
            frame = TemporalFrame(
                actor_id=observer.observer_id,
                scheduler=address.coordinate,
            )
        else:
            if not isinstance(time_frame, TemporalFrame):
                raise ObserverOrbitError("time_frame must be a TemporalFrame")
            if time_frame.actor_id != observer.observer_id:
                raise ObserverOrbitError("time_frame belongs to another observer")
            if time_frame.scheduler != address.coordinate:
                raise ObserverOrbitError("time_frame scheduler coordinate does not match the address")
            frame = time_frame

        try:
            read_receipt = self.registry.read_revision(
                memory_ref.memory_id,
                memory_ref.revision,
                memory_ref.coordinate,
                context=_thaw_json(memory_ref.context),
            )
        except StructuralMemoryError as exc:
            raise ObserverOrbitError("guarded Structural Memory navigation refused the requested coordinate") from exc

        if expected_value is not None:
            if type(expected_value) is not int:
                raise ObserverOrbitError("expected_value must be a strict integer")
            if read_receipt.value != expected_value:
                raise ObserverOrbitError("Structural Memory value differs from the expected value")

        projection = VirtualGroundProjection(
            system_identity=address.system_identity,
            base_ground=address.base_ground,
            computational_ground=address.computational_ground,
            transition=transition,
            coordinate=address.coordinate,
            orbit_offset=address.orbit_offset,
            structural_memory=memory_ref,
            value=read_receipt.value,
            value_digest=read_receipt.value_digest,
            read_receipt=read_receipt,
        )
        projection_ref = RepresentationRef.from_payload(
            "mailcpu.virtual-ground.projection",
            1,
            projection.identity_payload(),
        )
        read_ref = RepresentationRef.from_payload(
            "mailcpu.structural-memory.read-receipt",
            1,
            read_receipt.to_dict(),
        )
        observation_value = {
            "schema": "mailcpu.orbit.observation.v1",
            "coordinate": address.coordinate.to_dict(),
            "orbit_offset": address.orbit_offset,
            "value": read_receipt.value,
            "value_digest": read_receipt.value_digest,
            "virtual_ground_projection_digest": projection.projection_digest,
        }
        observer_receipt = ObserverReceipt.issue(
            observer,
            operation_id=operation_id,
            input_digest=address.digest,
            projection_value=observation_value,
            time_frame=frame,
            evidence=(read_ref, projection_ref),
        )
        family = version.spec.family
        complexity = _COMPLEXITY.get(family)
        if complexity is None:
            raise ObserverOrbitError(f"generator family {family!r} has no declared direct-navigation complexity")
        return OrbitNavigationResult(
            projection=projection,
            observation=observer_receipt,
            generator_family=family,
            complexity_bound=complexity,
            expanded_states=0,
        )

    def locate_value(
        self,
        base_address: ContextualOrbitAddress,
        observer: ObserverContract,
        target_value: int,
        *,
        operation_id: str = "mailcpu.orbit.locate-value",
        time_frame: TemporalFrame | None = None,
    ) -> OrbitValueResult:
        """Mathematics: invert supported generator dynamics and observe the first matching coordinate.

        The supplied address must be pinned at its base coordinate (offset zero).
        This operation intentionally supports only inverse methods with explicit
        direct algebraic bounds:
          * int: exact modular/non-modular progression inverse, O(1);
          * lcg: full-period power-of-two bit lifting, O(log m).

        It never invokes the general BSGS fallback. GF(2) inversion is bounded by
        the recurrence register order. Finite-graph inversion compiles a reusable
        hash index from the stored preperiod/cycle values, then performs O(1)
        expected lookup; no transition steps are executed during index creation.
        """
        if not isinstance(base_address, ContextualOrbitAddress):
            raise ObserverOrbitError("locate_value requires a base ContextualOrbitAddress")
        if not isinstance(observer, ObserverContract):
            raise ObserverOrbitError("locate_value requires an ObserverContract")
        if type(target_value) is not int:
            raise ObserverOrbitError("target_value must be a strict integer")
        _identifier(operation_id, "operation_id")
        if base_address.orbit_offset != 0:
            raise ObserverOrbitError("value inversion requires an address pinned at the base coordinate")
        if observer.context_digest != base_address.context_digest:
            raise ObserverOrbitError("observer context does not match the contextual orbit address")

        version = self._version_for_address(base_address)
        transition = structural_memory_spec_representation_ref(version.spec)
        if observer.subject != transition:
            raise ObserverOrbitError("observer subject does not identify the pinned Structural Memory law")
        if observer.interpretation != base_address.computational_ground:
            raise ObserverOrbitError("observer interpretation does not match the Computational Ground")

        params = version.spec.parameters
        family = version.spec.family
        if family == "int":
            step = params["step"]
            modulus = params.get("mod")
            origin = params["x0"]
            if not modulus:
                if step == 0:
                    candidate = 0 if target_value == origin else None
                else:
                    difference = target_value - origin
                    quotient, remainder = divmod(difference, step)
                    candidate = quotient if remainder == 0 and quotient >= 0 else None
            elif target_value < 0 or target_value >= modulus:
                candidate = None
            elif step % modulus == 0:
                candidate = 0 if target_value == origin % modulus else None
            else:
                candidate = find_coordinate_int(step, modulus, origin, target_value)
            inverse_complexity = "O(1)"
        elif family == "lcg":
            multiplier = params["a"]
            increment = params["c"]
            modulus = params["mod"]
            origin = params["x0"]
            is_power_of_two = modulus >= 8 and (modulus & (modulus - 1)) == 0
            is_full_period_2adic = (
                is_power_of_two
                and multiplier % 4 == 1
                and increment % 2 == 1
            )
            if not is_full_period_2adic:
                raise ObserverOrbitError(
                    "LCG inverse is unsupported without the full-period power-of-two 2-adic conditions; BSGS fallback is disabled"
                )
            if target_value < 0 or target_value >= modulus:
                candidate = None
            else:
                candidate = find_coordinate_lcg_adic(
                    multiplier,
                    increment,
                    modulus,
                    origin,
                    target_value,
                )
            inverse_complexity = "O(log m)"
        elif family == "gf2":
            candidate = find_coordinate_gf2_bit(
                params["C"],
                params["init"],
                target_value,
            )
            inverse_complexity = "O(L)"
        elif family == "fgraph":
            candidate = self._find_fgraph_coordinate(
                version.spec.digest,
                params["orbit"],
                target_value,
            )
            inverse_complexity = "O(1) after O(N) index compilation"
        else:
            raise ObserverOrbitError(
                f"direct inverse navigation is not yet admitted for {family!r}; no scan or BSGS fallback is permitted"
            )

        if candidate is None:
            raise ObserverOrbitError("target value is not reachable under the admitted direct inverse")
        law = Law(
            family=version.spec.family,
            params=params,
            order=version.spec.order,
            verdict=version.spec.law_verdict,
            first_bad=version.spec.first_bad,
        )
        try:
            verified_value = navigate_guarded(law, candidate)
        except (HorizonExceeded, Refused) as exc:
            raise ObserverOrbitError("inverse coordinate lies outside the certified Structural Memory horizon") from exc
        if verified_value != target_value:
            raise ObserverOrbitError("inverse candidate failed exact forward verification")

        resolved_ref = replace(base_address.structural_memory, coordinate=candidate)
        resolved_address = replace(
            base_address,
            coordinate=SchedulerReading(
                base_address.coordinate.scheduler_id,
                base_address.base_ground.coordinate + candidate,
            ),
            structural_memory=resolved_ref,
        )
        navigation = self.locate(
            resolved_address,
            observer,
            operation_id=operation_id,
            time_frame=time_frame,
            expected_value=target_value,
        )
        return OrbitValueResult(
            target_value=target_value,
            orbit_coordinate=candidate,
            inverse_complexity_bound=inverse_complexity,
            navigation=navigation,
            expanded_states=0,
        )

