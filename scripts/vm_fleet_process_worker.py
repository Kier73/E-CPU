#!/usr/bin/env python3
"""One process-isolated MailCPU VM worker used by the fleet capacity experiment."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time
import traceback
from time import perf_counter_ns
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mailcpu import HeadlessOS  # noqa: E402
from mailcpu.subprocess_service import publish_service_ready  # noqa: E402
from scripts.benchmark_vm_fleet import (  # noqa: E402
    PAGE_SIZE,
    _build_worker_program,
    _expected_interval_sum,
    _working_set_page,
)


def _atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    """Durably publish one bounded worker result through an atomic sibling replacement."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(
            value,
            stream,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _wait_for_file(path: Path, timeout: float, *, label: str) -> None:
    """Wait for a coordinator-owned barrier file without exceeding a finite deadline."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.is_file():
            return
        time.sleep(0.005)
    raise TimeoutError(f"worker {label} barrier did not arrive within {timeout:g} seconds")


def _rss_bytes() -> int | None:
    """Read this worker's current RSS on Linux; return None where no portable source is available."""
    if not sys.platform.startswith("linux"):
        return None
    try:
        with open("/proc/self/statm", "r", encoding="ascii") as stream:
            resident_pages = int(stream.read().split()[1])
        return resident_pages * int(os.sysconf("SC_PAGE_SIZE"))
    except (OSError, ValueError, IndexError):
        return None


