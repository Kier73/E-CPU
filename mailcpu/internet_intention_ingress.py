"""INTERNET-007: admit bounded public research intentions to a recoverable E-CPU DAG.

GitHub is both a read-only native service operator and a temporary online
execution substrate. This module does not execute source-repository code,
provision paid resources, or replace M3's independently governed quorum.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .computation_dag import ComputationNode, NavigableComputationDAG
from . import internet_free_fabric as foundation

SCHEMA = "mailcpu.internet007.intention.v1"
STATE_SCHEMA = "mailcpu.internet007.state.v1"
BRANCH = foundation.STATE_BRANCH
API = foundation.API_BASE
MANIFEST_FILE = re.compile(r"intentions/internet007/[a-z][a-z0-9_-]{1,47}\.json\Z")
NAME = re.compile(r"[a-z][a-z0-9_-]{1,47}\Z")
NODE = re.compile(r"[a-z][a-z0-9_-]{1,47}\Z")
SHA = re.compile(r"[0-9a-f]{40}\Z")
DIGEST = re.compile(r"[0-9a-f]{64}\Z")
REPOS = frozenset({
    "Kier73/E-CPU", "Kier73/Virtual-Ground-Interpreter",
    "Kier73/In-Formation-Space", "Kier73/VL-I", "Kier73/VL-64",
})
OPERATORS = frozenset({"github.git.commit", "github.git.compare",
                       "http.etag.check", "ground.join"})
MAX_MANIFEST_BYTES = 48_000
MAX_CHECKPOINT_BYTES = 350_000
MAX_REMOTE_BYTES = 2_000_000


class IntentionRefused(ValueError):
    """A requested Ground, operation, checkpoint, or authorization is insufficient."""


def require(condition: bool, reason: str) -> None:
    if condition is not True:
        raise IntentionRefused(reason)


def canonical(value: object) -> bytes:
    return foundation.canonical(value)


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def digest(value: object) -> str:
    return sha256(canonical(value))


def hash40(value: object) -> bool:
    return type(value) is str and SHA.fullmatch(value) is not None


def hash64(value: object) -> bool:
    return type(value) is str and DIGEST.fullmatch(value) is not None


def admit_manifest(value: object) -> dict:
    """The repository owner controls the finite operator language, not source hosts."""
    require(type(value) is dict and set(value) == {
        "schema", "intention_id", "purpose", "budget", "nodes"
    }, "intention schema differs")
    require(value["schema"] == SCHEMA and type(value["intention_id"]) is str and
            NAME.fullmatch(value["intention_id"]) is not None,
            "intention identity invalid")
    require(type(value["purpose"]) is str and 0 < len(value["purpose"]) <= 256,
            "purpose must be a bounded description")
    budget = value["budget"]
    require(type(budget) is dict and set(budget) == {
        "max_cost_usd", "max_nodes", "max_reads_per_quantum", "max_response_bytes"
    }, "budget contract differs")
    require(type(budget["max_cost_usd"]) is int and budget["max_cost_usd"] == 0,
            "free-fabric mode refuses paid capacity")
    require(type(budget["max_nodes"]) is int and
            1 <= budget["max_nodes"] <= 32, "node budget invalid")
    require(type(budget["max_reads_per_quantum"]) is int and
            1 <= budget["max_reads_per_quantum"] <= 3, "read budget invalid")
    require(type(budget["max_response_bytes"]) is int and
            256 <= budget["max_response_bytes"] <= MAX_REMOTE_BYTES,
            "response byte budget invalid")
    nodes = value["nodes"]
    require(type(nodes) is list and 1 <= len(nodes) <= budget["max_nodes"],
            "intention nodes exceed budget")
    mapping: dict[str, dict] = {}
    for entry in nodes:
        require(type(entry) is dict and set(entry) == {
            "id", "operator", "dependencies", "params"
        }, "operation contract differs")
        n = entry["id"]
        require(type(n) is str and NODE.fullmatch(n) is not None and
                n not in mapping and type(entry["operator"]) is str and
                entry["operator"] in OPERATORS,
                "unsupported or duplicated computational operation")
        deps = entry["dependencies"]
        require(type(deps) is list and len(deps) <= 32 and
                all(type(d) is str and NODE.fullmatch(d) for d in deps) and
                len(deps) == len(set(deps)) and n not in deps,
                "invalid dependency identities")
        params = entry["params"]
        require(type(params) is dict, "operator parameters must be an object")
        op = entry["operator"]
        if op == "github.git.commit":
            require(not deps and set(params) == {"repository", "sha"} and
                    type(params["repository"]) is str and
                    params["repository"] in REPOS and hash40(params["sha"]),
                    "Git object operator has an invalid pinned source")
        elif op == "github.git.compare":
            exp = params.get("expect")
            require(not deps and set(params) == {"repository", "base", "head", "expect"} and
                    type(params["repository"]) is str and
                    params["repository"] in REPOS and hash40(params["base"]) and
                    hash40(params["head"]) and type(exp) is dict and
                    set(exp) == {"merge_base", "ahead", "behind", "status"} and
                    hash40(exp["merge_base"]) and
                    type(exp["ahead"]) is int and 0 <= exp["ahead"] <= 100000 and
                    type(exp["behind"]) is int and 0 <= exp["behind"] <= 100000 and
                    type(exp["status"]) is str and
                    exp["status"] in ("ahead", "behind", "diverged", "identical"),
                    "Git graph requires pinned, independently expected results")
        elif op == "http.etag.check":
            require(len(deps) == 1 and set(params) == {"source"} and
                    params["source"] == deps[0], "conditional HTTP requires one source")
        elif op == "ground.join":
            require(len(deps) >= 2 and set(params) == {"label"} and
                    type(params["label"]) is str and
                    0 < len(params["label"]) <= 128, "join requires typed predecessor Grounds")
        mapping[n] = entry
    for entry in nodes:
        for predecessor in entry["dependencies"]:
            require(predecessor in mapping, "operation refers to an absent Ground")
        if entry["operator"] == "http.etag.check":
            require(mapping[entry["params"]["source"]]["operator"] == "github.git.commit",
                    "conditional source must be an admitted pinned Git operation")
    require(len(canonical(value)) <= MAX_MANIFEST_BYTES, "intention exceeds byte budget")
    graph_template(value)  # Native E-CPU cycle and resource-contract qualification.
    return value


def graph_template(manifest: Mapping) -> NavigableComputationDAG:
    ident = digest(manifest)
    return NavigableComputationDAG(
        (ComputationNode(
            item["id"], 1, item["operator"], "authorized-public-internet",
            ident, tuple(item["dependencies"]), item["params"],
        ) for item in manifest["nodes"]),
        max_nodes=manifest["budget"]["max_nodes"],
    )


def execution_order(manifest: dict) -> tuple[str, ...]:
    """Deterministic single-operation order over the admitted native DAG."""
    by_id = {entry["id"]: entry for entry in manifest["nodes"]}
    done: set[str] = set()
    order = []
    while len(done) < len(by_id):
        ready = sorted(n for n, entry in by_id.items() if n not in done and
                       all(d in done for d in entry["dependencies"]))
        require(bool(ready), "cyclic intention")
        chosen = ready[0]
        order.append(chosen)
        done.add(chosen)
    return tuple(order)


def state_path(manifest: dict) -> str:
    return ("state/internet007/" + manifest["intention_id"] + "-" +
            digest(manifest)[:24] + ".json")


def genesis(manifest: dict) -> dict:
    admitted = admit_manifest(manifest)
    fields = {"schema": STATE_SCHEMA, "intention_id": admitted["intention_id"],
              "manifest_digest": digest(admitted), "revision": 0,
              "previous_digest": None, "dag": None}
    return fields | {"digest": digest(fields)}


def _result_for_join(manifest: dict, node: ComputationNode,
                     dag: NavigableComputationDAG) -> dict:
    """Native E-CPU observer-path witness over the exact predecessor results."""
    from .observer_orbit import ObserverContract, ObserverReceipt
    from .observer_path_evidence import ObserverPathStage, verify_observer_path
    from .semantic_translation import (
        RepresentationRef, ObservationContract, canonical_value_digest,
    )
    entries = [{"node": dep, "result_digest": digest(dag.result(dep))}
               for dep in sorted(node.dependencies)]
    subject = RepresentationRef.from_payload("internet007.predecessor-grounds", 1, entries)
    ground = RepresentationRef.from_payload("internet007.intention", 1, manifest)
    context = canonical_value_digest({"manifest": digest(manifest),
                                      "join": node.node_id})
    contract = ObserverContract(
        "internet007-local-receiver", 1, subject, ground,
        ObservationContract.from_definition(
            "internet007.verified-composition", 1,
            {"operator": "ground.join", "source": "receiver-verified-predecessors"}),
        context,
    )
    receipt = ObserverReceipt.issue(
        contract, operation_id="internet007.compose-ground",
        input_digest=subject.content_digest, projection_value={"inputs": entries},
        subject_state_before_digest=subject.content_digest,
        subject_state_after_digest=subject.content_digest,
    )
    stage = ObserverPathStage(
        "observe", "internet007-local-receiver", "internet007-local-receiver",
        subject, subject, contract=contract, receipt=receipt,
    )
    witness = verify_observer_path(
        (stage,), ground=ground, context_digest=context,
        receiver_policy_digest=canonical_value_digest({
            "manifest": digest(manifest), "receiver": "internet007-local-receiver"}),
        observed_at=0, verify_carrier=lambda _: False,
        verify_observer=lambda s: s.contract == contract and s.receipt == receipt,
    )
    return {"dependencies": entries, "native_path_digest": witness.path_digest,
            "verification_scope": witness.to_dict()["verification_scope"]}


def verify_result(manifest: dict, item: dict, result: dict,
                  dag: NavigableComputationDAG) -> None:
    """Semantic type and source-pin checking in addition to native DAG digests."""
    require(type(result) is dict, "operation result must be an object")
    op, params = item["operator"], item["params"]
    if op == "github.git.commit":
        require(set(result) == {"repository", "sha", "tree", "parents",
                                "etag", "body_digest"} and
                result["repository"] == params["repository"] and
                result["sha"] == params["sha"] and hash40(result["tree"]) and
                type(result["parents"]) is int and 0 <= result["parents"] <= 100 and
                type(result["etag"]) is str and 0 < len(result["etag"]) <= 256 and
                "\n" not in result["etag"] and "\r" not in result["etag"] and
                hash64(result["body_digest"]), "Git source receipt invalid")
    elif op == "github.git.compare":
        require(set(result) == {"repository", "base", "head", "merge_base",
                                "ahead", "behind", "status", "body_digest"} and
                result["repository"] == params["repository"] and
                result["base"] == params["base"] and
                result["head"] == params["head"] and
                result["merge_base"] == params["expect"]["merge_base"] and
                type(result["ahead"]) is int and
                result["ahead"] == params["expect"]["ahead"] and
                type(result["behind"]) is int and
                result["behind"] == params["expect"]["behind"] and
                result["status"] == params["expect"]["status"] and
                hash64(result["body_digest"]), "Git graph receipt invalid")
    elif op == "http.etag.check":
        source = dag.result(params["source"])
        require(set(result) == {"source", "conditional", "mismatch",
                                "body_digest", "validator_digest"} and
                result["source"] == params["source"] and
                type(result["conditional"]) is int and result["conditional"] == 304 and
                type(result["mismatch"]) is int and result["mismatch"] == 200 and
                result["body_digest"] == source["body_digest"] and
                result["validator_digest"] == sha256(source["etag"].encode()),
                "native HTTP predicate receipt invalid")
    elif op == "ground.join":
        require(result == _result_for_join(
            manifest, next(n for n in dag.nodes if n.node_id == item["id"]), dag
        ), "composite Ground differs from exact native predecessor results")
    else:
        raise IntentionRefused("unknown runtime operator")


def verify_dag(manifest: dict, dag: NavigableComputationDAG) -> None:
    require(dag.digest == graph_template(manifest).digest, "source DAG identity changed")
    order = execution_order(manifest)
    committed = dag.committed_nodes
    require(committed == tuple(sorted(order[:len(committed)])),
            "stored DAG contains unexpected committed frontier")
    items = {entry["id"]: entry for entry in manifest["nodes"]}
    for name in order[:len(committed)]:
        verify_result(manifest, items[name], dag.result(name), dag)


def validate_state(manifest: dict, value: object) -> dict:
    require(type(value) is dict and set(value) == {
        "schema", "intention_id", "manifest_digest", "revision",
        "previous_digest", "dag", "digest"}, "workspace state schema invalid")
    require(value["schema"] == STATE_SCHEMA and
            value["intention_id"] == manifest["intention_id"] and
            value["manifest_digest"] == digest(manifest), "workspace scope changed")
    require(type(value["revision"]) is int and
            0 <= value["revision"] <= len(manifest["nodes"]), "state revision invalid")
    require(hash64(value["digest"]) and
            value["digest"] == digest({k: v for k, v in value.items() if k != "digest"}),
            "workspace state digest invalid")
    if value["revision"] == 0:
        require(value == genesis(manifest), "initial workspace genesis differs")
        return value
    require((value["revision"] == 1 and
             value["previous_digest"] == genesis(manifest)["digest"]) or
            (value["revision"] > 1 and hash64(value["previous_digest"])),
            "workspace state predecessor invalid")
    require(len(canonical(value)) <= MAX_CHECKPOINT_BYTES,
            "workspace checkpoint exceeds byte budget")
    try:
        dag = NavigableComputationDAG.from_snapshot(value["dag"])
        verify_dag(manifest, dag)
    except (TypeError, ValueError, KeyError, StopIteration) as exc:
        raise IntentionRefused("native computation DAG reconstruction refused") from exc
    require(len(dag.committed_nodes) == value["revision"],
            "state revision does not match native DAG commitments")
    return value


def advance(manifest: dict, before: dict, dag: NavigableComputationDAG) -> dict:
    validate_state(manifest, before)
    verify_dag(manifest, dag)
    require(len(dag.committed_nodes) == before["revision"] + 1,
            "quantum must advance exactly one accepted DAG operation")
    fields = {"schema": STATE_SCHEMA, "intention_id": manifest["intention_id"],
              "manifest_digest": digest(manifest), "revision": before["revision"] + 1,
              "previous_digest": before["digest"], "dag": dag.snapshot()}
    return validate_state(manifest, fields | {"digest": digest(fields)})


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise IntentionRefused("Internet service redirected outside admitted path")


def https_get(url: str, token: str | None, validator: str | None,
              byte_budget: int) -> tuple[int, dict[str, str], bytes]:
    """Real read-only existing GitHub service operation, not a remote E-CPU worker."""
    require(type(url) is str and
            re.fullmatch(
                r"https://api\.github\.com/repos/Kier73/(?:E-CPU|Virtual-Ground-Interpreter|In-Formation-Space|VL-I|VL-64)/(?:git/commits/[0-9a-f]{40}|compare/[0-9a-f]{40}\.\.\.[0-9a-f]{40})",
                url) is not None, "unauthorized Internet path")
    require(type(byte_budget) is int and 0 < byte_budget <= MAX_REMOTE_BYTES,
            "HTTP byte budget invalid")
    headers = {"Accept": "application/vnd.github+json",
               "User-Agent": "E-CPU-INTERNET-007",
               "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = "Bearer " + token
    if validator is not None:
        require(type(validator) is str and 0 < len(validator) <= 256 and
                "\r" not in validator and "\n" not in validator, "invalid validator")
        headers["If-None-Match"] = validator
    try:
        with build_opener(NoRedirect()).open(
            Request(url, headers=headers), timeout=20
        ) as response:
            status = response.status
            response_headers = {k.lower(): v for k, v in response.headers.items()}
            content = response.read(byte_budget + 1)
    except HTTPError as exc:
        require(exc.code == 304, f"GitHub HTTP status {exc.code}")
        status = exc.code
        response_headers = {k.lower(): v for k, v in exc.headers.items()}
        content = exc.read(byte_budget + 1)
    except (URLError, TimeoutError, OSError) as exc:
        raise IntentionRefused("Internet source path did not respond") from exc
    require(len(content) <= byte_budget, "Internet response exceeded admitted budget")
    return status, response_headers, content


def execute_one(manifest: dict, dag: NavigableComputationDAG,
                get: Callable[[str, str | None, int], tuple[int, Mapping[str, str], bytes]]
                ) -> str | None:
    """One E-CPU quantum; receipts come from native remote service transitions."""
    verify_dag(manifest, dag)
    if dag.is_complete:
        return None
    ready = dag.ready_nodes()
    require(bool(ready), "no dependency-qualified computational frontier")
    order = execution_order(manifest)
    next_name = order[len(dag.committed_nodes)]
    require(next_name in {n.node_id for n in ready}, "unexpected readiness")
    items = {entry["id"]: entry for entry in manifest["nodes"]}
    item = items[next_name]
    op, params = item["operator"], item["params"]
    limit = manifest["budget"]["max_response_bytes"]
    calls = 0

    def bounded(url: str, etag: str | None):
        nonlocal calls
        calls += 1
        require(calls <= manifest["budget"]["max_reads_per_quantum"],
                "Internet request budget exhausted")
        return get(url, etag, limit)

    if op == "github.git.commit":
        url = f'https://api.github.com/repos/{params["repository"]}/git/commits/{params["sha"]}'
        status, headers, raw = bounded(url, None)
        require(status == 200, "Git native object query returned non-200")
        obj = foundation.strict_json(raw)
        tree = obj.get("tree")
        parents = obj.get("parents")
        require(obj.get("sha") == params["sha"] and type(tree) is dict and
                hash40(tree.get("sha")) and type(parents) is list and
                all(type(p) is dict and hash40(p.get("sha")) for p in parents),
                "Git remote commit object cannot be admitted")
        result = {"repository": params["repository"], "sha": params["sha"],
                  "tree": tree["sha"], "parents": len(parents),
                  "etag": headers.get("etag"), "body_digest": sha256(raw)}
    elif op == "github.git.compare":
        url = (f'https://api.github.com/repos/{params["repository"]}/compare/'
               f'{params["base"]}...{params["head"]}')
        status, _, raw = bounded(url, None)
        require(status == 200, "Git native graph query returned non-200")
        obj = foundation.strict_json(raw)
        base = obj.get("merge_base_commit")
        require(type(base) is dict and hash40(base.get("sha")),
                "Git graph missing merge base")
        result = {"repository": params["repository"], "base": params["base"],
                  "head": params["head"], "merge_base": base["sha"],
                  "ahead": obj.get("ahead_by"), "behind": obj.get("behind_by"),
                  "status": obj.get("status"), "body_digest": sha256(raw)}
    elif op == "http.etag.check":
        src = dag.result(params["source"])
        url = f'https://api.github.com/repos/{src["repository"]}/git/commits/{src["sha"]}'
        status, _, body = bounded(url, src["etag"])
        require(status == 304 and body == b"", "HTTP matching predicate was not 304")
        mismatch, _, other = bounded(url, '"internet007-mismatching-validator"')
        require(mismatch == 200 and
                foundation.strict_json(other).get("sha") == src["sha"] and
                sha256(other) == src["body_digest"],
                "HTTP changed predicate did not return the pinned representation")
        result = {"source": params["source"], "conditional": status,
                  "mismatch": mismatch, "body_digest": src["body_digest"],
                  "validator_digest": sha256(src["etag"].encode())}
    elif op == "ground.join":
        result = _result_for_join(
            manifest, next(n for n in dag.nodes if n.node_id == next_name), dag)
    else:
        raise IntentionRefused("unsupported execution operator")
    verify_result(manifest, item, result, dag)
    require(dag.commit(next_name, result) is False, "replayed accepted DAG effect")
    return next_name


def remote_state(token: str, manifest: dict) -> tuple[dict | None, str | None]:
    branch_url = f"{API}/git/ref/heads/{BRANCH}"
    status, _, raw = foundation.request("GET", branch_url, token)
    require(status == 200, "workspace branch missing")
    branch = foundation.strict_json(raw)
    ref = branch.get("object")
    require(branch.get("ref") == "refs/heads/" + BRANCH and
            type(ref) is dict and hash40(ref.get("sha")), "workspace branch invalid")
    status, _, raw = foundation.request(
        "GET", f"{API}/contents/{state_path(manifest)}?ref={BRANCH}", token)
    if status == 404:
        return None, None
    require(status == 200, "workspace checkpoint unavailable")
    entry = foundation.strict_json(raw)
    require(entry.get("encoding") == "base64" and
            type(entry.get("content")) is str and hash40(entry.get("sha")),
            "GitHub object lacks exact bytes and blob SHA")
    try:
        decoded = base64.b64decode(entry["content"].replace("\n", ""), validate=True)
    except (ValueError, TypeError) as exc:
        raise IntentionRefused("invalid GitHub checkpoint encoding") from exc
    require(len(decoded) <= MAX_CHECKPOINT_BYTES, "stored native state too large")
    return validate_state(manifest, foundation.strict_json(decoded)), entry["sha"]


def publish(token: str, manifest: dict, state: dict,
            old_blob: str | None) -> str:
    validate_state(manifest, state)
    require(old_blob is None or hash40(old_blob), "old Git blob identity invalid")
    run_id = os.environ.get("GITHUB_RUN_ID")
    attempt = os.environ.get("GITHUB_RUN_ATTEMPT")
    require(type(run_id) is str and re.fullmatch(r"[1-9][0-9]{0,19}", run_id) is not None and
            type(attempt) is str and re.fullmatch(r"[1-9][0-9]{0,4}", attempt) is not None,
            "online publication requires a concrete hosted workflow invocation")
    message = (f"INTERNET-007 {manifest['intention_id']} revision {state['revision']} "
               f"[run={run_id} attempt={attempt}]")
    body = {"message": message,
            "branch": BRANCH,
            "content": base64.b64encode(canonical(state) + b"\n").decode("ascii")}
    if old_blob is not None:
        body["sha"] = old_blob
    status, _, raw = foundation.request(
        "PUT", f"{API}/contents/{state_path(manifest)}",
        token, data=canonical(body))
    require(status in (200, 201), "conditional state publication refused")
    result = foundation.strict_json(raw).get("content")
    require(type(result) is dict and hash40(result.get("sha")),
            "publication has no Git blob identity")
    return result["sha"]


def read_manifest(path: str) -> dict:
    require(type(path) is str and MANIFEST_FILE.fullmatch(path) is not None,
            "unapproved intention manifest path")
    source = Path(path)
    require(source.is_file() and not source.is_symlink() and
            source.stat().st_size <= MAX_MANIFEST_BYTES,
            "manifest file absent or oversized")
    try:
        manifest = foundation.strict_json(source.read_bytes())
    except (OSError, UnicodeError, ValueError) as exc:
        raise IntentionRefused("manifest is not valid strict JSON") from exc
    require(path == f'intentions/internet007/{manifest.get("intention_id")}.json',
            "manifest identity differs from its repository path")
    return admit_manifest(manifest)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--intention-file",
                        default="intentions/internet007/public-source-grounds.json")
    parser.add_argument("--mode", choices=("initialize", "step"), required=True)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--output", default="internet007-result.json")
    args = parser.parse_args()
    require(args.live, "explicit live online execution required")
    require(os.environ.get("GITHUB_REPOSITORY") == foundation.REPOSITORY,
            "execution requires the admitted E-CPU repository")
    token = os.environ.get("GITHUB_TOKEN")
    require(type(token) is str and bool(token), "GitHub token required")
    manifest = read_manifest(args.intention_file)
    state, blob = remote_state(token, manifest)
    if args.mode == "initialize":
        require(os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch",
                "new workspace requires explicitly dispatched admission")
        require(state is None and blob is None, "existing workspace cannot be reset")
        next_state = genesis(manifest)
        operation = "genesis"
    else:
        require(state is not None and blob is not None,
                "workspace missing; initialize explicitly instead of silent reset")
        dag = (graph_template(manifest) if state["revision"] == 0 else
               NavigableComputationDAG.from_snapshot(state["dag"]))
        verify_dag(manifest, dag)
        def get(url, validator, limit):
            return https_get(url, token, validator, limit)
        operation = execute_one(manifest, dag, get)
        next_state = advance(manifest, state, dag) if operation else state
    committed = publish(token, manifest, next_state, blob) if operation else None
    report = {"schema": "mailcpu.internet007.report.v1",
              "intention_id": manifest["intention_id"],
              "manifest_digest": digest(manifest), "mode": args.mode,
              "previous_revision": state["revision"] if state is not None else None,
              "revision": next_state["revision"], "operation": operation,
              "state_digest": next_state["digest"],
              "published_blob_sha": committed, "status": "complete" if
              next_state["revision"] == len(manifest["nodes"]) else "recoverable",
              "max_cost_usd": 0,
              "authority": "owner-approved-manifest-and-Git-CAS-not-M3-quorum"}
    Path(args.output).write_bytes(canonical(report) + b"\n")
    print(f"INTERNET-007 {manifest['intention_id']} revision={next_state['revision']} "
          f"operation={operation} committed={committed is not None}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
