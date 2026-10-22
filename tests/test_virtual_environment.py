from __future__ import annotations

import pytest

from mailcpu.bus import MailboxBus
from mailcpu.devices import DeviceBus
from mailcpu.environment import VirtualEnvironment
from mailcpu.fs import FsError, VirtualFileSystem
from mailcpu.kernel import Capability, FD_CLOEXEC, F_GETFD, F_SETFD, KernelError, POLLHUP, POLLIN, VirtualKernel


def test_content_addressed_filesystem_and_snapshot() -> None:
    """Mathematics: verify `read(write(F, x)) = x` and that distinct blobs have distinct SHA-256 addresses."""

    filesystem = VirtualFileSystem()
    filesystem.mkdir("/tmp")
    filesystem.create_file("/tmp/data", b"abc")
    assert filesystem.read_file("/tmp/data") == b"abc"
    filesystem.write_file("/tmp/data", b"XYZ", offset=1)
    assert filesystem.read_file("/tmp/data") == b"aXYZ"
    snapshot = filesystem.snapshot()
    assert snapshot["blobs"]
    with pytest.raises(FsError):
        filesystem.read_file("/tmp/missing")

    malformed = filesystem.snapshot()
    malformed["next_inode"] = 2
    with pytest.raises(FsError, match="collides"):
        VirtualFileSystem.from_snapshot(malformed)


def test_filesystem_rename_preserves_inode_identity_and_rejects_cycles() -> None:
    """Mathematics: rename preserves inode identity `id(new)=id(old)` while `new_parent∈descendants(old)` is forbidden."""

    filesystem = VirtualFileSystem()
    filesystem.mkdir("/tmp")
    filesystem.mkdir("/tmp/tree")
    filesystem.create_file("/tmp/tree/value", b"x")
    inode_id = filesystem.stat("/tmp/tree/value").inode_id
    filesystem.rename("/tmp/tree/value", "/tmp/value")
    assert filesystem.stat("/tmp/value").inode_id == inode_id
    with pytest.raises(FsError, match="own subtree"):
        filesystem.rename("/tmp/tree", "/tmp/tree/child")


def test_kernel_syscalls_capabilities_and_file_descriptors() -> None:
    """Mathematics: verify descriptor cursor law `o' = o + |read(o)|` and subtree capability enforcement."""

    kernel = VirtualKernel()
    kernel.fs.mkdir("/sandbox")
    pid = kernel.spawn(
        "worker",
        (Capability("/sandbox", frozenset({"read", "write"})),),
    )
    fd = kernel.syscall(pid, "open", path="/sandbox/file", mode="w", create=True)
    assert kernel.syscall(pid, "write", fd=fd, data=b"hello") == 5
    kernel.syscall(pid, "close", fd=fd)
    fd = kernel.syscall(pid, "open", path="/sandbox/file", mode="r")
    assert kernel.syscall(pid, "read", fd=fd, size=2) == b"he"
    assert kernel.syscall(pid, "read", fd=fd, size=-1) == b"llo"
    with pytest.raises(KernelError, match="permission denied"):
        kernel.syscall(pid, "open", path="/etc/secret", mode="r")


def test_empty_capability_tuple_is_not_promoted_to_root_and_create_requires_write() -> None:
    r"""Mathematics: `C=∅` grants no path rights, and namespace creation requires `write ∈ C`."""

    kernel = VirtualKernel()
    kernel.fs.mkdir("/sandbox")
    no_rights = kernel.spawn("closed", capabilities=())
    with pytest.raises(KernelError, match="permission denied"):
        kernel.syscall(no_rights, "open", path="/sandbox/new", mode="r", create=True)

    read_only = kernel.spawn(
        "reader",
        capabilities=(Capability("/sandbox", frozenset({"read"})),),
    )
    with pytest.raises(KernelError, match="permission denied"):
        kernel.syscall(read_only, "open", path="/sandbox/new", mode="r", create=True)


