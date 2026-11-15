"""USM-009: E-CPU navigates *real repository verification work*.

The work itself is a real development goal: identify the earliest open
experiment that can be safely verified from current GitHub evidence, without
mistaking an unexecuted check for success. Existing NavigableComputationDAG
owns dependency readiness and immutable evidence commits. A separate bounded
advisory-model process chooses from the actual ready frontier. The receiver
revalidates every choice and never grants a merge.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Mapping
from urllib.request import Request, urlopen

from mailcpu.computation_dag import ComputationNode, NavigableComputationDAG
from examples.research_frontier_worker import REQUEST, RESPONSE, POLICY, digest

SCHEMA = "mailcpu.research-frontier-evidence.v1"
REPORT = "mailcpu.research-frontier-result.v1"
SHA = re.compile(r"^[0-9a-f]{40}$")
IDENTITY = re.compile(r"^[a-z][a-z0-9-]{2,80}$")
GITHUB_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
STATUS_TO_ACTION = {
    "failed": "investigate_failure",
    "missing": "collect_verification",
    "queued": "run_verification",
    "in_progress": "inspect_running_verification",
    "verified": "review_verified_change",
}


class ResearchFrontierRefused(ValueError):
    """Evidence or model instruction is not admissible to the research host."""


def require(condition: bool, why: str) -> None:
    """Refuse an ungrounded, unsafe, or malformed research result."""
    if not condition:
        raise ResearchFrontierRefused(why)


def validated_config(config: Any) -> list[dict[str, Any]]:
    """Require a bounded, explicitly reviewed research-dependency declaration."""
    require(isinstance(config, dict) and set(config) == {"schema", "items"}
            and config["schema"] == "mailcpu.research-frontier-config.v1"
            and isinstance(config["items"], list)
            and 0 < len(config["items"]) <= 64, "invalid research configuration")
    items = config["items"]
    ids = set()
    for item in items:
        require(isinstance(item, dict) and set(item) == {
            "id", "repo", "number", "requires", "required_workflows"
        }, "invalid research item")
        require(type(item["id"]) is str and IDENTITY.fullmatch(item["id"]) is not None
                and item["id"] not in ids, "duplicate or malformed research identity")
        ids.add(item["id"])
        require(type(item["repo"]) is str and GITHUB_REPO.fullmatch(item["repo"]) is not None
                and type(item["number"]) is int and item["number"] > 0,
                "invalid GitHub PR reference")
        require(isinstance(item["requires"], list)
                and all(type(d) is str for d in item["requires"])
                and len(item["requires"]) == len(set(item["requires"])),
                "invalid research dependency list")
        require(isinstance(item["required_workflows"], list)
                and 0 < len(item["required_workflows"]) <= 16
                and all(type(w) is str and w.strip() and len(w) < 150
                        for w in item["required_workflows"])
                and len(item["required_workflows"]) == len(set(item["required_workflows"])),
                "missing or invalid required verification workflows")
    for item in items:
        require(all(dep in ids and dep != item["id"] for dep in item["requires"]),
                "unknown or self-referential research dependency")
    return items


def _github_json(path: str) -> Any:
    """Read only public repository metadata over HTTPS; never write GitHub state."""
    import urllib.error
    token = os.environ.get("GITHUB_TOKEN")
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "mailcpu-research-frontier-observer",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = "Bearer " + token
    request = Request("https://api.github.com" + path, headers=headers)
    with urlopen(request, timeout=15) as response:
        return json.load(response)


def observe_live(config: Mapping[str, Any]) -> dict[str, Any]:
    """Bind the actual current PR HEAD to the newest run for each workflow."""
    from datetime import datetime, timezone
    items = validated_config(config)
    observations = []
    for item in items:
        repo, number = item["repo"], item["number"]
        pr = _github_json(f"/repos/{repo}/pulls/{number}")
        require(isinstance(pr, dict) and pr.get("number") == number,
                "GitHub PR endpoint returned an unrelated object")
        head_sha = pr["head"]["sha"]
        require(type(head_sha) is str and SHA.fullmatch(head_sha) is not None,
                "invalid GitHub PR HEAD")
        branch = pr["head"]["ref"]
        # Explicit head SHA check on every run; the branch may be shared
        # by multiple pull requests or receive commits during observation.
        from urllib.parse import quote
        runs = _github_json(
            f"/repos/{repo}/actions/runs?branch={quote(branch, safe='')}&per_page=100"
        )["workflow_runs"]
        selected = {}
        for run in runs:
            if run["head_sha"] != head_sha or run["name"] not in item["required_workflows"]:
                continue
            name = run["name"]
            if name not in selected or (run["created_at"], run["id"]) > (
                selected[name]["created_at"], selected[name]["id"]
            ):
                selected[name] = run
        recorded = [{
            "workflow": name, "id": run["id"], "head_sha": run["head_sha"],
            "status": run["status"], "conclusion": run["conclusion"],
            "url": run["html_url"], "created_at": run["created_at"],
        } for name, run in sorted(selected.items())]
        observations.append({
            **item,
            "url": pr["html_url"], "head_sha": head_sha,
            "base": pr["base"]["ref"], "head_ref": branch,
            "state": pr["state"],
            "merged": pr["merged_at"] is not None,
            "runs": recorded,
        })
    core = {
        "schema": SCHEMA, "source": "github-api-https",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "items": observations,
    }
    return {**core, "evidence_digest": digest(core)}


def validate_evidence(evidence: Any, config: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    """Treat reported statuses as *observations*, not as execution grants."""
    require(isinstance(evidence, dict) and set(evidence) == {
        "schema", "source", "observed_at", "items", "evidence_digest"
    } and evidence["schema"] == SCHEMA
    and evidence["source"] in {"github-api-https", "fixture"}
    and type(evidence["observed_at"]) is str
    and isinstance(evidence["items"], list)
    and len(evidence["items"]) > 0,
    "invalid research evidence envelope")
    require(digest({k: v for k, v in evidence.items() if k != "evidence_digest"})
            == evidence["evidence_digest"], "research evidence digest mismatch")
    if config is not None:
        expected_items = validated_config(config)
        expected = {item["id"]: item for item in expected_items}
    else:
        expected = None
    ids = set()
    for item in evidence["items"]:
        require(isinstance(item, dict) and set(item) == {
            "id", "repo", "number", "requires", "required_workflows",
            "url", "head_sha", "base", "head_ref", "state", "merged", "runs"
        }, "malformed source PR observation")
        key = item["id"]
        require(type(key) is str and IDENTITY.fullmatch(key) is not None and key not in ids,
                "duplicate or malformed PR observation")
        ids.add(key)
        if expected is not None:
            require(key in expected
                    and all(item[k] == expected[key][k] for k in expected[key]),
                    "observed PR does not match configured research intention")
        require(type(item["repo"]) is str and GITHUB_REPO.fullmatch(item["repo"]) is not None
                and type(item["number"]) is int and item["number"] > 0
                and type(item["head_sha"]) is str and SHA.fullmatch(item["head_sha"]) is not None
                and type(item["base"]) is str and item["base"]
                and type(item["head_ref"]) is str and item["head_ref"]
                and item["state"] in {"open", "closed"}
                and type(item["merged"]) is bool
                and (not item["merged"] or item["state"] == "closed"),
                "invalid GitHub PR identity or lifecycle")
        require(item["url"] == f"https://github.com/{item['repo']}/pull/{item['number']}",
                "PR reference URL does not agree with source identity")
        require(type(item["required_workflows"]) is list
                and item["required_workflows"]
                and len(item["required_workflows"]) == len(set(item["required_workflows"]))
                and type(item["requires"]) is list
                and len(item["requires"]) == len(set(item["requires"])),
                "invalid required workflow or predecessor set")
        seen = set()
        require(isinstance(item["runs"], list), "invalid workflow records")
        for run in item["runs"]:
            require(isinstance(run, dict) and set(run) == {
                "workflow", "id", "head_sha", "status", "conclusion", "url", "created_at"
            } and run["workflow"] in item["required_workflows"]
            and run["workflow"] not in seen
            and type(run["id"]) is int and run["id"] > 0
            and run["head_sha"] == item["head_sha"]
            and run["status"] in {"queued", "in_progress", "completed", "waiting", "requested", "pending"}
            and (run["conclusion"] is None or run["conclusion"] in {
                "success", "failure", "cancelled", "timed_out", "action_required",
                "neutral", "skipped", "stale", "startup_failure"
            }) and type(run["created_at"]) is str
            and run["url"] == f"https://github.com/{item['repo']}/actions/runs/{run['id']}",
            "workflow does not match exact PR HEAD or canonical URL")
            seen.add(run["workflow"])
    require(len(ids) <= 64 and all(
        dep in ids and dep != item["id"]
        for item in evidence["items"] for dep in item["requires"]
    ), "source research dependency is unresolved")
    if expected is not None:
        require(set(expected) == ids, "missing configured research observation")
    indexed = {item["id"]: item for item in evidence["items"]}
    for item in evidence["items"]:
        for dependency in item["requires"]:
            parent = indexed[dependency]
            if parent["repo"] == item["repo"]:
                require(item["base"] == parent["head_ref"],
                        "stacked PR base does not match configured predecessor branch")
    return list(evidence["items"])


def check_status(item: Mapping[str, Any]) -> tuple[str, int]:
    """No absent, skipped, neutral, cancelled or queued run ever means green."""
    observed = {run["workflow"]: run for run in item["runs"]}
    required = item["required_workflows"]
    present = [observed[name] for name in required if name in observed]
    complete = sum(run["status"] == "completed" and run["conclusion"] == "success"
                   for run in present)
    if len(present) != len(required):
        return "missing", complete
    if complete == len(required):
        return "verified", complete
    if any(run["status"] == "completed" and run["conclusion"] not in {"success", "cancelled"}
           for run in present):
        return "failed", complete
    if any(run["status"] == "in_progress" for run in present):
        return "in_progress", complete
    return "queued", complete


def build_research_dag(evidence: Mapping[str, Any]) -> tuple[
    NavigableComputationDAG, dict[str, dict[str, Any]], dict[str, str]
]:
    """Reuse native E-CPU predecessor readiness for *real* PR observations."""
    items = validate_evidence(evidence)
    records = {item["id"]: item for item in items}
    statuses = {key: check_status(item)[0] for key, item in records.items()}
    nodes = [
        ComputationNode(
            node_id=item["id"], revision=1,
            operation="verify-public-research-artifact",
            resource=item["url"],
            context_digest=evidence["evidence_digest"],
            dependencies=item["requires"],
            payload={
                "head_sha": item["head_sha"],
                "state": item["state"],
                "merged": item["merged"],
                "status": statuses[item["id"]],
                "required_workflows": item["required_workflows"],
            },
        )
        for item in items
    ]
    graph = NavigableComputationDAG(nodes)
    # A dependency is a *verified and merged* antecedent. Merely green or
    # merely merged does not unlock descendants for merge-readiness review.
    while True:
        ready = graph.ready_nodes()
        completed = [
            node for node in ready
            if records[node.node_id]["merged"] and statuses[node.node_id] == "verified"
        ]
        if not completed:
            break
        for node in completed:
            graph.commit(node.node_id, {
                "accepted_head_sha": records[node.node_id]["head_sha"],
                "status": "verified-and-merged",
                "source_evidence_digest": evidence["evidence_digest"],
            })
    return graph, records, statuses


def _descendants(item_id: str, records: Mapping[str, Mapping[str, Any]]) -> int:
    """Count transitive dependent research operations, not arbitrary node weight."""
    seen: set[str] = set()
    todo = [item_id]
    while todo:
        current = todo.pop()
        for key, item in records.items():
            if current in item["requires"] and key not in seen:
                seen.add(key)
                todo.append(key)
    return len(seen)


def _adviser_prompt(
    graph: NavigableComputationDAG,
    records: Mapping[str, Mapping[str, Any]],
    statuses: Mapping[str, str],
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    frontier = []
    for node in graph.ready_nodes():
        item = records[node.node_id]
        if item["state"] == "closed" and not item["merged"]:
            # A closed, unmerged PR is not a runnable or mergeable operation.
            continue
        status, count = check_status(item)
        frontier.append({
            "id": node.node_id, "status": status,
            "descendants": _descendants(node.node_id, records),
            "required_checks": len(item["required_workflows"]),
            "completed_checks": count,
        })
    return {
        "schema": REQUEST,
        "intent": "verify-next-safe-research-operation",
        "graph_digest": graph.digest,
        "evidence_digest": evidence["evidence_digest"],
        "frontier": frontier,
    }


def _run_adviser(prompt: Mapping[str, Any]) -> dict[str, Any]:
    """Isolate advisory inference from the trusted E-CPU readiness decision."""
    safe_env = {
        name: value for name, value in os.environ.items()
        if name in {"PATH", "PYTHONPATH", "SYSTEMROOT", "WINDIR", "VIRTUAL_ENV", "HOME"}
    }
    completed = subprocess.run(
        [sys.executable, "-m", "examples.research_frontier_worker"],
        input=json.dumps(prompt, sort_keys=True, separators=(",", ":"), allow_nan=False),
        capture_output=True, text=True, env=safe_env, timeout=8, check=False,
    )
    require(completed.returncode == 0 and len(completed.stdout) < 4096,
            "advisory model did not provide a bounded decision")
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ResearchFrontierRefused("advisory worker did not return typed JSON") from exc


def operate(
    evidence: Mapping[str, Any],
    *,
    proposed_advice: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Use a model proposal while E-CPU preserves verification and action authority."""
    graph, records, statuses = build_research_dag(evidence)
    prompt = _adviser_prompt(graph, records, statuses, evidence)
    require(bool(prompt["frontier"]), "no outstanding research operation is ready")
    advice = dict(proposed_advice) if proposed_advice is not None else _run_adviser(prompt)
    require(set(advice) == {
        "schema", "policy", "prompt_digest", "selected_id", "action", "score",
        "advice_digest"
    } and advice["schema"] == RESPONSE and advice["policy"] == POLICY
    and advice["prompt_digest"] == digest(prompt)
    and advice["advice_digest"] == digest({
        k: v for k, v in advice.items() if k != "advice_digest"
    }), "model proposal is not bound to the observed research frontier")
    available = {item["id"]: item for item in prompt["frontier"]}
    require(type(advice["selected_id"]) is str and advice["selected_id"] in available,
            "model selected an operation outside the native DAG readiness frontier")
    selected = available[advice["selected_id"]]
    require(advice["action"] == STATUS_TO_ACTION[selected["status"]],
            "model requested an operation not authorized by its actual CI state")
    require(type(advice["score"]) is int, "adviser returned an invalid ranking score")
    selected_record = records[selected["id"]]
    actionable = {entry["id"] for entry in prompt["frontier"]}
    blocked = [{
        "id": key,
        "waiting_for": [dep for dep in item["requires"] if dep not in graph.committed_nodes],
        "closed_unmerged": item["state"] == "closed" and not item["merged"],
    } for key, item in sorted(records.items())
        if key not in actionable and key not in graph.committed_nodes]
    # This output is *advice*, never a merge, workflow dispatch or authorization.
    core = {
        "schema": REPORT,
        "evidence_digest": evidence["evidence_digest"],
        "source": evidence["source"],
        "observed_at": evidence["observed_at"],
        "graph_snapshot": graph.snapshot(),
        "frontier": prompt["frontier"],
        "blocked": blocked,
        "advice": advice,
        "selected_pr": {
            "id": selected["id"], "url": selected_record["url"],
            "head_sha": selected_record["head_sha"],
            "check_status": statuses[selected["id"]],
        },
        "recommended_action": advice["action"],
        "merge_authorized": False,
        "github_state_mutated": False,
        "evidence_attestation": "HTTPS observation, not a GitHub-signed assertion"
            if evidence["source"] == "github-api-https" else
            "offline fixture, not authenticated live GitHub state",
    }
    return {**core, "report_digest": digest(core)}


