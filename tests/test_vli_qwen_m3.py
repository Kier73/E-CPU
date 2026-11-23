"""SOI-011: original Qwen 8-layer numerical state under E-CPU M1 and M3 CAS.

All numerical work uses the pinned original VL-I/Qwen eight-layer *small F32*
source fixture, not Qwen3.8-27B pretrained weights. Test processes genuinely
perform original full GDN/GQA layer transitions with existing E-CPU M1 bytes.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Event, Thread

import pytest

from mailcpu.computational_objects import ComputationalObjectStore
from mailcpu.computational_session import (
    ComputationalSessionStore, ComputationalSessionConflictError,
)
from mailcpu.computational_transition import (
    ComputationalSessionTransitionAdapter, ComputationalTransitionError,
)
from mailcpu.recovery_lineage import RecoveryLineageAuthority, RecoveryLineageCoordinator
from mailcpu.seed_commit_quorum import SeedCommitMembership
from mailcpu.stream_os_session import restore_headless_state, OS_STATE_SCHEMA
from mailcpu.vli_temporal_session import bootstrap_vli_temporal_state, read_vli_temporal_checkpoint
from mailcpu.vli_qwen_pages import DurableModelPageBacking, m1_qwen_causal_pages
from mailcpu.vli_qwen_m3 import (
    PATH, RESULT_ROOT, QwenCausalM3Backend,
    admit_original_qwen_runtime_source, bootstrap_qwen_causal_m3,
    encode_qwen_causal_input, qwen_backend_fingerprint,
    qwen_m3_contract, qwen_source_description,
)

upstream = pytest.importorskip("test_qwen_architecture_navigator")
pytest.importorskip("numpy")

GENESIS = hashlib.sha256(b"mailcpu-recovery-lineage-genesis-v1").hexdigest()
SAMPLES = ((63204, [.5, -.2, .3]), (628, [-.1, .2, .8]), (123, [.7, .6, -.3]))


def _source():
    """Admit both exact original VL-I and VL-64 model-fabric module trees."""
    vli, fabric = admit_original_qwen_runtime_source()
    profile = qwen_source_description(upstream.auto_eight)
    fingerprint = qwen_backend_fingerprint(profile, vli, fabric)
    return vli, fabric, profile, fingerprint


def _objects(root: Path):
    """Reopen real durable E-CPU M1, separately from the disposable model worker."""
    return ComputationalObjectStore(
        DurableModelPageBacking(root / "m1"), chunk_size=4096,
    )


def _store(root: Path, source):
    """Create original majority-recovery A/B/C journals over source-bound M3."""
    vli, fabric, profile, fingerprint = source
    membership = SeedCommitMembership(
        "original-qwen-eight-layer-M3", 1, ("A", "B", "C"), "A", 1, GENESIS,
    )
    authorities = {
        member: RecoveryLineageAuthority(
            membership, member, root / "authorities" / f"{member}.jsonl",
        )
        for member in membership.member_ids
    }
    return ComputationalSessionStore(
        root / "sessions", _objects(root),
        RecoveryLineageCoordinator(membership, authorities),
        artifact_manifest_digest=vli.manifest_digest,
        backend_fingerprint=fingerprint,
        state_schema_id=OS_STATE_SCHEMA,
        state_media_type="application/json",
    )


def _state(os_bytes: bytes):
    """Read accepted original Qwen causal pointer without trusting worker memory."""
    machine = restore_headless_state(os_bytes)
    return json.loads(machine.environment.kernel.fs.read_file(PATH))


def _result(os_bytes: bytes, sequence: int, operation_id: str):
    """Read an original numerical Qwen receipt from accepted native OS state."""
    machine = restore_headless_state(os_bytes)
    return json.loads(machine.environment.kernel.fs.read_file(
        f"{RESULT_ROOT}/{sequence:08d}_{operation_id}.json",
    ))


CHILD = r"""
import json,sys,os,time
from pathlib import Path
from mailcpu.computational_objects import ComputationalObjectStore
from mailcpu.vli_qwen_pages import DurableModelPageBacking
from mailcpu.vli_qwen_m3 import (
    evaluate_original_qwen_step,admit_original_qwen_runtime_source,
    qwen_source_description,
)
from test_qwen_architecture_navigator import auto_eight
payload=json.loads(sys.stdin.buffer.read())
vli, fabric=admit_original_qwen_runtime_source()
if (vli.manifest_digest!=payload["vli_manifest_digest"]
    or fabric.manifest_digest!=payload["fabric_manifest_digest"]
    or qwen_source_description(auto_eight)!=payload["source"]):
    raise ValueError("source model fingerprint changed on remote worker")
