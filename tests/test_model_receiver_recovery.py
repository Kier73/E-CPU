"""USM-005 hard-crash model-to-E-CPU recovery, quorum lineage and replay tests."""

from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest

from examples.model_receiver_recovery import (
    EXIT_AFTER_EFFECT_BEFORE_ACK, ModelRecoveryRefused,
    ModelRecoveryStore, run_demo,
)
from examples.model_system_calls import verify_system_call_trace
from mailcpu.structural_memory import StructuralMemoryRegistry


pytestmark = pytest.mark.skipif(
    shutil.which("openssl") is None,
    reason="OpenSSL command-line utility is required for real mTLS tests",
)


@pytest.fixture(scope="module")
def recovered_session(tmp_path_factory):
    """Run one actual hard-crash/resumption experiment for focused assertions."""
    root = tmp_path_factory.mktemp("usm005")
    report = run_demo(root)
    return root, report


def test_live_model_process_survives_receiver_hard_kill(recovered_session):
    """An unacknowledged model read is completed by a replacement receiver."""
    _root, report = recovered_session
    assert report["first_receiver_exit"] == EXIT_AFTER_EFFECT_BEFORE_ACK
    assert report["model_unchanged_process"] is True
    assert report["authenticated_reconnect"] is True
    assert report["read_pending_at_crash"] is True
    assert report["model_calls"] == ["observe", "propose", "read"]
    assert report["first_receiver_process"] != report["model_process"]
    assert report["replacement_receiver_process"] != report["model_process"]
    assert report["result"]["status"] == "complete"
    assert report["result"]["replayed_request_sequence"] == 3
    assert report["result"]["semantic_reentries"] == 0
    assert report["result"]["events"] == 3
    assert report["source_oracle_match"] is True
    assert report["result"]["first_quorum_generation"] == 1
    assert report["result"]["latest_quorum_generation"] == 2
    assert report["quorum_anchor_failure_domains"] == 1
    exported = report["independent_case"]
    assert exported["case"]["policy"] == "high-request"
    assert [decision["call"] for decision in exported["episode"]["decisions"]] == [
        "observe", "propose", "read"
    ]
    assert verify_system_call_trace(exported["episode"]["session"])
    assert exported["episode"]["session"]["events"][-1]["output"]["value"] == (
        7 + 201 + 5 * (10**12 + 137)
    ) % 97


def test_structural_ground_and_reliable_ack_cursor_restore_together(recovered_session):
    """Generation two contains the exact admitted Ground and ACK-completed channel."""
    root, report = recovered_session
    store = ModelRecoveryStore(root / "checkpoint")
    state, manifest = store.load()
    assert manifest.generation == 2
    assert state["incoming_channel"]["next_receive_sequence"] == 4
    assert state["outgoing_channel"]["next_sequence"] == 4
    assert state["phase"] == "complete"
    assert state["events"][-1]["call"]["op"] == "read"
    assert len(state["events"]) == 3
    assert state["events"][-1]["output"]["read_receipt_id"] == (
        report["result"]["read_receipt_id"]
    )
    registry = StructuralMemoryRegistry.from_snapshot(
        state["registry"],
        admission_policy=lambda _proposal: False,
    )
    version = registry.active_version(state["stream_id"])
    assert version is not None
    assert version.spec.digest == report["result"]["ground_digest"]
    assert registry.read_revision(
        state["stream_id"], 1, 10**12 + 137,
        context=state["context"],
    ).value == report["result"]["value"]


def test_stale_but_untampered_checkpoint_is_rejected_by_lineage(recovered_session):
    """A valid checkpoint from before the ACK cannot roll back generation two."""
    root, _report = recovered_session
    store = ModelRecoveryStore(root / "checkpoint")
    with pytest.raises(ModelRecoveryRefused, match="validation"):
        store.load(generation=1)


def test_tampering_checkpoint_bytes_fails_quorum_admission(recovered_session, tmp_path):
    """A hash-preserving filename cannot replace the sealed state payload."""
    root, _report = recovered_session
    copy = tmp_path / "corrupt-state"
    shutil.copytree(root / "checkpoint", copy)
    path = copy / "checkpoint-2.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["events"][-1]["output"]["value"] += 1
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    with pytest.raises(ModelRecoveryRefused, match="validation"):
        ModelRecoveryStore(copy).load()


def test_tampering_manifest_cannot_change_quorum_high_water(recovered_session, tmp_path):
    """A rewritten checkpoint manifest conflicts with its durable quorum root."""
    root, _report = recovered_session
    copy = tmp_path / "corrupt-manifest"
    shutil.copytree(root / "checkpoint", copy)
    path = copy / "manifest-2.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["capture_cut"] = "invented-recovery-cut"
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    with pytest.raises(ModelRecoveryRefused, match="validation"):
        ModelRecoveryStore(copy).load()
