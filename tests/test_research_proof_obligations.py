"""USM-010: use E-CPU's formal navigation to classify real research blockers."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from examples.research_frontier import ResearchFrontierRefused, operate
from examples.research_frontier_worker import digest
from examples.research_proof_obligations import (
    _equality_certificate, evaluate_obligations, verify_obligations,
)
from test_research_frontier import observation, reseal

ARCHIVED = Path(__file__).resolve().parents[1] / (
    "examples/research_frontier_observation_2026_11_15.json"
)


def test_native_formal_constraint_exact_current_evidence_and_future_unknown():
    """A missing workflow is refuted *now*, never declared impossible later."""
    for required in range(1, 17):
        for accepted in range(required + 1):
            proof = _equality_certificate(accepted, required)
            assert proof["current_disposition"] == (
                "entailed" if accepted == required else "refuted"
            )
            assert proof["future_disposition"] == (
                "entailed" if accepted == required else "unknown"
            )
            assert proof["constraint"]["relation"] == "eq"
            assert proof["constraint"]["expression"]["terms"] == [
                ["successful_checks", 1]
            ]
            assert proof["constraint"]["expression"]["constant"] == -required


def test_real_archived_ci_evidence_yields_a_useful_research_obligation():
    """The source is actual captured GitHub metadata, not a hand-waved fixture."""
    source = json.loads(ARCHIVED.read_text(encoding="utf-8"))
    assert source["source"] == "github-api-https"
    assert len(source["items"]) == 9
    decision = operate(source)
    proof = evaluate_obligations(source, decision)
    assert verify_obligations(source, decision, proof)
    assert proof["selected_obligation"] == "ecpu-138"
    assert proof["selected_disposition"] == "refuted"
    assert proof["recommended_next_action"] == "investigate_queued_runner"
    assert proof["merge_authorized"] is False
    assert proof["github_state_mutated"] is False
    assert proof["native_dag_digest"] == decision["graph_snapshot"]["digest"]
    selected = next(i for i in proof["obligations"] if i["id"] == "ecpu-138")
    assert selected["ready_in_native_dag"] is True
    assert selected["eligible_for_advisory_selection"] is True
    assert selected["formal_verification"]["required_count"] == 2
    assert selected["formal_verification"]["current_success_count"] == 0
    assert selected["formal_verification"]["future_disposition"] == "unknown"
    assert len(selected["outstanding"]) == 2
    assert all(o["kind"] == "not_completed" for o in selected["outstanding"])
    assert all("github.com" in o["run_url"] for o in selected["outstanding"])
    assert len([i for i in proof["obligations"] if i["unresolved_ancestors"]]) == 7


def test_merged_and_green_parent_is_entailed_and_unblocks_next_task():
    """A native DAG commit requires observed checks AND an actual merge."""
    _config, source = observation()
    parent = source["items"][0]
    parent["merged"], parent["state"] = True, "closed"
    for run in parent["runs"]:
        run["status"], run["conclusion"] = "completed", "success"
    reseal(source)
    decision = operate(source)
    proof = evaluate_obligations(source, decision)
    old_parent = next(row for row in proof["obligations"] if row["id"] == "ecpu-138")
    next_child = next(row for row in proof["obligations"] if row["id"] == "ecpu-139")
    assert old_parent["formal_verification"]["current_disposition"] == "entailed"
    assert old_parent["committed_in_native_dag"] is True
    assert old_parent["eligible_for_advisory_selection"] is False
    assert next_child["ready_in_native_dag"] is True
    assert next_child["unresolved_ancestors"] == []
    assert decision["selected_pr"]["id"] == "ecpu-139"
    assert proof["merge_authorized"] is False


def test_green_but_unmerged_parent_cannot_satisfy_dependency():
    """Successful check evidence alone is not a merged ancestor commit."""
    _config, source = observation()
    for run in source["items"][0]["runs"]:
        run["status"], run["conclusion"] = "completed", "success"
    reseal(source)
    decision = operate(source)
    proof = evaluate_obligations(source, decision)
    parent = next(row for row in proof["obligations"] if row["id"] == "ecpu-138")
    dependent = next(row for row in proof["obligations"] if row["id"] == "ecpu-139")
    assert parent["formal_verification"]["current_disposition"] == "entailed"
    assert parent["committed_in_native_dag"] is False
    assert "ecpu-138" in dependent["unresolved_ancestors"]
    assert proof["merge_authorized"] is False


def test_cancelled_and_missing_evidence_can_never_entail_completion():
    """Canceled, absent, queued and neutral are never successful check proofs."""
    _config, source = observation()
    source["items"][0]["runs"][0]["status"] = "completed"
    source["items"][0]["runs"][0]["conclusion"] = "cancelled"
    source["items"][0]["runs"] = source["items"][0]["runs"][:1]
    reseal(source)
    decision = operate(source)
    proof = evaluate_obligations(source, decision)
    item = next(row for row in proof["obligations"] if row["id"] == "ecpu-138")
    assert item["formal_verification"]["current_disposition"] == "refuted"
    assert {o["kind"] for o in item["outstanding"]} == {
        "no_run", "completed_without_success"
    }
    assert item["formal_verification"]["future_disposition"] == "unknown"


def test_tampered_proof_or_recomputed_outer_digest_is_not_enough():
    """An external observer can reproduce the certificate from the source."""
    _config, source = observation()
    decision = operate(source)
    result = evaluate_obligations(source, decision)
    fake = copy.deepcopy(result)
    fake["obligations"][0]["formal_verification"]["current_disposition"] = "entailed"
    fake["report_digest"] = digest({
        key: value for key, value in fake.items() if key != "report_digest"
    })
    assert not verify_obligations(source, decision, fake)
    assert verify_obligations(source, decision, result)


def test_changed_source_after_decision_invalidates_research_proof():
    """A recorded model decision never automatically authorizes later state."""
    _config, source = observation()
    decision = operate(source)
    altered = copy.deepcopy(source)
    altered["items"][0]["runs"][0]["status"] = "completed"
    altered["items"][0]["runs"][0]["conclusion"] = "success"
    reseal(altered)
    with pytest.raises(ResearchFrontierRefused, match="cannot be reconstructed"):
        evaluate_obligations(altered, decision)
