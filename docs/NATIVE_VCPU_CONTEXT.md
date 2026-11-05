# Native vCPU Context Backend

## Purpose

This backend is the first subsystem-specific connection between hypervisor-admitted navigation and the native MailCPU virtual CPU. It projects the scheduler's actual program counter and integer register file, not a parallel simulated register object.

The backend is deliberately a **suspended-context editor**, not an alternate instruction interpreter. It changes only the native task's `pc` and integer register valuation at a scheduler safepoint. The existing scheduler and `apply_instruction` interpreter remain responsible for retiring the next instruction, system calls, mailbox effects, instruction counting, and halt/block semantics.

## CPU state projection

For a task PID (p), the provider emits:

```text
C_p = (
  schema, pid, process_id, program_digest, program_length,
  pc, registers, task_status, halted, blocked, steps
)
```

The program digest is calculated from the ordered native instruction sequence. A process descriptor and semantic address must name the same process ID and version. The live `ProcessContext` also binds the PID, program digest, instruction count, kernel capability rights, fixed resource capacities, and bounded navigation budgets.

A provider call is accepted only when:
- the kernel process exists and has not exited;
- the scheduler task exists and is `SUSPENDED`;
- the task is neither halted nor blocked and has no outstanding wait request;
- the PC is inside the current immutable program;
- the register file is a bounded mapping of non-empty names to integers.

Suspension is a safepoint. The scheduler's re-entrant state lock serializes instruction retirement and snapshot publication with context commits. VM-level composite operations (spawn, fork, exec, reap, shared-memory topology changes, and VM snapshots) use the same lock, so a checkpoint cannot observe those operations half-applied.

## Commit contract

`NativeCPUContextBackend.execution_adapter()` returns the generic `HypervisorNavigationExecutionAdapter` with this backend's provider, commit callback, and receipt lookup.

After the generic adapter verifies journal provenance, current capabilities, grant expiry, context identity, transition guards, resource envelope, and final semantic goal, the native callback re-enters the scheduler's state transaction and repeats the critical checks. It then performs a compare-and-swap on the complete CPU context digest.

Only `pc` and `registers` may differ between the start and candidate states. The callback refuses changes to:
- task/process identity and program image digest;
- program length;
- task lifecycle state, halted/blocked flags;
- retired instruction count.

The PC must remain in the program's valid instruction range. Register names and values are validated and the configured register limit is enforced. Kernel resource rights and the half-open scheduler-tick grant interval are rechecked inside the scheduler transaction.

## Atomic persistence and recovery

The scheduler stores:
- a per-PID native CPU context revision;
- committed navigation receipts keyed by stable execution ID.

Both are included in the scheduler snapshot. On a successful context CAS, the backend updates the scheduler's real task state and calls `save_checkpoint`. The updated PC, registers, revision, and idempotency receipt are therefore published together through the checkpoint's same-directory atomic file replacement.

If checkpoint publication fails, in-memory PC/register/revision/receipt changes are rolled back and the callback returns a non-committed receipt. If the host is lost after the checkpoint is published but before the generic execution journal receives its final commit record, checkpoint restore recovers both the CPU context and the receipt. The generic adapter then reconciles its existing write-ahead execution intent without applying the context update twice.

The checkpoint path is mandatory. This backend does not claim crash recovery when it is configured without durable storage.

## Example state-space

A process may describe native context navigation with ordinary declarative rules:

- guard: `pc == 0`;
- updates: `pc := pc + 1`, `registers.rax := registers.rax + 7`;
- goal: `pc == 1 ∧ registers.rax == 8`.

The coordinator finds and verifies the route, admission asks the hypervisor for an ALLOW/CPU grant, and the execution adapter replays the route before the native callback commits the real scheduler-owned context.

On resume, the existing interpreter fetches the instruction at the navigated PC. No instruction is silently counted as retired by the context edit itself.

## Explicit non-goals

This first backend does not:
- retire an instruction or fabricate an interpreter execution event; changing the PC can intentionally select a different next instruction after resume;
- change code, opcodes, or the program digest;
- mutate mailboxes, I/O output, syscalls, memory pages, kernel process state, scheduler time, or task lifecycle state;
- navigate a running task or a task blocked on an external event;
- change the architecture into a hardware ISA emulator.

These are separate integration boundaries. In particular, future memory navigation needs a page-table-aware transactional backend, and instruction execution needs a scheduler-owned retirement API that preserves the single-transition conformance contract.