def verify_research_report(
    evidence: Mapping[str, Any], report: Mapping[str, Any]
) -> bool:
    """Reconstruct an advisory result from source evidence and native DAG identity."""
    try:
        require(report["report_digest"] == digest({
            k: v for k, v in report.items() if k != "report_digest"
        }), "research report was altered")
        graph, records, statuses = build_research_dag(evidence)
        require(graph.snapshot() == report["graph_snapshot"], "E-CPU DAG changed")
        prompt = _adviser_prompt(graph, records, statuses, evidence)
        require(prompt["frontier"] == report["frontier"], "research readiness differs")
        rebuilt = operate(evidence, proposed_advice=report["advice"])
        require(rebuilt == report, "report does not reproduce from observed evidence")
        return True
    except (KeyError, ValueError, TypeError):
        return False


def main() -> None:
    """Observe real public GitHub state or inspect an explicitly labelled fixture."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name(
        "research_frontier_config.json"
    ))
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--live", action="store_true")
    source.add_argument("--snapshot", type=Path)
    parser.add_argument("--output", type=Path, default=Path("research-frontier.json"))
    parser.add_argument("--evidence-output", type=Path)
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    evidence = observe_live(config) if args.live else json.loads(
        args.snapshot.read_text(encoding="utf-8")
    )
    validate_evidence(evidence, config)
    result = operate(evidence)
    require(verify_research_report(evidence, result),
            "independent research evidence reconstruction failed")
    args.output.write_text(
        json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    if args.evidence_output:
        args.evidence_output.write_text(
            json.dumps(evidence, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps({
        "next": result["selected_pr"]["id"],
        "action": result["recommended_action"],
        "frontier": [item["id"] for item in result["frontier"]],
        "merge_authorized": False,
        "report_digest": result["report_digest"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
