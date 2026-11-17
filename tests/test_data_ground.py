"""DATA-GROUND-001: every finite byte observation has an exact mathematical basis.

Fixture tests distinguish lossless structure, optional source-dependent
interpretation, semantic equality, and receiver-scoped verification.
"""
from dataclasses import replace
from hashlib import sha256
import ipaddress

import pytest

from mailcpu.computational_objects import (
    ComputationalObjectError, ComputationalObjectStore,
)
from mailcpu.data_ground import (
    DataGround, DataGroundRefused, DataLens, MAX_WINDOW,
)
from mailcpu.semantic_translation import (
    ObservationComparison, TranslationContract,
)


def _make_ipv4(*, ttl=64, body=b"abcd"):
    """Construct an actual checksum-valid, exact 20-byte IPv4 header plus payload."""
    header = bytearray(
        bytes([0x45, 0x00])
        + (20 + len(body)).to_bytes(2, "big")
        + (0x1234).to_bytes(2, "big")
        + b"\x00\x00"
        + bytes([ttl, 17])
        + b"\x00\x00"
        + ipaddress.IPv4Address("192.0.2.1").packed
        + ipaddress.IPv4Address("198.51.100.9").packed
    )
    def sum_words(data):
        value = sum(int.from_bytes(data[i:i + 2], "big") for i in range(0, len(data), 2))
        while value > 0xFFFF:
            value = (value & 0xFFFF) + (value >> 16)
        return value
    header[10:12] = (0xFFFF ^ sum_words(header)).to_bytes(2, "big")
    assert sum_words(header) == 0xFFFF
    return bytes(header) + body


def test_any_finite_bytes_have_an_exact_Z256_vector_without_a_semantic_assumption():
    """Opaque bytes, invalid text, all-zero and empty input remain valid Grounds."""
    for raw in (b"", b"\x00\xff\x80", bytes(range(256))):
        ground = DataGround(raw)
        result = ground.interpret(DataLens("opaque"))
        assert result.structure == {
            "domain": "(Z/256Z)^n",
            "length": len(raw), "coordinates_hex": raw.hex(),
        }
        assert result.roundtrip_bytes_exact
        assert result.observation_mode == "exact-bytes"
        assert result.comparison.equivalent
        assert result.source_sha256 == sha256(raw).hexdigest()
        assert result.contract.mapping.type_id == "mailcpu.data-ground.typed-lens"
        assert ground.verify_interpretation(result)
        assert TranslationContract.from_dict(result.contract.to_dict()) == result.contract
        assert ObservationComparison.from_dict(result.comparison.to_dict()) == result.comparison


def test_coordinate_navigation_is_a_bounded_actual_resident_data_read():
    ground = DataGround(b"\x00\x01\xff")
    assert ground.coordinate(0)["value"] == 0
    assert ground.coordinate(2)["value"] == 255
    assert ground.coordinate(2)["resident_byte_reads"] == 1
    assert ground.coordinate(2)["domain"] == "Z/256Z"
    for invalid in (-1, 3, True, 0.1, "2"):
        with pytest.raises(DataGroundRefused):
            ground.coordinate(invalid)


def test_same_source_has_distinct_valid_mathematical_lenses_no_automatic_semantic_choice():
    """ASCII '123' is equally valid text, a JSON integer and a big-endian integer."""
    ground = DataGround(b"123")
    u = ground.interpret(DataLens("uint-be"))
    text = ground.interpret(DataLens("utf8"))
    number = ground.interpret(DataLens("json"))
    assert u.structure["value"] == str(int.from_bytes(b"123", "big"))
    assert text.structure == {"domain": "unicode-sequence", "text": "123", "codepoint_count": 3}
    assert number.structure == {"domain": "Z", "value": "123"}
    assert len({item.contract.digest for item in (u, text, number)}) == 3
    assert all(ground.verify_interpretation(x) for x in (u, text, number))
    # One valid representation does not authorize the other meanings.
    assert text.contract.target != u.contract.target
    assert number.contract.target != text.contract.target


