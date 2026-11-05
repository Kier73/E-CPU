from __future__ import annotations

from pathlib import Path

import pytest

import mailcpu.checkpoint as checkpoint_module
from mailcpu import CheckpointError, HeadlessOS, ServiceSpec, TrajectoryReader, TrajectoryWriter, load_checkpoint
from mailcpu.law_certifier import Law
from mailcpu.structural_memory import StructuralMemoryAuthorizationError, StructuralMemoryError


def _trajectory_payloads(data_path: Path, index_path: Path) -> list[dict[str, object]]:
    """Mathematics: decode the ordered witness projection `F=(payload_0,...,payload_n)` after receipt verification."""

    with TrajectoryReader(data_path, index_path) as reader:
        assert reader.verify() >= 0
        frames: list[dict[str, object]] = []
        reader.replay(lambda frame: frames.append(frame.payload))
        return frames


def test_checkpoint_restores_process_filesystem_bus_and_memory(tmp_path: Path) -> None:
    """Mathematics: continuation after restore satisfies `T^k(restore(snapshot(S))) = T^k(S)` for the remaining orbit."""

    os = HeadlessOS()
    os.install_source("/home/countdown.mca", "set n 3\nset one 1\nset zero 0\nset minus_one -1\nloop:\ncompare positive n zero\nbranch positive decrement\nhalt\ndecrement:\nadd n n minus_one\nbranch one loop\n")
    pid = os.launch_file("/home/countdown.mca", "countdown")
    os.run(5)
    os.vm.memories[pid].write(0, b"checkpoint")
    os.environment.kernel.bus.send("test", "pending", "DATA", {"value": 7})
    checkpoint = tmp_path / "state.mcpu.json"
    digest = os.save_checkpoint(checkpoint)
    restored = load_checkpoint(checkpoint)
    assert digest
    assert restored.process(pid).registers == os.process(pid).registers
    assert restored.process(pid).pc == os.process(pid).pc
    assert restored.environment.kernel.fs.read_file("/home/countdown.mca") == os.environment.kernel.fs.read_file("/home/countdown.mca")
    assert restored.vm.memories[pid].read(0, len(b"checkpoint")) == b"checkpoint"
    assert restored.environment.kernel.bus.peek("pending")[0].payload["value"] == 7
    os.run(100)
    restored.run(100)
    assert restored.process(pid).to_dict() == os.process(pid).to_dict()


def test_checkpoint_resume_matches_uninterrupted_semantic_trajectory(tmp_path: Path) -> None:
    """Mathematics: digest-checked restore with receipt append satisfies `π(uninterrupted)=π(resumed)` and one contiguous `H_n` chain."""

    source = "set n 3\nset one 1\nset zero 0\nset minus_one -1\nloop:\ncompare positive n zero\nbranch positive decrement\nhalt\ndecrement:\nadd n n minus_one\nbranch one loop\n"
    uninterrupted_data = tmp_path / "uninterrupted.mtrj"
    uninterrupted_index = tmp_path / "uninterrupted.mtrj.idx"
    checkpoint = tmp_path / "resume.mcpu.json"
    with TrajectoryWriter(uninterrupted_data, uninterrupted_index) as writer:
        operating_system = HeadlessOS(trajectory=writer)
        operating_system.launch_source(source, "resume-corpus")
        prefix_events = operating_system.run(5)
        operating_system.save_checkpoint(checkpoint)
        operating_system.run(100)
    uninterrupted = _trajectory_payloads(uninterrupted_data, uninterrupted_index)

    resumed_data = tmp_path / "resumed.mtrj"
    resumed_index = tmp_path / "resumed.mtrj.idx"
    with TrajectoryWriter(resumed_data, resumed_index) as writer:
        prefix_os = HeadlessOS(trajectory=writer)
        prefix_os.launch_source(source, "resume-corpus")
        assert len(prefix_os.run(5)) == len(prefix_events)
    with TrajectoryWriter.resume(resumed_data, resumed_index) as writer:
        restored = load_checkpoint(checkpoint)
        restored.vm.trajectory = writer
        restored.run(100)
    resumed = _trajectory_payloads(resumed_data, resumed_index)

    assert uninterrupted == resumed


