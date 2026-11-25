"""INTERNET-006 cross-run pure online DAG and refusal controls."""
import base64
import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from mailcpu import internet_fabric_dag as online
from mailcpu import internet_free_fabric as source
from mailcpu.computation_dag import NavigableComputationDAG


def fake_get(url, validator):
    if url == source.COMMIT_URL:
        if validator is None:
            return (200, {"etag": '"github-test-etag"'}, source.canonical({"sha": source.HEAD}))
        if validator == '"github-test-etag"':
            return (304, {}, b"")
        return (200, {}, source.canonical({"sha": source.HEAD}))
    if url == source.COMPARE_URL:
        return 200, {}, source.canonical({
            "merge_base_commit": {"sha": source.BASE},
            "ahead_by": 11, "behind_by": 0, "status": "ahead",
        })
    raise AssertionError("unadmitted endpoint")


def advance():
    dag = online.graph_template()
    previous = None
    history = []
    for node in online.ORDER:
        assert online.run_one(dag, fake_get) == node
        following = online.checkpoint(previous, dag)
        history.append(following)
        restored = NavigableComputationDAG.from_snapshot(following["dag"])
        assert restored.committed_nodes == dag.committed_nodes
        assert online.validate_snapshot(restored.snapshot()).digest == dag.digest
        previous, dag = following, restored
    assert dag.is_complete and online.run_one(dag, fake_get) is None
    assert len({item["digest"] for item in history}) == 4
    return history


def test_four_native_service_operations_across_ephemeral_runner_lifetimes():
    history = advance()
    assert [x["revision"] for x in history] == [1, 2, 3, 4]
    assert history[0]["previous_digest"] is None
    for left, right in zip(history, history[1:]):
        assert right["previous_digest"] == left["digest"]
    dag = NavigableComputationDAG.from_snapshot(history[-1]["dag"])
    assert dag.is_complete
    native = dag.result("compose")
    assert native["scope"] == "receiver_callbacks_not_external_attestation"
    assert native["observation"]["ahead_by"] == 11
    assert len(native["native_receiver_path_digest"]) == 64


def test_unchanged_graph_snapshot_survives_new_python_process(tmp_path):
    history = advance()
    first = history[0]
    path = tmp_path / "checkpoint.json"
    path.write_bytes(source.canonical(first))
    child = ("import json,sys;"
             "from mailcpu.internet_fabric_dag import validate_checkpoint,run_one,checkpoint;"
             "from mailcpu.computation_dag import NavigableComputationDAG;"
             "state=validate_checkpoint(json.load(open(sys.argv[1])));"
             "dag=NavigableComputationDAG.from_snapshot(state['dag']);"
             "print(json.dumps({'revision':state['revision'],"
             "'ready':[n.node_id for n in dag.ready_nodes()]}))")
    result = subprocess.check_output(
        [sys.executable, "-c", child, str(path)],
        cwd=Path(__file__).resolve().parents[1], text=True)
    assert json.loads(result) == {"revision": 1, "ready": ["http-conditional"]}


@pytest.mark.parametrize("change", ["workspace", "revision", "digest",
                                    "dag_result", "dag_node", "predecessor"])
def test_changed_checkpoint_and_dag_reconstruction_refuse(change):
    history = advance()
    checkpoint = copy.deepcopy(history[-1])
    if change == "workspace":
        checkpoint["workspace_id"] = "0" * 64
    elif change == "revision":
        checkpoint["revision"] = 3
    elif change == "digest":
        checkpoint["digest"] = "a" * 64
    elif change == "dag_result":
        checkpoint["dag"]["state"]["commits"][0]["result"]["sha"] = source.BASE
    elif change == "dag_node":
        checkpoint["dag"]["state"]["nodes"][0]["operation"] = "unauthorized.operator"
    else:
        checkpoint["previous_digest"] = None
    with pytest.raises((online.OnlineDAGRefused, ValueError)):
        online.validate_checkpoint(checkpoint)


@pytest.mark.parametrize("kind", ["changed_etag", "changed_body", "changed_graph",
                                  "unexpected_status"])
def test_external_operations_are_actual_and_exact(kind):
    def wrong(url, etag):
        status, headers, body = fake_get(url, etag)
        if kind == "changed_etag" and etag == '"github-test-etag"':
            return 200, {}, source.canonical({"sha": source.HEAD})
        if kind == "changed_body" and url == source.COMMIT_URL and etag is not None and status == 200:
            return status, headers, source.canonical({"sha": source.HEAD, "wrong": True})
        if kind == "changed_graph" and url == source.COMPARE_URL:
            return 200, {}, source.canonical({"merge_base_commit": {"sha": source.HEAD},
                                               "ahead_by": 11, "behind_by": 0,
                                               "status": "ahead"})
        if kind == "unexpected_status" and url == source.COMMIT_URL and etag is None:
            return 302, {}, b""
        return status, headers, body
    dag = online.graph_template()
    with pytest.raises(online.OnlineDAGRefused):
        for _ in online.ORDER:
            online.run_one(dag, wrong)


def test_dag_node_cannot_be_completed_out_of_dependency_order():
    dag = online.graph_template()
    with pytest.raises(ValueError):
        dag.commit("compose", {"result": True})
    assert [n.node_id for n in dag.ready_nodes()] == ["git-commit"]


def test_publish_uses_sha_fenced_github_object(monkeypatch):
    state = advance()[-1]
    operations = []
    def server(method, url, token=None, *, data=None, etag=None):
        operations.append((method, url, json.loads(data)))
        return 200, {}, source.canonical({"content": {"sha": "a" * 40}})
    monkeypatch.setattr(source, "request", server)
    assert online.publish("token", state, "b" * 40) == "a" * 40
    assert operations[0][0] == "PUT"
    assert operations[0][2]["sha"] == "b" * 40
    assert operations[0][2]["branch"] == source.STATE_BRANCH
    assert json.loads(base64.b64decode(operations[0][2]["content"])) == state


def test_missing_state_branch_refuses_untrusted_reinitialization(monkeypatch):
    monkeypatch.setattr(source, "request", lambda *_a, **_kw: (404, {}, b""))
    with pytest.raises(online.OnlineDAGRefused, match="state branch missing"):
        online.read_state("token")


def test_empty_state_file_on_existing_branch_bootstraps(monkeypatch):
    ref = source.canonical({"ref": "refs/heads/" + source.STATE_BRANCH,
                            "object": {"sha": "f" * 40}})
    def server(method, url, *_a, **_kw):
        if "/git/ref/heads/" in url:
            return 200, {}, ref
        return 404, {}, b""
    monkeypatch.setattr(source, "request", server)
    assert online.read_state("token") == (None, None)


def test_remote_checkpoint_read_reconstructs_verified_dag(monkeypatch):
    state = advance()[1]
    data = source.canonical({"encoding": "base64", "sha": "a" * 40,
                             "content": base64.b64encode(source.canonical(state)).decode()})
    ref = source.canonical({"ref": "refs/heads/" + source.STATE_BRANCH,
                            "object": {"sha": "f" * 40}})
    def server(method, url, *_a, **_kw):
        return (200, {}, ref) if "/git/ref/heads/" in url else (200, {}, data)
    monkeypatch.setattr(source, "request", server)
    assert online.read_state("token") == (state, "a" * 40)


def test_terminal_workspace_does_not_repeat_accepted_effects():
    dag = NavigableComputationDAG.from_snapshot(advance()[-1]["dag"])
    def unexpected(*_a):
        raise AssertionError("completed execution must not issue network requests")
    assert online.run_one(dag, unexpected) is None
