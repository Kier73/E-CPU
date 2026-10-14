from __future__ import annotations

import pytest

from mailcpu import HeadlessOS, assemble
from mailcpu.fs import FsError
from mailcpu.kernel import KernelError, POLLIN


COUNTDOWN = """
set n 3
set one 1
set zero 0
set minus_one -1
loop:
compare positive n zero
branch positive decrement
halt
decrement:
add n n minus_one
branch one loop
"""


def test_headless_os_executes_source_from_virtual_filesystem() -> None:
    """Mathematics: verify the process orbit reaches `n = 0` and then the kernel terminal state `EXITED`."""

    os = HeadlessOS()
    path = os.install_source("/home/countdown.mca", COUNTDOWN)
    report = os.run_file(path)
    assert report.status == "exited"
    assert report.exit_code == 0
    assert report.registers["n"] == 0
    assert report.steps > 0
    assert os.shell("ps").exit_code == 0
    assert "countdown.mca" in os.shell("ps").stdout


def test_headless_os_preserves_blocked_process_state() -> None:
    """Mathematics: an empty `WAIT` queue satisfies `|Q_mailbox| = 0 => status = BLOCKED`, never a false halt."""

    os = HeadlessOS()
    report = os.run_source("wait inbox value\nhalt\n", name="waiter", max_ticks=4)
    assert report.status == "blocked"
    assert report.exit_code is None
    assert report.pc == 0


def test_tick_budget_exhaustion_is_never_reported_as_success() -> None:
    """Mathematics: `run(max_ticks)` truncates the orbit at `τ = max_ticks`, so an unfinished process stays `runnable` and an empty `WAIT` stays `blocked`; neither carries an exit code."""

    os = HeadlessOS()
    running = os.launch_source(COUNTDOWN, "budget-bounded")
    os.run(2)
    report = os.process(running)
    assert report.status == "runnable"
    assert report.exit_code is None

    waiting = os.run_source("wait inbox value\nhalt\n", name="budget-blocked", max_ticks=4)
    assert waiting.status == "blocked"
    assert waiting.exit_code is None
    assert waiting.pc == 0


def test_deadline_wait_wakes_exactly_once_and_cannot_be_reset() -> None:
    """Mathematics: a deadline wait is a one-shot transition `τ := τ_deadline`, so it fires once and further ticks cannot re-arm the same request."""

    os = HeadlessOS()
    init = os.environment.init_pid
    read_fd, _write_fd = os.syscall(init, "pipe")
    pid = os.launch_source(
        "\n".join(
            (
                f"SYSCALL ready poll_fd fd={read_fd} events={POLLIN} timeout=3",
                "SYSCALL code exit code=0",
            )
        ),
        name="deadline-waiter",
        parent_pid=init,
        inherit_fds=True,
    )
    os.run(2)
    assert os.process(pid).status == "blocked"
    assert os.vm.scheduler.tasks[pid].wait_request == {
        "kind": "fd",
        "fd": read_fd,
        "events": POLLIN,
        "deadline": 3,
    }

    os.run(20)
    complete = os.process(pid)
    assert complete.status == "exited"
    assert complete.registers["ready"] == 0
    advances = [
        record
        for record in os.environment.kernel.journal.records()
        if record.kind == "scheduler.time_advance"
    ]
    assert len(advances) == 1

    os.run(20)
    assert os.process(pid).status == "exited"
    assert len(
        [
            record
            for record in os.environment.kernel.journal.records()
            if record.kind == "scheduler.time_advance"
        ]
    ) == 1


def test_headless_shell_runs_virtual_source_and_reports_json() -> None:
    """Mathematics: verify shell composition `run(path) = report_to_json(run_file(path))` over an in-VM path."""

    os = HeadlessOS()
    os.install_source("/home/one.mca", "set result 41\nset one 1\nadd result result one\nhalt\n")
    result = os.shell("run /home/one.mca")
    assert result.exit_code == 0
    assert '"status": "exited"' in result.stdout
    assert '"result": 42' in result.stdout


def test_headless_process_report_exposes_virtual_cwd_after_relative_shell_use() -> None:
    """Mathematics: process projection preserves `cwd' = N(cwd/p)` after a virtual `chdir` transition."""

    os = HeadlessOS()
    pid = os.launch_source("halt\n", "cwd-task")
    assert os.shell("cd /home", pid).exit_code == 0
    assert os.process(pid).cwd == "/home"
    assert os.shell("pwd", pid).stdout == "/home\n"


