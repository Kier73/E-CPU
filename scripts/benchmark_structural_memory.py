#!/usr/bin/env python3
"""Compare materialized bytes, structural-memory reads, and demand-paged VM pages.

This is a diagnostic benchmark, not a performance claim. It uses the same
uint8-valued modular progression for every representation and reports the
costs that can be observed at this layer: construction/read time, journal
growth, and serialized descriptor/snapshot sizes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import statistics
import sys
from time import perf_counter_ns
from typing import Any, Callable

from mailcpu.journal import EventJournal
from mailcpu.law_certifier import Law
from mailcpu.memory import VirtualMemory
from mailcpu.providers import StructuralMemoryFileProvider, StructuralMemoryFileRef
from mailcpu.structural_memory import StructuralMemoryRegistry
from mailcpu.structural_memory_pages import StructuralMemoryPageBacking


DEFAULT_SIZES = (256, 4096, 16384)
MAX_PAGE_SIZE = StructuralMemoryPageBacking.MAX_PAGE_SIZE
WITNESSES = {0: 0, 1: 1, 2: 2, 3: 3}


def _json_size(value: Any) -> int:
    """Return the compact UTF-8 JSON size of a serializable benchmark value."""
    return len(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def _timed(operation: Callable[[], Any]) -> tuple[Any, int]:
    """Run one operation and return its result with monotonic elapsed nanoseconds."""
    started = perf_counter_ns()
    result = operation()
    return result, perf_counter_ns() - started


def _new_admitted_memory(memory_id: str, page_size: int):
    """Create one fresh registry containing the benchmark's admitted byte-valued law."""
    journal = EventJournal()
    registry = StructuralMemoryRegistry(
        admission_policy=lambda proposal: True,
        journal=journal,
    )
    law = Law(
        family="int",
        params={"x0": 0, "step": 1, "mod": 256},
        order=1,
        verdict="GROUND",
    )
    proposal = registry.propose(
        memory_id,
        law,
        WITNESSES,
        domain="benchmark-byte-page",
        context={"benchmark": "structural-memory-page-v1"},
    )
    version = registry.admit(proposal.proposal_id, expected_revision=0)
    reference = StructuralMemoryFileRef.from_version(version, 0, page_size)
    return registry, journal, version, reference


def _journal_delta(journal: EventJournal, start: int) -> dict[str, int]:
    """Measure new event count and compact serialized size after a journal cut."""
    records = journal.records()[start:]
    encoded = [
        {
            "sequence": record.sequence,
            "kind": record.kind,
            "payload": record.payload,
            "previous_digest": record.previous_digest,
            "digest": record.digest,
        }
        for record in records
    ]
    return {"events": len(records), "serialized_bytes": _json_size(encoded)}


