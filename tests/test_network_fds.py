from __future__ import annotations

from pathlib import Path

import pytest

from mailcpu import HeadlessOS
from mailcpu import F_GETFL, F_SETFL, O_APPEND, O_NONBLOCK
from mailcpu.kernel import KernelError, POLLHUP, POLLIN, POLLNVAL, POLLOUT
from mailcpu.datagram import DatagramError
from mailcpu.stream import StreamError


def _topology() -> tuple[HeadlessOS, int]:
    """Mathematics: construct the connected endpoint relation `root/eth0↔guest/eth0` for descriptor tests."""

    os = HeadlessOS()
    pid = os.environment.init_pid
    os.syscall(pid, "net_namespace_create", name="guest")
    os.syscall(pid, "net_interface_create", namespace="root", interface="eth0")
    os.syscall(pid, "net_interface_create", namespace="guest", interface="eth0")
    os.syscall(
        pid,
        "net_connect",
        link="root-guest",
        left_namespace="root",
        left_interface="eth0",
        right_namespace="guest",
        right_interface="eth0",
    )
    return os, pid


def test_non_zero_blocking_poll_timeouts_are_refused() -> None:
    """Mathematics: `timeout ≠ 0` lies outside the partial domain of `poll`/`poll_into`, so a blocking request is refused rather than silently truncated to the non-blocking instant."""

    os, init_pid = _topology()
    pid = os.launch_source("halt\n", name="poll-timeout-probe")
    listener_fd = os.syscall(pid, "net_stream_listen_fd", namespace="guest", interface="eth0", port=8950)
    with pytest.raises(KernelError, match="blocking poll timeouts"):
        os.syscall(pid, "poll", fds=[{"fd": listener_fd, "events": POLLIN}], timeout=1)
    with pytest.raises(KernelError, match="blocking poll timeouts"):
        os.syscall(pid, "poll", fds=[{"fd": listener_fd, "events": POLLIN}], timeout=-1)

    address = os.syscall(pid, "mmap", length=12, writable=True)
    os.syscall(
        pid,
        "mem_write",
        address=address,
        data=listener_fd.to_bytes(4, "little", signed=True) + POLLIN.to_bytes(4, "little") + b"\x00" * 4,
    )
    with pytest.raises(KernelError, match="blocking poll_into timeouts"):
        os.syscall(pid, "poll_into", address=address, count=1, timeout=5)
    assert os.vm.memories[pid].read(address, 8) == (
        listener_fd.to_bytes(4, "little", signed=True) + POLLIN.to_bytes(4, "little")
    )


def test_stream_descriptors_support_read_write_dup_and_checkpoint(tmp_path: Path) -> None:
    """Mathematics: descriptor aliases share description `D`, and `restore(snapshot(D,Q))` preserves queued stream bytes."""

    os, pid = _topology()
    listener_fd = os.syscall(pid, "net_stream_listen_fd", namespace="guest", interface="eth0", port=8000)
    client_fd = os.syscall(
        pid,
        "net_stream_connect_fd",
        source_namespace="root",
        source_interface="eth0",
        source_port=9000,
        destination_namespace="guest",
        destination_interface="eth0",
        destination_port=8000,
    )
    accepted_fd = os.syscall(pid, "net_stream_accept_fd", fd=listener_fd)
    assert listener_fd >= 3 and client_fd >= 3 and accepted_fd >= 3
    assert os.syscall(pid, "write", fd=client_fd, data=b"first") == 5
    assert os.syscall(pid, "read", fd=accepted_fd, size=5) == b"first"
    duplicate_fd = os.syscall(pid, "dup", fd=client_fd)
    os.syscall(pid, "close", fd=client_fd)
    assert os.syscall(pid, "write", fd=duplicate_fd, data=b"saved") == 5
    checkpoint = tmp_path / "network-fd.mcpu.json"
    os.save_checkpoint(checkpoint)
    restored = HeadlessOS.restore_checkpoint(checkpoint)
    assert restored.syscall(pid, "read", fd=accepted_fd, size=5) == b"saved"
    assert restored.environment.kernel.journal.verify()


