"""USM-009: native computation-DAG research frontier and model refusal cases."""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys

import pytest

from examples.research_frontier import (
    ResearchFrontierRefused,
    _adviser_prompt,
    build_research_dag,
    check_status,
    operate,
    validate_evidence,
    validated_config,
    verify_research_report,
)
from examples.research_frontier_worker import advise, digest
from mailcpu.computation_dag import ComputationDAGError

RESEARCH = [
    ("ecpu-138", "Kier73/E-CPU", 138, (), "use-system/model-ground-os-001"),
    ("ecpu-139", "Kier73/E-CPU", 139, ("ecpu-138",), "use-system/model-syscalls-002"),
    ("ecpu-140", "Kier73/E-CPU", 140, ("ecpu-139",), "use-system/model-authenticated-fabric-004"),
    ("ecpu-141", "Kier73/E-CPU", 141, ("ecpu-140",), "use-system/model-recovery-005"),
    ("ecpu-142", "Kier73/E-CPU", 142, ("ecpu-141",), "use-system/model-distributed-lineage-006"),
    ("ecpu-143", "Kier73/E-CPU", 143, ("ecpu-142",), "use-system/model-quorum-publication-008"),
    ("ifs-229", "Kier73/In-Formation-Space", 229, (), "use-system/model-op-independent-001"),
    ("ifs-231", "Kier73/In-Formation-Space", 231, ("ifs-229",), "use-system/model-recovery-independent-005"),
    ("ifs-232", "Kier73/In-Formation-Space", 232, ("ifs-231",), "use-system/model-route-fencing-007"),
]
WORKFLOW = {
    "ecpu-138": "USM-001 model-operated E-CPU",
    "ecpu-139": "USM-002 model-issued E-CPU system calls",
    "ecpu-140": "USM-004 authenticated model-operated E-CPU",
    "ecpu-141": "USM-005 model receiver recovery before lost ACK",
    "ecpu-142": "USM-006 native distributed model recovery lineage",
    "ecpu-143": "USM-008 quorum-fenced model Ground publication",
    "ifs-229": "USM-003 independently reconstructed model-operated E-CPU",
    "ifs-231": "USM-005 independent observer of recovered model Ground",
    "ifs-232": "USM-007 fenced model result publication via existing IFS route epochs",
}


def observation() -> tuple[dict, dict]:
    """Representative observed stack with all required jobs still queued."""
    items = []
    config = []
    branch = {key: head for key, _, _, _, head in RESEARCH}
    for i, (key, repo, number, requires, head_ref) in enumerate(RESEARCH, 1):
        workflows = [WORKFLOW[key], "verify" if key.startswith("ecpu") else "Encounter envelope tests"]
        config.append({"id": key, "repo": repo, "number": number,
                       "requires": list(requires), "required_workflows": workflows})
        item = {
            **config[-1],
            "url": f"https://github.com/{repo}/pull/{number}",
            "head_sha": f"{i:040x}",
            "head_ref": head_ref,
            "base": branch[requires[0]] if requires else "main",
            "state": "open", "merged": False, "runs": [],
        }
        for index, workflow in enumerate(workflows):
            run_id = 10_000 + i * 10 + index
            item["runs"].append({
                "workflow": workflow, "id": run_id,
                "head_sha": item["head_sha"],
                "status": "queued", "conclusion": None,
                "url": f"https://github.com/{repo}/actions/runs/{run_id}",
                "created_at": "2026-11-14T23:00:00Z",
            })
        items.append(item)
    evidence = {
        "schema": "mailcpu.research-frontier-evidence.v1",
        "source": "fixture",
        "observed_at": "2026-11-14T23:00:00Z",
        "items": items,
    }
    evidence["evidence_digest"] = digest(evidence)
    return {"schema": "mailcpu.research-frontier-config.v1", "items": config}, evidence


def reseal(evidence):
    evidence["evidence_digest"] = digest({
        k: v for k, v in evidence.items() if k != "evidence_digest"
    })


def test_real_stacked_topology_uses_native_ecpu_dag_and_model_worker():
    config, evidence = observation()
    assert len(validated_config(config)) == 9
    validate_evidence(evidence, config)
    result = operate(evidence)
    assert result["selected_pr"]["id"] == "ecpu-138"
    assert result["recommended_action"] == "monitor_queued_verification"
    assert result["merge_authorized"] is False
    assert result["github_state_mutated"] is False
    assert result["source"] == "fixture"
    assert [item["id"] for item in result["frontier"]] == ["ecpu-138", "ifs-229"]
    assert len(result["blocked"]) == 7
    assert result["selected_pr"]["check_status"] == "queued"
    assert result["advice"]["policy"] == "mailcpu.research-frontier.linear-policy.v1"
    assert verify_research_report(evidence, result)
    assert result["graph_snapshot"]["format"] == (
        "mailcpu-navigable-computation-dag-v1"
    )


def test_model_proposal_does_not_unlock_blocked_dependency():
    _config, evidence = observation()
    graph, records, statuses = build_research_dag(evidence)
    prompt = _adviser_prompt(graph, records, statuses, evidence)
    advice = advise(prompt)
    advice["selected_id"] = "ecpu-143"
    advice["advice_digest"] = digest({
        k: v for k, v in advice.items() if k != "advice_digest"
    })
    with pytest.raises(ResearchFrontierRefused, match="outside the native"):
        operate(evidence, proposed_advice=advice)


