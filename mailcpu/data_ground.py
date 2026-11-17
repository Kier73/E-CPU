"""DATA-GROUND-001: exact mathematical interpretation of finite data observations.

Every finite byte string x belongs to (Z/256Z)^n without assuming
a schema, linguistic meaning, model architecture or computational law.
A receiver may select a versioned, exact *lens* to additionally recognize
UTF-8, integers, JSON rationals, or an IPv4 datagram. Recognition is
checked against the original bytes and recorded with E-CPU's existing
RepresentationRef / TranslationContract / ObservationComparison.

This is a finite, receiver-controlled recognition primitive, not an
automatic decoder of every possible format. Opaque data remains a valid
mathematical byte-vector Ground. It does not mint authority, authenticate
an origin, or prove properties outside the explicitly observed range.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from hashlib import sha256
import ipaddress
import json
from typing import Any, Mapping

from .computational_objects import ComputationalObjectManifest, ComputationalObjectStore
from .semantic_translation import (
    ObservationComparison, ObservationContract, RepresentationRef,
    ResourceBound, TranslationContract, canonical_value_digest,
    compare_projected_observations,
)

SCHEMA = "mailcpu.data-ground.v1"
MAX_WINDOW = 65_536
MAX_DEPTH = 32
KINDS = frozenset({"opaque", "uint-be", "uint-le", "utf8", "json", "ipv4-datagram"})


class DataGroundRefused(ValueError):
    """Data, decoder or purported semantic observation fails exact admission."""


def _integer(value: Any, name: str, low: int, high: int) -> int:
    """Mathematics: only builtin integer coordinates are valid, not Booleans."""
    if type(value) is not int or not low <= value <= high:
        raise DataGroundRefused(f"{name} must be an integer in [{low}, {high}]")
    return value


def _sha(data: bytes) -> str:
    """Mathematics: SHA-256 identifies bytes, but does not authenticate their sender."""
    return sha256(data).hexdigest()


def _object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Mathematics: reject duplicate JSON keys rather than silently overwrite them."""
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise DataGroundRefused("JSON contains ambiguous duplicate object keys")
        out[key] = value
    return out


def _refuse_nonfinite(value: str) -> None:
    """Mathematics: JSON NaN/Infinity are outside this exact rational algebra."""
    raise DataGroundRefused(f"JSON nonfinite number {value!r} is not admitted")


def _exact_integer(token: str) -> int:
    """Mathematics: enforce finite integer digit budget before big-int conversion."""
    if len(token) > 1024:
        raise DataGroundRefused("JSON integer exceeds exact numeric budget")
    return int(token)


def _exact_decimal(token: str) -> Decimal:
    """Mathematics: bound decimal exponent and mantissa before rational expansion."""
    if len(token) > 1024:
        raise DataGroundRefused("JSON decimal exceeds exact numeric budget")
    result = Decimal(token)
    if abs(result.as_tuple().exponent) > 1024:
        raise DataGroundRefused("JSON decimal exponent exceeds rational budget")
    return result


def _parse_json(data: bytes) -> Any:
    """Mathematics: parse exact UTF-8 JSON using Decimal, not binary floats."""
    try:
        return json.loads(
            data.decode("utf-8", errors="strict"),
            parse_int=_exact_integer, parse_float=_exact_decimal,
            parse_constant=_refuse_nonfinite, object_pairs_hook=_object_pairs,
        )
    except (UnicodeError, ValueError, RecursionError, TypeError) as exc:
        raise DataGroundRefused("data is not admitted exact UTF-8 JSON") from exc


def _ast(value: Any, depth: int = 0) -> dict[str, Any]:
    """Mathematics: map JSON scalars to disjoint symbolic domains and exact Q."""
    if depth > MAX_DEPTH:
        raise DataGroundRefused("JSON mathematical structure exceeds finite depth")
    if value is None:
        return {"domain": "null"}
    if type(value) is bool:
        return {"domain": "boolean", "value": value}
    if type(value) is int:
        return {"domain": "Z", "value": str(value)}
    if isinstance(value, Decimal):
        q = Fraction(value)
        return {
            "domain": "Q", "numerator": str(q.numerator),
            "denominator": str(q.denominator),
        }
    if type(value) is str:
        return {"domain": "unicode", "text": value}
    if type(value) is list:
        return {"domain": "ordered-product", "items": [
            _ast(item, depth + 1) for item in value
        ]}
    if type(value) is dict:
        return {"domain": "finite-string-map", "entries": [
            [key, _ast(value[key], depth + 1)] for key in sorted(value)
        ]}
    raise DataGroundRefused("decoded value is outside exact mathematical JSON algebra")