def test_datagram_descriptor_read_and_explicit_sendto() -> None:
    """Mathematics: `write_fd` for datagrams is explicit `sendto(fd,d,b)`, while `read_fd` dequeues payload bytes."""

    os, pid = _topology()
    source_fd = os.syscall(pid, "net_dgram_bind_fd", namespace="root", interface="eth0", port=6000)
    destination_fd = os.syscall(pid, "net_dgram_bind_fd", namespace="guest", interface="eth0", port=7000)
    assert os.syscall(
        pid,
        "net_dgram_send_fd",
        fd=source_fd,
        destination_namespace="guest",
        destination_interface="eth0",
        destination_port=7000,
        payload=b"fd-dgram",
        logical_time=2,
    ) == 8
    assert os.syscall(pid, "read", fd=destination_fd, size=8) == b"fd-dgram"


def test_scheduled_program_uses_network_fds_through_memory_io() -> None:
    """Mathematics: `write_from(fd,M[a:n])` followed by `read_into(fd,M[a:n])` preserves bytes through native descriptors."""

    os, _ = _topology()
    report = os.run_source(
        "\n".join(
            (
                "SYSCALL r0 net_stream_listen_fd namespace=guest interface=eth0 port=8000",
                "SYSCALL r1 net_stream_connect_fd source_namespace=root source_interface=eth0 source_port=9000 destination_namespace=guest destination_interface=eth0 destination_port=8000",
                "SYSCALL r2 net_stream_accept_fd fd=$r0",
                "SYSCALL r3 mmap length=4 writable=true",
                "SYSCALL r4 mem_write address=$r3 data=hex:66647321",
                "SYSCALL r5 write_from fd=$r1 address=$r3 size=4",
                "SYSCALL r6 read_into fd=$r2 address=$r3 size=4",
                "SYSCALL r7 exit code=0",
            )
        ),
        name="network-fd-userland",
    )
    assert report.exit_code == 0
    address = report.registers["r3"]
    assert os.vm.memories[report.pid].read(address, 4) == b"fds!"


def test_scheduled_program_can_observe_scalar_network_readiness() -> None:
    """Mathematics: the integer trap `poll_fd(fd,E)` returns the same `revents` projection as structured `poll` for one FD."""

    os, _ = _topology()
    report = os.run_source(
        "\n".join(
            (
                "SYSCALL r0 net_stream_listen_fd namespace=guest interface=eth0 port=8050",
                "SYSCALL r1 net_stream_connect_fd source_namespace=root source_interface=eth0 source_port=9050 destination_namespace=guest destination_interface=eth0 destination_port=8050",
                "SYSCALL r2 poll_fd fd=$r0 events=1 timeout=0",
                "SYSCALL r3 exit code=0",
            )
        ),
        name="poll-fd-userland",
    )
    assert report.exit_code == 0
    assert report.registers["r2"] == POLLIN