def test_relative_paths_seek_append_and_rename_preserve_open_handles() -> None:
    """Mathematics: `chdir` changes path base, `lseek` sets `o'`, append starts at `|file|`, and rename preserves open-handle access."""

    kernel = VirtualKernel()
    kernel.fs.mkdir("/sandbox")
    pid = kernel.spawn(
        "worker",
        (Capability("/sandbox", frozenset({"read", "write", "execute"})),),
    )
    kernel.syscall(pid, "chdir", path="/sandbox")
    fd = kernel.syscall(pid, "open", path="value", mode="w+", create=True)
    assert kernel.syscall(pid, "write", fd=fd, data=b"abc") == 3
    assert kernel.syscall(pid, "lseek", fd=fd, offset=0, whence="set") == 0
    assert kernel.syscall(pid, "read", fd=fd, size=-1) == b"abc"
    kernel.syscall(pid, "rename", old_path="value", new_path="renamed")
    assert kernel.syscall(pid, "lseek", fd=fd, offset=0, whence=0) == 0
    assert kernel.syscall(pid, "read", fd=fd, size=-1) == b"abc"
    kernel.syscall(pid, "close", fd=fd)
    append_fd = kernel.syscall(pid, "open", path="renamed", mode="a")
    kernel.syscall(pid, "write", fd=append_fd, data=b"!")
    kernel.syscall(pid, "close", fd=append_fd)
    assert kernel.fs.read_file("/sandbox/renamed") == b"abc!"
    with pytest.raises(KernelError, match="is a directory"):
        kernel.syscall(pid, "unlink", path=".")


def test_directory_rename_rewrites_open_descendant_paths_and_fstat() -> None:
    """Mathematics: directory rename maps every open descendant `old/x ↦ new/x`, while `fstat(fd)=stat(path(fd))`."""

    kernel = VirtualKernel()
    kernel.fs.mkdir("/sandbox")
    kernel.fs.mkdir("/sandbox/tree")
    kernel.fs.create_file("/sandbox/tree/value", b"x")
    pid = kernel.spawn(
        "worker",
        (Capability("/sandbox", frozenset({"read", "write", "execute"})),),
    )
    fd = kernel.syscall(pid, "open", path="/sandbox/tree/value", mode="r")
    before = kernel.syscall(pid, "fstat", fd=fd)
    kernel.syscall(pid, "rename", old_path="/sandbox/tree", new_path="/sandbox/moved")
    assert kernel.syscall(pid, "read", fd=fd, size=-1) == b"x"
    after = kernel.syscall(pid, "fstat", fd=fd)
    assert after.inode_id == before.inode_id
    assert kernel.fs.read_file("/sandbox/moved/value") == b"x"


def test_fstat_projects_pipe_and_device_descriptions() -> None:
    r"""Mathematics: `fstat` maps pipe/device descriptors to stable synthetic kinds instead of requiring filesystem inodes."""

    kernel = VirtualKernel()
    kernel.fs.mkdir("/dev")
    kernel.fs.create_file("/dev/null", b"")
    pid = kernel.spawn("fstat-user")
    read_fd, write_fd = kernel.syscall(pid, "pipe")
    kernel.syscall(pid, "write", fd=write_fd, data=b"pipe")

    pipe_stat = kernel.syscall(pid, "fstat", fd=read_fd)
    assert pipe_stat.kind == "pipe"
    assert pipe_stat.size == 4

    device_fd = kernel.syscall(pid, "open", path="/dev/null", mode="r")
    device_stat = kernel.syscall(pid, "fstat", fd=device_fd)
    assert device_stat.kind == "device"
    assert device_stat.size == 0


def test_kernel_restore_rejects_missing_process_details_instead_of_granting_root() -> None:
    r"""Mathematics: restore must preserve capability relation `C_pid`, never replace absent details with `C_pid={root}`."""

    kernel = VirtualKernel()
    pid = kernel.spawn("secured")
    snapshot = kernel.snapshot()
    del snapshot["process_details"]

    with pytest.raises(KernelError, match="missing process_details"):
        VirtualKernel.from_snapshot(snapshot)


