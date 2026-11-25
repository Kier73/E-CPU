"""INTERNET-007: generic public service intention admission and native DAG rejoin."""
from __future__ import annotations

import base64
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from mailcpu import internet_intention_ingress as ingress
from mailcpu import internet_free_fabric as source
from mailcpu.computation_dag import NavigableComputationDAG

MANIFEST_PATH = Path(__file__).resolve().parents[1] / "intentions/internet007/public-source-grounds.json"


@pytest.fixture
def manifest():
    return ingress.admit_manifest(json.loads(MANIFEST_PATH.read_text()))


def fake_get(url, validator, limit):
    assert limit <= ingress.MAX_REMOTE_BYTES
    if "/git/commits/" in url:
        sha = url.rsplit("/", 1)[-1]
        body = source.canonical({
            "sha": sha, "tree": {"sha": "c" * 40},
            "parents": [{"sha": "b" * 40}],
        })
        if validator == '"public-etag-v1"':
            return (304, {}, b"")
        return (200, {"etag": '"public-etag-v1"'}, body)
    if "/compare/" in url:
        return (200, {}, source.canonical({
            "merge_base_commit": {"sha": source.BASE},
            "ahead_by": 11, "behind_by": 0, "status": "ahead",
        }))
    raise AssertionError("unadmitted source operation")


def advance(manifest):
    dag = ingress.graph_template(manifest)
    checkpoint = ingress.genesis(manifest)
    history = [checkpoint]
    applied = []
    while True:
        operation = ingress.execute_one(manifest, dag, fake_get)
        if operation is None:
            break
        checkpoint = ingress.advance(manifest, checkpoint, dag)
        history.append(checkpoint)
        applied.append(operation)
        dag = NavigableComputationDAG.from_snapshot(checkpoint["dag"])
        ingress.verify_dag(manifest, dag)
    return history, dag, applied


def test_manifest_selects_five_native_operations_across_two_public_repos(manifest):
    assert len(manifest["nodes"]) == 5
    assert ingress.execution_order(manifest) == (
        "a-ecpu-commit", "b-vgi-commit", "c-http-etag", "d-graph", "z-join"
    )
    assert ingress.genesis(manifest)["revision"] == 0
    assert ingress.state_path(manifest).startswith("state/internet007/public-source-grounds-")


def test_native_dag_advances_across_five_independent_reconstructions(manifest):
    states, dag, committed = advance(manifest)
    assert committed == list(ingress.execution_order(manifest))
    assert [s["revision"] for s in states] == list(range(6))
    for earlier, later in zip(states, states[1:]):
        assert later["previous_digest"] == earlier["digest"]
    assert dag.is_complete
    join = dag.result("z-join")
    assert len(join["dependencies"]) == 4
    assert len(join["native_path_digest"]) == 64
    assert join["verification_scope"] == "receiver_callbacks_not_external_attestation"
    assert ingress.execute_one(manifest, dag, lambda *x: 1 / 0) is None


def test_fresh_python_process_can_reconstruct_remaining_work(manifest, tmp_path):
    states, _, _ = advance(manifest)
    path = tmp_path / "state.json"
    path.write_bytes(source.canonical(states[2]))
    manifest_file = tmp_path / "manifest.json"
    manifest_file.write_bytes(source.canonical(manifest))
    script = (
        "import json,sys;"
        "from mailcpu.internet_intention_ingress import validate_state;"
        "from mailcpu.computation_dag import NavigableComputationDAG;"
        "m=json.load(open(sys.argv[1]));s=json.load(open(sys.argv[2]));"
        "validate_state(m,s);d=NavigableComputationDAG.from_snapshot(s['dag']);"
        "print(json.dumps([n.node_id for n in d.ready_nodes()]))"
    )
    result = subprocess.check_output(
        [sys.executable, "-c", script, str(manifest_file), str(path)],
        cwd=MANIFEST_PATH.parents[2], text=True)
    assert json.loads(result) == ["c-http-etag", "d-graph"]


@pytest.mark.parametrize("change", ["fee", "external", "operator", "cycle",
                                    "missing_predecessor", "duplicate", "bad_sha",
                                    "param", "too_many_reads"])
def test_invalid_intentions_refuse_before_execution(manifest, change):
    m = copy.deepcopy(manifest)
    if change == "fee":
        m["budget"]["max_cost_usd"] = 1
    elif change == "external":
        m["nodes"][0]["params"]["repository"] = "someone-else/compute"
    elif change == "operator":
        m["nodes"][0]["operator"] = "python.exec"
    elif change == "cycle":
        m["nodes"][-1]["dependencies"].append("z-join")
    elif change == "missing_predecessor":
        m["nodes"][-1]["dependencies"].append("unknown")
    elif change == "duplicate":
        m["nodes"][1]["id"] = "a-ecpu-commit"
    elif change == "bad_sha":
        m["nodes"][0]["params"]["sha"] = "main"
    elif change == "param":
        m["nodes"][0]["params"]["dangerous"] = "run command"
    else:
        m["budget"]["max_reads_per_quantum"] = 999
    with pytest.raises((ingress.IntentionRefused, ValueError)):
        ingress.admit_manifest(m)


@pytest.mark.parametrize("change", ["state_digest", "source_tree", "commit_result",
                                    "foreign_workspace", "revision", "predecessor"])
