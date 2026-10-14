from __future__ import annotations

import hashlib
import json

import pytest

from mailcpu import (
    HeadlessOS,
    MailCPUVirtualMachine,
    QueueInterpreter,
    ReferenceInterpreter,
    VirtualMemoryError,
    MemoryQuotaExceeded,
    PageFault,
    SharedRegion,
    ResidentQuotaExceeded,
    VirtualMemory,
)
from mailcpu.kernel import KernelError
from mailcpu.model import Instruction, Op, Program


def test_reference_and_mailbox_interpreters_refuse_syscall() -> None:
    """Mathematics: with no OS authority behind them, `SYSCALL` leaves both pure backends' transition domain, so each refuses instead of fabricating a result."""

    program = Program((Instruction(Op.SYSCALL, ("result", "getpid")), Instruction(Op.HALT)))
    with pytest.raises(RuntimeError, match="SYSCALL requires an OS execution backend"):
        ReferenceInterpreter(program).run()
    with pytest.raises(RuntimeError, match="SYSCALL requires an OS execution backend"):
        QueueInterpreter(program).run()


def test_logical_time_advances_exactly_one_per_accepted_event() -> None:
    """Mathematics: `τ` is an integer counter raised by exactly one per accepted scheduler transition, so accepted-event ticks form a dense interval `0..n-1` independent of any host clock."""

    vm = MailCPUVirtualMachine()
    first = vm.spawn_program(Program((Instruction(Op.SET, ("x", 1)), Instruction(Op.HALT))), "tick-left")
    second = vm.spawn_program(Program((Instruction(Op.SET, ("y", 2)), Instruction(Op.HALT))), "tick-right")
    events = vm.run(20)
    assert [event.tick for event in events] == list(range(len(events)))
    assert vm.scheduler.tick == len(events)
    ticks = [
        record.payload["tick"]
        for record in vm.scheduler.journal.records()
        if record.kind == "scheduler.tick"
    ]
    assert ticks == list(range(len(events)))
    assert {event.pid for event in events} == {first, second}


