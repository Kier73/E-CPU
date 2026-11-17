"""DATA-GROUND-001: one byte stream, several exact mathematical interpretations.

This is a source-level demonstration of finite semantic admission, not
automatic meaning extraction or a remote host execution.
"""
from __future__ import annotations

from hashlib import sha256
import ipaddress
import json

from mailcpu.data_ground import DataGround, DataLens


def example_ipv4_datagram() -> bytes:
    """Build a checksum-valid IPv4 datagram (actual native binary header)."""
    h = bytearray(
        b"\x45\x00" + (24).to_bytes(2, "big")
        + (113).to_bytes(2, "big") + b"\x00\x00"
        + b"\x20\x11\x00\x00"
        + ipaddress.IPv4Address("192.0.2.3").packed
        + ipaddress.IPv4Address("198.51.100.6").packed
    )
    checksum = sum(int.from_bytes(h[i:i + 2], "big") for i in range(0, len(h), 2))
    while checksum > 65535:
        checksum = (checksum & 65535) + (checksum >> 16)
    h[10:12] = (65535 ^ checksum).to_bytes(2, "big")
    return bytes(h) + b"\x01\x02\x03\x04"


def run() -> dict:
    """Mathematics: navigate exact bytes, recognize typed views, retain ambiguity."""
    source = DataGround(b"123")
    views = {
        kind: source.interpret(DataLens(kind))
        for kind in ("opaque", "utf8", "uint-be", "json")
    }
    packet = DataGround(example_ipv4_datagram())
    ip_view = packet.interpret(DataLens("ipv4-datagram"))
    json_ground = DataGround(b' {"volts": 1.2500, "samples": [2, -0.5]} ')
    json_view = json_ground.interpret(DataLens("json"))
    return {
        "schema": "mailcpu.data-ground.demo.v1",
        "same_exact_source_sha256": source.byte_sha256,
        "interpretations": {
            kind: {
                "structure": item.structure,
                "translation_contract_digest": item.contract.digest,
                "paired_observation_equivalent": item.comparison.equivalent,
                "byte_reconstruction_exact": item.roundtrip_bytes_exact,
            }
            for kind, item in views.items()
        },
        "packet_observation": {
            "ttl_direct_byte_coordinate": packet.coordinate(8),
            "recognized_ip_header": {
                key: ip_view.structure[key]
                for key in ("ttl", "source", "destination", "protocol",
                            "payload_length", "payload_sha256")
            },
            "verified": packet.verify_interpretation(ip_view),
        },
        "exact_json_rationals": {
            "math_ast": json_view.structure,
            "bytes_preserved_by_normalization": json_view.roundtrip_bytes_exact,
            "mathematically_equivalent": json_view.comparison.equivalent,
        },
        "not_claimed": [
            "the decoder knows why bytes were sent",
            "the network packet traversed a remote router",
            "data identity alone confers interpretation authority",
        ],
    }


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, sort_keys=True))