def _run_once(page_size: int, repeat_index: int) -> dict[str, Any]:
    """Run cold, hot, and random-access comparisons over one page-sized law interval."""
    expected, materialize_ns = _timed(
        lambda: bytes(coordinate & 0xFF for coordinate in range(page_size))
    )
    expected_digest = hashlib.sha256(expected).hexdigest()
    positions = random.Random(20261105 + repeat_index).sample(
        range(page_size), min(128, page_size)
    )

    _, materialized_random_ns = _timed(
        lambda: sum(expected[position] for position in positions)
    )

    # Direct file-provider path: cold coordinates enter the registry journal;
    # the provider-local cache makes the second identical range read hot.
    direct_registry, direct_journal, direct_version, direct_reference = _new_admitted_memory(
        f"bench-direct-{page_size}-{repeat_index}", page_size
    )
    direct_provider = StructuralMemoryFileProvider(
        direct_reference,
        direct_registry,
        max_read_bytes=page_size,
    )
    direct_start = len(direct_journal.records())
    (direct_bytes, direct_cold_receipt), direct_cold_ns = _timed(
        lambda: direct_provider.read_with_receipt(0, page_size)
    )
    direct_cold_journal = _journal_delta(direct_journal, direct_start)
    (direct_hot_bytes, direct_hot_receipt), direct_hot_ns = _timed(
        lambda: direct_provider.read_with_receipt(0, page_size)
    )
    direct_hot_journal = _journal_delta(
        direct_journal, direct_start + direct_cold_journal["events"]
    )

    random_registry, random_journal, _, random_reference = _new_admitted_memory(
        f"bench-random-{page_size}-{repeat_index}", page_size
    )
    random_provider = StructuralMemoryFileProvider(
        random_reference,
        random_registry,
        max_read_bytes=page_size,
    )
    random_start = len(random_journal.records())

    def direct_random_reads() -> int:
        total = 0
        for position in positions:
            chunk, _ = random_provider.read_with_receipt(position, 1)
            total += chunk[0]
        return total

    _, direct_random_ns = _timed(direct_random_reads)
    direct_random_journal = _journal_delta(random_journal, random_start)

    # VM path: an immutable page digest resolves to the same pinned byte range.
    # The first VM read faults the page in; subsequent reads use resident bytes.
    page_registry, page_journal, page_version, page_reference = _new_admitted_memory(
        f"bench-page-{page_size}-{repeat_index}", page_size
    )
    backing = StructuralMemoryPageBacking(page_registry)
    backing.register_page_reference(expected_digest, page_reference)
    vm = VirtualMemory(page_size=page_size, page_backing=backing)
    vm.reserve(0, page_size, writable=False, backing_blob_ids=(expected_digest,))
    reserved_snapshot_bytes = _json_size(vm.snapshot())
    backing_descriptor_bytes = _json_size(backing.snapshot())
    page_start = len(page_journal.records())

    page_bytes, page_cold_ns = _timed(lambda: vm.read(0, page_size))
    page_cold_journal = _journal_delta(page_journal, page_start)
    page_hot_bytes, page_hot_ns = _timed(lambda: vm.read(0, page_size))
    page_hot_journal = _journal_delta(
        page_journal, page_start + page_cold_journal["events"]
    )

    def vm_random_reads() -> int:
        total = 0
        for position in positions:
            total += vm.read(position, 1)[0]
        return total

    _, vm_random_ns = _timed(vm_random_reads)
    resident_snapshot_bytes = _json_size(vm.snapshot())
    generator_descriptor_bytes = _json_size(
        {
            "spec": page_version.spec.to_dict(),
            "certificate": page_version.certificate.to_dict(),
            "file_reference": page_reference.to_dict(),
        }
    )

    if not (
        direct_bytes == direct_hot_bytes == page_bytes == page_hot_bytes == expected
    ):
        raise AssertionError("representations produced different page bytes")
    if direct_cold_receipt.content_digest != expected_digest:
        raise AssertionError("direct range receipt does not bind the expected bytes")
    if page_journal.records()[page_start].kind != "structural_memory.read_revision":
        raise AssertionError("VM page fault did not produce structural-memory read events")
    if direct_cold_journal["events"] != page_size:
        raise AssertionError("direct range read event count differs from byte cardinality")
    if page_cold_journal["events"] != page_size:
        raise AssertionError("VM page materialization event count differs from byte cardinality")
    if direct_hot_journal["events"] or page_hot_journal["events"]:
        raise AssertionError("hot reads unexpectedly repeated registry read events")
    if direct_hot_receipt.cache_hit_count != page_size:
        raise AssertionError("direct provider hot read did not use its byte cache")

    return {
        "materialized": {
            "construction_ns": materialize_ns,
            "random_access_total_ns": materialized_random_ns,
            "logical_bytes": len(expected),
            "python_bytes_object_size": sys.getsizeof(expected),
        },
        "direct_file_provider": {
            "cold_range_ns": direct_cold_ns,
            "hot_range_ns": direct_hot_ns,
            "random_single_byte_total_ns": direct_random_ns,
            "random_single_byte_reads": len(positions),
            "cold_range_journal": direct_cold_journal,
            "hot_range_journal": direct_hot_journal,
            "random_read_journal": direct_random_journal,
            "cold_receipt_coordinates": len(direct_cold_receipt.value_receipt_ids),
            "hot_receipt_cache_hits": direct_hot_receipt.cache_hit_count,
        },
        "vm_demand_page": {
            "cold_page_fault_ns": page_cold_ns,
            "hot_resident_read_ns": page_hot_ns,
            "random_resident_reads_total_ns": vm_random_ns,
            "random_single_byte_reads": len(positions),
            "cold_fault_journal": page_cold_journal,
            "hot_read_journal": page_hot_journal,
            "page_digest": expected_digest,
            "reserved_vm_snapshot_bytes": reserved_snapshot_bytes,
            "resident_vm_snapshot_bytes": resident_snapshot_bytes,
            "vm_snapshot_scope": (
                "VirtualMemory.snapshot() only; excludes HeadlessOS, registry, journal, and backing rebind state"
            ),
            "page_backing_descriptor_bytes": backing_descriptor_bytes,
            "generator_spec_certificate_reference_bytes": generator_descriptor_bytes,
        },
        "equivalence": {
            "all_bytes_equal": True,
            "sha256": expected_digest,
            "direct_receipt_matches": direct_cold_receipt.content_digest == expected_digest,
        },
    }


