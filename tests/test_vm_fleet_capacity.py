from __future__ import annotations

from scripts.benchmark_vm_fleet import benchmark_case, build_report


def test_vm_fleet_runs_independent_os_instances_and_reduces_disjoint_work() -> None:
    report = benchmark_case(
        3,
        work_units=8,
        working_set_pages=2,
    )

    assert report["requested_vm_count"] == 3
    assert report["admitted_vm_count"] == 3
    assert report["all_workers_independent"] is True
    assert report["distinct_headless_os_count"] == 3
    assert report["distinct_vm_count"] == 3
    assert report["distinct_scheduler_count"] == 3
    assert report["distinct_kernel_count"] == 3
    assert report["distinct_journal_count"] == 3
    assert report["distinct_guest_memory_count"] == 3
    assert report["all_workers_halted_and_correct"] is True
    assert all(item["checkpoint_restored_correctly"] for item in report["worker_receipts"])
    assert all(item["checkpoint_memory_bytes_verified"] == 2 * 4096 for item in report["worker_receipts"])
    assert report["total_resident_pages"] == 6
    assert report["total_retired_instructions"] == 3 * (2 * 8 + 4)
    assert report["observed_total_sum"] == report["expected_total_sum"]
    assert len(report["worker_receipts"]) == 3
    assert all(item["journal_valid"] for item in report["worker_receipts"])


def test_vm_fleet_guest_page_budget_refuses_excess_instances() -> None:
    report = benchmark_case(
        3,
        work_units=4,
        working_set_pages=2,
        max_total_resident_pages=4,
    )

    assert report["requested_vm_count"] == 3
    assert report["admitted_vm_count"] == 2
    assert report["rejected_by_guest_page_budget"] == 1
    assert report["total_resident_pages"] == 4
    assert report["all_workers_halted_and_correct"] is True
    assert report["expected_total_sum"] == sum(range(8))


def test_vm_fleet_report_does_not_call_a_sampled_scale_point_an_absolute_host_maximum() -> None:
    report = build_report(
        (1, 2),
        work_units=2,
        working_set_pages=2,
        max_total_resident_pages=8,
    )

    assert report["capacity"]["highest_fully_admitted_and_verified_vm_count"] == 2
    assert report["capacity"]["exact_under_guest_page_budget"] is False
    assert "not established by this run" in report["capacity"]["physical_host_capacity_claim"]


def test_vm_fleet_rejects_invalid_profiles() -> None:
    import pytest

    with pytest.raises(ValueError, match="working_set_pages"):
        benchmark_case(1, working_set_pages=1)
    with pytest.raises(ValueError, match="at least one VM working set"):
        benchmark_case(1, working_set_pages=2, max_total_resident_pages=1)
    with pytest.raises(ValueError, match="strictly increasing"):
        build_report(
            (2, 1),
            work_units=1,
            working_set_pages=2,
            max_total_resident_pages=None,
        )
