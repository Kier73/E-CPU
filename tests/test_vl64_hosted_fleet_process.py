"""SOI-003 full-process VL-64 hosted fleet smoke and resource-admission tests."""

from __future__ import annotations

import hashlib

import pytest

from scripts.benchmark_vl64_fleet import benchmark_case

pytest.importorskip("vld")


def test_four_independent_python_interpreters_host_real_vl64_vm_instances() -> None:
    """Four real interpreters own four full E-CPU OS instances and 24 VL64 operations."""
    report = benchmark_case(4, max_concurrent_processes=4, max_total_resident_pages=8)
    assert report["requested_vm_count"] == 4
    assert report["admitted_vm_count"] == 4
    assert report["refused_vm_count"] == 0
    assert report["real_vl64_host_process_count"] == 4
    assert report["vl64_operation_count"] == 24
    assert report["guest_resident_pages"] == 8
    assert report["guest_resident_bytes"] == 32_768
    assert report["all_vm_checks_passed"]
    assert report["total_snapshot_bytes"] > 0
    ids = [worker["os_observation_digest"] for worker in report["vm_results"]]
    assert len(set(ids)) == 4
    sources = {worker["artifact_manifest_digest"] for worker in report["vm_results"]}
    profiles = {worker["backend_fingerprint"] for worker in report["vm_results"]}
    assert len(sources) == len(profiles) == 1
    assert all(len(worker["operation_receipt_digests"]) == 6 for worker in report["vm_results"])
    assert all(worker["native_supervisor_steps"] == 4 for worker in report["vm_results"])


def test_fleet_page_budget_refuses_excess_vm_count_before_launch() -> None:
    """Two pages per VM and an eight-page ceiling admit exactly four of seven."""
    report = benchmark_case(7, max_concurrent_processes=3, max_total_resident_pages=8)
    assert report["requested_vm_count"] == 7
    assert report["admitted_vm_count"] == 4
    assert report["refused_vm_count"] == 3
    assert report["real_vl64_host_process_count"] == 4
    assert report["all_vm_checks_passed"]


@pytest.mark.parametrize("limits", [
    {"vm_count": 0}, {"vm_count": True}, {"vm_count": 257},
    {"vm_count": 1, "max_concurrent_processes": 0},
    {"vm_count": 1, "max_total_resident_pages": 1},
])
def test_fleet_rejects_invalid_admission_geometry(limits) -> None:
    """Reject impossible capacities before launching even one observer-host."""
    with pytest.raises(ValueError):
        benchmark_case(**limits)



def test_four_live_admitted_vl64_vm_hosts_reach_synchronized_start() -> None:
    """A barrier establishes four simultaneously live fully prepared OS hosts."""
    result = benchmark_case(
        4, max_concurrent_processes=4,
        max_total_resident_pages=8,
        simultaneous_gate=True,
    )
    assert result["simultaneous_live_ready_count"] == 4
    assert result["real_vl64_host_process_count"] == 4
    assert result["vl64_operation_count"] == 24
    assert result["all_vm_checks_passed"]


def test_synchronized_vm_host_admission_requires_enough_process_slots() -> None:
    """Never deadlock on a barrier larger than the configured worker pool."""
    with pytest.raises(ValueError, match="enough process slots"):
        benchmark_case(
            5, max_concurrent_processes=4,
            max_total_resident_pages=10,
            simultaneous_gate=True,
        )
