# Exact Scheduler-State Relation (Iteration 3.1)

## Purpose

This experiment advances from a task-output projection to an exact observational relation over a bounded, closed MailCPU scheduler execution. It is a verification instrument, not an execution accelerator. It never skips instructions or mutates the scheduler on the basis of a learned law.

## State included in the relation

For a scheduler state \(S\), define the canonical witness:

\[
W(S) = (\Sigma, M, Q, J)
\]

where:

- \(\Sigma\) is the canonical scheduler snapshot: logical tick, ready-queue order, task identities, programs, PCs, step counts, register values, lifecycle status, wait/wake requests, ChronoFold metadata, chemical-time settings and system epoch.
- \(M\) adds live \`MachineState\` flags and backend snapshots not fully represented by \`scheduler.snapshot()\`: blocked/halted flags, backend registers, local input queues and output logs.
- \(Q\) is the complete message-bus snapshot, including FIFO queue order, message identity, source/destination, kind, payload, logical time and counters.
- \(J\) is the verified event-journal record count and terminal SHA-256 digest.

The state digest is:

\[
D(S) = \operatorname{SHA256}(\operatorname{CanonicalJSON}(W(S))).
\]

Two scheduler states are related exactly when their canonical witness payloads are equal. The implementation checks both digest and payload equality; a digest match alone is not treated as proof.

## Closed execution domain

The relation rejects:
- external syscall handlers;
- task-level syscall handlers;
- \`SYSCALL\` instructions;
- custom wait predicates;
- post-step callbacks.

These can cause effects outside the represented scheduler, bus and journal state. They must be brought inside a larger system witness before they can be admitted.

This is an exact relation for a represented scheduler boundary, not for the entire HeadlessOS or VM. Filesystem, virtual memory, capabilities, open descriptors, devices, services, and kernel-managed external effects are not included here.

## Trace witness

For observed transitions \(e_0,\ldots,e_{n-1}\) and post-state digests \(d_1,\ldots,d_n\), define:

\[
r_0 = 0^{256}, \qquad
r_{i+1} = \operatorname{SHA256}
\left(r_i \Vert \operatorname{CanonicalJSON}(i,H(e_i),d_{i+1})\right).
\]

The witness stores the initial/final tick, every boundary digest, every event digest and the terminal receipt. It is an integrity index, not a reconstructable VM trace: the original scheduler execution or a checkpoint is still required to recover machine state.

Capture advances the real scheduler one tick at a time and requires exactly one accepted \`ScheduleEvent\` and a one-tick scheduler advance for each capture step. A stopped or blocked scheduler may terminate capture with fewer transitions than the budget.

## Tests

The integration tests exercise the actual \`DeterministicScheduler\` and cover:

1. Two independently constructed producer/worker executions with FIFO \`SEND\`/\`WAIT\` messaging are related at every transition boundary.
2. A scheduler, bus and journal restored from snapshots remain related, and their future traces remain equal.
3. A changed pending mailbox breaks the relation even when selected worker registers are equal.
4. A changed ready-queue order breaks the relation.
5. External callbacks and \`SYSCALL\` are rejected.
6. Journal tampering invalidates the observation.

The separate unit tests exercise receipt construction and canonicalization against deterministic test doubles.

## Running

\`\`\`bash
python -m pytest -q tests/test_scheduler_relation_unit.py
python -m pytest -q tests/test_scheduler_relation.py
python examples/scheduler_relation_benchmark.py --cycles 32
\`\`\`

The focused GitHub Actions workflow runs the real scheduler integration tests on pushes to this feature branch and on pull requests.

## What this does not establish

- It does not establish approximate bisimulation between different physical substrates or different scheduler implementations.
- It does not prove that a prior \`(x,y,z)\` task projection is sufficient for the whole VM.
- It does not compress or reconstruct the complete scheduler history.
- It does not permit a virtual jump, scheduler fast-forward or omission of \`SEND\`, \`WAIT\`, journal, output, kernel or external side effects.

The next proof obligation is to extend the relation to kernel-managed state, including memory, filesystem, capabilities, descriptors, devices and syscall effects. Only after the relevant effects are represented should we test whether any abstract transition can preserve them exactly.
