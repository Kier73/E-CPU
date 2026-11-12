from __future__ import annotations

import json

import pytest

from mailcpu.journal import EventJournal
from mailcpu.stateful_transition import StatefulTransitionRuntime
from mailcpu.stateful_transition_trajectory import (
    FRAME_SCHEMA,
    MANIFEST_SCHEMA,
    StatefulTransitionTrajectoryError,
    export_stateful_transition_trajectory,
    restore_stateful_transition_trajectory,
    seek_stateful_transition_event,
)
from mailcpu.trajectory import TrajectoryReader
from mailcpu.transition_space import two_bit_counter_program


def _edited_program():
    """Build the counter revision used to create a same-tick revision frame."""
    return two_bit_counter_program().with_row_output(
        (0, 1, 1, 1),
        (1, 0),
        name="two-bit-counter.reset-exception.v1",
    )


def _runtime_with_revision() -> StatefulTransitionRuntime:
    """Build a runtime with step/revision/step/step events at logical times 1,1,2,3."""
    runtime = StatefulTransitionRuntime(two_bit_counter_program(), (0, 1))
    runtime.step({"advance": 0, "reset": 0})
    runtime.revise(_edited_program())
    runtime.step({"advance": 1, "reset": 1})
    runtime.step({"advance": 0, "reset": 0})
    return runtime


def test_trajectory_export_restores_runtime_and_validates_all_three_receipt_views(tmp_path):
    runtime = _runtime_with_revision()
    data_path = tmp_path / "transition.mtrj"
    index_path = tmp_path / "transition.mtrj.idx"
    manifest_path = tmp_path / "transition.manifest.json"

    manifest = export_stateful_transition_trajectory(
        runtime,
        data_path,
        index_path,
        manifest_path,
        stride=1,
    )

    assert manifest["schema"] == MANIFEST_SCHEMA
    assert manifest["trajectory"]["event_count"] == 4
    assert manifest["trajectory"]["tick"] == 3
    assert manifest["trajectory"]["revision"] == 1
    assert manifest["trajectory"]["journal_head_digest"] != "0" * 64

    journal = EventJournal()
    for event in runtime.events:
        payload = {
            key: value
            for key, value in event.items()
            if key not in ("sequence", "kind", "previous_event_digest", "event_digest")
        }
        journal.append(event["kind"], payload)
    assert journal.verify()
    assert journal.records()[-1].digest == manifest["trajectory"]["journal_head_digest"]

    with TrajectoryReader(data_path, index_path) as reader:
        assert reader.verify() == 4
        frames = []
        assert reader.replay(frames.append) == 4
    assert all(frame.payload["schema"] == FRAME_SCHEMA for frame in frames)
    assert [frame.payload["runtime_event"]["kind"] for frame in frames] == [
        "step",
        "revision",
        "step",
        "step",
    ]

    restored = restore_stateful_transition_trajectory(
        manifest_path,
        data_path,
        index_path,
    )
    assert restored.snapshot() == runtime.snapshot()
    assert restored.state == (1, 0)
    assert restored.tick == 3
    assert restored.revision == 1


@pytest.mark.parametrize("stride", [1, 64])
def test_trajectory_seek_lands_on_latest_event_at_a_revision_tick(tmp_path, stride):
    runtime = _runtime_with_revision()
    data_path = tmp_path / "seek.mtrj"
    index_path = tmp_path / "seek.mtrj.idx"
    manifest_path = tmp_path / "seek.manifest.json"
    export_stateful_transition_trajectory(
        runtime,
        data_path,
        index_path,
        manifest_path,
        stride=stride,
    )

    at_revision = seek_stateful_transition_event(data_path, index_path, 1)
    assert at_revision is not None
    assert at_revision["logical_time"] == 1
    assert at_revision["runtime_event"]["kind"] == "revision"
    assert at_revision["runtime_event"]["revision_after"] == 1

    after_revision = seek_stateful_transition_event(data_path, index_path, 2)
    assert after_revision is not None
    assert after_revision["logical_time"] == 2
    assert after_revision["runtime_event"]["kind"] == "step"
    assert after_revision["runtime_event"]["state_after"] == [1, 0]


def test_trajectory_restore_rejects_tampered_binary_frame_receipt(tmp_path):
    runtime = _runtime_with_revision()
    data_path = tmp_path / "tamper.mtrj"
    index_path = tmp_path / "tamper.mtrj.idx"
    manifest_path = tmp_path / "tamper.manifest.json"
    export_stateful_transition_trajectory(
        runtime,
        data_path,
        index_path,
        manifest_path,
        stride=1,
    )

    raw = bytearray(data_path.read_bytes())
    raw[-1] ^= 1
    data_path.write_bytes(raw)

    with pytest.raises(StatefulTransitionTrajectoryError, match="receipt or frame"):
        restore_stateful_transition_trajectory(manifest_path, data_path, index_path)


