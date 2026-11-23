"""SOI-009: original VL-I complete finite neural model over real E-CPU M2/M3.

Uses the actual VL-I COORD-002 descriptive neural model fixture, the actual
VLD neural parameter compiler, actual source-checked neural forward steps,
and actual VLD response DAG. Native HeadlessOS + M1/M3 preserves generated
weights identity and conversation state across disposable Python processes.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
from threading import Event, Thread

import pytest

from mailcpu import HeadlessOS
from mailcpu.computational_host import (
    ComputationalBackendError, ComputationalHostReceipt,
    ComputationalHostRequest, LocalComputationalHost,
)
from mailcpu.computational_objects import ComputationalObjectStore
from mailcpu.computational_session import (
    ComputationalSessionConflictError, ComputationalSessionStore,
)
from mailcpu.computational_transition import (
    ComputationalSessionTransitionAdapter, ComputationalTransitionError,
)
from mailcpu.recovery_lineage import RecoveryLineageAuthority, RecoveryLineageCoordinator
from mailcpu.seed_commit_quorum import SeedCommitMembership
from mailcpu.stream_os_session import restore_headless_state, serialize_headless_state, OS_STATE_SCHEMA
from mailcpu.vli_neural_model import (
    VLIGenerativeModelAdapter, MODEL_HOST_SCHEMA, admit_vli_neural_runtime,
    vli_neural_profile,
)
from mailcpu.vli_neural_session import (
    MODEL_SOURCE_PATH, MODEL_CHECKPOINT_PATH, VLINeuralModelSessionBackend,
    bootstrap_vli_neural_model, encode_vli_model_turn, read_vli_model_checkpoint,
    vli_model_session_fingerprint, vli_model_session_contract,
)
from mailcpu.vli_temporal_session import read_vli_temporal_checkpoint
from mailcpu.model import Instruction, Op, Program

vli = pytest.importorskip("vli")
pytest.importorskip("vld.models.procedural")
from vli.generative_response import (
    GeneratedModelGround, GenerativeConversation,
)

MODEL_FILE = Path(__file__).resolve().parent / "fixtures/vli_original_described_neural_model.json"
GENESIS = hashlib.sha256(b"mailcpu-recovery-lineage-genesis-v1").hexdigest()
VIEWS = ("text", "code", "tokens", "tool_call")


class PageBacking:
    """One controller-held M1 immutable source page store across worker-process deaths."""

    page_size = 4096

    def __init__(self) -> None:
        """Create the test process-owned exact page map."""
        self.pages: dict[str, bytes] = {}

    def put_page(self, data: bytes) -> str:
        """Admit exactly one full content-addressed M1 page."""
        if not isinstance(data, bytes) or len(data) != 4096:
            raise ValueError("invalid immutable M1 page")
        digest = hashlib.sha256(data).hexdigest()
        if self.pages.setdefault(digest, data) != data:
            raise ValueError("M1 source collision")
        return digest

    def get_page(self, digest: str) -> bytes:
        """Retrieve the exact previously admitted page by SHA-256."""
        return self.pages[digest]


def _reference():
    """Bind both actual original runtime trees to their immutable source manifests."""
    manifest, vld_dependency, root = admit_vli_neural_runtime()
    profile = vli_neural_profile(manifest, vld_dependency)
    return LocalComputationalHost(
        host_id="vli-neural-reference", manifest=manifest,
        artifact_root=root, profile=profile,
        adapter=VLIGenerativeModelAdapter(vld_dependency),
    )


def _store(tmp: Path, backing: PageBacking, reference):
    """Use E-CPU's actual M1 page objects and 3 separately fsynced quorum journals."""
    membership = SeedCommitMembership(
        "original-vli-neural-m3-session", 1, ("A", "B", "C"), "A", 1, GENESIS,
    )
    authorities = {
        peer: RecoveryLineageAuthority(
            membership, peer, tmp / "authorities" / f"{peer}.jsonl",
        ) for peer in membership.member_ids
    }
    lineage = RecoveryLineageCoordinator(membership, authorities)
    return ComputationalSessionStore(
        tmp / "sessions",
        ComputationalObjectStore(backing, chunk_size=4096),
        lineage,
        artifact_manifest_digest=reference.manifest.manifest_digest,
        backend_fingerprint=vli_model_session_fingerprint(reference),
        state_schema_id=OS_STATE_SCHEMA,
        state_media_type="application/json",
    )


