"""USM-006: real mTLS authority processes across model-operated recovery."""

from __future__ import annotations

import json
import shutil

import pytest

from examples.model_distributed_lineage import (
    prepare_distributed_authorities, run_distributed_demo,
)
from examples.model_receiver_recovery import (
    GENESIS, MACHINE, ModelRecoveryRefused, ModelRecoveryStore,
)
from examples.run_model_authenticated_experiment import ephemeral_certificates
from mailcpu.recovery_lineage import RecoveryLineageError, RecoveryStateManifest
from mailcpu.seed_commit_quorum import SeedCommitMembership


pytestmark = pytest.mark.skipif(
    shutil.which("openssl") is None,
    reason="native mutually authenticated tests require OpenSSL",
)


@pytest.fixture(scope="module")
def distributed_model_result(tmp_path_factory):
    """Operate one crash/recovery with independent authority OS processes."""
    root = tmp_path_factory.mktemp("usm006-distributed-authorities")
    return root, run_distributed_demo(root)


def test_model_receives_original_ground_after_distributed_authority_reconnect(
    distributed_model_result,
):
    """The model sees one semantic Ground despite crash and authority reconnect."""
    _root, result = distributed_model_result
    baseline = result["recovered_model"]
    assert baseline["first_receiver_exit"] == 86
    assert baseline["model_unchanged_process"] is True
    assert baseline["read_pending_at_crash"] is True
    assert baseline["authenticated_reconnect"] is True
    assert baseline["result"]["semantic_reentries"] == 0
    assert baseline["result"]["events"] == 3
    assert baseline["result"]["first_quorum_generation"] == 1
    assert baseline["result"]["latest_quorum_generation"] == 2
    assert baseline["source_oracle_match"] is True
    assert result["authorities_survived_receiver_restart"] is True
    assert result["independent_os_authority_processes"] == 2
    assert result["single_physical_failure_domain"] is True
    assert result["offline_reconstructed_quorum_generation"] == 2


def test_native_authority_services_have_distinct_process_and_tls_identities(
    distributed_model_result,
):
    """B/C are two independent process participants, never pretend three hosts."""
    _root, report = distributed_model_result
    pids = report["authenticated_authority_processes"]
    assert set(pids) == {"B", "C"}
    assert pids["B"] != pids["C"]
    assert set(report["authenticated_authority_dns"]) == {"B", "C"}
    baseline = report["recovered_model"]
    assert not {pids["B"], pids["C"]} & {
        baseline["model_process"],
        baseline["first_receiver_process"],
        baseline["replacement_receiver_process"],
    }


def test_quorum_state_remains_independently_reconstructable_after_service_exit(
    distributed_model_result,
):
    """The owner and remote authority files reconstruct a common high-water."""
    root, report = distributed_model_result
    checkpoint = root / "checkpoint"
    assert not (checkpoint / "remote-authorities.json").exists()
    for member in ("A", "B", "C"):
        assert (checkpoint / f"anchor-{member}.jsonl").is_file()
    with pytest.raises(ModelRecoveryRefused, match="local fallback forbidden"):
        ModelRecoveryStore(checkpoint)
    offline = ModelRecoveryStore(checkpoint, offline_audit=True)
    state, manifest = offline.load()
    with pytest.raises(ModelRecoveryRefused, match="cannot seal"):
        offline.save(state, "unauthorized-offline-attempt")
    assert manifest.generation == 2
    assert manifest.state_digest == report["offline_reconstructed_state_digest"]
    assert state["phase"] == "complete"
    assert len(state["events"]) == 3
    assert state["events"][-1]["output"]["value"] == (
        7 + 201 + 5 * (10**12 + 137)
    ) % 97


def test_remote_lineage_configuration_rejects_changed_peer_identity(tmp_path):
    """Cannot treat an arbitrary network endpoint as the configured authority."""
    certificates = tmp_path / "certificates"
    certificates.mkdir()
    ephemeral_certificates(certificates)
    stop, _state = prepare_distributed_authorities(tmp_path, {})
    try:
        config_file = tmp_path / "checkpoint" / "remote-authorities.json"
        config = json.loads(config_file.read_text())
        config["members"]["B"]["dns"] = "forged-host.invalid"
        config_file.write_text(json.dumps(config), encoding="utf-8")
        with pytest.raises(ValueError, match="remote authority endpoint"):
            ModelRecoveryStore(tmp_path / "checkpoint")
    finally:
        stop()


def test_native_quorum_refuses_commit_when_all_remote_authorities_unreachable(
    tmp_path,
):
    """An owner journal alone cannot form a strict-majority recovery seal."""
    certificates = tmp_path / "certificates"
    certificates.mkdir()
    ephemeral_certificates(certificates)
    stop, _state = prepare_distributed_authorities(tmp_path, {})
    store = ModelRecoveryStore(tmp_path / "checkpoint")
    try:
        stop()
        membership = SeedCommitMembership(
            MACHINE, 1, ("A", "B", "C"), "A", 1, GENESIS
        )
        manifest = RecoveryStateManifest(
            machine_id=membership.system_id,
            incarnation=membership.incarnation,
            owner_id=membership.owner_id,
            owner_term=membership.owner_term,
            membership_digest=membership.digest,
            generation=1,
            predecessor_digest=GENESIS,
            state_digest="a" * 64,
            capture_cut="test-lost-all-remote-authority-links",
        )
        with pytest.raises(RecoveryLineageError, match="quorum"):
            store.lineage.seal(manifest)
    finally:
        store.close()
        stop()
