"""SOI-002: M1/M3-authoritative OS continuation using two actual TCP worker processes."""

from __future__ import annotations

import hashlib
import json
from threading import Event, Thread
from pathlib import Path

import pytest

from mailcpu import HeadlessOS
from mailcpu.computational_objects import ComputationalObjectStore
from mailcpu.computational_session import (
    ComputationalSessionConflictError,
    ComputationalSessionStore,
)
from mailcpu.computational_transition import (
    ComputationalSessionTransitionAdapter,
    ComputationalTransitionContract,
    ComputationalTransitionError,
)
from mailcpu.headless_relation import compare_headless_os_states
from mailcpu.model import Instruction, Op, Program
from mailcpu.recovery_lineage import RecoveryLineageAuthority, RecoveryLineageCoordinator
from mailcpu.seed_commit_quorum import SeedCommitMembership
from mailcpu.stream_os_session import (
    OS_BACKEND_FINGERPRINT,
    OS_INTERPRETATION_FINGERPRINT,
    OS_STATE_SCHEMA,
    OS_STEP_INPUT_SCHEMA,
    OS_TRANSITION_ID,
    HeadlessOSQuorumTransitionBackend,
    encode_headless_step,
    execute_headless_step,
    restore_headless_state,
    serialize_headless_state,
)

from test_stream_hosted_os import _remote_step, _remote_crash_cut, _virtual_stream

GENESIS = hashlib.sha256(b"mailcpu-recovery-lineage-genesis-v1").hexdigest()
ARTIFACT = hashlib.sha256(b"SOI-002-native-headlessos-artifact").hexdigest()


class MemoryPageBacking:
    """Immutable in-memory pages for M1; authority journals are separate real files."""

    page_size = 4096

    def __init__(self) -> None:
        """Construct the immutable test page table."""
        self.pages: dict[str, bytes] = {}

    def put_page(self, data: bytes) -> str:
        """Store a fixed-size M1 page and refuse content-address collisions."""
        if not isinstance(data, bytes) or len(data) != self.page_size:
            raise ValueError("M1 page length mismatch")
        digest = hashlib.sha256(data).hexdigest()
        previous = self.pages.setdefault(digest, data)
        if previous != data:
            raise ValueError("M1 page digest collision")
        return digest

    def get_page(self, digest: str) -> bytes:
        """Resolve a byte-identical previously stored immutable page."""
        return self.pages[digest]


def _store(tmp_path: Path, backing: MemoryPageBacking) -> ComputationalSessionStore:
    """Reopen the same fixed three-authority quorum journals and M1 backing."""
    membership = SeedCommitMembership(
        "soi-002-headless-os", 1, ("A", "B", "C"), "A", 1, GENESIS
    )
    authorities = {
        member: RecoveryLineageAuthority(
            membership, member, tmp_path / "authorities" / (member + ".jsonl")
        )
        for member in membership.member_ids
    }
    lineage = RecoveryLineageCoordinator(membership, authorities)
    objects = ComputationalObjectStore(backing, chunk_size=4096)
    return ComputationalSessionStore(
        tmp_path / "session",
        objects,
        lineage,
        artifact_manifest_digest=ARTIFACT,
        backend_fingerprint=OS_BACKEND_FINGERPRINT,
        state_schema_id=OS_STATE_SCHEMA,
        state_media_type="application/json",
    )


def _contract() -> ComputationalTransitionContract:
    """Declare one native pure OS backend, state schema and bounded workload."""
    return ComputationalTransitionContract(
        transition_id=OS_TRANSITION_ID,
        state_schema_id=OS_STATE_SCHEMA,
        input_schema_id=OS_STEP_INPUT_SCHEMA,
        interpretation_fingerprint=OS_INTERPRETATION_FINGERPRINT,
        backend_fingerprint=OS_BACKEND_FINGERPRINT,
        max_input_bytes=1024,
        max_state_bytes=4_194_304,
    )


