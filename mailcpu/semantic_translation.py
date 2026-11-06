"""Declarative contracts for meaning-preserving representation translations.

This module describes translation boundaries; it does not execute translators,
grant capabilities, or prove a universal equivalence law. A paired observation
check establishes equality only for the exact case whose inputs and projected
observations are supplied.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import math
import re
from typing import Any, Mapping

from .model import Program
from .structural_memory import StructuralMemorySpec


_SCHEMA = "mailcpu.semantic-translation-contract.v1"
_CHECK_SCHEMA = "mailcpu.semantic-translation-check.v1"
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}\Z")
_RESOURCE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
_RIGHT = re.compile(r"[A-Za-z][A-Za-z0-9._-]{0,63}\Z")
_RESOURCE = re.compile(r"/?[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}\Z")


class SemanticTranslationError(ValueError):
    """A semantic translation descriptor or paired observation is malformed."""


class EffectClass(str, Enum):
    """Effect boundary declared by a translation contract."""

    PURE = "pure"
    JOURNALED = "journaled"
    EXTERNAL = "external"


class ReplayClass(str, Enum):
    """Replay guarantee required by a translation's effect boundary."""

    DETERMINISTIC = "deterministic"
    SEMANTIC_LEDGER = "semantic-ledger"
    NON_REPLAYABLE = "non-replayable"


def _identifier(value: Any, name: str) -> str:
    """Mathematics: require an identifier from the finite safe alphabet A, where 1 ≤ |s| ≤ 128."""
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise SemanticTranslationError(f"{name} must be a safe non-empty identifier")
    return value


def _digest(value: Any, name: str) -> str:
    """Mathematics: require a canonical SHA-256 identity in the domain {0,…,9,a,…,f}^64."""
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise SemanticTranslationError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _positive_int(value: Any, name: str, *, allow_zero: bool = False) -> int:
    """Mathematics: accept x ∈ Z with x ≥ 1, or x ≥ 0 when allow_zero is true; exclude Booleans."""
    minimum = 0 if allow_zero else 1
    if type(value) is not int or value < minimum:
        relation = "non-negative" if allow_zero else "positive"
        raise SemanticTranslationError(f"{name} must be a {relation} integer")
    return value