def test_device_restore_rejects_asymmetric_pty_peer_state() -> None:
    r"""Mathematics: a PTY relation requires symmetric peer edges `peer(peer(e)) = e` and equal pair identities."""

    environment = VirtualEnvironment.bootstrap()
    environment.kernel.syscall(environment.init_pid, "pty_open")
    state = environment.kernel.devices.snapshot()
    state["ptym0001"]["peer_name"] = "ptys9999"

    with pytest.raises(ValueError, match="missing pty peer"):
        DeviceBus.from_snapshot(state)


def test_shell_cat_reports_binary_input_without_leaking_a_decode_exception() -> None:
    r"""Mathematics: shell command result is total over byte strings, so invalid UTF-8 maps to status `1` rather than an uncaught exception."""

    kernel = VirtualKernel()
    kernel.fs.mkdir("/tmp")
    kernel.fs.create_file("/tmp/binary", b"\xff")
    pid = kernel.spawn("shell")
    result = VirtualEnvironment(kernel, pid).run_command(("cat", "/tmp/binary"), pid=pid)
    assert result.exit_code == 1
    assert "binary or invalid UTF-8" in result.stderr


def test_dup_and_inherited_descriptors_share_open_description_across_checkpoint() -> None:
    """Mathematics: aliases satisfy `D(fd_1)=D(fd_2)`, therefore `offset(fd_1)=offset(fd_2)` and checkpoint preserves that equivalence class."""

    kernel = VirtualKernel()
    kernel.fs.mkdir("/sandbox")
    parent = kernel.spawn(
        "parent",
        (Capability("/sandbox", frozenset({"read", "write", "execute"})),),
    )
    fd = kernel.syscall(parent, "open", path="/sandbox/value", mode="w+", create=True)
    alias = kernel.syscall(parent, "dup", fd=fd)
    assert kernel.syscall(parent, "write", fd=fd, data=b"abc") == 3
    assert kernel.syscall(parent, "lseek", fd=alias, offset=0, whence=0) == 0
    assert kernel.syscall(parent, "read", fd=fd, size=3) == b"abc"
    child = kernel.spawn("child", parent_pid=parent, inherit_fds=True)
    restored = VirtualKernel.from_snapshot(kernel.snapshot())
    assert restored.syscall(child, "lseek", fd=alias, offset=0, whence=0) == 0
    assert restored.syscall(parent, "read", fd=fd, size=3) == b"abc"
    replacement = restored.syscall(parent, "dup2", fd=fd, new_fd=20)
    assert replacement == 20
    assert restored.syscall(parent, "close", fd=fd) == 0
    assert restored.syscall(parent, "lseek", fd=20, offset=0, whence=0) == 0
    assert restored.syscall(parent, "read", fd=alias, size=3) == b"abc"


def test_pipe_endpoint_transfer_keeps_pipe_alive_until_receipt() -> None:
    r"""Mathematics: an in-flight transfer is a live pipe endpoint, so closing the sender cannot delete `Q_pipe`."""

    kernel = VirtualKernel()
    parent = kernel.spawn("parent")
    child = kernel.spawn("child", parent_pid=parent)
    read_fd, write_fd = kernel.syscall(parent, "pipe")
    assert kernel.syscall(parent, "write", fd=write_fd, data=b"queued") == 6
    assert kernel.syscall(parent, "send_fd", fd=read_fd, destination_pid=child) == 0
    kernel.syscall(parent, "close", fd=read_fd)
    assert kernel.pipes

    received = kernel.syscall(child, "receive_fd")
    assert received >= 3
    assert kernel.syscall(child, "read", fd=received, size=6) == b"queued"