def test_trajectory_restore_rejects_tampered_manifest_metadata(tmp_path):
    runtime = _runtime_with_revision()
    data_path = tmp_path / "manifest.mtrj"
    index_path = tmp_path / "manifest.mtrj.idx"
    manifest_path = tmp_path / "manifest.json"
    export_stateful_transition_trajectory(
        runtime,
        data_path,
        index_path,
        manifest_path,
        stride=1,
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["trajectory"]["revision"] = 99
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True),
        encoding="utf-8",
    )
    with pytest.raises(StatefulTransitionTrajectoryError, match="manifest digest"):
        restore_stateful_transition_trajectory(manifest_path, data_path, index_path)


def test_empty_runtime_trajectory_round_trips_and_has_no_seekable_event(tmp_path):
    runtime = StatefulTransitionRuntime(two_bit_counter_program(), (0, 1))
    data_path = tmp_path / "empty.mtrj"
    index_path = tmp_path / "empty.mtrj.idx"
    manifest_path = tmp_path / "empty.manifest.json"

    manifest = export_stateful_transition_trajectory(
        runtime,
        data_path,
        index_path,
        manifest_path,
        stride=2,
    )
    assert manifest["trajectory"]["event_count"] == 0
    assert manifest["trajectory"]["receipt_head"] == "0" * 64
    assert manifest["trajectory"]["journal_head_digest"] == "0" * 64
    assert seek_stateful_transition_event(data_path, index_path, 0) is None

    restored = restore_stateful_transition_trajectory(
        manifest_path,
        data_path,
        index_path,
    )
    assert restored.snapshot() == runtime.snapshot()


def test_trajectory_seek_rejects_invalid_time_coordinates(tmp_path):
    runtime = _runtime_with_revision()
    data_path = tmp_path / "invalid-time.mtrj"
    index_path = tmp_path / "invalid-time.mtrj.idx"
    manifest_path = tmp_path / "invalid-time.manifest.json"
    export_stateful_transition_trajectory(
        runtime,
        data_path,
        index_path,
        manifest_path,
        stride=1,
    )

    with pytest.raises(StatefulTransitionTrajectoryError, match="non-negative integer"):
        seek_stateful_transition_event(data_path, index_path, -1)


def test_state_checkpoint_returns_state_and_active_model_revision_at_logical_time(tmp_path):
    runtime = _runtime_with_revision()
    data_path = tmp_path / "checkpoint.mtrj"
    index_path = tmp_path / "checkpoint.mtrj.idx"
    manifest_path = tmp_path / "checkpoint.manifest.json"
    export_stateful_transition_trajectory(
        runtime,
        data_path,
        index_path,
        manifest_path,
        stride=64,
    )

    at_revision = seek_stateful_transition_checkpoint(
        data_path,
        index_path,
        1,
    )
    assert at_revision is not None
    assert at_revision["schema"] == "mailcpu.stateful-transition-checkpoint.v1"
    assert at_revision["logical_time"] == 1
    assert at_revision["state"] == [0, 1]
    assert at_revision["revision"] == 1
    assert at_revision["event_kind"] == "revision"
    assert at_revision["program_digest"] == _edited_program().digest
    assert at_revision["model_digest"] != runtime.events[0]["model_digest"]
    assert at_revision["runtime_event_sequence"] == 2
    assert at_revision["trajectory_sequence"] == 1

    after_revision = seek_stateful_transition_checkpoint(
        data_path,
        index_path,
        2,
    )
    assert after_revision is not None
    assert after_revision["logical_time"] == 2
    assert after_revision["state"] == [1, 0]
    assert after_revision["revision"] == 1
    assert after_revision["event_kind"] == "step"
    assert after_revision["runtime_event_sequence"] == 3
    assert after_revision["trajectory_sequence"] == 2

    assert seek_stateful_transition_checkpoint(
        data_path,
        index_path,
        0,
    ) is None


def test_state_checkpoint_is_bound_to_the_runtime_event_and_trajectory_receipt(tmp_path):
    runtime = _runtime_with_revision()
    data_path = tmp_path / "checkpoint-provenance.mtrj"
    index_path = tmp_path / "checkpoint-provenance.mtrj.idx"
    manifest_path = tmp_path / "checkpoint-provenance.manifest.json"
    export_stateful_transition_trajectory(
        runtime,
        data_path,
        index_path,
        manifest_path,
        stride=64,
    )

    checkpoint = seek_stateful_transition_checkpoint(
        data_path,
        index_path,
        1,
    )
    assert checkpoint is not None
    event = seek_stateful_transition_event(data_path, index_path, 1)
    assert event is not None
    assert checkpoint["runtime_event_digest"] == event["runtime_event"]["event_digest"]
    assert checkpoint["trajectory_receipt"] == event["trajectory_receipt"]
    assert checkpoint["trajectory_sequence"] == event["trajectory_sequence"]