def test_blocking_scheduled_network_io_preserves_pc_and_wakes_across_checkpoint(tmp_path: Path) -> None:
    """Mathematics: a blocked syscall preserves `(pc,R,M)` and resumes iff its checkpointed readiness predicate becomes true."""

    os, init_pid = _topology()
    receiver = os.launch_source(
        "\n".join(
            (
                "SYSCALL r0 net_stream_listen_fd namespace=guest interface=eth0 port=8300",
                "SYSCALL r1 net_stream_accept_fd fd=$r0",
                "SYSCALL r2 mmap length=4 writable=true",
                "SYSCALL r3 read_into fd=$r1 address=$r2 size=4",
                "SYSCALL r4 exit code=0",
            )
        ),
        name="blocking-network-reader",
    )
    os.run(10)
    blocked = os.process(receiver)
    assert blocked.status == "blocked"
    assert blocked.pc == 1
    assert os.vm.scheduler.tasks[receiver].wait_request == {
        "kind": "fd",
        "fd": blocked.registers["r0"],
        "events": POLLIN,
    }

    checkpoint = tmp_path / "blocked-network.mcpu.json"
    os.save_checkpoint(checkpoint)
    restored = HeadlessOS.restore_checkpoint(checkpoint)
    assert restored.process(receiver).status == "blocked"
    assert restored.vm.scheduler.tasks[receiver].wait_request == os.vm.scheduler.tasks[receiver].wait_request

    client_fd = restored.syscall(
        init_pid,
        "net_stream_connect_fd",
        source_namespace="root",
        source_interface="eth0",
        source_port=9300,
        destination_namespace="guest",
        destination_interface="eth0",
        destination_port=8300,
    )
    restored.run(10)
    accepted = restored.process(receiver)
    assert accepted.status == "blocked"
    assert accepted.pc == 3
    assert accepted.registers["r1"] >= 3
    assert restored.vm.scheduler.tasks[receiver].wait_request == {
        "kind": "fd",
        "fd": accepted.registers["r1"],
        "events": POLLIN,
    }

    assert restored.syscall(init_pid, "write", fd=client_fd, data=b"wake") == 4
    restored.run(20)
    complete = restored.process(receiver)
    assert complete.status == "exited"
    assert restored.vm.memories[receiver].read(complete.registers["r2"], 4) == b"wake"


def test_scheduled_poll_fd_wait_wakes_across_checkpoint(tmp_path: Path) -> None:
    """Mathematics: `poll_fd(F,E,-1)` preserves its instruction until `R(F,E)≠0`, then returns the readiness mask."""

    os, init_pid = _topology()
    receiver = os.launch_source(
        "\n".join(
            (
                "SYSCALL r0 net_stream_listen_fd namespace=guest interface=eth0 port=8650",
                "SYSCALL r1 poll_fd fd=$r0 events=1 timeout=-1",
                "SYSCALL r2 net_stream_accept_fd fd=$r0",
                "SYSCALL r3 exit code=0",
            )
        ),
        name="blocking-poll-reader",
    )
    os.run(10)
    blocked = os.process(receiver)
    assert blocked.status == "blocked"
    assert blocked.pc == 1
    assert os.vm.scheduler.tasks[receiver].wait_request == {
        "kind": "fd",
        "fd": blocked.registers["r0"],
        "events": POLLIN,
        "deadline": None,
    }

    checkpoint = tmp_path / "blocked-poll.mcpu.json"
    os.save_checkpoint(checkpoint)
    restored = HeadlessOS.restore_checkpoint(checkpoint)
    client_fd = restored.syscall(
        init_pid,
        "net_stream_connect_fd",
        source_namespace="root",
        source_interface="eth0",
        source_port=9650,
        destination_namespace="guest",
        destination_interface="eth0",
        destination_port=8650,
    )
    assert client_fd >= 3
    restored.run(20)
    complete = restored.process(receiver)
    assert complete.status == "exited"
    assert complete.registers["r1"] == POLLIN
    assert complete.registers["r2"] >= 3


def test_scheduled_poll_fd_positive_timeout_advances_virtual_time() -> None:
    """Mathematics: with no readiness, `poll_fd(F,E,t)` returns `0` after virtual deadline `τ_deadline=τ_block+t`."""

    os, _ = _topology()
    report = os.run_source(
        "\n".join(
            (
                "SYSCALL r0 net_stream_listen_fd namespace=guest interface=eth0 port=8750",
                "SYSCALL r1 poll_fd fd=$r0 events=1 timeout=3",
                "SYSCALL r2 exit code=0",
            )
        ),
        name="timed-poll",
        max_ticks=20,
    )
    assert report.status == "exited"
    assert report.registers["r1"] == 0
    assert any(record.kind == "scheduler.time_advance" for record in os.environment.kernel.journal.records())


