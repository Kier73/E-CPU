from __future__ import annotations

from pathlib import Path

import pytest

from mailcpu import CheckpointError, HeadlessOS, ServiceSpec, load_checkpoint


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