def test_scheduled_program_can_invoke_typed_native_syscalls_and_exit() -> None:
    """Mathematics: scheduled `SYSCALL` applies `H(pid,name,A)`, writes its integer result, and `exit` maps to terminal state."""

    os = HeadlessOS()
    pid = os.launch_source(
        "SYSCALL identity getpid\n"
        "SYSCALL previous get_subreaper\n"
        "SYSCALL changed set_subreaper enabled=true\n"
        "SYSCALL code exit code=23\n",
        "syscaller",
    )
    os.run(20)
    report = os.process(pid)
    assert report.status == "exited"
    assert report.exit_code == 23
    assert report.registers["identity"] == pid
    assert report.registers["previous"] == 0
    assert report.registers["changed"] == 0
    assert report.subreaper is True


def test_scheduled_process_context_abi_packs_argv_environment_and_cwd_atomically() -> None:
    """Mathematics: `argv_into`/`environ_into`/`getcwd_into` realize `M[a:a+|B|]=B` only after `capacity≥|B|`, with `B` NUL-packed and deterministic."""

    os = HeadlessOS()
    pid = os.launch_source(
        "\n".join(
            (
                "SYSCALL argv_addr mmap length=4096",
                "SYSCALL env_addr mmap length=4096",
                "SYSCALL cwd_addr mmap length=4096",
                "SYSCALL fail_addr mmap length=4096",
                "SYSCALL sentinel mem_write address=$fail_addr data=hex:5858",
                "SYSCALL argv_need argv_size",
                "SYSCALL failed argv_into address=$fail_addr size=0",
                "SYSCALL failed_errno get_errno",
                "SYSCALL argv_written argv_into address=$argv_addr size=$argv_need",
                "SYSCALL env_need environ_size",
                "SYSCALL env_written environ_into address=$env_addr size=$env_need",
                "SYSCALL cwd_need getcwd_size",
                "SYSCALL cwd_written getcwd_into address=$cwd_addr size=$cwd_need",
                "SYSCALL code exit code=0",
            )
        ),
        name="context-abi",
        argv=("mailcpu", "--mode", "alpha beta"),
        environment={"B": "two", "A": "one"},
    )
    os.run(80)
    report = os.process(pid)
    assert report.status == "exited"
    assert report.registers["failed"] == -34
    assert report.registers["failed_errno"] == 34
    assert report.registers["argv_written"] == len(b"mailcpu\x00--mode\x00alpha beta\x00")
    assert report.registers["env_written"] == len(b"A=one\x00B=two\x00")
    assert report.registers["cwd_written"] == 2
    assert os.vm.memories[pid].read(report.registers["fail_addr"], 2) == b"XX"
    assert os.vm.memories[pid].read(report.registers["argv_addr"], report.registers["argv_written"]) == b"mailcpu\x00--mode\x00alpha beta\x00"
    assert os.vm.memories[pid].read(report.registers["env_addr"], report.registers["env_written"]) == b"A=one\x00B=two\x00"
    assert os.vm.memories[pid].read(report.registers["cwd_addr"], report.registers["cwd_written"]) == b"/\x00"
    assert any(record.kind == "memory.context_transfer" for record in os.environment.kernel.journal.records())


def test_process_context_abi_continues_through_checkpoint(tmp_path) -> None:
    """Mathematics: `restore(snapshot(S))` preserves the context-byte transition and its remaining program counter."""

    os = HeadlessOS()
    pid = os.launch_source(
        "SYSCALL address mmap length=4096\n"
        "SYSCALL needed argv_size\n"
        "SYSCALL copied argv_into address=$address size=$needed\n"
        "SYSCALL code exit code=0\n",
        name="context-checkpoint",
        argv=("checkpoint", "arg"),
    )
    os.run(2)
    checkpoint = tmp_path / "context.mcpu.json"
    os.save_checkpoint(checkpoint)
    restored = HeadlessOS.restore_checkpoint(checkpoint)
    restored.run(20)
    report = restored.process(pid)
    assert report.status == "exited"
    assert restored.vm.memories[pid].read(report.registers["address"], report.registers["copied"]) == b"checkpoint\x00arg\x00"