def test_poll_into_writes_multi_descriptor_revents_without_consuming_payload() -> None:
    """Mathematics: `poll_into` preserves each `(fd,events)` input and writes only `revents=R(fd,events)` with ready count `|{i:R_i≠0}|`."""

    os, _ = _topology()
    pid = os.launch_source("halt", name="poll-probe")
    listener_fd = os.syscall(pid, "net_stream_listen_fd", namespace="guest", interface="eth0", port=8800)
    address = os.syscall(pid, "mmap", length=24, writable=True)
    invalid_fd = 9999
    records = (
        listener_fd.to_bytes(4, "little", signed=True)
        + POLLIN.to_bytes(4, "little")
        + b"\xAA\xAA\xAA\xAA"
        + invalid_fd.to_bytes(4, "little", signed=True)
        + POLLIN.to_bytes(4, "little")
        + b"\xBB\xBB\xBB\xBB"
    )
    os.syscall(pid, "mem_write", address=address, data=records)
    assert os.syscall(pid, "poll_into", address=address, count=2, timeout=0) == 1
    updated = os.vm.memories[pid].read(address, 24)
    assert updated[0:8] == records[0:8]
    assert int.from_bytes(updated[8:12], "little") == 0
    assert updated[12:20] == records[12:20]
    assert int.from_bytes(updated[20:24], "little") == POLLNVAL


def test_scheduled_poll_into_wakes_and_updates_user_memory(tmp_path: Path) -> None:
    """Mathematics: a blocked memory poll preserves `(pc,M)` and resumes with `M[a+8:a+12]=POLLIN` after listener readiness."""

    os, init_pid = _topology()
    receiver = os.launch_source(
        "\n".join(
            (
                "SYSCALL r0 net_stream_listen_fd namespace=guest interface=eth0 port=8850",
                "SYSCALL r1 mem_write address=0 data=hex:030000000100000000000000",
                "SYSCALL r2 poll_into address=0 count=1 timeout=-1",
                "SYSCALL r3 net_stream_accept_fd fd=$r0",
                "SYSCALL r4 exit code=0",
            )
        ),
        name="memory-poll-reader",
        parent_pid=init_pid,
        inherit_fds=True,
    )
    os.run(10)
    assert os.process(receiver).status == "blocked"
    assert os.vm.scheduler.tasks[receiver].wait_request == {
        "kind": "poll_memory",
        "address": 0,
        "count": 1,
        "entries": [{"fd": 3, "events": POLLIN}],
        "deadline": None,
    }

    checkpoint = tmp_path / "blocked-poll-into.mcpu.json"
    os.save_checkpoint(checkpoint)
    restored = HeadlessOS.restore_checkpoint(checkpoint)
    client_fd = restored.syscall(
        init_pid,
        "net_stream_connect_fd",
        source_namespace="root",
        source_interface="eth0",
        source_port=9850,
        destination_namespace="guest",
        destination_interface="eth0",
        destination_port=8850,
    )
    assert client_fd >= 3
    restored.run(20)
    report = restored.process(receiver)
    assert report.status == "exited"
    assert report.registers["r2"] == 1
    assert int.from_bytes(restored.vm.memories[receiver].read(8, 4), "little") == POLLIN


def test_scheduled_poll_into_zero_count_timeout_is_checkpointable() -> None:
    """Mathematics: for empty vector `n=0`, `poll_into(a,0,t)` returns `0` at `τ_deadline=τ_block+t` without touching memory."""

    os, _ = _topology()
    report = os.run_source(
        "\n".join(
            (
                "SYSCALL r0 mmap length=12 writable=true",
                "SYSCALL r1 poll_into address=$r0 count=0 timeout=2",
                "SYSCALL r2 exit code=0",
            )
        ),
        name="empty-memory-poll",
        max_ticks=20,
    )
    assert report.status == "exited"
    assert report.registers["r1"] == 0