def test_multitask_checkpoint_resume_preserves_causal_mailbox_trajectory(tmp_path: Path) -> None:
    """Mathematics: for producer/consumer state `S`, `π(T^k(S)) = π(T^k(restore(save(S))))` while FIFO delivery and task order remain equal."""

    consumer_source = "wait proc:2 received\nadd result received received\nhalt\n"
    producer_source = "set value 7\nsend proc:2 value\nhalt\n"
    uninterrupted_data = tmp_path / "multitask-uninterrupted.mtrj"
    uninterrupted_index = tmp_path / "multitask-uninterrupted.mtrj.idx"
    resumed_data = tmp_path / "multitask-resumed.mtrj"
    resumed_index = tmp_path / "multitask-resumed.mtrj.idx"
    checkpoint = tmp_path / "multitask.mcpu.json"

    with TrajectoryWriter(uninterrupted_data, uninterrupted_index) as writer:
        uninterrupted = HeadlessOS(trajectory=writer)
        consumer = uninterrupted.launch_source(consumer_source, "consumer")
        producer = uninterrupted.launch_source(producer_source, "producer")
        assert (consumer, producer) == (2, 3)
        prefix = uninterrupted.run(2)
        assert [(event.tick, event.pid, event.op, event.status_after) for event in prefix] == [
            (0, consumer, "WAIT", "blocked"),
            (1, producer, "SET", "runnable"),
        ]
        uninterrupted.save_checkpoint(checkpoint)
        uninterrupted.run(20)
        uninterrupted_snapshot = uninterrupted.snapshot()

    with TrajectoryWriter(resumed_data, resumed_index) as writer:
        prefix_os = HeadlessOS(trajectory=writer)
        prefix_os.launch_source(consumer_source, "consumer")
        prefix_os.launch_source(producer_source, "producer")
        assert prefix_os.run(2) == prefix

    with TrajectoryWriter.resume(resumed_data, resumed_index) as writer:
        restored = load_checkpoint(checkpoint)
        restored.vm.trajectory = writer
        restored.run(20)
        restored_snapshot = restored.snapshot()

    assert restored_snapshot == uninterrupted_snapshot
    assert _trajectory_payloads(uninterrupted_data, uninterrupted_index) == _trajectory_payloads(
        resumed_data, resumed_index
    )
    assert restored.environment.kernel.bus.pending() == 0
    assert restored.process(consumer).registers["result"] == 14


def test_checkpoint_preserves_subreaper_and_session_identity(tmp_path: Path) -> None:
    """Mathematics: `restore(save(S))` fixes `(session_id, group_id, subreaper)` at their pre-checkpoint values, so adoption and grouping survive persistence."""

    os = HeadlessOS()
    init = os.environment.init_pid
    assert init is not None
    leader = os.launch_source("wait inbox value\n", "session-leader", parent_pid=init)
    assert os.syscall(leader, "set_subreaper", enabled=True) is False
    assert os.syscall(leader, "setsid") == leader
    follower = os.launch_source("wait inbox value\n", "session-follower", parent_pid=leader)
    assert os.syscall(leader, "setpgid", target_pid=follower, group_id=follower) == follower

    checkpoint = tmp_path / "identity.mcpu.json"
    os.save_checkpoint(checkpoint)
    restored = HeadlessOS.restore_checkpoint(checkpoint)
    assert restored.process(leader).session_id == leader
    assert restored.process(leader).group_id == leader
    assert restored.process(leader).subreaper is True
    assert restored.process(follower).session_id == leader
    assert restored.process(follower).group_id == follower


def test_checkpoint_detects_tampering(tmp_path: Path) -> None:
    """Mathematics: changing state while retaining digest makes `SHA256(state) != digest`, which must be rejected."""

    os = HeadlessOS()
    path = tmp_path / "tampered.json"
    os.save_checkpoint(path)
    path.write_text(path.read_text(encoding="utf-8").replace("mailcpu-checkpoint-v1", "tampered"), encoding="utf-8")
    with pytest.raises(CheckpointError, match="unsupported checkpoint format"):
        load_checkpoint(path)