def _parse_arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker-index", type=int, required=True)
    parser.add_argument("--work-units", type=int, required=True)
    parser.add_argument("--working-set-pages", type=int, required=True)
    parser.add_argument("--release-file", type=Path, required=True)
    parser.add_argument("--shutdown-file", type=Path, required=True)
    parser.add_argument("--result-file", type=Path, required=True)
    parser.add_argument("--barrier-timeout", type=float, default=120.0)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_arguments(argv)
    construction_started = perf_counter_ns()
    worker_index = args.worker_index
    start = worker_index * args.work_units
    try:
        operating_system = HeadlessOS(
            max_resident_pages=args.working_set_pages
        )
        program = _build_worker_program(start, args.work_units)
        pid = operating_system.spawn(
            program,
            f"process-fleet-worker-{worker_index:04d}",
            max_pages=args.working_set_pages,
        )
        memory = operating_system.vm.memories[pid]
        if args.working_set_pages > 2:
            memory.map(
                2 * PAGE_SIZE,
                (args.working_set_pages - 2) * PAGE_SIZE,
            )
        for page_number in range(args.working_set_pages):
            memory.write(
                page_number * PAGE_SIZE,
                _working_set_page(worker_index, page_number),
            )
        resident_pages = operating_system.vm.resident_pages()
        if resident_pages != args.working_set_pages:
            raise RuntimeError(
                f"worker {worker_index} materialized {resident_pages} pages; "
                f"expected {args.working_set_pages}"
            )

        ready = {
            "role": "mailcpu-vm-fleet-process-worker",
            "worker_index": worker_index,
            "guest_pid": pid,
            "resident_pages": resident_pages,
            "page_size_bytes": PAGE_SIZE,
            "rss_at_ready_bytes": _rss_bytes(),
            "construction_wall_ns": perf_counter_ns() - construction_started,
        }
        publish_service_ready(ready)

        _wait_for_file(
            args.release_file,
            args.barrier_timeout,
            label="fleet release",
        )
        execution_started = perf_counter_ns()
        task = operating_system.vm.scheduler.tasks[pid]
        quantum_ns: list[int] = []
        retired_instructions = 0
        expected_instructions = 2 * args.work_units + 4
        while not task.state.halted:
            quantum_started = perf_counter_ns()
            events = operating_system.run(
                max_ticks=operating_system.vm.scheduler.tick + 1
            )
            quantum_ns.append(perf_counter_ns() - quantum_started)
            if len(events) != 1:
                raise RuntimeError(
                    f"worker {worker_index} retired {len(events)} instructions "
                    "for a one-instruction scheduler quantum"
                )
            retired_instructions += len(events)
        execution_finished = perf_counter_ns()

        actual_sum = task.backend.read_register("acc")
        expected_sum = _expected_interval_sum(start, args.work_units)
        journal_valid = operating_system.environment.kernel.journal.verify()

        snapshot_started = perf_counter_ns()
        snapshot = operating_system.snapshot()
        snapshot_bytes = len(
            json.dumps(
                snapshot,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
        )
        snapshot_ns = perf_counter_ns() - snapshot_started

        restore_started = perf_counter_ns()
        restored = HeadlessOS.from_snapshot(snapshot)
        restore_ns = perf_counter_ns() - restore_started
        restored_task = restored.vm.scheduler.tasks.get(pid)
        restored_memory = restored.vm.memories.get(pid)
        expected_memory = b"".join(
            _working_set_page(worker_index, page_number)
            for page_number in range(args.working_set_pages)
        )
        restored_memory_valid = (
            restored_memory is not None
            and restored_memory.read(0, len(expected_memory)) == expected_memory
        )
        restore_objects_distinct = (
            restored is not operating_system
            and restored.vm is not operating_system.vm
            and restored.vm.scheduler is not operating_system.vm.scheduler
            and restored.environment.kernel is not operating_system.environment.kernel
            and restored.environment.kernel.journal
            is not operating_system.environment.kernel.journal
            and restored_memory is not memory
        )
        checkpoint_valid = (
            restore_objects_distinct
            and restored_task is not None
            and restored_task.state.halted
            and restored_task.state.steps == expected_instructions
            and restored_task.backend.read_register("acc") == expected_sum
            and restored.vm.resident_pages() == resident_pages
            and restored_memory_valid
            and restored.environment.kernel.journal.verify()
        )
        valid = (
            task.state.halted
            and task.state.steps == expected_instructions
            and retired_instructions == expected_instructions
            and actual_sum == expected_sum
            and journal_valid
            and checkpoint_valid
        )

        result = {
            "schema": "mailcpu.vm-fleet-process-worker.v1",
            "worker_index": worker_index,
            "process_pid": os.getpid(),
            "guest_pid": pid,
            "work_units": args.work_units,
            "start": start,
            "expected_partial_sum": expected_sum,
            "partial_sum": actual_sum,
            "expected_instructions": expected_instructions,
            "retired_instructions": retired_instructions,
            "task_halted": bool(task.state.halted),
            "journal_valid": bool(journal_valid),
            "resident_pages": resident_pages,
            "resident_guest_bytes": resident_pages * PAGE_SIZE,
            "snapshot_bytes": snapshot_bytes,
            "snapshot_wall_ns": snapshot_ns,
            "checkpoint_restore_wall_ns": restore_ns,
            "checkpoint_restored_correctly": bool(checkpoint_valid),
            "checkpoint_restored_as_independent_instances": bool(
                restore_objects_distinct
            ),
            "checkpoint_memory_bytes_verified": (
                len(expected_memory) if restored_memory_valid else 0
            ),
            "execution_wall_ns": execution_finished - execution_started,
            "execution_started_perf_ns": execution_started,
            "execution_finished_perf_ns": execution_finished,
            "quantum_p50_ns": (
                sorted(quantum_ns)[len(quantum_ns) // 2]
                if quantum_ns else None
            ),
            "quantum_p95_ns": (
                sorted(quantum_ns)[max(0, int(len(quantum_ns) * 0.95) - 1)]
                if quantum_ns else None
            ),
            "rss_at_ready_bytes": ready["rss_at_ready_bytes"],
            "rss_after_checkpoint_bytes": _rss_bytes(),
            "all_checks_passed": bool(valid),
        }
        _atomic_write_json(args.result_file, result)
        _wait_for_file(
            args.shutdown_file,
            args.barrier_timeout,
            label="fleet shutdown",
        )
        return 0 if valid else 3
    except Exception:
        traceback.print_exc()
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
