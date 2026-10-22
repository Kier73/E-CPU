"""Hash-chained logical event journal for deterministic replay and audit."""

from __future__ import annotations

import hashlib
import json
import copy
from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class EventRecord:
    """One immutable logical event and its integrity-chain digest."""

    sequence: int
    kind: str
    payload: dict[str, Any]
    previous_digest: str
    digest: str


def _canonical_bytes(sequence: int, kind: str, payload: dict[str, Any], previous_digest: str) -> bytes:
    """Mathematics: encode an event as a unique canonical byte string `c = JSON(sort_keys, compact)(seq, kind, payload, prev)`."""

    return json.dumps(
        {
            "kind": kind,
            "payload": payload,
            "previous_digest": previous_digest,
            "sequence": sequence,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


class EventJournal:
    """An append-only logical clock and audit log."""

    def __init__(self, records: Iterable[EventRecord] = ()) -> None:
        """Mathematics: initialize the chain `H_0 = 0^64` and append supplied records after validation."""

        self._records: list[EventRecord] = []
        self._records.extend(records)
        if not self.verify():
            raise ValueError("event journal has an invalid hash chain")

    def append(self, kind: str, payload: dict[str, Any]) -> EventRecord:
        """Mathematics: extend the chain by `H_n = SHA256(H_{n-1} || c_n)`, where `n = len(records)+1`."""

        sequence = len(self._records) + 1
        previous_digest = self._records[-1].digest if self._records else "0" * 64
        canonical = _canonical_bytes(sequence, kind, payload, previous_digest)
        digest = hashlib.sha256(bytes.fromhex(previous_digest) + canonical).hexdigest()
        record = EventRecord(sequence, kind, copy.deepcopy(dict(payload)), previous_digest, digest)
        self._records.append(record)
        return record

    def records(self) -> tuple[EventRecord, ...]:
        """Mathematics: expose the ordered event sequence `E = (e_1, ..., e_n)` without mutation."""

        return tuple(
            EventRecord(
                record.sequence,
                record.kind,
                copy.deepcopy(record.payload),
                record.previous_digest,
                record.digest,
            )
            for record in self._records
        )

    def verify(self) -> bool:
        """Mathematics: check every link satisfies `digest_i = SHA256(digest_{i-1} || canonical(event_i))`."""

        previous_digest = "0" * 64
        for expected_sequence, record in enumerate(self._records, start=1):
            if record.sequence != expected_sequence or record.previous_digest != previous_digest:
                return False
            canonical = _canonical_bytes(
                record.sequence,
                record.kind,
                record.payload,
                record.previous_digest,
            )
            expected_digest = hashlib.sha256(
                bytes.fromhex(previous_digest) + canonical
            ).hexdigest()
            if record.digest != expected_digest:
                return False
            previous_digest = record.digest
        return True

    def snapshot(self) -> list[dict[str, Any]]:
        """Mathematics: serialize the chain-preserving sequence `E` into replayable JSON records."""

        return [
            {
                "sequence": record.sequence,
                "kind": record.kind,
                "payload": copy.deepcopy(record.payload),
                "previous_digest": record.previous_digest,
                "digest": record.digest,
            }
            for record in self._records
        ]

    @classmethod
    def from_snapshot(cls, payload: list[dict[str, Any]]) -> "EventJournal":
        """Mathematics: reconstruct event sequence `E` and revalidate every hash-chain identity before use."""

        return cls(
            EventRecord(
                int(item["sequence"]),
                str(item["kind"]),
                copy.deepcopy(dict(item["payload"])),
                str(item["previous_digest"]),
                str(item["digest"]),
            )
            for item in payload
        )

