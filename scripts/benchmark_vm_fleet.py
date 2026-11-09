#!/usr/bin/env python3
"""Measure independent MailCPU VM-fleet density with a deterministic distributed workload.

Each fleet member owns a separate HeadlessOS, scheduler, kernel, journal, and
virtual address space. The orchestrator gives each member one instruction
quantum per round. Workers sum disjoint integer intervals; the coordinator
reduces their partial results and verifies the global answer.

This is a reproducible capacity experiment, not a claim about arbitrary Linux
guests, foreign native instruction execution, or physical multi-host execution.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import sys
from time import perf_counter_ns
from typing import Any, Sequence

from mailcpu import HeadlessOS
from mailcpu.model import Instruction, Op, Program

PAGE_SIZE = 4096
SCHEMA = "mailcpu.vm-fleet-capacity.v1"


class FleetBenchmarkError(RuntimeError):
    """The measured fleet failed an admission, execution, or correctness invariant."""


def _strict_int(value: Any, name: str, minimum: int) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


def _percentile(values: Sequence[int], percentile: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(percentile * len(ordered)) - 1))
    return int(ordered[index])


def _current_rss_bytes() -> int | None:
    """Read current process RSS on Linux; return None when no portable source is available."""
    if not sys.platform.startswith("linux"):
        return None
    try:
        with open("/proc/self/statm", "r", encoding="ascii") as handle:
            resident_pages = int(handle.read().split()[1])
        return resident_pages * int(os.sysconf("SC_PAGE_SIZE"))
    except (OSError, ValueError, IndexError):
        return None


def _available_memory_bytes() -> int | None:
    """Read Linux MemAvailable without adding a runtime dependency."""
    if not sys.platform.startswith("linux"):
        return None
    try:
        with open("/proc/meminfo", "r", encoding="ascii") as handle:
            for line in handle:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


def _build_worker_program(start: int, work_units: int) -> Program:
    """Build a finite program that sums [start, start + work_units)."""
    instructions = [
        Instruction(Op.SET, ("acc", 0)),
        Instruction(Op.SET, ("value", start)),
        Instruction(Op.SET, ("one", 1)),
    ]
    for _ in range(work_units):
        instructions.append(Instruction(Op.ADD, ("acc", "acc", "value")))
        instructions.append(Instruction(Op.ADD, ("value", "value", "one")))
    instructions.append(Instruction(Op.HALT))
    return Program(tuple(instructions))


def _expected_interval_sum(start: int, count: int) -> int:
    if count == 0:
        return 0
    return count * (2 * start + count - 1) // 2


def _initialize_working_set(operating_system: HeadlessOS, pid: int, pages: int, worker_index: int) -> None:
    """Materialize a distinct, fully written page working set for one VM."""
    memory = operating_system.vm.memories[pid]
    if pages > 2:
        memory.map(2 * PAGE_SIZE, (pages - 2) * PAGE_SIZE)
    for page_number in range(pages):
        seed = (worker_index * 17 + page_number * 31) & 0xFF
        payload = bytes((seed + offset) & 0xFF for offset in range(PAGE_SIZE))
        memory.write(page_number * PAGE_SIZE, payload)
    if operating_system.vm.resident_pages() != pages:
        raise FleetBenchmarkError(
            f"worker {worker_index} materialized {operating_system.vm.resident_pages()} "
            f"resident pages; expected {pages}"
        )


def benchmark_case(
    vm_count: int,
    *,
    work_units: int = 64,
    working_set_pages: int = 2,
    max_total_resident_pages: int | None = None,
) -> dict[str, Any]:
    """Run one independently hosted VM fleet and return measurements plus correctness evidence."""
    _strict_int(vm_count, "vm_count", 1)
    _strict_int(work_units, "work_units", 1)
    _strict_int(working_set_pages, "working_set_pages", 2)
    if max_total_resident_pages is not None:
        _strict_int(max_total_resident_pages, "max_total_resident_pages", 1)

    page_budget_capacity = (
        None
        if max_total_resident_pages is None
        else max_total_resident_pages // working_set_pages
    )
    admitted_count = (
        vm_count
        if page_budget_capacity is None
        else min(vm_count, page_budget_capacity)
    )

    rss_before = _current_rss_bytes()
    available_before = _available_memory_bytes()
    construction_started = perf_counter_ns()

    workers: list[dict[str, Any]] = []
    for worker_index in range(admitted_count):
        operating_system = HeadlessOS(max_resident_pages=working_set_pages)
        start = worker_index * work_units
        program = _build_worker_program(start, work_units)
        pid = operating_system.spawn(
            program,
            f"fleet-worker-{worker_index:04d}",
            max_pages=working_set_pages,
        )
        _initialize_working_set(operating_system, pid, working_set_pages, worker_index)
        task = operating_system.vm.scheduler.tasks[pid]
        workers.append(
            {
                "index": worker_index,
                "os": operating_system,
                "pid": pid,
                "task": task,
                "expected_sum": _expected_interval_sum(start, work_units),
                "elapsed_ns": 0,
                "quantum_ns": [],
                "events": 0,
            }
        )

    construction_ns = perf_counter_ns() - construction_started
    execution_started = perf_counter_ns()
    if workers:
        while not all(worker["task"].state.halted for worker in workers):
            progressed = False
            for worker in workers:
                task = worker["task"]
                if task.state.halted:
                    continue
                machine = worker["os"]
                started = perf_counter_ns()
                events = machine.run(max_ticks=machine.vm.scheduler.tick + 1)
                elapsed = perf_counter_ns() - started
                worker["elapsed_ns"] += elapsed
                worker["quantum_ns"].append(elapsed)
                if len(events) != 1:
                    raise FleetBenchmarkError(
                        f"worker {worker['index']} did not retire exactly one instruction "
                        f"for one scheduler quantum (retired {len(events)})"
                    )
                worker["events"] += len(events)
                progressed = True
            if not progressed:
                raise FleetBenchmarkError("fleet scheduler made no progress before all workers halted")
    execution_ns = perf_counter_ns() - execution_started

    worker_reports: list[dict[str, Any]] = []
    correctness = True
    total_retired = 0
    total_resident_pages = 0
    total_snapshot_bytes = 0
    snapshot_started = perf_counter_ns()
    for worker in workers:
        machine = worker["os"]
        task = worker["task"]
        actual_sum = task.backend.read_register("acc")
        expected_steps = 2 * work_units + 4
        valid = (
            task.state.halted
            and task.state.steps == expected_steps
            and actual_sum == worker["expected_sum"]
            and worker["events"] == expected_steps
            and machine.environment.kernel.journal.verify()
        )
        correctness = correctness and valid
        resident_pages = machine.vm.resident_pages()
        total_resident_pages += resident_pages
        total_retired += worker["events"]
        snapshot_bytes = len(
            json.dumps(
                machine.snapshot(),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
        )
        total_snapshot_bytes += snapshot_bytes
        worker_reports.append(
            {
                "worker_index": worker["index"],
                "pid": worker["pid"],
                "scheduler_identity": id(machine.vm.scheduler),
                "kernel_identity": id(machine.environment.kernel),
                "resident_pages": resident_pages,
                "resident_guest_bytes": resident_pages * PAGE_SIZE,
                "retired_instructions": worker["events"],
                "expected_instructions": expected_steps,
                "partial_sum": actual_sum,
                "expected_partial_sum": worker["expected_sum"],
                "task_halted": bool(task.state.halted),
                "journal_valid": bool(machine.environment.kernel.journal.verify()),
                "snapshot_bytes": snapshot_bytes,
                "worker_wall_ns": worker["elapsed_ns"],
                "quantum_p50_ns": _percentile(worker["quantum_ns"], 0.50),
                "quantum_p95_ns": _percentile(worker["quantum_ns"], 0.95),
            }
        )
    snapshot_ns = perf_counter_ns() - snapshot_started

    distinct_scheduler_ids = len({item["scheduler_identity"] for item in worker_reports})
    distinct_kernel_ids = len({item["kernel_identity"] for item in worker_reports})
    observed_sum = sum(item["partial_sum"] for item in worker_reports)
    total_work_units = admitted_count * work_units
    expected_total_sum = _expected_interval_sum(0, total_work_units)
    all_workers_independent = (
        distinct_scheduler_ids == admitted_count and distinct_kernel_ids == admitted_count
    )
    correctness = (
        correctness
        and all_workers_independent
        and observed_sum == expected_total_sum
        and total_retired == admitted_count * (2 * work_units + 4)
        and total_resident_pages == admitted_count * working_set_pages
    )

    rss_after = _current_rss_bytes()
    available_after = _available_memory_bytes()
    total_elapsed_ns = construction_ns + execution_ns + snapshot_ns
    instructions_per_second = (
        total_retired * 1_000_000_000 / execution_ns if execution_ns > 0 else None
    )
    return {
        "requested_vm_count": vm_count,
        "admitted_vm_count": admitted_count,
        "rejected_by_guest_page_budget": vm_count - admitted_count,
        "work_units_per_vm": work_units,
        "total_work_units": total_work_units,
        "working_set_pages_per_vm": working_set_pages,
        "page_size_bytes": PAGE_SIZE,
        "total_resident_pages": total_resident_pages,
        "total_guest_resident_bytes": total_resident_pages * PAGE_SIZE,
        "total_retired_instructions": total_retired,
        "expected_total_sum": expected_total_sum,
        "observed_total_sum": observed_sum,
        "all_workers_independent": all_workers_independent,
        "distinct_scheduler_count": distinct_scheduler_ids,
        "distinct_kernel_count": distinct_kernel_ids,
        "all_workers_halted_and_correct": correctness,
        "snapshot_bytes_total": total_snapshot_bytes,
        "snapshot_bytes_per_vm_mean": (
            total_snapshot_bytes / admitted_count if admitted_count else None
        ),
        "construction_wall_ns": construction_ns,
        "execution_wall_ns": execution_ns,
        "snapshot_wall_ns": snapshot_ns,
        "total_wall_ns": total_elapsed_ns,
        "retired_instructions_per_second": instructions_per_second,
        "host_rss_before_bytes": rss_before,
        "host_rss_after_bytes": rss_after,
        "host_rss_growth_bytes": (
            max(0, rss_after - rss_before)
            if rss_before is not None and rss_after is not None
            else None
        ),
        "host_available_memory_before_bytes": available_before,
        "host_available_memory_after_bytes": available_after,
        "page_budget_capacity_vm_count": page_budget_capacity,
        "worker_receipts": worker_reports,
        "measurement_scope": (
            "Independent HeadlessOS/VM instances in one Python process; local round-robin "
            "orchestration; guest resident-page accounting; process RSS where available; "
            "full HeadlessOS snapshot serialization; deterministic interval-sum correctness."
        ),
    }


def build_report(
    vm_counts: Sequence[int],
    *,
    work_units: int,
    working_set_pages: int,
    max_total_resident_pages: int | None,
) -> dict[str, Any]:
    """Run all requested scale points and derive only capacity claims supported by the profile."""
    counts = tuple(vm_counts)
    if not counts or any(type(item) is not int or item < 1 for item in counts):
        raise ValueError("vm_counts must contain positive integers")
    if tuple(sorted(set(counts))) != counts:
        raise ValueError("vm_counts must be strictly increasing with no duplicates")

    trials = [
        benchmark_case(
            count,
            work_units=work_units,
            working_set_pages=working_set_pages,
            max_total_resident_pages=max_total_resident_pages,
        )
        for count in counts
    ]
    full_successes = [
        trial["requested_vm_count"]
        for trial in trials
        if trial["requested_vm_count"] == trial["admitted_vm_count"]
        and trial["all_workers_halted_and_correct"]
    ]
    budget_capacity = (
        None
        if max_total_resident_pages is None
        else max_total_resident_pages // working_set_pages
    )
    highest_requested = max(counts)
    all_requested_passed = len(full_successes) == len(counts) and all(
        trial["requested_vm_count"] == trial["admitted_vm_count"]
        and trial["all_workers_halted_and_correct"]
        for trial in trials
    )
    return {
        "schema": SCHEMA,
        "repository": "Kier73/E-CPU",
        "profile": {
            "vm_definition": "one independent HeadlessOS + MailCPUVirtualMachine + scheduler + kernel + journal",
            "guest_processes_per_vm": 1,
            "guest_isa": "MailCPU nine-opcode transition algebra",
            "program": "distributed-contiguous-integer-range-sum",
            "orchestration": "one retired instruction per runnable VM per round",
            "working_set_pages_per_vm": working_set_pages,
            "page_size_bytes": PAGE_SIZE,
            "work_units_per_vm": work_units,
            "foreign_native_guest_execution": False,
            "network_federation": False,
        },
        "host": {
            "platform": platform.platform(),
            "python": sys.version,
            "logical_cpu_count": os.cpu_count(),
            "rss_measurement_available": sys.platform.startswith("linux"),
            "available_memory_measurement_available": sys.platform.startswith("linux"),
        },
        "limits": {
            "max_total_resident_pages": max_total_resident_pages,
            "page_budget_capacity_vm_count": budget_capacity,
            "guest_page_budget_is_a_hard_fleet_admission_cap": max_total_resident_pages is not None,
        },
        "capacity": {
            "highest_requested_vm_count": highest_requested,
            "highest_fully_admitted_and_verified_vm_count": max(full_successes) if full_successes else 0,
            "all_requested_scale_points_passed": all_requested_passed,
            "exact_under_guest_page_budget": (
                budget_capacity is not None
                and highest_requested >= budget_capacity
                and all(
                    trial["all_workers_halted_and_correct"]
                    for trial in trials
                    if trial["admitted_vm_count"] == trial["requested_vm_count"]
                )
            ),
            "physical_host_capacity_claim": (
                "not established by this run; host memory and CPU are measured observations, "
                "not a global resource reservation or proof of an absolute hardware maximum"
            ),
        },
        "trials": trials,
    }


def _parse_counts(value: str) -> tuple[int, ...]:
    try:
        result = tuple(int(part.strip()) for part in value.split(",") if part.strip())
    except ValueError as exc:
        raise argparse.ArgumentTypeError("VM counts must be comma-separated integers") from exc
    if not result or any(item < 1 for item in result):
        raise argparse.ArgumentTypeError("VM counts must be positive")
    if tuple(sorted(set(result))) != result:
        raise argparse.ArgumentTypeError("VM counts must be strictly increasing with no duplicates")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vm-counts", type=_parse_counts, default=(1, 2, 4, 8))
    parser.add_argument("--work-units", type=int, default=64)
    parser.add_argument("--working-set-pages", type=int, default=2)
    parser.add_argument("--max-total-resident-pages", type=int, default=None)
    parser.add_argument("--output", type=str, default=None)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = build_report(
            args.vm_counts,
            work_units=args.work_units,
            working_set_pages=args.working_set_pages,
            max_total_resident_pages=args.max_total_resident_pages,
        )
    except (ValueError, FleetBenchmarkError) as exc:
        parser.error(str(exc))
    encoded = json.dumps(
        report,
        sort_keys=True,
        indent=2 if args.pretty else None,
        ensure_ascii=False,
        allow_nan=False,
    )
    print(encoded)
    if args.output:
        with open(args.output, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(encoded)
            handle.write("\n")
    if any(not trial["all_workers_halted_and_correct"] for trial in report["trials"]):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