def test_bus_ordering_and_process_ipc() -> None:
    """Mathematics: verify FIFO order `receive(send(m1); send(m2)) = (m1, m2)` across process endpoints."""

    kernel = VirtualKernel(bus=MailboxBus())
    first = kernel.spawn("first")
    second = kernel.spawn("second")
    kernel.syscall(first, "send", destination=f"proc:{second}", payload={"n": 1})
    kernel.syscall(first, "send", destination=f"proc:{second}", payload={"n": 2})
    assert kernel.syscall(second, "receive").payload["n"] == 1
    assert kernel.syscall(second, "receive").payload["n"] == 2
    assert kernel.syscall(second, "receive") is None


def test_booted_environment_command_surface_and_journal() -> None:
    """Mathematics: verify the boot image supports a closed command trace and preserves a valid hash chain."""

    environment = VirtualEnvironment.bootstrap()
    results = environment.run_script(
        """
        mkdir /home/demo
        write /home/demo/message hello mailcpu
        cat /home/demo/message
        ls /home/demo
        ps
        """
    )
    assert [result.exit_code for result in results] == [0, 0, 0, 0, 0]
    assert results[2].stdout == "hello mailcpu"
    assert "message\n" == results[3].stdout
    assert environment.kernel.journal.verify()
    assert environment.snapshot()["init_pid"] == 1


def test_shell_relative_filesystem_workflow_is_virtual_and_checkpointable() -> None:
    """Mathematics: shell composition `mkdir;cd;write;mv;cat;rm` acts only on the virtual filesystem and preserves cwd state."""

    environment = VirtualEnvironment.bootstrap()
    results = environment.run_script(
        """
        mkdir /home/work
        cd /home/work
        write note hello relative world
        mv note renamed
        cat renamed
        pwd
        rm renamed
        """
    )
    assert [result.exit_code for result in results] == [0, 0, 0, 0, 0, 0, 0]
    assert results[4].stdout == "hello relative world"
    assert results[5].stdout == "/home/work\n"
    assert environment.kernel.syscall(environment.init_pid, "listdir", path=".") == ()
    assert environment.kernel.journal.verify()


def test_device_files_use_driver_state_for_descriptor_io_and_checkpoint() -> None:
    """Mathematics: /dev/d projects descriptor reads/writes onto driver state D[d], and restore preserves the driver trajectory."""

    environment = VirtualEnvironment.bootstrap()
    pid = environment.init_pid
    assert pid is not None
    fd = environment.kernel.syscall(pid, "open", path="/dev/console", mode="r+")
    environment.feed_device("console", b"input\n")
    assert environment.kernel.descriptor_readiness(pid, fd, 0x001) == 0x001
    assert environment.kernel.syscall(pid, "read", fd=fd, size=5) == b"input"
    assert environment.kernel.syscall(pid, "read", fd=fd, size=1) == b"\n"
    assert environment.kernel.syscall(pid, "write", fd=fd, data=b"out") == 3
    restored = VirtualEnvironment.from_snapshot(environment.snapshot())
    assert restored.kernel.devices.snapshot()["console"]["writes_hex"] == ["6f7574"]
    restored.feed_device("console", b"!\n")
    assert restored.kernel.syscall(pid, "read", fd=fd, size=1) == b"!"


def test_nonblocking_console_read_reports_would_block_while_null_remains_eof() -> None:
    """Mathematics: `O_NONBLOCK ∧ Q_console=∅ ⇒ -EAGAIN`, while `/dev/null` satisfies `read=EOF` immediately."""

    environment = VirtualEnvironment.bootstrap()
    pid = environment.init_pid
    assert pid is not None
    console = environment.kernel.syscall(pid, "open", path="/dev/console", mode="r")
    environment.kernel.syscall(pid, "fcntl", fd=console, command=4, arg=0x0800)
    with pytest.raises(KernelError, match="would block"):
        environment.kernel.syscall(pid, "read", fd=console, size=1)
    null = environment.kernel.syscall(pid, "open", path="/dev/null", mode="r")
    environment.kernel.syscall(pid, "fcntl", fd=null, command=4, arg=0x0800)
    assert environment.kernel.syscall(pid, "read", fd=null, size=1) == b""