def test_model_cannot_authorize_merge_when_jobs_are_queued():
    _config, evidence = observation()
    graph, records, statuses = build_research_dag(evidence)
    advice = advise(_adviser_prompt(graph, records, statuses, evidence))
    advice["action"] = "review_verified_change"
    advice["advice_digest"] = digest({
        k: v for k, v in advice.items() if k != "advice_digest"
    })
    with pytest.raises(ResearchFrontierRefused, match="not authorized"):
        operate(evidence, proposed_advice=advice)


def test_verified_but_unmerged_parent_does_not_unblock_descendants():
    _config, evidence = observation()
    parent = evidence["items"][0]
    for run in parent["runs"]:
        run["status"], run["conclusion"] = "completed", "success"
    reseal(evidence)
    result = operate(evidence)
    assert result["selected_pr"]["id"] == "ecpu-138"
    assert result["recommended_action"] == "review_verified_change"
    assert "ecpu-139" in {item["id"] for item in result["blocked"]}
    assert result["merge_authorized"] is False


def test_only_a_verified_and_merged_parent_commits_ecpu_dependency():
    _config, evidence = observation()
    parent = evidence["items"][0]
    parent["state"], parent["merged"] = "closed", True
    for run in parent["runs"]:
        run["status"], run["conclusion"] = "completed", "success"
    reseal(evidence)
    graph, _, _ = build_research_dag(evidence)
    assert graph.committed_nodes == ("ecpu-138",)
    assert {node.node_id for node in graph.ready_nodes()} == {"ecpu-139", "ifs-229"}
    result = operate(evidence)
    assert result["selected_pr"]["id"] == "ecpu-139"
    assert verify_research_report(evidence, result)


def test_exact_head_sha_gates_the_reported_workflow():
    _config, evidence = observation()
    evidence["items"][0]["runs"][0]["head_sha"] = "f" * 40
    reseal(evidence)
    with pytest.raises(ResearchFrontierRefused, match="exact PR HEAD"):
        operate(evidence)


def test_closed_unmerged_change_is_not_an_actionable_root():
    _config, evidence = observation()
    parent = evidence["items"][0]
    parent["state"], parent["merged"] = "closed", False
    reseal(evidence)
    result = operate(evidence)
    assert result["selected_pr"]["id"] == "ifs-229"
    excluded = {record["id"]: record for record in result["blocked"]}
    assert excluded["ecpu-138"]["closed_unmerged"] is True
    assert "ecpu-139" in excluded


def test_forged_actual_base_branch_is_refused_even_if_outer_hash_recomputed():
    config, evidence = observation()
    evidence["items"][1]["base"] = "invented-upstream-owner"
    reseal(evidence)
    with pytest.raises(ResearchFrontierRefused, match="actual|stacked PR base"):
        validate_evidence(evidence, config)


def test_no_omitted_or_neutral_workflow_is_green():
    _config, evidence = observation()
    parent = evidence["items"][0]
    parent["runs"] = parent["runs"][:1]
    parent["runs"][0]["status"], parent["runs"][0]["conclusion"] = "completed", "success"
    assert check_status(parent)[0] == "missing"
    parent["runs"].append({
        "workflow": parent["required_workflows"][1],
        "id": 1111, "head_sha": parent["head_sha"], "status": "completed",
        "conclusion": "skipped",
        "url": f"https://github.com/{parent['repo']}/actions/runs/1111",
        "created_at": "2026-11-14T23:01:00Z"
    })
    assert check_status(parent)[0] == "failed"
    parent["runs"][-1]["conclusion"] = "cancelled"
    assert check_status(parent)[0] == "cancelled"


def test_aged_hosted_queue_becomes_an_investigation_not_a_duplicate_dispatch():
    """A genuinely old queued workflow creates a useful research blocker."""
    _config, evidence = observation()
    evidence["observed_at"] = "2026-11-15T01:00:00Z"
    reseal(evidence)
    report = operate(evidence)
    assert report["selected_pr"]["id"] == "ecpu-138"
    assert report["recommended_action"] == "investigate_queued_runner"
    assert report["selected_pr"]["check_status"] == "stalled_queued"
    assert len(report["selected_pr"]["workflow_runs"]) == 2
    assert verify_research_report(evidence, report)


def test_report_tampering_and_model_digest_mismatch_are_detected():
    _config, evidence = observation()
    report = operate(evidence)
    broken = copy.deepcopy(report)
    broken["recommended_action"] = "review_verified_change"
    assert not verify_research_report(evidence, broken)
    broken = copy.deepcopy(report)
    broken["advice"]["selected_id"] = "ifs-229"
    broken["advice"]["advice_digest"] = digest({
        k: v for k, v in broken["advice"].items() if k != "advice_digest"
    })
    broken["report_digest"] = digest({
        k: v for k, v in broken.items() if k != "report_digest"
    })
    assert not verify_research_report(evidence, broken)


def test_source_config_rejects_cycles_as_real_ecpu_dag_constraint():
    _config, evidence = observation()
    evidence["items"][0]["requires"] = ["ecpu-143"]
    evidence["items"][0]["base"] = evidence["items"][5]["head_ref"]
    reseal(evidence)
    with pytest.raises(ComputationDAGError, match="cycle|cyclic"):
        build_research_dag(evidence)


def test_standalone_model_worker_rejects_bad_prompt_without_merge_privilege():
    proc = subprocess.run(
        [sys.executable, "-m", "examples.research_frontier_worker"],
        input=json.dumps({"schema": "invented", "frontier": []}),
        capture_output=True, text=True, timeout=8, check=False,
    )
    assert proc.returncode != 0
    assert "invalid research adviser prompt" in proc.stderr