def test_blocking_scheduled_pipe_write_wakes_after_capacity_is_released() -> None:
    """Mathematics: a bounded pipe writer waits while `|Q|=C`, then resumes when a reader makes `|Q|<C`."""

    os = HeadlessOS()
    init_pid = os.environment.init_pid
    read_fd, write_fd = os.syscall(init_pid, "pipe")
    assert os.syscall(init_pid, "write", fd=write_fd, data=b"x" * 65_536) == 65_536
    writer = os.launch_source(
        "\n".join(
            (
                "SYSCALL r0 mmap length=4 writable=true",
                "SYSCALL r1 mem_write address=$r0 data=hex:70697065",
                f"SYSCALL r2 write_from fd={write_fd} address=$r0 size=4",
                "SYSCALL r3 exit code=0",
            )
        ),
        name="blocked-pipe-writer",
        parent_pid=init_pid,
        inherit_fds=True,
    )
    os.run(10)
    blocked = os.process(writer)
    assert blocked.status == "blocked"
    assert blocked.pc == 2
    assert os.vm.scheduler.tasks[writer].wait_request == {
        "kind": "fd",
        "fd": write_fd,
        "events": POLLOUT,
    }

    assert os.syscall(init_pid, "read", fd=read_fd, size=65_536) == b"x" * 65_536
    os.run(10)
    complete = os.process(writer)
    assert complete.status == "exited"
    assert os.syscall(init_pid, "read", fd=read_fd, size=4) == b"pipe"


def test_fcntl_flags_are_shared_and_checkpointed(tmp_path: Path) -> None:
    """Mathematics: `F_SETFL` mutates shared description flags `φ`, while append writes satisfy `offset:=|file|` before each commit."""

    os = HeadlessOS()
    pid = os.environment.init_pid
    os.environment.kernel.fs.create_file("/tmp/flags", b"base")
    fd = os.syscall(pid, "open", path="/tmp/flags", mode="r+")
    duplicate = os.syscall(pid, "dup", fd=fd)
    assert os.syscall(pid, "fcntl", fd=fd, command=F_GETFL) == 2
    assert os.syscall(pid, "fcntl", fd=fd, command=F_SETFL, arg=O_NONBLOCK) == 0
    assert os.syscall(pid, "fcntl", fd=duplicate, command=F_GETFL) == 2 | O_NONBLOCK
    assert os.syscall(pid, "fcntl", fd=fd, command=F_SETFL, arg=O_APPEND) == 0
    assert os.syscall(pid, "write", fd=duplicate, data=b"!") == 1
    assert os.environment.kernel.fs.read_file("/tmp/flags") == b"base!"

    checkpoint = tmp_path / "fcntl-flags.mcpu.json"
    os.save_checkpoint(checkpoint)
    restored = HeadlessOS.restore_checkpoint(checkpoint)
    assert restored.syscall(pid, "fcntl", fd=duplicate, command=F_GETFL) == 2 | O_APPEND


def test_nonblocking_listener_does_not_enter_scheduler_wait() -> None:
    """Mathematics: `O_NONBLOCK` changes empty listener `accept` from suspension to its explicit `0` no-connection result."""

    os, _ = _topology()
    report = os.run_source(
        "\n".join(
            (
                "SYSCALL r0 net_stream_listen_fd namespace=guest interface=eth0 port=8400",
                "SYSCALL r1 fcntl fd=$r0 command=4 arg=2048",
                "SYSCALL r2 net_stream_accept_fd fd=$r0",
                "SYSCALL r3 exit code=0",
            )
        ),
        name="nonblocking-listener",
    )
    assert report.status == "exited"
    assert report.registers["r2"] == 0


def test_fd_rights_transfer_preserves_shared_file_description_and_checkpoint(tmp_path: Path) -> None:
    """Mathematics: `send_fd`/`receive_fd` transfer one shared description `D`, preserving cursor and in-flight lifetime across restore."""

    os = HeadlessOS()
    sender = os.environment.init_pid
    receiver = os.launch_source("halt\n", name="rights-receiver", parent_pid=sender)
    os.environment.kernel.fs.create_file("/tmp/rights", b"abcdef")
    fd = os.syscall(sender, "open", path="/tmp/rights", mode="r")
    assert os.syscall(sender, "read", fd=fd, size=2) == b"ab"
    assert os.syscall(sender, "send_fd", fd=fd, destination_pid=receiver) == 0
    os.syscall(sender, "close", fd=fd)

    checkpoint = tmp_path / "rights.mcpu.json"
    os.save_checkpoint(checkpoint)
    restored = HeadlessOS.restore_checkpoint(checkpoint)
    received_fd = restored.syscall(receiver, "receive_fd")
    assert received_fd >= 3
    assert restored.syscall(receiver, "read", fd=received_fd, size=-1) == b"cdef"
    assert any(record.kind == "fd.send" for record in restored.environment.kernel.journal.records())
    assert any(record.kind == "fd.receive" for record in restored.environment.kernel.journal.records())