def test_scheduled_pty_open_into_commits_a_descriptor_pair_inside_process_memory() -> None:
    """Mathematics: `pty_open_into(a)` atomically realizes `M[a:a+8]=u32(master)||u32(slave)` and exits without leaking the pair."""

    os = HeadlessOS()
    pid = os.launch_source(
        "SYSCALL address mmap length=4096\n"
        "SYSCALL master pty_open_into address=$address\n"
        "SYSCALL code exit code=0\n",
        name="pty-userland",
    )
    os.run(20)
    report = os.process(pid)
    assert report.status == "exited"
    pair = os.vm.memories[pid].read(report.registers["address"], 8)
    master = int.from_bytes(pair[:4], "little", signed=True)
    slave = int.from_bytes(pair[4:], "little", signed=True)
    assert report.registers["master"] == master
    assert slave == master + 1
    assert not os.environment.kernel.devices.pty_pairs()
    assert any(record.kind == "memory.pty_transfer" for record in os.environment.kernel.journal.records())

    failed_pid = os.launch_source(
        "SYSCALL failed pty_open_into address=8192\n"
        "SYSCALL error get_errno\n"
        "SYSCALL code exit code=0\n",
        name="pty-failure",
    )
    os.run(20)
    failed = os.process(failed_pid)
    assert failed.registers["failed"] == -14
    assert failed.registers["error"] == 14
    assert not os.environment.kernel.devices.pty_pairs()


def test_pty_control_characters_deliver_typed_signals_to_foreground_groups() -> None:
    """Mathematics: terminal controls `ETX→INT`, `SUB→STOP`, and `FS→QUIT` apply exactly once to `G_fg` and never enter slave input."""

    os = HeadlessOS()
    init_pid = os.environment.init_pid
    assert init_pid is not None
    master, slave = os.environment.kernel.syscall(init_pid, "pty_open")

    interrupt_target = os.launch_source("WAIT hold value\n", "interrupt-target", group_id=42)
    os.environment.kernel.syscall(init_pid, "tcsetpgrp", fd=slave, group_id=42)
    assert os.environment.kernel.syscall(init_pid, "write", fd=master, data=b"\x03") == 1
    interrupted = os.process(interrupt_target)
    assert interrupted.status == "exited"
    assert interrupted.exit_code == 130

    stop_target = os.launch_source("WAIT hold value\n", "stop-target", group_id=43)
    os.environment.kernel.syscall(init_pid, "tcsetpgrp", fd=slave, group_id=43)
    assert os.environment.kernel.syscall(init_pid, "write", fd=master, data=b"\x1a") == 1
    assert os.process(stop_target).status == "stopped"
    assert os.signal(stop_target, "CONT").status == "runnable"

    quit_target = os.launch_source("WAIT hold value\n", "quit-target", group_id=44)
    os.environment.kernel.syscall(init_pid, "tcsetpgrp", fd=slave, group_id=44)
    assert os.environment.kernel.syscall(init_pid, "write", fd=master, data=b"\x1c") == 1
    quit_report = os.process(quit_target)
    assert quit_report.status == "exited"
    assert quit_report.exit_code == 131
    assert any(record.kind == "terminal.signal" for record in os.environment.kernel.journal.records())


def test_pty_hangup_and_sighup_bridge_survive_headless_checkpoint() -> None:
    """Mathematics: checkpoint preserves `h_slave=0`, and restored `master↓` atomically yields `h_slave=1` plus `SIGHUP(fg(T))`."""

    os = HeadlessOS()
    init = os.environment.init_pid
    assert init is not None
    master, slave = os.environment.kernel.syscall(init, "pty_open")
    child = os.launch_source("wait inbox value\n", "pty-hangup-child")
    assert os.syscall(init, "setpgid", target_pid=child, group_id=child) == child
    assert os.syscall(init, "tcsetpgrp", fd=slave, group_id=child) == 0
    restored = HeadlessOS.from_snapshot(os.snapshot())
    assert restored.environment.kernel.devices.peer_hungup("ptys0001") is False
    assert restored.environment.kernel.syscall(init, "close", fd=master) == 0
    assert restored.process(child).status == "exited"
    assert restored.process(child).exit_code == 129
    assert restored.environment.kernel.devices.peer_hungup("ptys0001") is True
    assert any(record.kind == "pty.hangup" for record in restored.environment.kernel.journal.records())
    assert restored.syscall(init, "tcsetpgrp", fd=slave, group_id=init) == 0
    assert restored.syscall(init, "close", fd=slave) == 0
    assert "ptym0001" not in restored.environment.kernel.devices.names()
    assert restored.environment.kernel.journal.verify()


