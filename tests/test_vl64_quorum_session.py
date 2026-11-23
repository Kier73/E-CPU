"""SOI-004: real VL-64 worker migration with M1/M3-authoritative app state."""

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
    ComputationalHostReceipt,
    LocalComputationalHost,
)
from mailcpu.computational_objects import ComputationalObjectStore
from mailcpu.computational_session import (
    ComputationalSessionConflictError,
    ComputationalSessionStore,
)
from mailcpu.computational_transition import (
    ComputationalSessionTransitionAdapter,
    ComputationalTransitionError,
)
from mailcpu.model import Instruction, Op, Program
from mailcpu.recovery_lineage import RecoveryLineageAuthority, RecoveryLineageCoordinator
from mailcpu.seed_commit_quorum import SeedCommitMembership
from mailcpu.stream_os_session import OS_STATE_SCHEMA, restore_headless_state, serialize_headless_state
from mailcpu.vl64_runtime import (
    VL64BackendAdapter, admit_vl64_runtime, vl64_backend_profile,
)
from mailcpu.vl64_session import (
    VL64QuorumSessionBackend,
    encode_vl64_session_operation,
    vl64_session_backend_fingerprint,
    vl64_session_contract,
)

pytest.importorskip("vld")

GENESIS = hashlib.sha256(b"mailcpu-recovery-lineage-genesis-v1").hexdigest()


class PageBacking:
    """M1 immutable 4KiB pages outside every disposable VL-64 worker process."""

    page_size = 4096

    def __init__(self) -> None:
        """Create the controller-owned content-addressed page table."""
        self.pages: dict[str, bytes] = {}

    def put_page(self, data: bytes) -> str:
        """Store immutable exact-size data under its SHA-256 address."""
        if not isinstance(data, bytes) or len(data) != self.page_size:
            raise ValueError("page geometry differs")
        digest = hashlib.sha256(data).hexdigest()
        if self.pages.setdefault(digest, data) != data:
            raise ValueError("page collision")
        return digest

    def get_page(self, digest: str) -> bytes:
        """Resolve an immutable page by the digest admitted earlier."""
        return self.pages[digest]


def _reference():
    """Construct an E-CPU M2 backend over VL-64's actual installed source."""
    manifest, root = admit_vl64_runtime()
    profile = vl64_backend_profile(manifest)
    return LocalComputationalHost(
        host_id="reference-vl64",
        manifest=manifest, artifact_root=root, profile=profile,
        adapter=VL64BackendAdapter(),
    )


def _store(root: Path, backing: PageBacking, reference: LocalComputationalHost):
    """Attach real durable three-member lineage journals to one OS session."""
    membership = SeedCommitMembership(
        "vl64-app-session", 1, ("A", "B", "C"), "A", 1, GENESIS,
    )
    authorities = {
        member: RecoveryLineageAuthority(
            membership, member, root / "authorities" / f"{member}.jsonl"
        ) for member in membership.member_ids
    }
    lineage = RecoveryLineageCoordinator(membership, authorities)
    return ComputationalSessionStore(
        root / "sessions",
        ComputationalObjectStore(backing, chunk_size=4096),
        lineage,
        artifact_manifest_digest=reference.manifest.manifest_digest,
        backend_fingerprint=vl64_session_backend_fingerprint(reference),
        state_schema_id=OS_STATE_SCHEMA,
        state_media_type="application/json",
    )


def _initial_os() -> bytes:
    """Boot native MailCPU work whose state changes during VL-64 operations."""
    machine = HeadlessOS()
    pid = machine.spawn(
        Program((
            Instruction(Op.SET, ("steps_remaining", 4)),
            Instruction(Op.SET, ("negative_one", -1)),
            Instruction(Op.ADD, ("steps_remaining", "steps_remaining", "negative_one")),
            Instruction(Op.ADD, ("steps_remaining", "steps_remaining", "negative_one")),
            Instruction(Op.ADD, ("steps_remaining", "steps_remaining", "negative_one")),
            Instruction(Op.HALT),
        )),
        "vl64-app-native-supervisor",
    )
    machine.run(max_ticks=1)
    assert machine.process(pid).status == "runnable"
    return serialize_headless_state(machine)


