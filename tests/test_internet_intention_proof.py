"""Independent Git history, byte-identity, and hosted-run proof checks."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from mailcpu import internet_free_fabric as foundation
from mailcpu import internet_intention_ingress as ingress
from mailcpu import internet_intention_proof as proof
from mailcpu.computation_dag import NavigableComputationDAG

MANIFEST_PATH = (
    Path(__file__).resolve().parents[1] /
    "intentions/internet007/public-source-grounds.json"
)


@pytest.fixture
def manifest():
    return ingress.admit_manifest(json.loads(MANIFEST_PATH.read_text()))


def fake_source(url, validator, limit):
    assert limit <= ingress.MAX_REMOTE_BYTES
    if "/git/commits/" in url:
        sha = url.rsplit("/", 1)[-1]
        body = foundation.canonical({
            "sha": sha, "tree": {"sha": "c" * 40},
            "parents": [{"sha": "b" * 40}],
        })
        if validator == '"proof-etag-v1"':
            return 304, {}, b""
        return 200, {"etag": '"proof-etag-v1"'}, body
    if "/compare/" in url:
        return 200, {}, foundation.canonical({
            "merge_base_commit": {"sha": foundation.BASE},
            "ahead_by": 11, "behind_by": 0, "status": "ahead",
        })
    raise AssertionError("unexpected external service route")


def history_for(manifest):
    """Model separate native-DAG interpreters, not a real hosted-run proof."""
    state = ingress.genesis(manifest)
    entries = []
    def commit(state, revision):
        raw = foundation.canonical(state) + b"\n"
        sha = proof.GENESIS_COMMITS["public-source-grounds"] if revision == 0 else f"{revision:040x}"
        message = ("INTERNET-007: admitted public genesis" if revision == 0 else
                   f"INTERNET-007 {manifest['intention_id']} revision {revision} "
                   f"[run={100000+revision} attempt=1]")
        entries.append(proof.GitCheckpoint(
            sha, message, proof.git_blob_identity(raw), raw))
    commit(state, 0)
    dag = ingress.graph_template(manifest)
    for revision in range(1, len(manifest["nodes"]) + 1):
        operation = ingress.execute_one(manifest, dag, fake_source)
        assert operation is not None
        state = ingress.advance(manifest, state, dag)
        commit(state, revision)
        dag = NavigableComputationDAG.from_snapshot(state["dag"])
    return entries


def replace_entry(history, position, **changes):
    altered = list(history)
    previous = altered[position]
    fields = {"commit_sha": previous.commit_sha,
              "commit_message": previous.commit_message,
              "blob_sha": previous.blob_sha,
              "raw_bytes": previous.raw_bytes}
    fields.update(changes)
    altered[position] = proof.GitCheckpoint(**fields)
    return altered


def test_real_git_blob_digest_known_vector():
    assert proof.git_blob_identity(b"hello\n") == "ce013625030ba8dba906f756967f9e9ca394464a"


def test_sequence_of_distinct_native_dag_commits_qualifies_with_independent_run_callback(manifest):
    history = history_for(manifest)
    checked = []
    def verify(run_id, attempt):
        checked.append((run_id, attempt))
        return True
    report = proof.verify_history(manifest, history, run_verifier=verify)
    assert report["complete"] is True
    assert report["status"] == "verified-complete"
    assert report["observed_revisions"] == 5
    assert report["unique_workflow_run_claims"] == 5
    assert checked == [(100001 + i, 1) for i in range(5)]
    assert report["commit_chain"][0]["git_commit_sha"] == proof.GENESIS_COMMITS["public-source-grounds"]
    assert [r["committed_node"] for r in report["commit_chain"][1:]] == list(
        ingress.execution_order(manifest))
    assert len(report["digest"]) == 64


def test_git_history_without_external_run_verification_is_not_hosted_proof(manifest):
    report = proof.verify_history(manifest, history_for(manifest))
    assert report["complete"] is True
    assert report["status"] == "run-claims-unverified"
    assert report["run_metadata_verified"] is False


def test_incomplete_exact_history_reports_partial_evidence(manifest):
    partial = history_for(manifest)[:3]
    report = proof.verify_history(manifest, partial,
                                  run_verifier=lambda run_id, attempt: True)
    assert report["status"] == "verified-partial"
    assert report["observed_revisions"] == 2
    assert report["complete"] is False


@pytest.mark.parametrize("change", [
    "genesis-rebase", "skip-commit", "duplicate-run",
    "missing-run", "wrong-node", "changed-bytes", "changed-state",
    "bad-predecessor", "stale-revision",
])
def test_forged_or_incomplete_online_history_refuses(manifest, change):
    original = history_for(manifest)
    if change == "genesis-rebase":
        revised = replace_entry(original, 0, commit_sha="f" * 40)
    elif change == "skip-commit":
        revised = original[:2] + original[3:]
    elif change == "duplicate-run":
        revised = replace_entry(
            original, 3,
            commit_message=original[2].commit_message.replace("revision 2", "revision 3"))
    elif change == "missing-run":
        revised = replace_entry(original, 2,
                                commit_message="INTERNET-007 arbitrary checkpoint")
    elif change == "wrong-node":
        altered = json.loads(original[3].raw_bytes)
        altered["dag"]["state"]["commits"][0]["result"]["sha"] = "a" * 40
        raw = foundation.canonical(altered) + b"\n"
        revised = replace_entry(original, 3,
                                raw_bytes=raw, blob_sha=proof.git_blob_identity(raw))
    elif change == "changed-bytes":
        revised = replace_entry(original, 4, raw_bytes=original[4].raw_bytes + b" ")
    elif change == "changed-state":
        altered = json.loads(original[4].raw_bytes)
        altered["manifest_digest"] = "a" * 64
        raw = foundation.canonical(altered) + b"\n"
        revised = replace_entry(original, 4,
                                raw_bytes=raw, blob_sha=proof.git_blob_identity(raw))
    elif change == "bad-predecessor":
        altered = json.loads(original[3].raw_bytes)
        altered["previous_digest"] = "a" * 64
        altered["digest"] = ingress.digest({k: v for k, v in altered.items() if k != "digest"})
        raw = foundation.canonical(altered) + b"\n"
        revised = replace_entry(original, 3,
                                raw_bytes=raw, blob_sha=proof.git_blob_identity(raw))
    else:
        altered = json.loads(original[3].raw_bytes)
        altered["revision"] = 2
        altered["digest"] = ingress.digest({k: v for k, v in altered.items() if k != "digest"})
        raw = foundation.canonical(altered) + b"\n"
        revised = replace_entry(original, 3,
                                raw_bytes=raw, blob_sha=proof.git_blob_identity(raw))
    with pytest.raises((proof.ContinuityProofRefused, ValueError)):
        proof.verify_history(manifest, revised,
                             run_verifier=lambda run_id, attempt: True)


def test_unsupported_hosted_run_refuses_claim_of_continuity(manifest):
    with pytest.raises(proof.ContinuityProofRefused, match="independent successful"):
        proof.verify_history(manifest, history_for(manifest),
                             run_verifier=lambda run_id, attempt: False)


def test_commit_history_readback_pins_immutable_git_content(manifest, monkeypatch):
    history = history_for(manifest)
    entries = [{
        "sha": entry.commit_sha, "commit": {"message": entry.commit_message},
    } for entry in reversed(history)]
    by_commit = {item.commit_sha: item for item in history}
    observed = []
    def server(method, url, token=None, **kwargs):
        observed.append(url)
        if "/commits?" in url:
            return 200, {}, foundation.canonical(entries)
        if "/contents/" in url:
            sha = url.rsplit("ref=", 1)[-1]
            entry = by_commit[sha]
            return 200, {}, foundation.canonical({
                "encoding": "base64", "sha": entry.blob_sha,
                "content": __import__("base64").b64encode(entry.raw_bytes).decode(),
            })
        raise AssertionError("unadmitted audit URL")
    monkeypatch.setattr(foundation, "request", server)
    restored = proof.get_history("token", manifest)
    assert restored == history
    assert len(observed) == len(history) + 1
    assert all(url.startswith(foundation.API_BASE) for url in observed)


def test_github_actions_run_lookup_rejects_unfinished_and_different_workflows(monkeypatch):
    def server(method, url, token=None, **kwargs):
        return 200, {}, foundation.canonical({
            "id": 3434, "run_attempt": 1,
            "name": "INTERNET-007 native intention ingress",
            "head_branch": "main", "event": "schedule",
            "status": "completed", "conclusion": "success",
        })
    monkeypatch.setattr(foundation, "request", server)
    verify = proof.github_run_verifier("token")
    assert verify(3434, 1)
    assert not verify(3435, 1)
    assert not verify(3434, 2)
    def queued(method, url, token=None, **kwargs):
        return 200, {}, foundation.canonical({
            "id": 3434, "run_attempt": 1,
            "name": "INTERNET-007 native intention ingress",
            "head_branch": "main", "event": "schedule",
            "status": "queued", "conclusion": None,
        })
    monkeypatch.setattr(foundation, "request", queued)
    assert not verify(3434, 1)


def test_committed_manifest_publisher_records_hosted_run_id(manifest, monkeypatch):
    monkeypatch.setenv("GITHUB_RUN_ID", "909001")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "2")
    state = history_for(manifest)[1]
    saved = json.loads(state.raw_bytes)
    observed = []
    def server(method, url, token=None, *, data=None, **kwargs):
        observed.append(json.loads(data))
        return 200, {}, foundation.canonical({"content": {"sha": "a" * 40}})
    monkeypatch.setattr(foundation, "request", server)
    assert ingress.publish("token", manifest, saved, "b" * 40) == "a" * 40
    assert observed[0]["message"] == (
        "INTERNET-007 public-source-grounds revision 1 [run=909001 attempt=2]")
    assert observed[0]["sha"] == "b" * 40
    monkeypatch.delenv("GITHUB_RUN_ID")
    with pytest.raises(ingress.IntentionRefused, match="hosted workflow invocation"):
        ingress.publish("token", manifest, saved, "b" * 40)