def test_scheduled_syscall_failure_returns_negative_errno_and_can_be_observed() -> None:
    """Mathematics: failed scheduled syscall `e` yields `r=-κ(e)`, stores `errno=κ(e)`, and leaves the scheduler orbit alive."""

    os = HeadlessOS()
    report = os.run_source(
        "\n".join(
            (
                "SYSCALL r0 open path=/missing mode=r",
                "SYSCALL r1 get_errno",
                "SYSCALL r2 exit code=0",
            )
        ),
        name="errno-userland",
    )
    assert report.status == "exited"
    assert report.registers["r0"] == -2
    assert report.registers["r1"] == 2
    assert report.errno == 2
    assert any(
        record.kind == "syscall.error" and record.payload["errno"] == 2
        for record in os.environment.kernel.journal.records()
    )


def test_errno_survives_checkpoint_until_the_next_failure(tmp_path) -> None:
    """Mathematics: checkpoint preserves `errno_p=e`, and a successful syscall leaves `e` unchanged until a later failure overwrites it."""

    os = HeadlessOS()
    pid = os.launch_source(
        "SYSCALL r0 open path=/missing mode=r\nSYSCALL r1 getpid\nSYSCALL r2 exit code=0\n",
        name="errno-checkpoint",
    )
    os.run(1)
    assert os.process(pid).errno == 2
    checkpoint = tmp_path / "errno.mcpu.json"
    os.save_checkpoint(checkpoint)
    restored = HeadlessOS.restore_checkpoint(checkpoint)
    restored.run(10)
    report = restored.process(pid)
    assert report.status == "exited"
    assert report.errno == 2


def test_scheduled_waitpid_projects_child_reap_to_integer_abi() -> None:
    """Mathematics: `waitpid(c,WNOHANG)` projects `⊥↦0` and a reap record `{pid:c}` to integer `c`, while releasing child state."""

    os = HeadlessOS()
    parent = os.launch_source(
        "set zero 0\n"
        "set one 1\n"
        "loop:\n"
        "SYSCALL r0 waitpid child_pid=3 nohang=true\n"
        "compare done zero r0\n"
        "branch done done\n"
        "branch one loop\n"
        "done:\n"
        "SYSCALL r1 exit code=0\n",
        name="wait-parent",
    )
    child = os.launch_source("halt\n", name="wait-child", parent_pid=parent)
    assert child == 3
    os.run(10)
    report = os.process(parent)
    assert report.status == "exited"
    assert report.registers["r0"] == child
    with pytest.raises(KernelError, match="unknown pid"):
        os.process(child)


def test_scheduled_spawn_file_creates_virtual_child_without_host_launch() -> None:
    """Mathematics: `spawn_file(P,p)` inserts child `c` with `parent(c)=P` and returns `c` while preserving scheduler closure."""

    os = HeadlessOS()
    child_path = os.install_source("/bin/child.mca", "SYSCALL r0 exit code=7\n", mode=0o755)
    parent_pid = os.launch_source(
        f"SYSCALL r0 spawn_file path={child_path} name=spawned\nWAIT hold value\n",
        name="spawn-parent",
    )
    os.run(6)
    parent = os.process(parent_pid)
    child_pid = parent.registers["r0"]
    assert parent.status == "blocked"
    child = os.process(child_pid)
    assert child.name == "spawned"
    assert child.parent_pid == parent_pid
    assert child.status == "exited"
    assert child.exit_code == 7


def test_scheduled_exec_replaces_image_after_trap_without_old_program_continuing() -> None:
    """Mathematics: successful `exec(path)` commits `T_pid:=(P_new,0,0)` after the trap and makes the old continuation unreachable."""

    os = HeadlessOS()
    path = os.install_source(
        "/bin/replacement.mca",
        "SYSCALL r0 getpid\nSYSCALL r1 exit code=9\n",
        mode=0o755,
    )
    pid = os.launch_source(
        f"set stale 1\nSYSCALL r0 exec path={path} name=replaced\nSYSCALL r2 exit code=1\n",
        name="old-image",
    )
    os.run(20)
    report = os.process(pid)
    assert report.status == "exited"
    assert report.name == "replaced"
    assert report.exit_code == 9
    assert report.registers["r0"] == pid
    assert "r2" not in report.registers


