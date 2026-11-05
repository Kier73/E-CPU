"""Verified, versioned structural memories over MailCPU's deterministic law algebra.

This E0 service stores compact generators rather than materialized traces. It
admits only a fixed set of existing deterministic law families, binds every
version to an exact context and witness digest, and uses guarded navigation for
all runtime reads. A GROUND verdict means agreement with the supplied witness
set; it is not a proof over an infinite domain.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
import hashlib
import json
import threading
from typing import Any, Callable, Mapping, Sequence

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
    """Return a detached JSON value and reject opaque or non-string-keyed data."""
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
    """Encode a JSON-compatible value in one canonical sorted compact form."""
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
    """Calculate SHA-256 over the canonical JSON encoding of a value."""
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _require_int(value: Any, name: str, *, minimum: int | None = None) -> int:
    """Validate one strict integer field, excluding Booleans."""
    if type(value) is not int:
        raise StructuralMemoryError(f"{name} must be an integer (booleans are not coordinates)")
    if minimum is not None and value < minimum:
        raise StructuralMemoryError(f"{name} must be at least {minimum}")
    return value


def _require_nonempty_string(value: Any, name: str, *, maximum: int = 256) -> str:
    """Validate one bounded non-empty text identifier."""
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise StructuralMemoryError(f"{name} must be a non-empty string of at most {maximum} characters")
    return value


def _require_hash(value: Any, name: str) -> str:
    """Validate one lowercase SHA-256 hexadecimal digest."""
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise StructuralMemoryError(f"{name} must be a lowercase SHA-256 hex digest")
    return value


def _validate_law_parameters(family: str, params: Mapping[str, Any], order: int) -> None:
    """Validate the exact parameter ABI for each admitted generator family."""
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
                f"law verdict {self.law_verdict!r} is not admissible; FITTED and TAPE remain proposals only"
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
        """Create a schema-checked immutable spec from an existing Law object."""
        if not isinstance(law, Law):
            raise StructuralMemoryError("law must be an existing mailcpu.law_certifier.Law")
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
        """Return a detached copy of the generator parameters."""
        return json.loads(self.parameters_json)

    @property
    def context(self) -> dict[str, Any]:
        """Return a detached copy of the context boundary metadata."""
        return json.loads(self.context_json)

    @property
    def context_digest(self) -> str:
        """Return the SHA-256 digest of the exact canonical context."""
        return hashlib.sha256(self.context_json.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        """Serialize this immutable structural-memory record."""
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
        """Return the stable digest of this immutable record."""
        return _digest(self.to_dict())


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
        """Serialize this immutable structural-memory record."""
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
        """Return the stable digest of this immutable certificate."""
        return _digest(self.to_dict())


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
        """Serialize this immutable structural-memory record."""
        return {
            "proposal_id": self.proposal_id,
            "spec": self.spec.to_dict(),
            "certificate": self.certificate.to_dict(),
            "witnesses": [[coordinate, observed] for coordinate, observed in self.witnesses],
        }


@dataclass(frozen=True)
class StructuralMemoryVersion:
    """One admitted immutable revision and its originating proposal identity."""

    spec: StructuralMemorySpec
    certificate: StructuralMemoryCertificate
    admitted_proposal_id: str

    def to_dict(self) -> dict[str, Any]:
        """Serialize this immutable structural-memory record."""
        return {
            "spec": self.spec.to_dict(),
            "certificate": self.certificate.to_dict(),
            "admitted_proposal_id": self.admitted_proposal_id,
        }


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

    def to_dict(self) -> dict[str, Any]:
        """Serialize this immutable structural-memory record."""
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


class ContextMapper:
    """Canonicalize and bind an explicit context object without changing its law.

    E0 treats context as an exact boundary identity. Context-to-parameter
    adaptation is intentionally deferred; a changed context requires a new
    immutable proposal and revision.
    """

    def encode(self, context: Mapping[str, Any] | None) -> tuple[str, str]:
        """Return canonical context JSON and its SHA-256 identity."""
        value = {} if context is None else _json_value(context, "context")
        if not isinstance(value, dict):
            raise StructuralMemoryError("context must be a JSON object")
        encoded = _canonical_json(value)
        return encoded, hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def bind(self, spec: StructuralMemorySpec, context: Mapping[str, Any] | None) -> str:
        """Require a read context to equal the exact context bound into the spec."""
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
        """Reconstruct one whitelisted Law from canonical spec parameters."""
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
        """Evaluate one coordinate through the law certifier's horizon guard."""
        law = self.build_law(spec)
        try:
            value = navigate_guarded(law, coordinate)
        except (HorizonExceeded, Refused) as exc:
            raise StructuralMemoryRefused(str(exc)) from exc
        if type(value) is not int:
            raise StructuralMemoryRefused("generator returned a non-integer value outside the E0 value ABI")
        return value

    def predict_prefix_boundary(self, spec: StructuralMemorySpec, coordinate: int) -> int:
        """Evaluate exactly first_bad for witness adjudication, never for runtime reads."""
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
        """Issue a certificate only after deterministic witness replay succeeds."""
        if len(witnesses) < 2:
            raise StructuralMemoryRefused("at least two independent witness coordinates are required")
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
        """Recompute a staged proposal certificate from its immutable witnesses."""
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
        """Validate certificate, context, coordinate, and horizon before any cache lookup."""
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
        """Return a guarded state value and its verified context digest."""
        context_digest = self.validate(spec, certificate, coordinate, context)
        return self.generators.navigate_guarded(spec, coordinate), context_digest


