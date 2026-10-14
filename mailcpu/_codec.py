"""Encode and decode runtime state values with transport and canonical JSON algebras."""

from __future__ import annotations

import json
from typing import Any

from .model import Message

_BYTES_TAG = "bytes_hex"
_TUPLE_TAG = "tuple"
_LIST_TAG = "list"
_DICT_TAG = "dict"

_TRANSPORT_FIELDS = (
    "sender",
    "recipient",
    "op",
    "addr",
    "value",
    "seq",
    "message_id",
)


# ---------------------------------------------------------------------------
# TRANSPORT algebra
# ---------------------------------------------------------------------------


def encode_transport_value(value: Any) -> Any:
    """Mathematics: embed `value` into the TRANSPORT algebra `E` such that `decode(E(x))` reconstructs every scalar and every byte payload."""

    if isinstance(value, bytes):
        return {_BYTES_TAG: value.hex()}
    if isinstance(value, dict):
        return {str(key): encode_transport_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [encode_transport_value(item) for item in value]
    return value


def decode_transport_value(value: Any) -> Any:
    """Mathematics: invert `encode_transport_value` on the TRANSPORT algebra `E`."""

    if isinstance(value, dict):
        if set(value) == {_BYTES_TAG}:
            return bytes.fromhex(str(value[_BYTES_TAG]))
        return {str(key): decode_transport_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [decode_transport_value(item) for item in value]
    return value


def message_to_record(message: Message) -> dict[str, Any]:
    """Mathematics: project message `m` onto its identity coordinates and a TRANSPORT-algebra body, discarding nothing."""

    record = {field: getattr(message, field) for field in _TRANSPORT_FIELDS}
    record["body"] = encode_transport_value(message.body)
    return record


def message_from_record(record: dict[str, Any]) -> Message:
    """Mathematics: reconstruct message `m` from its canonical projection, admitting only bodies in the domain `A^{n}` for `n >= 0`."""

    body = decode_transport_value(record.get("body", ()))
    if not isinstance(body, (list, tuple)):
        raise ValueError("message body must be a sequence")
    return Message(
        sender=str(record.get("sender", "")),
        recipient=str(record.get("recipient", "")),
        op=str(record.get("op", "")),
        addr=str(record.get("addr", "")),
        value=None if record.get("value") is None else int(record["value"]),
        seq=int(record.get("seq", 0)),
        body=tuple(body),
        message_id=str(record.get("message_id", "")),
    )


# ---------------------------------------------------------------------------
# CANONICAL algebra
# ---------------------------------------------------------------------------


def encode_canonical_value(value: Any) -> Any:
    """Mathematics: embed `value` injectively into the CANONICAL algebra such that `decode(encode(x)) = x` and `encode` is invariant under permutation of mapping keys."""

    if isinstance(value, bytes):
        return {_BYTES_TAG: value.hex()}
    if isinstance(value, tuple):
        return {_TUPLE_TAG: [encode_canonical_value(item) for item in value]}
    if isinstance(value, list):
        return {_LIST_TAG: [encode_canonical_value(item) for item in value]}
    if isinstance(value, dict):
        return {
            _DICT_TAG: [
                [str(key), encode_canonical_value(item)]
                for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            ]
        }
    return value


def decode_canonical_value(value: Any) -> Any:
    """Mathematics: invert `encode_canonical_value` over the CANONICAL algebra."""

    if not isinstance(value, dict):
        return value
    if set(value) == {_BYTES_TAG}:
        return bytes.fromhex(str(value[_BYTES_TAG]))
    if set(value) == {_TUPLE_TAG}:
        return tuple(decode_canonical_value(item) for item in value[_TUPLE_TAG])
    if set(value) == {_LIST_TAG}:
        return [decode_canonical_value(item) for item in value[_LIST_TAG]]
    if set(value) == {_DICT_TAG}:
        return {str(pair[0]): decode_canonical_value(pair[1]) for pair in value[_DICT_TAG]}
    return {str(key): decode_canonical_value(item) for key, item in value.items()}


def canonical_digest_payload(value: Any) -> str:
    """Mathematics: `encode_canonical_value` composed with JSON serialisation by sorted key, yielding one representation per equivalence class under input permutation.""" 

    return json.dumps(encode_canonical_value(value), sort_keys=True, separators=(",", ":"))