def benchmark_case(page_size: int, repeats: int = 3) -> dict[str, Any]:
    """Return median measurements for one valid power-of-two virtual page size."""
    if type(page_size) is not int or page_size < 256 or page_size > MAX_PAGE_SIZE:
        raise ValueError(f"page_size must be a power of two in [256, {MAX_PAGE_SIZE}]")
    if page_size & (page_size - 1):
        raise ValueError("page_size must be a power of two")
    if type(repeats) is not int or repeats < 1 or repeats > 25:
        raise ValueError("repeats must be an integer in [1, 25]")

    runs = [_run_once(page_size, repeat_index) for repeat_index in range(repeats)]
    timings = (
        ("materialized", "construction_ns"),
        ("materialized", "random_access_total_ns"),
        ("direct_file_provider", "cold_range_ns"),
        ("direct_file_provider", "hot_range_ns"),
        ("direct_file_provider", "random_single_byte_total_ns"),
        ("vm_demand_page", "cold_page_fault_ns"),
        ("vm_demand_page", "hot_resident_read_ns"),
        ("vm_demand_page", "random_resident_reads_total_ns"),
    )
    result: dict[str, Any] = {
        "page_size": page_size,
        "repeats": repeats,
        "materialized": dict(runs[0]["materialized"]),
        "direct_file_provider": dict(runs[0]["direct_file_provider"]),
        "vm_demand_page": dict(runs[0]["vm_demand_page"]),
        "equivalence": dict(runs[0]["equivalence"]),
    }
    for section, key in timings:
        result[section][key + "_median"] = int(
            statistics.median(run[section][key] for run in runs)
        )
    result["measurement_note"] = (
        "Timings are local wall-clock diagnostics; compare on the same host and "
        "Python build. Journal and snapshot byte counts are deterministic for "
        "a fixed page size and repository revision."
    )
    return result


def _parse_sizes(value: str) -> tuple[int, ...]:
    """Parse comma-separated page sizes and reject values outside VM geometry."""
    try:
        sizes = tuple(int(part.strip()) for part in value.split(",") if part.strip())
    except ValueError as exc:
        raise argparse.ArgumentTypeError("sizes must be comma-separated integers") from exc
    if not sizes:
        raise argparse.ArgumentTypeError("at least one page size is required")
    for size in sizes:
        if size < 256 or size > MAX_PAGE_SIZE or size & (size - 1):
            raise argparse.ArgumentTypeError(
                f"each size must be a power of two in [256, {MAX_PAGE_SIZE}]"
            )
    return sizes


def main() -> int:
    """Run selected Structural Memory comparisons and emit machine-readable JSON."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", type=_parse_sizes, default=DEFAULT_SIZES)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.repeats <= 25:
        parser.error("--repeats must be in [1, 25]")

    report = {
        "schema": "mailcpu.structural-memory-benchmark.v1",
        "method": "materialized bytes vs StructuralMemoryFileProvider vs VM demand page",
        "cases": [benchmark_case(size, args.repeats) for size in args.sizes],
    }
    print(json.dumps(report, indent=2 if args.pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
