"""Independent INTERNET-007 audit of Git-backed native DAG continuations.

This observer reads Git commit history and version-pinned Git blobs, rather
than trusting the most recent branch tip or a workflow console status. Exact
native E-CPU DAG commitments, content hashes, the pinned genesis Git commit,
and distinct successful GitHub workflow invocations must all agree.
"""
from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Callable, Mapping, Sequence

from . import internet_free_fabric as foundation
from . import internet_intention_ingress as ingress
from .computation_dag import NavigableComputationDAG

AUDIT_SCHEMA = "mailcpu.internet007.independent-proof.v1"
GENESIS_COMMITS = {
    "public-source-grounds": "ca5c173de08866d989a319656f122c8a35886d3d",
}
MAX_READ_STATES = 33
MAX_REMOTE_BYTES = 2_000_000
RUN_LINE = re.compile(
    r"INTERNET-007 ([a-z][a-z0-9_-]{1,47}) revision ([1-9][0-9]{0,3}) "
    r"\[run=([1-9][0-9]{0,19}) attempt=([1-9][0-9]{0,4})\]\Z"
)


class ContinuityProofRefused(ValueError):
    """An Internet workspace has insufficient independent continuity evidence."""


def require(ok: bool, reason: str) -> None:
    if ok is not True:
        raise ContinuityProofRefused(reason)


def strict_list(content: bytes) -> list:
    def pairs(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "duplicate history metadata key")
            result[key] = value
        return result
    try:
        value = json.loads(content, object_pairs_hook=pairs,
                           parse_constant=lambda _: require(False, "nonfinite history metadata"))
    except (UnicodeError, ValueError) as exc:
        raise ContinuityProofRefused("Git history metadata invalid") from exc
    require(type(value) is list, "Git commit history is not a list")
    return value


def git_blob_identity(raw: bytes) -> str:
    """Independently reconstruct Git blob identity from the actual bytes."""
    require(type(raw) is bytes and len(raw) <= ingress.MAX_CHECKPOINT_BYTES,
            "checkpoint blob exceeds byte budget")
    prefix = b"blob " + str(len(raw)).encode("ascii") + b"\x00"
    return hashlib.sha1(prefix + raw).hexdigest()


@dataclass(frozen=True)
class GitCheckpoint:
    commit_sha: str
    commit_message: str
    blob_sha: str
    raw_bytes: bytes

    def __post_init__(self) -> None:
        require(ingress.hash40(self.commit_sha), "invalid Git history commit identity")
        require(type(self.commit_message) is str and len(self.commit_message) <= 512,
                "invalid Git history message")
        require(ingress.hash40(self.blob_sha), "invalid Git blob identity")
        require(type(self.raw_bytes) is bytes and
                len(self.raw_bytes) <= ingress.MAX_CHECKPOINT_BYTES,
                "invalid checkpoint bytes")


RunVerifier = Callable[[int, int], bool]


def verify_history(manifest: dict, history: Sequence[GitCheckpoint],
                   *, run_verifier: RunVerifier | None = None) -> dict:
    """Check every version of one native DAG, not only the newest snapshot.

    GitCheckout blobs are bound to the exact commit SHA, and their native DAG
    results must be strictly monotonic. GitHub Actions invocation claims do
    not become proof merely because they are strings in commit messages.
    """
    manifest = ingress.admit_manifest(manifest)
    require(type(history) in (list, tuple) and
            1 <= len(history) <= min(MAX_READ_STATES, len(manifest["nodes"]) + 1),
            "history size outside admitted intention")
    require(all(isinstance(entry, GitCheckpoint) for entry in history),
            "history contains an untyped Git checkpoint")
    expected_order = ingress.execution_order(manifest)
    genesis_sha = GENESIS_COMMITS.get(manifest["intention_id"])
    require(genesis_sha is not None and history[0].commit_sha == genesis_sha,
            "history is not anchored to the independently pinned Git genesis")
    require(len(set(x.commit_sha for x in history)) == len(history),
            "duplicate Git commits in a purported continuity history")
    previous_state = None
    previous_dag = None
    observed_runs = set()
    witness = []
    for revision, item in enumerate(history):
        require(isinstance(item, GitCheckpoint), "history contains a non-Git entry")
        require(git_blob_identity(item.raw_bytes) == item.blob_sha,
                "Git content blob identity does not match its original bytes")
        try:
            state = ingress.validate_state(manifest, foundation.strict_json(item.raw_bytes))
        except (ValueError, KeyError, TypeError) as exc:
            raise ContinuityProofRefused("native E-CPU checkpoint verification failed") from exc
        require(state["revision"] == revision,
                "one or more revisions missing, replayed, or out of order")
        if revision == 0:
            require(state == ingress.genesis(manifest),
                    "Git genesis differs from admitted intention")
            accepted = None
        else:
            require(state["previous_digest"] == previous_state["digest"],
                    "checkpoint does not descend from exact previous Git revision")
            try:
                dag = NavigableComputationDAG.from_snapshot(state["dag"])
                ingress.verify_dag(manifest, dag)
                require(dag.committed_nodes == tuple(sorted(expected_order[:revision])),
                        "unadmitted computation result appeared in Git history")
                if previous_dag is not None:
                    for node_id in previous_dag.committed_nodes:
                        require(dag.result(node_id) == previous_dag.result(node_id),
                                "an earlier accepted computation effect changed")
            except (KeyError, TypeError, ValueError) as exc:
                raise ContinuityProofRefused("native DAG state continuity failed") from exc
            accepted = expected_order[revision - 1]
            match = RUN_LINE.fullmatch(item.commit_message)
            require(match is not None and match.group(1) == manifest["intention_id"] and
                    int(match.group(2)) == revision,
                    "Git commit is missing its exact unique GitHub Actions run claim")
            run_id, attempt = int(match.group(3)), int(match.group(4))
            require(run_id not in observed_runs, "different DAG revisions reused one runner invocation")
            observed_runs.add(run_id)
            if run_verifier is not None:
                require(run_verifier(run_id, attempt) is True,
                        "claimed hosted run has no independent successful GitHub evidence")
            previous_dag = dag
        witness.append({
            "revision": revision,
            "git_commit_sha": item.commit_sha,
            "git_blob_sha": item.blob_sha,
            "native_state_digest": state["digest"],
            "committed_node": accepted,
        })
        previous_state = state
    complete = len(history) == len(manifest["nodes"]) + 1
    report = {
        "schema": AUDIT_SCHEMA, "intention_id": manifest["intention_id"],
        "manifest_digest": ingress.digest(manifest),
        "genesis_commit_sha": genesis_sha, "observed_revisions": len(history) - 1,
        "required_revisions": len(manifest["nodes"]),
        "unique_workflow_run_claims": len(observed_runs),
        "run_metadata_verified": run_verifier is not None,
        "complete": complete,
        "status": "verified-complete" if complete and run_verifier is not None
                  else "verified-partial" if run_verifier is not None
                  else "run-claims-unverified",
        "commit_chain": witness,
        "interpretation": "single-GitHub-admin-durable-native-DAG-not-M3-quorum",
    }
    return report | {"digest": ingress.digest(report)}


