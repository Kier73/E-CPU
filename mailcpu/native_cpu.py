"""Checkpoint-backed adapter for native MailCPU virtual-CPU contexts.

The adapter projects the real scheduler-owned program counter and integer
register file into the declarative navigation model. Commits are restricted
to suspended task safepoints and are persisted together with their idempotency
receipt in one integrity-checked HeadlessOS checkpoint.
"""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .checkpoint import save_checkpoint
from .fs import normalize_path
from .kernel import ProcessStatus
from .model import Program
from .navigation import ProcessContext, ProcessDescriptor, SemanticAddress
from .navigation_execution import (
    HypervisorNavigationExecutionAdapter,
    NavigationCommitReceipt,
)
from .scheduler import TaskStatus


class NativeCPUContextError(ValueError):
    """Invalid native CPU context, unsafe task state, or backend configuration."""


def _canonical_bytes(value: Any) -> bytes:
    """Encode a JSON-compatible value in the canonical form used by navigation receipts."""
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise NativeCPUContextError(f"value is not canonical JSON: {exc}") from exc


def _digest(value: Any) -> str:
    """Return the SHA-256 identity of one canonical JSON value."""
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _program_digest(program: Program) -> str:
    """Identify the immutable native instruction image without transport metadata."""
    return _digest(
        {
            "schema": "mailcpu.program.v1",
            "instructions": [
                {"op": instruction.op.value, "args": list(instruction.args)}
                for instruction in program.instructions
            ],
        }
    )


