#!/usr/bin/env python3
"""Measure independent MailCPU VM instances hosted in separate operating-system processes.

The host coordinator uses the existing SubprocessServiceSupervisor for
PID-bound readiness, bounded lifetime, and explicit NEVER-restart policy.
Each child owns one complete HeadlessOS/VM/scheduler/kernel/journal and
executes the same deterministic interval-sum workload behind a common release
barrier. This is a process-isolation measurement, not a security sandbox or a
physical multi-host experiment.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import sys
import tempfile
import time
from time import perf_counter_ns
from typing import Any, Sequence

from mailcpu import RestartPolicy, SubprocessServiceSpec, SubprocessServiceSupervisor

from scripts.benchmark_vm_fleet import PAGE_SIZE, _expected_interval_sum


SCHEMA = "mailcpu.vm-fleet-process-capacity.v1"


class ProcessFleetBenchmarkError(RuntimeError):
    """The process-isolated fleet failed admission, lifecycle, execution, or recovery invariants."""


def _strict_int(value: Any, name: str, minimum: int) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


def _atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    """Durably publish one coordinator barrier through an atomic replacement."""
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


def _read_process_memory(pid: int) -> dict[str, int | None]:
    """Read one child PSS/RSS pair on Linux; report unavailable rather than guessing elsewhere."""
    result: dict[str, int | None] = {"pss_bytes": None, "rss_bytes": None}
    if not sys.platform.startswith("linux"):
        return result
    try:
        with open(f"/proc/{pid}/smaps_rollup", "r", encoding="ascii") as stream:
            for line in stream:
                if line.startswith("Pss:"):
                    result["pss_bytes"] = int(line.split()[1]) * 1024
                elif line.startswith("Rss:"):
                    result["rss_bytes"] = int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    if result["rss_bytes"] is None:
        try:
            with open(f"/proc/{pid}/statm", "r", encoding="ascii") as stream:
                resident_pages = int(stream.read().split()[1])
            result["rss_bytes"] = resident_pages * int(os.sysconf("SC_PAGE_SIZE"))
        except (OSError, ValueError, IndexError):
            pass
    return result


def _parent_rss_bytes() -> int | None:
    """Read coordinator RSS on Linux to keep host and child memory scopes distinct."""
    if not sys.platform.startswith("linux"):
        return None
    try:
        with open("/proc/self/statm", "r", encoding="ascii") as stream:
            resident_pages = int(stream.read().split()[1])
        return resident_pages * int(os.sysconf("SC_PAGE_SIZE"))
    except (OSError, ValueError, IndexError):
        return None


def _available_memory_bytes() -> int | None:
    """Read Linux MemAvailable as a host observation, not a reservation."""
    if not sys.platform.startswith("linux"):
        return None
    try:
        with open("/proc/meminfo", "r", encoding="ascii") as stream:
            for line in stream:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


def _read_worker_result(path: Path, worker_index: int) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProcessFleetBenchmarkError(
            f"worker {worker_index} result is unavailable or malformed: {exc}"
        ) from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema") != "mailcpu.vm-fleet-process-worker.v1"
        or payload.get("worker_index") != worker_index
    ):
        raise ProcessFleetBenchmarkError(
            f"worker {worker_index} result schema or identity is invalid"
        )
    return payload


def benchmark_case(
    vm_count: int,
    *,
    work_units: int = 64,
    working_set_pages: int = 2,
    max_total_resident_pages: int | None = None,
    barrier_timeout: float = 120.0,
) -> dict[str, Any]:
    """Run one process-isolated fleet behind a common start barrier and verify every VM checkpoint."""
    _strict_int(vm_count, "vm_count", 1)
    _strict_int(work_units, "work_units", 1)
    _strict_int(working_set_pages, "working_set_pages", 2)
    if max_total_resident_pages is not None:
        _strict_int(max_total_resident_pages, "max_total_resident_pages", 1)
        if max_total_resident_pages < working_set_pages:
            raise ValueError(
                "max_total_resident_pages must admit at least one VM working set"
            )
    if (
        not isinstance(barrier_timeout, (int, float))
        or isinstance(barrier_timeout, bool)
        or barrier_timeout <= 0
        or barrier_timeout > 3600
    ):
        raise ValueError("barrier_timeout must be positive and at most 3600 seconds")

    budget_capacity = (
        None
        if max_total_resident_pages is None
        else max_total_resident_pages // working_set_pages
    )
    admitted_count = (
        vm_count
        if budget_capacity is None
        else min(vm_count, budget_capacity)
    )
    if admitted_count < 1:
        raise ProcessFleetBenchmarkError("guest page budget admitted no process-hosted VM")

    repository_root = Path(__file__).resolve().parents[1]
    worker_script = Path(__file__).with_name("vm_fleet_process_worker.py")
    host_rss_before = _parent_rss_bytes()
    available_before = _available_memory_bytes()
    construction_started = perf_counter_ns()
    worker_results: dict[int, dict[str, Any]] = {}
    worker_pids: dict[int, int] = {}
    ready_memory: dict[int, dict[str, int | None]] = {}
    statuses_after_exit: dict[str, dict[str, Any]] = {}
    supervisor = SubprocessServiceSupervisor()

    with tempfile.TemporaryDirectory(prefix="mailcpu-vm-fleet-process-") as temporary:
        root = Path(temporary)
        readiness_directory = root / "readiness"
        logs_directory = root / "logs"
        results_directory = root / "results"
        readiness_directory.mkdir(parents=True)
        logs_directory.mkdir(parents=True)
        results_directory.mkdir(parents=True)
        release_file = root / "release.json"
        shutdown_file = root / "shutdown.json"
        started_services: list[str] = []

        try:
            for worker_index in range(admitted_count):
                service_name = f"vm-worker-{worker_index:04d}"
                result_path = results_directory / f"worker-{worker_index:04d}.json"
                command = (
                    sys.executable,
                    str(worker_script),
                    "--worker-index",
                    str(worker_index),
                    "--work-units",
                    str(work_units),
                    "--working-set-pages",
                    str(working_set_pages),
                    "--release-file",
                    str(release_file),
                    "--shutdown-file",
                    str(shutdown_file),
                    "--result-file",
                    str(result_path),
                    "--barrier-timeout",
                    str(float(barrier_timeout)),
                )
                supervisor.register(
                    SubprocessServiceSpec(
                        name=service_name,
                        command=command,
                        readiness_directory=readiness_directory,
                        restart=RestartPolicy.NEVER,
                        max_restarts=0,
                        readiness_timeout=min(60.0, float(barrier_timeout)),
                        shutdown_timeout=10.0,
                        restart_delay=0.0,
                        cwd=repository_root,
                        log_path=logs_directory / f"{service_name}.log",
                    )
                )
                report = supervisor.start(service_name)
                started_services.append(service_name)
                if report.state != "running" or report.pid is None or report.ready is None:
                    raise ProcessFleetBenchmarkError(
                        f"{service_name} did not reach a PID-bound running state: {report.to_dict()}"
                    )
                details = dict(report.ready)
                if (
                    details.get("role") != "mailcpu-vm-fleet-process-worker"
                    or details.get("worker_index") != worker_index
                    or details.get("resident_pages") != working_set_pages
                    or details.get("guest_pid") != 2
                ):
                    raise ProcessFleetBenchmarkError(
                        f"{service_name} readiness details do not match the requested VM profile"
                    )
                worker_pids[worker_index] = report.pid
                ready_memory[worker_index] = _read_process_memory(report.pid)

            construction_ns = perf_counter_ns() - construction_started
            release_started = perf_counter_ns()
            _atomic_write_json(
                release_file,
                {
                    "schema": "mailcpu.vm-fleet-process-release.v1",
                    "admitted_workers": admitted_count,
                    "released_perf_ns": release_started,
                },
            )

            deadline = time.monotonic() + float(barrier_timeout)
            pending = set(range(admitted_count))
            while pending and time.monotonic() < deadline:
                for worker_index in tuple(sorted(pending)):
                    result_path = results_directory / f"worker-{worker_index:04d}.json"
                    if result_path.is_file():
                        worker_results[worker_index] = _read_worker_result(
                            result_path,
                            worker_index,
                        )
                        pending.remove(worker_index)
                reports = supervisor.reconcile()
                for report in reports:
                    if report.state in {"failed", "restart_exhausted"}:
                        if not any(
                            name == report.name
                            for name in started_services
                        ):
                            continue
                        worker_index = int(report.name.rsplit("-", 1)[1])
                        if worker_index in pending:
                            log_path = logs_directory / f"{report.name}.log"
                            diagnostic = (
                                log_path.read_text(encoding="utf-8", errors="replace")[-4096:]
                                if log_path.is_file() else ""
                            )
                            raise ProcessFleetBenchmarkError(
                                f"{report.name} failed before publishing its result: "
                                f"{report.last_error}; log={diagnostic}"
                            )
                if pending:
                    time.sleep(0.01)
            if pending:
                raise ProcessFleetBenchmarkError(
                    f"process-hosted VM workers timed out without results: {sorted(pending)}"
                )

            # Workers intentionally remain alive after publishing results so
            # the coordinator can inspect their real process memory before exit.
            memory_after: dict[int, dict[str, int | None]] = {
                index: _read_process_memory(pid)
                for index, pid in worker_pids.items()
            }
            process_completion_ns = perf_counter_ns() - release_started

            _atomic_write_json(
                shutdown_file,
                {
                    "schema": "mailcpu.vm-fleet-process-shutdown.v1",
                    "admitted_workers": admitted_count,
                },
            )
            exit_deadline = time.monotonic() + 15.0
            while time.monotonic() < exit_deadline:
                statuses = supervisor.reconcile()
                if all(
                    report.state == "exited" and report.exit_code == 0
                    for report in statuses
                    if report.name in started_services
                ):
                    statuses_after_exit = {
                        report.name: report.to_dict()
                        for report in statuses
                        if report.name in started_services
                    }
                    break
                if any(
                    report.state in {"failed", "restart_exhausted"}
                    or (report.state == "exited" and report.exit_code != 0)
                    for report in statuses
                    if report.name in started_services
                ):
                    raise ProcessFleetBenchmarkError("one or more worker processes exited unsuccessfully")
                time.sleep(0.01)
            if len(statuses_after_exit) != admitted_count:
                raise ProcessFleetBenchmarkError("worker processes did not exit cleanly after shutdown")

        finally:
            if not shutdown_file.exists():
                try:
                    _atomic_write_json(
                        shutdown_file,
                        {"schema": "mailcpu.vm-fleet-process-shutdown.v1"},
                    )
                except OSError:
                    pass
            supervisor.close()

    ordered_results = [worker_results[index] for index in range(admitted_count)]
    unique_pids = {int(item["process_pid"]) for item in ordered_results}
    all_workers_independent = (
        len(unique_pids) == admitted_count
        and unique_pids == set(worker_pids.values())
        and all(
            statuses_after_exit.get(f"vm-worker-{index:04d}", {}).get("exit_code") == 0
            for index in range(admitted_count)
        )
    )
    expected_total_sum = _expected_interval_sum(0, admitted_count * work_units)
    observed_total_sum = sum(int(item["partial_sum"]) for item in ordered_results)
    total_retired_instructions = sum(
        int(item["retired_instructions"]) for item in ordered_results
    )
    total_resident_pages = sum(
        int(item["resident_pages"]) for item in ordered_results
    )
    expected_instruction_total = admitted_count * (2 * work_units + 4)
    all_workers_correct = (
        all_workers_independent
        and observed_total_sum == expected_total_sum
        and total_retired_instructions == expected_instruction_total
        and total_resident_pages == admitted_count * working_set_pages
        and all(item["all_checks_passed"] for item in ordered_results)
    )

    pss_ready_total = (
        sum(int(item["pss_bytes"]) for item in ready_memory.values())
        if all(item["pss_bytes"] is not None for item in ready_memory.values())
        else None
    )
    rss_ready_total = (
        sum(int(item["rss_bytes"]) for item in ready_memory.values())
        if all(item["rss_bytes"] is not None for item in ready_memory.values())
        else None
    )
    pss_after_total = (
        sum(int(item["pss_bytes"]) for item in memory_after.values())
        if all(item["pss_bytes"] is not None for item in memory_after.values())
        else None
    )
    rss_after_total = (
        sum(int(item["rss_bytes"]) for item in memory_after.values())
        if all(item["rss_bytes"] is not None for item in memory_after.values())
        else None
    )
    host_rss_after = _parent_rss_bytes()
    available_after = _available_memory_bytes()
    execution_finished_perf_ns = max(
        int(item["execution_finished_perf_ns"])
        for item in ordered_results
    )
    execution_started_perf_ns = min(
        int(item["execution_started_perf_ns"])
        for item in ordered_results
    )
    execution_wall_ns = max(1, execution_finished_perf_ns - release_started)
    total_snapshot_bytes = sum(int(item["snapshot_bytes"]) for item in ordered_results)
    total_snapshot_ns = sum(int(item["snapshot_wall_ns"]) for item in ordered_results)
    total_restore_ns = sum(
        int(item["checkpoint_restore_wall_ns"]) for item in ordered_results
    )

    receipts = []
    for index, item in enumerate(ordered_results):
        receipts.append(
            {
                **item,
                "host_pss_at_ready_bytes": ready_memory[index]["pss_bytes"],
                "host_rss_at_ready_bytes": ready_memory[index]["rss_bytes"],
                "host_pss_after_checkpoint_bytes": memory_after[index]["pss_bytes"],
                "host_rss_after_checkpoint_bytes": memory_after[index]["rss_bytes"],
                "process_exit_code": statuses_after_exit[
                    f"vm-worker-{index:04d}"
                ]["exit_code"],
            }
        )
    all_pss_measured = pss_ready_total is not None and pss_after_total is not None
    return {
        "schema": SCHEMA,
        "requested_vm_count": vm_count,
        "admitted_vm_count": admitted_count,
        "rejected_by_guest_page_budget": vm_count - admitted_count,
        "work_units_per_vm": work_units,
        "total_work_units": admitted_count * work_units,
        "working_set_pages_per_vm": working_set_pages,
        "page_size_bytes": PAGE_SIZE,
        "total_resident_pages": total_resident_pages,
        "total_guest_resident_bytes": total_resident_pages * PAGE_SIZE,
        "total_retired_instructions": total_retired_instructions,
        "expected_total_sum": expected_total_sum,
        "observed_total_sum": observed_total_sum,
        "all_workers_independent": all_workers_independent,
        "distinct_process_count": len(unique_pids),
        "distinct_headless_os_count": admitted_count if all_workers_correct else 0,
        "distinct_vm_count": admitted_count if all_workers_correct else 0,
        "all_workers_halted_and_correct": all_workers_correct,
        "snapshot_bytes_total": total_snapshot_bytes,
        "snapshot_bytes_per_vm_mean": total_snapshot_bytes / admitted_count,
        "construction_wall_ns": construction_ns,
        "concurrent_execution_wall_ns": execution_wall_ns,
        "process_completion_wall_ns": process_completion_ns,
        "snapshot_wall_ns_sum": total_snapshot_ns,
        "checkpoint_restore_wall_ns_sum": total_restore_ns,
        "host_parent_rss_before_bytes": host_rss_before,
        "host_parent_rss_after_bytes": host_rss_after,
        "host_parent_rss_growth_bytes": (
            max(0, host_rss_after - host_rss_before)
            if host_rss_before is not None and host_rss_after is not None
            else None
        ),
        "sum_worker_pss_at_ready_bytes": pss_ready_total,
        "sum_worker_rss_at_ready_bytes": rss_ready_total,
        "sum_worker_pss_after_checkpoint_bytes": pss_after_total,
        "sum_worker_rss_after_checkpoint_bytes": rss_after_total,
        "worker_pss_measurement_available": all_pss_measured,
        "host_available_memory_before_bytes": available_before,
        "host_available_memory_after_bytes": available_after,
        "page_budget_capacity_vm_count": budget_capacity,
        "worker_receipts": receipts,
        "measurement_scope": (
            "One HeadlessOS/VM per supervised operating-system child process; "
            "PID-bound readiness from SubprocessServiceSupervisor; common process "
            "release barrier; independent local MailCPU execution and per-worker "
            "checkpoint/restore; child PSS/RSS observations where /proc is available. "
            "Processes share one OS kernel and user identity and are not a hardened "
            "security sandbox."
        ),
    }


def build_report(
    vm_counts: Sequence[int],
    *,
    work_units: int,
    working_set_pages: int,
    max_total_resident_pages: int | None,
    barrier_timeout: float = 120.0,
) -> dict[str, Any]:
    """Run process-isolated scale points and state only the capacity boundary the run tested."""
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
            barrier_timeout=barrier_timeout,
        )
        for count in counts
    ]
    successful_counts = [
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
    all_requested_passed = len(successful_counts) == len(counts)
    highest_requested = max(counts)
    return {
        "schema": SCHEMA,
        "repository": "Kier73/E-CPU",
        "profile": {
            "vm_definition": "one HeadlessOS + MailCPUVirtualMachine per independent operating-system process",
            "guest_processes_per_vm": 1,
            "guest_isa": "MailCPU nine-opcode transition algebra",
            "program": "distributed-contiguous-integer-range-sum",
            "orchestration": "one SubprocessServiceSupervisor child per VM; common release barrier; independent local instruction execution",
            "working_set_pages_per_vm": working_set_pages,
            "page_size_bytes": PAGE_SIZE,
            "work_units_per_vm": work_units,
            "foreign_native_guest_execution": False,
            "network_federation": False,
            "process_isolation_is_hardened_sandbox": False,
        },
        "host": {
            "platform": platform.platform(),
            "python": sys.version,
            "logical_cpu_count": os.cpu_count(),
            "child_pss_measurement_available": sys.platform.startswith("linux"),
            "child_rss_measurement_available": sys.platform.startswith("linux"),
            "available_memory_measurement_available": sys.platform.startswith("linux"),
        },
        "limits": {
            "max_total_resident_pages": max_total_resident_pages,
            "page_budget_capacity_vm_count": budget_capacity,
            "guest_page_budget_is_a_hard_fleet_admission_cap": max_total_resident_pages is not None,
            "barrier_timeout_seconds": barrier_timeout,
        },
        "capacity": {
            "highest_requested_vm_count": highest_requested,
            "highest_fully_admitted_and_verified_vm_count": (
                max(successful_counts) if successful_counts else 0
            ),
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
                "not established by this run; child PSS/RSS and available memory "
                "are observations, not a host-level resource reservation or proof "
                "of an absolute physical-host maximum"
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
    parser.add_argument("--barrier-timeout", type=float, default=120.0)
    parser.add_argument("--output", type=str, default=None)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = build_report(
            args.vm_counts,
            work_units=args.work_units,
            working_set_pages=args.working_set_pages,
            max_total_resident_pages=args.max_total_resident_pages,
            barrier_timeout=args.barrier_timeout,
        )
    except (ValueError, ProcessFleetBenchmarkError) as exc:
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
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(encoded + "\n", encoding="utf-8")
    if any(not trial["all_workers_halted_and_correct"] for trial in report["trials"]):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