def _json_normalize(value: Any, depth: int = 0) -> str:
    """Mathematics: serialize normalized JSON without ever converting Q to float."""
    if depth > MAX_DEPTH:
        raise DataGroundRefused("JSON normalization exceeds finite depth")
    if value is None:
        return "null"
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) is int:
        return str(value)
    if type(value) is Decimal:
        return str(value)
    if type(value) is str:
        return json.dumps(value, ensure_ascii=False)
    if type(value) is list:
        return "[" + ",".join(_json_normalize(item, depth + 1) for item in value) + "]"
    if type(value) is dict:
        return "{" + ",".join(
            json.dumps(key, ensure_ascii=False) + ":" +
            _json_normalize(value[key], depth + 1)
            for key in sorted(value)
        ) + "}"
    raise DataGroundRefused("JSON normalization encountered unsupported mathematical type")


def _checksum(header: bytes) -> int:
    """Mathematics: one's-complement sum of the finite IPv4 header words."""
    if len(header) % 2:
        raise DataGroundRefused("IPv4 checksum words are not 16-bit aligned")
    value = sum(int.from_bytes(header[i:i + 2], "big") for i in range(0, len(header), 2))
    while value > 0xFFFF:
        value = (value & 0xFFFF) + (value >> 16)
    return value


def _decode_ipv4(data: bytes) -> dict[str, Any]:
    """Mathematics: admit only one complete IPv4 datagram with valid header checksum.

    A packet header is a *declared structured observation*, not proof of
    where the packet travelled or who produced it.
    """
    if not 20 <= len(data) <= MAX_WINDOW or data[0] >> 4 != 4:
        raise DataGroundRefused("not a finite IPv4 version-four datagram")
    ihl = (data[0] & 0xF) * 4
    if ihl < 20 or ihl > len(data):
        raise DataGroundRefused("IPv4 header length is invalid")
    total = int.from_bytes(data[2:4], "big")
    if total != len(data) or _checksum(data[:ihl]) != 0xFFFF:
        raise DataGroundRefused("IPv4 datagram length or header checksum is inconsistent")
    flags_fragment = int.from_bytes(data[6:8], "big")
    return {
        "domain": "ipv4-datagram",
        "version": 4,
        "header_bytes": ihl,
        "length": total,
        "source": str(ipaddress.IPv4Address(data[12:16])),
        "destination": str(ipaddress.IPv4Address(data[16:20])),
        "ttl": data[8],
        "protocol": data[9],
        "identification": int.from_bytes(data[4:6], "big"),
        "fragment_word": flags_fragment,
        "options_hex": data[20:ihl].hex(),
        "payload_length": total - ihl,
        "payload_sha256": _sha(data[ihl:]),
        # Retain a reversible source image; this is a small bounded lens,
        # never a claim that the semantic fields alone recover all bytes.
        "datagram_hex": data.hex(),
    }


def _decode(data: bytes, kind: str) -> tuple[dict[str, Any], bytes, str]:
    """Mathematics: explicit finite lens, reconstructed bytes, observation equivalence mode."""
    if kind == "opaque":
        return {"domain": "(Z/256Z)^n", "length": len(data),
                "coordinates_hex": data.hex()}, data, "exact-bytes"
    if kind in {"uint-be", "uint-le"}:
        if not 1 <= len(data) <= 16:
            raise DataGroundRefused("unsigned integer lens requires 1..16 bytes")
        order = "big" if kind == "uint-be" else "little"
        value = int.from_bytes(data, order)
        return {
            "domain": "Z", "value": str(value), "bits": 8 * len(data),
            "endian": order,
        }, value.to_bytes(len(data), order), "exact-bytes"
    if kind == "utf8":
        try:
            text = data.decode("utf-8", errors="strict")
        except UnicodeError as exc:
            raise DataGroundRefused("bytes do not encode valid UTF-8") from exc
        return {
            "domain": "unicode-sequence", "text": text,
            "codepoint_count": len(text),
        }, text.encode("utf-8"), "exact-bytes"
    if kind == "json":
        value = _parse_json(data)
        source_math = _ast(value)
        normalized = _json_normalize(value).encode("utf-8")
        if _ast(_parse_json(normalized)) != source_math:
            raise DataGroundRefused("JSON rational normalization changes mathematical value")
        return source_math, normalized, "exact-mathematical-ast"
    if kind == "ipv4-datagram":
        view = _decode_ipv4(data)
        return view, bytes.fromhex(view["datagram_hex"]), "exact-bytes"
    raise DataGroundRefused("decoder is not an admitted typed mathematical lens")


