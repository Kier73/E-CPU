"""Bounded auto-dispatch policy cannot extend execution beyond its intention."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from mailcpu import internet_quantum_continuation as continuation
from mailcpu import internet_intention_ingress as ingress

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "intentions/internet007/public-source-grounds.json"


@pytest.fixture
def manifest():
    return ingress.admit_manifest(json.loads(MANIFEST.read_text()))


def accepted_report(manifest, revision=1):
    count = len(manifest["nodes"])
    return {
        "schema": "mailcpu.internet007.report.v1",
        "intention_id": manifest["intention_id"],
        "manifest_digest": ingress.digest(manifest),
        "mode": "step",
        "previous_revision": revision - 1,
        "revision": revision,
        "operation": ingress.execution_order(manifest)[revision - 1],
        "state_digest": "f" * 64,
        "published_blob_sha": "d" * 40,
        "status": "complete" if revision == count else "recoverable",
        "max_cost_usd": 0,
        "authority": "owner-approved-manifest-and-Git-CAS-not-M3-quorum",
    }


def choose(manifest, report):
    return continuation.continuation_decision(
        manifest, report,
        repository="Kier73/E-CPU",
        ref="refs/heads/main",
        event_name="workflow_dispatch",
    )


def test_each_nonterminal_success_requests_only_one_next_runner(manifest):
    for revision in range(1, len(manifest["nodes"])):
        assert choose(manifest, accepted_report(manifest, revision))
    assert not choose(manifest, accepted_report(manifest, len(manifest["nodes"])))


@pytest.mark.parametrize("event,ref,repo", [
    ("pull_request", "refs/heads/main", "Kier73/E-CPU"),
    ("push", "refs/heads/untrusted", "Kier73/E-CPU"),
    ("schedule", "refs/heads/main", "outside/repository"),
])
def test_non_admitted_runner_context_cannot_dispatch(manifest, event, ref, repo):
    with pytest.raises(continuation.QuantumContinuationRefused):
        continuation.continuation_decision(
            manifest, accepted_report(manifest),
            repository=repo, ref=ref, event_name=event,
        )


@pytest.mark.parametrize("change", [
    "manifest_digest", "intention_id", "mode", "previous_revision",
    "revision", "operation", "published_blob_sha", "state_digest",
    "max_cost_usd", "authority", "status", "schema", "extra",
])
def test_altered_or_uncommitted_report_does_not_dispatch(manifest, change):
    report = accepted_report(manifest)
    if change == "manifest_digest":
        report[change] = "a" * 64
    elif change == "intention_id":
        report[change] = "other"
    elif change == "mode":
        report[change] = "initialize"
    elif change == "previous_revision":
        report[change] = 999
    elif change == "revision":
        report[change] = 5
    elif change == "operation":
        report[change] = "ground.join"
    elif change == "published_blob_sha":
        report[change] = None
    elif change == "state_digest":
        report[change] = "error"
    elif change == "max_cost_usd":
        report[change] = 1
    elif change == "authority":
        report[change] = "untrusted"
    elif change == "status":
        report[change] = "complete"
    elif change == "schema":
        report[change] = "v2"
    else:
        report[change] = "spoof"
    with pytest.raises(continuation.QuantumContinuationRefused):
        choose(manifest, report)


def test_second_intention_uses_its_own_length_and_operation_order():
    other = ingress.admit_manifest(json.loads(
        (MANIFEST.parent / "cross-source-structures.json").read_text()
    ))
    assert len(other["nodes"]) == 3
    assert choose(other, accepted_report(other, 1))
    assert choose(other, accepted_report(other, 2))
    assert not choose(other, accepted_report(other, 3))


def test_missing_required_fields_and_noninteger_revisions_fail_closed(manifest):
    value = accepted_report(manifest)
    del value["state_digest"]
    with pytest.raises(continuation.QuantumContinuationRefused):
        choose(manifest, value)
    value = accepted_report(manifest)
    value["revision"] = True
    with pytest.raises(continuation.QuantumContinuationRefused):
        choose(manifest, value)
    value = accepted_report(manifest)
    value["max_cost_usd"] = False
    with pytest.raises(continuation.QuantumContinuationRefused):
        choose(manifest, value)


def test_workflow_has_bounded_actions_dispatch_and_token_scope():
    text = (ROOT / ".github/workflows/internet-007-intentions.yml").read_text()
    assert "actions: write" in text
    assert 'steps.next.outputs.dispatch' in text
    assert 'continue-on-error: true' in text
    assert "internet-005-state-branch" in text
    assert "repos/${GITHUB_REPOSITORY}/actions/workflows/" in text