def _json_value(value: Any, path: str = "value") -> Any:
    """Mathematics: recursively project finite JSON values into the scalar, mapping, and ordered-sequence algebra."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise SemanticTranslationError(f"{path} contains a non-finite number")
        return value
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise SemanticTranslationError(f"{path} mapping keys must be strings")
            result[key] = _json_value(item, f"{path}.{key}")
        return result
    if isinstance(value, (tuple, list)):
        return [_json_value(item, f"{path}[{index}]") for index, item in enumerate(value)]
    raise SemanticTranslationError(f"{path} contains unsupported type {type(value).__name__}")


def _canonical_bytes(value: Any) -> bytes:
    """Mathematics: encode one JSON value as UTF-8 sorted-key compact JSON with non-finite numbers excluded."""
    try:
        normalized = _json_value(value)
        return json.dumps(
            normalized,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        if isinstance(exc, SemanticTranslationError):
            raise
        raise SemanticTranslationError(f"value is not canonical JSON: {exc}") from exc


def canonical_value_digest(value: Any) -> str:
    """Mathematics: define H(x) = SHA256(canonical_json(x)) for a finite JSON-compatible value."""
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


@dataclass(frozen=True)
class RepresentationRef:
    """Content-addressed identity of one source or target representation."""

    type_id: str
    schema_version: int
    content_digest: str

    def __post_init__(self) -> None:
        """Mathematics: require a typed representation identity (type_id, schema_version, SHA256(payload))."""
        _identifier(self.type_id, "representation type_id")
        _positive_int(self.schema_version, "representation schema_version")
        _digest(self.content_digest, "representation content_digest")

    @classmethod
    def from_payload(
        cls,
        type_id: str,
        schema_version: int,
        payload: Any,
    ) -> "RepresentationRef":
        """Mathematics: construct R=(type,version,H(payload)) without retaining caller-owned payload data."""
        return cls(type_id, schema_version, canonical_value_digest(payload))

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize the complete immutable identity tuple R."""
        return {
            "type_id": self.type_id,
            "schema_version": self.schema_version,
            "content_digest": self.content_digest,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RepresentationRef":
        """Mathematics: reconstruct R only from the exact declared field set."""
        expected = {"type_id", "schema_version", "content_digest"}
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise SemanticTranslationError("representation reference fields are invalid")
        return cls(
            payload["type_id"],
            payload["schema_version"],
            payload["content_digest"],
        )


@dataclass(frozen=True)
class ObservationContract:
    """Versioned definition of the projection whose meaning must survive translation."""

    projection_id: str
    schema_version: int
    projection_digest: str
    comparison: str = "canonical-json-exact"

    def __post_init__(self) -> None:
        """Mathematics: bind one named projection to its schema and definition digest; v1 admits exact canonical equality only."""
        _identifier(self.projection_id, "observation projection_id")
        _positive_int(self.schema_version, "observation schema_version")
        _digest(self.projection_digest, "observation projection_digest")
        if self.comparison != "canonical-json-exact":
            raise SemanticTranslationError("only canonical-json-exact observation comparison is supported")

    @classmethod
    def from_definition(
        cls,
        projection_id: str,
        schema_version: int,
        definition: Any,
    ) -> "ObservationContract":
        """Mathematics: bind a stable projection name and schema to H(definition)."""
        return cls(
            projection_id,
            schema_version,
            canonical_value_digest(definition),
        )

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize the projection identity and exact comparison relation."""
        return {
            "projection_id": self.projection_id,
            "schema_version": self.schema_version,
            "projection_digest": self.projection_digest,
            "comparison": self.comparison,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ObservationContract":
        """Mathematics: reconstruct one observation contract from its exact typed projection."""
        expected = {"projection_id", "schema_version", "projection_digest", "comparison"}
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise SemanticTranslationError("observation contract fields are invalid")
        return cls(
            payload["projection_id"],
            payload["schema_version"],
            payload["projection_digest"],
            payload["comparison"],
        )


@dataclass(frozen=True)
class ResourceBound:
    """One named integer resource ceiling with an explicit unit."""

    name: str
    maximum: int
    unit: str

    def __post_init__(self) -> None:
        """Mathematics: require a unique resource name, non-negative ceiling, and stable unit label."""
        if not isinstance(self.name, str) or _RESOURCE_NAME.fullmatch(self.name) is None:
            raise SemanticTranslationError("resource bound name is invalid")
        _positive_int(self.maximum, "resource bound maximum", allow_zero=True)
        if not isinstance(self.unit, str) or _IDENTIFIER.fullmatch(self.unit) is None:
            raise SemanticTranslationError("resource bound unit must be a safe identifier")

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize one resource ceiling as (name, maximum, unit)."""
        return {"name": self.name, "maximum": self.maximum, "unit": self.unit}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ResourceBound":
        """Mathematics: reconstruct one resource ceiling from exactly three fields."""
        if not isinstance(payload, Mapping) or set(payload) != {"name", "maximum", "unit"}:
            raise SemanticTranslationError("resource bound fields are invalid")
        return cls(payload["name"], payload["maximum"], payload["unit"])


@dataclass(frozen=True)
class CapabilityRequirement:
    """A declared receiver-side capability requirement; it is not a capability grant."""

    resource: str
    rights: tuple[str, ...]

    def __post_init__(self) -> None:
        """Mathematics: require a non-empty resource and finite, unique right names; no authority is created by this declaration."""
        if not isinstance(self.resource, str) or _RESOURCE.fullmatch(self.resource) is None:
            raise SemanticTranslationError("capability resource must be a safe resource identifier")
        if not isinstance(self.rights, (tuple, list)):
            raise SemanticTranslationError("capability rights must be an array")
        rights = tuple(self.rights)
        if not rights or any(not isinstance(right, str) or _RIGHT.fullmatch(right) is None for right in rights):
            raise SemanticTranslationError("capability rights must be non-empty safe identifiers")
        if len(set(rights)) != len(rights):
            raise SemanticTranslationError("capability rights must be unique")
        object.__setattr__(self, "rights", tuple(sorted(rights)))

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize one capability requirement as a resource and sorted rights set."""
        return {"resource": self.resource, "rights": list(self.rights)}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CapabilityRequirement":
        """Mathematics: reconstruct the declarative resource/right pair without issuing it."""
        if not isinstance(payload, Mapping) or set(payload) != {"resource", "rights"}:
            raise SemanticTranslationError("capability requirement fields are invalid")
        if not isinstance(payload["rights"], (list, tuple)):
            raise SemanticTranslationError("capability rights must be an array")
        return cls(payload["resource"], tuple(payload["rights"]))


@dataclass(frozen=True)
class TranslationContract:
    """A non-executable edge declaring what source-to-target translation must preserve."""

    contract_id: str
    revision: int
    source: RepresentationRef
    target: RepresentationRef
    mapping: RepresentationRef
    observation: ObservationContract
    context_digest: str
    precondition_digests: tuple[str, ...] = ()
    invariant_digests: tuple[str, ...] = ()
    resource_bounds: tuple[ResourceBound, ...] = ()
    authority_requirements: tuple[CapabilityRequirement, ...] = ()
    effect_class: EffectClass = EffectClass.PURE
    replay_class: ReplayClass = ReplayClass.DETERMINISTIC

    def __post_init__(self) -> None:
        """Mathematics: bind one immutable translation edge to source, target, observation, context, proof obligations, budgets, and operational boundaries."""
        _identifier(self.contract_id, "contract_id")
        _positive_int(self.revision, "contract revision")
        if not isinstance(self.source, RepresentationRef) or not isinstance(self.target, RepresentationRef):
            raise SemanticTranslationError("source and target must be RepresentationRef values")
        if not isinstance(self.mapping, RepresentationRef):
            raise SemanticTranslationError("mapping must be a RepresentationRef")
        if not isinstance(self.observation, ObservationContract):
            raise SemanticTranslationError("observation must be an ObservationContract")
        _digest(self.context_digest, "context_digest")
        if not isinstance(self.effect_class, EffectClass):
            raise SemanticTranslationError("effect_class must be an EffectClass")
        if not isinstance(self.replay_class, ReplayClass):
            raise SemanticTranslationError("replay_class must be a ReplayClass")
        if self.effect_class is EffectClass.PURE and self.replay_class is not ReplayClass.DETERMINISTIC:
            raise SemanticTranslationError("pure translations must declare deterministic replay")
        if self.effect_class is EffectClass.EXTERNAL and self.replay_class is ReplayClass.DETERMINISTIC:
            raise SemanticTranslationError("external effects cannot claim deterministic replay without a semantic ledger")

        preconditions = tuple(_digest(item, "precondition digest") for item in self.precondition_digests)
        invariants = tuple(_digest(item, "invariant digest") for item in self.invariant_digests)
        if len(set(preconditions)) != len(preconditions):
            raise SemanticTranslationError("precondition digests must be unique")
        if len(set(invariants)) != len(invariants):
            raise SemanticTranslationError("invariant digests must be unique")
        object.__setattr__(self, "precondition_digests", tuple(sorted(preconditions)))
        object.__setattr__(self, "invariant_digests", tuple(sorted(invariants)))

        bounds = tuple(self.resource_bounds)
        if any(not isinstance(item, ResourceBound) for item in bounds):
            raise SemanticTranslationError("resource_bounds must contain ResourceBound values")
        if len({item.name for item in bounds}) != len(bounds):
            raise SemanticTranslationError("resource bound names must be unique")
        object.__setattr__(self, "resource_bounds", tuple(sorted(bounds, key=lambda item: item.name)))

        requirements = tuple(self.authority_requirements)
        if any(not isinstance(item, CapabilityRequirement) for item in requirements):
            raise SemanticTranslationError("authority_requirements must contain CapabilityRequirement values")
        keys = {(item.resource, item.rights) for item in requirements}
        if len(keys) != len(requirements):
            raise SemanticTranslationError("authority requirements must be unique")
        object.__setattr__(
            self,
            "authority_requirements",
            tuple(sorted(requirements, key=lambda item: (item.resource, item.rights))),
        )

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: project the translation edge to its canonical schema-defined JSON representation."""
        return {
            "schema": _SCHEMA,
            "contract_id": self.contract_id,
            "revision": self.revision,
            "source": self.source.to_dict(),
            "target": self.target.to_dict(),
            "mapping": self.mapping.to_dict(),
            "observation": self.observation.to_dict(),
            "context_digest": self.context_digest,
            "precondition_digests": list(self.precondition_digests),
            "invariant_digests": list(self.invariant_digests),
            "resource_bounds": [item.to_dict() for item in self.resource_bounds],
            "authority_requirements": [item.to_dict() for item in self.authority_requirements],
            "effect_class": self.effect_class.value,
            "replay_class": self.replay_class.value,
        }

    @property
    def digest(self) -> str:
        """Mathematics: define the immutable translation-contract identity as H(to_dict(contract))."""
        return canonical_value_digest(self.to_dict())

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "TranslationContract":
        """Mathematics: reconstruct a translation edge only when its schema and complete field set match."""
        expected = {
            "schema",
            "contract_id",
            "revision",
            "source",
            "target",
            "mapping",
            "observation",
            "context_digest",
            "precondition_digests",
            "invariant_digests",
            "resource_bounds",
            "authority_requirements",
            "effect_class",
            "replay_class",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected or payload["schema"] != _SCHEMA:
            raise SemanticTranslationError("translation contract schema or fields are invalid")
        if not isinstance(payload["source"], Mapping) or not isinstance(payload["target"], Mapping):
            raise SemanticTranslationError("translation source and target must be objects")
        if not isinstance(payload["mapping"], Mapping):
            raise SemanticTranslationError("translation mapping must be an object")
        if not isinstance(payload["observation"], Mapping):
            raise SemanticTranslationError("translation observation must be an object")
        for name in ("precondition_digests", "invariant_digests", "resource_bounds", "authority_requirements"):
            if not isinstance(payload[name], (list, tuple)):
                raise SemanticTranslationError(f"{name} must be an array")
        try:
            effect_class = EffectClass(payload["effect_class"])
            replay_class = ReplayClass(payload["replay_class"])
        except (TypeError, ValueError) as exc:
            raise SemanticTranslationError("translation effect or replay class is invalid") from exc
        return cls(
            contract_id=payload["contract_id"],
            revision=payload["revision"],
            source=RepresentationRef.from_dict(payload["source"]),
            target=RepresentationRef.from_dict(payload["target"]),
            mapping=RepresentationRef.from_dict(payload["mapping"]),
            observation=ObservationContract.from_dict(payload["observation"]),
            context_digest=payload["context_digest"],
            precondition_digests=tuple(payload["precondition_digests"]),
            invariant_digests=tuple(payload["invariant_digests"]),
            resource_bounds=tuple(ResourceBound.from_dict(item) for item in payload["resource_bounds"]),
            authority_requirements=tuple(
                CapabilityRequirement.from_dict(item) for item in payload["authority_requirements"]
            ),
            effect_class=effect_class,
            replay_class=replay_class,
        )


@dataclass(frozen=True)
class ObservationComparison:
    """Paired exact comparison for one concrete input case under one translation contract."""

    contract_digest: str
    case_digest: str
    projection_digest: str
    source_observation_digest: str
    target_observation_digest: str
    equivalent: bool

    def __post_init__(self) -> None:
        """Mathematics: bind the comparison verdict to H(contract), H(case), projection identity, and both projected values."""
        for name, value in (
            ("contract_digest", self.contract_digest),
            ("case_digest", self.case_digest),
            ("projection_digest", self.projection_digest),
            ("source_observation_digest", self.source_observation_digest),
            ("target_observation_digest", self.target_observation_digest),
        ):
            _digest(value, name)
        if type(self.equivalent) is not bool:
            raise SemanticTranslationError("equivalent must be a Boolean")
        if self.equivalent != (self.source_observation_digest == self.target_observation_digest):
            raise SemanticTranslationError("equivalent must match the paired observation digests")

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize a paired observation result without promoting it to a universal proof claim."""
        return {
            "schema": _CHECK_SCHEMA,
            "contract_digest": self.contract_digest,
            "case_digest": self.case_digest,
            "projection_digest": self.projection_digest,
            "source_observation_digest": self.source_observation_digest,
            "target_observation_digest": self.target_observation_digest,
            "equivalent": self.equivalent,
        }

    @property
    def digest(self) -> str:
        """Mathematics: define the immutable paired-check identity as H(to_dict(check))."""
        return canonical_value_digest(self.to_dict())

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ObservationComparison":
        """Mathematics: reconstruct an exact paired-check record from its complete schema."""
        expected = {
            "schema",
            "contract_digest",
            "case_digest",
            "projection_digest",
            "source_observation_digest",
            "target_observation_digest",
            "equivalent",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected or payload["schema"] != _CHECK_SCHEMA:
            raise SemanticTranslationError("observation comparison schema or fields are invalid")
        return cls(
            payload["contract_digest"],
            payload["case_digest"],
            payload["projection_digest"],
            payload["source_observation_digest"],
            payload["target_observation_digest"],
            payload["equivalent"],
        )


def compare_projected_observations(
    contract: TranslationContract,
    *,
    case_payload: Any,
    source_observation: Any,
    target_observation: Any,
) -> ObservationComparison:
    """Check exact equality of two caller-projected observations for one concrete input case.

    Mathematics: let C be the translation contract, x the case payload, and
    o_s/o_t the observations already projected under C.observation. The check
    returns equivalent iff canonical_json(o_s) = canonical_json(o_t). It does
    not establish equivalence for inputs other than x or validate that either
    caller applied the declared projection correctly.
    """
    if not isinstance(contract, TranslationContract):
        raise SemanticTranslationError("contract must be a TranslationContract")
    source_bytes = _canonical_bytes(source_observation)
    target_bytes = _canonical_bytes(target_observation)
    return ObservationComparison(
        contract_digest=contract.digest,
        case_digest=canonical_value_digest(case_payload),
        projection_digest=contract.observation.projection_digest,
        source_observation_digest=hashlib.sha256(source_bytes).hexdigest(),
        target_observation_digest=hashlib.sha256(target_bytes).hexdigest(),
        equivalent=source_bytes == target_bytes,
    )


def program_representation_ref(program: Program) -> RepresentationRef:
    """Mathematics: identify a validated MailCPU program by H(ordered opcode/operand sequence)."""
    if not isinstance(program, Program):
        raise SemanticTranslationError("program_representation_ref requires a validated Program")
    payload = {
        "instructions": [
            {"op": instruction.op.value, "args": list(instruction.args)}
            for instruction in program.instructions
        ]
    }
    return RepresentationRef.from_payload("mailcpu.program", 1, payload)


def structural_memory_spec_representation_ref(spec: StructuralMemorySpec) -> RepresentationRef:
    """Mathematics: identify one immutable Structural Memory specification using its canonical schema projection."""
    if not isinstance(spec, StructuralMemorySpec):
        raise SemanticTranslationError(
            "structural_memory_spec_representation_ref requires a StructuralMemorySpec"
        )
    return RepresentationRef.from_payload("mailcpu.structural-memory.spec", 1, spec.to_dict())



_CPU_ORACLE_DEFINITION = {
    "identity": "mailcpu.transit.cpu-reference-oracle",
    "version": 1,
    "execution": "independent transport-free evaluator",
    "initial_register_default": 0,
    "instructions": {
        "SET": "R[d] := immediate",
        "COPY": "R[d] := R[s]",
        "ADD": "R[d] := R[l] + R[r]",
        "COMPARE": "R[d] := sign(R[l] - R[r])",
        "BRANCH": "pc := target when R[c] != 0, else pc + 1",
        "HALT": "terminate with pc unchanged",
    },
    "step_accounting": "one unit per fetched instruction, including HALT",
    "terminal": {"status": "exited", "exit_code": 0},
}
_STRUCTURAL_MEMORY_ORACLE_DEFINITION = {
    "identity": "mailcpu.transit.structural-memory-reference-oracle",
    "version": 1,
    "families": {
        "int": "independent arithmetic progression evaluation",
        "lcg": "binary composition of affine maps",
        "gf2": "bit-packed companion-matrix exponentiation",
        "fgraph": "preperiod/cycle modular indexing",
    },
    "guard": "PREFIX-GROUND requires coordinate < first_bad",
    "source": "pinned immutable StructuralMemorySpec and certificate",
}
_CPU_ORACLE_PROJECTION = {
    "fields": ["status", "exit_code", "pc", "steps", "registers"],
    "registers": "sorted integer map",
}
_STRUCTURAL_MEMORY_ORACLE_PROJECTION = {
    "fields": [
        "memory_id", "revision", "spec_digest", "certificate_digest",
        "coordinate", "context_digest", "value", "value_digest",
        "verification_class", "witness_digest",
    ],
    "comparison": "exact canonical JSON",
}
_CPU_ORACLE_REF = RepresentationRef.from_payload(
    "mailcpu.transit.semantic-oracle.cpu-arithmetic",
    1,
    _CPU_ORACLE_DEFINITION,
)
_STRUCTURAL_MEMORY_ORACLE_REF = RepresentationRef.from_payload(
    "mailcpu.transit.semantic-oracle.structural-memory-coordinate",
    1,
    _STRUCTURAL_MEMORY_ORACLE_DEFINITION,
)
_CPU_ORACLE_PROJECTION_DIGEST = canonical_value_digest(_CPU_ORACLE_PROJECTION)
_STRUCTURAL_MEMORY_ORACLE_PROJECTION_DIGEST = canonical_value_digest(
    _STRUCTURAL_MEMORY_ORACLE_PROJECTION
)
_ORACLE_EVIDENCE_SCHEMA = "mailcpu.transit-oracle-evidence.v1"


def _transit_oracle_effect_projection(
    oracle_type_id: str,
    effect: Mapping[str, Any],
) -> dict[str, Any]:
    """Project only the operation's semantic result, excluding transport and provenance noise. Mathematics: apply the registered projection π to remove transport-specific fields while preserving the operation observation."""
    if not isinstance(effect, Mapping):
        raise SemanticTranslationError("oracle effect must be an object")
    if oracle_type_id == _CPU_ORACLE_REF.type_id:
        fields = ("status", "exit_code", "pc", "steps", "registers")
        if any(field not in effect for field in fields):
            raise SemanticTranslationError("CPU effect is missing an oracle-projected field")
        registers = effect["registers"]
        if not isinstance(registers, Mapping):
            raise SemanticTranslationError("CPU effect registers must be an object")
        normalized_registers: dict[str, int] = {}
        for name, value in registers.items():
            if not isinstance(name, str) or type(value) is not int:
                raise SemanticTranslationError("CPU effect registers must map names to strict integers")
            normalized_registers[name] = value
        if (
            effect["status"] != "exited"
            or type(effect["exit_code"]) is not int
            or type(effect["pc"]) is not int
            or type(effect["steps"]) is not int
        ):
            raise SemanticTranslationError("CPU effect terminal projection is invalid")
        return {
            "status": effect["status"],
            "exit_code": effect["exit_code"],
            "pc": effect["pc"],
            "steps": effect["steps"],
            "registers": dict(sorted(normalized_registers.items())),
        }
    if oracle_type_id == _STRUCTURAL_MEMORY_ORACLE_REF.type_id:
        fields = (
            "memory_id", "revision", "spec_digest", "certificate_digest",
            "coordinate", "context_digest", "value", "value_digest",
            "verification_class", "witness_digest",
        )
        if any(field not in effect for field in fields):
            raise SemanticTranslationError("Structural Memory effect is missing an oracle-projected field")
        projected = {field: effect[field] for field in fields}
        if (
            not isinstance(projected["memory_id"], str)
            or type(projected["revision"]) is not int
            or type(projected["coordinate"]) is not int
            or type(projected["value"]) is not int
            or not isinstance(projected["verification_class"], str)
        ):
            raise SemanticTranslationError("Structural Memory effect projection has invalid scalar types")
        for field in ("spec_digest", "certificate_digest", "context_digest", "value_digest", "witness_digest"):
            _digest(projected[field], f"Structural Memory {field}")
        return projected
    raise SemanticTranslationError(f"unknown Transit semantic oracle {oracle_type_id!r}")


@dataclass(frozen=True)
class TransitOracleEvidence:
    """Bounded independent operation check, with deterministic work recorded as part of its cost."""

    oracle: RepresentationRef
    request_fingerprint: str
    case_digest: str
    projection_digest: str
    expected_observation: Mapping[str, Any]
    observed_observation: Mapping[str, Any]
    work_units: int
    work_limit: int
    equivalent: bool

    def __post_init__(self) -> None:
        if not isinstance(self.oracle, RepresentationRef):
            raise SemanticTranslationError("oracle must be a RepresentationRef")
        if self.oracle == _CPU_ORACLE_REF:
            expected_projection = _CPU_ORACLE_PROJECTION_DIGEST
        elif self.oracle == _STRUCTURAL_MEMORY_ORACLE_REF:
            expected_projection = _STRUCTURAL_MEMORY_ORACLE_PROJECTION_DIGEST
        else:
            raise SemanticTranslationError("Transit semantic oracle identity is not admitted")
        _digest(self.request_fingerprint, "oracle request_fingerprint")
        _digest(self.case_digest, "oracle case_digest")
        _digest(self.projection_digest, "oracle projection_digest")
        if self.projection_digest != expected_projection:
            raise SemanticTranslationError("oracle projection does not match its registered definition")
        expected = _json_value(self.expected_observation, "oracle.expected_observation")
        observed = _json_value(self.observed_observation, "oracle.observed_observation")
        if not isinstance(expected, Mapping) or not isinstance(observed, Mapping):
            raise SemanticTranslationError("oracle observations must be JSON objects")
        object.__setattr__(self, "expected_observation", dict(expected))
        object.__setattr__(self, "observed_observation", dict(observed))
        _positive_int(self.work_units, "oracle work_units")
        _positive_int(self.work_limit, "oracle work_limit")
        if self.work_units > self.work_limit:
            raise SemanticTranslationError("oracle work_units exceed the declared work_limit")
        if type(self.equivalent) is not bool:
            raise SemanticTranslationError("oracle equivalent must be a Boolean")
        equal = canonical_value_digest(expected) == canonical_value_digest(observed)
        if self.equivalent != equal:
            raise SemanticTranslationError("oracle equivalent flag does not match its observations")

    @property
    def expected_digest(self) -> str:
        """Return the canonical digest of the independently derived observation. Mathematics: H_e = SHA256(canonical_json(expected_observation))."""
        return canonical_value_digest(self.expected_observation)

    @property
    def observed_digest(self) -> str:
        """Return the canonical digest of the backend's projected observation. Mathematics: H_o = SHA256(canonical_json(observed_observation))."""
        return canonical_value_digest(self.observed_observation)

    @property
    def digest(self) -> str:
        """Return the stable digest of this complete oracle evidence record. Mathematics: H_evidence = SHA256(canonical_json(to_dict()))."""
        return canonical_value_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        """Serialize the strict schema-defined oracle evidence projection. Mathematics: emit the canonical record fields R under schema v1."""
        return {
            "schema": _ORACLE_EVIDENCE_SCHEMA,
            "oracle": self.oracle.to_dict(),
            "request_fingerprint": self.request_fingerprint,
            "case_digest": self.case_digest,
            "projection_digest": self.projection_digest,
            "expected_observation": _json_value(self.expected_observation),
            "observed_observation": _json_value(self.observed_observation),
            "expected_digest": self.expected_digest,
            "observed_digest": self.observed_digest,
            "work_units": self.work_units,
            "work_limit": self.work_limit,
            "equivalent": self.equivalent,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "TransitOracleEvidence":
        """Reconstruct oracle evidence and revalidate its schema, digests, and cost. Mathematics: accept only R' where schema(R')=v1 and all bound hashes and limits hold."""
        expected_fields = {
            "schema", "oracle", "request_fingerprint", "case_digest",
            "projection_digest", "expected_observation", "observed_observation",
            "expected_digest", "observed_digest", "work_units", "work_limit",
            "equivalent",
        }
        if (
            not isinstance(payload, Mapping)
            or set(payload) != expected_fields
            or payload["schema"] != _ORACLE_EVIDENCE_SCHEMA
        ):
            raise SemanticTranslationError("Transit oracle evidence schema or fields are invalid")
        if not isinstance(payload["oracle"], Mapping):
            raise SemanticTranslationError("Transit oracle reference must be an object")
        record = cls(
            oracle=RepresentationRef.from_dict(payload["oracle"]),
            request_fingerprint=payload["request_fingerprint"],
            case_digest=payload["case_digest"],
            projection_digest=payload["projection_digest"],
            expected_observation=payload["expected_observation"],
            observed_observation=payload["observed_observation"],
            work_units=payload["work_units"],
            work_limit=payload["work_limit"],
            equivalent=payload["equivalent"],
        )
        if (
            payload["expected_digest"] != record.expected_digest
            or payload["observed_digest"] != record.observed_digest
        ):
            raise SemanticTranslationError("Transit oracle observation digest does not match its value")
        return record

    def validate_against_effect(
        self,
        effect: Mapping[str, Any],
        *,
        request_fingerprint: str,
    ) -> None:
        """Recheck the observed projection against the committed raw handler effect. Mathematics: require H(π(effect))=observed_digest and request_fingerprint=F."""
        if request_fingerprint != self.request_fingerprint:
            raise SemanticTranslationError("oracle request fingerprint does not match Transit evidence")
        if not self.equivalent:
            raise SemanticTranslationError("Transit oracle comparison is not equivalent")
        observed = _transit_oracle_effect_projection(self.oracle.type_id, effect)
        if canonical_value_digest(observed) != self.observed_digest:
            raise SemanticTranslationError("Transit oracle observation does not match the committed effect")



_TRANSIT_EVIDENCE_SCHEMA = "mailcpu.transit-translation-evidence.v1"


@dataclass(frozen=True)
class TransitTranslationEvidence:
    """A durable binding from one authorized Transit event to its committed handler effect."""

    request_source: str
    request_channel: str
    request_sequence: int
    operation: str
    resource: str
    domain: str
    required_rights: tuple[str, ...]
    request_fingerprint: str
    decision_receipt: str
    effect_digest: str
    backend_manifest: tuple[tuple[str, str], ...]
    contract: TranslationContract
    comparison: ObservationComparison

    def __post_init__(self) -> None:
        """Mathematics: bind event identity I, operation/resource/domain, required rights, request fingerprint F, decision receipt D, effect H(E), backend relation M, and a successful paired canonicalization check."""
        for name, value in (
            ("request_source", self.request_source),
            ("request_channel", self.request_channel),
            ("operation", self.operation),
            ("resource", self.resource),
            ("domain", self.domain),
        ):
            if not isinstance(value, str) or not value:
                raise SemanticTranslationError(f"{name} must be non-empty text")
        _positive_int(self.request_sequence, "request_sequence")
        _digest(self.request_fingerprint, "request_fingerprint")
        _digest(self.decision_receipt, "decision_receipt")
        _digest(self.effect_digest, "effect_digest")
        rights = tuple(self.required_rights)
        if any(not isinstance(right, str) or _RIGHT.fullmatch(right) is None for right in rights):
            raise SemanticTranslationError("required_rights contains an invalid right")
        if tuple(sorted(set(rights))) != rights:
            raise SemanticTranslationError("required_rights must be sorted and unique")
        object.__setattr__(self, "required_rights", rights)
        if any(not isinstance(item, (tuple, list)) for item in self.backend_manifest):
            raise SemanticTranslationError("backend_manifest entries must be operation/resource pairs")
        manifest = tuple(tuple(item) for item in self.backend_manifest)
        if not manifest or any(
            len(item) != 2
            or any(not isinstance(part, str) or not part for part in item)
            for item in manifest
        ):
            raise SemanticTranslationError("backend_manifest must contain non-empty operation/resource pairs")
        if tuple(sorted(set(manifest))) != manifest:
            raise SemanticTranslationError("backend_manifest must be sorted and unique")
        if (self.operation, self.resource) not in manifest:
            raise SemanticTranslationError("selected operation/resource is absent from the backend manifest")
        object.__setattr__(self, "backend_manifest", manifest)
        if not isinstance(self.contract, TranslationContract):
            raise SemanticTranslationError("contract must be a TranslationContract")
        if not isinstance(self.comparison, ObservationComparison):
            raise SemanticTranslationError("comparison must be an ObservationComparison")
        if self.contract.source.type_id != "mailcpu.transit.authorized-event":
            raise SemanticTranslationError("Transit evidence source type is invalid")
        if self.contract.target.type_id != "mailcpu.transit.handler-effect":
            raise SemanticTranslationError("Transit evidence target type is invalid")
        if self.contract.mapping.type_id != "mailcpu.transit.backend-dispatch":
            raise SemanticTranslationError("Transit evidence mapping type is invalid")
        if self.contract.source.content_digest != self.request_fingerprint:
            raise SemanticTranslationError("Transit evidence request fingerprint does not match its contract source")
        if self.contract.target.content_digest != self.effect_digest:
            raise SemanticTranslationError("Transit evidence effect digest does not match its contract target")

        expected_mapping = RepresentationRef.from_payload(
            "mailcpu.transit.backend-dispatch",
            1,
            {
                "operation": self.operation,
                "resource": self.resource,
                "domain": self.domain,
                "backend_manifest": [list(item) for item in manifest],
                "adapter": "mailcpu.transit-worker.effect-encoder.v1",
            },
        )
        if self.contract.mapping != expected_mapping:
            raise SemanticTranslationError("Transit evidence mapping does not match its selected backend")

        expected_authority = (
            (CapabilityRequirement(self.resource, rights),)
            if rights
            else ()
        )
        if self.contract.authority_requirements != expected_authority:
            raise SemanticTranslationError("Transit evidence authority requirements do not match the request")

        if self.comparison.contract_digest != self.contract.digest:
            raise SemanticTranslationError("Transit evidence comparison is bound to another contract")
        if self.comparison.case_digest != canonical_value_digest({
            "request_fingerprint": self.request_fingerprint,
            "backend_manifest": [list(item) for item in manifest],
        }):
            raise SemanticTranslationError("Transit evidence comparison is bound to another request or backend manifest")
        if self.comparison.projection_digest != self.contract.observation.projection_digest:
            raise SemanticTranslationError("Transit evidence projection does not match its contract")
        if not self.comparison.equivalent:
            raise SemanticTranslationError("Transit evidence requires an equivalent canonical effect comparison")
        if self.comparison.source_observation_digest != self.comparison.target_observation_digest:
            raise SemanticTranslationError("Transit evidence observation digests do not match")
        if self.contract.effect_class is not EffectClass.JOURNALED:
            raise SemanticTranslationError("Transit execution evidence must describe a journaled effect")
        if self.contract.replay_class is not ReplayClass.SEMANTIC_LEDGER:
            raise SemanticTranslationError("Transit execution evidence must use semantic-ledger replay")

    @property
    def identity(self) -> tuple[str, str, int]:
        """Mathematics: project the semantic operation key I=(source, channel, sequence)."""
        return self.request_source, self.request_channel, self.request_sequence

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize one complete Transit binding, retaining the full contract and paired observation check."""
        return {
            "schema": _TRANSIT_EVIDENCE_SCHEMA,
            "request_source": self.request_source,
            "request_channel": self.request_channel,
            "request_sequence": self.request_sequence,
            "operation": self.operation,
            "resource": self.resource,
            "domain": self.domain,
            "required_rights": list(self.required_rights),
            "request_fingerprint": self.request_fingerprint,
            "decision_receipt": self.decision_receipt,
            "effect_digest": self.effect_digest,
            "backend_manifest": [list(item) for item in self.backend_manifest],
            "contract": self.contract.to_dict(),
            "comparison": self.comparison.to_dict(),
        }

    @property
    def digest(self) -> str:
        """Mathematics: define the complete Transit evidence identity as H(to_dict(evidence))."""
        return canonical_value_digest(self.to_dict())

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "TransitTranslationEvidence":
        """Mathematics: reconstruct the exact Transit evidence schema and revalidate every cross-field binding."""
        expected = {
            "schema",
            "request_source",
            "request_channel",
            "request_sequence",
            "operation",
            "resource",
            "domain",
            "required_rights",
            "request_fingerprint",
            "decision_receipt",
            "effect_digest",
            "backend_manifest",
            "contract",
            "comparison",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected or payload["schema"] != _TRANSIT_EVIDENCE_SCHEMA:
            raise SemanticTranslationError("Transit translation evidence schema or fields are invalid")
        if not isinstance(payload["required_rights"], (list, tuple)):
            raise SemanticTranslationError("Transit evidence required_rights must be an array")
        if not isinstance(payload["backend_manifest"], (list, tuple)):
            raise SemanticTranslationError("Transit evidence backend_manifest must be an array")
        if any(not isinstance(item, (list, tuple)) for item in payload["backend_manifest"]):
            raise SemanticTranslationError("Transit evidence backend_manifest entries must be pairs")
        if not isinstance(payload["contract"], Mapping) or not isinstance(payload["comparison"], Mapping):
            raise SemanticTranslationError("Transit evidence contract and comparison must be objects")
        return cls(
            request_source=payload["request_source"],
            request_channel=payload["request_channel"],
            request_sequence=payload["request_sequence"],
            operation=payload["operation"],
            resource=payload["resource"],
            domain=payload["domain"],
            required_rights=tuple(payload["required_rights"]),
            request_fingerprint=payload["request_fingerprint"],
            decision_receipt=payload["decision_receipt"],
            effect_digest=payload["effect_digest"],
            backend_manifest=tuple(tuple(item) for item in payload["backend_manifest"]),
            contract=TranslationContract.from_dict(payload["contract"]),
            comparison=ObservationComparison.from_dict(payload["comparison"]),
        )

    def validate_execution_result(
        self,
        result: Any,
        *,
        require_oracle: bool = False,
    ) -> None:
        """Cross-check translation provenance and, when required, independent oracle evidence.

        Mathematics: require result.identity=I, result.fingerprint=F,
        result.decision_receipt=D, result.domain=domain, result.executed=1,
        and H(result.effect without reserved evidence)=H(E); additionally
        require oracle evidence O when require_oracle=True. Absence of O is
        accepted only as a pre-oracle legacy ledger record, never as proof of
        semantic correctness.
        """
        from .classifier import HypervisorAction, HypervisorExecutionResult

        if not isinstance(result, HypervisorExecutionResult):
            raise SemanticTranslationError("Transit evidence requires a HypervisorExecutionResult")
        if (result.source, result.channel, result.sequence) != self.identity:
            raise SemanticTranslationError("Transit evidence identity does not match the execution result")
        if result.fingerprint != self.request_fingerprint:
            raise SemanticTranslationError("Transit evidence fingerprint does not match the execution result")
        if result.decision_receipt != self.decision_receipt:
            raise SemanticTranslationError("Transit evidence decision receipt does not match the execution result")
        if result.action is not HypervisorAction.ALLOW or result.domain.value != self.domain:
            raise SemanticTranslationError("Transit evidence policy action or domain does not match the execution result")
        if not result.executed or not isinstance(result.effect, Mapping):
            raise SemanticTranslationError("Transit evidence execution result has no committed object effect")
        raw_evidence = result.effect.get("_semantic_translation")
        if not isinstance(raw_evidence, Mapping):
            raise SemanticTranslationError("execution result is missing embedded Transit translation evidence")
        embedded = TransitTranslationEvidence.from_dict(raw_evidence)
        if embedded != self:
            raise SemanticTranslationError("embedded Transit translation evidence differs from the supplied record")
        raw_effect = {
            key: value for key, value in result.effect.items()
            if key not in {"_semantic_translation", "_semantic_oracle"}
        }
        if canonical_value_digest(raw_effect) != self.effect_digest:
            raise SemanticTranslationError("Transit evidence effect digest does not match the execution result")
        raw_oracle = result.effect.get("_semantic_oracle")
        if (
            self.operation == "execute deterministic CPU arithmetic program"
            and self.resource == "/cpu/compute"
        ):
            expected_oracle_type = _CPU_ORACLE_REF.type_id
        elif (
            self.operation == "read admitted structural-memory revision coordinate"
            and self.resource == "/structural-memory/read"
        ):
            expected_oracle_type = _STRUCTURAL_MEMORY_ORACLE_REF.type_id
        else:
            expected_oracle_type = None
        if type(require_oracle) is not bool:
            raise SemanticTranslationError("require_oracle must be a Boolean")
        if expected_oracle_type is not None and raw_oracle is None and require_oracle:
            raise SemanticTranslationError("supported Transit operation is missing required independent oracle evidence")
        if raw_oracle is not None:
            if not isinstance(raw_oracle, Mapping):
                raise SemanticTranslationError("embedded Transit oracle evidence must be an object")
            oracle = TransitOracleEvidence.from_dict(raw_oracle)
            oracle.validate_against_effect(
                raw_effect,
                request_fingerprint=self.request_fingerprint,
            )
            if expected_oracle_type is not None and oracle.oracle.type_id != expected_oracle_type:
                raise SemanticTranslationError("Transit oracle type does not match the selected operation")



def build_transit_translation_evidence(
    event: Any,
    raw_effect: Any,
    canonical_effect: Any,
    *,
    backend_manifest: tuple[tuple[str, str], ...],
    decision_receipt: str,
    domain: str,
) -> TransitTranslationEvidence:
    """Bind an authorized Transit event and backend result to a checked canonical effect representation.

    Mathematics: for authorized event e, raw backend effect E, canonical JSON
    round-trip E', selected backend manifest M, and policy receipt d, construct
    a contract C=(e,E,map(M),context,authority,effect,replay) and paired check
    π(E)=π(E'). The evidence record binds the operation identity, event digest,
    decision receipt, exact effect digest, and M. It is created before the
    hypervisor stores E in its semantic execution ledger, so exact replays
    return the same evidence without invoking this builder again.
    """
    from .classifier import HypervisorArbitrationEvent

    if not isinstance(event, HypervisorArbitrationEvent):
        raise SemanticTranslationError("Transit evidence requires an authorized HypervisorArbitrationEvent")
    if not isinstance(raw_effect, Mapping) or not isinstance(canonical_effect, Mapping):
        raise SemanticTranslationError("Transit handler effects must be JSON objects")
    if not isinstance(domain, str) or not domain:
        raise SemanticTranslationError("Transit execution domain must be non-empty text")
    if not isinstance(backend_manifest, (tuple, list)):
        raise SemanticTranslationError("Transit backend manifest must be an array")
    if any(not isinstance(item, (tuple, list)) for item in backend_manifest):
        raise SemanticTranslationError("Transit backend manifest entries must be operation/resource pairs")
    manifest = tuple(tuple(item) for item in backend_manifest)
    if not manifest or tuple(sorted(set(manifest))) != manifest:
        raise SemanticTranslationError("Transit backend manifest must be sorted, unique, and non-empty")
    fingerprint = canonical_value_digest(event.to_dict())
    effect_digest = canonical_value_digest(raw_effect)
    source = RepresentationRef.from_payload(
        "mailcpu.transit.authorized-event",
        1,
        event.to_dict(),
    )
    target = RepresentationRef.from_payload(
        "mailcpu.transit.handler-effect",
        1,
        raw_effect,
    )
    mapping = RepresentationRef.from_payload(
        "mailcpu.transit.backend-dispatch",
        1,
        {
            "operation": event.request.operation,
            "resource": event.request.resource,
            "domain": domain,
            "backend_manifest": [list(item) for item in manifest],
            "adapter": "mailcpu.transit-worker.effect-encoder.v1",
        },
    )
    observation = ObservationContract.from_definition(
        "mailcpu.transit.handler-effect",
        1,
        {
            "projection": "complete handler effect",
            "normalization": "sorted-key compact canonical JSON round-trip",
            "comparison": "canonical-json-exact",
        },
    )
    context_digest = canonical_value_digest({
        "operation": event.request.operation,
        "resource": event.request.resource,
        "payload": event.request.payload,
    })
    rights = tuple(sorted(event.request.required_rights))
    authority = (
        (CapabilityRequirement(event.request.resource, rights),)
        if rights
        else ()
    )
    contract = TranslationContract(
        contract_id="mailcpu.transit.operation",
        revision=1,
        source=source,
        target=target,
        mapping=mapping,
        observation=observation,
        context_digest=context_digest,
        precondition_digests=(
            canonical_value_digest({"receiver_authorized": True}),
            canonical_value_digest({"operation": event.request.operation, "resource": event.request.resource}),
        ),
        invariant_digests=(
            canonical_value_digest({"effect_commit": "hypervisor.execution"}),
            canonical_value_digest({"replay": "same semantic identity returns stored effect"}),
        ),
        authority_requirements=authority,
        effect_class=EffectClass.JOURNALED,
        replay_class=ReplayClass.SEMANTIC_LEDGER,
    )
    comparison = compare_projected_observations(
        contract,
        case_payload={
            "request_fingerprint": fingerprint,
            "backend_manifest": [list(item) for item in manifest],
        },
        source_observation=raw_effect,
        target_observation=canonical_effect,
    )
    if not comparison.equivalent:
        raise SemanticTranslationError("Transit handler effect changed during canonical representation")
    return TransitTranslationEvidence(
        request_source=event.source,
        request_channel=event.channel,
        request_sequence=event.sequence,
        operation=event.request.operation,
        resource=event.request.resource,
        domain=domain,
        required_rights=rights,
        request_fingerprint=fingerprint,
        decision_receipt=decision_receipt,
        effect_digest=effect_digest,
        backend_manifest=manifest,
        contract=contract,
        comparison=comparison,
    )