def test_scheduled_exec_failure_leaves_old_image_intact() -> None:
    """Mathematics: failed image construction `assemble(source)=⊥` returns `-EINVAL` and preserves `(P_old,R_old,M_old)`."""

    os = HeadlessOS()
    path = os.install_source("/bin/broken.mca", "NOT_AN_INSTRUCTION\n", mode=0o755)
    report = os.run_source(
        f"SYSCALL r0 exec path={path} name=broken\nSYSCALL r1 getpid\nSYSCALL r2 exit code=0\n",
        name="old-image",
    )
    assert report.status == "exited"
    assert report.name == "old-image"
    assert report.registers["r0"] == -22
    assert report.registers["r1"] == report.pid
    assert report.exit_code == 0


def test_scheduled_fork_uses_cow_memory_and_distinct_parent_child_returns() -> None:
    """Mathematics: `fork` yields parent register `c`, child register `0`, and `M_parent⊥M_child` after divergent COW writes."""

    os = HeadlessOS()
    parent = os.launch_source(
        "\n".join(
            (
                "SYSCALL address mmap length=4096 writable=true",
                "SYSCALL initial mem_write address=$address data=hex:41",
                "SYSCALL child_pid fork",
                "compare parent zero child_pid",
                "branch parent parent_path",
                "SYSCALL child_write mem_write address=$address data=hex:43",
                "SYSCALL child_exit exit code=7",
                "parent_path:",
                "SYSCALL parent_write mem_write address=$address data=hex:50",
                "SYSCALL parent_exit exit code=9",
            )
        ),
        name="forker",
    )
    os.run(60)
    parent_report = os.process(parent)
    child_pid = parent_report.registers["child_pid"]
    child_report = os.process(child_pid)
    assert parent_report.status == "exited"
    assert child_report.status == "exited"
    assert parent_report.exit_code == 9
    assert child_report.exit_code == 7
    assert parent_report.registers["child_pid"] == child_pid
    assert child_report.registers["child_pid"] == 0
    address = parent_report.registers["address"]
    assert os.vm.memories[parent].read(address, 1) == b"P"
    assert os.vm.memories[child_pid].read(address, 1) == b"C"


def test_fork_inherits_pipe_descriptions_and_moves_bytes_through_memory_abi() -> None:
    """Mathematics: inherited aliases preserve `pipe_read(Q)`/`pipe_write(Q)` across `fork`, while `pipe_into` commits `(r,w)` atomically to user memory."""

    os = HeadlessOS()
    parent = os.launch_source(
        "\n".join(
            (
                "SYSCALL address mmap length=4096 writable=true",
                "set one 1",
                "SYSCALL read_fd pipe_into address=$address",
                "add write_fd read_fd one",
                "SYSCALL child_pid fork",
                "compare parent zero child_pid",
                "branch parent parent_path",
                "SYSCALL closed_child close fd=$write_fd",
                "SYSCALL received read_into fd=$read_fd address=$address size=5",
                "SYSCALL child_exit exit code=$received",
                "parent_path:",
                "SYSCALL closed_parent close fd=$read_fd",
                "SYSCALL staged mem_write address=$address data=hex:68656c6c6f",
                "SYSCALL written write_from fd=$write_fd address=$address size=5",
                "SYSCALL closed_writer close fd=$write_fd",
                "SYSCALL parent_exit exit code=0",
            )
        ),
        name="pipe-forker",
    )
    os.run(80)
    parent_report = os.process(parent)
    child_pid = parent_report.registers["child_pid"]
    child_report = os.process(child_pid)
    assert parent_report.status == "exited"
    assert child_report.status == "exited"
    assert child_report.exit_code == 5
    assert parent_report.registers["written"] == 5
    address = parent_report.registers["address"]
    assert os.vm.memories[parent].read(address, 5) == b"hello"
    assert os.vm.memories[child_pid].read(address, 5) == b"hello"
    assert not os.environment.kernel.pipes
    assert any(record.kind == "memory.pipe_transfer" for record in os.environment.kernel.journal.records())


