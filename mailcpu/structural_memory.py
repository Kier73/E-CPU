"""Verified, versioned structural memories over MailCPU's deterministic law algebra.

This E0 service stores compact generators rather than materialized traces. It
admits only a fixed set of existing deterministic law families, binds every
version to an exact context and witness digest, and uses guarded navigation for
all runtime reads. A GROUND verdict means agreement with the supplied witness
set; it is not a proof over an infinite domain.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, replace
from enum import Enum
import hashlib
import json
import threading
from typing import Any, Callable, Iterator, Mapping, Sequence

from .journal import EventJournal

from .law_certifier import (
    HorizonExceeded,
    Law,
    Refused,
    navigate_guarded,
    recover_law,
)


STRUCTURAL_MEMORY_SCHEMA = "mailcpu.structural-memory.v1"
STRUCTURE_READ = "STRUCTURE_READ"
STRUCTURE_PROPOSE = "STRUCTURE_PROPOSE"
STRUCTURE_ADMIT = "STRUCTURE_ADMIT"
STRUCTURAL_MEMORY_REGISTRY_SCHEMA = "mailcpu.structural-memory-registry.v1"


class StructuralMemoryError(ValueError):
    """Malformed structural-memory identity, schema, or request."""


class StructuralMemoryRefused(StructuralMemoryError):
    """A valid request cannot be justified by the active structural evidence."""


class StructuralMemoryConflict(StructuralMemoryError):
    """A staged revision is stale relative to the active structural-memory head."""


class StructuralMemoryAuthorizationError(StructuralMemoryError):
    """A proposal lacks an explicit trusted host admission decision."""


class VerificationClass(str, Enum):
    """Evidence grade carried by an admitted structural-memory version."""

    WITNESS_GROUNDED = "witness_grounded"
    PREFIX_GROUNDED = "prefix_grounded"


def _json_value(value: Any, path: str = "value") -> Any:
    """Return a detached JSON value and reject opaque or non-string-keyed data. Mathematics: recursively maps values into the JSON scalar, mapping, and sequence algebra. """
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        # json.dumps below rejects NaN and infinities.
        return value
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise StructuralMemoryError(f"{path} mapping keys must be strings")
            result[key] = _json_value(item, f"{path}.{key}")
        return result
    if isinstance(value, (tuple, list)):
        return [_json_value(item, f"{path}[{index}]") for index, item in enumerate(value)]
    raise StructuralMemoryError(f"{path} contains unsupported value type {type(value).__name__}")


def _canonical_json(value: Any) -> str:
    """Encode a JSON-compatible value in one canonical sorted compact form. Mathematics: encodes x as sorted, compact JSON with non-finite numbers excluded. """
    try:
        return json.dumps(
            _json_value(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        if isinstance(exc, StructuralMemoryError):
            raise
        raise StructuralMemoryError(f"value is not canonical JSON: {exc}") from exc


def _digest(value: Any) -> str:
    """Calculate SHA-256 over the canonical JSON encoding of a value. Mathematics: defines H(x) = SHA256(canonical_json(x)). """
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _require_int(value: Any, name: str, *, minimum: int | None = None) -> int:
    """Validate one strict integer field, excluding Booleans. Mathematics: accepts x in the integers, excluding Boolean values and enforcing an optional lower bound. """
    if type(value) is not int:
        raise StructuralMemoryError(f"{name} must be an integer (booleans are not coordinates)")
    if minimum is not None and value < minimum:
        raise StructuralMemoryError(f"{name} must be at least {minimum}")
    return value


def _require_nonempty_string(value: Any, name: str, *, maximum: int = 256) -> str:
    """Validate one bounded non-empty text identifier. Mathematics: enforces 1 <= length(s) <= maximum and non-whitespace content. """
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise StructuralMemoryError(f"{name} must be a non-empty string of at most {maximum} characters")
    return value


def _require_hash(value: Any, name: str) -> str:
    """Validate one lowercase SHA-256 hexadecimal digest. Mathematics: enforces s in {0,...,9,a,...,f}^64. """
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise StructuralMemoryError(f"{name} must be a lowercase SHA-256 hex digest")
    return value


def _validate_law_parameters(family: str, params: Mapping[str, Any], order: int) -> None:
    """Validate the exact parameter ABI for each admitted generator family. Mathematics: checks each generator parameter vector against its family schema and order constraints. """
    if family == "int":
        if set(params) != {"x0", "step", "mod"}:
            raise StructuralMemoryError("int generator parameters must be exactly x0, step, and mod")
        _require_int(params["x0"], "int.x0")
        _require_int(params["step"], "int.step")
        _require_int(params["mod"], "int.mod", minimum=2)
        if order != 1:
            raise StructuralMemoryError("int generator order must be 1")
        return

    if family == "lcg":
        if set(params) != {"a", "c", "mod", "x0"}:
            raise StructuralMemoryError("lcg generator parameters must be exactly a, c, mod, and x0")
        for key in ("a", "c", "x0"):
            _require_int(params[key], f"lcg.{key}")
        _require_int(params["mod"], "lcg.mod", minimum=2)
        if order != 1:
            raise StructuralMemoryError("lcg generator order must be 1")
        return

    if family == "gf2":
        if set(params) != {"C", "init"}:
            raise StructuralMemoryError("gf2 generator parameters must be exactly C and init")
        coefficients = params["C"]
        initial = params["init"]
        if not isinstance(coefficients, list) or not isinstance(initial, list):
            raise StructuralMemoryError("gf2 C and init parameters must be arrays")
        if not initial or len(initial) != order:
            raise StructuralMemoryError("gf2 init length must equal its positive recurrence order")
        if len(coefficients) < order + 1:
            raise StructuralMemoryError("gf2 connection polynomial is shorter than its recurrence order")
        if any(type(bit) is not int or bit not in (0, 1) for bit in coefficients + initial):
            raise StructuralMemoryError("gf2 coefficients and initial values must be bits")
        if coefficients[0] != 1:
            raise StructuralMemoryError("gf2 connection polynomial must have constant coefficient 1")
        return

    if family == "fgraph":
        if set(params) != {"mu", "lam", "orbit"}:
            raise StructuralMemoryError("fgraph generator parameters must be exactly mu, lam, and orbit")
        mu = _require_int(params["mu"], "fgraph.mu", minimum=0)
        lam = _require_int(params["lam"], "fgraph.lam", minimum=1)
        orbit = params["orbit"]
        if not isinstance(orbit, list) or any(type(item) is not int for item in orbit):
            raise StructuralMemoryError("fgraph orbit must be an array of integers")
        if len(orbit) != mu + lam:
            raise StructuralMemoryError("fgraph orbit must contain exactly mu + lam states")
        if order != lam:
            raise StructuralMemoryError("fgraph order must equal its cycle length")
        return

    raise StructuralMemoryRefused(f"generator family {family!r} is not admitted by E0")


@dataclass(frozen=True)
class StructuralMemorySpec:
    """Immutable, digest-addressed structural description for one memory revision."""

    memory_id: str
    revision: int
    domain: str
    family: str
    parameters_json: str
    context_json: str
    order: int
    law_verdict: str
    first_bad: int | None = None
    parent_digest: str | None = None
    schema: str = STRUCTURAL_MEMORY_SCHEMA

    def __post_init__(self) -> None:
        _require_nonempty_string(self.memory_id, "memory_id")
        _require_int(self.revision, "revision", minimum=1)
        _require_nonempty_string(self.domain, "domain", maximum=128)
        _require_nonempty_string(self.family, "family", maximum=32)
        _require_int(self.order, "order", minimum=0)
        if self.schema != STRUCTURAL_MEMORY_SCHEMA:
            raise StructuralMemoryError(f"unsupported structural-memory schema {self.schema!r}")
        if self.family not in {"int", "lcg", "gf2", "fgraph"}:
            raise StructuralMemoryRefused(f"generator family {self.family!r} is not admitted by E0")
        if self.law_verdict not in {"GROUND", "PREFIX-GROUND"}:
            raise StructuralMemoryRefused(
                f"law verdict {self.law_verdict!r} is not admissible; FITTED and TAPE cannot be admitted by E0"
            )
        if self.law_verdict == "GROUND" and self.first_bad is not None:
            raise StructuralMemoryError("GROUND law cannot carry a first_bad horizon")
        if self.law_verdict == "PREFIX-GROUND":
            _require_int(self.first_bad, "first_bad", minimum=1)
        if self.parent_digest is not None:
            _require_hash(self.parent_digest, "parent_digest")

        try:
            params = json.loads(self.parameters_json)
            context = json.loads(self.context_json)
        except (TypeError, json.JSONDecodeError) as exc:
            raise StructuralMemoryError(f"spec JSON is invalid: {exc}") from exc
        if not isinstance(params, dict) or _canonical_json(params) != self.parameters_json:
            raise StructuralMemoryError("parameters_json must be a canonical JSON object")
        if not isinstance(context, dict) or _canonical_json(context) != self.context_json:
            raise StructuralMemoryError("context_json must be a canonical JSON object")
        _validate_law_parameters(self.family, params, self.order)

    @classmethod
    def from_law(
        cls,
        memory_id: str,
        revision: int,
        domain: str,
        law: Law,
        context: Mapping[str, Any] | None = None,
        parent_digest: str | None = None,
    ) -> "StructuralMemorySpec":
        """Create a schema-checked immutable spec from an existing Law object. Mathematics: maps a certified law tuple (family, parameters, order, verdict) into an immutable structural specification. """
        if not isinstance(law, Law):
            raise StructuralMemoryError("law must be an existing mailcpu.law_certifier.Law")
        if law.family not in {"int", "lcg", "gf2", "fgraph"}:
            raise StructuralMemoryRefused(f"generator family {law.family!r} is not admitted by E0")
        if law.verdict not in {"GROUND", "PREFIX-GROUND"}:
            raise StructuralMemoryRefused(
                f"law verdict {law.verdict!r} is not admissible; FITTED and TAPE cannot be admitted by E0"
            )
        context_value = {} if context is None else _json_value(context, "context")
        if not isinstance(context_value, dict):
            raise StructuralMemoryError("context must be a JSON object")
        return cls(
            memory_id=memory_id,
            revision=revision,
            domain=domain,
            family=law.family,
            parameters_json=_canonical_json(law.params),
            context_json=_canonical_json(context_value),
            order=law.order,
            law_verdict=law.verdict,
            first_bad=law.first_bad,
            parent_digest=parent_digest,
        )

    @property
    def parameters(self) -> dict[str, Any]:
        """Return a detached copy of the generator parameters. Mathematics: decodes the canonical parameter encoding into a detached mapping. """
        return json.loads(self.parameters_json)

    @property
    def context(self) -> dict[str, Any]:
        """Return a detached copy of the context boundary metadata. Mathematics: decodes the canonical boundary encoding into a detached mapping. """
        return json.loads(self.context_json)

    @property
    def context_digest(self) -> str:
        """Return the SHA-256 digest of the exact canonical context. Mathematics: computes H(context_json) for the exact canonical boundary. """
        return hashlib.sha256(self.context_json.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        """Serialize this immutable structural-memory record. Mathematics: projects the immutable record onto its schema-defined serialization fields. """
        return {
            "schema": self.schema,
            "memory_id": self.memory_id,
            "revision": self.revision,
            "domain": self.domain,
            "family": self.family,
            "parameters": self.parameters,
            "context": self.context,
            "order": self.order,
            "law_verdict": self.law_verdict,
            "first_bad": self.first_bad,
            "parent_digest": self.parent_digest,
        }

    @property
    def digest(self) -> str:
        """Return the stable digest of this immutable record. Mathematics: computes H(to_dict(record)) as the stable identity of this immutable record. """
        return _digest(self.to_dict())

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "StructuralMemorySpec":
        """Reconstruct one immutable spec from its exact typed projection. Mathematics: invert the spec serialization map and require its generator ABI and canonical parameters to validate."""
        expected = {
            "schema", "memory_id", "revision", "domain", "family", "parameters",
            "context", "order", "law_verdict", "first_bad", "parent_digest",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise StructuralMemoryError("structural memory spec fields are invalid")
        parameters = payload["parameters"]
        context = payload["context"]
        if not isinstance(parameters, Mapping) or not isinstance(context, Mapping):
            raise StructuralMemoryError("structural memory parameters and context must be objects")
        return cls(
            memory_id=payload["memory_id"],
            revision=payload["revision"],
            domain=payload["domain"],
            family=payload["family"],
            parameters_json=_canonical_json(parameters),
            context_json=_canonical_json(context),
            order=payload["order"],
            law_verdict=payload["law_verdict"],
            first_bad=payload["first_bad"],
            parent_digest=payload["parent_digest"],
            schema=payload["schema"],
        )


@dataclass(frozen=True)
class StructuralMemoryCertificate:
    """Immutable evidence record bound to one exact spec and context digest."""

    spec_digest: str
    context_digest: str
    witness_digest: str
    witness_count: int
    verification_class: VerificationClass
    first_bad: int | None
    valid_before_exclusive: int | None
    generator_id: str = "mailcpu.law_certifier"
    generator_version: int = 1
    schema: str = "mailcpu.structural-memory-certificate.v1"

    def __post_init__(self) -> None:
        _require_hash(self.spec_digest, "certificate.spec_digest")
        _require_hash(self.context_digest, "certificate.context_digest")
        _require_hash(self.witness_digest, "certificate.witness_digest")
        _require_int(self.witness_count, "witness_count", minimum=2)
        _require_nonempty_string(self.generator_id, "generator_id", maximum=128)
        _require_int(self.generator_version, "generator_version", minimum=1)
        if self.schema != "mailcpu.structural-memory-certificate.v1":
            raise StructuralMemoryError("unsupported certificate schema")
        if not isinstance(self.verification_class, VerificationClass):
            raise StructuralMemoryError("verification_class must be a VerificationClass")
        if self.verification_class is VerificationClass.WITNESS_GROUNDED:
            if self.first_bad is not None or self.valid_before_exclusive is not None:
                raise StructuralMemoryError("witness-grounded certificate cannot carry a prefix horizon")
        else:
            _require_int(self.first_bad, "certificate.first_bad", minimum=1)
            if self.valid_before_exclusive != self.first_bad:
                raise StructuralMemoryError("prefix certificate horizon must equal first_bad")

    def to_dict(self) -> dict[str, Any]:
        """Serialize this immutable structural-memory record. Mathematics: projects the immutable record onto its schema-defined serialization fields. """
        return {
            "schema": self.schema,
            "spec_digest": self.spec_digest,
            "context_digest": self.context_digest,
            "witness_digest": self.witness_digest,
            "witness_count": self.witness_count,
            "verification_class": self.verification_class.value,
            "first_bad": self.first_bad,
            "valid_before_exclusive": self.valid_before_exclusive,
            "generator_id": self.generator_id,
            "generator_version": self.generator_version,
        }

    @property
    def digest(self) -> str:
        """Return the stable digest of this immutable certificate. Mathematics: computes H(to_dict(record)) as the stable identity of this immutable record. """
        return _digest(self.to_dict())

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "StructuralMemoryCertificate":
        """Reconstruct one typed evidence certificate. Mathematics: invert certificate serialization while preserving the exact evidence grade, horizon and digest bindings."""
        expected = {
            "schema", "spec_digest", "context_digest", "witness_digest", "witness_count",
            "verification_class", "first_bad", "valid_before_exclusive", "generator_id",
            "generator_version",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise StructuralMemoryError("structural memory certificate fields are invalid")
        try:
            verification_class = VerificationClass(payload["verification_class"])
        except (TypeError, ValueError) as exc:
            raise StructuralMemoryError("structural memory verification class is invalid") from exc
        return cls(
            spec_digest=payload["spec_digest"],
            context_digest=payload["context_digest"],
            witness_digest=payload["witness_digest"],
            witness_count=payload["witness_count"],
            verification_class=verification_class,
            first_bad=payload["first_bad"],
            valid_before_exclusive=payload["valid_before_exclusive"],
            generator_id=payload["generator_id"],
            generator_version=payload["generator_version"],
            schema=payload["schema"],
        )


@dataclass(frozen=True)
class StructuralMemoryProposal:
    """Staged immutable candidate; creating it never changes an active version."""

    proposal_id: str
    spec: StructuralMemorySpec
    certificate: StructuralMemoryCertificate
    witnesses: tuple[tuple[int, int], ...]

    def __post_init__(self) -> None:
        _require_hash(self.proposal_id, "proposal_id")
        if not isinstance(self.spec, StructuralMemorySpec):
            raise StructuralMemoryError("proposal spec is invalid")
        if not isinstance(self.certificate, StructuralMemoryCertificate):
            raise StructuralMemoryError("proposal certificate is invalid")
        if not isinstance(self.witnesses, tuple) or len(self.witnesses) < 2:
            raise StructuralMemoryError("proposal witnesses must be a tuple of at least two coordinate/value pairs")
        for index, item in enumerate(self.witnesses):
            if not isinstance(item, tuple) or len(item) != 2:
                raise StructuralMemoryError(f"proposal witness {index} must be a coordinate/value pair")
            _require_int(item[0], f"proposal witness {index} coordinate", minimum=0)
            _require_int(item[1], f"proposal witness {index} value")
        normalized = tuple(sorted(self.witnesses))
        if normalized != self.witnesses or len({item[0] for item in normalized}) != len(normalized):
            raise StructuralMemoryError("proposal witnesses must be unique and sorted by coordinate")
        expected = _digest({
            "spec": self.spec.to_dict(),
            "certificate": self.certificate.to_dict(),
            "witnesses": [[coordinate, observed] for coordinate, observed in self.witnesses],
        })
        if self.proposal_id != expected:
            raise StructuralMemoryError("proposal ID does not match its immutable contents")

    def to_dict(self) -> dict[str, Any]:
        """Serialize this immutable structural-memory record. Mathematics: projects the immutable record onto its schema-defined serialization fields. """
        return {
            "proposal_id": self.proposal_id,
            "spec": self.spec.to_dict(),
            "certificate": self.certificate.to_dict(),
            "witnesses": [[coordinate, observed] for coordinate, observed in self.witnesses],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "StructuralMemoryProposal":
        """Reconstruct a staged proposal and its finite witness set. Mathematics: invert proposal serialization and recompute its content-addressed proposal identity."""
        expected = {"proposal_id", "spec", "certificate", "witnesses"}
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise StructuralMemoryError("structural memory proposal fields are invalid")
        raw_witnesses = payload["witnesses"]
        if not isinstance(raw_witnesses, (list, tuple)):
            raise StructuralMemoryError("structural memory proposal witnesses must be a sequence")
        witnesses: list[tuple[int, int]] = []
        for item in raw_witnesses:
            if not isinstance(item, (list, tuple)) or len(item) != 2:
                raise StructuralMemoryError("structural memory proposal witness must be a pair")
            witnesses.append((item[0], item[1]))
        return cls(
            proposal_id=payload["proposal_id"],
            spec=StructuralMemorySpec.from_dict(payload["spec"]),
            certificate=StructuralMemoryCertificate.from_dict(payload["certificate"]),
            witnesses=tuple(witnesses),
        )


@dataclass(frozen=True)
class StructuralMemoryVersion:
    """One admitted immutable revision and its originating proposal identity."""

    spec: StructuralMemorySpec
    certificate: StructuralMemoryCertificate
    admitted_proposal_id: str

    def __post_init__(self) -> None:
        """Validate one admitted version against its exact spec and certificate. Mathematics: require certificate.spec_digest = H(spec) and certificate.context_digest = H(spec.context)."""
        if not isinstance(self.spec, StructuralMemorySpec):
            raise StructuralMemoryError("structural memory version spec is invalid")
        if not isinstance(self.certificate, StructuralMemoryCertificate):
            raise StructuralMemoryError("structural memory version certificate is invalid")
        _require_hash(self.admitted_proposal_id, "admitted_proposal_id")
        if self.certificate.spec_digest != self.spec.digest:
            raise StructuralMemoryError("version certificate does not bind its spec")
        if self.certificate.context_digest != self.spec.context_digest:
            raise StructuralMemoryError("version certificate does not bind its context")

    def to_dict(self) -> dict[str, Any]:
        """Serialize this immutable structural-memory record. Mathematics: projects the immutable record onto its schema-defined serialization fields. """
        return {
            "spec": self.spec.to_dict(),
            "certificate": self.certificate.to_dict(),
            "admitted_proposal_id": self.admitted_proposal_id,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "StructuralMemoryVersion":
        """Reconstruct one admitted immutable version. Mathematics: map its nested spec and certificate projections back to the typed revision identity."""
        expected = {"spec", "certificate", "admitted_proposal_id"}
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise StructuralMemoryError("structural memory version fields are invalid")
        return cls(
            spec=StructuralMemorySpec.from_dict(payload["spec"]),
            certificate=StructuralMemoryCertificate.from_dict(payload["certificate"]),
            admitted_proposal_id=payload["admitted_proposal_id"],
        )


@dataclass(frozen=True)
class StructuralMemoryReadReceipt:
    """Evidence-bearing result of one structural read."""

    receipt_id: str
    memory_id: str
    revision: int
    spec_digest: str
    certificate_digest: str
    coordinate: int
    context_digest: str
    value: int
    value_digest: str
    verification_class: VerificationClass
    witness_digest: str
    cache_hit: bool = False

    def __post_init__(self) -> None:
        """Validate one immutable structural-read receipt. Mathematics: require every identity to be a 256-bit digest and all coordinates and values to be strict integers."""
        _require_hash(self.receipt_id, "receipt_id")
        _require_nonempty_string(self.memory_id, "memory_id")
        _require_int(self.revision, "revision", minimum=1)
        for name in ("spec_digest", "certificate_digest", "context_digest", "value_digest", "witness_digest"):
            _require_hash(getattr(self, name), name)
        _require_int(self.coordinate, "coordinate", minimum=0)
        _require_int(self.value, "value")
        if not isinstance(self.verification_class, VerificationClass):
            raise StructuralMemoryError("receipt verification class is invalid")
        if type(self.cache_hit) is not bool:
            raise StructuralMemoryError("receipt cache_hit flag must be Boolean")

    def to_dict(self) -> dict[str, Any]:
        """Serialize this immutable structural-memory record. Mathematics: projects the immutable record onto its schema-defined serialization fields. """
        return {
            "receipt_id": self.receipt_id,
            "memory_id": self.memory_id,
            "revision": self.revision,
            "spec_digest": self.spec_digest,
            "certificate_digest": self.certificate_digest,
            "coordinate": self.coordinate,
            "context_digest": self.context_digest,
            "value": self.value,
            "value_digest": self.value_digest,
            "verification_class": self.verification_class.value,
            "witness_digest": self.witness_digest,
            "cache_hit": self.cache_hit,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "StructuralMemoryReadReceipt":
        """Reconstruct one typed structural read receipt. Mathematics: invert the full provenance projection without dropping its cache and evidence attributes."""
        expected = {
            "receipt_id", "memory_id", "revision", "spec_digest", "certificate_digest",
            "coordinate", "context_digest", "value", "value_digest", "verification_class",
            "witness_digest", "cache_hit",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise StructuralMemoryError("structural memory read receipt fields are invalid")
        try:
            verification_class = VerificationClass(payload["verification_class"])
        except (TypeError, ValueError) as exc:
            raise StructuralMemoryError("structural memory receipt verification class is invalid") from exc
        return cls(
            receipt_id=payload["receipt_id"],
            memory_id=payload["memory_id"],
            revision=payload["revision"],
            spec_digest=payload["spec_digest"],
            certificate_digest=payload["certificate_digest"],
            coordinate=payload["coordinate"],
            context_digest=payload["context_digest"],
            value=payload["value"],
            value_digest=payload["value_digest"],
            verification_class=verification_class,
            witness_digest=payload["witness_digest"],
            cache_hit=payload["cache_hit"],
        )


@dataclass(frozen=True)
class StructuralMemoryRangeReadReceipt:
    """Compact commitment to one ordered, revision-pinned range of generated integer values."""

    receipt_id: str
    memory_id: str
    revision: int
    spec_digest: str
    certificate_digest: str
    coordinate_start: int
    length: int
    context_digest: str
    value_range_digest: str
    value_receipt_digest: str
    verification_class: VerificationClass
    witness_digest: str

    def __post_init__(self) -> None:
        """Mathematics: bind an exact integer interval to its generator, certificate, context, value commitment and ordered per-coordinate receipt commitment."""
        _require_hash(self.receipt_id, "range receipt_id")
        _require_nonempty_string(self.memory_id, "range memory_id")
        _require_int(self.revision, "range revision", minimum=1)
        _require_int(self.coordinate_start, "range coordinate_start", minimum=0)
        _require_int(self.length, "range length", minimum=1)
        for name in (
            "spec_digest",
            "certificate_digest",
            "context_digest",
            "value_range_digest",
            "value_receipt_digest",
            "witness_digest",
        ):
            _require_hash(getattr(self, name), f"range {name}")
        if not isinstance(self.verification_class, VerificationClass):
            raise StructuralMemoryError("range receipt verification class is invalid")

    def to_dict(self) -> dict[str, Any]:
        """Serialize the compact range commitment. Mathematics: project the complete range identity and both aggregate digests."""
        return {
            "receipt_id": self.receipt_id,
            "memory_id": self.memory_id,
            "revision": self.revision,
            "spec_digest": self.spec_digest,
            "certificate_digest": self.certificate_digest,
            "coordinate_start": self.coordinate_start,
            "length": self.length,
            "context_digest": self.context_digest,
            "value_range_digest": self.value_range_digest,
            "value_receipt_digest": self.value_receipt_digest,
            "verification_class": self.verification_class.value,
            "witness_digest": self.witness_digest,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "StructuralMemoryRangeReadReceipt":
        """Reconstruct one typed aggregate range receipt. Mathematics: invert the exact range receipt schema without dropping either aggregate commitment."""
        expected = {
            "receipt_id",
            "memory_id",
            "revision",
            "spec_digest",
            "certificate_digest",
            "coordinate_start",
            "length",
            "context_digest",
            "value_range_digest",
            "value_receipt_digest",
            "verification_class",
            "witness_digest",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise StructuralMemoryError("structural memory range receipt fields are invalid")
        try:
            verification_class = VerificationClass(payload["verification_class"])
        except (TypeError, ValueError) as exc:
            raise StructuralMemoryError("structural memory range verification class is invalid") from exc
        return cls(
            receipt_id=payload["receipt_id"],
            memory_id=payload["memory_id"],
            revision=payload["revision"],
            spec_digest=payload["spec_digest"],
            certificate_digest=payload["certificate_digest"],
            coordinate_start=payload["coordinate_start"],
            length=payload["length"],
            context_digest=payload["context_digest"],
            value_range_digest=payload["value_range_digest"],
            value_receipt_digest=payload["value_receipt_digest"],
            verification_class=verification_class,
            witness_digest=payload["witness_digest"],
        )


class ContextMapper:
    """Canonicalize and bind an explicit context object without changing its law.

    E0 treats context as an exact boundary identity. Context-to-parameter
    adaptation is intentionally deferred; a changed context requires a new
    immutable proposal and revision.
    """

    def encode(self, context: Mapping[str, Any] | None) -> tuple[str, str]:
        """Return canonical context JSON and its SHA-256 identity. Mathematics: maps context c to (canonical_json(c), SHA256(canonical_json(c))). """
        value = {} if context is None else _json_value(context, "context")
        if not isinstance(value, dict):
            raise StructuralMemoryError("context must be a JSON object")
        encoded = _canonical_json(value)
        return encoded, hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def bind(self, spec: StructuralMemorySpec, context: Mapping[str, Any] | None) -> str:
        """Require a read context to equal the exact context bound into the spec. Mathematics: accepts a context exactly when canonical_json(c) equals the specification's canonical boundary. """
        if context is None:
            encoded = spec.context_json
            digest = spec.context_digest
        else:
            encoded, digest = self.encode(context)
        if encoded != spec.context_json or digest != spec.context_digest:
            raise StructuralMemoryRefused("read context does not match the context bound to this revision")
        return digest