def test_terminal_foreground_group_and_canonical_mode_survive_checkpoint() -> None:
    """Mathematics: terminal reads require `session(p)=s(T) ∧ group(p)=fg(T)`, and canonical readiness requires a newline in the input queue."""

    environment = VirtualEnvironment.bootstrap()
    init_pid = environment.init_pid
    assert init_pid is not None
    child = environment.kernel.spawn(
        "background-reader",
        parent_pid=init_pid,
        group_id=99,
        session_id=1,
    )
    with pytest.raises(KernelError, match="background process group"):
        environment.kernel.syscall(child, "read", fd=0, size=1)
    assert environment.kernel.syscall(init_pid, "tcgetpgrp", fd=0) == 1
    assert environment.kernel.syscall(init_pid, "tcsetpgrp", fd=0, group_id=99) == 0
    environment.feed_device("console", b"x\n")
    assert environment.kernel.syscall(child, "read", fd=0, size=1) == b"x"
    environment.kernel.syscall(init_pid, "tty_setmode", fd=0, canonical=False, echo=True)
    assert environment.kernel.syscall(init_pid, "tty_canonical", fd=0) == 0
    assert environment.kernel.syscall(init_pid, "tty_echo", fd=0) == 1
    restored = VirtualEnvironment.from_snapshot(environment.snapshot())
    assert restored.kernel.syscall(init_pid, "tcgetpgrp", fd=0) == 99
    assert restored.kernel.syscall(init_pid, "tty_canonical", fd=0) == 0


def test_canonical_terminal_editing_and_eof_survive_checkpoint() -> None:
    """Mathematics: canonical `VERASE` deletes one current-line byte, `VKILL` deletes the suffix, and `VEOF` exposes bytes then one EOF."""

    environment = VirtualEnvironment.bootstrap()
    pid = environment.init_pid
    assert pid is not None
    fd = environment.kernel.syscall(pid, "open", path="/dev/console", mode="r+")
    environment.kernel.syscall(pid, "tty_setmode", fd=fd, canonical=True, echo=True)
    environment.feed_device("console", b"abc\x7fX\n")
    assert environment.kernel.syscall(pid, "read", fd=fd, size=-1) == b"abX\n"
    environment.feed_device("console", b"bad\x15good\n")
    assert environment.kernel.syscall(pid, "read", fd=fd, size=-1) == b"good\n"
    environment.feed_device("console", b"partial\x04")
    checkpoint = environment.snapshot()
    restored = VirtualEnvironment.from_snapshot(checkpoint)
    assert restored.kernel.syscall(pid, "read", fd=fd, size=-1) == b"partial"
    assert restored.kernel.syscall(pid, "read", fd=fd, size=-1) == b""
    restored.kernel.syscall(pid, "tty_setmode", fd=fd, canonical=False, echo=False, isig=True)
    restored.feed_device("console", b"\x04")
    assert restored.kernel.syscall(pid, "read", fd=fd, size=1) == b"\x04"


def test_pty_master_slave_routes_bytes_and_restores_terminal_state() -> None:
    """Mathematics: PTY master writes satisfy `Q_slave:=Q_slave||B`, slave writes satisfy `Q_master:=Q_master||B`, and both queues checkpoint."""

    environment = VirtualEnvironment.bootstrap()
    pid = environment.init_pid
    assert pid is not None
    master, slave = environment.kernel.syscall(pid, "pty_open")
    assert environment.kernel.processes[pid].fds[master].path == "/dev/ptym0001"
    assert environment.kernel.processes[pid].fds[slave].path == "/dev/ptys0001"
    assert environment.kernel.syscall(pid, "write", fd=master, data=b"hello\n") == 6
    assert environment.kernel.syscall(pid, "read", fd=slave, size=-1) == b"hello\n"
    assert environment.kernel.syscall(pid, "write", fd=slave, data=b"output") == 6
    assert environment.kernel.syscall(pid, "read", fd=master, size=-1) == b"output"
    environment.kernel.syscall(pid, "tty_setmode", fd=slave, canonical=True, echo=True)
    environment.kernel.syscall(pid, "write", fd=master, data=b"echo\n")
    assert environment.kernel.syscall(pid, "read", fd=master, size=-1) == b"echo\n"
    assert environment.kernel.syscall(pid, "read", fd=slave, size=-1) == b"echo\n"
    restored = VirtualEnvironment.from_snapshot(environment.snapshot())
    assert restored.kernel.devices.snapshot()["ptys0001"]["echo"] is True
    restored.kernel.syscall(pid, "write", fd=slave, data=b"restored")
    assert restored.kernel.syscall(pid, "read", fd=master, size=-1) == b"restored"
    restored.kernel.syscall(pid, "close", fd=slave)
    restored.kernel.syscall(pid, "close", fd=master)
    assert "ptym0001" not in restored.kernel.devices.names()


