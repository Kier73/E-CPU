from __future__ import annotations

import json

import pytest

from mailcpu import Message
from mailcpu._codec import (
    decode_canonical_value,
    decode_transport_value,
    encode_canonical_value,
    encode_transport_value,
    message_from_record,
    message_to_record,
)


_ROUND_TRIP_CASES = [
    b"",
    b"\x00\xff\x10",
    [],
    ["a", "b"],
    {"k": "v"},
    {"k": {"nested": [b"\x01", b"\x02"]}},
    {},
    [],
    0,
    -1,
    2**70,
    None,
    True,
]

_TUPLE_BEARING_CASES = [
    (),
    ("a", "b"),
    ["a", ("b", 1)],
    {"k": {"nested": [b"\x01", ("x",)]}},
]


@pytest.mark.parametrize("value", _ROUND_TRIP_CASES)
def test_canonical_algebra_is_injective_on_round_trip(value: object) -> None:
    """Mathematics: `decode_canonical_value(encode_canonical_value(x)) = x` for every `x` in the finite value domain."""

    assert decode_canonical_value(encode_canonical_value(value)) == value


@pytest.mark.parametrize("value", _ROUND_TRIP_CASES + _TUPLE_BEARING_CASES)
def test_canonical_algebra_converges_tuple_identity(value: object) -> None:
    """Mathematics: the CANONICAL algebra carries a tuple tag, so tuple identity survives where the TRANSPORT algebra discards it."""

    decoded = decode_canonical_value(encode_canonical_value(value))
    assert decoded == value
    assert type(decoded) is type(value)


@pytest.mark.parametrize("value", _ROUND_TRIP_CASES)
def test_transport_algebra_round_trips_scalars_and_bytes(value: object) -> None:
    """Mathematics: `decode_transport_value(encode_transport_value(x)) = x` for every `x` not bearing tuple identity."""

    assert decode_transport_value(encode_transport_value(value)) == value


@pytest.mark.parametrize("value", _TUPLE_BEARING_CASES)
def test_transport_algebra_does_not_conserve_tuple_identity(value: object) -> None:
    """Mathematics: `encode_transport_value` maps tuples and lists to one JSON array form, so tuple identity is outside the TRANSPORT algebra's domain of definition."""

    decoded = decode_transport_value(encode_transport_value(value))
    assert decoded == _flatten_tuples(value)
    assert _contains_tuple(decoded) is False


def _flatten_tuples(value: object) -> object:
    """Mathematics: project `value` onto its TRANSPORT normal form by replacing every tuple with a list."""

    if isinstance(value, tuple):
        return [_flatten_tuples(item) for item in value]
    if isinstance(value, list):
        return [_flatten_tuples(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _flatten_tuples(item) for key, item in value.items()}
    return value


def _contains_tuple(value: object) -> bool:
    """Mathematics: decide whether any node of the finite tree rooted at `value` carries tuple type."""

    if isinstance(value, tuple):
        return True
    if isinstance(value, list):
        return any(_contains_tuple(item) for item in value)
    if isinstance(value, dict):
        return any(_contains_tuple(item) for item in value.values())
    return False


def test_canonical_algebra_distinguishes_container_types() -> None:
    """Mathematics: for `a != b`, `encode_canonical_value(a) != encode_canonical_value(b)` over tuples, lists, mappings, and scalars."""

    encodings = [
        encode_canonical_value(("x",)),
        encode_canonical_value(["x"]),
        encode_canonical_value({"x": 1}),
        encode_canonical_value("x"),
        encode_canonical_value(b"x"),
    ]
    assert len({json.dumps(item, sort_keys=True) for item in encodings}) == 5


def test_canonical_encoding_is_permutation_invariant() -> None:
    """Mathematics: `encode_canonical_value` emits mapping keys in sorted order, so equal mappings share one representation."""

    assert encode_canonical_value({"a": 1, "b": 2}) == encode_canonical_value({"b": 2, "a": 1})


def test_transport_encoding_is_not_permutation_ordered() -> None:
    """Mathematics: `encode_transport_value` preserves mapping insertion order, so it is inadmissible wherever a digest is computed over the encoded form."""

    left = json.dumps(encode_transport_value({"a": 1, "b": 2}), sort_keys=False)
    right = json.dumps(encode_transport_value({"b": 2, "a": 1}), sort_keys=False)
    assert left != right
    assert json.dumps(encode_canonical_value({"a": 1, "b": 2}), sort_keys=False) == json.dumps(
        encode_canonical_value({"b": 2, "a": 1}), sort_keys=False
    )


def test_message_record_round_trip_preserves_identity_and_body() -> None:
    """Mathematics: `message_from_record(message_to_record(m)) = m` for every message whose body lies in `A^{n}`."""

    message = Message(
        sender="program",
        recipient="kernel",
        op="SYSCALL",
        addr="mailbox:req",
        value=7,
        seq=11,
        body=("open", b"\x00\x01", {"path": "/etc/hosts"}),
        message_id="m-1",
    )
    assert message_from_record(message_to_record(message)) == message


def test_message_record_rejects_non_sequence_body() -> None:
    """Mathematics: a body outside `A^{n}` leaves the TRANSPORT domain, so reconstruction is undefined rather than coerced."""

    record = message_to_record(Message(sender="a", recipient="b", body=()))
    record["body"] = {"not": "a sequence"}
    with pytest.raises(ValueError, match="must be a sequence"):
        message_from_record(record)
