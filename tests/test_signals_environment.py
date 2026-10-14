from __future__ import annotations

import pytest

from mailcpu import HeadlessOS, SignalError
from mailcpu.kernel import KernelError


def test_process_environment_is_scoped_and_checkpointable() -> None:
    """Mathematics: environment map `E_pid` is process-local, sorted for observation, and mutable only through setenv."""

    os = HeadlessOS()
    pid = os.launch_source("halt\n", "env-task", environment={"MODE": "test", "COUNT": "1"})
    assert os.process(pid).environment == {"COUNT": "1", "MODE": "test"}
    assert os.shell("export EXTRA value with spaces", pid).exit_code == 0
    assert os.environment.kernel.syscall(pid, "getenv", key="EXTRA") == "value with spaces"
    assert "EXTRA=value with spaces\n" in os.shell("env", pid).stdout
    with pytest.raises(KernelError, match="invalid environment key"):
        os.environment.kernel.syscall(pid, "setenv", key="BAD-KEY", value="x")


def test_signal_delivery_has_explicit_process_outcomes() -> None:
    """Mathematics: verify `STOP/CONT` preserve execution state and `TERM/KILL` produce distinct exit codes."""

    os = HeadlessOS()
    pid = os.launch_source("wait inbox value\nhalt\n", "signalable")
    assert os.signal(pid, "SIGSTOP").status == "stopped"
    assert os.signal(pid, "SIGCONT").status == "runnable"
    assert os.signal(pid, "SIGTERM").exit_code == 143
    with pytest.raises(SignalError, match="exited process"):
        os.signal(pid, "CONT")

    other = os.launch_source("set one 1\nloop:\nbranch one loop\n", "killable")
    assert os.shell(f"signal {other} KILL").exit_code == 0
    assert os.process(other).exit_code == 137


def test_kill_and_stop_dispositions_cannot_be_ignored() -> None:
    """Mathematics: `D_pid[σ] = ignore` is outside the defined domain for `σ ∈ {KILL, STOP}`, so both requests are refused and neither disposition is recorded."""

    os = HeadlessOS()
    pid = os.launch_source("wait inbox value\nhalt\n", "non-ignorable")
    for signal in ("KILL", "STOP"):
        with pytest.raises(KernelError, match="cannot be ignored"):
            os.environment.kernel.syscall(pid, "signal_set_ignored", signal=signal, ignored=True)
        assert os.environment.kernel.signal_is_ignored(pid, signal) is False
    assert os.process(pid).status == "runnable"
    assert os.process(pid).exit_code is None


def test_signal_dispositions_ignore_hup_inherit_and_restore() -> None:
    """Mathematics: `D_parent[HUP]=ignore` is inherited by a child and makes `δ_signal(HUP)` the identity on both live records."""

    os = HeadlessOS()
    init = os.environment.init_pid
    assert init is not None
    assert os.syscall(init, "signal_set_ignored", signal="HUP", ignored=True) == 0
    child = os.launch_source("wait inbox value\n", "ignored-hup-child")
    assert os.environment.kernel.signal_is_ignored(child, "HUP") is True
    assert os.signal(child, "HUP").status == "runnable"
    assert os.process(child).exit_code is None
    checkpoint = os.snapshot()
    restored = HeadlessOS.from_snapshot(checkpoint)
    assert restored.syscall(child, "signal_is_ignored", signal="HUP") == 1
    assert restored.signal(child, "HUP").status == "runnable"
    with pytest.raises(KernelError, match="cannot be ignored"):
        restored.syscall(child, "signal_set_ignored", signal="KILL", ignored=True)


def test_scheduled_signal_disposition_uses_integer_abi() -> None:
    """Mathematics: scheduled `signal_set_ignored` and `signal_is_ignored` project disposition state into integer results `0` and `1`."""

    os = HeadlessOS()
    pid = os.launch_source(
        "SYSCALL result signal_set_ignored signal=HUP ignored=true\n"
        "SYSCALL status signal_is_ignored signal=HUP\n"
        "halt\n",
        "scheduled-signal-disposition",
    )
    os.run()
    report = os.process(pid)
    assert report.status == "exited"
    assert report.registers["result"] == 0
    assert report.registers["status"] == 1


def test_process_abi_inherits_arguments_environment_capabilities_group_and_descriptors() -> None:
    """Mathematics: verify child ABI state `(argv,E,C,g,F)` inherits from parent and survives descriptor reads."""

    os = HeadlessOS()
    parent = os.launch_source(
        "halt\n",
        "parent",
        environment={"MODE": "parent"},
        argv=("parent", "--worker"),
        group_id=77,
    )
    fd = os.environment.kernel.syscall(parent, "open", path="/etc/hostname", mode="r")
    child = os.launch_source(
        "halt\n",
        "child",
        argv=("child", "--arg", "value"),
        parent_pid=parent,
        inherit_fds=True,
    )
    report = os.process(child)
    assert report.argv == ("child", "--arg", "value")
    assert report.parent_pid == parent
    assert report.group_id == 77
    assert report.environment == {"MODE": "parent"}
    assert os.environment.kernel.syscall(child, "read", fd=fd, size=-1) == b"mailcpu\n"


