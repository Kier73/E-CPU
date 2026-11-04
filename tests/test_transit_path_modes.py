from __future__ import annotations

import hashlib
import json

import pytest

from mailcpu import TransitPathState, TransitPathStateError

MODULI = (101, 103, 107, 109, 113)


def _redigest(snapshot: dict) -> None:
    snapshot["digest"] = hashlib.sha256(
        json.dumps(
            snapshot["state"],
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def test_one_path_switches_memory_sensor_processor_and_back() -> None:
    path = TransitPathState("path-a")
    original = path.store(42, k=3, moduli=MODULI)
    assert path.read(original) == 42

    path.set_mode("sensor")
    path.record_round_trip(1, 1_000_000, 11_000_000)
    path.record_sample(3, 20_000)
    path.record_sample(2, 35_000)
    path.mark_lost(4)
    path.record_sample(4, 40_000)

    path.set_mode("processor")
    summary = path.summarize()
    assert summary.sample_count == 4
    assert summary.loss_count == 1
    assert summary.unresolved_loss_count == 0
    assert summary.recovered_count == 1
    assert summary.out_of_order_count == 1
    assert summary.gap_count == 1
    assert summary.mean_latency_us == 26_250
    assert summary.slot_interval_us > 1_000
    assert path.reduce_sensor_metric("out_of_order_count") == 1

    transformed = path.transform_group(original, "mul", 2)
    path.set_mode("memory")
    assert path.read(original) == 42
    assert path.read(transformed) == 84
    assert [entry["mode"] for entry in path.mode_history] == [
        "memory", "sensor", "processor", "memory"
    ]


def test_rrns_memory_survives_erasure_and_repair() -> None:
    path = TransitPathState("redundant-path")
    group_id = path.store(54_321, k=3, moduli=MODULI)
    path.mark_slot_lost(group_id, 1)
    path.mark_slot_lost(group_id, 3)
    assert path.read(group_id) == 54_321
    assert path.repair(group_id) == 54_321
    group = path.engine.groups[group_id]
    assert all(slot.alive for slot in group.slots)
    assert group.slots[1].version == 1
    assert group.slots[3].version == 1


def test_path_snapshot_round_trip_preserves_all_three_roles_and_state() -> None:
    path = TransitPathState("persistent-path")
    group_id = path.store(77, k=3, moduli=MODULI)
    path.set_mode("sensor")
    path.record_sample(1, 10_000)
    path.record_sample(2, 12_000)
    path.set_mode("processor")
    result_id = path.transform_group(group_id, "add", 8)

    snapshot = path.snapshot()
    restored = TransitPathState.from_snapshot(snapshot)
    assert restored.snapshot() == snapshot
    assert restored.path_id == "persistent-path"
    assert restored.mode == "processor"
    assert restored.logical_tick == path.logical_tick
    assert restored.engine.read_group(result_id) == (85, True)


def test_path_snapshot_rejects_digest_and_semantic_tampering() -> None:
    path = TransitPathState("tamper-path")
    group_id = path.store(45, k=3, moduli=MODULI)
    path.set_mode("sensor")
    path.record_sample(1, 15_000)

    snapshot = path.snapshot()
    snapshot["state"]["mode"] = "processor"
    with pytest.raises(TransitPathStateError, match="digest"):
        TransitPathState.from_snapshot(snapshot)

    snapshot = path.snapshot()
    snapshot["state"]["sensor_samples"][0]["out_of_order"] = True
    _redigest(snapshot)
    with pytest.raises(TransitPathStateError, match="derived flags"):
        TransitPathState.from_snapshot(snapshot)

    snapshot = path.snapshot()
    snapshot["state"]["engine"]["groups"][group_id]["slots"][4]["residue"] += 1
    _redigest(snapshot)
    with pytest.raises(TransitPathStateError, match="RRNS residues"):
        TransitPathState.from_snapshot(snapshot)


def test_modes_and_sensor_contract_are_explicit() -> None:
    path = TransitPathState("guarded-path")
    with pytest.raises(TransitPathStateError, match="sensor"):
        path.record_sample(1, 10)
    path.set_mode("sensor")
    with pytest.raises(TransitPathStateError, match="latency_us=None"):
        path.record_sample(1, 10, delivered=False)
    with pytest.raises(TransitPathStateError, match="cannot mark an already delivered"):
        path.record_sample(2, 10)
        path.mark_lost(2)
    with pytest.raises(TransitPathStateError, match="mode"):
        path.set_mode("host")


def test_path_mode_result_matches_conventional_buffer_and_worker_reference() -> None:
    reference_memory = {"input": 1234}
    reference_memory["output"] = reference_memory["input"] * 3 + 7

    path = TransitPathState("parity-path")
    source_id = path.store(1234, k=3, moduli=MODULI)
    path.set_mode("sensor")
    path.record_sample(1, 21_000)
    path.set_mode("processor")
    result_id = path.transform_group(source_id, "mul", 3)
    path.set_mode("memory")
    assert path.read(result_id) == reference_memory["input"] * 3
    path.set_mode("processor")
    final_id = path.transform_group(result_id, "add", 7)
    path.set_mode("memory")
    assert path.read(final_id) == reference_memory["output"]
    assert path.read(source_id) == reference_memory["input"]
    assert path.engine.slot_interval_s >= 3 * path.engine.jitter_s