def test_checkpoint_publication_preserves_previous_file_on_replace_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    r"""Mathematics: failed publication leaves prior `C_old` intact because `replace(C_tmp, C)` is the sole commit point."""

    operating_system = HeadlessOS()
    path = tmp_path / "atomic.mcpu.json"
    operating_system.save_checkpoint(path)
    previous = path.read_bytes()

    def fail_replace(_source: Path, _destination: Path) -> None:
        """Mathematics: model an interruption before the atomic commit function `replace` returns."""

        raise OSError("simulated publication interruption")

    monkeypatch.setattr(checkpoint_module.os, "replace", fail_replace)
    with pytest.raises(OSError, match="publication interruption"):
        operating_system.save_checkpoint(path)

    assert path.read_bytes() == previous
    assert not list(tmp_path.glob(".atomic.mcpu.json.*.tmp"))


def test_snapshot_refuses_uncommitted_deferred_transition() -> None:
    r"""Mathematics: serialization is admitted only at a transition boundary, `pending_exec ∪ pending_fork = ∅`."""

    operating_system = HeadlessOS()
    operating_system._pending_fork[123] = 124

    with pytest.raises(ValueError, match="uncommitted"):
        operating_system.snapshot()


def test_vm_restore_rejects_orphan_memory_image() -> None:
    r"""Mathematics: VM correspondence requires `dom(M) = dom(T)` for memory images `M` and scheduler tasks `T`."""

    operating_system = HeadlessOS()
    pid = operating_system.launch_source("halt", "memory-owner")
    snapshot = operating_system.snapshot()
    del snapshot["vm"]["memories"][str(pid)]

    with pytest.raises(ValueError, match="one-to-one"):
        HeadlessOS.from_snapshot(snapshot)


def test_checkpoint_preserves_service_controller(tmp_path: Path) -> None:
    """Mathematics: service relation `S` survives persistence with desired state, PID, policy, and restart count."""

    os = HeadlessOS()
    os.install_source("/etc/services/waiter.mca", "wait inbox value\nhalt\n")
    os.services.register(ServiceSpec("waiter", "/etc/services/waiter.mca"))
    os.services.start("waiter")
    os.services.tick(1)
    path = tmp_path / "service.json"
    os.save_checkpoint(path)
    restored = HeadlessOS.restore_checkpoint(path)
    assert restored.services.status("waiter").state == "blocked"
    assert restored.services.status("waiter").pid == os.services.status("waiter").pid


def _structural_counter_law(x0: int = 0) -> Law:
    """Mathematics: define the modular progression x(t)=(x0+t) mod 97 as a known generator family."""
    return Law(
        family="int",
        params={"x0": x0, "step": 1, "mod": 97},
        order=1,
        verdict="GROUND",
    )


def test_headless_checkpoint_persists_structural_memory_and_shared_journal(tmp_path: Path) -> None:
    """Mathematics: restore preserves admitted structural revisions, cached reads, and the exact shared journal chain."""

    operating_system = HeadlessOS(
        structural_memory_admission_policy=lambda proposal: proposal.spec.domain == "integer-orbit"
    )
    proposal = operating_system.structural_memory.propose(
        "durable-counter",
        _structural_counter_law(),
        {0: 0, 1: 1, 2: 2, 3: 3},
        context={"tenant": "alpha"},
    )
    active = operating_system.structural_memory.admit(proposal.proposal_id, expected_revision=0)
    first = operating_system.structural_memory.read("durable-counter", 12)
    operating_system.structural_memory.read("durable-counter", 12)
    checkpoint = tmp_path / "structural-memory.mcpu.json"
    operating_system.save_checkpoint(checkpoint)
    journal_before = operating_system.environment.kernel.journal.snapshot()

    restored = HeadlessOS.restore_checkpoint(
        checkpoint,
        structural_memory_admission_policy=lambda candidate: candidate.spec.domain == "integer-orbit",
    )
    assert restored.structural_memory.active_version("durable-counter") == active
    assert restored.environment.kernel.journal.snapshot() == journal_before
    resumed = restored.structural_memory.read("durable-counter", 12)
    assert resumed.value == first.value
    assert resumed.receipt_id == first.receipt_id
    assert resumed.cache_hit is True
    assert restored.environment.kernel.journal.verify()

    next_law = _structural_counter_law(5)
    next_proposal = restored.structural_memory.propose(
        "durable-counter",
        next_law,
        {0: 5, 1: 6, 2: 7, 3: 8},
        context={"tenant": "alpha", "revision": 2},
    )
    next_active = restored.structural_memory.admit(next_proposal.proposal_id, expected_revision=1)
    assert next_active.spec.revision == 2
    assert restored.structural_memory.read("durable-counter", 0).value == 5