class GeneratorRegistry:
    """Whitelist adapters over the existing deterministic law-certifier families."""

    GENERATOR_ID = "mailcpu.law_certifier"
    GENERATOR_VERSION = 1
    SUPPORTED_FAMILIES = frozenset({"int", "lcg", "gf2", "fgraph"})

    def build_law(self, spec: StructuralMemorySpec) -> Law:
        """Reconstruct one whitelisted Law from canonical spec parameters. Mathematics: reconstructs the deterministic transition law L from its whitelisted family and parameter vector. """
        if spec.family not in self.SUPPORTED_FAMILIES:
            raise StructuralMemoryRefused(f"generator family {spec.family!r} is not supported")
        verdict = "PREFIX-GROUND" if spec.first_bad is not None else "GROUND"
        return Law(
            family=spec.family,
            params=spec.parameters,
            order=spec.order,
            verdict=verdict,
            first_bad=spec.first_bad,
            residual=0.0,
        )

    def navigate_guarded(self, spec: StructuralMemorySpec, coordinate: int) -> int:
        """Evaluate one coordinate through the law certifier's horizon guard. Mathematics: evaluates G(t) only when t is strictly below any certified first_bad horizon. """
        law = self.build_law(spec)
        try:
            value = navigate_guarded(law, coordinate)
        except (HorizonExceeded, Refused) as exc:
            raise StructuralMemoryRefused(str(exc)) from exc
        if type(value) is not int:
            raise StructuralMemoryRefused("generator returned a non-integer value outside the E0 value ABI")
        return value

    def navigate_guarded_range(
        self,
        spec: StructuralMemorySpec,
        coordinate_start: int,
        count: int,
    ) -> tuple[int, ...]:
        """Evaluate a bounded ordered range under one reconstructed law. Mathematics: return (G(a),...,G(a+n-1)) using one admitted generator instance and the same per-coordinate horizon guard."""
        _require_int(coordinate_start, "coordinate_start", minimum=0)
        _require_int(count, "count", minimum=1)
        if count > 65_536:
            raise StructuralMemoryRefused("one structural range read cannot exceed 65536 coordinates")
        law = self.build_law(spec)
        values: list[int] = []
        for coordinate in range(coordinate_start, coordinate_start + count):
            try:
                value = navigate_guarded(law, coordinate)
            except (HorizonExceeded, Refused) as exc:
                raise StructuralMemoryRefused(str(exc)) from exc
            if type(value) is not int:
                raise StructuralMemoryRefused("generator returned a non-integer value outside the E0 value ABI")
            values.append(value)
        return tuple(values)

    def predict_prefix_boundary(self, spec: StructuralMemorySpec, coordinate: int) -> int:
        """Evaluate exactly first_bad for witness adjudication, never for runtime reads. Mathematics: evaluates G(first_bad) only to adjudicate the observed escape witness. """
        if spec.first_bad != coordinate:
            raise StructuralMemoryError("boundary prediction must be exactly at first_bad")
        return self.build_law(spec).navigate(coordinate)