def test_exact_integer_endianness_is_not_silently_guessed():
    raw = b"\x01\x02\x03"
    ground = DataGround(raw)
    be = ground.interpret(DataLens("uint-be"))
    le = ground.interpret(DataLens("uint-le"))
    assert be.structure["value"] == "66051"
    assert le.structure["value"] == "197121"
    assert be.roundtrip_bytes_exact and le.roundtrip_bytes_exact
    assert be.structure != le.structure


def test_utf8_unicode_is_reversible_but_arbitrary_invalid_text_is_refused():
    value = "water 💧 and Δ"
    ground = DataGround(value.encode("utf-8"))
    result = ground.interpret(DataLens("utf8"))
    assert result.structure["text"] == value
    assert result.roundtrip_bytes_exact
    with pytest.raises(DataGroundRefused, match="UTF-8"):
        DataGround(b"\xff\xfe").interpret(DataLens("utf8"))


def test_json_numbers_are_exact_rationals_and_not_float_approximations():
    raw = b' { "measurements" : [1.2500, -2e-3, 10000000000000000000000001], "enabled": true } '
    ground = DataGround(raw)
    result = ground.interpret(DataLens("json"))
    assert result.structure["domain"] == "finite-string-map"
    fields = dict(result.structure["entries"])
    fractions = fields["measurements"]["items"]
    assert fractions[0] == {"domain": "Q", "numerator": "5", "denominator": "4"}
    assert fractions[1] == {"domain": "Q", "numerator": "-1", "denominator": "500"}
    assert fractions[2] == {"domain": "Z", "value": "10000000000000000000000001"}
    assert fields["enabled"] == {"domain": "boolean", "value": True}
    assert result.comparison.equivalent  # exact mathematical AST agrees
    assert not result.roundtrip_bytes_exact  # source whitespace was NOT recovered
    assert result.observation_mode == "exact-mathematical-ast"
    assert ground.verify_interpretation(result)


@pytest.mark.parametrize("invalid", [
    b'{"x":1,"x":2}',
    b'{"value": NaN}',
    b'{"value": Infinity}',
    b'{"value":1e999999}',
    b'{"value":' + b"9"*1200 + b'}',
    b'{"x":',
    b"\xff",
])
def test_json_refuses_ambiguous_nonfinite_and_unbounded_inputs(invalid):
    with pytest.raises(DataGroundRefused):
        DataGround(invalid).interpret(DataLens("json"))


def test_json_type_distinctions_do_not_collapse_boolean_into_integer():
    g = DataGround(b'[true,1,1.0,null,"1"]')
    r = g.interpret(DataLens("json"))
    assert [item["domain"] for item in r.structure["items"]] == [
        "boolean", "Z", "Q", "null", "unicode",
    ]
    assert r.structure["items"][1]["value"] == "1"
    assert r.structure["items"][2] == {
        "domain": "Q", "numerator": "1", "denominator": "1",
    }


def test_real_checksum_verified_ipv4_semantics_are_grounded_in_original_header():
    ip_packet = _make_ipv4(ttl=33, body=b"example")
    ground = DataGround(b"\xaa"*14 + ip_packet)
    result = ground.interpret(DataLens("ipv4-datagram", offset=14, length=len(ip_packet)))
    assert result.structure["ttl"] == 33
    assert result.structure["source"] == "192.0.2.1"
    assert result.structure["destination"] == "198.51.100.9"
    assert result.structure["identification"] == 0x1234
    assert result.structure["payload_sha256"] == sha256(b"example").hexdigest()
    assert result.roundtrip_bytes_exact
    assert ground.coordinate(14 + 8)["value"] == 33
    assert ground.verify_interpretation(result)
    damaged = bytearray(ip_packet)
    damaged[8] = 32  # header TTL changed without updating checksum
    with pytest.raises(DataGroundRefused, match="checksum"):
        DataGround(bytes(damaged)).interpret(DataLens("ipv4-datagram"))


