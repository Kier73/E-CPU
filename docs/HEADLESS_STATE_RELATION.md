# Exact HeadlessOS-State Relation (Iteration 3.2)

## Purpose

Iteration 3.1 established an exact observational relation over a closed MailCPU scheduler, its task runtimes, FIFO message bus and journal. This extension moves the comparison boundary outward to the continuation-capable \`HeadlessOS.snapshot()\` graph.

It is still a verification instrument. It does not skip instructions, mutate a live machine using a predicted state, or grant permission to fast-forward.

## Snapshot boundary

The observer uses the canonical \`HeadlessOS.snapshot()\` result and verifies the shared kernel journal. The snapshot graph includes:

- **VM:** virtual environment, scheduler, per-process memory images, shared regions, resolver observation receipts and the VM resident-page budget.
- **Kernel:** filesystem, bus, process table and process details, capabilities, working directories, descriptors, open descriptions, pipes, FD transfers, device state, counters and journal.
- **Environment:** init identity, network device, owned network fabric, datagram/stream stacks and resource ownership maps.
- **Services and control plane:** service supervisor, classifier hypervisor, arbitration state and seed-admission coordinator.

The state digest is:

\[
D(OS)=\operatorname{SHA256}(\operatorname{CanonicalJSON}(OS.snapshot())).
\]

The implementation also checks the payload equality after digest equality and returns path-level differences when the states are not related.

## Closed-boundary admission

The following are deliberately refused because they are external to, or not represented by, the snapshot graph:

- a trajectory writer;
- VM or per-process external page backing;
- non-standard VM/OS callbacks;
- non-standard scheduler callbacks;
- non-standard memory resident-page admission callbacks;
- pending, uncommitted exec or fork transitions;
- inconsistent scheduler/kernel bus or journal identity.

The built-in HeadlessOS callback path is admitted because it is re-established by \`HeadlessOS.from_snapshot()\` and its mutable state is held in the snapshot graph. This allows standard OS-managed syscalls and wake/deferred-exec behavior, unlike the scheduler-only closed profile.

## Trace witness

Capture calls \`HeadlessOS.run(max_ticks=tick+1)\` for each accepted transition and requires exactly one \`ScheduleEvent\` and a one-tick scheduler advance. Each event and complete post-transition OS snapshot is hashed into an ordered receipt chain.

The witness stores digests and byte counts, not the original VM history. It is an integrity index, not a reconstructable trace or semantic compression format.

## Tests

The real integration suite exercises two HeadlessOS processes exchanging FIFO \`SEND\`/\`WAIT\` messages and checks:

1. Identical complete HeadlessOS snapshots and all transition boundaries.
2. Checkpoint-style snapshot restoration with identical future execution.
3. Divergence when memory, filesystem, mailbox queues or capabilities change.
4. Rejection of external page backing, trajectory writers and substituted callbacks.
5. Rejection of tampered event-journal state.

Run:

\`\`\`bash
python -m pytest -q tests/test_headless_relation.py
python -m pytest -q tests/test_scheduler_relation_unit.py tests/test_scheduler_relation.py
\`\`\`

## Limits and next obligation

This is an exact relation over the state graph currently returned by \`HeadlessOS.snapshot()\`, subject to the closed-boundary checks above. It does not prove approximate bisimulation between different implementations or physical substrates. It does not cover an external page store, a live trajectory writer, or arbitrary host effects.

The next step is to test the relation under deliberately varied **standard OS-managed operations**—for example syscalls, pipes, descriptor transfer, device I/O, shared memory and service transitions—and confirm that the full snapshot graph predicts their continuation. Any newly discovered stateful resource outside the snapshot must be added explicitly or refused. Only after this wider conformance matrix should a task-relative abstract transition be compared with full-system execution.