def _remote(
    remote_host: str, process_ids: list[int], reference: LocalComputationalHost,
):
    """Bind a disposable independent Python interpreter to one admitted host ID."""
    def execute(operation, operation_id, arguments, context):
        """Rebind the exact M3 context to a fresh one-shot real VL-64 process."""
        request = {
            "schema": "mailcpu.vl64-one-shot-host.v1",
            "host_id": remote_host,
            "context_binding_digest": context.binding_digest,
            "artifact_manifest_digest": reference.manifest.manifest_digest,
            "backend_fingerprint": reference.profile.fingerprint,
            "operation_id": operation_id,
            "session_id": context.session_id,
            "logical_time": context.logical_time,
            "operation": operation,
            "arguments": arguments,
        }
        worker = subprocess.Popen(
            [sys.executable, "-m", "mailcpu.vl64_worker"],
            cwd=Path(__file__).resolve().parents[1],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        process_ids.append(worker.pid)
        output, error = worker.communicate(
            json.dumps(request, sort_keys=True, separators=(",", ":")).encode("utf-8"),
            timeout=30,
        )
        if worker.returncode != 0:
            raise RuntimeError(error.decode("utf-8", errors="replace")[-1200:])
        return json.loads(output)
    return execute


def _adapter(store, reference, remote):
    """Use original M3 session adapter with the native VL-64 state backend."""
    backend = VL64QuorumSessionBackend(
        reference, remote, allowed_remote_hosts=frozenset({"host-a", "host-b"}),
    )
    return backend, ComputationalSessionTransitionAdapter(
        store, vl64_session_contract(reference), backend,
    )


def _result(os_bytes, operation_id, logical_time):
    """Read a committed application result from the restored native OS VFS."""
    os_state = restore_headless_state(os_bytes)
    path = f"/vl64/results/{logical_time:08d}_{operation_id}.json"
    return json.loads(os_state.environment.kernel.fs.read_file(path))


def _affine(b: int):
    """Encode the genuine VL-64 long-horizon navigation operation."""
    return encode_vl64_session_operation(
        "affine.navigate",
        {"a": 5, "b": b, "x0": 3, "steps": 10**12 + 13, "modulus": 257},
    )


def test_full_vl64_app_history_survives_two_real_process_rehosts_and_m3_reopen(tmp_path: Path) -> None:
    """Native VFS results and VM supervisor state continue under one quorum identity."""
    reference = _reference()
    backing = PageBacking()
    store = _store(tmp_path, backing, reference)
    genesis = store.create_session(_initial_os())
    pids: list[int] = []
    backend_a, adapter_a = _adapter(store, reference, _remote("host-a", pids, reference))
    first = adapter_a.apply(
        _affine(1), operation_id="first", expected_revision=genesis.revision,
        expected_checkpoint_digest=genesis.checkpoint_digest,
    )
    assert first.revision == 2
    one = _result(first.state_bytes, "first", 1)
    assert one["result"]["value"] == __import__("vld").affine_navigate(5, 1, 3, 10**12 + 13, 257)
    assert one["logical_time"] == 1

    # Dispose local worker authority, reopen M3 and continue on another host.
    new_store = _store(tmp_path, backing, reference)
    backend_b, adapter_b = _adapter(new_store, reference, _remote("host-b", pids, reference))
    second = adapter_b.apply(
        _affine(2), operation_id="second",
        expected_revision=first.revision,
        expected_checkpoint_digest=first.checkpoint_digest,
    )
    assert second.revision == 3
    assert len(pids) == 2 and pids[0] != pids[1]
    assert _result(second.state_bytes, "first", 1) == one
    two = _result(second.state_bytes, "second", 2)
    assert two["result"]["value"] == __import__("vld").affine_navigate(5, 2, 3, 10**12 + 13, 257)
    assert two["result"]["value"] != one["result"]["value"]
    assert backend_a.remote_calls == backend_b.remote_calls == 1
    latest = _store(tmp_path, backing, reference).load_latest()
    assert latest.revision == 3
    assert latest.checkpoint_digest == second.checkpoint_digest
    assert latest.state_bytes == second.state_bytes
    assert latest.checkpoint.predecessor_checkpoint_digest == first.checkpoint_digest
    assert latest.checkpoint.predecessor_lineage_digest == first.lineage_manifest.digest

    def forbidden(*_args):
        """A lost reply must replay without creating a third VL-64 interpreter."""
        raise AssertionError("committed VL64 replay re-entered remote host")

    replay_backend, replay_adapter = _adapter(_store(tmp_path, backing, reference), reference, forbidden)
    replay = replay_adapter.apply(
        _affine(2), operation_id="second",
        expected_revision=first.revision,
        expected_checkpoint_digest=first.checkpoint_digest,
    )
    assert replay.replayed
    assert replay.checkpoint_digest == second.checkpoint_digest
    assert replay_backend.remote_calls == 0
    assert len(pids) == 2


def test_forged_vl64_receipt_and_context_are_rejected_before_m3_commit(tmp_path: Path) -> None:
    """Changed output with a valid reconstructed M2 receipt still fails semantic equivalence."""
    reference = _reference()
    backing = PageBacking()
    store = _store(tmp_path, backing, reference)
    genesis = store.create_session(_initial_os())

    def changed_context(operation, operation_id, arguments, context):
        """Corrupt the echoed context digest without altering the VL-64 computation."""
        result = _remote("host-a", [], reference)(operation, operation_id, arguments, context)
        result["context_binding_digest"] = "0" * 64
        return result

    backend, adapter = _adapter(store, reference, changed_context)
    with pytest.raises(ComputationalTransitionError, match="context"):
        adapter.apply(_affine(1), operation_id="wrong-context")
    assert store.load_latest().checkpoint_digest == genesis.checkpoint_digest

    def forged_value(operation, operation_id, arguments, context):
        """Reissue a well-formed receipt over a different, incorrect output."""
        result = _remote("host-a", [], reference)(operation, operation_id, arguments, context)
        result["output"]["result"]["value"] += 1
        old = ComputationalHostReceipt.from_dict(result["receipt"])
        output_bytes = json.dumps(
            result["output"], sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        ).encode("utf-8")
        result["receipt"] = ComputationalHostReceipt.create(
            host_id=old.host_id,
            artifact_manifest_digest=old.artifact_manifest_digest,
            backend_fingerprint=old.backend_fingerprint,
            request_id=old.request_id, workload_id=old.workload_id,
            logical_time=old.logical_time, input_digest=old.input_digest,
            output_digest=hashlib.sha256(output_bytes).hexdigest(),
            output_size_bytes=len(output_bytes),
        ).to_dict()
        return result

    forged_backend, forged_adapter = _adapter(store, reference, forged_value)
    with pytest.raises(ComputationalTransitionError, match="reference"):
        forged_adapter.apply(_affine(1), operation_id="forged-output")
    assert forged_backend.remote_calls == 1
    assert store.load_latest().checkpoint_digest == genesis.checkpoint_digest


def test_old_real_vl64_worker_cannot_publish_after_new_host_wins_m3(tmp_path: Path) -> None:
    """An independently executed valid result remains obsolete after a competing CAS."""
    reference = _reference()
    backing = PageBacking()
    store = _store(tmp_path, backing, reference)
    initial = store.create_session(_initial_os())
    staged = Event()
    release = Event()
    old_outcomes: list[object] = []
    pids = []

    def delayed_old_host(operation, operation_id, arguments, context):
        """Run actual VL-64 in host-a but hold its output until host-b commits."""
        result = _remote("host-a", pids, reference)(operation, operation_id, arguments, context)
        staged.set()
        assert release.wait(timeout=30)
        return result

    old_backend, old_adapter = _adapter(store, reference, delayed_old_host)
    new_backend, new_adapter = _adapter(store, reference, _remote("host-b", pids, reference))
    def old_writer():
        """Attempt obsolete publication from the prior M3 state coordinate."""
        try:
            old_outcomes.append(old_adapter.apply(
                _affine(1), operation_id="obsolete",
                expected_revision=initial.revision,
                expected_checkpoint_digest=initial.checkpoint_digest,
            ))
        except Exception as exc:
            old_outcomes.append(exc)

    thread = Thread(target=old_writer, name="old-vl64-host", daemon=True)
    thread.start()
    try:
        assert staged.wait(timeout=30)
        accepted = new_adapter.apply(
            _affine(2), operation_id="winner",
            expected_revision=initial.revision,
            expected_checkpoint_digest=initial.checkpoint_digest,
        )
    finally:
        release.set()
        thread.join(timeout=30)
    assert not thread.is_alive()
    assert len(old_outcomes) == 1
    assert isinstance(old_outcomes[0], ComputationalSessionConflictError)
    assert old_backend.remote_calls == new_backend.remote_calls == 1
    assert len(pids) == 2 and pids[0] != pids[1]
    latest = store.load_latest()
    assert latest.checkpoint_digest == accepted.checkpoint_digest
    assert _result(latest.state_bytes, "winner", 1)["result"]["value"] == __import__("vld").affine_navigate(
        5, 2, 3, 10**12 + 13, 257
    )
    assert "obsolete" not in restore_headless_state(latest.state_bytes).environment.kernel.fs.listdir("/vl64/results")


def test_lost_worker_result_recovers_from_latest_m3_os_state(tmp_path: Path) -> None:
    """A killed/unreachable observer cannot advance M3; a replacement can."""
    reference = _reference()
    backing = PageBacking()
    store = _store(tmp_path, backing, reference)
    genesis = store.create_session(_initial_os())

    def interrupted(operation, operation_id, arguments, context):
        """Execute a real VL64 child then lose its response before M3 publication."""
        _remote("host-a", [], reference)(operation, operation_id, arguments, context)
        raise ConnectionError("injected loss of VL64 worker response")

    backend, adapter = _adapter(store, reference, interrupted)
    with pytest.raises(ComputationalTransitionError, match="backend failed"):
        adapter.apply(_affine(1), operation_id="retry-op")
    assert backend.remote_calls == 1
    assert store.load_latest().checkpoint_digest == genesis.checkpoint_digest

    pids = []
    replacement, new_adapter = _adapter(
        _store(tmp_path, backing, reference), reference, _remote("host-b", pids, reference),
    )
    recovery = new_adapter.apply(
        _affine(1), operation_id="retry-op",
        expected_revision=genesis.revision,
        expected_checkpoint_digest=genesis.checkpoint_digest,
    )
    assert recovery.revision == 2
    assert replacement.remote_calls == 1
    assert _result(recovery.state_bytes, "retry-op", 1)["result"]["value"] == __import__("vld").affine_navigate(
        5, 1, 3, 10**12 + 13, 257
    )
