from __future__ import annotations

import pytest

from scripts.benchmark_structural_memory_vm import benchmark_pair


def test_structural_memory_vm_pair_holds_virtual_geometry_and_working_set_constant() -> None:
    report = benchmark_pair(
        page_size=256,
        virtual_pages=4,
        working_set_pages=2,
        hot_repetitions=2,
    )

    materialized = report["cases"]["materialized"]
    structural = report["cases"]["structural"]

    assert report["comparison"]["same_virtual_geometry"] is True
    assert materialized["virtual_bytes"] == structural["virtual_bytes"] == 1024
    assert materialized["working_set_bytes"] == structural["working_set_bytes"] == 512

    assert materialized["resident_pages_after_cold_access"] == 4
    assert materialized["reserved_pages_after_cold_access"] == 0
    assert structural["resident_pages_after_cold_access"] == 2
    assert structural["reserved_pages_after_cold_access"] == 2
    assert report["comparison"]["resident_page_reduction"] == 2
    assert report["comparison"]["resident_byte_reduction"] == 512

    assert materialized["restore_state_preserved"] is True
    assert structural["restore_state_preserved"] is True
    assert materialized["restored_page_content_valid"] is True
    assert structural["restored_page_content_valid"] is True
    assert materialized["journal_valid_after_restore_fault"] is True
    assert structural["journal_valid_after_restore_fault"] is True
    assert materialized["post_restore_fault_resident_delta"] == 0
    assert structural["post_restore_fault_resident_delta"] == 1
    assert structural["post_restore_fault_receipt_verified"] is True
    assert structural["structural_range_read_event_count"] == 2
    assert structural["structural_coordinate_commitment_count"] == 2 * 256
    assert structural["provider_coordinate_receipt_count"] == 2 * 256
    assert structural["structural_registry_point_cache_entry_count"] == 0
    assert materialized["host_backing_cached_page_count_after_cold_access"] == 0
    assert materialized["host_backing_cached_page_bytes_after_cold_access"] == 0
    assert structural["host_backing_cached_page_count_after_cold_access"] == 2
    assert structural["host_backing_cached_page_bytes_after_cold_access"] == 2 * 256
    assert structural["host_backing_cached_receipt_coordinate_count_after_cold_access"] == 2 * 256
    assert structural["host_backing_cached_provider_coordinate_count_after_cold_access"] == 0
    assert structural["cache_probe_page_content_valid"] is True
    assert structural["host_backing_cached_reuse_count_after_probe"] >= 2
    assert structural["host_backing_cache_probe_hit_delta"] == 2
    assert structural["host_backing_cached_page_count_after_probe"] == 2
    assert structural["host_backing_cached_page_bytes_after_probe"] == 2 * 256
    assert structural["host_backing_cached_provider_coordinate_count_after_probe"] == 0
    assert structural["host_backing_cache_retention_policy"] == "measured_regeneration_cost_times_observed_reuse_per_byte"
    assert materialized["host_backing_cached_reuse_count_after_probe"] == 0
    assert structural["structural_registry_bytes"] > materialized["structural_registry_bytes"]
    # Compact range commitments reduce journal growth, but the generator,
    # certificate, structural registry, and inert page descriptors still have
    # a real checkpoint cost. At this small page geometry that cost can exceed
    # materializing a few hundred bytes, so record it rather than asserting
    # that every profile must have a smaller total checkpoint.
    assert structural["checkpoint_bytes"] > 0
    assert materialized["checkpoint_bytes"] > 0
    assert structural["page_backing_descriptor_bytes"] > materialized["page_backing_descriptor_bytes"]


def test_structural_memory_vm_pair_requires_cold_restore_page() -> None:
    with pytest.raises(ValueError, match="cold restore page"):
        benchmark_pair(
            page_size=256,
            virtual_pages=2,
            working_set_pages=2,
        )


def test_structural_memory_vm_pair_rejects_unsupported_page_geometry() -> None:
    with pytest.raises(ValueError, match="power of two"):
        benchmark_pair(page_size=300, virtual_pages=4, working_set_pages=2)
