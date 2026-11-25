"""Bounded continuation policy for recoverable INTERNET-007 hosted quanta.

This module has *no dispatch authority*. It validates the exact local result,
read-only manifest and hosted main-branch context, then writes a boolean to
GITHUB_OUTPUT. The workflow alone may request one successor via GitHub's
explicit workflow_dispatch API, under its separately scoped Actions token.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Mapping

from . import internet_free_fabric as foundation
from . import internet_intention_ingress as ingress


class QuantumContinuationRefused(ValueError):
    """The reported work cannot request another online quantum."""


def continuation_decision(
    manifest: Mapping[str, object],
    report: Mapping[str, object],
    *,
    repository: str,
    ref: str,
    event_name: str,
) -> bool:
    """Return true only after a newly published, accepted, nonterminal operation.

    The report must describe the same immutable intention and exactly one
    *successful* hosted quantum. Mere status='recoverable', an empty report,
    or a caller-supplied name never justifies further execution.
    """
    qualified = ingress.admit_manifest(dict(manifest))
    if (
        repository != foundation.REPOSITORY
        or ref != "refs/heads/main"
        or event_name not in ("push", "workflow_dispatch", "schedule")
    ):
        raise QuantumContinuationRefused("not an admitted hosted main-branch execution")
    required = {
        "schema", "intention_id", "manifest_digest", "mode",
        "previous_revision", "revision", "operation", "state_digest",
        "published_blob_sha", "status", "max_cost_usd", "authority",
    }
    if not isinstance(report, Mapping) or set(report) != required:
        raise QuantumContinuationRefused("hosted quantum report schema invalid")
    if (
        report["schema"] != "mailcpu.internet007.report.v1"
        or report["intention_id"] != qualified["intention_id"]
        or report["manifest_digest"] != ingress.digest(qualified)
        or report["mode"] != "step"
        or type(report["revision"]) is not int
        or type(report["previous_revision"]) is not int
        or type(report["max_cost_usd"]) is not int
        or report["max_cost_usd"] != 0
        or report["authority"] != "owner-approved-manifest-and-Git-CAS-not-M3-quorum"
        or not ingress.hash64(report["state_digest"])
    ):
        raise QuantumContinuationRefused("report violates admitted intention or zero-cost authority")
    count = len(qualified["nodes"])
    revision = report["revision"]
    if not 1 <= revision <= count or report["previous_revision"] != revision - 1:
        raise QuantumContinuationRefused("report does not advance exactly one native computation")
    expected = ingress.execution_order(qualified)
    if report["operation"] != expected[revision - 1]:
        raise QuantumContinuationRefused("reported native operation differs from intended DAG")
    if not ingress.hash40(report["published_blob_sha"]):
        raise QuantumContinuationRefused("no accepted Git blob publication")
    status = "complete" if revision == count else "recoverable"
    if report["status"] != status:
        raise QuantumContinuationRefused("terminal status is inconsistent with accepted DAG")
    return revision < count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--intention-file", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--github-output", required=True)
    args = parser.parse_args()
    manifest = ingress.read_manifest(args.intention_file)
    report_path = Path(args.report)
    if not report_path.is_file() or report_path.stat().st_size > 16_384:
        raise QuantumContinuationRefused("hosted report absent or over its byte budget")
    report = foundation.strict_json(report_path.read_bytes())
    next_step = continuation_decision(
        manifest, report,
        repository=os.environ.get("GITHUB_REPOSITORY", ""),
        ref=os.environ.get("GITHUB_REF", ""),
        event_name=os.environ.get("GITHUB_EVENT_NAME", ""),
    )
    output = Path(args.github_output)
    if not output.is_file():
        raise QuantumContinuationRefused("GITHUB_OUTPUT file is unavailable")
    with output.open("a", encoding="utf-8") as stream:
        stream.write("dispatch=" + ("true" if next_step else "false") + "\n")
    print("INTERNET-007 continuation: " + ("one successor admitted" if next_step else "terminal; no successor"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
