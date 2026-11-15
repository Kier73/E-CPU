"""GEOMETRY-TRANSIT-002: native E-CPU revision authority for VGI similarity Grounds.

A native StructuralMemoryRegistry *indexes and versions* a complete, bounded
VGI record. The E-CPU recurrence law below only proves the index-coordinate
relation. It NEVER proves the matrix similarity claim, which is independently
checked by VGI on admission and fresh receiver reconstruction.

The host's StructuralMemoryRegistry admission policy controls publication;
network requests cannot insert records or choose a revision.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Mapping

from .law_certifier import Law
from .structural_memory import StructuralMemoryRegistry, StructuralMemoryVersion
from .vgi_similarity_host import (
    MAX_RECORD_BYTES, PinnedSimilarityCatalogue, PinnedSimilarityRecord,
    SimilarityHostError, _reconstruct, _sha,
)

NATIVE_DOMAIN = "vgi-similarity-index"
NATIVE_SCHEMA = "mailcpu.vgi-similarity-native-index.v1"
# This is a deterministic *index-coordinate* recurrence, not a matrix proof.
_INDEX_LAW = {"x0": 0, "step": 1, "mod": 2_147_483_647}
_INDEX_WITNESSES = {0: 0, 1: 1, 2: 2}
_MAX_LABEL = 128


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _strict_positive(value: Any, label: str, *, zero: bool = False) -> int:
    if type(value) is not int or value < (0 if zero else 1):
        raise SimilarityHostError(f"{label} requires a strict nonnegative/positive integer")
    return value


def _label(value: Any, label: str, maximum: int = _MAX_LABEL) -> str:
    if type(value) is not str or not value.strip() or len(value) > maximum:
        raise SimilarityHostError(f"{label} must be bounded nonempty text")
    return value


@dataclass(frozen=True, slots=True)
class NativeSimilarityPin:
    """Trusted host bootstrap pin to one immutable native registry revision."""

    memory_id: str
    revision: int
    spec_digest: str
    certificate_digest: str
    memory_sha256: str
    graph_fingerprint: str

    def __post_init__(self) -> None:
        _label(self.memory_id, "memory_id", 256)
        _strict_positive(self.revision, "revision")
        for key in ("spec_digest", "certificate_digest", "memory_sha256", "graph_fingerprint"):
            _sha(getattr(self, key), key)

    @classmethod
    def from_version(cls, version: StructuralMemoryVersion) -> "NativeSimilarityPin":
        if not isinstance(version, StructuralMemoryVersion):
            raise SimilarityHostError("native pin requires an admitted version")
        context = _verified_context(version)
        return cls(
            version.spec.memory_id, version.spec.revision, version.spec.digest,
            version.certificate.digest, context["memory_sha256"],
            context["graph_fingerprint"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {"memory_id": self.memory_id, "revision": self.revision,
                "spec_digest": self.spec_digest,
                "certificate_digest": self.certificate_digest,
                "memory_sha256": self.memory_sha256,
                "graph_fingerprint": self.graph_fingerprint}


def _verified_context(version: StructuralMemoryVersion) -> dict[str, Any]:
    spec = version.spec
    if (spec.domain != NATIVE_DOMAIN or spec.family != "int"
        or spec.parameters != _INDEX_LAW or spec.order != 1
        or spec.law_verdict != "GROUND" or spec.first_bad is not None):
        raise SimilarityHostError("native version is not a similarity index revision")
    context = spec.context
    if not isinstance(context, dict) or set(context) != {
        "schema", "memory_sha256", "graph_fingerprint", "record", "provenance_label"
    } or context["schema"] != NATIVE_SCHEMA:
        raise SimilarityHostError("native mathematical index context has invalid schema")
    _sha(context["memory_sha256"], "memory_sha256")
    _sha(context["graph_fingerprint"], "graph_fingerprint")
    _label(context["provenance_label"], "provenance_label")
    if not isinstance(context["record"], dict):
        raise SimilarityHostError("native index is missing its exact mathematical record")
    if not 0 < len(_canonical(context["record"])) <= MAX_RECORD_BYTES:
        raise SimilarityHostError("native record exceeds its finite size bound")
    return context


def admit_native_similarity_revision(
    registry: StructuralMemoryRegistry,
    record: bytes,
    *,
    memory_id: str,
    expected_revision: int,
    expected_memory_sha256: str,
    expected_graph_fingerprint: str,
    provenance_label: str,
) -> NativeSimilarityPin:
    """Stage and CAS-admit a VGI record under *existing trusted E-CPU policy*.

    A caller must supply out-of-band identity pins and configure the registry's
    trusted admission_policy independently. A network-submitted claim alone is
    never sufficient. This adapter does not alter that policy.
    """
    if not isinstance(registry, StructuralMemoryRegistry):
        raise SimilarityHostError("requires the receiver's native StructuralMemoryRegistry")
    _label(memory_id, "memory_id", 256)
    _label(provenance_label, "provenance_label")
    _strict_positive(expected_revision, "expected_revision", zero=True)
    _sha(expected_memory_sha256, "expected_memory_sha256")
    _sha(expected_graph_fingerprint, "expected_graph_fingerprint")
    if type(record) is not bytes or not 0 < len(record) <= MAX_RECORD_BYTES:
        raise SimilarityHostError("record must be bounded exact bytes")
    # The VGI mathematical verifier is not E-CPU's index-law verifier.
    admitted = _reconstruct(PinnedSimilarityRecord(
        expected_memory_sha256, expected_graph_fingerprint, record,
    ))
    normalized = _canonical(json.loads(record.decode("utf-8")))
    if normalized != record:
        raise SimilarityHostError("native admission requires canonical mathematical record bytes")
    context = {
        "schema": NATIVE_SCHEMA,
        "memory_sha256": admitted.memory_sha256,
        "graph_fingerprint": admitted.graph_fingerprint,
        "record": json.loads(record.decode("utf-8")),
        "provenance_label": provenance_label,
    }
    proposal = registry.propose(
        memory_id, Law(family="int", params=dict(_INDEX_LAW), order=1, verdict="GROUND"),
        _INDEX_WITNESSES, domain=NATIVE_DOMAIN, context=context,
    )
    version = registry.admit(proposal.proposal_id, expected_revision=expected_revision)
    return NativeSimilarityPin.from_version(version)


class NativeSimilarityCatalogue(PinnedSimilarityCatalogue):
    """Receiver-local adapter: every lookup resolves the native *pinned revision*.

    Intentionally implements the PinnedSimilarityCatalogue contract, without
    keeping a second set of authority-bearing records. Cache is an optional
    mathematical acceleration; the actual version is revalidated on each query.
    """

    def __init__(self, operating_system: Any, authority_pid: int,
                 pin: NativeSimilarityPin, *, require_active: bool = False) -> None:
        if not isinstance(pin, NativeSimilarityPin):
            raise SimilarityHostError("native catalogue requires a trusted native pin")
        if type(authority_pid) is not int or authority_pid <= 0:
            raise SimilarityHostError("receiver authority PID is invalid")
        if not isinstance(require_active, bool):
            raise SimilarityHostError("require_active must be boolean")
        registry = getattr(operating_system, "structural_memory", None)
        if not isinstance(registry, StructuralMemoryRegistry):
            raise SimilarityHostError("HeadlessOS has no native structural-memory registry")
        operating_system.environment.kernel._process(authority_pid)
        self.operating_system = operating_system
        self.authority_pid = authority_pid
        self.pin = pin
        self.require_active = require_active
        self._verified = None
        self._verified_spec_digest = None
        # Refuse misbound startup immediately, not on the first computation.
        self._version()

    def _read_authorized(self) -> None:
        process = self.operating_system.environment.kernel._process(self.authority_pid)
        if not any(cap.allows("/structural-memory/read", "read")
                   for cap in process.capabilities):
            raise SimilarityHostError("receiver authority lacks structural-memory read capability")

    def _version(self) -> StructuralMemoryVersion:
        try:
            registry = self.operating_system.structural_memory
            version = registry.version_for_revision(self.pin.memory_id, self.pin.revision)
        except Exception as exc:
            raise SimilarityHostError(f"native similarity revision unavailable: {exc}") from exc
        if (version.spec.digest != self.pin.spec_digest
            or version.certificate.digest != self.pin.certificate_digest):
            raise SimilarityHostError("native similarity revision identity mismatch")
        context = _verified_context(version)
        if (context["memory_sha256"] != self.pin.memory_sha256
            or context["graph_fingerprint"] != self.pin.graph_fingerprint):
            raise SimilarityHostError("native similarity revision mathematical identity mismatch")
        if self.require_active:
            active = registry.active_version(self.pin.memory_id)
            if active is None or active.spec.digest != self.pin.spec_digest:
                raise SimilarityHostError("native similarity revision has been superseded")
        return version

    def resolve(self, memory_sha256: str, graph_fingerprint: str) -> Any:
        self._read_authorized()
        _sha(memory_sha256, "memory_sha256")
        _sha(graph_fingerprint, "graph_fingerprint")
        if (memory_sha256 != self.pin.memory_sha256
            or graph_fingerprint != self.pin.graph_fingerprint):
            raise SimilarityHostError("request does not match pinned native Ground revision")
        version = self._version()
        if self._verified is None or self._verified_spec_digest != version.spec.digest:
            context = _verified_context(version)
            payload = _canonical(context["record"])
            self._verified = _reconstruct(PinnedSimilarityRecord(
                memory_sha256, graph_fingerprint, payload,
            ))
            self._verified_spec_digest = version.spec.digest
        return self._verified

    def record_bytes(self, memory_sha256: str) -> bytes:
        self._read_authorized()
        if memory_sha256 != self.pin.memory_sha256:
            raise SimilarityHostError("requested record is not pinned")
        version = self._version()
        return _canonical(_verified_context(version)["record"])

    def native_anchor(self) -> dict[str, Any]:
        """Return authoritative revision provenance after the local read check."""
        self._read_authorized()
        version = self._version()
        return {
            "schema": NATIVE_SCHEMA,
            "memory_id": version.spec.memory_id,
            "revision": version.spec.revision,
            "parent_spec_digest": version.spec.parent_digest,
            "spec_digest": version.spec.digest,
            "certificate_digest": version.certificate.digest,
            "context_digest": version.spec.context_digest,
            "admitted_proposal_id": version.admitted_proposal_id,
            "mathematical_memory_sha256": self.pin.memory_sha256,
            "graph_fingerprint": self.pin.graph_fingerprint,
            "index_law_scope": "revision_coordinate_only_not_similarity_proof",
        }