@dataclass(frozen=True)
class DataLens:
    """Finite declared coordinate selection and exact mathematical interpretation."""

    kind: str
    offset: int = 0
    length: int | None = None

    def __post_init__(self) -> None:
        if type(self.kind) is not str or self.kind not in KINDS:
            raise DataGroundRefused("unknown mathematical interpretation")
        _integer(self.offset, "offset", 0, 1 << 40)
        if self.length is not None:
            _integer(self.length, "length", 0, MAX_WINDOW)

    def to_dict(self) -> dict[str, Any]:
        return {"schema": SCHEMA + ".lens", "kind": self.kind,
                "offset": self.offset, "length": self.length}


@dataclass(frozen=True)
class DataInterpretation:
    """One verifiable exact-case E-CPU translation, never a universal inference."""

    lens: DataLens
    structure: dict[str, Any]
    source_sha256: str
    range_sha256: str
    roundtrip_bytes_exact: bool
    observation_mode: str
    contract: TranslationContract
    comparison: ObservationComparison
    qualification_scope: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA + ".interpretation",
            "lens": self.lens.to_dict(), "structure": self.structure,
            "source_sha256": self.source_sha256,
            "range_sha256": self.range_sha256,
            "roundtrip_bytes_exact": self.roundtrip_bytes_exact,
            "observation_mode": self.observation_mode,
            "contract": self.contract.to_dict(),
            "comparison": self.comparison.to_dict(),
            "qualification_scope": self.qualification_scope,
            "not_claimed": [
                "automatic source format identification",
                "sender authentication",
                "unobserved object bytes verified when range-only",
                "universal correctness of a semantic interpretation",
            ],
        }


