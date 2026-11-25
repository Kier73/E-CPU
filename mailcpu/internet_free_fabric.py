"""INTERNET-005: bounded GitHub-native path computation with recoverable online state.

A real GitHub service supplies the Git graph and HTTP conditional predicate.
The standard-library client verifies their responses, then publishes a compact
content-addressed checkpoint through GitHub's SHA-guarded Contents API.
This is *not* M3 quorum recovery, WAN router execution, or an always-on CPU.
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

SCHEMA = "mailcpu.internet-free-fabric-checkpoint.v1"
OBS_SCHEMA = "mailcpu.internet-free-fabric-observation.v1"
REPOSITORY = "Kier73/E-CPU"
STATE_BRANCH = "research/internet-005-state"
STATE_PATH = "state/internet005-checkpoint.json"
BASE = "9a34c11147db7d8619b65b6058fa121ab9b1c43c"
HEAD = "afcd39be08ee2f64992763e913c5370968232b84"
COMMIT_URL = f"https://api.github.com/repos/{REPOSITORY}/git/commits/{HEAD}"
COMPARE_URL = f"https://api.github.com/repos/{REPOSITORY}/compare/{BASE}...{HEAD}"
API_BASE = f"https://api.github.com/repos/{REPOSITORY}"
MAX_REPLY = 2_000_000
MAX_STATE = 32768
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
HEX40 = re.compile(r"[0-9a-f]{40}\Z")
INTENTION = {
    "kind": "internet-native-service-graph-and-conditional-observation",
    "repository": REPOSITORY, "base": BASE, "head": HEAD,
    "expected_ahead": 11, "expected_behind": 0,
}
WORKSPACE_ID = hashlib.sha256(json.dumps(INTENTION, sort_keys=True,
    separators=(",", ":")).encode()).hexdigest()


class FreeFabricRefused(ValueError):
    """The live path or persisted observation failed qualification."""


def require(predicate: bool, reason: str) -> None:
    if not predicate:
        raise FreeFabricRefused(reason)


def canonical(obj: object) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def digest(obj: object) -> str:
    return hashlib.sha256(canonical(obj)).hexdigest()


def strict_json(data: bytes) -> dict:
    def pairs(items):
        result = {}
        for k, v in items:
            require(k not in result, "duplicate JSON key")
            result[k] = v
        return result
    try:
        value = json.loads(data, object_pairs_hook=pairs,
                           parse_constant=lambda _: require(False, "nonfinite JSON value"))
    except (ValueError, UnicodeError, TypeError) as exc:
        raise FreeFabricRefused("invalid JSON response") from exc
    require(type(value) is dict, "expected JSON object")
    return value


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise FreeFabricRefused("redirect is not an admitted path")


def request(method: str, url: str, token: str | None = None,
            *, etag: str | None = None, data: bytes | None = None) -> tuple[int, dict, bytes]:
    """Bounded authorized GitHub HTTPS operation; no arbitrary host or redirect."""
    require(url.startswith(API_BASE + "/"), "unapproved Internet endpoint")
    require(method in ("GET", "PUT"), "unapproved method")
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "E-CPU-INTERNET-005",
               "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = "Bearer " + token
    if etag is not None:
        require(len(etag) <= 256 and "\n" not in etag and "\r" not in etag,
                "unbounded HTTP validator")
        headers["If-None-Match"] = etag
    if method == "PUT":
        require(token is not None and data is not None, "writes need explicit credential")
        headers["Content-Type"] = "application/json"
    call = Request(url, headers=headers, data=data, method=method)
    try:
        with build_opener(NoRedirect()).open(call, timeout=20) as response:
            status = response.status
            response_headers = {k.lower(): v for k, v in response.headers.items()}
            raw = response.read(MAX_REPLY + 1)
    except HTTPError as exc:
        if exc.code not in (304, 404):
            raise FreeFabricRefused(f"GitHub HTTP status {exc.code}") from exc
        status = exc.code
        response_headers = {k.lower(): v for k, v in exc.headers.items()}
        raw = exc.read(MAX_REPLY + 1)
    except (URLError, TimeoutError, OSError) as exc:
        raise FreeFabricRefused("Internet path unavailable") from exc
    require(len(raw) <= MAX_REPLY, "Internet response byte budget exceeded")
    return status, response_headers, raw


HttpGet = Callable[[str, str | None], tuple[int, Mapping[str, str], bytes]]


def observe_native_paths(get: HttpGet) -> dict:
    """Qualify two already-existing Internet service operations independently."""
    status, headers, raw = get(COMMIT_URL, None)
    require(status == 200, "pinned Git object observation was not 200")
    commit = strict_json(raw)
    require(commit.get("sha") == HEAD, "pinned Git object identity changed")
    etag = headers.get("etag")
    require(type(etag) is str and 0 < len(etag) <= 256,
            "missing bounded representation validator")
    conditional, _, no_body = get(COMMIT_URL, etag)
    require(conditional == 304 and no_body == b"",
            "Internet HTTP conditional predicate was not observed")
    changed, _, other_body = get(COMMIT_URL, '"internet005-unmatched-validator"')
    require(changed == 200 and strict_json(other_body).get("sha") == HEAD,
            "nonmatching HTTP predicate did not return pinned source")
    require(hashlib.sha256(raw).digest() == hashlib.sha256(other_body).digest(),
            "pinned representation changed across conditional probes")

    compared, _, comparison_bytes = get(COMPARE_URL, None)
    require(compared == 200, "Git comparison operator did not return 200")
    graph = strict_json(comparison_bytes)
    merge_base = graph.get("merge_base_commit")
    require(type(merge_base) is dict and merge_base.get("sha") == BASE,
            "Git service merge base disagrees with independent pinned Ground")
    require(type(graph.get("ahead_by")) is int and graph["ahead_by"] == 11 and
            type(graph.get("behind_by")) is int and graph["behind_by"] == 0,
            "Git service graph divergence disagrees with pinned oracle")
    require(graph.get("status") == "ahead", "unexpected Git service graph status")

    receipt = {
        "schema": OBS_SCHEMA, "workspace_id": WORKSPACE_ID,
        "commit_sha": HEAD, "commit_body_sha256": hashlib.sha256(raw).hexdigest(),
        "validator_sha256": hashlib.sha256(etag.encode()).hexdigest(),
        "conditional_status": 304, "changed_predicate_status": 200,
        "compare_base": BASE, "compare_head": HEAD, "merge_base": BASE,
        "ahead_by": 11, "behind_by": 0,
        "compare_body_sha256": hashlib.sha256(comparison_bytes).hexdigest(),
        "service_operations": ["github.git.commit", "http.if-none-match", "github.git.compare"],
        "source_code_payload_bytes": 0,
        "claim": "internet-service-native-not-physical-router-computation",
    }
    return receipt | {"digest": digest(receipt)}


def validate_observation(receipt: object) -> None:
    require(type(receipt) is dict, "observation receipt must be an object")
    fields = {"schema", "workspace_id", "commit_sha", "commit_body_sha256",
              "validator_sha256", "conditional_status", "changed_predicate_status",
              "compare_base", "compare_head", "merge_base", "ahead_by", "behind_by",
              "compare_body_sha256", "service_operations", "source_code_payload_bytes",
              "claim", "digest"}
    require(set(receipt) == fields, "observation receipt fields changed")
    require(receipt["schema"] == OBS_SCHEMA and receipt["workspace_id"] == WORKSPACE_ID,
            "observation receipt scope differs")
    require(receipt["commit_sha"] == HEAD and receipt["compare_base"] == BASE and
            receipt["compare_head"] == HEAD and receipt["merge_base"] == BASE,
            "observation source pins differ")
    require(type(receipt["ahead_by"]) is int and receipt["ahead_by"] == 11 and
            type(receipt["behind_by"]) is int and receipt["behind_by"] == 0,
            "unexpected graph counts")
    require(type(receipt["conditional_status"]) is int and
            receipt["conditional_status"] == 304 and
            type(receipt["changed_predicate_status"]) is int and
            receipt["changed_predicate_status"] == 200, "unexpected HTTP result")
    require(receipt["service_operations"] ==
            ["github.git.commit", "http.if-none-match", "github.git.compare"] and
            type(receipt["source_code_payload_bytes"]) is int and
            receipt["source_code_payload_bytes"] == 0 and
            receipt["claim"] == "internet-service-native-not-physical-router-computation",
            "unsupported computation provenance")
    for field in ("commit_body_sha256", "validator_sha256", "compare_body_sha256"):
        require(type(receipt[field]) is str and HEX64.fullmatch(receipt[field]) is not None,
                "invalid evidence digest")
    require(receipt["digest"] == digest({k: v for k, v in receipt.items() if k != "digest"}),
            "observation receipt has been altered")


def validate_checkpoint(value: object) -> dict:
    require(type(value) is dict, "checkpoint must be an object")
    fields = {"schema", "workspace_id", "revision", "previous_digest",
              "observation", "digest"}
    require(set(value) == fields, "checkpoint fields changed")
    require(value["schema"] == SCHEMA and value["workspace_id"] == WORKSPACE_ID,
            "wrong workspace identity")
    require(type(value["revision"]) is int and 1 <= value["revision"] <= 10**12,
            "invalid checkpoint revision")
    require(type(value["previous_digest"]) is str and
            HEX64.fullmatch(value["previous_digest"]) is not None or
            value["revision"] == 1 and value["previous_digest"] is None,
            "invalid checkpoint predecessor")
    validate_observation(value["observation"])
    require(type(value["digest"]) is str and
            value["digest"] == digest({k: v for k, v in value.items() if k != "digest"}),
            "checkpoint content digest mismatch")
    require(len(canonical(value)) <= MAX_STATE, "checkpoint byte budget exceeded")
    return value


def successor(previous: dict | None, observation: dict) -> dict:
    validate_observation(observation)
    if previous is not None:
        validate_checkpoint(previous)
    revision = previous["revision"] + 1 if previous else 1
    require(revision <= 10**12, "revision budget exhausted")
    candidate = {
        "schema": SCHEMA, "workspace_id": WORKSPACE_ID, "revision": revision,
        "previous_digest": previous["digest"] if previous else None,
        "observation": observation,
    }
    return validate_checkpoint(candidate | {"digest": digest(candidate)})


def bind_native_observer_path(observation: dict) -> dict:
    """Carry verified remote-service facts into native E-CPU observer evidence.

    The receiver issues the E-CPU observer receipt after checking the HTTPS
    response. This names a *local observer*, not an authenticated GitHub
    machine, native WAN carrier, or remote E-CPU peer.
    """
    from .observer_orbit import ObserverContract, ObserverReceipt
    from .observer_path_evidence import ObserverPathStage, verify_observer_path
    from .semantic_translation import (
        ObservationContract, RepresentationRef, canonical_value_digest,
    )

    validate_observation(observation)
    ground = RepresentationRef.from_payload("internet005.ground", 1, INTENTION)
    subject = RepresentationRef.from_payload("internet005.service-evidence", 1, observation)
    context = canonical_value_digest({"workspace_id": WORKSPACE_ID, "source": HEAD})
    projection = ObservationContract.from_definition(
        "internet005.remote-service-projection", 1,
        {"exact": True, "source": "verified-GitHub-HTTPS-response"},
    )
    contract = ObserverContract(
        "internet005-local-receiver", 1, subject, ground, projection, context,
    )
    native_receipt = ObserverReceipt.issue(
        contract, operation_id="internet005.verify-service-observation",
        input_digest=subject.content_digest,
        projection_value={"native_graph_ahead": observation["ahead_by"],
                          "native_http_predicate": observation["conditional_status"],
                          "source_receipt": observation["digest"]},
        subject_state_before_digest=subject.content_digest,
        subject_state_after_digest=subject.content_digest,
    )
    stage = ObserverPathStage(
        "observe", "internet005-local-receiver", "internet005-local-receiver",
        subject, subject, contract=contract, receipt=native_receipt,
    )
    path = verify_observer_path(
        (stage,), ground=ground, context_digest=context,
        receiver_policy_digest=canonical_value_digest({
            "allow": "only-pinned-internet005-remote-service-observation",
            "workspace_id": WORKSPACE_ID,
        }), observed_at=0, verify_carrier=lambda _: False,
        verify_observer=lambda item: (
            item.contract == contract and item.receipt == native_receipt
        ),
    )
    return path.to_dict()


def state_url() -> str:
    return f"{API_BASE}/contents/{STATE_PATH}?ref={STATE_BRANCH}"


def read_remote_state(token: str) -> tuple[dict | None, str | None]:
    branch_url = f"{API_BASE}/git/ref/heads/{STATE_BRANCH}"
    ref_status, _, ref_raw = request("GET", branch_url, token)
    require(ref_status == 200, "isolated state branch is missing; refuse reset")
    ref = strict_json(ref_raw)
    obj = ref.get("object")
    require(ref.get("ref") == "refs/heads/" + STATE_BRANCH and
            type(obj) is dict and type(obj.get("sha")) is str and
            HEX40.fullmatch(obj["sha"]) is not None,
            "isolated state branch identity is invalid")
    status, _, raw = request("GET", state_url(), token)
    if status == 404:
        return None, None
    require(status == 200, "state read failed")
    envelope = strict_json(raw)
    content = envelope.get("content")
    sha = envelope.get("sha")
    require(envelope.get("encoding") == "base64" and type(content) is str and
            type(sha) is str and HEX40.fullmatch(sha) is not None,
            "remote state object malformed")
    try:
        binary = base64.b64decode(content.replace("\n", ""), validate=True)
    except (ValueError, TypeError) as exc:
        raise FreeFabricRefused("invalid checkpoint base64") from exc
    require(len(binary) <= MAX_STATE, "remote state exceeds byte budget")
    return validate_checkpoint(strict_json(binary)), sha


def publish_remote_state(token: str, state: dict, old_blob: str | None) -> str:
    validate_checkpoint(state)
    request_body = {
        "message": f"INTERNET-005 checkpoint revision {state['revision']}",
        "content": base64.b64encode(canonical(state) + b"\n").decode("ascii"),
        "branch": STATE_BRANCH,
    }
    if old_blob is not None:
        require(HEX40.fullmatch(old_blob) is not None, "invalid old Git blob SHA")
        request_body["sha"] = old_blob
    status, _, raw = request("PUT", f"{API_BASE}/contents/{STATE_PATH}", token,
                             data=canonical(request_body))
    require(status in (200, 201), "conditional state publication failed")
    response = strict_json(raw)
    result = response.get("content")
    require(type(result) is dict and type(result.get("sha")) is str and
            HEX40.fullmatch(result["sha"]) is not None,
            "GitHub did not return the published blob identity")
    return result["sha"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Perform bounded live HTTPS probes")
    parser.add_argument("--publish", action="store_true",
                        help="Commit the verified successor to the isolated state branch")
    parser.add_argument("--output", default="internet005-result.json")
    args = parser.parse_args()
    require(args.live, "use --live explicitly; no synthetic result is reported")
    require(not args.publish or args.live, "publication needs live observation")
    require(os.environ.get("GITHUB_REPOSITORY") == REPOSITORY,
            "workspace repository is not admitted")
    token = os.environ.get("GITHUB_TOKEN")
    require(type(token) is str and len(token) > 0, "GitHub token is required")
    previous, blob = read_remote_state(token)
    def get(url: str, etag: str | None):
        require(url in (COMMIT_URL, COMPARE_URL), "unknown Git operator")
        return request("GET", url, token, etag=etag)
    evidence = observe_native_paths(get)
    native_path = bind_native_observer_path(evidence)
    state = successor(previous, evidence)
    committed_blob = publish_remote_state(token, state, blob) if args.publish else None
    report = {
        "schema": "mailcpu.internet-free-fabric-report.v1",
        "workspace_id": WORKSPACE_ID, "prior_revision": previous["revision"] if previous else 0,
        "next_revision": state["revision"], "next_digest": state["digest"],
        "previous_digest": state["previous_digest"], "observation": evidence,
        "native_receiver_path": native_path,
        "published": committed_blob is not None, "published_blob_sha": committed_blob,
        "physical_execution": "GitHub-hosted Python observer",
        "external_execution": "GitHub Git and HTTP service-native operations",
        "storage": "GitHub isolated state branch, optimistic blob-SHA compare-and-swap",
        "limitation": "No M3 quorum, independent replicas, WAN path attestation, or always-on CPU",
    }
    Path(args.output).write_bytes(canonical(report) + b"\n")
    print(f"INTERNET-005 revision={state['revision']} published={report['published']} "
          f"checkpoint={state['digest']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