class StructuralMemoryVerifier:
    """Independently replay supplied observations before issuing a memory certificate."""

    def __init__(self, generators: GeneratorRegistry | None = None) -> None:
        self.generators = generators or GeneratorRegistry()

    def certify(
        self,
        spec: StructuralMemorySpec,
        witnesses: tuple[tuple[int, int], ...],
    ) -> StructuralMemoryCertificate:
        """Issue a certificate only after deterministic witness replay succeeds. Mathematics: requires G(t_i) = y_i for every valid witness and, for prefix evidence, G(first_bad) != y_first_bad. """
        if not isinstance(spec, StructuralMemorySpec):
            raise StructuralMemoryError("certificate spec must be a StructuralMemorySpec")
        if not isinstance(witnesses, tuple) or len(witnesses) < 2:
            raise StructuralMemoryRefused("at least two independent witness coordinates are required")
        normalized: list[tuple[int, int]] = []
        for index, item in enumerate(witnesses):
            if not isinstance(item, tuple) or len(item) != 2:
                raise StructuralMemoryError(f"witness {index} must be a coordinate/value pair")
            coordinate = _require_int(item[0], f"witness {index} coordinate", minimum=0)
            observed = _require_int(item[1], f"witness {index} value")
            normalized.append((coordinate, observed))
        if normalized != sorted(normalized) or len({item[0] for item in normalized}) != len(normalized):
            raise StructuralMemoryError("witnesses must be unique and sorted by coordinate")
        witnesses = tuple(normalized)
        law_records: list[dict[str, Any]] = []
        boundary_mismatch = False
        prefix_valid_count = 0

        for coordinate, observed in witnesses:
            if spec.first_bad is not None:
                if coordinate > spec.first_bad:
                    raise StructuralMemoryRefused("prefix proposal includes a witness beyond first_bad")
                if coordinate == spec.first_bad:
                    predicted = self.generators.predict_prefix_boundary(spec, coordinate)
                    if predicted == observed:
                        raise StructuralMemoryRefused("first_bad witness does not escape the proposed law")
                    boundary_mismatch = True
                else:
                    predicted = self.generators.navigate_guarded(spec, coordinate)
                    if predicted != observed:
                        raise StructuralMemoryRefused(
                            f"witness mismatch at coordinate {coordinate}: predicted {predicted}, observed {observed}"
                        )
                    prefix_valid_count += 1
            else:
                predicted = self.generators.navigate_guarded(spec, coordinate)
                if predicted != observed:
                    raise StructuralMemoryRefused(
                        f"witness mismatch at coordinate {coordinate}: predicted {predicted}, observed {observed}"
                    )
            law_records.append({
                "coordinate": coordinate,
                "observed": observed,
                "predicted": predicted,
                "matches": predicted == observed,
            })

        if spec.first_bad is not None:
            if not boundary_mismatch:
                raise StructuralMemoryRefused("prefix certificate requires a mismatching witness exactly at first_bad")
            if prefix_valid_count < 2:
                raise StructuralMemoryRefused("prefix certificate requires at least two matching pre-horizon witnesses")
            evidence_class = VerificationClass.PREFIX_GROUNDED
            valid_before = spec.first_bad
        else:
            evidence_class = VerificationClass.WITNESS_GROUNDED
            valid_before = None

        witness_digest = _digest({
            "spec_digest": spec.digest,
            "observations": law_records,
        })
        return StructuralMemoryCertificate(
            spec_digest=spec.digest,
            context_digest=spec.context_digest,
            witness_digest=witness_digest,
            witness_count=len(law_records),
            verification_class=evidence_class,
            first_bad=spec.first_bad,
            valid_before_exclusive=valid_before,
            generator_id=self.generators.GENERATOR_ID,
            generator_version=self.generators.GENERATOR_VERSION,
        )

    def verify_proposal(self, proposal: StructuralMemoryProposal) -> None:
        """Recompute a staged proposal certificate from its immutable witnesses. Mathematics: reissues the certificate from the proposal's exact specification and witness tuple and compares digests. """
        recomputed = self.certify(proposal.spec, proposal.witnesses)
        if recomputed.to_dict() != proposal.certificate.to_dict():
            raise StructuralMemoryRefused("proposal certificate does not reproduce from its witness set")


