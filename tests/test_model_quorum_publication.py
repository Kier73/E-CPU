"""USM-008: real two-client mTLS publication governed by the native recovery quorum."""

from __future__ import annotations

import copy
import json
import shutil

import pytest

from examples.model_quorum_publication import (
    CANDIDATES, CLAIM_SCHEMA, ModelPublicationRefused, REQUEST_SCHEMA,
    QuorumPublicationGate, _strict_identity, run_quorum_publication,
    verified_ground,
)
from examples.model_receiver_recovery import (
    ModelRecoveryRefused, ModelRecoveryStore, PUBLICATION_SCHEMA, _restore,
)
from examples.model_ground_os import _digest
from mailcpu.structural_memory import StructuralMemoryRegistry


pytestmark = pytest.mark.skipif(
    shutil.which("openssl") is None,
    reason="real mutually authenticated MailCPU candidate channels require OpenSSL",
)


@pytest.fixture(scope="module")
def completed_publication(tmp_path_factory):
    root = tmp_path_factory.mktemp("usm008-authorized-publication")
    return root, run_quorum_publication(root)


def test_two_distinct_tls_candidates_fenced_by_one_existing_quorum(completed_publication):
    """One authentic model-result claimant wins and one must not publish."""
    _root, report = completed_publication
    recovered = report["recovered_model"]
    chosen = report["publication"]
    assert report["single_physical_failure_domain"] is True
    assert report["physical_independence_verified"] is False
    assert recovered["first_receiver_exit"] == 86
    assert recovered["model_unchanged_process"] is True
    assert recovered["result"]["semantic_reentries"] == 0
    assert recovered["result"]["latest_quorum_generation"] == 2
    assert chosen["quorum_generation"] == 3
    assert chosen["native_quorum_verified"] is True
    assert chosen["logical_publication_only"] is True
    assert chosen["idempotent_winner_replay_checked"] is True
    claims = chosen["candidate_claims"]
    assert set(x["owner_id"] for x in claims) == set(CANDIDATES)
    assert sorted(x["status"] for x in claims) == ["authorized", "superseded"]
    assert len(set(x["candidate_process"] for x in claims)) == 2
    assert all(x["candidate_process"] != recovered["model_process"] for x in claims)
    winner = next(x for x in claims if x["status"] == "authorized")
    loser = next(x for x in claims if x["status"] == "superseded")
    assert loser["publication"] is None
    assert winner["owner_id"] == chosen["publication_owner"]
    assert winner["publication"]["read_receipt_id"] == recovered["result"]["read_receipt_id"]
    assert winner["publication"]["ground_digest"] == recovered["result"]["ground_digest"]
    assert chosen["publication_value"] == (7 + 201 + 5 * (10**12 + 137)) % 97
    assert chosen["publication_manifest"]["capture_cut"] == (
        "after_quorum_publication_claim"
    )


def test_post_publication_generation_remains_a_restorable_ground(completed_publication):
    """The winner is embedded in a *recoverable* generation-three state."""
    root, report = completed_publication
    store = ModelRecoveryStore(root / "checkpoint", offline_audit=True)
    checkpoint, manifest = store.load()
    assert manifest.generation == 3
    assert checkpoint["schema"] == PUBLICATION_SCHEMA
    assert checkpoint["publication_claim"]["owner_id"] == (
        report["publication"]["publication_owner"]
    )
    assert checkpoint["publication_claim"]["trace_digest"] == (
        report["recovered_model"]["result"]["trace_digest"]
    )
    assert checkpoint["publication_claim"]["source_report_digest"] == (
        report["recovered_model"]["report_digest"]
    )
    restored = _restore(checkpoint)
    assert restored.ground_digest == report["recovered_model"]["result"]["ground_digest"]
    assert restored.trace()["trace_digest"] == report["recovered_model"]["result"]["trace_digest"]
    assert restored.registry.read_revision(
        restored.stream_id, restored.ground_revision, 10**12 + 137,
        context=restored.context,
    ).value == report["publication"]["publication_value"]
    with pytest.raises(ModelRecoveryRefused, match="cannot seal"):
        store.save(checkpoint, "offline-writer-not-authorized")


def test_valid_older_recovery_state_is_stale_after_publication(completed_publication):
    """The old Ground state is still intact, but cannot roll back publication."""
    root, _ = completed_publication
    store = ModelRecoveryStore(root / "checkpoint", offline_audit=True)
    with pytest.raises(ModelRecoveryRefused, match="validation"):
        store.load(generation=2)
    with pytest.raises(ModelRecoveryRefused, match="local fallback forbidden"):
        ModelRecoveryStore(root / "checkpoint")


def test_forged_ground_value_with_fresh_report_digest_is_refused(completed_publication):
    """A hash rewrite alone cannot override known observation-source truth."""
    _root, report = completed_publication
    forged = copy.deepcopy(report["recovered_model"])
    forged["result"]["value"] += 1
    forged["report_digest"] = _digest({
        k: value for k, value in forged.items() if k != "report_digest"
    })
    with pytest.raises(ModelPublicationRefused):
        verified_ground(forged)


def test_authenticated_identity_is_unique_and_bound_to_cert_san():
    """Only one explicitly named certificate identity can become a claimant."""
    assert _strict_identity({
        "subjectAltName": (("DNS", "candidate.model.local"),
                           ("DNS", "candidate-a.model.local"))
    }) == "replacement-a"
    with pytest.raises(ModelPublicationRefused, match="does not bind one"):
        _strict_identity({"subjectAltName": (("DNS", "candidate.model.local"),)})
    with pytest.raises(ModelPublicationRefused, match="does not bind one"):
        _strict_identity({
            "subjectAltName": (
                ("DNS", "candidate.model.local"),
                ("DNS", "candidate-a.model.local"),
                ("DNS", "candidate-b.model.local"),
            ),
        })
    with pytest.raises(ModelPublicationRefused, match="authorized claimant role"):
        _strict_identity({"subjectAltName": (("DNS", "candidate-a.model.local"),)})


def test_quorum_state_tampering_is_rejected_even_when_local_file_exists(
    completed_publication, tmp_path
):
    """The quorum high-water and state digest prevent local claim rewrites."""
    root, _report = completed_publication
    clone = tmp_path / "altered-quorum"
    shutil.copytree(root / "checkpoint", clone)
    state_path = clone / "checkpoint-3.json"
    state = json.loads(state_path.read_text())
    state["publication_claim"]["owner_id"] = (
        "replacement-a" if state["publication_claim"]["owner_id"] == "replacement-b"
        else "replacement-b"
    )
    state_path.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
    with pytest.raises(ModelRecoveryRefused, match="validation"):
        ModelRecoveryStore(clone, offline_audit=True).load()