class _Pages:
    """Small native PageBacking fixture, not another publication protocol."""

    page_size = 8

    def __init__(self):
        self.pages = {}
        self.reads = []

    def put_page(self, data):
        digest = sha256(data).hexdigest()
        self.pages[digest] = data
        return digest

    def get_page(self, digest):
        self.reads.append(digest)
        return self.pages[digest]


def test_native_computational_object_range_ground_verifies_only_observed_pages():
    backing = _Pages()
    store = ComputationalObjectStore(backing)
    raw = b"part-one" + b"part-two" + b"part-3!!"
    manifest = store.put_bytes(raw)
    backing.reads.clear()
    # The requested 8-byte page is not the complete object.
    ground = DataGround.from_object_range(store, manifest, 8, 8)
    assert ground.data == b"part-two"
    assert ground.source_scope == "page-verified-range"
    assert len(backing.reads) == 1
    assert ground.parent_manifest_digest == manifest.manifest_digest
    assert ground.parent_content_digest == manifest.content_digest
    r = ground.interpret(DataLens("utf8"))
    assert r.qualification_scope == "page-verified-range"
    assert r.structure["text"] == "part-two"
    # A corrupted unobserved page cannot be claimed verified, nor does
    # it invalidate the correctly verified exact requested range.
    backing.pages[manifest.chunks[0].page_digest] = b"incorrect"
    assert DataGround.from_object_range(store, manifest, 8, 8).data == b"part-two"
    with pytest.raises(ComputationalObjectError):
        DataGround.from_object_range(store, manifest, 0, manifest.size_bytes)


def test_complete_native_object_verified_scope_is_distinct_from_range_scope():
    backing = _Pages()
    store = ComputationalObjectStore(backing)
    manifest = store.put_bytes(b"hello")
    ground = DataGround.from_object_range(store, manifest, 0, manifest.size_bytes)
    assert ground.source_scope == "full-object-content-verified"
    assert ground.interpret(DataLens("utf8")).roundtrip_bytes_exact


def test_forged_claim_and_changed_source_are_refused_by_receiver_owned_reconstruction():
    a = DataGround(b"\x00\x10")
    b = DataGround(b"\x00\x11")
    valid = a.interpret(DataLens("uint-be"))
    assert a.verify_interpretation(valid)
    assert not b.verify_interpretation(valid)
    assert not a.verify_interpretation(replace(valid, roundtrip_bytes_exact=False))
    assert not a.verify_interpretation(replace(
        valid, source_sha256="0"*64,
    ))
    assert not a.verify_interpretation(None)


def test_unobserved_ranges_and_invalid_decode_instructions_refuse():
    with pytest.raises(DataGroundRefused):
        DataGround(b"a"* (MAX_WINDOW + 1))
    with pytest.raises(DataGroundRefused):
        DataLens("arbitrary-neural-inference")
    with pytest.raises(DataGroundRefused):
        DataLens("utf8", offset=True)
    with pytest.raises(DataGroundRefused):
        DataLens("opaque", length=MAX_WINDOW+1)
    with pytest.raises(DataGroundRefused):
        DataGround(b"hello").interpret(DataLens("utf8", offset=4, length=8))
    with pytest.raises(DataGroundRefused):
        DataGround(b"1"*17).interpret(DataLens("uint-be"))
    with pytest.raises(DataGroundRefused):
        DataGround(b"").interpret(DataLens("uint-le"))
    with pytest.raises(DataGroundRefused):
        DataGround(b"junk").interpret("utf8")


def test_empty_json_and_unadmitted_ipv4_are_not_misidentified():
    for raw in (b"", b"x", b"\x45"*20):
        with pytest.raises(DataGroundRefused):
            DataGround(raw).interpret(DataLens("json"))
    with pytest.raises(DataGroundRefused):
        DataGround(b"arbitrary binary data").interpret(DataLens("ipv4-datagram"))
