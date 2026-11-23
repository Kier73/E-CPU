"""SOI-007: actual VL-I TIME-001/002 hosted by original E-CPU M2 and M3."""

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
from mailcpu.model import Instruction, Op, Program
from mailcpu.recovery_lineage import RecoveryLineageAuthority, RecoveryLineageCoordinator
from mailcpu.seed_commit_quorum import SeedCommitMembership
from mailcpu.stream_os_session import OS_STATE_SCHEMA, restore_headless_state, serialize_headless_state
from mailcpu.vli_temporal_host import (
    VLITemporalBackendAdapter, VLI_TEMPORAL_HOST_SCHEMA,
    admit_vli_temporal_runtime, vli_temporal_backend_profile,
    create_vli_temporal_genesis,
)
from mailcpu.vli_temporal_session import (
    VLITemporalSessionBackend, VLI_STATE_PATH, bootstrap_vli_temporal_state,
    encode_vli_temporal_operation, read_vli_temporal_checkpoint,
    vli_temporal_session_backend_fingerprint, vli_temporal_session_contract,
)

vli = pytest.importorskip("vli")
from vli.temporal_intelligence import (
    TemporalIntelligenceGround, verify_temporal_navigation, verify_temporal_snapshot,
)

GENESIS = hashlib.sha256(b"mailcpu-recovery-lineage-genesis-v1").hexdigest()


class PageBacking:
    """Admitted fixed-size immutable E-CPU M1 page storage, outside worker processes."""

    page_size = 4096

    def __init__(self) -> None:
        """Construct a bounded digest-keyed M1 page map."""
        self.pages: dict[str, bytes] = {}

    def put_page(self, data: bytes) -> str:
        """Admit one complete immutable page under SHA-256."""
        if not isinstance(data, bytes) or len(data) != self.page_size:
            raise ValueError("invalid M1 page geometry")
        digest = hashlib.sha256(data).hexdigest()
        if self.pages.setdefault(digest, data) != data:
            raise ValueError("page identity collision")
        return digest

    def get_page(self, digest: str) -> bytes:
        """Resolve exactly the page bound by the snapshot manifest."""
        return self.pages[digest]


def _reference():
    """Admit all original VL-I modules into the real M2 computational host."""
    manifest, root = admit_vli_temporal_runtime()
    profile = vli_temporal_backend_profile(manifest)
    host = LocalComputationalHost(
        host_id="vli-temporal-reference",
        manifest=manifest, artifact_root=root, profile=profile,
        adapter=VLITemporalBackendAdapter(),
    )
    return host


def _store(root: Path, backing: PageBacking, reference: LocalComputationalHost):
    """Reuse real A/B/C local durable quorum lineage and M1/M3 session CAS."""
    membership = SeedCommitMembership(
        "vli-temporal-observer-m3", 1, ("A", "B", "C"), "A", 1, GENESIS,
    )
    authorities = {
        name: RecoveryLineageAuthority(
            membership, name, root / "authorities" / f"{name}.jsonl",
        )
        for name in membership.member_ids
    }
    coordinator = RecoveryLineageCoordinator(membership, authorities)
    return ComputationalSessionStore(
        root / "sessions",
        ComputationalObjectStore(backing, chunk_size=4096),
        coordinator,
        artifact_manifest_digest=reference.manifest.manifest_digest,
        backend_fingerprint=vli_temporal_session_backend_fingerprint(reference),
        state_schema_id=OS_STATE_SCHEMA,
        state_media_type="application/json",
    )


def _initial() -> bytes:
    """Boot actual native E-CPU OS plus the original VL-I continuous Ground."""
    machine = restore_headless_state(bootstrap_vli_temporal_state(
        "environment:time-source-drift", dimensions=1, observer="continuing-vli",
    ))
    pid = machine.spawn(
        Program((
            Instruction(Op.SET, ("counter", 12)),
            Instruction(Op.SET, ("delta", -1)),
            Instruction(Op.ADD, ("counter", "counter", "delta")),
            Instruction(Op.ADD, ("counter", "counter", "delta")),
            Instruction(Op.HALT),
        )),
        "vli-temporal-os-scheduler",
    )
    machine.run(max_ticks=1)
    assert machine.process(pid).registers["counter"] == 12
    return serialize_headless_state(machine)


def _sample(index: int, reading: int) -> dict[str, object]:
    """Represent an explicit synthetic sensor sample, not an actual external measurement."""
    time = f"{index}/1"
    value = f"{reading}/1"
    return {
        "schema": "vl-i.source-sample.v1",
        "sequence": index,
        "time": time,
        "values": [value],
        "source_digest": hashlib.sha256(
            f"laboratory:{index}:{time}:{value}".encode("utf-8")
        ).hexdigest(),
    }