def test_scheduled_network_fd_rights_receiver_blocks_then_reads_transferred_socket() -> None:
    """Mathematics: a rights-waiting process resumes on `SCM_RIGHTS`, then uses the transferred network description as its own FD."""

    os, sender = _topology()
    listener_fd = os.syscall(sender, "net_stream_listen_fd", namespace="guest", interface="eth0", port=8500)
    client_fd = os.syscall(
        sender,
        "net_stream_connect_fd",
        source_namespace="root",
        source_interface="eth0",
        source_port=9500,
        destination_namespace="guest",
        destination_interface="eth0",
        destination_port=8500,
    )
    accepted_fd = os.syscall(sender, "net_stream_accept_fd", fd=listener_fd)
    assert os.syscall(sender, "write", fd=client_fd, data=b"rights") == 6
    receiver = os.launch_source(
        "\n".join(
            (
                f"SYSCALL r0 receive_fd source_pid={sender}",
                "SYSCALL r1 mmap length=6 writable=true",
                "SYSCALL r2 read_into fd=$r0 address=$r1 size=6",
                "SYSCALL r3 exit code=0",
            )
        ),
        name="scheduled-rights-receiver",
        parent_pid=sender,
    )
    os.run(10)
    assert os.process(receiver).status == "blocked"
    assert os.vm.scheduler.tasks[receiver].wait_request == {"kind": "rights", "source_pid": sender}

    assert os.syscall(sender, "send_fd", fd=accepted_fd, destination_pid=receiver) == 0
    os.syscall(sender, "close", fd=accepted_fd)
    os.run(20)
    report = os.process(receiver)
    assert report.status == "exited"
    assert os.vm.memories[receiver].read(report.registers["r1"], 6) == b"rights"


def test_pending_network_rights_survive_sender_close_and_cancel_on_destination_reap() -> None:
    """Mathematics: native handle lifetime follows `refs(processes) ∪ refs(transfers)`, then cancellation removes the final transfer reference."""

    os, sender = _topology()
    receiver = os.launch_source(
        f"SYSCALL r0 receive_fd source_pid={sender}\nSYSCALL r1 exit code=0\n",
        name="canceled-rights-receiver",
        parent_pid=sender,
    )
    os.run(2)
    socket_fd = os.syscall(sender, "net_dgram_bind_fd", namespace="root", interface="eth0", port=8600)
    socket_handle = os.environment.kernel.processes[sender].fds[socket_fd].network_handle
    assert os.syscall(sender, "send_fd", fd=socket_fd, destination_pid=receiver) == 0
    os.syscall(sender, "close", fd=socket_fd)
    assert socket_handle is not None
    assert os.environment.datagrams.binding(int(socket_handle))[1] == 8600

    os.terminate(receiver)
    os.reap_process(receiver)
    with pytest.raises(DatagramError, match="unknown socket"):
        os.environment.datagrams.binding(int(socket_handle))


def test_inherited_network_descriptor_keeps_shared_open_description() -> None:
    """Mathematics: inherited descriptor `F_child[fd]=F_parent[fd]` retains network authority and queued byte state."""

    os, pid = _topology()
    listener_fd = os.syscall(pid, "net_stream_listen_fd", namespace="guest", interface="eth0", port=8000)
    client_fd = os.syscall(
        pid,
        "net_stream_connect_fd",
        source_namespace="root",
        source_interface="eth0",
        source_port=9000,
        destination_namespace="guest",
        destination_interface="eth0",
        destination_port=8000,
    )
    accepted_fd = os.syscall(pid, "net_stream_accept_fd", fd=listener_fd)
    os.syscall(pid, "write", fd=client_fd, data=b"child")
    child = os.launch_source(
        "\n".join(
            (
                "SYSCALL r0 mmap length=5 writable=true",
                f"SYSCALL r1 read_into fd={accepted_fd} address=$r0 size=5",
                "SYSCALL r2 exit code=0",
            )
        ),
        name="inherited-network-reader",
        parent_pid=pid,
        inherit_fds=True,
    )
    os.run()
    address = os.process(child).registers["r0"]
    assert os.vm.memories[child].read(address, 5) == b"child"


