"""SOI-008: E-CPU M3-pinned VL-I TIME-005 Ed25519 source admission.

The external publisher holds the private key. The E-CPU OS retains its
public verification key and every accepted original signed source packet
inside quorum-verified checkpoint bytes. Each rehosted observer reconstructs
both the native TIME-001 Ground and the TIME-005 source evidence sequence.

Signatures authenticate the *publisher's assertion*, not physical sensor truth.
"""
from __future__ import annotations

import json
import re
from typing import Any

from .computational_transition import ComputationalTransitionError
from .fs import FsError
from .stream_os_session import restore_headless_state, serialize_headless_state

SOURCE_ROOT_SCHEMA = "mailcpu.vli-signed-source-root.v1"
SOURCE_ROOT_PATH = "/vli/temporal/source-root.json"
SOURCE_PACKET_ROOT = "/vli/temporal/signed-observations"
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")


def _canonical(value: Any) -> bytes:
    """Encode a finite trusted source record deterministically."""
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ComputationalTransitionError("signed-source record is not finite JSON") from exc


def _read_json(machine, path: str, *, max_bytes: int = 8192) -> dict[str, Any] | None:
    """Read bounded canonical source evidence from the native portable VFS."""
    try:
        raw = machine.environment.kernel.fs.read_file(path)
    except FsError as exc:
        if "not found" in str(exc):
            return None
        raise ComputationalTransitionError("VL-I signed-source VFS read failed") from exc
    if len(raw) > max_bytes:
        raise ComputationalTransitionError("VL-I signed-source file exceeds byte budget")
    def unique(pairs):
        """Disallow duplicate JSON fields in source evidence."""
        record = {}
        for key, value in pairs:
            if key in record:
                raise ValueError("duplicate key")
            record[key] = value
        return record
    try:
        value = json.loads(
            raw.decode("utf-8"), object_pairs_hook=unique,
            parse_constant=lambda constant: (_ for _ in ()).throw(ValueError(constant)),
        )
    except (ValueError, UnicodeError) as exc:
        raise ComputationalTransitionError("VL-I signed-source bytes are not JSON") from exc
    if not isinstance(value, dict) or _canonical(value) != raw:
        raise ComputationalTransitionError("VL-I signed-source file is noncanonical")
    return value


def source_root(machine) -> dict[str, str] | None:
    """Read an exact M3-pinned publisher identity and its original Ed25519 key."""
    root = _read_json(machine, SOURCE_ROOT_PATH, max_bytes=2048)
    if root is None:
        return None
    if (set(root) != {"schema", "source", "public_key"}
        or root["schema"] != SOURCE_ROOT_SCHEMA
        or not isinstance(root["source"], str)
        or not 1 <= len(root["source"]) <= 100
        or not isinstance(root["public_key"], str)
        or _HEX64.fullmatch(root["public_key"]) is None):
        raise ComputationalTransitionError("source trust-root identity is malformed")
    return root


def bind_vli_signed_source(
    state_bytes: bytes, *, source: str, public_key: str,
) -> bytes:
    """Explicitly bind an externally supplied Ed25519 public key at OS genesis."""
    if not isinstance(source, str) or not 1 <= len(source) <= 100:
        raise ComputationalTransitionError("source publisher identity is invalid")
    if not isinstance(public_key, str) or _HEX64.fullmatch(public_key) is None:
        raise ComputationalTransitionError("signed source requires real public-key bytes")
    machine = restore_headless_state(state_bytes)
    if source_root(machine) is not None:
        raise ComputationalTransitionError("signed source root cannot silently be replaced")
    # A policy may only be introduced at the beginning of observation history:
    # never retroactively label existing unsigned events as authenticated.
    prior = _read_json(machine, "/vli/temporal/state.json", max_bytes=4_194_304)
    if not isinstance(prior, dict) or prior.get("events") != []:
        raise ComputationalTransitionError("signed source must be bound before the first observation")
    from vli.temporal_intelligence import verify_temporal_snapshot
    try:
        verify_temporal_snapshot(
            prior, expected_head=prior["head"], expected_identity=prior["identity"],
        )
    except (ValueError, KeyError, TypeError) as exc:
        raise ComputationalTransitionError("signed source initial Ground is not verified") from exc
    # A syntactically valid public key becomes the authorized trust root only
    # when the caller creates M3 genesis with this committed OS state.
    machine.install_source(
        SOURCE_ROOT_PATH, _canonical({
            "schema": SOURCE_ROOT_SCHEMA, "source": source,
            "public_key": public_key,
        }).decode("utf-8"),
    )
    return serialize_headless_state(machine)