@dataclass(frozen=True)
class DataGround:
    """One finite actual byte window and a separately identified source extent."""

    data: bytes
    source_scope: str = "complete-inline-bytes"
    parent_manifest_digest: str | None = None
    parent_content_digest: str | None = None
    parent_offset: int = 0

    def __post_init__(self) -> None:
        if type(self.data) is not bytes or len(self.data) > MAX_WINDOW:
            raise DataGroundRefused("finite observed byte window exceeds admission budget")
        if self.source_scope not in {
            "complete-inline-bytes", "page-verified-range", "full-object-content-verified",
        }:
            raise DataGroundRefused("unknown source observation scope")
        _integer(self.parent_offset, "parent offset", 0, 1 << 40)
        if self.source_scope == "complete-inline-bytes":
            if self.parent_manifest_digest is not None or self.parent_content_digest is not None or self.parent_offset:
                raise DataGroundRefused("inline bytes cannot impersonate a page-store origin")
        else:
            for label, digest in (
                ("manifest", self.parent_manifest_digest),
                ("object content", self.parent_content_digest),
            ):
                if type(digest) is not str or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                    raise DataGroundRefused(f"parent {label} digest is invalid")

    @classmethod
    def from_object_range(
        cls, store: ComputationalObjectStore, manifest: ComputationalObjectManifest,
        offset: int, length: int,
    ) -> "DataGround":
        """Resolve only requested pages; do not claim untouched pages were verified."""
        if not isinstance(store, ComputationalObjectStore) or not isinstance(manifest, ComputationalObjectManifest):
            raise DataGroundRefused("native E-CPU computational object and store required")
        _integer(offset, "object offset", 0, 1 << 40)
        _integer(length, "object range length", 0, MAX_WINDOW)
        data = store.read_range(manifest, offset, length)
        full = offset == 0 and length == manifest.size_bytes
        return cls(
            data,
            "full-object-content-verified" if full else "page-verified-range",
            manifest.manifest_digest, manifest.content_digest, offset,
        )

    @property
    def byte_sha256(self) -> str:
        return _sha(self.data)

    def coordinate(self, position: int) -> dict[str, Any]:
        """Mathematics: directly observe a *resident* (Z/256Z) coordinate in O(1)."""
        _integer(position, "byte coordinate", 0, len(self.data) - 1)
        return {
            "schema": SCHEMA + ".coordinate",
            "position": position, "value": self.data[position],
            "domain": "Z/256Z", "source_sha256": self.byte_sha256,
            "scope": self.source_scope, "resident_byte_reads": 1,
        }

    def interpret(self, lens: DataLens) -> DataInterpretation:
        """Admit a structural lens through existing E-CPU semantic translation contracts."""
        if not isinstance(lens, DataLens):
            raise DataGroundRefused("receiver must supply a typed interpretation lens")
        length = len(self.data) - lens.offset if lens.length is None else lens.length
        if lens.offset > len(self.data) or length > len(self.data) - lens.offset:
            raise DataGroundRefused("lens extends outside actually observed byte window")
        selected = self.data[lens.offset:lens.offset + length]
        structure, encoded, comparison_mode = _decode(selected, lens.kind)
        if comparison_mode == "exact-bytes" and encoded != selected:
            raise DataGroundRefused("declared reversible mathematical lens lost input bytes")
        source_case = {
            "source_sha256": self.byte_sha256,
            "parent_manifest_digest": self.parent_manifest_digest,
            "parent_content_digest": self.parent_content_digest,
            "parent_offset": self.parent_offset,
            "source_scope": self.source_scope,
            "lens": lens.to_dict(), "range_sha256": _sha(selected),
            "range_length": len(selected),
        }
        source_ref = RepresentationRef.from_payload(
            "mailcpu.data-ground.byte-range", 1, source_case,
        )
        target_ref = RepresentationRef.from_payload(
            "mailcpu.data-ground.mathematical-view", 1,
            {"source": source_ref.to_dict(), "structure": structure},
        )
        mapping = RepresentationRef.from_payload(
            "mailcpu.data-ground.typed-lens", 1,
            {"kind": lens.kind, "revision": 1, "mode": comparison_mode},
        )
        observation = ObservationContract.from_definition(
            "mailcpu.data-ground.byte-or-math-equivalence", 1,
            {"mode": comparison_mode, "lens_kind": lens.kind},
        )
        contract = TranslationContract(
            contract_id="mailcpu.data-ground." + lens.kind,
            revision=1, source=source_ref, target=target_ref,
            mapping=mapping, observation=observation,
            context_digest=canonical_value_digest(source_case),
            resource_bounds=(ResourceBound("observed_bytes", len(selected), "bytes"),),
        )
        if comparison_mode == "exact-bytes":
            original_observation = {"bytes_hex": selected.hex()}
            reconstructed_observation = {"bytes_hex": encoded.hex()}
        else:
            original_observation = {"math": structure}
            reconstructed_observation = {"math": _ast(_parse_json(encoded))}
        comparison = compare_projected_observations(
            contract, case_payload=source_case,
            source_observation=original_observation,
            target_observation=reconstructed_observation,
        )
        if not comparison.equivalent:
            raise DataGroundRefused("declared observation relation did not survive translation")
        return DataInterpretation(
            lens=lens, structure=structure, source_sha256=self.byte_sha256,
            range_sha256=_sha(selected), roundtrip_bytes_exact=(encoded == selected),
            observation_mode=comparison_mode, contract=contract,
            comparison=comparison, qualification_scope=self.source_scope,
        )

    def verify_interpretation(self, claim: DataInterpretation) -> bool:
        """Reconstruct exact claim against current source bytes; content hashes alone cannot authorize."""
        if not isinstance(claim, DataInterpretation):
            return False
        try:
            return self.interpret(claim.lens) == claim
        except (DataGroundRefused, ValueError, TypeError, UnicodeError):
            return False
