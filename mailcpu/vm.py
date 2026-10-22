"""Composed MailCPU virtual machine: environment, memory images, scheduler, and bus."""

from __future__ import annotations

from typing import Any, Callable, Sequence

from .environment import VirtualEnvironment
from .memory import PageBacking, ResidentQuotaExceeded, SharedRegion, VirtualMemory
from .model import DEFAULT_MAX_TICKS, Program
from .observation import (
    ResolverObservation,
    SubstrateObservation,
    decode_substrate_observation,
)
from .scheduler import DeterministicScheduler, ScheduleEvent
from .trajectory import TrajectoryWriter


class MailCPUVirtualMachine:
    """A composed virtual machine with a Unix-shaped control plane and message-backed execution plane."""

    def __init__(
        self,
        environment: VirtualEnvironment | None = None,
        trajectory: TrajectoryWriter | None = None,
        max_resident_pages: int | None = None,
        page_backing: PageBacking | None = None,
    ) -> None:
        """Mathematics: compose `VM = (environment.kernel, scheduler, memory_map, page_backing)` over one shared bus and journal."""

        if max_resident_pages is not None and max_resident_pages <= 0:
            raise ValueError("max_resident_pages must be positive when provided")
        self.environment = environment or VirtualEnvironment.bootstrap()
        self.trajectory = trajectory
        self.scheduler = DeterministicScheduler(
            bus=self.environment.kernel.bus,
            journal=self.environment.kernel.journal,
            syscall_handler=self._dispatch_program_syscall,
        )
        self.memories: dict[int, VirtualMemory] = {}
        self.shared_regions: dict[str, SharedRegion] = {}
        self.max_resident_pages = max_resident_pages
        self.page_backing = page_backing
        self.host_syscall_handler: Callable[[int, str, dict[str, Any]], Any] | None = None
        self._resolver_observation_receipts: dict[tuple[int, str, int], tuple[Any, ...]] = {}

    def create_shared_memory(self, name: str, size: int) -> SharedRegion:
        """Mathematics: extend shared map `S := S[name↦region]` with zero-filled region of byte cardinality `size`."""

        if name in self.shared_regions:
            raise ValueError(f"shared memory already exists: {name}")
        region = SharedRegion(name, size)
        self.shared_regions[name] = region
        self.environment.kernel.journal.append(
            "memory.shared.create",
            {"name": name, "size": size},
        )
        return region

    def attach_shared_memory(self, pid: int, name: str, start: int, writable: bool = True) -> None:
        """Mathematics: add shared mapping `M_pid[start/P+j] := S[name][j]` for every page `j`."""

        try:
            region = self.shared_regions[name]
            memory = self.memories[pid]
        except KeyError as exc:
            raise ValueError(f"unknown shared memory or process: {name}, {pid}") from exc
        self._admit_resident_pages(region.size // memory.page_size)
        memory.attach_shared(start, region, writable)
        self.environment.kernel.journal.append(
            "memory.shared.attach",
            {"pid": pid, "name": name, "start": start, "writable": writable},
        )

    def spawn_program(
        self,
        program: Program,
        name: str,
        initial_registers: dict[str, int] | None = None,
        environment: dict[str, str] | None = None,
        argv: Sequence[str] = (),
        parent_pid: int | None = None,
        group_id: int | None = None,
        inherit_fds: bool = False,
        page_size: int = 4096,
        max_pages: int | None = None,
    ) -> int:
        """Mathematics: create ABI process `P`, scheduler task `T`, and private memory image `M_pid` as one spawn transition."""

        self._admit_resident_pages(2)
        memory = VirtualMemory(page_size, max_pages, self._admit_resident_pages, self.page_backing)
        memory.map(0, page_size * 2)
        pid = self.environment.kernel.spawn(
            name,
            environment=environment,
            argv=argv,
            parent_pid=parent_pid,
            group_id=group_id,
            inherit_fds=inherit_fds,
        )
        self.scheduler.add(program, name, initial_registers, pid=pid)
        self.memories[pid] = memory
        return pid

    def run(self, max_ticks: int = DEFAULT_MAX_TICKS) -> tuple[ScheduleEvent, ...]:
        """Mathematics: execute the scheduler orbit for at most `max_ticks` logical transitions."""

        events = self.scheduler.run(max_ticks)
        if self.trajectory is not None:
            for event in events:
                self.trajectory.append(
                    event.tick,
                    {
                        "kind": "scheduler.tick",
                        "step": event.tick,
                        "pid": event.pid,
                        "name": event.name,
                        "pc_before": event.pc_before,
                        "op": event.op,
                        "args": list(event.args),
                        "pc_after": event.pc_after,
                        "status_after": event.status_after,
                        "registers": [list(item) for item in event.registers],
                        "output_delta": [list(item) for item in event.output_delta],
                    },
                )
            self.trajectory.flush()
        return events

    def apply_substrate_observation(
        self,
        pid: int,
        observation: SubstrateObservation,
        sequence: int,
        register_prefix: str = "substrate",
    ) -> bool:
        """Mathematics: apply idempotent external transition `R[p,*] := π(O)` once per receipt key `(pid,source,sequence)`."""

        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence <= 0:
            raise ValueError("observation sequence must be a positive integer")
        try:
            task = self.scheduler.tasks[pid]
        except KeyError as exc:
            raise ValueError(f"unknown observation target pid: {pid}") from exc
        payload = observation.to_payload()
        receipt_key = (pid, observation.source, sequence)
        previous = self._resolver_observation_receipts.get(receipt_key)
        if previous is not None:
            if previous != payload:
                raise ValueError("observation receipt sequence conflicts with prior payload")
            return False
        for register, value in observation.register_values(register_prefix).items():
            task.backend.write_register(register, value)
        self._resolver_observation_receipts[receipt_key] = payload
        self.scheduler.system_epoch = self.scheduler.system_epoch.advance_event()
        journal_payload = {
            "pid": pid,
            "source": observation.source,
            "sequence": sequence,
            "kind": observation.kind,
            "register_values": observation.register_values(register_prefix),
        }
        if isinstance(observation, ResolverObservation):
            journal_payload.update(
                {
                    "domain": observation.domain,
                    "record_type": observation.record_type,
                    "logical_time": observation.logical_time,
                    "status": observation.status,
                    "hit": observation.hit,
                    "ttl": observation.ttl,
                    "value": observation.value,
                }
            )
        self.environment.kernel.journal.append(
            f"substrate.{observation.kind}_observation",
            journal_payload,
        )
        return True

    def apply_resolver_observation(
        self,
        pid: int,
        observation: ResolverObservation,
        sequence: int,
        register_prefix: str = "resolver",
    ) -> bool:
        """Mathematics: preserve resolver API as the specialization `apply_resolver(O)=apply_substrate(O)` for `kind(O)=resolver`."""

        if observation.kind != "resolver":
            raise ValueError("resolver application requires a resolver observation")
        return self.apply_substrate_observation(pid, observation, sequence, register_prefix)

    def _dispatch_program_syscall(self, pid: int, name: str, arguments: dict[str, Any]) -> int:
        """Mathematics: compose program trap `H(pid,name,A)=int(G(pid,name,A))`, where `G` is the bound OS handler or kernel syscall map."""

        result = (
            self.host_syscall_handler(pid, name, arguments)
            if self.host_syscall_handler is not None
            else self.environment.kernel.syscall(pid, name, **arguments)
        )
        if isinstance(result, bool):
            return int(result)
        if not isinstance(result, int):
            raise RuntimeError(f"program syscall {name} returned non-integer result")
        return result

    def exec_program(self, pid: int, program: Program, name: str | None = None) -> None:
        """Mathematics: atomically replace task code and private memory while preserving PID and VM-wide resident invariant."""

        try:
            old_memory = self.memories[pid]
        except KeyError as exc:
            raise ValueError(f"unknown process memory: {pid}") from exc
        old_resident = len(old_memory.mapped_pages())
        new_resident = 2
        self._admit_replacement(old_resident, new_resident)
        replacement = VirtualMemory(
            old_memory.page_size,
            old_memory.max_pages,
            self._admit_resident_pages,
            self.page_backing,
        )
        replacement.map(0, old_memory.page_size * 2)
        self.scheduler.exec(pid, program, name)
        self.memories[pid] = replacement

    def fork_program(
        self,
        parent_pid: int,
        child_pid: int,
        child_registers: dict[str, int],
        child_pc: int,
        child_steps: int,
    ) -> int:
        """Mathematics: commit `M_child=clone(M_parent)` and `T_child=fork(T_parent)` after admitting `|mapped(M_parent)|` shared COW mappings."""

        try:
            parent_memory = self.memories[parent_pid]
            parent_task = self.scheduler.tasks[parent_pid]
            parent_process = self.environment.kernel._process(parent_pid)
        except KeyError as exc:
            raise ValueError(f"unknown fork parent: {parent_pid}") from exc
        additional_pages = len(parent_memory.mapped_pages())
        self._admit_resident_pages(additional_pages)
        child_memory = parent_memory.clone()
        actual_pid = self.environment.kernel.spawn(
            parent_process.name,
            environment=dict(parent_process.environment),
            argv=parent_process.argv,
            parent_pid=parent_pid,
            group_id=parent_process.group_id,
            session_id=parent_process.session_id,
            inherit_fds=True,
            subreaper=parent_process.subreaper,
        )
        if actual_pid != child_pid:
            raise ValueError(f"fork PID reservation changed: expected {child_pid}, got {actual_pid}")
        self.scheduler.fork_task(
            parent_pid,
            actual_pid,
            child_registers,
            child_pc,
            child_steps,
        )
        self.memories[actual_pid] = child_memory
        self.environment.kernel._process(actual_pid).errno = parent_process.errno
        return actual_pid

    def reap_process(self, pid: int) -> None:
        """Mathematics: remove exited process state `T[pid],M[pid]` after parent wait, releasing its resident mappings."""

        if pid not in self.memories:
            raise ValueError(f"unknown process memory: {pid}")
        self.scheduler.reap(pid)
        del self.memories[pid]

    def snapshot(self) -> dict[str, Any]:
        """Mathematics: serialize the composed product state `VM = (E, S, {M_pid})` for replay inspection."""

        return {
            "environment": self.environment.snapshot(),
            "scheduler": self.scheduler.snapshot(),
            "max_resident_pages": self.max_resident_pages,
            "memories": {str(pid): memory.snapshot() for pid, memory in sorted(self.memories.items())},
            "shared_regions": {
                name: region.snapshot() for name, region in sorted(self.shared_regions.items())
            },
            "resolver_observation_receipts": [
                {
                    "pid": pid,
                    "source": source,
                    "sequence": sequence,
                    "payload": list(payload),
                }
                for (pid, source, sequence), payload in sorted(self._resolver_observation_receipts.items())
            ],
        }

    @classmethod
    def from_snapshot(
        cls,
        payload: dict[str, Any],
        trajectory: TrajectoryWriter | None = None,
        page_backing: PageBacking | None = None,
    ) -> "MailCPUVirtualMachine":
        """Mathematics: invert `snapshot` into a continuation-equivalent VM state with shared bus and journal identity."""

        environment = VirtualEnvironment.from_snapshot(dict(payload["environment"]))
        machine = cls(
            environment,
            trajectory=trajectory,
            max_resident_pages=(
                None
                if payload.get("max_resident_pages") is None
                else int(payload["max_resident_pages"])
            ),
            page_backing=page_backing,
        )
        machine.shared_regions = {
            str(name): SharedRegion.from_snapshot(dict(raw))
            for name, raw in payload.get("shared_regions", {}).items()
        }
        machine.scheduler = DeterministicScheduler.from_snapshot(
            dict(payload["scheduler"]),
            bus=environment.kernel.bus,
            journal=environment.kernel.journal,
            syscall_handler=machine._dispatch_program_syscall,
        )
        machine.memories = {
            int(pid): VirtualMemory.from_snapshot(
                dict(memory),
                shared_regions=machine.shared_regions,
                resident_admitter=machine._admit_resident_pages,
                page_backing=machine.page_backing,
            )
            for pid, memory in payload.get("memories", {}).items()
        }
        machine._resolver_observation_receipts = {}
        raw_receipts = payload.get("resolver_observation_receipts", ())
        if not isinstance(raw_receipts, (list, tuple)):
            raise ValueError("VM resolver observation receipts must be a sequence")
        for raw_receipt in raw_receipts:
            if not isinstance(raw_receipt, dict):
                raise ValueError("VM resolver observation receipt must be a mapping")
            pid = int(raw_receipt["pid"])
            source = str(raw_receipt["source"])
            sequence = int(raw_receipt["sequence"])
            if pid <= 0 or not source or sequence <= 0:
                raise ValueError("invalid VM resolver observation receipt identity")
            raw_payload = raw_receipt.get("payload")
            if not isinstance(raw_payload, (list, tuple)):
                raise ValueError("VM resolver observation receipt payload must be a sequence")
            observation = decode_substrate_observation(tuple(raw_payload))
            if observation.source != source or pid not in machine.scheduler.tasks:
                raise ValueError("VM resolver observation receipt ownership mismatch")
            receipt_key = (pid, source, sequence)
            if receipt_key in machine._resolver_observation_receipts:
                raise ValueError("duplicate VM resolver observation receipt")
            machine._resolver_observation_receipts[receipt_key] = observation.to_payload()
        task_pids = set(machine.scheduler.tasks)
        memory_pids = set(machine.memories)
        if task_pids != memory_pids:
            raise ValueError("VM scheduler tasks and memory images are not one-to-one")
        kernel_pids = set(environment.kernel.processes)
        if not task_pids.issubset(kernel_pids):
            raise ValueError("VM scheduler task has no kernel process")
        machine._validate_resident_budget()
        return machine

    def resident_pages(self) -> int:
        """Mathematics: calculate resident mapping cardinality `R = Σ_pid |M_pid|`."""

        return sum(len(memory.mapped_pages()) for memory in self.memories.values())

    def _admit_resident_pages(self, additional_pages: int) -> None:
        """Mathematics: require `B=None ∨ resident_pages()+n≤B` before committing new resident mappings."""

        if additional_pages < 0:
            raise ValueError("additional resident pages must be non-negative")
        if self.max_resident_pages is not None and self.resident_pages() + additional_pages > self.max_resident_pages:
            raise ResidentQuotaExceeded(
                f"resident page budget exceeded: {self.resident_pages() + additional_pages} > {self.max_resident_pages}"
            )

    def _validate_resident_budget(self) -> None:
        """Mathematics: validate restored state invariant `resident_pages()≤B` after reconstructing all process memories."""

        self._admit_resident_pages(0)

    def _admit_replacement(self, removed_pages: int, added_pages: int) -> None:
        """Mathematics: require `B=None ∨ resident_pages()-removed+added≤B` before an image replacement."""

        if removed_pages < 0 or added_pages < 0:
            raise ValueError("replacement page counts must be non-negative")
        if (
            self.max_resident_pages is not None
            and self.resident_pages() - removed_pages + added_pages > self.max_resident_pages
        ):
            raise ResidentQuotaExceeded(
                "resident page budget exceeded during exec: "
                f"{self.resident_pages() - removed_pages + added_pages} > {self.max_resident_pages}"
            )
