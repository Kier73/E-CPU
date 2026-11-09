from __future__ import annotations

from scripts.benchmark_vm_fleet_processes import benchmark_case, build_report


def test_process_fleet_runs_one_independent_vm_per_supervised_child() -> None:
    report = benchmark_case(
        2,
        work_units=8,
        working_set_pages=2,
        max_total_resident_pages=4,
        barrier_timeout=30.0,
    )

    assert report["requested_vm_count"] == 2
    assert report["admitted_vm_count"] == 2
    assert report["all_workers_independent"] is True
    assert report["distinct_process_count"] == 2
    assert report["all_workers_halted_and_correct"] is True
    assert report["total_resident_pages"] == 4
    assert report["total_retired_instructions"] == 2 * (2 * 8 + 4)
    assert report["observed_total_sum"] == report["expected_total_sum"]
    assert all(item["process_exit_code"] == 0 for item in report["worker_receipts"])
    assert all(item["checkpoint_restored_correctly"] for item in report["worker_receipts"])
    assert all(item["checkpoint_restored_as_independent_instances"] for item in report["worker_receipts"])
    assert all(item["checkpoint_memory_bytes_verified"] == 2 * 4096 for item in report["worker_receipts"])
    assert report["profile_does_not_treat_same_user_processes_as_security_sandbox"] is True


def test_process_fleet_enforces_guest_page_budget_before_starting_children() -> None:
    report = benchmark_case(
        3,
        work_units=4,
        working_set_pages=2,
        max_total_resident_pages=4,
        barrier_timeout=30.0,
    )

    assert report["requested_vm_count"] == 3
    assert report["admitted_vm_count"] == 2
    assert report["rejected_by_guest_page_budget"] == 1
    assert report["distinct_process_count"] == 2
    assert report["total_resident_pages"] == 4
    assert report["all_workers_halted_and_correct"] is True


def test_process_fleet_report_does_not_claim_absolute_physical_host_capacity() -> None:
    report = build_report(
        (1, 2),
        work_units=2,
        working_set_pages=2,
        max_total_resident_pages=4,
        barrier_timeout=30.0,
    )

    assert report["capacity"]["highest_fully_admitted_and_verified_vm_count"] == 2
    assert report["capacity"]["exact_under_guest_page_budget"] is True
    assert "not established by this run" in report["capacity"]["physical_host_capacity_claim"]