store=ComputationalObjectStore(
    DurableModelPageBacking(Path(payload["m1_root"])),chunk_size=4096)
candidate=evaluate_original_qwen_step(
    payload["state"],payload["command"],
    model_factory=auto_eight,object_store=store,
    source=payload["source"],
    model_fabric_digest=fabric.manifest_digest,
)
result={"context_binding_digest":payload["context_binding_digest"],
        "host_id":payload["active_host"],"candidate":candidate}
if payload["crash_cut"]=="before_publish":
    os._exit(73)
print(json.dumps(result,sort_keys=True,separators=(",",":"),allow_nan=False),flush=True)
if payload["crash_cut"]=="after_publish":
    while True:time.sleep(1)
"""


def _remote(root: Path, worker_pids: list[int], *, crash_cut: str | None = None):
    """Original Qwen process given only an exact M3 context and original source pin."""
    def run(message: dict, context):
        """Compute and advertise immutable causal pages, not an accepted M3 state."""
        request = {
            **message,
            "m1_root": str(root / "m1"),
            "crash_cut": crash_cut,
        }
        worker = subprocess.Popen(
            [sys.executable, "-u", "-c", CHILD],
            cwd=Path(__file__).resolve().parents[1],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        worker_pids.append(worker.pid)
        data = json.dumps(request, sort_keys=True, separators=(",", ":")).encode()
        if crash_cut == "after_publish":
            assert worker.stdin is not None and worker.stdout is not None
            try:
                worker.stdin.write(data)
                worker.stdin.close()
                line = worker.stdout.readline()
                assert line, "original Qwen worker did not publish"
                assert worker.poll() is None, "original Qwen worker ended before hard kill"
                worker.kill()
                worker.wait(timeout=25)
                return json.loads(line)
            finally:
                if worker.poll() is None:
                    worker.kill()
                    worker.wait(timeout=25)
                for stream in (worker.stdin, worker.stdout, worker.stderr):
                    if stream is not None:
                        stream.close()
        output, error = worker.communicate(data, timeout=90)
        if worker.returncode != 0:
            raise RuntimeError(error.decode(errors="replace")[-2000:])
        return json.loads(output)
    return run


def _adapter(root: Path, source, host: str, remote):
    """Construct an independent controller against the original M3 high-water."""
    vli, fabric, profile, fp = source
    backend = QwenCausalM3Backend(
        _objects(root), upstream.auto_eight, vli, fabric, remote,
        active_host=host,
        allowed_remote_hosts=frozenset({"host-a", "host-b"}),
    )
    return backend, ComputationalSessionTransitionAdapter(
        _store(root, source), qwen_m3_contract(fp), backend,
    )


def _initial(source):
    """One native OS contains both original VL-I living Ground and Qwen causal state."""
    vli, fabric, profile, fp = source
    temporal = bootstrap_vli_temporal_state(
        "environment:original-qwen-numerical-compute", observer="living-model-observer",
    )
    return bootstrap_qwen_causal_m3(
        upstream.auto_eight, vli, fabric, original_os_state=temporal,
    )


def test_real_eight_layer_qwen_m3_session_recovers_three_positions_on_new_processes(tmp_path: Path) -> None:
    """True GDN/GQA state, full native OS, temporal Ground and M3 high-water continue."""
    source = _source()
    root = tmp_path / "qwen"
    current = _store(root, source).create_session(_initial(source))
    unmodified_temporal = read_vli_temporal_checkpoint(current.state_bytes)
    uninterrupted = upstream.auto_eight()
    pids = []
    heads = []
    for idx, (token_id, hidden) in enumerate(SAMPLES, 1):
        host = "host-a" if idx % 2 else "host-b"
        backend, adapter = _adapter(root, source, host, _remote(root, pids))
        accepted = adapter.apply(
            encode_qwen_causal_input(hidden, token_id),
            operation_id=f"qwen-position-{idx}",
            expected_revision=current.revision,
            expected_checkpoint_digest=current.checkpoint_digest,
        )
        expected_output, expected_receipt = uninterrupted.step(hidden, token_id=token_id)
        result = _result(accepted.state_bytes, idx, f"qwen-position-{idx}")
        assert result["output"] == expected_output
        # Range acquisition is host-dependent after a reconstructed worker:
        # semantic F64/state witnesses and the causal chain are the authority.
        assert result["receipt"]["chain_head"] == expected_receipt["chain_head"]
        assert result["receipt"]["position"] == expected_receipt["position"]
        assert result["receipt"]["plan_digest"] == expected_receipt["plan_digest"]
        def semantic_witnesses(receipt):
            return [
                {k: v for k, v in row.items()
                 if k not in ("range_chain", "qualified_ranges", "trained_weight_bytes")}
                for row in receipt["layer_witnesses"]
            ]
        assert semantic_witnesses(result["receipt"]) == semantic_witnesses(expected_receipt)
        assert result["position"] == idx
        assert result["receipt"]["complete_prefix_layers"] == 8
        assert [e["kind"] for e in result["receipt"]["layer_witnesses"]] == (
            ["GDN", "GDN", "GDN", "GATED_GQA"] * 2
        )
        assert result["receipt"]["complete_decoder"] is False
        state = _state(accepted.state_bytes)
        assert state["position"] == idx
        assert state["causal_head"] == uninterrupted.head
        assert len(state["checkpoint"]["layer_checkpoints"]) == 8
        assert read_vli_temporal_checkpoint(accepted.state_bytes) == unmodified_temporal
        assert restore_headless_state(accepted.state_bytes).environment.kernel.journal.verify()
        heads.append(state["causal_head"])
        assert accepted.revision == current.revision + 1
        assert backend.remote_calls == 1
        current = accepted

    assert len(set(pids)) == len(pids) == 3
    assert len(set(heads)) == 3
    current_high_water = _store(root, source).load_latest()
    assert current_high_water.checkpoint_digest == current.checkpoint_digest
    assert current_high_water.state_bytes == current.state_bytes

    def cannot_execute(*args):
        """An exact committed retry never computes a new model token."""
        raise AssertionError("accepted Qwen token operation reentered a worker")

    replay_backend, replay_adapter = _adapter(root, source, "host-a", cannot_execute)
    duplicate = replay_adapter.apply(
        encode_qwen_causal_input(SAMPLES[-1][1], SAMPLES[-1][0]),
        operation_id="qwen-position-3",
    )
    assert duplicate.replayed
    assert duplicate.checkpoint_digest == current.checkpoint_digest
    assert replay_backend.remote_calls == 0


def test_original_qwen_m3_rejects_remote_forged_numerical_output(tmp_path: Path) -> None:
    """Independent source-executed eight-layer step refuses rehashed wrong output."""
    source = _source()
    root = tmp_path / "qwen-forged"
    start = _store(root, source).create_session(_initial(source))
    pids = []

    def forged(message, context):
        """Recompute candidate then change its advertised numeric value."""
        output = _remote(root, pids)(message, context)
        output["candidate"]["output"][0] += 0.25
        return output

    backend, adapter = _adapter(root, source, "host-a", forged)
    with pytest.raises(ComputationalTransitionError, match="independent full-layer execution"):
        adapter.apply(
            encode_qwen_causal_input(SAMPLES[0][1], SAMPLES[0][0]),
            operation_id="forged-eight-layers",
        )
    assert backend.remote_calls == 1
    assert _store(root, source).load_latest().checkpoint_digest == start.checkpoint_digest


def test_original_qwen_m3_competing_old_worker_cannot_publish_stale_state(tmp_path: Path) -> None:
    """A real old eight-layer result cannot overwrite another already committed head."""
    source = _source()
    root = tmp_path / "qwen-race"
    start = _store(root, source).create_session(_initial(source))
    staged, release = Event(), Event()
    outcomes: list[object] = []
    pids = []

    def delayed_old(message, context):
        """An obsolete host computes original Qwen but cannot publish promptly."""
        value = _remote(root, pids)(message, context)
        staged.set()
        assert release.wait(timeout=45)
        return value

    old, old_adapter = _adapter(root, source, "host-a", delayed_old)
    new, new_adapter = _adapter(root, source, "host-b", _remote(root, pids))
    def old_publish():
        """Make original Qwen predecessor CAS after winner changed source head."""
        try:
            outcomes.append(old_adapter.apply(
                encode_qwen_causal_input(SAMPLES[0][1], SAMPLES[0][0]),
                operation_id="old-qwen",
                expected_revision=start.revision,
                expected_checkpoint_digest=start.checkpoint_digest,
            ))
        except Exception as exc:
            outcomes.append(exc)

    thread = Thread(target=old_publish, daemon=True)
    thread.start()
    try:
        assert staged.wait(timeout=45)
        accepted = new_adapter.apply(
            encode_qwen_causal_input(SAMPLES[1][1], SAMPLES[1][0]),
            operation_id="winning-qwen",
            expected_revision=start.revision,
            expected_checkpoint_digest=start.checkpoint_digest,
        )
    finally:
        release.set()
        thread.join(timeout=45)
    assert not thread.is_alive()
    assert len(outcomes) == 1
    assert isinstance(outcomes[0], ComputationalSessionConflictError)
    assert old.remote_calls == new.remote_calls == 1
    assert len(set(pids)) == 2
    latest = _store(root, source).load_latest()
    assert latest.checkpoint_digest == accepted.checkpoint_digest
    assert _result(latest.state_bytes, 1, "winning-qwen")["position"] == 1


def test_original_qwen_killed_before_and_after_publication_retains_only_m3_commit(tmp_path: Path) -> None:
    """Hard-kill original eight-layer Qwen executor; do not accept a private token state."""
    source = _source()
    root = tmp_path / "qwen-kills"
    original = _store(root, source).create_session(_initial(source))
    workers = []
    killed, old_adapter = _adapter(
        root, source, "host-a", _remote(root, workers, crash_cut="before_publish"),
    )
    with pytest.raises(ComputationalTransitionError, match="backend failed"):
        old_adapter.apply(
            encode_qwen_causal_input(SAMPLES[0][1], SAMPLES[0][0]),
            operation_id="killed-before-qwen",
        )
    assert _store(root, source).load_latest().checkpoint_digest == original.checkpoint_digest
    succeeded, fresh_adapter = _adapter(
        root, source, "host-b", _remote(root, workers, crash_cut="after_publish"),
    )
    accepted = fresh_adapter.apply(
        encode_qwen_causal_input(SAMPLES[0][1], SAMPLES[0][0]),
        operation_id="killed-after-qwen",
        expected_revision=original.revision,
        expected_checkpoint_digest=original.checkpoint_digest,
    )
    assert accepted.revision == 2
    assert succeeded.remote_calls == killed.remote_calls == 1
    assert len(set(workers)) == len(workers) == 2
    assert _state(accepted.state_bytes)["position"] == 1
    assert _store(root, source).load_latest().checkpoint_digest == accepted.checkpoint_digest


def test_qwen_m3_refuses_tampered_immutable_causal_page_before_remote(tmp_path: Path) -> None:
    """Corrupt disk M1 bytes; no worker can execute from an unqualified causal state."""
    source = _source()
    root = tmp_path / "qwen-corrupt"
    state = _store(root, source).create_session(_initial(source))
    backend, adapter = _adapter(root, source, "host-a", _remote(root, []))
    committed = adapter.apply(
        encode_qwen_causal_input(SAMPLES[0][1], SAMPLES[0][0]),
        operation_id="first-before-corruption",
    )
    original = _state(committed.state_bytes)
    first = next(iter(original["bundle"]["pages"].values()))
    digest = first["chunks"][0]["page_digest"]
    (root / "m1" / digest).write_bytes(b"forged")
    no_work, new_adapter = _adapter(
        root, source, "host-b",
        lambda *_args: (_ for _ in ()).throw(AssertionError("corrupt M1 state reached worker")),
    )
    with pytest.raises((ComputationalTransitionError, ValueError), match="reconstruct|corrupt"):
        new_adapter.apply(
            encode_qwen_causal_input(SAMPLES[1][1], SAMPLES[1][0]),
            operation_id="bad-pages-qwen",
        )
    assert no_work.remote_calls == 0