def test_pty_master_close_hangs_up_foreground_group_and_exposes_slave_eof() -> None:
    """Mathematics: `master↓ ∧ slave↑` sets `HUP_slave=1`, emits one `SIGHUP` to `fg(T)`, and makes `read(slave)=b''` after buffered bytes drain."""

    environment = VirtualEnvironment.bootstrap()
    init = environment.init_pid
    assert init is not None
    master, slave = environment.kernel.syscall(init, "pty_open")
    child = environment.kernel.spawn("pty-session-child", parent_pid=init)
    assert environment.kernel.syscall(init, "setpgid", target_pid=child, group_id=child) == child
    assert environment.kernel.syscall(init, "tcsetpgrp", fd=slave, group_id=child) == 0
    assert environment.kernel.syscall(init, "write", fd=master, data=b"pending") == 7
    assert environment.kernel.syscall(init, "close", fd=master) == 0
    assert environment.kernel.processes[child].status.value == "exited"
    assert environment.kernel.processes[child].exit_code == 129
    assert environment.kernel.devices.peer_hungup("ptys0001") is True
    assert environment.kernel.syscall(init, "tcsetpgrp", fd=slave, group_id=init) == 0
    assert environment.kernel.descriptor_readiness(init, slave, POLLIN) == POLLIN | POLLHUP
    assert environment.kernel.syscall(init, "read", fd=slave, size=-1) == b"pending"
    assert environment.kernel.syscall(init, "read", fd=slave, size=-1) == b""
    with pytest.raises(KernelError, match="pty peer hung up"):
        environment.kernel.syscall(init, "write", fd=slave, data=b"closed")
    assert sum(record.kind == "pty.hangup" for record in environment.kernel.journal.records()) == 1
    environment.kernel.syscall(init, "close", fd=slave)
    assert "ptym0001" not in environment.kernel.devices.names()


def test_descriptor_local_close_on_exec_survives_checkpoint_and_dup_clears_alias_flag() -> None:
    """Mathematics: `exec` retains exactly unmarked descriptors, while `dup` creates a new alias with `FD_CLOEXEC=0`."""

    environment = VirtualEnvironment.bootstrap()
    pid = environment.init_pid
    assert pid is not None
    fd = environment.kernel.syscall(pid, "open", path="/etc/hostname", mode="r")
    alias = environment.kernel.syscall(pid, "dup", fd=fd)
    assert environment.kernel.syscall(pid, "fcntl", fd=fd, command=F_SETFD, arg=FD_CLOEXEC) == 0
    assert environment.kernel.syscall(pid, "fcntl", fd=fd, command=F_GETFD) == FD_CLOEXEC
    assert environment.kernel.syscall(pid, "fcntl", fd=alias, command=F_GETFD) == 0
    restored = VirtualEnvironment.from_snapshot(environment.snapshot())
    restored.kernel.exec_process(pid, "replacement", ("replacement",))
    assert fd not in restored.kernel.processes[pid].fds
    assert alias in restored.kernel.processes[pid].fds
    assert any(record.kind == "process.fd_close_on_exec" for record in restored.kernel.journal.records())