def _verified_packet(packet, root: dict[str, str]) -> str:
    """Invoke original VL-I TIME-005 Ed25519 signature and packet-identity code."""
    from vli.authenticated_temporal_source import (
        verify_source_signature, _packet_digest,
    )
    try:
        verify_source_signature(
            packet, public_key=root["public_key"], source=root["source"],
        )
        return _packet_digest(packet)
    except (ValueError, KeyError, TypeError) as exc:
        raise ComputationalTransitionError("VL-I TIME-005 Ed25519 signature refused") from exc


def verify_signed_history(machine, checkpoint: dict[str, Any]) -> dict[str, str] | None:
    """Reconstruct every pinned signed packet and correlate it to VL-I source events."""
    root = source_root(machine)
    if root is None:
        return None
    events = checkpoint.get("events")
    if not isinstance(events, list) or len(events) > 128:
        raise ComputationalTransitionError("VL-I signed-source event count is invalid")
    last_clock = 0
    for index, event in enumerate(events):
        packet = _read_json(machine, f"{SOURCE_PACKET_ROOT}/{index:04d}.json")
        if packet is None:
            raise ComputationalTransitionError("VL-I accepted Ground event lacks signed evidence")
        packet_digest = _verified_packet(packet, root)
        if (packet.get("sequence") != index
            or packet.get("time") != event["time"]
            or packet.get("values") != event["values"]
            or event["source_digest"] != packet_digest
            or type(packet.get("captured_monotonic_ns")) is not int
            or packet["captured_monotonic_ns"] < last_clock):
            raise ComputationalTransitionError("VL-I signed packet or source-Ground alignment differs")
        last_clock = packet["captured_monotonic_ns"]
    return root


def verify_next_signed_packet(
    machine, checkpoint: dict[str, Any], packet: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    """Authenticate next source sample against M3-pinned root and previous events."""
    root = verify_signed_history(machine, checkpoint)
    if root is None:
        raise ComputationalTransitionError("VL-I session has no signed-source admission root")
    count = len(checkpoint["events"])
    if count >= 128:
        raise ComputationalTransitionError("VL-I signed observation budget is exhausted")
    packet_digest = _verified_packet(packet, root)
    if packet.get("sequence") != count:
        raise ComputationalTransitionError("VL-I signed publisher sequence is stale or reordered")
    if count:
        previous_packet = _read_json(machine, f"{SOURCE_PACKET_ROOT}/{count - 1:04d}.json")
        if packet["captured_monotonic_ns"] < previous_packet["captured_monotonic_ns"]:
            raise ComputationalTransitionError("VL-I signed source clock regressed")
    sample = {
        "schema": "vl-i.source-sample.v1",
        "sequence": packet["sequence"],
        "time": packet["time"],
        "values": packet["values"],
        "source_digest": packet_digest,
    }
    return sample, packet_digest


def write_signed_packet(machine, packet: dict[str, Any]) -> None:
    """Retain exact accepted publisher evidence inside candidate native OS state."""
    machine.install_source(
        f"{SOURCE_PACKET_ROOT}/{packet['sequence']:04d}.json",
        _canonical(packet).decode("utf-8"),
    )