class StructuralNavigator:
    """Read an admitted structural memory only under its exact version and context."""

    def __init__(
        self,
        generators: GeneratorRegistry | None = None,
        context_mapper: ContextMapper | None = None,
    ) -> None:
        self.generators = generators or GeneratorRegistry()
        self.context_mapper = context_mapper or ContextMapper()

    def validate(
        self,
        spec: StructuralMemorySpec,
        certificate: StructuralMemoryCertificate,
        coordinate: int,
        context: Mapping[str, Any] | None = None,
    ) -> str:
        """Validate certificate, context, coordinate, and horizon before any cache lookup. Mathematics: requires matching specification/context digests and t < valid_before_exclusive when a prefix horizon exists. """
        _require_int(coordinate, "coordinate", minimum=0)
        if certificate.spec_digest != spec.digest:
            raise StructuralMemoryRefused("certificate is bound to a different structural spec")
        if certificate.context_digest != spec.context_digest:
            raise StructuralMemoryRefused("certificate is bound to a different context")
        context_digest = self.context_mapper.bind(spec, context)
        if certificate.valid_before_exclusive is not None and coordinate >= certificate.valid_before_exclusive:
            raise StructuralMemoryRefused(
                f"coordinate {coordinate} is at or beyond exclusive prefix horizon "
                f"{certificate.valid_before_exclusive}"
            )
        return context_digest

    def read(
        self,
        spec: StructuralMemorySpec,
        certificate: StructuralMemoryCertificate,
        coordinate: int,
        context: Mapping[str, Any] | None = None,
    ) -> tuple[int, str]:
        """Return a guarded state value and its verified context digest. Mathematics: returns the guarded generator value G(t) together with the digest of its bound context. """
        context_digest = self.validate(spec, certificate, coordinate, context)
        return self.generators.navigate_guarded(spec, coordinate), context_digest