def test_event_journal_is_a_sha256_hash_chain() -> None:
    """Mathematics: every appended event satisfies `H_n = SHA256(H_{n-1} || c_n)` over its canonical encoding, so a single altered record breaks every later digest."""

    operating_system = HeadlessOS()
    pid = operating_system.launch_source("halt\n", "journal-chain")
    operating_system.run(4)
    records = operating_system.environment.kernel.journal.records()
    assert records
    previous = "0" * 64
    for position, record in enumerate(records, start=1):
        assert record.sequence == position
        assert record.previous_digest == previous
        canonical = json.dumps(
            {
                "kind": record.kind,
                "payload": record.payload,
                "previous_digest": previous,
                "sequence": record.sequence,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        previous = hashlib.sha256(bytes.fromhex(previous) + canonical).hexdigest()
        assert record.digest == previous
    assert operating_system.environment.kernel.journal.verify()
    assert operating_system.process(pid).status == "exited"


def test_virtual_memory_cross_page_write_and_copy_on_write() -> None:
    """Mathematics: verify page-local writes preserve clone state, `clone(M)` sharing immutable blobs until divergence."""

    memory = VirtualMemory(page_size=8)
    memory.map(0, 16)
    memory.write(6, b"abcdefgh")
    clone = memory.clone()
    clone.write(7, b"Z")
    assert memory.read(6, 8) == b"abcdefgh"
    assert clone.read(6, 8) == b"aZcdefgh"


def test_virtual_memory_reports_typed_page_faults() -> None:
    """Mathematics: an absent mapping `p∉M` yields fault tuple `(address,p,access)` for both reads and writes."""

    memory = VirtualMemory(page_size=8)
    with pytest.raises(PageFault) as read_fault:
        memory.read(3, 1)
    assert (read_fault.value.address, read_fault.value.page_number, read_fault.value.access) == (3, 0, "read")

    with pytest.raises(PageFault) as write_fault:
        memory.write(9, b"x")
    assert (write_fault.value.address, write_fault.value.page_number, write_fault.value.access) == (9, 1, "write")


def test_virtual_memory_quota_and_mapping_failures_are_atomic() -> None:
    """Mathematics: failed allocation preserves `M` because `|M|+n>Q` and duplicate checks precede mutation."""

    memory = VirtualMemory(page_size=8, max_pages=2)
    memory.map(0, 8)
    with pytest.raises(MemoryQuotaExceeded):
        memory.map(8, 16)
    assert tuple(mapping.page_number for mapping in memory.mapped_pages()) == (0,)

    memory.map(8, 8)
    before = memory.mapped_pages()
    with pytest.raises(VirtualMemoryError):
        memory.map(8, 16)
    assert memory.mapped_pages() == before

    region = SharedRegion("mailbox", 16)
    with pytest.raises(VirtualMemoryError):
        memory.attach_shared(0, region)
    assert memory.mapped_pages() == before
    assert memory.snapshot()["shared_regions"] == {}


def test_demand_reservation_materializes_on_access_and_round_trips() -> None:
    """Mathematics: reserved `R` becomes resident `M` on first access, with `|M|+k≤Q` enforced before materialization."""

    memory = VirtualMemory(page_size=8, max_pages=3)
    memory.map(0, 8)
    memory.reserve(8, 16)
    assert tuple(item.page_number for item in memory.mapped_pages()) == (0,)
    assert tuple(item.page_number for item in memory.reserved_pages()) == (1, 2)
    assert memory.read(8, 16) == b"\x00" * 16
    assert len(memory.mapped_pages()) == 3
    assert memory.reserved_pages() == ()

    restored = VirtualMemory.from_snapshot(memory.snapshot())
    assert restored.read(0, 24) == b"\x00" * 24


def test_demand_reservation_preserves_failure_and_read_only_semantics() -> None:
    """Mathematics: a fault outside `R` and quota overflow leave `(M,R)` unchanged; read-only `R[p]` rejects writes."""

    memory = VirtualMemory(page_size=8, max_pages=1)
    memory.map(0, 8)
    memory.reserve(8, 8)
    before = memory.snapshot()
    with pytest.raises(MemoryQuotaExceeded):
        memory.read(8, 1)
    assert memory.snapshot() == before

    with pytest.raises(PageFault):
        memory.write(16, b"x")
    assert memory.snapshot() == before

    readonly = VirtualMemory(page_size=8)
    readonly.reserve(0, 8, writable=False)
    with pytest.raises(VirtualMemoryError):
        readonly.write(0, b"x")
    assert len(readonly.mapped_pages()) == 0
    assert readonly.read(0, 1) == b"\x00"
    assert readonly.mapped_pages()[0].writable is False


def test_memory_protection_transitions_are_atomic_and_process_local() -> None:
    """Mathematics: `mprotect(M,w)` changes only rights, and a missing page causes `M' = M` with typed protection fault."""

    memory = VirtualMemory(page_size=8)
    memory.map(0, 16)
    memory.write(0, b"ok")
    memory.protect(0, 16, writable=False)
    with pytest.raises(VirtualMemoryError):
        memory.write(0, b"!")
    memory.protect(0, 16, writable=True)
    assert memory.write(0, b"!") == 1

    before = memory.snapshot()
    with pytest.raises(PageFault):
        memory.protect(0, 24, writable=False)
    assert memory.snapshot() == before

    vm = MailCPUVirtualMachine()
    first = vm.spawn_program(Program((Instruction(Op.HALT),)), "first", page_size=8)
    second = vm.spawn_program(Program((Instruction(Op.HALT),)), "second", page_size=8)
    vm.create_shared_memory("rights", 8)
    vm.attach_shared_memory(first, "rights", 16, writable=True)
    vm.attach_shared_memory(second, "rights", 16, writable=True)
    vm.memories[first].protect(16, 8, writable=False)
    assert vm.memories[first].mapped_pages()[-1].writable is False
    assert vm.memories[second].mapped_pages()[-1].writable is True


def test_virtual_memory_first_fit_allocation_is_deterministic() -> None:
    """Mathematics: allocator returns least free run `min{p: [p,p+k)∩(M∪R)=∅}` and honors a free aligned hint."""

    memory = VirtualMemory(page_size=8)
    memory.map(0, 16)
    memory.reserve(24, 8)
    assert memory.allocate(8) == 16
    assert memory.allocate(8, hint=48) == 48
    assert memory.allocate(8, hint=24) == 32


def test_headless_mmap_can_allocate_without_a_virtual_address() -> None:
    """Mathematics: `mmap(length)` returns a deterministic free base and `mem_info` reports the new reservation."""

    operating_system = HeadlessOS()
    pid = operating_system.launch_source("halt\n", "allocator", max_pages=3)
    start = operating_system.syscall(pid, "mmap", length=4096)
    assert start == 8192
    assert operating_system.syscall(pid, "mem_info")["reserved_pages"] == 1
    assert operating_system.syscall(pid, "mem_write", address=start, data=b"allocated") == 9


def test_shared_memory_visibility_and_vm_checkpoint_identity() -> None:
    """Mathematics: shared writes satisfy `M_a[x]=M_b[x]` and snapshot restore preserves one region object across mappings."""

    vm = MailCPUVirtualMachine()
    first = vm.spawn_program(Program((Instruction(Op.HALT),)), "writer", page_size=8, max_pages=4)
    second = vm.spawn_program(Program((Instruction(Op.HALT),)), "reader", page_size=8, max_pages=4)
    vm.create_shared_memory("mailbox", 16)
    vm.attach_shared_memory(first, "mailbox", 16)
    vm.attach_shared_memory(second, "mailbox", 16, writable=False)

    vm.memories[first].write(17, b"mailcpu")
    assert vm.memories[second].read(17, 7) == b"mailcpu"
    with pytest.raises(VirtualMemoryError):
        vm.memories[second].write(17, b"!")

    restored = MailCPUVirtualMachine.from_snapshot(vm.snapshot())
    assert restored.memories[second].read(17, 7) == b"mailcpu"
    assert restored.memories[first]._shared_regions["mailbox"] is restored.shared_regions["mailbox"]


def test_vm_resident_budget_covers_spawn_faults_and_shared_attach() -> None:
    """Mathematics: the VM invariant `Σ_pid |M_pid|≤B` covers process admission, demand faults, and shared mappings."""

    demand_vm = MailCPUVirtualMachine(max_resident_pages=2)
    demand_pid = demand_vm.spawn_program(Program((Instruction(Op.HALT),)), "resident", page_size=8)
    demand_vm.memories[demand_pid].reserve(16, 8)
    before = demand_vm.memories[demand_pid].snapshot()
    with pytest.raises(ResidentQuotaExceeded):
        demand_vm.memories[demand_pid].read(16, 1)
    assert demand_vm.memories[demand_pid].snapshot() == before

    vm = MailCPUVirtualMachine(max_resident_pages=3)
    pid = vm.spawn_program(Program((Instruction(Op.HALT),)), "resident", page_size=8)
    vm.create_shared_memory("one-page", 8)
    vm.attach_shared_memory(pid, "one-page", 16)
    assert vm.resident_pages() == 3
    vm.create_shared_memory("over-budget", 8)
    with pytest.raises(ResidentQuotaExceeded):
        vm.attach_shared_memory(pid, "over-budget", 24)
    assert vm.resident_pages() == 3

    with pytest.raises(ResidentQuotaExceeded):
        vm.spawn_program(Program((Instruction(Op.HALT),)), "second", page_size=8)
    assert tuple(vm.memories) == (pid,)

    restored = MailCPUVirtualMachine.from_snapshot(vm.snapshot())
    assert restored.max_resident_pages == 3
    assert restored.resident_pages() == 3


def test_failed_quota_spawn_does_not_publish_process_state() -> None:
    """Mathematics: spawn is transactional at the admission boundary, so invalid `Q<initial_pages` leaves `P,T,M` unchanged."""

    vm = MailCPUVirtualMachine()
    with pytest.raises(MemoryQuotaExceeded):
        vm.spawn_program(Program((Instruction(Op.HALT),)), "oversized", page_size=8, max_pages=1)
    assert vm.memories == {}
    assert vm.scheduler.tasks == {}
    assert tuple(vm.environment.kernel.processes) == (vm.environment.init_pid,)


def test_headless_memory_syscalls_cover_private_and_shared_abi() -> None:
    """Mathematics: verify `mmap/read/write/munmap` and `shm` transitions are journaled, bounded, and capability-gated."""

    operating_system = HeadlessOS()
    writer = operating_system.launch_source("halt\n", "writer", max_pages=3)
    reader = operating_system.launch_source("halt\n", "reader", max_pages=3)

    assert operating_system.syscall(writer, "mmap", start=8192, length=4096) == 8192
    assert operating_system.syscall(writer, "mem_info")["reserved_pages"] == 1
    assert operating_system.syscall(writer, "mem_write", address=8192, data=b"private") == 7
    assert operating_system.syscall(writer, "mem_read", address=8192, size=7) == b"private"
    assert operating_system.syscall(writer, "mem_info")["mapped_pages"] == 3
    assert operating_system.syscall(writer, "mem_info")["resident_pages"] == 5
    assert operating_system.syscall(writer, "mprotect", start=8192, length=4096, writable=False) == 0
    with pytest.raises(VirtualMemoryError):
        operating_system.syscall(writer, "mem_write", address=8192, data=b"!")
    assert operating_system.syscall(writer, "mprotect", start=8192, length=4096, writable=True) == 0
    assert operating_system.syscall(writer, "munmap", start=8192, length=4096) == 0
    with pytest.raises(PageFault):
        operating_system.syscall(writer, "mem_read", address=8192, size=1)

    operating_system.syscall(writer, "shm_create", name="mailbox", size=4096)
    operating_system.syscall(writer, "shm_attach", name="mailbox", start=8192)
    operating_system.syscall(reader, "shm_attach", name="mailbox", start=8192, writable=False)
    operating_system.syscall(writer, "mem_write", address=8192, data=b"shared")
    assert operating_system.syscall(reader, "mem_read", address=8192, size=6) == b"shared"
    assert any(record.kind == "memory.page_fault" for record in operating_system.environment.kernel.journal.records())
    with pytest.raises(VirtualMemoryError):
        operating_system.syscall(reader, "mem_write", address=8192, data=b"!")

    limited = operating_system.launch_source("halt\n", "limited")
    operating_system.environment.kernel.processes[limited].capabilities = ()
    with pytest.raises(KernelError):
        operating_system.syscall(limited, "mem_info")
    assert operating_system.environment.kernel.journal.verify()


def test_memory_reclaim_evicts_private_pages_and_faults_back_losslessly(tmp_path) -> None:
    """Mathematics: `reclaim(M[p])=R[p]` lowers `|M|`, and `read(R[p])` restores the exact content hash under the resident budget."""

    operating_system = HeadlessOS(max_resident_pages=2)
    pid = operating_system.launch_source("halt\n", "reclaimable")
    assert operating_system.syscall(pid, "mem_write", address=0, data=b"persist") == 7
    assert operating_system.syscall(pid, "mem_reclaim", pages=(0,)) == (0,)
    info = operating_system.syscall(pid, "mem_info")
    assert info["mapped_pages"] == 1
    assert info["reserved_pages"] == 1
    assert info["resident_pages"] == 1

    checkpoint = tmp_path / "reclaimed.mcpu.json"
    operating_system.save_checkpoint(checkpoint)
    restored = HeadlessOS.restore_checkpoint(checkpoint)
    assert restored.syscall(pid, "mem_read", address=0, size=7) == b"persist"
    assert restored.syscall(pid, "mem_info")["resident_pages"] == 2
    assert any(record.kind == "memory.reclaim" for record in restored.environment.kernel.journal.records())


def test_read_into_preflight_preserves_file_cursor_when_memory_destination_is_invalid() -> None:
    """Mathematics: failed compound transfer satisfies `δ_read_into(S)=S` because memory preflight precedes destructive descriptor read."""

    operating_system = HeadlessOS()
    pid = operating_system.launch_source("halt\n", "atomic-transfer")
    operating_system.environment.kernel.fs.create_file("/home/input", b"abc")
    fd = operating_system.environment.kernel.syscall(pid, "open", path="/home/input", mode="r")
    with pytest.raises(PageFault):
        operating_system.syscall(pid, "read_into", fd=fd, address=8192, size=3)
    assert operating_system.environment.kernel.syscall(pid, "read", fd=fd, size=-1) == b"abc"


def test_round_robin_scheduler_routes_send_wait_over_bus() -> None:
    """Mathematics: verify producer/consumer composition `send(v); wait() -> received = v` under fair round-robin ticks."""

    vm = MailCPUVirtualMachine()
    consumer = Program(
        (
            Instruction(Op.WAIT, ("proc:2", "received")),
            Instruction(Op.ADD, ("result", "received", "received")),
            Instruction(Op.HALT),
        )
    )
    producer = Program(
        (
            Instruction(Op.SET, ("value", 7)),
            Instruction(Op.SEND, ("proc:2", "value")),
            Instruction(Op.HALT),
        )
    )
    second = vm.spawn_program(consumer, "consumer")
    first = vm.spawn_program(producer, "producer")
    assert (second, first) == (2, 3)
    events = vm.run(20)
    assert events
    assert vm.scheduler.tasks[second].status.value == "halted"
    assert vm.scheduler.tasks[second].backend.registers["result"] == 14
    assert vm.scheduler.bus.pending("proc:2") == 0


def test_vm_snapshot_contains_scheduler_memory_and_journal() -> None:
    """Mathematics: verify the composed snapshot projection contains every state factor needed for replay inspection."""

    vm = MailCPUVirtualMachine()
    pid = vm.spawn_program(Program((Instruction(Op.HALT),)), "idle")
    vm.run()
    snapshot = vm.snapshot()
    assert "environment" in snapshot
    assert "scheduler" in snapshot
    assert "memories" in snapshot
    assert snapshot["scheduler"]["tasks"][str(pid)]["halted"] is True