class NativeCPUContextBackend:
    """Expose a real suspended MailCPU task as a CAS-backed navigation context.

    This backend edits only the native task PC and integer register file. It
    does not retire instructions, modify code, perform I/O, or mutate virtual
    memory. The existing scheduler/interpreter resumes execution afterward.
    """

    STATE_SCHEMA = "mailcpu.native-cpu-context.v1"

    def __init__(
        self,
        operating_system: Any,
        checkpoint_path: str | Path,
        *,
        resource_path: str = "/cpu/context",
        max_registers: int = 128,
        max_expansions: int = 10_000,
        max_depth: int = 256,
    ) -> None:
        """Bind one OS instance, an atomic checkpoint destination, and finite navigation budgets."""
        if not hasattr(operating_system, "vm") or not hasattr(operating_system.vm, "scheduler"):
            raise NativeCPUContextError("operating_system must expose a MailCPU VM scheduler")
        if not isinstance(checkpoint_path, (str, Path)) or not str(checkpoint_path).strip():
            raise NativeCPUContextError("checkpoint_path must be a non-empty path")
        try:
            canonical_resource = normalize_path(resource_path)
        except Exception as exc:
            raise NativeCPUContextError(f"resource_path is invalid: {exc}") from exc
        if canonical_resource != resource_path:
            raise NativeCPUContextError("resource_path must already be canonical")
        for name, value in (
            ("max_registers", max_registers),
            ("max_expansions", max_expansions),
            ("max_depth", max_depth),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise NativeCPUContextError(f"{name} must be a positive integer")
        self.operating_system = operating_system
        self.checkpoint_path = Path(checkpoint_path)
        self.resource_path = canonical_resource
        self.max_registers = max_registers
        self.max_expansions = max_expansions
        self.max_depth = max_depth

    def _resolve_task(self, pid: int):
        """Resolve a live task only when it is at a non-blocked suspended instruction boundary."""
        if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
            raise NativeCPUContextError("pid must be a positive integer")
        kernel = self.operating_system.environment.kernel
        scheduler = self.operating_system.vm.scheduler
        try:
            process = kernel._process(pid)
            task = scheduler.tasks[pid]
        except Exception as exc:
            raise NativeCPUContextError(f"native CPU task is unavailable: {exc}") from exc
        if process.status is ProcessStatus.EXITED:
            raise NativeCPUContextError("exited kernel process cannot expose a CPU context")
        if task.status is not TaskStatus.SUSPENDED:
            raise NativeCPUContextError("native CPU context requires a suspended scheduler task")
        if task.state.halted or task.state.blocked or task.wait_request is not None:
            raise NativeCPUContextError("halted or blocked task is not a supported CPU safepoint")
        if task.program is None or not isinstance(task.program, Program):
            raise NativeCPUContextError("scheduler task has no valid native Program")
        if not 0 <= task.state.pc < len(task.program.instructions):
            raise NativeCPUContextError("native program counter is outside the instruction image")
        if task.state.steps < 0:
            raise NativeCPUContextError("native instruction count is invalid")
        registers = task.backend.snapshot_registers()
        if len(registers) > self.max_registers:
            raise NativeCPUContextError("native register file exceeds the configured register bound")
        if any(
            not isinstance(name, str)
            or not name
            or not isinstance(value, int)
            or isinstance(value, bool)
            for name, value in registers.items()
        ):
            raise NativeCPUContextError("native register file must map non-empty names to integers")
        return process, task

    def _native_state(self, pid: int, process_id: str) -> dict[str, Any]:
        """Project the live scheduler-owned PC/register file and immutable execution coordinates."""
        _, task = self._resolve_task(pid)
        return {
            "schema": self.STATE_SCHEMA,
            "pid": pid,
            "process_id": process_id,
            "program_digest": _program_digest(task.program),
            "program_length": len(task.program.instructions),
            "pc": task.state.pc,
            "registers": task.backend.snapshot_registers(),
            "task_status": task.status.value,
            "halted": task.state.halted,
            "blocked": task.state.blocked,
            "steps": task.state.steps,
        }

    def state_provider(
        self,
        pid: int,
        descriptor: ProcessDescriptor,
        address: SemanticAddress,
    ) -> ProcessContext:
        """Return a complete context whose current_state is the actual native task PC and register file."""
        if not isinstance(descriptor, ProcessDescriptor) or not isinstance(address, SemanticAddress):
            raise NativeCPUContextError("state_provider requires a ProcessDescriptor and SemanticAddress")
        if (
            descriptor.process_id != address.process_id
            or descriptor.version != address.version
        ):
            raise NativeCPUContextError("semantic address does not identify the native process descriptor")
        scheduler = self.operating_system.vm.scheduler
        with scheduler.state_transaction():
            process, _ = self._resolve_task(pid)
            state = self._native_state(pid, descriptor.process_id)
            program_digest = state["program_digest"]
            rights = frozenset(
                right
                for capability in process.capabilities
                for right in capability.rights
            )
            return ProcessContext(
                process_id=descriptor.process_id,
                current_state=state,
                bindings={
                    "cpu.pid": pid,
                    "cpu.program_digest": program_digest,
                    "cpu.program_length": state["program_length"],
                },
                resource_capacity={
                    "cpu.context": 1,
                    "cpu.registers": self.max_registers,
                },
                capabilities=rights,
                max_expansions=self.max_expansions,
                max_depth=self.max_depth,
            )

    def _validate_candidate(
        self,
        candidate_state: Mapping[str, Any],
        current_state: Mapping[str, Any],
        grant: Any,
    ) -> dict[str, Any]:
        """Allow only a bounded PC/register update while binding every other CPU coordinate."""
        if not isinstance(candidate_state, Mapping):
            raise NativeCPUContextError("candidate CPU context must be a mapping")
        candidate = dict(candidate_state)
        required_keys = {
            "schema",
            "pid",
            "process_id",
            "program_digest",
            "program_length",
            "pc",
            "registers",
            "task_status",
            "halted",
            "blocked",
            "steps",
        }
        if set(candidate) != required_keys:
            raise NativeCPUContextError("candidate CPU context has an unexpected field set")
        mutable = {"pc", "registers"}
        for name in required_keys - mutable:
            if candidate[name] != current_state[name] or type(candidate[name]) is not type(current_state[name]):
                raise NativeCPUContextError(f"navigation may not change native CPU coordinate {name}")
        pc = candidate["pc"]
        if not isinstance(pc, int) or isinstance(pc, bool):
            raise NativeCPUContextError("candidate program counter must be an integer")
        if not 0 <= pc < current_state["program_length"]:
            raise NativeCPUContextError("candidate program counter is outside the native instruction image")
        registers = candidate["registers"]
        if not isinstance(registers, Mapping):
            raise NativeCPUContextError("candidate register file must be a mapping")
        if len(registers) > self.max_registers:
            raise NativeCPUContextError("candidate register file exceeds the configured register bound")
        normalized: dict[str, int] = {}
        for name, value in registers.items():
            if (
                not isinstance(name, str)
                or not name
                or not isinstance(value, int)
                or isinstance(value, bool)
            ):
                raise NativeCPUContextError("candidate registers must map non-empty names to integers")
            normalized[name] = value
        candidate["registers"] = dict(sorted(normalized.items()))
        if (
            grant.pid != candidate["pid"]
            or grant.process_id != candidate["process_id"]
            or grant.resource != self.resource_path
        ):
            raise NativeCPUContextError("grant identity or resource does not match this native CPU backend")
        return candidate

    def commit_callback(
        self,
        pid: int,
        execution_id: str,
        expected_start_state_digest: str,
        candidate_state: Mapping[str, Any],
        grant: Any,
    ) -> NavigationCommitReceipt:
        """Atomically update scheduler PC/registers and checkpoint the update with its durable receipt."""
        scheduler = self.operating_system.vm.scheduler
        with scheduler.state_transaction():
            previous_raw = scheduler.navigation_commit_receipts.get(execution_id)
            if previous_raw is not None:
                previous = NavigationCommitReceipt.from_dict(previous_raw)
                if not previous.committed:
                    return replace(previous, replayed=True)
                return replace(previous, replayed=True)

            try:
                process, task = self._resolve_task(pid)
                if pid != grant.pid or grant.resource != self.resource_path:
                    raise NativeCPUContextError("grant PID/resource is outside this backend")
                if not grant.valid_at(scheduler.tick):
                    raise NativeCPUContextError("grant has expired at the current scheduler tick")
                for right in grant.required_rights:
                    if not any(capability.allows(grant.resource, right) for capability in process.capabilities):
                        raise NativeCPUContextError(f"live kernel capability no longer grants {right}")
                current_state = self._native_state(pid, grant.process_id)
                current_digest = _digest(current_state)
                if current_digest != expected_start_state_digest:
                    return NavigationCommitReceipt(
                        execution_id,
                        False,
                        expected_start_state_digest,
                        current_digest,
                        scheduler.native_cpu_revisions.get(pid, 0),
                        False,
                        "native CPU context changed before compare-and-swap",
                    )
                candidate = self._validate_candidate(candidate_state, current_state, grant)
                final_digest = _digest(candidate)
            except Exception as exc:
                observed_digest = (
                    expected_start_state_digest
                    if "current_digest" not in locals()
                    else current_digest
                )
                return NavigationCommitReceipt(
                    execution_id,
                    False,
                    expected_start_state_digest,
                    observed_digest,
                    scheduler.native_cpu_revisions.get(pid, 0),
                    False,
                    f"{type(exc).__name__}: {exc}",
                )

            old_pc = task.state.pc
            old_backend_registers = dict(task.backend.registers)
            old_state_registers = dict(task.state.registers)
            old_revision = scheduler.native_cpu_revisions.get(pid, 0)
            revision = old_revision + 1
            receipt = NavigationCommitReceipt(
                execution_id,
                True,
                expected_start_state_digest,
                final_digest,
                revision,
                False,
                None,
            )

            task.state.pc = candidate["pc"]
            task.backend.registers = dict(candidate["registers"])
            task.state.registers = dict(candidate["registers"])
            scheduler.native_cpu_revisions[pid] = revision
            scheduler.navigation_commit_receipts[execution_id] = receipt.to_dict()
            try:
                save_checkpoint(self.operating_system, self.checkpoint_path)
            except Exception as exc:
                task.state.pc = old_pc
                task.backend.registers = old_backend_registers
                task.state.registers = old_state_registers
                if old_revision:
                    scheduler.native_cpu_revisions[pid] = old_revision
                else:
                    scheduler.native_cpu_revisions.pop(pid, None)
                scheduler.navigation_commit_receipts.pop(execution_id, None)
                return NavigationCommitReceipt(
                    execution_id,
                    False,
                    expected_start_state_digest,
                    expected_start_state_digest,
                    old_revision,
                    False,
                    f"atomic checkpoint failed: {type(exc).__name__}: {exc}",
                )
            return receipt

    def commit_lookup(self, execution_id: str) -> NavigationCommitReceipt | None:
        """Read the checkpointed idempotency receipt without reapplying its CPU context update."""
        scheduler = self.operating_system.vm.scheduler
        with scheduler.state_transaction():
            raw = scheduler.navigation_commit_receipts.get(execution_id)
            if raw is None:
                return None
            receipt = NavigationCommitReceipt.from_dict(raw)
            return replace(receipt, replayed=True)

    def execution_adapter(self) -> HypervisorNavigationExecutionAdapter:
        """Bind this native CPU provider and atomic commit contract to the generic grant verifier."""
        return HypervisorNavigationExecutionAdapter(
            self.operating_system,
            self.state_provider,
            self.commit_callback,
            self.commit_lookup,
        )
