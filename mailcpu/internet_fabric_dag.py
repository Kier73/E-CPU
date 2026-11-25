"""INTERNET-006: resume a native E-CPU dependency DAG on fresh GitHub runners.

Each bounded online quantum commits ONE native DAG operation. GitHub's existing
Git and HTTP services provide the external operators; the owned Git branch is
only a single-administrator checkpoint carrier, not an M3 recovery quorum.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re

from .computation_dag import ComputationNode, NavigableComputationDAG
from . import internet_free_fabric as internet

SCHEMA = "mailcpu.internet006.online-dag-checkpoint.v1"
REPORT_SCHEMA = "mailcpu.internet006.online-dag-report.v1"
STATE_BRANCH = internet.STATE_BRANCH
STATE_PATH = "state/internet006-dag.json"
STATE_LIMIT = 128_000
WORKSPACE_ID = internet.digest({
    "intention": "native-dag-online-operator-composition",
    "base": internet.BASE, "head": internet.HEAD,
    "operations": ["git-commit", "http-conditional", "git-compare", "compose"],
})
ORDER = ("git-commit", "http-conditional", "git-compare", "compose")
NODES = (
    ("git-commit", "internet.git.object", ()),
    ("http-conditional", "internet.http.conditional", ("git-commit",)),
    ("git-compare", "internet.git.compare", ("http-conditional",)),
    ("compose", "internet.path.compose", ("http-conditional", "git-compare")),
)
HEX40 = re.compile(r"[0-9a-f]{40}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")


class OnlineDAGRefused(ValueError):
    """Workspace state, Internet observation or intended transition was refused."""


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise OnlineDAGRefused(reason)


def graph_template() -> NavigableComputationDAG:
    """Reuse the native E-CPU DAG and its exact admitted operator dependencies."""
    nodes = [
        ComputationNode(
            node_id=node_id, revision=1, operation=operation,
            resource="github-native-https",
            context_digest=WORKSPACE_ID,
            dependencies=dependencies,
            payload={"workspace": WORKSPACE_ID,
                     "base": internet.BASE, "head": internet.HEAD,
                     "operator": operation},
        )
        for node_id, operation, dependencies in NODES
    ]
    return NavigableComputationDAG(nodes)


def _is_hash(value: object, count: int = 64) -> bool:
    return type(value) is str and (
        HEX64.fullmatch(value) if count == 64 else HEX40.fullmatch(value)
    ) is not None


def _is_etag(value: object) -> bool:
    return (type(value) is str and 0 < len(value) <= 256 and
            "\r" not in value and "\n" not in value)


def validate_result(node_id: str, result: dict, dag: NavigableComputationDAG) -> None:
    """Admit only the exact structure and linked semantic values of each operation."""
    require(type(result) is dict, "DAG commit result is not an object")
    if node_id == "git-commit":
        require(set(result) == {"sha", "body_sha256", "etag"} and
                result["sha"] == internet.HEAD and _is_hash(result["body_sha256"]) and
                _is_etag(result["etag"]), "pinned native Git commit result invalid")
    elif node_id == "http-conditional":
        prior = dag.result("git-commit")
        require(set(result) == {"conditional_status", "changed_status", "body_sha256",
                                "validator_sha256"} and
                type(result["conditional_status"]) is int and result["conditional_status"] == 304 and
                type(result["changed_status"]) is int and result["changed_status"] == 200 and
                result["body_sha256"] == prior["body_sha256"] and
                result["validator_sha256"] == hashlib.sha256(prior["etag"].encode("utf-8")).hexdigest() ,
                "native HTTP conditional result invalid")
    elif node_id == "git-compare":
        require(set(result) == {"base", "head", "merge_base", "ahead", "behind",
                                "status", "body_sha256"} and
                result["base"] == internet.BASE and result["head"] == internet.HEAD and
                result["merge_base"] == internet.BASE and
                type(result["ahead"]) is int and result["ahead"] == 11 and
                type(result["behind"]) is int and result["behind"] == 0 and
                result["status"] == "ahead" and _is_hash(result["body_sha256"]),
                "native Git graph result invalid")
    elif node_id == "compose":
        expected = compose_receipt(dag)
        require(result == expected, "composed Ground differs from exact native DAG predecessors")
    else:
        raise OnlineDAGRefused("unadmitted operation")


def compose_receipt(dag: NavigableComputationDAG) -> dict:
    """Create verified native E-CPU observer evidence from previously admitted operations."""
    c = dag.result("git-commit")
    h = dag.result("http-conditional")
    g = dag.result("git-compare")
    body = {
        "schema": internet.OBS_SCHEMA, "workspace_id": internet.WORKSPACE_ID,
        "commit_sha": internet.HEAD, "commit_body_sha256": c["body_sha256"],
        "validator_sha256": h["validator_sha256"],
        "conditional_status": h["conditional_status"],
        "changed_predicate_status": h["changed_status"],
        "compare_base": g["base"], "compare_head": g["head"],
        "merge_base": g["merge_base"], "ahead_by": g["ahead"],
        "behind_by": g["behind"], "compare_body_sha256": g["body_sha256"],
        "service_operations": ["github.git.commit", "http.if-none-match", "github.git.compare"],
        "source_code_payload_bytes": 0,
        "claim": "internet-service-native-not-physical-router-computation",
    }
    observed = body | {"digest": internet.digest(body)}
    internet.validate_observation(observed)
    native = internet.bind_native_observer_path(observed)
    return {"observation": observed, "native_receiver_path_digest": native["path_digest"],
            "scope": native["verification_scope"]}


def validate_snapshot(snapshot: object) -> NavigableComputationDAG:
    require(type(snapshot) is dict, "missing native DAG snapshot")
    dag = NavigableComputationDAG.from_snapshot(snapshot)
    require(dag.digest == graph_template().digest, "native DAG graph/intent has changed")
    committed = dag.committed_nodes
    require(committed == tuple(sorted(ORDER[:len(committed)])),
            "committed DAG frontier does not match required intention order")
    for node_id in ORDER[:len(committed)]:
        validate_result(node_id, dag.result(node_id), dag)
    return dag


def genesis() -> dict:
    """Explicit, committed initial state: absence must never cause a silent reset."""
    fields = {"schema": SCHEMA, "workspace_id": WORKSPACE_ID,
              "revision": 0, "previous_digest": None, "dag": None}
    return fields | {"digest": internet.digest(fields)}


def checkpoint(previous: dict, dag: NavigableComputationDAG) -> dict:
    validate_checkpoint(previous)
    revision = len(dag.committed_nodes)
    require(revision > 0 and revision <= len(ORDER), "checkpoint requires a new verified commit")
    require(revision == previous["revision"] + 1,
            "native DAG successor must advance exactly once")
    fields = {
        "schema": SCHEMA, "workspace_id": WORKSPACE_ID,
        "revision": revision, "previous_digest": previous["digest"],
        "dag": dag.snapshot(),
    }
    return validate_checkpoint(fields | {"digest": internet.digest(fields)})


def validate_checkpoint(state: object) -> dict:
    require(type(state) is dict and
            set(state) == {"schema", "workspace_id", "revision", "previous_digest",
                           "dag", "digest"}, "checkpoint schema is invalid")
    require(state["schema"] == SCHEMA and state["workspace_id"] == WORKSPACE_ID,
            "checkpoint scope is invalid")
    require(type(state["revision"]) is int and 0 <= state["revision"] <= len(ORDER),
            "checkpoint revision invalid")
    require((state["revision"] == 0 and state["previous_digest"] is None) or
            (state["revision"] == 1 and state["previous_digest"] == genesis()["digest"]) or
            (state["revision"] > 1 and _is_hash(state["previous_digest"])),
            "checkpoint lineage invalid")
    require(_is_hash(state["digest"]) and
            state["digest"] == internet.digest({k: v for k, v in state.items() if k != "digest"}),
            "checkpoint digest mismatch")
    require(len(internet.canonical(state)) <= STATE_LIMIT, "checkpoint exceeds byte budget")
    if state["revision"] == 0:
        require(state["dag"] is None and state == genesis(),
                "the workspace must begin at the exact admitted genesis")
        return state
    dag = validate_snapshot(state["dag"])
    require(len(dag.committed_nodes) == state["revision"],
            "checkpoint revision disagrees with committed DAG effects")
    return state


def run_one(dag: NavigableComputationDAG, fetch) -> str | None:
    """Execute at most one ready pure operation, without replay of committed nodes."""
    validate_snapshot(dag.snapshot())
    if dag.is_complete:
        return None
    ready = dag.ready_nodes()
    require(len(ready) == 1, "expected a single exact ready native frontier")
    node_id = ready[0].node_id
    if node_id == "git-commit":
        status, headers, raw = fetch(internet.COMMIT_URL, None)
        require(status == 200, "Git object did not return HTTP 200")
        object_ = internet.strict_json(raw)
        require(object_.get("sha") == internet.HEAD, "Git object pin differs")
        etag = headers.get("etag")
        require(_is_etag(etag), "Git object ETag is missing")
        result = {"sha": internet.HEAD, "body_sha256":
                  hashlib.sha256(raw).hexdigest(), "etag": etag}
    elif node_id == "http-conditional":
        prior = dag.result("git-commit")
        status, _, raw = fetch(internet.COMMIT_URL, prior["etag"])
        require(status == 304 and raw == b"", "GitHub HTTP native conditional failed")
        other_status, _, other_body = fetch(internet.COMMIT_URL,
                                           '"internet006-not-this-etag"')
        require(other_status == 200 and
                internet.strict_json(other_body).get("sha") == internet.HEAD and
                hashlib.sha256(other_body).hexdigest() == prior["body_sha256"],
                "nonmatching conditional did not retain exact Git representation")
        result = {"conditional_status": 304, "changed_status": 200,
                  "body_sha256": prior["body_sha256"],
                  "validator_sha256": hashlib.sha256(prior["etag"].encode("utf-8")).hexdigest()}
    elif node_id == "git-compare":
        status, _, raw = fetch(internet.COMPARE_URL, None)
        require(status == 200, "Git graph operator did not return HTTP 200")
        graph = internet.strict_json(raw)
        merge = graph.get("merge_base_commit")
        require(type(merge) is dict and merge.get("sha") == internet.BASE and
                type(graph.get("ahead_by")) is int and graph["ahead_by"] == 11 and
                type(graph.get("behind_by")) is int and graph["behind_by"] == 0 and
                graph.get("status") == "ahead",
                "Git native compare disagrees with pinned independent oracle")
        result = {"base": internet.BASE, "head": internet.HEAD,
                  "merge_base": internet.BASE, "ahead": 11, "behind": 0,
                  "status": "ahead",
                  "body_sha256": hashlib.sha256(raw).hexdigest()}
    elif node_id == "compose":
        result = compose_receipt(dag)
    else:
        raise OnlineDAGRefused("unknown native DAG operation")
    validate_result(node_id, result, dag)
    require(dag.commit(node_id, result) is False, "native DAG commit replayed a prior effect")
    return node_id


def _state_url() -> str:
    return f"{internet.API_BASE}/contents/{STATE_PATH}?ref={STATE_BRANCH}"


def read_state(token: str) -> tuple[dict, str]:
    branch_url = f"{internet.API_BASE}/git/ref/heads/{STATE_BRANCH}"
    status, _, data = internet.request("GET", branch_url, token)
    require(status == 200, "workspace state branch missing; refusing reset")
    branch = internet.strict_json(data)
    obj = branch.get("object")
    require(branch.get("ref") == "refs/heads/" + STATE_BRANCH and
            type(obj) is dict and _is_hash(obj.get("sha"), 40),
            "state branch identity malformed")
    status, _, response = internet.request("GET", _state_url(), token)
    require(status == 200, "genesis/checkpoint file missing; refusing workspace reset")
    envelope = internet.strict_json(response)
    require(envelope.get("encoding") == "base64" and
            type(envelope.get("content")) is str and _is_hash(envelope.get("sha"), 40),
            "GitHub checkpoint object metadata malformed")
    try:
        raw = base64.b64decode(envelope["content"].replace("\n", ""), validate=True)
    except (ValueError, TypeError) as exc:
        raise OnlineDAGRefused("GitHub checkpoint bytes malformed") from exc
    require(len(raw) <= STATE_LIMIT, "checkpoint exceeds budget")
    return validate_checkpoint(internet.strict_json(raw)), envelope["sha"]


def publish(token: str, state: dict, previous_blob: str | None) -> str:
    validate_checkpoint(state)
    if previous_blob is not None:
        require(_is_hash(previous_blob, 40), "invalid old Git blob identity")
    body = {
        "message": f"INTERNET-006 native DAG revision {state['revision']}",
        "content": base64.b64encode(internet.canonical(state) + b"\n").decode(),
        "branch": STATE_BRANCH,
    }
    if previous_blob is not None:
        body["sha"] = previous_blob
    status, _, response = internet.request(
        "PUT", f"{internet.API_BASE}/contents/{STATE_PATH}",
        token, data=internet.canonical(body),
    )
    require(status in (200, 201), "GitHub conditional state publication failed")
    result = internet.strict_json(response).get("content")
    require(type(result) is dict and _is_hash(result.get("sha"), 40),
            "GitHub published object lacks exact blob identity")
    return result["sha"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--output", default="internet006-result.json")
    args = parser.parse_args()
    require(args.live, "live Internet observation must be explicitly selected")
    require(os.getenv("GITHUB_REPOSITORY") == internet.REPOSITORY,
            "GitHub workspace repository is not admitted")
    token = os.getenv("GITHUB_TOKEN")
    require(type(token) is str and bool(token), "explicit GitHub token needed")
    state, blob = read_state(token)
    dag = (NavigableComputationDAG.from_snapshot(state["dag"])
           if state["revision"] > 0 else graph_template())
    validate_snapshot(dag.snapshot())
    def get(url: str, etag: str | None):
        require(url in (internet.COMMIT_URL, internet.COMPARE_URL),
                "unapproved Internet operation")
        return internet.request("GET", url, token, etag=etag)
    node_id = run_one(dag, get)
    next_state = checkpoint(state, dag) if node_id else state
    published = publish(token, next_state, blob) if node_id and args.publish else None
    report = {
        "schema": REPORT_SCHEMA, "workspace_id": WORKSPACE_ID,
        "prior_revision": state["revision"],
        "revision": next_state["revision"],
        "committed_node": node_id, "remaining": len(ORDER) - len(dag.committed_nodes),
        "complete": dag.is_complete, "native_dag_digest": dag.digest,
        "checkpoint_digest": next_state["digest"],
        "published_blob_sha": published,
        "authority": "single-GitHub-administrator-CAS-not-M3-quorum",
    }
    Path(args.output).write_bytes(internet.canonical(report) + b"\n")
    print(f"INTERNET-006 revision={report['revision']} node={node_id} "
          f"complete={dag.is_complete} published={published is not None}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
