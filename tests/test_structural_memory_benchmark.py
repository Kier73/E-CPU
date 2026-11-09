"""Smoke tests for the reproducible Structural Memory comparison benchmark."""

from __future__ import annotations

from scripts.benchmark_structural_memory import benchmark_case


def test_benchmark_compares_equal_bytes_and_exposes_cold_journal_costs():
    report = benchmark_case(256, repeats=1)

    assert report["equivalence"]["all_bytes_equal"] is True
    assert report["equivalence"]["direct_receipt_matches"] is True
    assert report["materialized"]["logical_bytes"] == 256

    direct = report["direct_file_provider"]
    assert direct["cold_range_journal"]["events"] == 1
    assert direct["cold_coordinate_commitment_count"] == 256
    assert direct["hot_range_journal"]["events"] == 0
    assert direct["cold_receipt_coordinates"] == 256
    assert direct["hot_receipt_cache_hits"] == 256

    demand = report["vm_demand_page"]
    assert demand["cold_fault_journal"]["events"] == 1
    assert demand["cold_coordinate_commitment_count"] == 256
    assert demand["hot_read_journal"]["events"] == 0
    assert demand["page_backing_descriptor_bytes"] > 0
    assert demand["generator_spec_certificate_reference_bytes"] > 0
    assert demand["resident_vm_snapshot_bytes"] > demand["reserved_vm_snapshot_bytes"]


def test_benchmark_rejects_page_sizes_outside_supported_geometry():
    import pytest

    with pytest.raises(ValueError, match="power of two"):
        benchmark_case(300, repeats=1)
    with pytest.raises(ValueError, match="page_size"):
        benchmark_case(131072, repeats=1)