def test_scheduled_read_into_blocks_on_driver_input_and_wakes_from_device_feed() -> None:
    """Mathematics: a console read preserves (pc,M) while Q_console=empty, then commits M[a:a+n]=B after feed(B)."""

    os = HeadlessOS()
    pid = os.launch_source(
        "\n".join(
            (
                "SYSCALL address mmap length=4096 writable=true",
                "SYSCALL count read_into fd=0 address=$address size=4",
                "SYSCALL code exit code=$count",
            )
        ),
        name="console-reader",
    )
    os.run(2)
    blocked = os.process(pid)
    assert blocked.status == "blocked"
    assert blocked.pc == 1
    os.environment.feed_device("console", b"ping\n")
    os.run(20)
    report = os.process(pid)
    assert report.status == "exited"
    assert report.exit_code == 4
    assert os.vm.memories[pid].read(report.registers["address"], 4) == b"ping"


def test_scheduled_standard_output_reaches_virtual_console_driver() -> None:
    """Mathematics: standard descriptor `1` realizes `write(1,M[a:a+n])=n` into the console driver's output trace."""

    os = HeadlessOS()
    pid = os.launch_source(
        "\n".join(
            (
                "SYSCALL address mmap length=4096 writable=true",
                "SYSCALL staged mem_write address=$address data=hex:6f6b",
                "SYSCALL written write_from fd=1 address=$address size=2",
                "SYSCALL code exit code=0",
            )
        ),
        name="console-writer",
    )
    os.run(20)
    assert os.process(pid).status == "exited"
    assert os.environment.kernel.devices.snapshot()["console"]["writes_hex"][-1] == "6f6b"


def test_program_syscall_handler_survives_checkpoint_continuation(tmp_path) -> None:
    """Mathematics: `run^k(restore(snapshot(S)))` preserves the native trap transition and terminal result."""

    os = HeadlessOS()
    pid = os.launch_source("SYSCALL identity getpid\nSYSCALL code exit code=7\n", "checkpoint-syscaller")
    os.run(1)
    checkpoint = tmp_path / "syscall.mcpu.json"
    os.save_checkpoint(checkpoint)
    restored = HeadlessOS.restore_checkpoint(checkpoint)
    restored.run(10)
    report = restored.process(pid)
    assert report.status == "exited"
    assert report.exit_code == 7
    assert report.registers["identity"] == pid


def test_program_byte_syscalls_move_memory_to_virtual_file_across_checkpoint(tmp_path) -> None:
    """Mathematics: `write_from(fd,M[a:a+n])` commits exactly the bytes staged by `mem_write` after checkpoint continuation."""

    os = HeadlessOS()
    pid = os.launch_source(
        "SYSCALL fd open path=/home/program-output mode=w create=true\n"
        "SYSCALL address mmap length=4096\n"
        "SYSCALL staged mem_write address=$address data=hex:6d61696c\n"
        "SYSCALL copied write_from fd=$fd address=$address size=4\n"
        "SYSCALL code exit code=0\n",
        "byte-userland",
    )
    os.run(3)
    checkpoint = tmp_path / "byte-userland.mcpu.json"
    os.save_checkpoint(checkpoint)
    restored = HeadlessOS.restore_checkpoint(checkpoint)
    restored.run(10)
    assert restored.environment.kernel.fs.read_file("/home/program-output") == b"mail"
    assert restored.process(pid).exit_code == 0
    assert any(
        record.kind == "memory.byte_transfer"
        for record in restored.environment.kernel.journal.records()
    )


def test_headless_control_plane_wakes_and_terminates_processes() -> None:
    """Mathematics: verify `WAIT` wake-up by input and explicit termination with a preserved exit code."""

    os = HeadlessOS()
    pid = os.spawn(assemble("wait inbox value\nhalt\n"), "waiter")
    assert os.run(1)[0].status_after == "blocked"
    assert os.inject(pid, "inbox", [41]).status == "runnable"
    assert os.run(3)[-1].status_after == "halted"
    assert os.process(pid).registers["value"] == 41

    other_pid = os.spawn(assemble("wait inbox value\nhalt\n"), "to-kill")
    os.run(1)
    assert os.shell(f"kill {other_pid} 9").exit_code == 0
    assert os.process(other_pid).status == "exited"
    assert os.process(other_pid).exit_code == 9


