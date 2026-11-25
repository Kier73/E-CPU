"""Independent controls for INTERNET-005 online path and durable checkpoint."""
import base64
import copy
import json
from pathlib import Path
import subprocess
import sys

import pytest

from mailcpu import internet_free_fabric as f


def fake_get(url, validator):
    if url == f.COMMIT_URL:
        if validator is None:
            return (200, {"etag": '"fixed-response-tag"'}, f.canonical({"sha": f.HEAD}))
        if validator == '"fixed-response-tag"':
            return (304, {}, b"")
        return (200, {}, f.canonical({"sha": f.HEAD}))
    if url == f.COMPARE_URL:
        return (200, {}, f.canonical({
            "merge_base_commit": {"sha": f.BASE},
            "ahead_by": 11, "behind_by": 0, "status": "ahead",
        }))
    raise AssertionError("unexpected service endpoint")


def receipt():
    return f.observe_native_paths(fake_get)


def test_real_service_operations_are_modeled_separately():
    found = receipt()
    f.validate_observation(found)
    assert found["service_operations"] == [
        "github.git.commit", "http.if-none-match", "github.git.compare"]
    assert found["source_code_payload_bytes"] == 0
    assert found["claim"].startswith("internet-service-native")


@pytest.mark.parametrize("failure", ["wrong_commit", "wrong_validator", "wrong_content",
                                      "wrong_graph", "wrong_base", "redirect_analogue"])
def test_native_observations_refuse_unwarranted_claims(failure):
    def bad_get(url, validator):
        status, headers, body = fake_get(url, validator)
        if failure == "wrong_commit" and url == f.COMMIT_URL and validator is None:
            return status, headers, f.canonical({"sha": f.BASE})
        if failure == "wrong_validator" and url == f.COMMIT_URL and validator == '"fixed-response-tag"':
            return 200, {}, f.canonical({"sha": f.HEAD})
        if failure == "wrong_content" and url == f.COMMIT_URL and validator is not None and status == 200:
            return status, headers, f.canonical({"sha": f.HEAD, "other": "changed"})
        if failure == "wrong_graph" and url == f.COMPARE_URL:
            return status, headers, f.canonical({"merge_base_commit": {"sha": f.BASE},
                                                  "ahead_by": 12, "behind_by": 0, "status": "ahead"})
        if failure == "wrong_base" and url == f.COMPARE_URL:
            return status, headers, f.canonical({"merge_base_commit": {"sha": f.HEAD},
                                                  "ahead_by": 11, "behind_by": 0, "status": "ahead"})
        if failure == "redirect_analogue" and url == f.COMPARE_URL:
            return 302, {}, b""
        return status, headers, body
    with pytest.raises(f.FreeFabricRefused):
        f.observe_native_paths(bad_get)


def test_checkpoint_chain_across_reconstructed_process(tmp_path):
    first = f.successor(None, receipt())
    assert first["revision"] == 1 and first["previous_digest"] is None
    saved = tmp_path / "checkpoint.json"
    saved.write_bytes(f.canonical(first))
    child = (
        "import json,sys;"
        "from mailcpu.internet_free_fabric import validate_checkpoint, successor;"
        "s=validate_checkpoint(json.loads(open(sys.argv[1]).read()));"
        "next=successor(s,s['observation']);"
        "print(json.dumps({'revision':next['revision'], 'prior':next['previous_digest']}))"
    )
    result = subprocess.check_output([sys.executable, "-c", child, str(saved)],
                                     cwd=Path(__file__).resolve().parents[1], text=True)
    reconstructed = json.loads(result)
    assert reconstructed == {"revision": 2, "prior": first["digest"]}


def test_corrupted_checkpoint_or_observation_refused():
    state = f.successor(None, receipt())
    for change in ("wrong_workspace", "wrong_digest", "receipt_change", "noncanonical_revision"):
        altered = copy.deepcopy(state)
        if change == "wrong_workspace":
            altered["workspace_id"] = "e" * 64
        elif change == "wrong_digest":
            altered["digest"] = "f" * 64
        elif change == "receipt_change":
            altered["observation"]["ahead_by"] = 10
        else:
            altered["revision"] = True
        with pytest.raises(f.FreeFabricRefused):
            f.validate_checkpoint(altered)


def test_original_state_has_no_authority_from_digest():
    state = f.successor(None, receipt())
    assert state["revision"] == 1
    assert "membership_digest" not in state
    assert "signature" not in state


def test_state_publication_uses_original_blob_as_compare_and_swap(monkeypatch):
    previous = f.successor(None, receipt())
    state = f.successor(previous, receipt())
    seen = []
    def service(method, url, token=None, *, data=None, etag=None):
        seen.append((method, url, json.loads(data)))
        return 200, {}, f.canonical({"content": {"sha": "a" * 40}})
    monkeypatch.setattr(f, "request", service)
    sha = f.publish_remote_state("token", state, "b" * 40)
    assert sha == "a" * 40
    assert len(seen) == 1
    assert seen[0][2]["sha"] == "b" * 40
    assert seen[0][2]["branch"] == f.STATE_BRANCH
    assert json.loads(base64.b64decode(seen[0][2]["content"])) == state


def test_missing_state_starts_new_lineage_and_existing_is_verified(monkeypatch):
    ref = f.canonical({"ref": "refs/heads/" + f.STATE_BRANCH,
                       "object": {"sha": "d" * 40}})
    def missing_file(method, url, *_args, **_kw):
        return (200, {}, ref) if "/git/ref/heads/" in url else (404, {}, b"")
    monkeypatch.setattr(f, "request", missing_file)
    assert f.read_remote_state("token") == (None, None)
    state = f.successor(None, receipt())
    envelope = {"encoding": "base64", "sha": "c" * 40,
                "content": base64.b64encode(f.canonical(state)).decode()}
    def existing_file(method, url, *_args, **_kw):
        return (200, {}, ref) if "/git/ref/heads/" in url else (200, {}, f.canonical(envelope))
    monkeypatch.setattr(f, "request", existing_file)
    read, sha = f.read_remote_state("token")
    assert sha == "c" * 40 and read == state


def test_duplicate_json_keys_and_nonfinite_values_refused():
    with pytest.raises(f.FreeFabricRefused):
        f.strict_json(b'{"revision":1,"revision":2}')
    with pytest.raises(f.FreeFabricRefused):
        f.strict_json(b'{"revision":NaN}')


def test_no_arbitrary_host_request(monkeypatch):
    with pytest.raises(f.FreeFabricRefused):
        f.request("GET", "https://example.com/cpu")


def test_missing_state_branch_is_refused_not_reinitialized(monkeypatch):
    monkeypatch.setattr(f, "request", lambda *_args, **_kw: (404, {}, b""))
    with pytest.raises(f.FreeFabricRefused, match="state branch is missing"):
        f.read_remote_state("token")