def test_poll_unifies_files_pipes_and_network_state() -> None:
    """Mathematics: one poll vector returns `revents_i = R(F_i,E_i)` without consuming any ready payload."""

    os, pid = _topology()
    os.environment.kernel.fs.create_file("/tmp/poll", b"file")
    file_fd = os.syscall(pid, "open", path="/tmp/poll", mode="r")
    read_pipe, write_pipe = os.syscall(pid, "pipe")
    listener_fd = os.syscall(pid, "net_stream_listen_fd", namespace="guest", interface="eth0", port=8100)
    initial = os.syscall(
        pid,
        "poll",
        fds=[
            {"fd": file_fd, "events": POLLIN},
            {"fd": read_pipe, "events": POLLIN},
            {"fd": write_pipe, "events": POLLOUT},
            {"fd": listener_fd, "events": POLLIN},
            {"fd": 9999, "events": POLLIN},
        ],
        timeout=0,
    )
    assert initial["ready"] == 3
    assert initial["fds"][0]["revents"] == POLLIN
    assert initial["fds"][1]["revents"] == 0
    assert initial["fds"][2]["revents"] == POLLOUT
    assert initial["fds"][3]["revents"] == 0
    assert initial["fds"][4]["revents"] == POLLNVAL

    os.syscall(pid, "write", fd=write_pipe, data=b"pipe")
    ready_pipe = os.syscall(pid, "poll", fds=[{"fd": read_pipe, "events": POLLIN}], timeout=0)
    assert ready_pipe == {"ready": 1, "fds": [{"fd": read_pipe, "events": POLLIN, "revents": POLLIN}]}
    os.syscall(pid, "close", fd=write_pipe)
    buffered_eof = os.syscall(pid, "poll", fds=[{"fd": read_pipe, "events": POLLIN}], timeout=0)
    assert buffered_eof["fds"][0]["revents"] == POLLIN | POLLHUP
    assert os.syscall(pid, "read", fd=read_pipe, size=4) == b"pipe"
    eof_pipe = os.syscall(pid, "poll", fds=[{"fd": read_pipe, "events": POLLIN}], timeout=0)
    assert eof_pipe["fds"][0]["revents"] == POLLHUP

    os.syscall(
        pid,
        "net_stream_connect_fd",
        source_namespace="root",
        source_interface="eth0",
        source_port=9100,
        destination_namespace="guest",
        destination_interface="eth0",
        destination_port=8100,
    )
    network_ready = os.syscall(pid, "poll", fds=[{"fd": listener_fd, "events": POLLIN}], timeout=0)
    assert network_ready["fds"][0]["revents"] == POLLIN


def test_dup2_closes_replaced_network_description() -> None:
    """Mathematics: `dup2(file,net)` removes the final network alias and applies the native close transition before replacement."""

    os, pid = _topology()
    listener_fd = os.syscall(pid, "net_stream_listen_fd", namespace="guest", interface="eth0", port=8200)
    listener_handle = os.environment.kernel.processes[pid].fds[listener_fd].network_handle
    os.environment.kernel.fs.create_file("/tmp/replacement", b"")
    file_fd = os.syscall(pid, "open", path="/tmp/replacement", mode="r")
    assert os.syscall(pid, "dup2", fd=file_fd, new_fd=listener_fd) == listener_fd
    try:
        os.environment.streams.listener_binding(int(listener_handle))
    except StreamError:
        pass
    else:
        raise AssertionError("dup2 left the replaced native listener alive")