def test_restored_structural_memory_requires_host_policy_for_new_admissions(tmp_path: Path) -> None:
    """Mathematics: checkpoint restore preserves memory state but not executable authority policy."""

    operating_system = HeadlessOS(structural_memory_admission_policy=lambda proposal: True)
    proposal = operating_system.structural_memory.propose(
        "policy-boundary",
        _structural_counter_law(),
        {0: 0, 1: 1, 2: 2},
    )
    operating_system.structural_memory.admit(proposal.proposal_id, expected_revision=0)
    checkpoint = tmp_path / "policy-boundary.mcpu.json"
    operating_system.save_checkpoint(checkpoint)

    restored = HeadlessOS.restore_checkpoint(checkpoint)
    assert restored.structural_memory.read("policy-boundary", 9).value == 9
    next_law = _structural_counter_law(5)
    staged = restored.structural_memory.propose(
        "policy-boundary",
        next_law,
        {0: 5, 1: 6, 2: 7},
    )
    with pytest.raises(StructuralMemoryAuthorizationError, match="explicit"):
        restored.structural_memory.admit(staged.proposal_id, expected_revision=1)


def test_legacy_checkpoint_without_structural_memory_remains_readable() -> None:
    """Mathematics: accept an older OS projection without structural-memory fields only when its journal has no structural-memory events."""

    operating_system = HeadlessOS()
    snapshot = operating_system.snapshot()
    snapshot.pop("structural_memory")
    restored = HeadlessOS.from_snapshot(snapshot)
    assert restored.structural_memory.active_version("legacy") is None


def test_checkpoint_cannot_omit_structural_memory_state_when_journal_has_its_events() -> None:
    """Mathematics: reject a checkpoint projection that contains structural-memory journal events but omits their state relation."""

    operating_system = HeadlessOS(structural_memory_admission_policy=lambda proposal: True)
    proposal = operating_system.structural_memory.propose(
        "missing-state",
        _structural_counter_law(),
        {0: 0, 1: 1, 2: 2},
    )
    operating_system.structural_memory.admit(proposal.proposal_id, expected_revision=0)
    snapshot = operating_system.snapshot()
    snapshot.pop("structural_memory")

    with pytest.raises(StructuralMemoryError, match="no structural-memory registry state"):
        HeadlessOS.from_snapshot(snapshot)


def test_checkpoint_restore_rejects_structural_memory_journal_anchor_mismatch() -> None:
    """Mathematics: require the registry's saved (sequence,digest) anchor to equal the restored kernel event-chain tail."""

    operating_system = HeadlessOS(structural_memory_admission_policy=lambda proposal: True)
    proposal = operating_system.structural_memory.propose(
        "anchor-check",
        _structural_counter_law(),
        {0: 0, 1: 1, 2: 2},
    )
    operating_system.structural_memory.admit(proposal.proposal_id, expected_revision=0)
    snapshot = operating_system.snapshot()
    snapshot["structural_memory"]["journal_anchor"]["digest"] = "0" * 64

    with pytest.raises(StructuralMemoryError, match="journal anchor"):
        HeadlessOS.from_snapshot(snapshot)