def test_corrupted_or_reinterpreted_state_refused(manifest, change):
    states, _, _ = advance(manifest)
    state = copy.deepcopy(states[-1])
    if change == "state_digest":
        state["digest"] = "0" * 64
    elif change == "source_tree":
        state["dag"]["state"]["commits"][0]["result"]["tree"] = "a" * 40
    elif change == "commit_result":
        state["dag"]["state"]["commits"][0]["result"]["sha"] = source.BASE
    elif change == "foreign_workspace":
        state["manifest_digest"] = "f" * 64
    elif change == "revision":
        state["revision"] = True
    else:
        state["previous_digest"] = None
    with pytest.raises((ingress.IntentionRefused, ValueError, KeyError)):
        ingress.validate_state(manifest, state)


def test_zero_currency_budget_and_source_identity_are_binding(manifest):
    original = ingress.genesis(manifest)
    changed = copy.deepcopy(manifest)
    changed["purpose"] += " second study"
    assert ingress.digest(changed) != ingress.digest(manifest)
    assert ingress.state_path(changed) != ingress.state_path(manifest)
    with pytest.raises(ingress.IntentionRefused):
        ingress.validate_state(changed, original)


def test_http_conditional_response_must_be_observed_not_inferred(manifest):
    dag = ingress.graph_template(manifest)
    assert ingress.execute_one(manifest, dag, fake_get) == "a-ecpu-commit"
    def wrong(url, validator, limit):
        if validator is not None:
            return (200, {}, source.canonical({"sha": "0" * 40}))
        return fake_get(url, validator, limit)
    assert ingress.execute_one(manifest, dag, fake_get) == "b-vgi-commit"
    with pytest.raises(ingress.IntentionRefused):
        ingress.execute_one(manifest, dag, wrong)
    assert "c-http-etag" not in dag.committed_nodes


def test_http_request_refuses_nonallowlisted_service():
    with pytest.raises(ingress.IntentionRefused):
        ingress.https_get("https://example.com/arbitrary", None, None, 1000)
    with pytest.raises(ingress.IntentionRefused):
        ingress.https_get("https://api.github.com/repos/Kier73/E-CPU/contents/.env",
                          None, None, 1000)


def test_recovered_state_missing_fails_in_step_mode(manifest, monkeypatch):
    branch = source.canonical({"ref": "refs/heads/" + ingress.BRANCH,
                               "object": {"sha": "d" * 40}})
    def responder(method, url, *args, **kw):
        return (200, {}, branch) if "/git/ref/heads/" in url else (404, {}, b"")
    monkeypatch.setattr(source, "request", responder)
    assert ingress.remote_state("token", manifest) == (None, None)


def test_git_checkpoint_uses_original_blob_for_cas(monkeypatch, manifest):
    monkeypatch.setenv("GITHUB_RUN_ID", "12345001")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    history, _, _ = advance(manifest)
    messages = []
    def write(method, url, token, *, data=None, **kw):
        messages.append((method, url, json.loads(data)))
        return (200, {}, source.canonical({"content": {"sha": "a" * 40}}))
    monkeypatch.setattr(source, "request", write)
    assert ingress.publish("token", manifest, history[-1], "b" * 40) == "a" * 40
    body = messages[0][2]
    assert body["sha"] == "b" * 40
    assert body["branch"] == ingress.BRANCH
    assert json.loads(base64.b64decode(body["content"])) == history[-1]


def test_response_budget_and_string_resource_policy_are_strict(manifest):
    m = copy.deepcopy(manifest)
    m["budget"]["max_cost_usd"] = False
    with pytest.raises(ingress.IntentionRefused):
        ingress.admit_manifest(m)
    m = copy.deepcopy(manifest)
    m["nodes"][0]["params"]["repository"] = ["Kier73/E-CPU"]
    with pytest.raises((ingress.IntentionRefused, TypeError)):
        ingress.admit_manifest(m)


def test_second_repository_intention_runs_without_new_runtime_code():
    filename = (MANIFEST_PATH.parent / "cross-source-structures.json")
    manifest = ingress.admit_manifest(json.loads(filename.read_text()))
    history, dag, applied = advance(manifest)
    assert applied == ["a-ifs", "b-vli", "z-join"]
    assert history[-1]["revision"] == 3
    assert dag.is_complete
    assert len(dag.result("z-join")["dependencies"]) == 2
    assert history[-1]["manifest_digest"] != ingress.digest(
        json.loads(MANIFEST_PATH.read_text())
    )


def test_disallowed_source_types_and_unrecognized_ops_refuse_cleanly(manifest):
    invalid = copy.deepcopy(manifest)
    invalid["nodes"][0]["operator"] = ["github.git.commit"]
    with pytest.raises(ingress.IntentionRefused):
        ingress.admit_manifest(invalid)
    invalid = copy.deepcopy(manifest)
    invalid["nodes"][0]["params"]["repository"] = ["Kier73/E-CPU"]
    with pytest.raises(ingress.IntentionRefused):
        ingress.admit_manifest(invalid)


def test_per_quantum_read_budget_refuses_unfunded_second_http_observation(manifest):
    limited = copy.deepcopy(manifest)
    limited["budget"]["max_reads_per_quantum"] = 1
    limited = ingress.admit_manifest(limited)
    dag = ingress.graph_template(limited)
    assert ingress.execute_one(limited, dag, fake_get) == "a-ecpu-commit"
    assert ingress.execute_one(limited, dag, fake_get) == "b-vgi-commit"
    with pytest.raises(ingress.IntentionRefused, match="request budget exhausted"):
        ingress.execute_one(limited, dag, fake_get)
    assert "c-http-etag" not in dag.committed_nodes