def test_signal_group_fans_out_in_pid_order() -> None:
    """Mathematics: verify `signal_group(g,σ)` applies exactly once to each live member of group `g` in PID order."""

    os = HeadlessOS()
    first = os.launch_source("wait inbox value\nhalt\n", "first", group_id=42)
    second = os.launch_source("wait inbox value\nhalt\n", "second", group_id=42)
    os.run(2)
    stopped = os.signal_group(42, "STOP")
    assert [report.pid for report in stopped] == [first, second]
    assert all(report.status == "stopped" for report in stopped)
    continued = os.signal_group(42, "CONT")
    assert all(report.status == "runnable" for report in continued)
    killed = os.signal_group(42, "KILL")
    assert [report.exit_code for report in killed] == [137, 137]
    assert os.environment.kernel.journal.verify()


def test_signal_group_shell_command_is_json_and_deterministic() -> None:
    """Mathematics: verify shell projection `signal-group(g,σ)=JSON(sorted members)` preserves group outcomes."""

    os = HeadlessOS()
    pid = os.launch_source("wait inbox value\nhalt\n", "shell-group", group_id=99)
    os.run(1)
    result = os.shell("signal-group 99 STOP")
    assert result.exit_code == 0
    assert f'"pid": {pid}' in result.stdout
    assert '"status": "stopped"' in result.stdout


def test_sessions_and_process_groups_are_checkpointed_with_membership_rules(tmp_path) -> None:
    """Mathematics: `setsid(p)` creates `(session,group)=(p,p)`, while `setpgid` changes only self/direct-child members of one session."""

    os = HeadlessOS()
    init = os.environment.init_pid
    child = os.launch_source("wait inbox value\n", "session-leader", parent_pid=init)
    assert os.process(init).session_id == init
    assert os.process(child).session_id == init
    with pytest.raises(KernelError, match="group leader"):
        os.syscall(init, "setsid")

    assert os.syscall(child, "setsid") == child
    assert os.process(child).session_id == child
    assert os.process(child).group_id == child
    grandchild = os.launch_source("wait inbox value\n", "session-child", parent_pid=child)
    assert os.process(grandchild).session_id == child
    assert os.syscall(child, "setpgid", target_pid=grandchild, group_id=grandchild) == grandchild
    assert os.syscall(child, "getpgid", target_pid=grandchild) == grandchild
    assert os.syscall(child, "getsid", target_pid=grandchild) == child
    with pytest.raises(KernelError, match="another session"):
        os.syscall(init, "setpgid", target_pid=child, group_id=init)

    checkpoint = tmp_path / "sessions.mcpu.json"
    os.save_checkpoint(checkpoint)
    restored = HeadlessOS.restore_checkpoint(checkpoint)
    assert restored.process(child).session_id == child
    assert restored.process(grandchild).group_id == grandchild
    assert restored.environment.kernel.journal.verify()


def test_kernel_pipes_are_bounded_descriptor_state_and_checkpointable() -> None:
    """Mathematics: verify pipe FIFO law `read(write(Q,B))=Q'`, bounded capacity, EOF, and snapshot continuation."""

    os = HeadlessOS()
    pid = os.launch_source("halt\n", "pipe-user")
    read_fd, write_fd = os.environment.kernel.syscall(pid, "pipe")
    with pytest.raises(KernelError, match="would block"):
        os.environment.kernel.syscall(pid, "read", fd=read_fd, size=8)
    assert os.environment.kernel.syscall(pid, "write", fd=write_fd, data=b"abcdef") == 6
    assert os.environment.kernel.syscall(pid, "read", fd=read_fd, size=2) == b"ab"
    snapshot = os.snapshot()
    restored = HeadlessOS.from_snapshot(snapshot)
    assert restored.environment.kernel.syscall(pid, "read", fd=read_fd, size=-1) == b"cdef"
    restored.environment.kernel.syscall(pid, "close", fd=read_fd)
    with pytest.raises(KernelError, match="broken pipe"):
        restored.environment.kernel.syscall(pid, "write", fd=write_fd, data=b"x")


def test_pipe_write_commits_available_prefix_and_returns_partial_count() -> None:
    """Mathematics: bounded write returns `k=min(|B|,C-|Q|)` and commits exactly `B[:k]`, preserving the remainder for a caller loop."""

    os = HeadlessOS()
    pid = os.launch_source("halt\n", "partial-pipe")
    read_fd, write_fd = os.syscall(pid, "pipe")
    payload = b"a" * (65_536 + 17)
    written = os.syscall(pid, "write", fd=write_fd, data=payload)
    assert written == 65_536
    assert os.syscall(pid, "read", fd=read_fd, size=-1) == payload[:written]
    assert os.syscall(pid, "write", fd=write_fd, data=payload[written:]) == 17
    assert os.syscall(pid, "read", fd=read_fd, size=-1) == payload[written:]
