"""USM-010: formal evidence obligations for E-CPU's own research decisions.

This is a direct use of the *existing* E-CPU computation-DAG and formal
navigation algebra. It is not a new proof kernel, GitHub authority, or
continuous monitoring service.

One exact-HEAD workflow requirement is an observation predicate. A native
LinearConstraint proves whether all required checks have *already* succeeded.
Future success remains UNKNOWN until a newer observation supplies evidence.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from mailcpu.navigation_formal import (
    ConstraintDisposition, ConstraintRelation, IntInterval,
    LinearConstraint, LinearExpression,
)
from examples.research_frontier import (
    ResearchFrontierRefused, build_research_dag, check_status,
    operate, validate_evidence, verify_research_report,
)
from examples.research_frontier_worker import digest

SCHEMA = "mailcpu.research-proof-obligations.v1"
INVARIANT_ID = "all-required-exact-head-workflows-succeeded"


def _equality_certificate(successes: int, required: int) -> dict[str, Any]:
    """Build an exact, inspectable formal-navigation proof-obligation record."""
    if type(successes) is not int or type(required) is not int or not 0 <= successes <= required:
        raise ResearchFrontierRefused("invalid number of successful required workflows")
    # Predicate: successes - required = 0.
    predicate = LinearConstraint(
        LinearExpression.variable("successful_checks") - required,
        ConstraintRelation.EQ,
    )
    actual = predicate.classify({"successful_checks": IntInterval.point(successes)})
    # The future is not known: further executions could make all checks green.
    later = predicate.classify({
        "successful_checks": IntInterval(successes, required)
    })
    expected_now = (
        ConstraintDisposition.ENTAILED if successes == required
        else ConstraintDisposition.REFUTED
    )
    expected_later = (
        ConstraintDisposition.ENTAILED if successes == required
        else ConstraintDisposition.UNKNOWN
    )
    if actual != expected_now or later != expected_later:
        raise ResearchFrontierRefused("formal verifier and exact evidence disagree")
    return {
        "invariant": INVARIANT_ID,
        "constraint": predicate.to_dict(),
        "observed_bounds": IntInterval.point(successes).to_dict(),
        "potential_future_bounds": IntInterval(successes, required).to_dict(),
        "current_disposition": actual.value,
        "future_disposition": later.value,
        "current_success_count": successes,
        "required_count": required,
    }


def evaluate_obligations(
    source: Mapping[str, Any],
    research_report: Mapping[str, Any],
) -> dict[str, Any]:
    """Turn a trusted-by-correlation research choice into explicit obligations.

    The native DAG controls readiness. Native linear constraints classify
    observed completion. Neither the adviser nor this adapter controls merges.
    """
    if not verify_research_report(source, research_report):
        raise ResearchFrontierRefused("original research selection cannot be reconstructed")
    graph, records, statuses = build_research_dag(source)
    observed = validate_evidence(source)
    by_id = {item["id"]: item for item in observed}
    ready = {node.node_id for node in graph.ready_nodes()}
    committed = set(graph.committed_nodes)
    obligations: list[dict[str, Any]] = []
    for key, item in sorted(by_id.items()):
        verification, successes = check_status(item, source["observed_at"])
        if verification != statuses[key]:
            raise ResearchFrontierRefused("research verification status changed")
        required = len(item["required_workflows"])
        proved = _equality_certificate(successes, required)
        run_by_workflow = {run["workflow"]: run for run in item["runs"]}
        outstanding = []
        for workflow in item["required_workflows"]:
            run = run_by_workflow.get(workflow)
            if run is not None and run["status"] == "completed" and run["conclusion"] == "success":
                continue
            outstanding.append({
                "workflow": workflow,
                "kind": "no_run" if run is None else (
                    "not_completed" if run["status"] != "completed"
                    else "completed_without_success"
                ),
                "run_id": run["id"] if run else None,
                "run_url": run["url"] if run else None,
                "status": run["status"] if run else "missing",
                "conclusion": run["conclusion"] if run else None,
            })
        if len(outstanding) != required - successes:
            raise ResearchFrontierRefused("unsatisfied obligations disagree with CI state")
        unresolved_ancestors = [
            parent for parent in graph.lineage(key) if parent not in committed
        ]
        if key in committed and (
            proved["current_disposition"] != "entailed" or not item["merged"]
        ):
            raise ResearchFrontierRefused("E-CPU DAG committed unverified research")
        obligations.append({
            "id": key,
            "pr_url": item["url"],
            "source_head_sha": item["head_sha"],
            "source_state": item["state"],
            "merged": item["merged"],
            "verification_status": verification,
            "formal_verification": proved,
            "outstanding": outstanding,
            "unresolved_ancestors": unresolved_ancestors,
            "ready_in_native_dag": key in ready,
            "committed_in_native_dag": key in committed,
            "eligible_for_advisory_selection": any(
                entry["id"] == key for entry in research_report["frontier"]
            ),
        })
    if (
        {entry["id"] for entry in obligations} != set(by_id)
        or research_report["selected_pr"]["id"] not in {
            entry["id"] for entry in obligations if entry["eligible_for_advisory_selection"]
        }
    ):
        raise ResearchFrontierRefused("research decision is not an eligible obligation")
    selected = next(
        entry for entry in obligations
        if entry["id"] == research_report["selected_pr"]["id"]
    )
    if research_report["recommended_action"] in {
        "monitor_queued_verification", "investigate_queued_runner",
        "reassess_cancelled_verification", "investigate_failure",
        "collect_verification", "inspect_running_verification",
    } and selected["formal_verification"]["current_disposition"] == "entailed":
        raise ResearchFrontierRefused("model advised gathering checks that already succeeded")
    payload = {
        "schema": SCHEMA,
        "source_evidence_digest": source["evidence_digest"],
        "research_report_digest": research_report["report_digest"],
        "native_dag_digest": graph.snapshot()["digest"],
        "proof_method": "E-CPU navigation_formal.LinearConstraint",
        "selected_obligation": selected["id"],
        "selected_disposition": selected["formal_verification"]["current_disposition"],
        "recommended_next_action": research_report["recommended_action"],
        "obligations": obligations,
        "proof_scope": "exact captured workflow observation; not future success",
        "merge_authorized": False,
        "github_state_mutated": False,
    }
    return {**payload, "report_digest": digest(payload)}


def verify_obligations(
    source: Mapping[str, Any],
    research_report: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> bool:
    """Reconstruct exact native proof status from independent captured inputs."""
    try:
        return (
            isinstance(evidence, Mapping)
            and evaluate_obligations(source, research_report) == evidence
        )
    except (TypeError, KeyError, ValueError, AttributeError):
        return False


def main() -> None:
    """Consume the exact E-CPU research decision or create one from the source."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--decision", type=Path)
    parser.add_argument("--output", type=Path, default=Path("research-obligations.json"))
    args = parser.parse_args()
    source = json.loads(args.source.read_text(encoding="utf-8"))
    decision = (
        json.loads(args.decision.read_text(encoding="utf-8"))
        if args.decision else operate(source)
    )
    result = evaluate_obligations(source, decision)
    if not verify_obligations(source, decision, result):
        raise ResearchFrontierRefused("research proof obligation reconstruction failed")
    args.output.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    selected = next(
        item for item in result["obligations"] if item["id"] == result["selected_obligation"]
    )
    print(json.dumps({
        "selected": result["selected_obligation"],
        "current_proof": result["selected_disposition"],
        "future_proof": selected["formal_verification"]["future_disposition"],
        "missing_checks": len(selected["outstanding"]),
        "next_action": result["recommended_next_action"],
        "merge_authorized": result["merge_authorized"],
        "report_digest": result["report_digest"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
