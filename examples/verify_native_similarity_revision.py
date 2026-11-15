"""Separate-process native E-CPU StructuralMemoryRegistry recovery verifier.

Replays the *actual registry's* committed revision/journal snapshot in a fresh
Python interpreter, without discovery. Does not claim to restore an entire
HeadlessOS process/Transit effect ledger; that is the GEOMETRY-TRANSIT-001 gate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

from mailcpu import Capability
from mailcpu.journal import EventJournal
from mailcpu.structural_memory import StructuralMemoryRegistry
from mailcpu.vgi_similarity_native_memory import (
    NATIVE_DOMAIN, NativeSimilarityCatalogue, NativeSimilarityPin,
)
from vgi.typed_operator_navigation import TypedVector


def verify(document: dict, expected_pin_sha: str, initial: tuple[int, ...], tick: int) -> dict:
    if not isinstance(document, dict) or set(document) != {"registry", "journal", "pin"}:
        raise ValueError("invalid checkpoint fields")
    pin = NativeSimilarityPin(**document["pin"])
    canonical_pin = json.dumps(pin.to_dict(), sort_keys=True, separators=(",", ":")).encode()
    if hashlib.sha256(canonical_pin).hexdigest() != expected_pin_sha:
        raise ValueError("trusted native revision pin differs")
    if type(tick) is not int or tick < 0 or tick.bit_length() > 256:
        raise ValueError("logical coordinate outside bounded experiment")
    restored = StructuralMemoryRegistry.from_snapshot(
        document["registry"],
        admission_policy=lambda proposal: proposal.spec.domain == NATIVE_DOMAIN,
        journal=EventJournal.from_snapshot(document["journal"]),
    )
    # Real registry journal is verified. The read capability is local, not in
    # checkpoint data and not borrowed from the peer's claimed authorization.
    owner = SimpleNamespace(
        structural_memory=restored,
        environment=SimpleNamespace(kernel=SimpleNamespace(
            _process=lambda pid: SimpleNamespace(capabilities=(
                Capability("/structural-memory/read", frozenset({"read"})),
            )),
        )),
    )
    from vgi.similarity_blocks import CertifiedSimilarityBlocks
    original_discover = CertifiedSimilarityBlocks.__dict__["discover"]
    try:
        CertifiedSimilarityBlocks.discover = classmethod(
            lambda cls, *args, **kwargs: (_ for _ in ()).throw(
                AssertionError("receiver must not perform a fresh basis search")
            )
        )
        catalogue = NativeSimilarityCatalogue(owner, 1, pin)
        ground = catalogue.resolve(pin.memory_sha256, pin.graph_fingerprint)
        receipt = ground.state_at(TypedVector(ground.graph.domain, initial), tick)
    finally:
        CertifiedSimilarityBlocks.discover = original_discover
    if not restored.journal.verify():
        raise ValueError("restored journal verification failed")
    return {
        "schema": "mailcpu.vgi-similarity-native-restore-result.v1",
        "process_id": os.getpid(),
        "native_pin": pin.to_dict(),
        "navigation": receipt.to_dict(),
        "rediscovery": False,
        "recovered_from": "native_structural_memory_registry_plus_journal_snapshot",
        "transit_execution_ledger_replay": "not_tested_here",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("checkpoint", type=Path)
    parser.add_argument("expected_pin_sha")
    parser.add_argument("initial_json")
    parser.add_argument("tick", type=int)
    args = parser.parse_args()
    if args.checkpoint.stat().st_size > 2_000_000:
        parser.error("checkpoint exceeds bounded recovery artifact size")
    snapshot = json.loads(args.checkpoint.read_text(encoding="utf-8"))
    initial = json.loads(args.initial_json)
    if not isinstance(initial, list) or any(type(x) is not int for x in initial):
        parser.error("initial coordinates must be a JSON array of strict integers")
    print(json.dumps(verify(snapshot, args.expected_pin_sha, tuple(initial), args.tick),
                     sort_keys=True, separators=(",", ":")), flush=True)


if __name__ == "__main__":
    main()