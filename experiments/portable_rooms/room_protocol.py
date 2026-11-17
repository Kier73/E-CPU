"""ROOM-001: receiver-verifiable portable intent and monotone receipt chain.

The intent is a bounded instance of E-CPU SAB-008's affine Ground. Hashes are
content identities, not signatures or proof of current authority. A separate
trusted pin is required to reject a rollback or substituted root.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

INTENT_SCHEMA = "ecpu.room001.intention.v1"
RECEIPT_SCHEMA = "ecpu.room001.receipt.v1"
CAPSULE_SCHEMA = "ecpu.room001.capsule.v1"
ZERO = "0" * 64
ROOMS = ("github-actions", "durable-object", "browser-wasm")
METHODS = ("python-native-affine", "js-event-affine", "wasm-affine")
MAX_COORD = 10**15


class RoomRefused(ValueError):
    pass


def require(ok: bool, why: str) -> None:
    if not ok:
        raise RoomRefused(why)


def canonical(data: Any) -> bytes:
    try:
        return json.dumps(data, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise RoomRefused("not finite canonical JSON") from error


def digest(data: Any) -> str:
    return hashlib.sha256(canonical(data)).hexdigest()


def field_int(data: dict, key: str, smallest: int, largest: int) -> int:
    value = data[key]
    require(type(value) is int and smallest <= value <= largest, "bad " + key)
    return value


def check_intent(intent: Any) -> None:
    require(type(intent) is dict and set(intent) == {"schema", "request_id", "ground", "coordinate", "projection"}, "intent schema")
    require(intent["schema"] == INTENT_SCHEMA and intent["projection"] == "value", "unrecognized intention")
    require(intent["request_id"] == "room001-portable-intention", "unapproved request identity")
    ground = intent["ground"]
    require(type(ground) is dict and set(ground) == {"a", "c", "modulus", "seed", "family"} and ground["family"] == "affine_mod", "ground schema")
    modulus = field_int(ground, "modulus", 2, 65521)
    for k in ("a", "c", "seed"):
        field_int(ground, k, 0, modulus - 1)
    field_int(intent, "coordinate", 0, MAX_COORD)


def intention() -> dict:
    return {"schema": INTENT_SCHEMA, "request_id": "room001-portable-intention",
            "ground": {"family": "affine_mod", "a": 17, "c": 29,
                       "modulus": 65521, "seed": 5},
            "coordinate": 1_000_000_000_137, "projection": "value"}


def value_at(intent: dict) -> int:
    """Independent binary affine composition, O(log coordinate)."""
    check_intent(intent)
    g = intent["ground"]
    a, c, m, n = g["a"], g["c"], g["modulus"], intent["coordinate"]
    p, q, mul, add = 1, 0, a, c
    while n:
        if n & 1:
            p, q = p * mul % m, (q * mul + add) % m
        mul, add = mul * mul % m, add * (mul + 1) % m
        n //= 2
    return (p * g["seed"] + q) % m


def receipt(intent: dict, prior: list[dict], room: str, method: str, value: int) -> dict:
    check_intent(intent)
    require(room in ROOMS and method == METHODS[ROOMS.index(room)], "room/method identity")
    require(type(value) is int and value == value_at(intent), "unverified observation")
    require(len(prior) <= 2, "receipt chain capacity")
    prior_hash = prior[-1]["digest"] if prior else ZERO
    data = {"schema": RECEIPT_SCHEMA, "generation": len(prior) + 1,
            "predecessor": prior_hash, "intention_digest": digest(intent),
            "room": room, "method": method, "value": value,
            "status": "finite-ground-checked"}
    data["digest"] = digest(data)
    return data


def verify_capsule(data: Any, *, expected_intention: str | None = None,
                   expected_head: str | None = None,
                   expected_generation: int | None = None) -> str:
    require(type(data) is dict and set(data) == {"schema", "intention", "receipts"} and data["schema"] == CAPSULE_SCHEMA, "capsule schema")
    intent = data["intention"]
    check_intent(intent)
    root = digest(intent)
    if expected_intention is not None:
        require(root == expected_intention, "external intention pin mismatch")
    receipts = data["receipts"]
    require(type(receipts) is list and 0 < len(receipts) <= 3, "receipt chain length")
    last = ZERO
    for index, item in enumerate(receipts):
        require(type(item) is dict and set(item) == {"schema", "generation", "predecessor", "intention_digest", "room", "method", "value", "status", "digest"}, "receipt fields")
        require(item["schema"] == RECEIPT_SCHEMA and type(item["generation"]) is int and item["generation"] == index + 1, "receipt generation")
        require(item["room"] == ROOMS[index] and item["method"] == METHODS[index], "receipt realizer sequence")
        require(item["predecessor"] == last and item["intention_digest"] == root, "receipt parent/intent mismatch")
        require(item["status"] == "finite-ground-checked" and type(item["value"]) is int and item["value"] == value_at(intent), "receipt semantic value")
        require(item["digest"] == digest({k:v for k,v in item.items() if k != "digest"}), "receipt byte identity")
        last = item["digest"]
    if expected_head is not None:
        require(last == expected_head, "external head pin mismatch / rollback")
    if expected_generation is not None:
        require(len(receipts) == expected_generation, "external generation mismatch")
    return last


def make_capsule(intent: dict) -> dict:
    return {"schema": CAPSULE_SCHEMA, "intention": intent, "receipts": [receipt(intent, [], ROOMS[0], METHODS[0], value_at(intent))]}