def test_headless_suspend_resume_is_an_explicit_scheduler_state() -> None:
    """Mathematics: suspension preserves `(pc, R)` while resume restores the runnable transition relation."""

    os = HeadlessOS()
    pid = os.launch_source("set result 41\nset one 1\nadd result result one\nhalt\n", "suspendable")
    stopped = os.suspend(pid)
    assert stopped.status == "stopped"
    assert os.run(10) == ()
    assert os.process(pid).pc == 0
    assert os.shell(f"cont {pid}").exit_code == 0
    os.run(10)
    assert os.process(pid).status == "exited"
    assert os.process(pid).registers["result"] == 42


def test_executable_loading_uses_kernel_descriptors() -> None:
    """Mathematics: executable launch must factor through the syscall composition `open; read; close`."""

    os = HeadlessOS()
    os.install_source("/home/executable.mca", "halt\n")
    os.launch_file("/home/executable.mca")
    kinds = [record.kind for record in os.environment.kernel.journal.records()]
    assert kinds.count("syscall.begin") >= 2
    os.install_source("/home/plain.txt", "halt\n", mode=0o644)
    with pytest.raises(FsError, match="not executable"):
        os.launch_file("/home/plain.txt")


def test_binary_mcpb_file_launches_through_the_same_virtual_loader() -> None:
    """Mathematics: `launch_file(MCPB(P)) = spawn(P)` after execute-mode descriptor admission and bytecode validation."""

    os = HeadlessOS()
    binary_path = os.install_binary(
        "/bin/native.mcp",
        assemble("SYSCALL identity getpid\nSYSCALL code exit code=7\n"),
    )
    pid = os.launch_file(binary_path, name="native-binary")
    os.run(20)
    report = os.process(pid)
    assert report.status == "exited"
    assert report.exit_code == 7
    assert report.registers["identity"] == pid


def test_scheduled_exec_replaces_with_native_binary_without_old_continuation() -> None:
    """Mathematics: successful binary replacement commits `T_pid := (decode(MCPB),0)` and makes the old post-trap instruction unreachable."""

    os = HeadlessOS()
    binary_path = os.install_binary(
        "/bin/native-replacement.mcp",
        assemble("SYSCALL identity getpid\nSYSCALL code exit code=11\n"),
    )
    pid = os.launch_source(
        f"SYSCALL result exec path={binary_path} name=native-replacement\nSYSCALL stale exit code=1\n",
        name="source-image",
    )
    os.run(20)
    report = os.process(pid)
    assert report.status == "exited"
    assert report.name == "native-replacement"
    assert report.exit_code == 11
    assert report.registers["identity"] == pid
    assert "stale" not in report.registers


def test_exec_replaces_image_preserves_process_identity_and_descriptors() -> None:
    """Mathematics: `execve` preserves `(pid,C,E,F,parent,group)` while replacing `(program,pc,R,M)` with a fresh image."""

    os = HeadlessOS(max_resident_pages=2)
    pid = os.launch_source("set old 1\nhalt\n", "old-image", argv=("old-image", "x"), environment={"KEEP": "yes"})
    fd = os.environment.kernel.syscall(pid, "open", path="/etc/hostname", mode="r")
    old_parent = os.process(pid).parent_pid
    old_group = os.process(pid).group_id
    os.install_source("/home/new-image.mca", "set result 41\nset one 1\nadd result result one\nhalt\n")

    report = os.exec_file(pid, "/home/new-image.mca", argv=("new-image", "arg"))
    assert report.pid == pid
    assert report.status == "runnable"
    assert report.name == "new-image.mca"
    assert report.argv == ("new-image", "arg")
    assert report.environment == {"KEEP": "yes"}
    assert report.parent_pid == old_parent
    assert report.group_id == old_group
    assert fd in os.environment.kernel.processes[pid].fds
    assert os.vm.resident_pages() == 2

    os.run(20)
    completed = os.process(pid)
    assert completed.status == "exited"
    assert completed.registers["result"] == 42
    assert "old" not in completed.registers


def test_exec_failure_does_not_replace_existing_image() -> None:
    """Mathematics: failed load/assembly satisfies `OS_after = OS_before` for process image and memory state."""

    os = HeadlessOS()
    pid = os.launch_source("set keep 7\nhalt\n", "stable")
    before_report = os.process(pid).to_dict()
    before_memory = os.vm.memories[pid].snapshot()
    os.install_source("/home/not-executable.txt", "halt\n", mode=0o644)
    with pytest.raises(FsError, match="not executable"):
        os.exec_file(pid, "/home/not-executable.txt")
    assert os.process(pid).to_dict() == before_report
    assert os.vm.memories[pid].snapshot() == before_memory