def get_history(token: str, manifest: dict) -> list[GitCheckpoint]:
    """Read each historical Git blob from its own immutable Git commit identity."""
    path = ingress.state_path(manifest)
    url = (f"{foundation.API_BASE}/commits?sha={ingress.BRANCH}&"
           f"path={path}&per_page=100")
    status, _, body = foundation.request("GET", url, token)
    require(status == 200, "Git revision history unavailable")
    commits = strict_list(body)
    require(1 <= len(commits) <= min(MAX_READ_STATES, len(manifest["nodes"]) + 1),
            "history missing or outside the accepted revision budget")
    result = []
    for metadata in reversed(commits):
        require(type(metadata) is dict, "Git history entry malformed")
        sha = metadata.get("sha")
        commit = metadata.get("commit")
        require(ingress.hash40(sha) and type(commit) is dict and
                type(commit.get("message")) is str,
                "Git history lacks commit identity or message")
        point_url = f"{foundation.API_BASE}/contents/{path}?ref={sha}"
        read_status, _, data = foundation.request("GET", point_url, token)
        require(read_status == 200, "historical Git content could not be fetched")
        envelope = foundation.strict_json(data)
        encoded = envelope.get("content")
        blob = envelope.get("sha")
        require(envelope.get("encoding") == "base64" and
                type(encoded) is str and ingress.hash40(blob),
                "historical Git blob metadata malformed")
        try:
            raw = base64.b64decode(encoded.replace("\n", ""), validate=True)
        except (ValueError, TypeError) as exc:
            raise ContinuityProofRefused("historical Git blob base64 invalid") from exc
        result.append(GitCheckpoint(sha, commit["message"], blob, raw))
    return result


def github_run_verifier(token: str) -> RunVerifier:
    """Corroborate run IDs against GitHub's own Actions records, read-only."""
    def verify(run_id: int, attempt: int) -> bool:
        status, _, data = foundation.request(
            "GET", f"{foundation.API_BASE}/actions/runs/{run_id}", token)
        if status != 200:
            return False
        value = foundation.strict_json(data)
        return (
            type(value.get("id")) is int and value["id"] == run_id and
            type(value.get("run_attempt")) is int and
            value["run_attempt"] == attempt and
            value.get("name") == "INTERNET-007 native intention ingress" and
            value.get("path") == ".github/workflows/internet-007-intentions.yml" and
            value.get("head_branch") == "main" and
            value.get("event") in ("push", "schedule", "workflow_dispatch") and
            value.get("status") == "completed" and value.get("conclusion") == "success"
        )
    return verify


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--intention-file",
                        default="intentions/internet007/public-source-grounds.json")
    parser.add_argument("--output", default="internet007-proof.json")
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args()
    require(os.getenv("GITHUB_REPOSITORY") == foundation.REPOSITORY,
            "proof must run in the admitted E-CPU repository")
    token = os.getenv("GITHUB_TOKEN")
    require(type(token) is str and len(token) > 0, "GitHub proof token required")
    manifest = ingress.read_manifest(args.intention_file)
    history = get_history(token, manifest)
    proof = verify_history(manifest, history,
                           run_verifier=github_run_verifier(token))
    Path(args.output).write_bytes(foundation.canonical(proof) + b"\n")
    if args.require_complete:
        require(proof["complete"] and proof["status"] == "verified-complete",
                "complete distinct-run online E-CPU proof has not yet been observed")
    print(f"INTERNET-007 proof: {proof['observed_revisions']}/"
          f"{proof['required_revisions']} unique-online-run checkpoints, "
          f"status={proof['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