def _remote(
    host_id: str, reference: LocalComputationalHost, process_ids: list[int],
    *, crash_cut: str | None = None,
):
    """Construct an original VL-I process on each M3 operation, with no shared Python heap."""
    def execute(operation, operation_id, arguments, context):
        """Send a completely source-pinned M2 request into one disposable Python process."""
        payload = {
            "schema": "mailcpu.vli-temporal-one-shot.v1",
            "host_id": host_id,
            "context_binding_digest": context.binding_digest,
            "artifact_manifest_digest": reference.manifest.manifest_digest,
            "backend_fingerprint": reference.profile.fingerprint,
            "operation_id": operation_id,
            "session_id": context.session_id,
            "logical_time": context.logical_time,
            "operation": operation,
            "arguments": arguments,
        }
        cmd = [sys.executable, "-m", "mailcpu.vli_temporal_worker"]
        if crash_cut is not None:
            cmd.extend(("--crash-cut", crash_cut))
        worker = subprocess.Popen(
            cmd, cwd=Path(__file__).resolve().parents[1],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        process_ids.append(worker.pid)
        data = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        if crash_cut == "after_publish":
            assert worker.stdin is not None and worker.stdout is not None
            try:
                worker.stdin.write(data)
                worker.stdin.close()
                response = worker.stdout.readline()
                assert response
                assert worker.poll() is None
                worker.kill()
                worker.wait(timeout=15)
            finally:
                if worker.poll() is None:
                    worker.kill()
                    worker.wait(timeout=15)
                for stream in (worker.stdin, worker.stdout, worker.stderr):
                    if stream is not None:
                        stream.close()
            return json.loads(response)
        output, error = worker.communicate(data, timeout=35)
        if worker.returncode != 0:
            raise RuntimeError(error.decode("utf-8", errors="replace")[-2000:])
        return json.loads(output)
    return execute


def _adapter(store, ref, host, remote):
    """Build a new M3 execution authority at a known source-admitted physical host."""
    backend = VLITemporalSessionBackend(
        ref, remote, active_host=host,
        allowed_remote_hosts=frozenset({"host-a", "host-b"}),
    )
    return backend, ComputationalSessionTransitionAdapter(
        store, vli_temporal_session_contract(ref), backend,
    )


def _read_result(os_bytes: bytes, operation_id: str, logical_time: int):
    """Read a semantic decision from accepted native OS virtual filesystem."""
    machine = restore_headless_state(os_bytes)
    return json.loads(machine.environment.kernel.fs.read_file(
        f"/vli/results/{logical_time:08d}_{operation_id}.json"
    ))


def test_real_vli_m2_runs_living_observation_and_source_derived_intention() -> None:
    """Original VL-I 0.1 source and true TIME-002 sink, not an E-CPU approximation."""
    reference = _reference()
    manifest = reference.manifest
    assert len(manifest.components) >= 50
    assert manifest.total_size_bytes > 100_000
    assert manifest.total_size_bytes < 2_097_152
    assert manifest.metadata["version"] == vli.__version__
    assert all(component.path.endswith(".py") for component in manifest.components)
    snapshot = create_vli_temporal_genesis("environment:time-source-drift", observer="continuing-vli")
    assert verify_temporal_snapshot(
        snapshot, expected_head=snapshot["head"], expected_identity=snapshot["identity"]
    )
    for index in range(3):
        request = ComputationalHostRequest(
            request_id=f"observe-{index}",
            artifact_manifest_digest=manifest.manifest_digest,
            operation="temporal.ingest",
            input_value={"snapshot": snapshot, "host": "host-a", "sample": _sample(index, 2*index+1)},
            logical_time=index + 1,
            workload_id="actual-vli-m2",
        )
        completed = reference.execute(request)
        assert completed.receipt.status == "EXECUTED"
        assert completed.receipt.artifact_manifest_digest == manifest.manifest_digest
        assert completed.output["result"]["durability"] == "STAGED_FOR_M3_QUORUM"
        assert "measured_process_uptime_ns" not in completed.output["result"]
        assert "samples_in_one_live_process" not in completed.output["result"]
        snapshot = completed.output["snapshot"]
        assert len(snapshot["events"]) == index + 1
        assert snapshot["events"][-1]["host"] == "host-a"
    assert snapshot["events"][-1]["time"] == "2/1"
    assert TemporalIntelligenceGround.restore(
        snapshot, expected_head=snapshot["head"], expected_identity=snapshot["identity"]
    ).epochs[0]["status"] == "QUALIFIED_SAMPLES_ONLY"

    compiled = reference.execute(ComputationalHostRequest(
        request_id="compile",
        artifact_manifest_digest=manifest.manifest_digest,
        operation="temporal.compile",
        input_value={"snapshot": snapshot, "epoch_index": 0},
        logical_time=4, workload_id="actual-vli-m2",
    ))
    assert compiled.output["result"]["rate"] == ["2/1"]
    navigation = reference.execute(ComputationalHostRequest(
        request_id="navigate",
        artifact_manifest_digest=manifest.manifest_digest,
        operation="temporal.navigate",
        input_value={"snapshot": snapshot, "time": "1/2", "epoch_index": 0, "allow_projection": False},
        logical_time=5, workload_id="actual-vli-m2",
    ))
    assert navigation.output["result"]["values"] == ["2/1"]
    assert navigation.output["result"]["status"] == "UNVERIFIED_INTERPOLATION"
    assert verify_temporal_navigation(
        snapshot, navigation.output["result"],
        expected_head=snapshot["head"], expected_identity=snapshot["identity"],
    )
    with pytest.raises(ComputationalBackendError, match="catalogue"):
        reference.execute(ComputationalHostRequest(
            request_id="invalid", artifact_manifest_digest=manifest.manifest_digest,
            operation="python.eval", input_value={"code": "print('bad')"},
            logical_time=7, workload_id="actual-vli-m2",
        ))


def test_real_vli_epochs_rehome_eight_times_and_reconstruct_m3_os(tmp_path: Path) -> None:
    """Actual living VL-I continuity across eight separately instantiated Python hosts."""
    ref = _reference()
    backing = PageBacking()
    initial_store = _store(tmp_path, backing, ref)
    current = initial_store.create_session(_initial())
    original = read_vli_temporal_checkpoint(current.state_bytes)
    initial_identity = original["identity"]
    pids: list[int] = []
    readings = [1, 3, 5, 7, 9, 30, 31, 32]
    observed_heads = []
    previous_history = []
    for index, value in enumerate(readings):
        observer_host = "host-a" if index % 2 == 0 else "host-b"
        reopened = _store(tmp_path, backing, ref)
        backend, adapter = _adapter(
            reopened, ref, observer_host, _remote(observer_host, ref, pids),
        )
        advanced = adapter.apply(
            encode_vli_temporal_operation("temporal.ingest", {
                "sample": _sample(index, value),
            }),
            operation_id=f"observe-{index}",
            expected_revision=current.revision,
            expected_checkpoint_digest=current.checkpoint_digest,
        )
        assert backend.remote_calls == 1
        assert advanced.revision == current.revision + 1
        checkpoint = read_vli_temporal_checkpoint(advanced.state_bytes)
        assert checkpoint["identity"] == initial_identity
        assert checkpoint["events"][:-1] == previous_history
        assert checkpoint["events"][-1]["host"] == observer_host
        assert checkpoint["events"][-1]["values"] == [f"{value}/1"]
        assert checkpoint["head"] not in observed_heads
        previous_history = checkpoint["events"]
        observed_heads.append(checkpoint["head"])
        semantic = _read_result(advanced.state_bytes, f"observe-{index}", index + 1)
        assert semantic["head"] == checkpoint["head"]
        assert semantic["result"]["source_sample_sequence"] == index
        assert semantic["result"]["durability"] == "STAGED_FOR_M3_QUORUM"
        if index == 5:
            assert semantic["result"]["changed_interpretation"] is True
            assert semantic["result"]["epoch_count"] == 2
            assert semantic["result"]["active_status"] == "INSUFFICIENT"
        current = advanced
    assert current.revision == 9
    assert len(set(pids)) == len(pids) == 8
    assert len(set(observed_heads)) == 8
    latest = _store(tmp_path, backing, ref).load_latest()
    assert latest.state_bytes == current.state_bytes
    assert latest.checkpoint_digest == current.checkpoint_digest
    restored = restore_headless_state(latest.state_bytes)
    assert restored.environment.kernel.journal.verify()
    ground = read_vli_temporal_checkpoint(latest.state_bytes)
    assert len(ground["events"]) == 8
    epochs = TemporalIntelligenceGround.restore(
        ground, expected_head=ground["head"], expected_identity=ground["identity"]
    ).epochs
    assert len(epochs) == 2
    assert [item["status"] for item in epochs] == [
        "QUALIFIED_SAMPLES_ONLY", "QUALIFIED_SAMPLES_ONLY",
    ]

    # New observer-host continues *intention*, not merely writing source events.
    inquire_backend, inquire = _adapter(
        _store(tmp_path, backing, ref), ref, "host-a", _remote("host-a", ref, pids),
    )
    sought = inquire.apply(
        encode_vli_temporal_operation("temporal.inquire", {"strategy": "uniform"}),
        operation_id="request-next", expected_revision=latest.revision,
        expected_checkpoint_digest=latest.checkpoint_digest,
    )
    asked = _read_result(sought.state_bytes, "request-next", 9)
    assert asked["result"]["time"] == "8/1"
    assert asked["result"]["source_observation"] is False
    assert inquire_backend.remote_calls == 1
    assert read_vli_temporal_checkpoint(sought.state_bytes) == ground

    navigate_backend, navigate = _adapter(
        _store(tmp_path, backing, ref), ref, "host-b", _remote("host-b", ref, pids),
    )
    moved = navigate.apply(
        encode_vli_temporal_operation("temporal.navigate", {
            "time": "13/2", "epoch_index": 1, "allow_projection": False,
        }),
        operation_id="navigate-intention", expected_revision=sought.revision,
        expected_checkpoint_digest=sought.checkpoint_digest,
    )
    prediction = _read_result(moved.state_bytes, "navigate-intention", 10)
    assert prediction["result"]["values"] == ["63/2"]
    assert prediction["result"]["status"] == "UNVERIFIED_INTERPOLATION"
    assert prediction["result"]["expanded_trajectory_steps"] == 0
    assert prediction["head"] == ground["head"]
    assert navigate_backend.remote_calls == 1
    assert _store(tmp_path, backing, ref).load_latest().state_bytes == moved.state_bytes

    def forbid(*_args):
        """Existing accepted VL-I observation cannot execute a second time."""
        raise AssertionError("accepted VL-I observation was re-executed")
    replay_backend, replay_adapter = _adapter(
        _store(tmp_path, backing, ref), ref, "host-b", forbid,
    )
    replay = replay_adapter.apply(
        encode_vli_temporal_operation("temporal.navigate", {
            "time": "13/2", "epoch_index": 1, "allow_projection": False,
        }), operation_id="navigate-intention",
    )
    assert replay.replayed
    assert replay.checkpoint_digest == moved.checkpoint_digest
    assert replay_backend.remote_calls == 0


def test_original_vli_refuses_tampered_prior_source_before_remote_work(tmp_path: Path) -> None:
    """Externally anchored M3 OS source bytes cannot bypass original VL-I verifier."""
    reference = _reference()
    backing = PageBacking()
    initial_os = restore_headless_state(_initial())
    forged = create_vli_temporal_genesis(
        "environment:time-source-drift", dimensions=1, observer="continuing-vli",
    )
    forged["head"] = "0" * 64
    initial_os.install_source(VLI_STATE_PATH, json.dumps(
        forged, sort_keys=True, separators=(",", ":")
    ))
    store = _store(tmp_path, backing, reference)
    initial = store.create_session(serialize_headless_state(initial_os))
    backend, adapter = _adapter(
        store, reference, "host-a",
        lambda *_args: (_ for _ in ()).throw(AssertionError("unverified Ground reached remote")),
    )
    with pytest.raises(ComputationalTransitionError, match="source-verification"):
        adapter.apply(
            encode_vli_temporal_operation("temporal.ingest", {"sample": _sample(0, 1)}),
            operation_id="bad-previous",
        )
    assert backend.remote_calls == 0
    assert store.load_latest().checkpoint_digest == initial.checkpoint_digest


def test_original_vli_rejects_forged_m2_output_with_fresh_valid_receipt(tmp_path: Path) -> None:
    """Full semantic reconstruction defeats a well-formed recomputed output digest."""
    ref = _reference()
    backing = PageBacking()
    store = _store(tmp_path, backing, ref)
    original = store.create_session(_initial())

    def forged(operation, operation_id, args, context):
        """Forge a new digest-valid M2 result without actual corresponding VL-I work."""
        result = _remote("host-a", ref, [])(operation, operation_id, args, context)
        result["output"]["result"]["active_status"] = "QUALIFIED_SAMPLES_ONLY"
        prior = ComputationalHostReceipt.from_dict(result["receipt"])
        raw = json.dumps(
            result["output"], sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        ).encode("utf-8")
        result["receipt"] = ComputationalHostReceipt.create(
            host_id=prior.host_id,
            artifact_manifest_digest=prior.artifact_manifest_digest,
            backend_fingerprint=prior.backend_fingerprint,
            request_id=prior.request_id, workload_id=prior.workload_id,
            logical_time=prior.logical_time, input_digest=prior.input_digest,
            output_digest=hashlib.sha256(raw).hexdigest(),
            output_size_bytes=len(raw),
        ).to_dict()
        return result

    backend, adapter = _adapter(store, ref, "host-a", forged)
    with pytest.raises(ComputationalTransitionError, match="source-executed reference"):
        adapter.apply(
            encode_vli_temporal_operation("temporal.ingest", {"sample": _sample(0, 1)}),
            operation_id="forged-output",
        )
    assert backend.remote_calls == 1
    assert store.load_latest().checkpoint_digest == original.checkpoint_digest


def test_dropped_vli_worker_response_and_reassigned_host_preserve_m3_head(tmp_path: Path) -> None:
    """Pure work without a published result leaves no accepted source observation."""
    ref = _reference()
    backing = PageBacking()
    store = _store(tmp_path, backing, ref)
    initial = store.create_session(_initial())

    def dropped(operation, operation_id, args, context):
        """Execute original VL-I then lose its output before M3 publication."""
        _remote("host-a", ref, [])(operation, operation_id, args, context)
        raise ConnectionError("lost observer result")

    old, adapter = _adapter(store, ref, "host-a", dropped)
    with pytest.raises(ComputationalTransitionError, match="backend failed"):
        adapter.apply(
            encode_vli_temporal_operation("temporal.ingest", {"sample": _sample(0, 1)}),
            operation_id="reassign-first",
        )
    assert old.remote_calls == 1
    assert store.load_latest().checkpoint_digest == initial.checkpoint_digest
    pids = []
    replacement, new_adapter = _adapter(
        _store(tmp_path, backing, ref), ref, "host-b", _remote("host-b", ref, pids),
    )
    accepted = new_adapter.apply(
        encode_vli_temporal_operation("temporal.ingest", {"sample": _sample(0, 1)}),
        operation_id="reassign-first",
        expected_revision=initial.revision,
        expected_checkpoint_digest=initial.checkpoint_digest,
    )
    assert replacement.remote_calls == 1
    assert accepted.revision == 2
    assert read_vli_temporal_checkpoint(accepted.state_bytes)["events"][0]["host"] == "host-b"


def test_valid_old_vli_host_cannot_overwrite_newly_committed_observation(tmp_path: Path) -> None:
    """A genuine but tardy VL-I source sample cannot win a stale M3 predecessor CAS."""
    ref = _reference()
    backing = PageBacking()
    store = _store(tmp_path, backing, ref)
    initial = store.create_session(_initial())
    ready, release = Event(), Event()
    outcomes: list[object] = []
    pids = []

    def delayed(operation, operation_id, args, context):
        """Hold real host-a output while host-b wins the M3 session revision."""
        result = _remote("host-a", ref, pids)(operation, operation_id, args, context)
        ready.set()
        assert release.wait(30)
        return result

    old_backend, old_adapter = _adapter(store, ref, "host-a", delayed)
    new_backend, new_adapter = _adapter(store, ref, "host-b", _remote("host-b", ref, pids))

    def obsolete_writer():
        """Attempt to publish a valid VL-I source observation after authority changes."""
        try:
            outcomes.append(old_adapter.apply(
                encode_vli_temporal_operation("temporal.ingest", {"sample": _sample(0, 1)}),
                operation_id="old-writer", expected_revision=initial.revision,
                expected_checkpoint_digest=initial.checkpoint_digest,
            ))
        except Exception as exc:
            outcomes.append(exc)

    thread = Thread(target=obsolete_writer, daemon=True)
    thread.start()
    try:
        assert ready.wait(30)
        accepted = new_adapter.apply(
            encode_vli_temporal_operation("temporal.ingest", {"sample": _sample(0, 1)}),
            operation_id="new-writer", expected_revision=initial.revision,
            expected_checkpoint_digest=initial.checkpoint_digest,
        )
    finally:
        release.set()
        thread.join(30)
    assert not thread.is_alive()
    assert len(outcomes) == 1
    assert isinstance(outcomes[0], ComputationalSessionConflictError)
    assert old_backend.remote_calls == new_backend.remote_calls == 1
    assert len(pids) == len(set(pids)) == 2
    newest = _store(tmp_path, backing, ref).load_latest()
    assert newest.checkpoint_digest == accepted.checkpoint_digest
    assert read_vli_temporal_checkpoint(newest.state_bytes)["events"][0]["host"] == "host-b"


def test_real_vli_worker_hard_kill_cut_preserves_only_admitted_m3_state(tmp_path: Path) -> None:
    """Reject unacknowledged work; accept published verified work after worker kill."""
    ref = _reference()
    backing = PageBacking()
    store = _store(tmp_path, backing, ref)
    initial = store.create_session(_initial())
    pids = []
    killed, adapter = _adapter(
        store, ref, "host-a", _remote("host-a", ref, pids, crash_cut="before_publish"),
    )
    with pytest.raises(ComputationalTransitionError, match="backend failed"):
        adapter.apply(
            encode_vli_temporal_operation("temporal.ingest", {"sample": _sample(0, 1)}),
            operation_id="cut-before",
        )
    assert store.load_latest().checkpoint_digest == initial.checkpoint_digest
    retained, replacement = _adapter(
        _store(tmp_path, backing, ref), ref, "host-b",
        _remote("host-b", ref, pids, crash_cut="after_publish"),
    )
    completed = replacement.apply(
        encode_vli_temporal_operation("temporal.ingest", {"sample": _sample(0, 1)}),
        operation_id="cut-after", expected_revision=initial.revision,
        expected_checkpoint_digest=initial.checkpoint_digest,
    )
    assert killed.remote_calls == retained.remote_calls == 1
    assert completed.revision == 2
    assert len(set(pids)) == len(pids) == 2
    assert read_vli_temporal_checkpoint(completed.state_bytes)["events"][0]["host"] == "host-b"
    final = _store(tmp_path, backing, ref).load_latest()
    assert final.checkpoint_digest == completed.checkpoint_digest
    assert _read_result(final.state_bytes, "cut-after", 1)["result"]["active_status"] == "INSUFFICIENT"



def _signed_publisher():
    """External publisher owns its actual Ed25519 private signing key."""
    pytest.importorskip("cryptography")
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from vli.authenticated_temporal_source import public_key_hex
    secret = Ed25519PrivateKey.generate()
    return secret, public_key_hex(secret)


def _signed_packet(secret, source, index, value):
    """Use the real VL-I TIME-005 external publisher, not a fabricated signature."""
    from vli.authenticated_temporal_source import sign_source_observation
    return sign_source_observation(
        secret, source=source, sequence=index,
        time=f"{index}/1", value=f"{value}/1",
    )


def test_ed25519_signed_original_vli_ground_survives_six_process_rehosts(tmp_path: Path) -> None:
    """The original TIME-005 publisher signature and TIME-001 Ground both survive M3."""
    from mailcpu.vli_signed_source import (
        bind_vli_signed_source, verify_signed_history,
    )
    from vli.authenticated_temporal_source import _packet_digest

    source = "external-ed25519-observation-publisher"
    secret, public_key = _signed_publisher()
    reference = _reference()
    backing = PageBacking()
    store = _store(tmp_path, backing, reference)
    initial = bind_vli_signed_source(_initial(), source=source, public_key=public_key)
    current = store.create_session(initial)
    pids = []
    heads = []
    values = [1, 3, 5, 23, 24, 25]
    for index, value in enumerate(values):
        packet = _signed_packet(secret, source, index, value)
        host_id = "host-a" if index % 2 == 0 else "host-b"
        backend, adapter = _adapter(
            _store(tmp_path, backing, reference), reference, host_id,
            _remote(host_id, reference, pids),
        )
        accepted = adapter.apply(
            encode_vli_temporal_operation("temporal.ingest_signed", {
                "packet": packet,
            }),
            operation_id=f"signed-{index}",
            expected_revision=current.revision,
            expected_checkpoint_digest=current.checkpoint_digest,
        )
        assert backend.remote_calls == 1
        assert accepted.revision == current.revision + 1
        assert packet["signature"] != ""
        semantic = _read_result(accepted.state_bytes, f"signed-{index}", index + 1)
        assert semantic["source_authentication"] == {
            "kind": "VL-I-TIME005-ED25519",
            "packet_digest": _packet_digest(packet),
            "publisher": source,
        }
        assert semantic["result"]["durability"] == "STAGED_FOR_M3_QUORUM"
        observed = read_vli_temporal_checkpoint(accepted.state_bytes)
        assert observed["events"][-1]["source_digest"] == _packet_digest(packet)
        assert observed["events"][-1]["host"] == host_id
        assert verify_signed_history(restore_headless_state(accepted.state_bytes), observed)
        heads.append(observed["head"])
        current = accepted

    assert len(set(pids)) == len(pids) == 6
    assert len(set(heads)) == 6
    recovered = _store(tmp_path, backing, reference).load_latest()
    assert recovered.revision == 7
    assert recovered.checkpoint_digest == current.checkpoint_digest
    ground = read_vli_temporal_checkpoint(recovered.state_bytes)
    assert [e["status"] for e in TemporalIntelligenceGround.restore(
        ground, expected_head=ground["head"], expected_identity=ground["identity"]
    ).epochs] == ["QUALIFIED_SAMPLES_ONLY", "QUALIFIED_SAMPLES_ONLY"]
    assert recovered.state_bytes == current.state_bytes


def test_signed_vli_observation_refuses_unsigned_tampered_and_stale_sources(tmp_path: Path) -> None:
    """Pinned public-key source policy governs input before remote Python execution."""
    from mailcpu.vli_signed_source import bind_vli_signed_source
    source = "trusted-externally-signed-environment"
    secret, public_key = _signed_publisher()
    ref = _reference()
    backing = PageBacking()
    store = _store(tmp_path, backing, ref)
    genesis = store.create_session(bind_vli_signed_source(
        _initial(), source=source, public_key=public_key,
    ))

    def never_remote(*_args):
        """A refused source packet must never enter a physical VL-I host."""
        raise AssertionError("rejected publisher request reached remote host")

    bad_backend, bad = _adapter(store, ref, "host-a", never_remote)
    with pytest.raises(ComputationalTransitionError, match="unsigned"):
        bad.apply(
            encode_vli_temporal_operation("temporal.ingest", {
                "sample": _sample(0, 1),
            }), operation_id="unsigned-refused",
        )
    first_packet = _signed_packet(secret, source, 0, 1)
    tampered = dict(first_packet)
    tampered["values"] = ["999/1"]
    with pytest.raises(ComputationalTransitionError, match="signature"):
        bad.apply(
            encode_vli_temporal_operation("temporal.ingest_signed", {
                "packet": tampered,
            }), operation_id="signature-refused",
        )
    wrong_secret, _ = _signed_publisher()
    with pytest.raises(ComputationalTransitionError, match="signature"):
        bad.apply(
            encode_vli_temporal_operation("temporal.ingest_signed", {
                "packet": _signed_packet(wrong_secret, source, 0, 1),
            }), operation_id="untrusted-publisher",
        )
    assert bad_backend.remote_calls == 0
    assert store.load_latest().checkpoint_digest == genesis.checkpoint_digest

    real_backend, real_adapter = _adapter(
        store, ref, "host-b", _remote("host-b", ref, []),
    )
    accepted = real_adapter.apply(
        encode_vli_temporal_operation("temporal.ingest_signed", {
            "packet": first_packet,
        }), operation_id="accepted-signed",
        expected_revision=genesis.revision,
        expected_checkpoint_digest=genesis.checkpoint_digest,
    )
    assert accepted.revision == 2
    stale_backend, stale_adapter = _adapter(
        _store(tmp_path, backing, ref), ref, "host-a", never_remote,
    )
    with pytest.raises(ComputationalTransitionError, match="sequence"):
        stale_adapter.apply(
            encode_vli_temporal_operation("temporal.ingest_signed", {
                "packet": first_packet,
            }), operation_id="stale-source-sequence",
        )
    assert stale_backend.remote_calls == 0
    assert _store(tmp_path, backing, ref).load_latest().checkpoint_digest == accepted.checkpoint_digest


def test_signed_vli_historical_source_packet_tampering_is_detected_at_restore(tmp_path: Path) -> None:
    """Rehashing the OS snapshot does not replace original publisher authentication."""
    from mailcpu.vli_signed_source import bind_vli_signed_source, SOURCE_PACKET_ROOT
    source = "sensor-history-signatures"
    secret, public_key = _signed_publisher()
    ref = _reference()
    backing = PageBacking()
    store = _store(tmp_path, backing, ref)
    starting = store.create_session(bind_vli_signed_source(
        _initial(), source=source, public_key=public_key,
    ))
    packet = _signed_packet(secret, source, 0, 1)
    _, adapter = _adapter(store, ref, "host-a", _remote("host-a", ref, []))
    current = adapter.apply(
        encode_vli_temporal_operation("temporal.ingest_signed", {
            "packet": packet,
        }), operation_id="history-valid",
    )
    machine = restore_headless_state(current.state_bytes)
    altered = dict(packet)
    altered["values"] = ["300/1"]
    machine.install_source(
        f"{SOURCE_PACKET_ROOT}/0000.json",
        json.dumps(altered, sort_keys=True, separators=(",", ":")),
    )
    with pytest.raises(ComputationalTransitionError, match="signature"):
        read_vli_temporal_checkpoint(serialize_headless_state(machine))


def test_signed_vli_host_kill_after_result_publishes_only_verified_source(tmp_path: Path) -> None:
    """Publisher signature remains verified even if the executing Python host dies."""
    from mailcpu.vli_signed_source import bind_vli_signed_source
    source = "signed-physical-worker-death"
    secret, public_key = _signed_publisher()
    ref = _reference()
    backing = PageBacking()
    store = _store(tmp_path, backing, ref)
    initial = store.create_session(bind_vli_signed_source(
        _initial(), source=source, public_key=public_key,
    ))
    pids = []
    backend, adapter = _adapter(
        store, ref, "host-b",
        _remote("host-b", ref, pids, crash_cut="after_publish"),
    )
    accepted = adapter.apply(
        encode_vli_temporal_operation("temporal.ingest_signed", {
            "packet": _signed_packet(secret, source, 0, 1),
        }),
        operation_id="signed-killed-publisher",
        expected_revision=initial.revision,
        expected_checkpoint_digest=initial.checkpoint_digest,
    )
    assert accepted.revision == 2
    assert backend.remote_calls == 1
    assert len(pids) == 1
    latest = _store(tmp_path, backing, ref).load_latest()
    assert latest.checkpoint_digest == accepted.checkpoint_digest
    assert read_vli_temporal_checkpoint(latest.state_bytes)["events"][0]["host"] == "host-b"
    assert _read_result(latest.state_bytes, "signed-killed-publisher", 1)["source_authentication"]["publisher"] == source



def test_real_vli_interpreter_executes_under_original_ecpu_hypervisor_authority() -> None:
    """True E-CPU Hypervisor admits a real VL-I source operation; no-capability peer is denied."""
    from mailcpu import (
        Capability, HypervisorAction, HypervisorPolicy, LexicalDecisionModel,
        OperatorRegistry, SystemIdentity, SystemSeed, SystemSeedEnvelope,
        VirtualBudget, VirtualGroundRef, VirtualLayerRuntime, VirtualLayerWorkload,
        VirtualOperatorRef,
    )
    from mailcpu.computational_host import register_computational_host_operator
    from mailcpu.vli_temporal_host import VLI_TEMPORAL_OPERATOR_ID

    reference = _reference()
    machine = HeadlessOS()
    machine.hypervisor.classifier = LexicalDecisionModel()
    machine.hypervisor.policy = HypervisorPolicy(embedding_review_confidence=1.0)
    identity = SystemIdentity("real-vli-hypervisor-system", 1)
    envelope = SystemSeedEnvelope(
        identity, "executor", "real-vli", SystemSeed.from_system(machine),
    )
    assert machine.seed_admission.admit(envelope).accepted
    ground = VirtualGroundRef.from_envelope(envelope)
    registry = OperatorRegistry()
    spec = register_computational_host_operator(
        registry, reference, operator_id=VLI_TEMPORAL_OPERATOR_ID,
    )
    assert spec.required_rights == frozenset({"compute"})
    runtime = VirtualLayerRuntime(
        registry, "vli-native-execution-node", frozenset({"cpu"}),
    )
    authorized_pid = machine.environment.kernel.spawn(
        "real-vli-authorized-service",
        capabilities=(Capability("/virtual-layer/operators", frozenset({"compute"})),),
        parent_pid=machine.environment.init_pid,
    )
    unauthorized_pid = machine.environment.kernel.spawn(
        "real-vli-unauthorized-service",
        parent_pid=machine.environment.init_pid,
    )

    def typed_workload(name: str):
        """Bind VL-I source computation to the original admissible seed and Hypervisor."""
        return VirtualLayerWorkload(
            workload_id=name,
            system=identity,
            ground=ground,
            intention={"goal": {"kind": "source-qualified-temporal-observation"}},
            operators=(VirtualOperatorRef(VLI_TEMPORAL_OPERATOR_ID, 1, "cpu"),),
            input_value={
                "operation": "temporal.ingest",
                "input": {
                    "snapshot": create_vli_temporal_genesis(
                        "environment:time-source-drift", observer="continuing-vli",
                    ),
                    "host": "authorized-original-vli",
                    "sample": _sample(0, 1),
                },
            },
            budget=VirtualBudget(
                max_energy=1_000_000, max_bytes=1_048_576, max_virtual_ticks=1000,
            ),
            logical_time=1,
            eligible_nodes=("vli-native-execution-node",),
            max_hops=2,
        )

    approved = runtime.execute_operator(
        machine, authorized_pid, "vli-source-controller", "vli-channel",
        1, 1, typed_workload("vli-authorized-1"), VLI_TEMPORAL_OPERATOR_ID,
    )
    assert approved.action is HypervisorAction.ALLOW
    assert approved.executed is True
    assert approved.effect["kind"] == "virtual_layer.operator_result"
    native_output = approved.effect["result"]["output"]
    assert native_output["result"]["active_status"] == "INSUFFICIENT"
    assert native_output["snapshot"]["events"][0]["time"] == "0/1"
    receipt = ComputationalHostReceipt.from_dict(approved.effect["result"]["receipt"])
    assert receipt.status == "EXECUTED"
    assert receipt.artifact_manifest_digest == reference.manifest.manifest_digest
    assert machine.environment.kernel.journal.verify()

    refused = runtime.execute_operator(
        machine, unauthorized_pid, "vli-source-controller", "vli-denied-channel",
        2, 1, typed_workload("vli-unauthorized-2"), VLI_TEMPORAL_OPERATOR_ID,
    )
    assert refused.executed is False
    assert refused.action is not HypervisorAction.ALLOW
    assert machine.environment.kernel.journal.verify()