def test_waitpid_reaps_exited_child_and_releases_state() -> None:
    """Mathematics: `waitpid` returns each exited child once, then removes its `(P,T,M,F)` state and releases resources."""

    os = HeadlessOS(max_resident_pages=4)
    parent = os.environment.init_pid
    child = os.launch_source("halt\n", "child", parent_pid=parent)
    assert os.syscall(parent, "waitpid", child_pid=child, nohang=True) is None
    with pytest.raises(KernelError, match="wait would block"):
        os.syscall(parent, "waitpid", child_pid=child)

    os.run(10)
    result = os.syscall(parent, "waitpid", child_pid=child)
    assert result == {"pid": child, "exit_code": 0, "status": "exited"}
    assert child not in os.environment.kernel.processes
    assert child not in os.vm.scheduler.tasks
    assert child not in os.vm.memories
    with pytest.raises(KernelError, match="no child process"):
        os.syscall(parent, "waitpid", child_pid=child, nohang=True)
    assert os.vm.resident_pages() == 0


def test_waitpid_state_survives_checkpoint_before_reap(tmp_path) -> None:
    """Mathematics: checkpoint preserves zombie relation `Z={exited unreaped children}` so restored wait returns the same child."""

    os = HeadlessOS()
    parent = os.environment.init_pid
    child = os.launch_source("halt\n", "child")
    os.run(10)
    checkpoint = tmp_path / "zombie.mcpu.json"
    os.save_checkpoint(checkpoint)
    restored = HeadlessOS.restore_checkpoint(checkpoint)
    assert restored.syscall(parent, "waitpid", child_pid=child) == {
        "pid": child,
        "exit_code": 0,
        "status": "exited",
    }
    assert child not in restored.environment.kernel.processes


def test_exiting_parent_adopts_orphan_to_init_and_init_waits() -> None:
    """Mathematics: parent exit applies `parent(c):=init` for every live child, preserving one eventual wait owner."""

    os = HeadlessOS()
    init = os.environment.init_pid
    parent = os.launch_source("halt\n", "parent", parent_pid=init)
    orphan = os.launch_source("halt\n", "orphan", parent_pid=parent)
    os.terminate(parent, 17)
    assert os.environment.kernel._process(orphan).parent_pid == init
    assert any(record.kind == "process.adopt" for record in os.environment.kernel.journal.records())

    os.run(10)
    assert os.syscall(init, "waitpid", child_pid=parent) == {
        "pid": parent,
        "exit_code": 17,
        "status": "exited",
    }
    assert os.syscall(init, "waitpid", child_pid=orphan) == {
        "pid": orphan,
        "exit_code": 0,
        "status": "exited",
    }


def test_nearest_subreaper_owns_nested_orphans_and_survives_checkpoint(tmp_path) -> None:
    """Mathematics: adoption chooses the nearest live ancestor with `s=1`, and `snapshot/restore` preserves `s` and parent edges."""

    os = HeadlessOS()
    init = os.environment.init_pid
    supervisor = os.launch_source("wait inbox value\n", "supervisor", parent_pid=init)
    assert os.syscall(supervisor, "set_subreaper", enabled=True) is False
    assert os.syscall(supervisor, "get_subreaper") is True
    parent = os.launch_source("halt\n", "parent", parent_pid=supervisor)
    orphan = os.launch_source("halt\n", "orphan", parent_pid=parent)

    os.terminate(parent, 17)
    assert os.environment.kernel._process(orphan).parent_pid == supervisor
    assert os.process(supervisor).subreaper is True

    checkpoint = tmp_path / "subreaper.mcpu.json"
    os.save_checkpoint(checkpoint)
    restored = HeadlessOS.restore_checkpoint(checkpoint)
    assert restored.environment.kernel._process(orphan).parent_pid == supervisor
    assert restored.process(supervisor).subreaper is True

    os.terminate(orphan, 23)
    assert os.syscall(supervisor, "waitpid", child_pid=parent) == {
        "pid": parent,
        "exit_code": 17,
        "status": "exited",
    }
    assert os.syscall(supervisor, "waitpid", child_pid=orphan) == {
        "pid": orphan,
        "exit_code": 23,
        "status": "exited",
    }