class StructuralMemoryRegistry:
    """Stage, authorize, admit, and read immutable structural-memory revisions.

    A caller may propose a candidate, but proposals do not alter active state.
    Admission requires both compare-and-swap against the expected active revision
    and a trusted host-supplied admission policy returning the literal value True.
    """

    def __init__(
        self,
        *,
        admission_policy: Callable[[StructuralMemoryProposal], bool] | None = None,
        generators: GeneratorRegistry | None = None,
    ) -> None:
        self.generators = generators or GeneratorRegistry()
        self.context_mapper = ContextMapper()
        self.verifier = StructuralMemoryVerifier(self.generators)
        self.navigator = StructuralNavigator(self.generators, self.context_mapper)
        self.admission_policy = admission_policy
        self._active: dict[str, StructuralMemoryVersion] = {}
        self._staged: dict[str, StructuralMemoryProposal] = {}
        self._admitted: dict[str, StructuralMemoryVersion] = {}
        self._read_cache: dict[tuple[str, str, str, int], StructuralMemoryReadReceipt] = {}
        self._lock = threading.RLock()

    def propose(
        self,
        memory_id: str,
        law: Law,
        witnesses: Mapping[int, int],
        *,
        domain: str = "integer-orbit",
        context: Mapping[str, Any] | None = None,
    ) -> StructuralMemoryProposal:
        """Stage a candidate law with independently replayed observations."""
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
        """Recover a known law from a training window and withheld witness suffix."""
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
        """Admit one staged proposal after host authorization and revision CAS."""
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
        """Read one state and return its value together with version/evidence provenance."""
        _require_nonempty_string(memory_id, "memory_id")
        _require_int(coordinate, "coordinate", minimum=0)
        with self._lock:
            version = self._active.get(memory_id)
            if version is None:
                raise StructuralMemoryRefused(f"memory {memory_id!r} has no admitted version")
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
                return replace(cached, cache_hit=True)

            value = self.generators.navigate_guarded(version.spec, coordinate)
            value_digest = _digest({"type": "integer", "value": value})
            receipt_id = _digest({
                "memory_id": memory_id,
                "revision": version.spec.revision,
                "spec_digest": version.spec.digest,
                "certificate_digest": version.certificate.digest,
                "coordinate": coordinate,
                "context_digest": context_digest,
                "value_digest": value_digest,
            })
            receipt = StructuralMemoryReadReceipt(
                receipt_id=receipt_id,
                memory_id=memory_id,
                revision=version.spec.revision,
                spec_digest=version.spec.digest,
                certificate_digest=version.certificate.digest,
                coordinate=coordinate,
                context_digest=context_digest,
                value=value,
                value_digest=value_digest,
                verification_class=version.certificate.verification_class,
                witness_digest=version.certificate.witness_digest,
            )
            self._read_cache[cache_key] = receipt
            return receipt

    def active_version(self, memory_id: str) -> StructuralMemoryVersion | None:
        """Return the currently admitted immutable version, if one exists."""
        _require_nonempty_string(memory_id, "memory_id")
        with self._lock:
            return self._active.get(memory_id)

    def staged_proposal(self, proposal_id: str) -> StructuralMemoryProposal | None:
        """Return one staged immutable proposal without changing its status."""
        _require_hash(proposal_id, "proposal_id")
        with self._lock:
            return self._staged.get(proposal_id)

    @staticmethod
    def _normalize_witnesses(witnesses: Mapping[int, int]) -> tuple[tuple[int, int], ...]:
        """Detach, validate, and coordinate-sort an integer witness mapping."""
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
        """Detach and strictly validate one observed integer sequence."""
        if isinstance(samples, (str, bytes)) or not isinstance(samples, Sequence):
            raise StructuralMemoryError(f"{name} must be a sequence of integers")
        result = list(samples)
        for index, value in enumerate(result):
            _require_int(value, f"{name}[{index}]")
        return result