class StructuralMemoryRegistry:
    """Stage, authorize, journal, checkpoint, and read immutable structural-memory revisions.

    Proposals and admissions share the HeadlessOS event journal when attached.
    A checkpoint snapshot binds the registry projection to the exact journal cut
    captured by the VM checkpoint. Host admission policy is executable
    configuration and is deliberately never serialized.
    """

    def __init__(
        self,
        *,
        admission_policy: Callable[[StructuralMemoryProposal], bool] | None = None,
        generators: GeneratorRegistry | None = None,
        journal: EventJournal | None = None,
    ) -> None:
        """Mathematics: compose registry state R=(active, staged, admitted, cache) with an optional shared event chain J."""
        if journal is not None and not isinstance(journal, EventJournal):
            raise StructuralMemoryError("journal must be an EventJournal or None")
        self.generators = generators or GeneratorRegistry()
        self.context_mapper = ContextMapper()
        self.verifier = StructuralMemoryVerifier(self.generators)
        self.navigator = StructuralNavigator(self.generators, self.context_mapper)
        self.admission_policy = admission_policy
        self.journal = journal
        self._active: dict[str, StructuralMemoryVersion] = {}
        self._staged: dict[str, StructuralMemoryProposal] = {}
        self._admitted: dict[str, StructuralMemoryVersion] = {}
        self._read_cache: dict[tuple[str, str, str, int], StructuralMemoryReadReceipt] = {}
        self._lock = threading.RLock()

    @contextmanager
    def checkpoint_guard(self) -> Iterator[None]:
        """Hold the registry transition lock over a composite OS checkpoint. Mathematics: exclude registry transitions during the interval in which its journal and registry projections are captured."""
        with self._lock:
            yield

    def propose(
        self,
        memory_id: str,
        law: Law,
        witnesses: Mapping[int, int],
        *,
        domain: str = "integer-orbit",
        context: Mapping[str, Any] | None = None,
    ) -> StructuralMemoryProposal:
        """Stage a candidate law with independently replayed observations. Mathematics: creates a staged revision r+1 whose parent digest equals the current active revision digest."""
        _require_nonempty_string(memory_id, "memory_id")
        with self._lock:
            current = self._active.get(memory_id)
            revision = 1 if current is None else current.spec.revision + 1
            parent_digest = None if current is None else current.spec.digest
            spec = StructuralMemorySpec.from_law(
                memory_id,
                revision,
                domain,
                law,
                context=context,
                parent_digest=parent_digest,
            )
            normalized = self._normalize_witnesses(witnesses)
            certificate = self.verifier.certify(spec, normalized)
            proposal_id = _digest({
                "spec": spec.to_dict(),
                "certificate": certificate.to_dict(),
                "witnesses": [[coordinate, observed] for coordinate, observed in normalized],
            })
            proposal = StructuralMemoryProposal(
                proposal_id=proposal_id,
                spec=spec,
                certificate=certificate,
                witnesses=normalized,
            )
            existing = self._staged.get(proposal_id)
            if existing is not None:
                return existing
            self._append_journal(
                "structural_memory.propose",
                self._proposal_event_payload(proposal),
            )
            self._staged[proposal_id] = proposal
            return proposal

    def propose_context_revision(
        self,
        memory_id: str,
        context: Mapping[str, Any] | None,
        witnesses: Mapping[int, int],
    ) -> StructuralMemoryProposal:
        """Stage a new context binding while preserving the active generator exactly.

        Mathematics: given active version v=(G,c,r), construct v'=(G,c',r+1)
        with parent_digest=H(v), then certify fresh caller-supplied observations
        against the unchanged generator G before host admission.
        """
        _require_nonempty_string(memory_id, "memory_id")
        with self._lock:
            current = self._active.get(memory_id)
            if current is None:
                raise StructuralMemoryRefused(
                    f"memory {memory_id!r} has no admitted revision to adapt"
                )
            context_json, _ = self.context_mapper.encode(context)
            if context_json == current.spec.context_json:
                raise StructuralMemoryRefused(
                    "context-only revision must change the bound context"
                )

            # Replacing only these three fields makes generator preservation a
            # construction property, not a comparison left to caller discipline.
            spec = replace(
                current.spec,
                revision=current.spec.revision + 1,
                context_json=context_json,
                parent_digest=current.spec.digest,
            )
            normalized = self._normalize_witnesses(witnesses)
            certificate = self.verifier.certify(spec, normalized)
            proposal_id = _digest({
                "spec": spec.to_dict(),
                "certificate": certificate.to_dict(),
                "witnesses": [[coordinate, observed] for coordinate, observed in normalized],
            })
            proposal = StructuralMemoryProposal(
                proposal_id=proposal_id,
                spec=spec,
                certificate=certificate,
                witnesses=normalized,
            )
            existing = self._staged.get(proposal_id)
            if existing is not None:
                return existing
            self._append_journal(
                "structural_memory.propose",
                self._proposal_event_payload(proposal),
            )
            self._staged[proposal_id] = proposal
            return proposal

    def propose_trace(
        self,
        memory_id: str,
        training: Sequence[int],
        withheld: Sequence[int],
        *,
        domain: str = "integer-orbit",
        context: Mapping[str, Any] | None = None,
    ) -> StructuralMemoryProposal:
        """Recover a known law from a training window and withheld witness suffix. Mathematics: derives a candidate law from training W and withheld T, then verifies their combined coordinate/value observations."""
        train = self._normalize_samples(training, "training")
        holdout = self._normalize_samples(withheld, "withheld")
        if not train or not holdout:
            raise StructuralMemoryError("propose_trace requires non-empty training and withheld sequences")
        try:
            law = recover_law(train, holdout)
        except Exception as exc:
            raise StructuralMemoryRefused(f"law recovery failed: {exc}") from exc
        if law.verdict not in {"GROUND", "PREFIX-GROUND"}:
            raise StructuralMemoryRefused(
                f"law recovery returned {law.verdict}; fitted or tape descriptions cannot be admitted"
            )
        samples = train + holdout
        witness_map = {coordinate: observed for coordinate, observed in enumerate(samples)}
        if law.first_bad is not None:
            witness_map = {
                coordinate: observed
                for coordinate, observed in witness_map.items()
                if coordinate <= law.first_bad
            }
        return self.propose(
            memory_id,
            law,
            witness_map,
            domain=domain,
            context=context,
        )

    def admit(self, proposal_id: str, *, expected_revision: int) -> StructuralMemoryVersion:
        """Admit one staged proposal after host authorization and revision CAS. Mathematics: commits only when active_revision = expected_revision, parent identity matches, and host_policy(proposal) is True."""
        _require_hash(proposal_id, "proposal_id")
        expected = _require_int(expected_revision, "expected_revision", minimum=0)
        with self._lock:
            already_admitted = self._admitted.get(proposal_id)
            if already_admitted is not None:
                return already_admitted

            proposal = self._staged.get(proposal_id)
            if proposal is None:
                raise StructuralMemoryRefused("unknown or unavailable structural-memory proposal")
            current = self._active.get(proposal.spec.memory_id)
            current_revision = 0 if current is None else current.spec.revision
            if expected != current_revision:
                raise StructuralMemoryConflict(
                    f"active revision is {current_revision}; caller expected {expected}"
                )
            expected_parent = None if current is None else current.spec.digest
            if (
                proposal.spec.revision != current_revision + 1
                or proposal.spec.parent_digest != expected_parent
            ):
                raise StructuralMemoryConflict("proposal parent or revision is stale")

            self.verifier.verify_proposal(proposal)
            if self.admission_policy is None:
                raise StructuralMemoryAuthorizationError(
                    "admission requires an explicit trusted host-supplied admission_policy"
                )
            try:
                authorized = self.admission_policy(proposal)
            except Exception as exc:
                raise StructuralMemoryAuthorizationError(f"host admission policy failed: {exc}") from exc
            if authorized is not True:
                raise StructuralMemoryAuthorizationError("host admission policy did not return literal True")

            version = StructuralMemoryVersion(
                spec=proposal.spec,
                certificate=proposal.certificate,
                admitted_proposal_id=proposal.proposal_id,
            )
            event_payload = {
                **self._proposal_event_payload(proposal),
                "expected_revision": expected,
            }
            self._append_journal("structural_memory.admit", event_payload)
            self._active[proposal.spec.memory_id] = version
            self._admitted[proposal_id] = version
            return version

    def read(
        self,
        memory_id: str,
        coordinate: int,
        *,
        context: Mapping[str, Any] | None = None,
    ) -> StructuralMemoryReadReceipt:
        """Read the active revision with value and evidence provenance. Mathematics: resolve the active version v and return its guarded value G_v(t)."""
        _require_nonempty_string(memory_id, "memory_id")
        _require_int(coordinate, "coordinate", minimum=0)
        with self._lock:
            version = self._active.get(memory_id)
            if version is None:
                raise StructuralMemoryRefused(f"memory {memory_id!r} has no admitted version")
            return self._read_version(
                version,
                coordinate,
                context=context,
                event_kind="structural_memory.read",
            )

    def read_revision(
        self,
        memory_id: str,
        revision: int,
        coordinate: int,
        *,
        context: Mapping[str, Any] | None = None,
    ) -> StructuralMemoryReadReceipt:
        """Read one explicitly selected admitted revision, including historical versions.

        Mathematics: resolve the unique admitted v with
        (v.memory_id, v.revision)=(memory_id, revision), then evaluate its
        guarded generator under that revision's exact context.
        """
        _require_nonempty_string(memory_id, "memory_id")
        _require_int(revision, "revision", minimum=1)
        _require_int(coordinate, "coordinate", minimum=0)
        with self._lock:
            version = self._version_for_revision(memory_id, revision)
            if version is None:
                raise StructuralMemoryRefused(
                    f"memory {memory_id!r} has no admitted revision {revision}"
                )
            return self._read_version(
                version,
                coordinate,
                context=context,
                event_kind="structural_memory.read_revision",
            )

    def read_revision_range(
        self,
        memory_id: str,
        revision: int,
        coordinate_start: int,
        count: int,
        *,
        context: Mapping[str, Any] | None = None,
    ) -> tuple[tuple[int, ...], StructuralMemoryRangeReadReceipt, tuple[str, ...]]:
        """Read one bounded revision-pinned range with one journal transition. Mathematics: evaluate G[a:a+n], emit H(values), H(ordered value-receipt IDs), and bind both to the exact spec/certificate/context."""
        _require_nonempty_string(memory_id, "memory_id")
        _require_int(revision, "revision", minimum=1)
        _require_int(coordinate_start, "coordinate_start", minimum=0)
        _require_int(count, "count", minimum=1)
        if count > 65_536:
            raise StructuralMemoryRefused("one structural range read cannot exceed 65536 coordinates")
        with self._lock:
            version = self._version_for_revision(memory_id, revision)
            if version is None:
                raise StructuralMemoryRefused(
                    f"memory {memory_id!r} has no admitted revision {revision}"
                )
            context_digest = self.navigator.validate(
                version.spec,
                version.certificate,
                coordinate_start,
                context=context,
            )
            # Prefix admissibility is monotone in the coordinate, so validating
            # the last coordinate proves that the entire ascending interval
            # remains strictly inside the same exclusive horizon.
            self.navigator.validate(
                version.spec,
                version.certificate,
                coordinate_start + count - 1,
                context=context,
            )
            values = self.generators.navigate_guarded_range(
                version.spec,
                coordinate_start,
                count,
            )
            value_receipt_ids = self._make_range_value_receipt_ids(
                version,
                coordinate_start,
                context_digest,
                values,
            )
            receipt = self._make_range_read_receipt(
                version,
                coordinate_start,
                context_digest,
                values,
                value_receipt_ids,
            )
            self._append_journal(
                "structural_memory.read_revision_range",
                {"receipt": receipt.to_dict()},
            )
            return values, receipt, value_receipt_ids

    def _read_version(
        self,
        version: StructuralMemoryVersion,
        coordinate: int,
        *,
        context: Mapping[str, Any] | None,
        event_kind: str,
    ) -> StructuralMemoryReadReceipt:
        """Evaluate one immutable version and journal the exact active or pinned read mode.

        Mathematics: for admitted version v and coordinate t, validate its
        exact context, then return the guarded generator value G_v(t) with a
        receipt whose provenance is bound to v and t.
        """
        context_digest = self.navigator.validate(
            version.spec,
            version.certificate,
            coordinate,
            context=context,
        )
        cache_key = (
            version.spec.digest,
            version.certificate.digest,
            context_digest,
            coordinate,
        )
        cached = self._read_cache.get(cache_key)
        if cached is not None:
            receipt = replace(cached, cache_hit=True)
            self._append_journal(event_kind, {"receipt": receipt.to_dict()})
            return receipt

        value = self.generators.navigate_guarded(version.spec, coordinate)
        receipt = self._make_read_receipt(version, coordinate, context_digest, value)
        self._append_journal(event_kind, {"receipt": receipt.to_dict()})
        self._read_cache[cache_key] = receipt
        return receipt

    def version_for_revision(self, memory_id: str, revision: int) -> StructuralMemoryVersion:
        """Return one exact immutable admitted revision without performing a read.

        Mathematics: resolve the unique admitted v with
        (v.memory_id, v.revision)=(memory_id, revision), under the registry lock.
        """
        _require_nonempty_string(memory_id, "memory_id")
        _require_int(revision, "revision", minimum=1)
        with self._lock:
            version = self._version_for_revision(memory_id, revision)
            if version is None:
                raise StructuralMemoryRefused(
                    f"memory {memory_id!r} has no admitted revision {revision}"
                )
            return version

    def admitted_versions(
        self,
        memory_id: str | None = None,
    ) -> tuple[StructuralMemoryVersion, ...]:
        """List immutable admitted revisions in stable identity order without performing reads.

        Mathematics: project the admitted relation A onto unique versions v and
        return sort_{memory_id,revision,digest}(A), optionally restricted to
        one memory identity. Staged proposals are excluded.
        """
        if memory_id is not None:
            _require_nonempty_string(memory_id, "memory_id")
        with self._lock:
            unique = {
                (
                    version.spec.memory_id,
                    version.spec.revision,
                    version.spec.digest,
                    version.certificate.digest,
                ): version
                for version in self._admitted.values()
                if memory_id is None or version.spec.memory_id == memory_id
            }
            return tuple(
                unique[key]
                for key in sorted(unique)
            )

    def active_version(self, memory_id: str) -> StructuralMemoryVersion | None:
        """Return the currently admitted immutable version, if one exists. Mathematics: projects the active registry mapping at memory identity m, or the empty value when absent."""
        _require_nonempty_string(memory_id, "memory_id")
        with self._lock:
            return self._active.get(memory_id)

    def staged_proposal(self, proposal_id: str) -> StructuralMemoryProposal | None:
        """Return one staged immutable proposal without changing its status. Mathematics: projects the staged-proposal mapping at proposal digest p, or the empty value when absent."""
        _require_hash(proposal_id, "proposal_id")
        with self._lock:
            return self._staged.get(proposal_id)

    def snapshot(
        self,
        *,
        journal_snapshot: Sequence[Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Serialize the complete structural-memory registry. Mathematics: emit a canonical state projection whose journal anchor equals the same captured OS journal cut."""
        with self._lock:
            anchor = None
            if self.journal is None:
                if journal_snapshot is not None:
                    raise StructuralMemoryError("journal snapshot was supplied to a registry without a journal")
            else:
                current_journal = self.journal.snapshot()
                selected_journal = current_journal if journal_snapshot is None else _json_value(
                    journal_snapshot, "journal_snapshot"
                )
                if selected_journal != current_journal:
                    raise StructuralMemoryError(
                        "event journal changed during the composite structural-memory checkpoint"
                    )
                anchor = self._journal_anchor(selected_journal)

            return {
                "schema": STRUCTURAL_MEMORY_REGISTRY_SCHEMA,
                "proposals": [
                    self._staged[key].to_dict()
                    for key in sorted(self._staged)
                ],
                "admitted": sorted(self._admitted),
                "active": {
                    memory_id: version.admitted_proposal_id
                    for memory_id, version in sorted(self._active.items())
                },
                "read_cache": [
                    receipt.to_dict()
                    for _, receipt in sorted(self._read_cache.items())
                ],
                "journal_anchor": anchor,
            }

    @classmethod
    def from_snapshot(
        cls,
        payload: Mapping[str, Any],
        *,
        admission_policy: Callable[[StructuralMemoryProposal], bool] | None = None,
        generators: GeneratorRegistry | None = None,
        journal: EventJournal | None = None,
    ) -> "StructuralMemoryRegistry":
        """Restore and validate the complete registry against its event journal. Mathematics: reconstruct R from immutable proposals, admissions and receipts, then require their identities to match the journal hash-chain cut."""
        expected = {"schema", "proposals", "admitted", "active", "read_cache", "journal_anchor"}
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise StructuralMemoryError("structural memory registry snapshot fields are invalid")
        if payload["schema"] != STRUCTURAL_MEMORY_REGISTRY_SCHEMA:
            raise StructuralMemoryError("unsupported structural memory registry snapshot schema")
        if not isinstance(payload["proposals"], (list, tuple)):
            raise StructuralMemoryError("structural memory proposals must be a sequence")
        if not isinstance(payload["admitted"], (list, tuple)):
            raise StructuralMemoryError("structural memory admissions must be a sequence")
        if not isinstance(payload["active"], Mapping):
            raise StructuralMemoryError("structural memory active heads must be an object")
        if not isinstance(payload["read_cache"], (list, tuple)):
            raise StructuralMemoryError("structural memory read cache must be a sequence")

        registry = cls(
            admission_policy=admission_policy,
            generators=generators,
            journal=journal,
        )
        for raw_proposal in payload["proposals"]:
            proposal = StructuralMemoryProposal.from_dict(raw_proposal)
            if proposal.proposal_id in registry._staged:
                raise StructuralMemoryError("duplicate structural memory proposal identity")
            registry.verifier.verify_proposal(proposal)
            registry._staged[proposal.proposal_id] = proposal

        admitted_ids: list[str] = []
        for raw_id in payload["admitted"]:
            _require_hash(raw_id, "admitted proposal ID")
            if raw_id in admitted_ids:
                raise StructuralMemoryError("duplicate structural memory admission identity")
            if raw_id not in registry._staged:
                raise StructuralMemoryError("admitted proposal is missing from the staged proposal set")
            admitted_ids.append(raw_id)
            proposal = registry._staged[raw_id]
            registry._admitted[raw_id] = StructuralMemoryVersion(
                spec=proposal.spec,
                certificate=proposal.certificate,
                admitted_proposal_id=raw_id,
            )

        history: dict[str, list[StructuralMemoryVersion]] = {}
        for version in registry._admitted.values():
            history.setdefault(version.spec.memory_id, []).append(version)
        for memory_id, versions in history.items():
            versions.sort(key=lambda item: item.spec.revision)
            for index, version in enumerate(versions, start=1):
                if version.spec.revision != index:
                    raise StructuralMemoryError(
                        f"structural memory {memory_id!r} has a gap in admitted revision history"
                    )
                expected_parent = None if index == 1 else versions[index - 2].spec.digest
                if version.spec.parent_digest != expected_parent:
                    raise StructuralMemoryError(
                        f"structural memory {memory_id!r} has broken revision parent lineage"
                    )

        for memory_id, proposal_id in payload["active"].items():
            _require_nonempty_string(memory_id, "active memory ID")
            _require_hash(proposal_id, "active proposal ID")
            version = registry._admitted.get(proposal_id)
            if version is None or version.spec.memory_id != memory_id:
                raise StructuralMemoryError("active structural memory head does not reference an admitted version")
            latest = max(
                (item for item in history[memory_id]),
                key=lambda item: item.spec.revision,
            )
            if version != latest:
                raise StructuralMemoryError("active structural memory head is not the newest admitted revision")
            registry._active[memory_id] = version
        if set(registry._active) != set(history):
            raise StructuralMemoryError("admitted structural memories and active heads do not correspond")

        for raw_receipt in payload["read_cache"]:
            receipt = StructuralMemoryReadReceipt.from_dict(raw_receipt)
            if receipt.cache_hit:
                raise StructuralMemoryError("stored structural memory cache entries must be canonical miss receipts")
            version = registry._version_for_spec_digest(receipt.spec_digest)
            if version is None:
                raise StructuralMemoryError("cached structural read references an unknown revision")
            registry._verify_read_receipt(receipt, version)
            key = (
                receipt.spec_digest,
                receipt.certificate_digest,
                receipt.context_digest,
                receipt.coordinate,
            )
            if key in registry._read_cache:
                raise StructuralMemoryError("duplicate structural memory cache identity")
            registry._read_cache[key] = receipt

        raw_anchor = payload["journal_anchor"]
        if journal is None:
            if raw_anchor is not None:
                raise StructuralMemoryError("registry snapshot has a journal anchor but no journal was supplied")
        else:
            if not isinstance(raw_anchor, Mapping) or set(raw_anchor) != {"sequence", "digest"}:
                raise StructuralMemoryError("structural memory journal anchor is invalid")
            sequence = _require_int(raw_anchor["sequence"], "journal anchor sequence", minimum=0)
            digest = _require_hash(raw_anchor["digest"], "journal anchor digest")
            if registry._journal_anchor(journal.snapshot()) != {"sequence": sequence, "digest": digest}:
                raise StructuralMemoryError("structural memory journal anchor does not match the restored OS journal")
            registry._verify_journal()
        return registry

    @staticmethod
    def assert_legacy_snapshot_compatible(journal: EventJournal) -> None:
        """Permit pre-E0.2 checkpoints only when their journal has no structural-memory events. Mathematics: require the structural-memory event projection of legacy journal J to be empty."""
        if any(record.kind.startswith("structural_memory.") for record in journal.records()):
            raise StructuralMemoryError(
                "checkpoint journal contains structural-memory events but has no structural-memory registry state"
            )

    def _append_journal(self, kind: str, payload: dict[str, Any]) -> None:
        """Append one registry transition to the shared OS event chain. Mathematics: extend J with a typed structural-memory event before publishing its corresponding registry mutation."""
        if self.journal is not None:
            self.journal.append(kind, payload)

    @staticmethod
    def _proposal_event_payload(proposal: StructuralMemoryProposal) -> dict[str, Any]:
        """Project a proposal identity onto its journal event fields. Mathematics: bind proposal ID, memory revision, spec digest and certificate digest in one event payload."""
        return {
            "proposal_id": proposal.proposal_id,
            "memory_id": proposal.spec.memory_id,
            "revision": proposal.spec.revision,
            "spec_digest": proposal.spec.digest,
            "certificate_digest": proposal.certificate.digest,
        }

    @staticmethod
    def _journal_anchor(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        """Return the exact sequence and terminal hash of one captured journal. Mathematics: anchor J by (|J|, H_|J|), using zero digest for the empty chain."""
        if not isinstance(records, (list, tuple)):
            raise StructuralMemoryError("journal snapshot must be a sequence")
        if not records:
            return {"sequence": 0, "digest": "0" * 64}
        final = records[-1]
        if not isinstance(final, Mapping):
            raise StructuralMemoryError("journal snapshot record must be an object")
        return {
            "sequence": len(records),
            "digest": _require_hash(final.get("digest"), "journal terminal digest"),
        }

    @staticmethod
    def _make_read_receipt(
        version: StructuralMemoryVersion,
        coordinate: int,
        context_digest: str,
        value: int,
        *,
        cache_hit: bool = False,
    ) -> StructuralMemoryReadReceipt:
        """Bind one generated value to its revision and evidence. Mathematics: derive receipt ID from H(spec), H(certificate), context, coordinate and H(value)."""
        value_digest = _digest({"type": "integer", "value": value})
        receipt_id = _digest({
            "memory_id": version.spec.memory_id,
            "revision": version.spec.revision,
            "spec_digest": version.spec.digest,
            "certificate_digest": version.certificate.digest,
            "coordinate": coordinate,
            "context_digest": context_digest,
            "value_digest": value_digest,
        })
        return StructuralMemoryReadReceipt(
            receipt_id=receipt_id,
            memory_id=version.spec.memory_id,
            revision=version.spec.revision,
            spec_digest=version.spec.digest,
            certificate_digest=version.certificate.digest,
            coordinate=coordinate,
            context_digest=context_digest,
            value=value,
            value_digest=value_digest,
            verification_class=version.certificate.verification_class,
            witness_digest=version.certificate.witness_digest,
            cache_hit=cache_hit,
        )

    @staticmethod
    def _make_range_value_receipt_ids(
        version: StructuralMemoryVersion,
        coordinate_start: int,
        context_digest: str,
        values: Sequence[int],
    ) -> tuple[str, ...]:
        """Mathematics: derive exactly the same H(spec, certificate, context, coordinate, value) point identities using pre-encoded immutable fields and no transient receipt objects."""
        # _make_read_receipt hashes two canonical JSON objects for each point.
        # In a range, all provenance fields except coordinate/value are fixed;
        # encode those once and preserve the exact sorted-key JSON byte schema.
        quote = lambda value: _canonical_json(value).encode("utf-8")
        certificate_digest = quote(version.certificate.digest)
        bound_context_digest = quote(context_digest)
        memory_id = quote(version.spec.memory_id)
        revision = str(version.spec.revision).encode("ascii")
        spec_digest = quote(version.spec.digest)
        prefix = (
            b'{"certificate_digest":' + certificate_digest
            + b',"context_digest":' + bound_context_digest
            + b',"coordinate":'
        )
        middle = (
            b',"memory_id":' + memory_id
            + b',"revision":' + revision
            + b',"spec_digest":' + spec_digest
            + b',"value_digest":'
        )
        result: list[str] = []
        for offset, value in enumerate(values):
            if type(value) is not int:
                raise StructuralMemoryError("range receipt values must be strict integers")
            value_digest = hashlib.sha256(
                b'{"type":"integer","value":' + str(value).encode("ascii") + b"}"
            ).hexdigest()
            payload = (
                prefix
                + str(coordinate_start + offset).encode("ascii")
                + middle
                + quote(value_digest)
                + b"}"
            )
            result.append(hashlib.sha256(payload).hexdigest())
        return tuple(result)

    @staticmethod
    def _make_range_read_receipt(
        version: StructuralMemoryVersion,
        coordinate_start: int,
        context_digest: str,
        values: Sequence[int],
        value_receipt_ids: Sequence[str],
    ) -> StructuralMemoryRangeReadReceipt:
        """Mathematics: commit ordered values and per-coordinate receipt identities as one range digest without one journal record per value."""
        value_range_digest = _digest({
            "type": "integer-range",
            "coordinate_start": coordinate_start,
            "values": list(values),
        })
        value_receipt_digest = _digest({
            "coordinate_start": coordinate_start,
            "receipt_ids": list(value_receipt_ids),
        })
        receipt_payload = {
            "memory_id": version.spec.memory_id,
            "revision": version.spec.revision,
            "spec_digest": version.spec.digest,
            "certificate_digest": version.certificate.digest,
            "coordinate_start": coordinate_start,
            "length": len(values),
            "context_digest": context_digest,
            "value_range_digest": value_range_digest,
            "value_receipt_digest": value_receipt_digest,
            "verification_class": version.certificate.verification_class.value,
            "witness_digest": version.certificate.witness_digest,
        }
        return StructuralMemoryRangeReadReceipt(
            receipt_id=_digest(receipt_payload),
            memory_id=version.spec.memory_id,
            revision=version.spec.revision,
            spec_digest=version.spec.digest,
            certificate_digest=version.certificate.digest,
            coordinate_start=coordinate_start,
            length=len(values),
            context_digest=context_digest,
            value_range_digest=value_range_digest,
            value_receipt_digest=value_receipt_digest,
            verification_class=version.certificate.verification_class,
            witness_digest=version.certificate.witness_digest,
        )

    def _verify_range_read_receipt(
        self,
        receipt: StructuralMemoryRangeReadReceipt,
        version: StructuralMemoryVersion,
    ) -> None:
        """Replay a compact range commitment against its admitted generator. Mathematics: regenerate every coordinate and require exact equality of the ordered value and per-coordinate receipt commitments."""
        if (
            receipt.memory_id != version.spec.memory_id
            or receipt.revision != version.spec.revision
            or receipt.spec_digest != version.spec.digest
            or receipt.certificate_digest != version.certificate.digest
            or receipt.context_digest != version.spec.context_digest
            or receipt.verification_class is not version.certificate.verification_class
            or receipt.witness_digest != version.certificate.witness_digest
        ):
            raise StructuralMemoryError("structural range receipt provenance does not match its admitted version")
        self.navigator.validate(
            version.spec,
            version.certificate,
            receipt.coordinate_start,
            context=version.spec.context,
        )
        self.navigator.validate(
            version.spec,
            version.certificate,
            receipt.coordinate_start + receipt.length - 1,
            context=version.spec.context,
        )
        values = self.generators.navigate_guarded_range(
            version.spec,
            receipt.coordinate_start,
            receipt.length,
        )
        value_receipt_ids = self._make_range_value_receipt_ids(
            version,
            receipt.coordinate_start,
            receipt.context_digest,
            values,
        )
        expected = self._make_range_read_receipt(
            version,
            receipt.coordinate_start,
            receipt.context_digest,
            values,
            value_receipt_ids,
        )
        if expected.to_dict() != receipt.to_dict():
            raise StructuralMemoryError("structural range receipt does not reproduce from its generator")

    def _version_for_revision(self, memory_id: str, revision: int) -> StructuralMemoryVersion | None:
        """Resolve one exact historical revision. Mathematics: find the unique admitted v with (v.memory_id,v.revision)=(m,r)."""
        matches = [
            version for version in self._admitted.values()
            if version.spec.memory_id == memory_id and version.spec.revision == revision
        ]
        if len(matches) > 1:
            raise StructuralMemoryError("multiple admitted versions share one memory revision")
        return matches[0] if matches else None

    def _version_for_spec_digest(self, spec_digest: str) -> StructuralMemoryVersion | None:
        """Resolve one historical immutable version by spec identity. Mathematics: find the unique admitted revision v with H(v.spec)=spec_digest."""
        matches = [
            version for version in self._admitted.values()
            if version.spec.digest == spec_digest
        ]
        if len(matches) > 1:
            raise StructuralMemoryError("multiple admitted versions share one structural spec digest")
        return matches[0] if matches else None

    def _verify_read_receipt(
        self,
        receipt: StructuralMemoryReadReceipt,
        version: StructuralMemoryVersion,
    ) -> None:
        """Recompute a receipt against its historical generator and certificate. Mathematics: require observed_value = G(coordinate) and receipt_id = H(all bound provenance)."""
        if (
            receipt.memory_id != version.spec.memory_id
            or receipt.revision != version.spec.revision
            or receipt.spec_digest != version.spec.digest
            or receipt.certificate_digest != version.certificate.digest
            or receipt.context_digest != version.spec.context_digest
            or receipt.verification_class is not version.certificate.verification_class
            or receipt.witness_digest != version.certificate.witness_digest
        ):
            raise StructuralMemoryError("structural read receipt provenance does not match its admitted version")
        try:
            self.navigator.validate(
                version.spec,
                version.certificate,
                receipt.coordinate,
                context=version.spec.context,
            )
            expected_value = self.generators.navigate_guarded(version.spec, receipt.coordinate)
        except StructuralMemoryError:
            raise
        except Exception as exc:
            raise StructuralMemoryError(f"structural read receipt cannot be replayed: {exc}") from exc
        expected = self._make_read_receipt(
            version,
            receipt.coordinate,
            receipt.context_digest,
            expected_value,
            cache_hit=receipt.cache_hit,
        )
        if expected.to_dict() != receipt.to_dict():
            raise StructuralMemoryError("structural read receipt does not reproduce from its generator")

    def _verify_journal(self) -> None:
        """Reconcile structural-memory journal events with restored state. Mathematics: enforce proposal-before-admission, parent-admission-before-child-proposal, and admission/read order for each revision."""
        if self.journal is None:
            return
        proposed_events: dict[str, tuple[int, dict[str, Any]]] = {}
        admitted_events: dict[str, tuple[int, dict[str, Any]]] = {}
        read_receipts: list[tuple[int, StructuralMemoryReadReceipt, bool]] = []
        range_read_receipts: list[tuple[int, StructuralMemoryRangeReadReceipt]] = []
        for record in self.journal.records():
            if not record.kind.startswith("structural_memory."):
                continue
            if record.kind == "structural_memory.propose":
                payload = record.payload
                proposal_id = payload.get("proposal_id")
                _require_hash(proposal_id, "journal proposal_id")
                if proposal_id in proposed_events:
                    raise StructuralMemoryError("duplicate structural-memory proposal journal event")
                proposed_events[proposal_id] = (record.sequence, payload)
            elif record.kind == "structural_memory.admit":
                payload = record.payload
                proposal_id = payload.get("proposal_id")
                _require_hash(proposal_id, "journal admission proposal_id")
                if proposal_id in admitted_events:
                    raise StructuralMemoryError("duplicate structural-memory admission journal event")
                admitted_events[proposal_id] = (record.sequence, payload)
            elif record.kind in {"structural_memory.read", "structural_memory.read_revision"}:
                payload = record.payload
                if set(payload) != {"receipt"}:
                    raise StructuralMemoryError("structural-memory read event payload is invalid")
                read_receipts.append((
                    record.sequence,
                    StructuralMemoryReadReceipt.from_dict(payload["receipt"]),
                    record.kind == "structural_memory.read_revision",
                ))
            elif record.kind == "structural_memory.read_revision_range":
                payload = record.payload
                if set(payload) != {"receipt"}:
                    raise StructuralMemoryError("structural-memory range-read event payload is invalid")
                range_read_receipts.append((
                    record.sequence,
                    StructuralMemoryRangeReadReceipt.from_dict(payload["receipt"]),
                ))
            else:
                raise StructuralMemoryError(f"unknown structural-memory journal event {record.kind!r}")

        if set(proposed_events) != set(self._staged):
            raise StructuralMemoryError("structural-memory proposal journal and registry state differ")
        if set(admitted_events) != set(self._admitted):
            raise StructuralMemoryError("structural-memory admission journal and registry history differ")

        for proposal_id, proposal in self._staged.items():
            proposal_sequence, payload = proposed_events[proposal_id]
            if payload != self._proposal_event_payload(proposal):
                raise StructuralMemoryError("structural-memory proposal journal payload mismatch")

            parent_digest = proposal.spec.parent_digest
            if parent_digest is None:
                if proposal.spec.revision != 1:
                    raise StructuralMemoryError("root structural-memory proposal has a non-root revision")
            else:
                parent = self._version_for_spec_digest(parent_digest)
                if parent is None:
                    raise StructuralMemoryError("structural-memory proposal parent is not an admitted revision")
                if (
                    parent.spec.memory_id != proposal.spec.memory_id
                    or proposal.spec.revision != parent.spec.revision + 1
                ):
                    raise StructuralMemoryError("structural-memory proposal revision does not immediately extend its parent")
                parent_sequence = admitted_events.get(parent.admitted_proposal_id, (0, {}))[0]
                if proposal_sequence <= parent_sequence:
                    raise StructuralMemoryError("structural-memory child proposal precedes parent admission")

            admitted = admitted_events.get(proposal_id)
            if admitted is not None and admitted[0] <= proposal_sequence:
                raise StructuralMemoryError("structural-memory admission precedes its proposal event")

        for proposal_id, version in self._admitted.items():
            _, payload = admitted_events[proposal_id]
            expected = {
                **self._proposal_event_payload(self._staged[proposal_id]),
                "expected_revision": version.spec.revision - 1,
            }
            if payload != expected:
                raise StructuralMemoryError("structural-memory admission journal payload mismatch")

        admission_by_spec = {
            version.spec.digest: admitted_events[proposal_id][0]
            for proposal_id, version in self._admitted.items()
        }
        revisions_by_memory: dict[str, list[StructuralMemoryVersion]] = {}
        for version in self._admitted.values():
            revisions_by_memory.setdefault(version.spec.memory_id, []).append(version)
        for versions in revisions_by_memory.values():
            versions.sort(key=lambda item: item.spec.revision)

        for sequence, receipt, pinned_revision in read_receipts:
            version = self._version_for_spec_digest(receipt.spec_digest)
            if version is None:
                raise StructuralMemoryError("structural-memory read journal references an unknown revision")
            admission_sequence = admission_by_spec[receipt.spec_digest]
            if sequence <= admission_sequence:
                raise StructuralMemoryError("structural-memory read precedes revision admission")
            if not pinned_revision:
                later_versions = [
                    item for item in revisions_by_memory[version.spec.memory_id]
                    if item.spec.revision > version.spec.revision
                ]
                if later_versions:
                    next_admission_sequence = admission_by_spec[later_versions[0].spec.digest]
                    if sequence >= next_admission_sequence:
                        raise StructuralMemoryError("structural-memory read occurs after a newer revision became active")
            self._verify_read_receipt(receipt, version)

        for sequence, receipt in range_read_receipts:
            version = self._version_for_spec_digest(receipt.spec_digest)
            if version is None:
                raise StructuralMemoryError("structural-memory range journal references an unknown revision")
            admission_sequence = admission_by_spec[receipt.spec_digest]
            if sequence <= admission_sequence:
                raise StructuralMemoryError("structural-memory range read precedes revision admission")
            self._verify_range_read_receipt(receipt, version)

    @staticmethod
    def _normalize_witnesses(witnesses: Mapping[int, int]) -> tuple[tuple[int, int], ...]:
        """Detach, validate, and coordinate-sort an integer witness mapping. Mathematics: validates and sorts a finite set of unique integer coordinate/value pairs."""
        if not isinstance(witnesses, Mapping):
            raise StructuralMemoryError("witnesses must map integer coordinates to integer observations")
        normalized: list[tuple[int, int]] = []
        for coordinate, observed in witnesses.items():
            _require_int(coordinate, "witness coordinate", minimum=0)
            _require_int(observed, f"witness at coordinate {coordinate}")
            normalized.append((coordinate, observed))
        normalized.sort()
        if len(normalized) < 2:
            raise StructuralMemoryRefused("at least two independent witness coordinates are required")
        return tuple(normalized)

    @staticmethod
    def _normalize_samples(samples: Sequence[int], name: str) -> list[int]:
        """Detach and strictly validate one observed integer sequence. Mathematics: maps a finite sequence to an integer vector while excluding Boolean coordinates."""
        if isinstance(samples, (str, bytes)) or not isinstance(samples, Sequence):
            raise StructuralMemoryError(f"{name} must be a sequence of integers")
        result = list(samples)
        for index, value in enumerate(result):
            _require_int(value, f"{name}[{index}]")
        return result