def _machine() -> tuple[HeadlessOS, int, int]:
    """Seed a running native VM and queued virtual TCP bytes before checkpoint."""
    machine = HeadlessOS()
    pid = machine.spawn(Program((
        Instruction(Op.SET, ("remaining", 45)),
        Instruction(Op.SET, ("minus_one", -1)),
        Instruction(Op.ADD, ("remaining", "remaining", "minus_one")),
        Instruction(Op.BRANCH, ("remaining", 2)),
        Instruction(Op.HALT),
    )), "quorum-rehosted-os-process")
    fd = _virtual_stream(machine)
    machine.run(max_ticks=5)
    assert machine.process(pid).status == "runnable"
    return machine, pid, fd


def _execute_tcp(state: bytes, operation: bytes, context) -> bytes:
    """Run the exact native OS step on a fresh process via the SOI-001 TCP carrier."""
    step = json.loads(operation)
    result = _remote_step(
        json.loads(state),
        identity=context.session_id,
        revision=context.revision,
        ticks=step["ticks"],
        consume_fd=step["read_fd"],
    )
    return json.dumps(
        result["state"], sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _adapter(store: ComputationalSessionStore, remote=_execute_tcp):
    """Bind a remote observer through the unmodified M3 pure transition adapter."""
    backend = HeadlessOSQuorumTransitionBackend(remote)
    return backend, ComputationalSessionTransitionAdapter(store, _contract(), backend)


def test_two_tcp_hosts_commit_quorum_verified_os_revisions(tmp_path: Path) -> None:
    """Different worker PIDs produce a single M3 lineage and exact OS state."""
    machine, pid, fd = _machine()
    initial = serialize_headless_state(machine)
    backing = MemoryPageBacking()
    store = _store(tmp_path, backing)
    genesis = store.create_session(initial)
    assert genesis.revision == 1
    backend, adapter = _adapter(store)

    first_input = encode_headless_step(ticks=8, read_fd=fd, read_size=6)
    first = adapter.apply(
        first_input, operation_id="receive-virtual-queue",
        expected_revision=genesis.revision,
        expected_checkpoint_digest=genesis.checkpoint_digest,
    )
    assert first.revision == 2
    assert first.checkpoint.predecessor_checkpoint_digest == genesis.checkpoint_digest
    assert first.checkpoint.predecessor_lineage_digest == genesis.lineage_manifest.digest

    second = adapter.apply(
        encode_headless_step(ticks=200), operation_id="finish-os-process",
        expected_revision=first.revision, expected_checkpoint_digest=first.checkpoint_digest,
    )
    assert second.revision == 3
    assert backend.remote_calls == 2
    assert second.checkpoint.predecessor_lineage_digest == first.lineage_manifest.digest

    reference = restore_headless_state(initial)
    assert reference.syscall(reference.environment.init_pid, "read", fd=fd, size=6) == b"queued"
    reference.run(8)
    reference.run(200)
    final = restore_headless_state(second.state_bytes)
    assert final.process(pid).status == "exited"
    assert final.process(pid).registers["remaining"] == 0
    assert compare_headless_os_states(reference, final).equivalent

    # Close the original session abstraction, reopen all its actual on-disk
    # authority journals and checkpoint records, but retain independently
    # owned M1 pages. Current state is the quorum high-water, not local age.
    reopened = _store(tmp_path, backing)
    latest = reopened.load_latest()
    assert latest.revision == second.revision
    assert latest.checkpoint_digest == second.checkpoint_digest
    assert latest.state_bytes == second.state_bytes

    def forbidden_remote(*_args):
        """A committed retry must return without creating a new TCP worker."""
        raise AssertionError("exact replay re-entered remote OS execution")

    replay_backend, replay_adapter = _adapter(reopened, forbidden_remote)
    replay = replay_adapter.apply(
        encode_headless_step(ticks=200), operation_id="finish-os-process",
        expected_revision=first.revision, expected_checkpoint_digest=first.checkpoint_digest,
    )
    assert replay.replayed
    assert replay.checkpoint_digest == second.checkpoint_digest
    assert replay_backend.remote_calls == 0


def test_worker_hard_kill_before_candidate_publication_preserves_quorum_tip(tmp_path: Path) -> None:
    """A private OS execution cannot advance M3 if its host dies before publishing."""
    machine, _pid, fd = _machine()
    backing = MemoryPageBacking()
    store = _store(tmp_path, backing)
    genesis = store.create_session(serialize_headless_state(machine))

    def dies_before_send(state: bytes, operation: bytes, context) -> bytes:
        """Execute and hard-kill the worker at the uncommitted publication cut."""
        step = json.loads(operation)
        receipt = _remote_crash_cut(
            json.loads(state), identity=context.session_id,
            revision=context.revision, ticks=step["ticks"],
            consume_fd=step["read_fd"], cut="before_publish",
        )
        assert receipt["kind"] == "prepared"
        raise ConnectionError("worker exited before accepted successor publication")

    interrupted_backend, interrupted_adapter = _adapter(store, dies_before_send)
    input_bytes = encode_headless_step(ticks=8, read_fd=fd, read_size=6)
    with pytest.raises(ComputationalTransitionError, match="backend failed"):
        interrupted_adapter.apply(input_bytes, operation_id="retry-after-death")
    assert interrupted_backend.remote_calls == 1
    assert store.load_latest().checkpoint_digest == genesis.checkpoint_digest

    fresh_store = _store(tmp_path, backing)
    new_backend, new_adapter = _adapter(fresh_store)
    recovered = new_adapter.apply(
        input_bytes, operation_id="retry-after-death",
        expected_revision=genesis.revision,
        expected_checkpoint_digest=genesis.checkpoint_digest,
    )
    assert recovered.revision == 2
    assert new_backend.remote_calls == 1
    assert recovered.checkpoint.predecessor_lineage_digest == genesis.lineage_manifest.digest


def test_worker_death_after_tcp_successor_pre_ack_commits_once(tmp_path: Path) -> None:
    """Receipt delivered before worker hard kill can be verified and sealed once."""
    machine, _pid, fd = _machine()
    backing = MemoryPageBacking()
    store = _store(tmp_path, backing)
    genesis = store.create_session(serialize_headless_state(machine))

    def dies_after_send(state: bytes, operation: bytes, context) -> bytes:
        """Kill a separate interpreter after its exact OS successor crossed TCP."""
        step = json.loads(operation)
        receipt = _remote_crash_cut(
            json.loads(state), identity=context.session_id,
            revision=context.revision, ticks=step["ticks"],
            consume_fd=step["read_fd"], cut="after_publish",
        )
        assert receipt["parent_revision"] == context.revision
        assert receipt["virtual_io_hex"] == b"queued".hex()
        return json.dumps(
            receipt["state"], sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")

    backend, adapter = _adapter(store, dies_after_send)
    step = encode_headless_step(ticks=8, read_fd=fd, read_size=6)
    accepted = adapter.apply(step, operation_id="worker-killed-post-tcp")
    assert accepted.revision == 2
    assert backend.remote_calls == 1
    reopened = _store(tmp_path, backing)
    replay_backend, replay_adapter = _adapter(reopened, lambda *_: b"must-not-execute")
    replay = replay_adapter.apply(step, operation_id="worker-killed-post-tcp")
    assert replay.replayed and replay.revision == accepted.revision
    assert replay_backend.remote_calls == 0
    assert reopened.load_latest().checkpoint_digest == accepted.checkpoint_digest
    assert accepted.checkpoint.predecessor_checkpoint_digest == genesis.checkpoint_digest


def test_remote_forgery_and_stale_os_writer_cannot_advance_m3(tmp_path: Path) -> None:
    """A valid but semantically incorrect OS snapshot and stale CAS are refused."""
    machine, _pid, _fd = _machine()
    backing = MemoryPageBacking()
    store = _store(tmp_path, backing)
    initial = store.create_session(serialize_headless_state(machine))
    step = encode_headless_step(ticks=8)

    def forged_successor(state: bytes, operation: bytes, _context) -> bytes:
        """Return a closed OS snapshot with an unauthorized extra filesystem effect."""
        next_state = restore_headless_state(execute_headless_step(state, operation))
        next_state.environment.kernel.fs.create_file("/forged-by-remote", b"bad")
        return serialize_headless_state(next_state)

    rogue, adapter = _adapter(store, forged_successor)
    with pytest.raises(ComputationalTransitionError, match="disagrees"):
        adapter.apply(step, operation_id="forged")
    assert store.load_latest().checkpoint_digest == initial.checkpoint_digest
    assert rogue.remote_calls == 1

    valid_backend, valid_adapter = _adapter(store)
    accepted = valid_adapter.apply(step, operation_id="valid")
    assert accepted.revision == 2
    with pytest.raises(ComputationalSessionConflictError, match="expected transition base"):
        valid_adapter.apply(
            step, operation_id="stale-after-commit",
            expected_revision=initial.revision,
            expected_checkpoint_digest=initial.checkpoint_digest,
        )
    assert valid_backend.remote_calls == 1
    with pytest.raises(ComputationalSessionConflictError, match="reused"):
        valid_adapter.apply(encode_headless_step(ticks=9), operation_id="valid")
    assert valid_backend.remote_calls == 1


def test_os_wire_input_and_snapshot_are_exact_and_bounded() -> None:
    """Reject noncanonical or unmodeled OS inputs and preserve original state."""
    machine, _pid, _fd = _machine()
    source = serialize_headless_state(machine)
    assert serialize_headless_state(restore_headless_state(source)) == source
    with pytest.raises(ComputationalTransitionError, match="ticks"):
        encode_headless_step(ticks=0)
    with pytest.raises(ComputationalTransitionError, match="read_size"):
        encode_headless_step(ticks=1, read_size=1)
    with pytest.raises(ComputationalTransitionError, match="cannot be decoded"):
        restore_headless_state(b'{"vm": {}, "vm": {}}')
    with pytest.raises(ComputationalTransitionError, match="fields"):
        execute_headless_step(source, b'{"read_fd":null,"read_size":0,"schema":"mailcpu.headless-pure-step.v1","ticks":1,"unmodeled":true}')


def test_delayed_old_tcp_host_cannot_publish_after_quorum_winner(tmp_path: Path) -> None:
    """Two independently executed successors compete; only current M3 base may win."""
    machine, _pid, _fd = _machine()
    backing = MemoryPageBacking()
    store = _store(tmp_path, backing)
    initial = store.create_session(serialize_headless_state(machine))
    published_by_old = Event()
    release_old = Event()
    old_outcome: list[BaseException | object] = []

    def delayed_old_host(state: bytes, operation: bytes, context) -> bytes:
        """Complete a real remote TCP execution but delay its local CAS publication."""
        candidate = _execute_tcp(state, operation, context)
        published_by_old.set()
        if not release_old.wait(timeout=30):
            raise RuntimeError("old host did not observe competing commit")
        return candidate

    old_backend, old_adapter = _adapter(store, delayed_old_host)
    new_backend, new_adapter = _adapter(store)

    def old_writer() -> None:
        """Try to publish an independently verified but superseded OS state."""
        try:
            old_outcome.append(old_adapter.apply(
                encode_headless_step(ticks=8), operation_id="obsolete-host-result",
                expected_revision=initial.revision,
                expected_checkpoint_digest=initial.checkpoint_digest,
            ))
        except BaseException as exc:
            old_outcome.append(exc)

    worker = Thread(target=old_writer, name="old-os-host-publication", daemon=True)
    worker.start()
    try:
        assert published_by_old.wait(timeout=20), "old host never produced a TCP successor"
        winner = new_adapter.apply(
            encode_headless_step(ticks=9), operation_id="current-host-result",
            expected_revision=initial.revision,
            expected_checkpoint_digest=initial.checkpoint_digest,
        )
        assert winner.revision == 2
        assert winner.checkpoint.predecessor_checkpoint_digest == initial.checkpoint_digest
    finally:
        release_old.set()
        worker.join(timeout=30)
    assert not worker.is_alive()
    assert len(old_outcome) == 1
    assert isinstance(old_outcome[0], ComputationalSessionConflictError)
    assert old_backend.remote_calls == new_backend.remote_calls == 1
    latest = store.load_latest()
    assert latest.checkpoint_digest == winner.checkpoint_digest
    assert latest.state_bytes == winner.state_bytes
    reference = restore_headless_state(initial.state_bytes)
    reference.run(9)
    assert compare_headless_os_states(restore_headless_state(latest.state_bytes), reference).equivalent