def _initial():
    """Boot actual native E-CPU guest work plus original VL-I temporal and neural states."""
    state = bootstrap_vli_neural_model(
        MODEL_FILE.read_bytes(), observer="ecpu-vli-continued-neural",
        include_living_ground=True,
    )
    os_state = restore_headless_state(state)
    pid = os_state.spawn(
        Program((
            Instruction(Op.SET, ("ready", 10)),
            Instruction(Op.SET, ("offset", -2)),
            Instruction(Op.ADD, ("ready", "ready", "offset")),
            Instruction(Op.HALT),
        )),
        "neural-vli-os-supervisor",
    )
    os_state.run(max_ticks=1)
    assert os_state.process(pid).registers["ready"] == 10
    return serialize_headless_state(os_state)


def _remote(host_name: str, reference, worker_pids, *, cut=None):
    """Execute original VLD/VL-I full neural code in a fresh Python interpreter."""
    def runner(operation, operation_id, arguments, context):
        """Bind exact worker/source/context identity before one native neural turn."""
        request = {
            "schema": "mailcpu.vli-neural-model-one-shot.v1",
            "host_id": host_name,
            "context_binding_digest": context.binding_digest,
            "artifact_manifest_digest": reference.manifest.manifest_digest,
            "vld_manifest_digest": reference.profile.configuration["vld_source_digest"],
            "backend_fingerprint": reference.profile.fingerprint,
            "operation_id": operation_id,
            "session_id": context.session_id,
            "logical_time": context.logical_time,
            "operation": operation,
            "arguments": arguments,
        }
        command = [sys.executable, "-m", "mailcpu.vli_neural_worker"]
        if cut is not None:
            command.extend(("--crash-cut", cut))
        child = subprocess.Popen(
            command, cwd=Path(__file__).resolve().parents[1],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        worker_pids.append(child.pid)
        payload = json.dumps(request, sort_keys=True, separators=(",", ":")).encode("utf-8")
        if cut == "after_publish":
            assert child.stdin is not None and child.stdout is not None
            try:
                child.stdin.write(payload)
                child.stdin.close()
                line = child.stdout.readline()
                assert line, "actual neural model did not publish before crash"
                assert child.poll() is None
                child.kill()
                child.wait(timeout=25)
            finally:
                if child.poll() is None:
                    child.kill()
                    child.wait(timeout=25)
                for stream in (child.stdin, child.stdout, child.stderr):
                    if stream is not None:
                        stream.close()
            return json.loads(line)
        response, error = child.communicate(payload, timeout=120)
        if child.returncode != 0:
            raise RuntimeError(error.decode("utf-8", errors="replace")[-2500:])
        return json.loads(response)
    return runner


def _adapter(store, reference, host: str, remote):
    """Join one source-verified original neural host to E-CPU M3 CAS."""
    backend = VLINeuralModelSessionBackend(
        reference, remote, active_host=host,
        allowed_remote_hosts=frozenset(("host-a", "host-b")),
    )
    return backend, ComputationalSessionTransitionAdapter(
        store, vli_model_session_contract(reference), backend,
    )


def _result(os_bytes: bytes, logical_time: int, operation: str):
    """Extract only the semantics of a completed M3-committed neural turn."""
    os_state = restore_headless_state(os_bytes)
    return json.loads(os_state.environment.kernel.fs.read_file(
        f"/vli/neural/results/{logical_time:08d}_{operation}.json",
    ))


def test_original_vli_source_and_vld_neural_compiler_execute_full_model() -> None:
    """Real VLD neural weights, whole 3x3 domain oracle and a rendered VL-I turn."""
    reference = _reference()
    dep = reference.profile.configuration["vld_source_digest"]
    assert len(reference.manifest.components) >= 60
    assert reference.manifest.total_size_bytes > 900_000
    assert reference.manifest.total_size_bytes < 2_097_152
    assert len(dep) == 64 and dep != reference.manifest.manifest_digest
    description = MODEL_FILE.read_bytes()
    ground = GeneratedModelGround(description)
    assert ground.verify()
    assert len(ground.neural.hidden_weight) == 9
    assert len(ground.neural.next_state_weight) == 3
    assert len(ground.neural.channel_weight) == 2
    for source_state in ground.system.states:
        for action in ground.system.actions:
            assert ground.generated(source_state, action) == ground.reference(source_state, action)

    genesis = GenerativeConversation(ground, observer="native-neural-host").checkpoint()
    payload = {
        "description_hex": description.hex(),
        "checkpoint": genesis,
        "prompt": "Advance the model and produce code",
        "action": "advance",
        "views": list(VIEWS),
    }
    request = ComputationalHostRequest(
        request_id="first-original-neural",
        artifact_manifest_digest=reference.manifest.manifest_digest,
        operation="model.respond", input_value=payload,
        logical_time=1, workload_id="native-vli-model",
    )
    result = reference.execute(request)
    assert result.receipt.status == "EXECUTED"
    assert result.receipt.artifact_manifest_digest == reference.manifest.manifest_digest
    assert result.receipt.backend_fingerprint == reference.profile.fingerprint
    out = result.output
    assert out["schema"] == MODEL_HOST_SCHEMA
    assert out["vld_runtime_manifest_digest"] == dep
    assert out["generated_weights_digest"] == ground.weights_digest
    assert out["checkpoint"]["state"] == "formed"
    assert out["output"]["turn"]["neural_forward_steps"] == 1
    assert out["output"]["response"]["phase"] == "RENDERED"
    assert out["output"]["response"]["step_receipt"]["neural_step_executed"]
    rendered = out["output"]["response"]["projections"]
    assert set(x["kind"] for x in rendered) == set(VIEWS)
    assert next(x["status"] for x in rendered if x["kind"] == "tool_call") == "INERT_PROPOSAL"
    assert any("def transition" in x["content"] for x in rendered if x["kind"] == "code")
    assert GenerativeConversation.restore(
        ground, out["checkpoint"],
        expected_head=out["checkpoint"]["checkpoint_digest"],
    ).state == "formed"
    with pytest.raises(ComputationalBackendError, match="unadmitted"):
        reference.execute(ComputationalHostRequest(
            request_id="arbitrary-execution",
            artifact_manifest_digest=reference.manifest.manifest_digest,
            operation="python.eval", input_value={"code": "print(2)"},
            logical_time=2, workload_id="native-vli-model",
        ))


def test_model_neural_forward_maintains_causal_chat_across_four_new_hosts(tmp_path: Path) -> None:
    """One original model and an untouched living VL-I Ground rehost through M3."""
    reference = _reference()
    backing = PageBacking()
    store = _store(tmp_path, backing, reference)
    current = store.create_session(_initial())
    temporal = read_vli_temporal_checkpoint(current.state_bytes)
    pids = []
    accepted_heads = []
    neural_weights = set()
    commands = [
        ("inspect", "Observe the state"),
        ("advance", "Advance the model and produce the next response"),
        ("reset", "Reset to the initial state"),
        ("advance", "Continue from the restored state"),
    ]
    source = MODEL_FILE.read_bytes()
    independent = GenerativeConversation(
        GeneratedModelGround(source), observer="ecpu-vli-continued-neural",
    )
    for index, (action, prompt) in enumerate(commands):
        host_name = "host-a" if index % 2 == 0 else "host-b"
        store = _store(tmp_path, backing, reference)
        backend, adapter = _adapter(
            store, reference, host_name, _remote(host_name, reference, pids),
        )
        prior = current
        updated = adapter.apply(
            encode_vli_model_turn(prompt, action, views=VIEWS),
            operation_id=f"neural-turn-{index}",
            expected_revision=prior.revision,
            expected_checkpoint_digest=prior.checkpoint_digest,
        )
        assert updated.revision == prior.revision + 1
        assert backend.remote_calls == 1
        expected = independent.respond(prompt, action, views=VIEWS)
        raw, checkpoint = read_vli_model_checkpoint(updated.state_bytes)
        assert raw == source
        assert checkpoint == independent.checkpoint()
        semantic = _result(updated.state_bytes, index + 1, f"neural-turn-{index}")
        assert semantic["turn"] == expected["turn"]
        assert semantic["response"] == expected["response"]
        assert semantic["turn"]["previous"] == read_vli_model_checkpoint(
            prior.state_bytes
        )[1]["head"]
        assert semantic["turn"]["neural_forward_steps"] == 1
        assert semantic["response"]["phase"] == "RENDERED"
        assert semantic["response"]["step_receipt"]["neural_step_executed"]
        assert len(semantic["response"]["projections"]) == len(VIEWS)
        assert _result(updated.state_bytes, 1, "neural-turn-0")["turn"]["sequence"] == 0
        assert read_vli_temporal_checkpoint(updated.state_bytes) == temporal
        assert restore_headless_state(updated.state_bytes).environment.kernel.journal.verify()
        accepted_heads.append(checkpoint["head"])
        neural_weights.add(semantic["generated_weights_digest"])
        current = updated
    assert len(set(pids)) == len(pids) == 4
    assert len(set(accepted_heads)) == 4
    assert len(neural_weights) == 1
    assert current.revision == 5
    final = _store(tmp_path, backing, reference).load_latest()
    assert final.checkpoint_digest == current.checkpoint_digest
    assert final.state_bytes == current.state_bytes
    assert read_vli_model_checkpoint(final.state_bytes)[1]["state"] == "formed"
    assert [event["sequence"] for event in independent.events] == [0, 1, 2, 3]

    def forbidden(*_args):
        """Exactly committed neural forward must not reenter any worker."""
        raise AssertionError("neural step replayed after M3 commit")

    replay_backend, replay_adapter = _adapter(
        _store(tmp_path, backing, reference), reference, "host-b", forbidden,
    )
    duplicate = replay_adapter.apply(
        encode_vli_model_turn(commands[-1][1], commands[-1][0], views=VIEWS),
        operation_id="neural-turn-3",
    )
    assert duplicate.replayed and duplicate.checkpoint_digest == current.checkpoint_digest
    assert replay_backend.remote_calls == 0


def test_original_neural_model_source_change_invalidates_checkpoint_before_remote(tmp_path: Path) -> None:
    """Changed description/Ground prevents a stale neural conversation from loading."""
    reference = _reference()
    backing = PageBacking()
    state = restore_headless_state(_initial())
    source = MODEL_FILE.read_bytes().decode()
    state.install_source(MODEL_SOURCE_PATH, source.replace("idle", "missing-model-state"))
    store = _store(tmp_path, backing, reference)
    before = store.create_session(serialize_headless_state(state))
    backend, adapter = _adapter(
        store, reference, "host-a",
        lambda *_args: (_ for _ in ()).throw(AssertionError("tampered source reached neural worker")),
    )
    with pytest.raises(ComputationalTransitionError, match="cannot be reconstructed"):
        adapter.apply(
            encode_vli_model_turn("Advance", "advance"),
            operation_id="changed-model",
        )
    assert backend.remote_calls == 0
    assert store.load_latest().checkpoint_digest == before.checkpoint_digest


def test_forged_original_neural_model_result_refused_even_with_valid_recomputed_receipt(tmp_path: Path) -> None:
    """A well-formed but changed generated forward output cannot publish to M3."""
    reference = _reference()
    backing = PageBacking()
    store = _store(tmp_path, backing, reference)
    before = store.create_session(_initial())
    pids = []

    def forged(operation, operation_id, input_value, context):
        """Forge the output and replace its M2 hash while retaining wrong math."""
        response = _remote("host-a", reference, pids)(operation, operation_id, input_value, context)
        response["output"]["output"]["response"]["step_receipt"]["target_state"] = "fake-target"
        prior = ComputationalHostReceipt.from_dict(response["receipt"])
        data = json.dumps(response["output"], sort_keys=True,
                          separators=(",", ":"), ensure_ascii=False).encode()
        response["receipt"] = ComputationalHostReceipt.create(
            host_id=prior.host_id, artifact_manifest_digest=prior.artifact_manifest_digest,
            backend_fingerprint=prior.backend_fingerprint,
            request_id=prior.request_id, workload_id=prior.workload_id,
            logical_time=prior.logical_time, input_digest=prior.input_digest,
            output_digest=hashlib.sha256(data).hexdigest(),
            output_size_bytes=len(data),
        ).to_dict()
        return response

    backend, adapter = _adapter(store, reference, "host-a", forged)
    with pytest.raises(ComputationalTransitionError, match="independently executed model"):
        adapter.apply(
            encode_vli_model_turn("Advance the model", "advance", views=VIEWS),
            operation_id="forged-neural",
        )
    assert backend.remote_calls == 1
    assert store.load_latest().checkpoint_digest == before.checkpoint_digest


def test_valid_old_neural_host_loses_m3_publication_race(tmp_path: Path) -> None:
    """A perfectly correct old neural forward may not overwrite current session."""
    reference = _reference()
    backing = PageBacking()
    store = _store(tmp_path, backing, reference)
    initial = store.create_session(_initial())
    arrived, continue_old = Event(), Event()
    outputs = []
    pids = []

    def delayed(operation, operation_id, input_value, context):
        """Complete real neural work but hold state publication behind a competing CAS."""
        result = _remote("host-a", reference, pids)(operation, operation_id, input_value, context)
        arrived.set()
        assert continue_old.wait(timeout=90)
        return result

    old, old_adapter = _adapter(store, reference, "host-a", delayed)
    new, new_adapter = _adapter(store, reference, "host-b",
                                _remote("host-b", reference, pids))

    def old_writer():
        """Submit a valid obsolete model result with its original expected checkpoint."""
        try:
            outputs.append(old_adapter.apply(
                encode_vli_model_turn("Inspect from old host", "inspect", views=VIEWS),
                operation_id="obsolete-model",
                expected_revision=initial.revision,
                expected_checkpoint_digest=initial.checkpoint_digest,
            ))
        except Exception as exc:
            outputs.append(exc)

    worker = Thread(target=old_writer, daemon=True)
    worker.start()
    try:
        assert arrived.wait(timeout=90)
        winning = new_adapter.apply(
            encode_vli_model_turn("Advance from current host", "advance", views=VIEWS),
            operation_id="winning-model",
            expected_revision=initial.revision,
            expected_checkpoint_digest=initial.checkpoint_digest,
        )
    finally:
        continue_old.set()
        worker.join(timeout=90)
    assert not worker.is_alive()
    assert len(outputs) == 1
    assert isinstance(outputs[0], ComputationalSessionConflictError)
    assert old.remote_calls == new.remote_calls == 1
    assert len(set(pids)) == len(pids) == 2
    latest = _store(tmp_path, backing, reference).load_latest()
    assert latest.checkpoint_digest == winning.checkpoint_digest
    assert read_vli_model_checkpoint(latest.state_bytes)[1]["events"][0]["prompt"] == "Advance from current host"


def test_hard_killed_neural_worker_before_and_after_publication(tmp_path: Path) -> None:
    """Actual process hard kill cannot invent or duplicate a generated model turn."""
    reference = _reference()
    backing = PageBacking()
    store = _store(tmp_path, backing, reference)
    initial = store.create_session(_initial())
    pids = []
    backend, interrupted = _adapter(
        store, reference, "host-a", _remote("host-a", reference, pids, cut="before_publish"),
    )
    with pytest.raises(ComputationalTransitionError, match="backend failed"):
        interrupted.apply(
            encode_vli_model_turn("Advance", "advance", views=VIEWS),
            operation_id="killed-before",
        )
    assert backend.remote_calls == 1
    assert store.load_latest().checkpoint_digest == initial.checkpoint_digest
    revived, replacement = _adapter(
        _store(tmp_path, backing, reference), reference, "host-b",
        _remote("host-b", reference, pids, cut="after_publish"),
    )
    accepted = replacement.apply(
        encode_vli_model_turn("Advance", "advance", views=VIEWS),
        operation_id="killed-after",
        expected_revision=initial.revision,
        expected_checkpoint_digest=initial.checkpoint_digest,
    )
    assert accepted.revision == 2
    assert revived.remote_calls == 1
    assert len(set(pids)) == len(pids) == 2
    assert read_vli_model_checkpoint(accepted.state_bytes)[1]["state"] == "formed"
    assert _store(tmp_path, backing, reference).load_latest().checkpoint_digest == accepted.checkpoint_digest
