# Genuine subprocess crash recovery

## Purpose

The previous recovery experiment captured a receiver-side transaction cut by
raising an exception inside the worker process, then reconstructed the receiver
in the same Python process. This experiment removes that simulation boundary:
an external supervisor launches a child interpreter, waits until the combined
checkpoint has been durably published, terminates the child without graceful
shutdown, and starts a second interpreter that resumes from disk.

The selected cut is exact:

> Branch B's receiver-side semantic execution effect is committed, but the
> response has not been published and the request has not been acknowledged.

## Process protocol

### Process 1 — prepare and commit

The supervisor launches
`tests/helpers/navigable_process_worker.py prepare CHECKPOINT MARKER`
using `subprocess.Popen`. That child constructs a fresh HeadlessOS receiver,
admitted Structural Memory recurrence, Transit worker/session, reliable TCP
channels, evidence route, and four-node computation frontier (memory, branches
A/B/C, and join).

The child reads `x_23=220`, executes branch A (239), then submits branch B
(660). At the Transit `after_execution_commit` fault hook, the child:

1. captures the schema-v3 `NavigableComputationCheckpoint` with the in-flight
   reliable cursors, receiver execution ledger, exact route and retry event,
   and DAG snapshot;
2. calls `NavigableComputationCheckpoint.save`, which writes and fsyncs a
   temporary file, atomically replaces the checkpoint path, and attempts to
   fsync the parent directory;
3. writes and fsyncs a supervisor marker containing its PID, checkpoint digest,
   backend call count, graph frontier, and proof that no response is pending;
4. blocks inside the fault hook, before the worker can publish a response or
   acknowledge the request.

The marker is not the checkpoint and does not authorize recovery. It only lets
the supervisor know that the checkpoint save returned and the selected
transaction cut is still held.

### Supervisor — hard termination

The parent verifies the marker, loads the checkpoint independently, checks its
schema/digest and transaction state, then calls `Popen.kill()`. On POSIX this
uses `SIGKILL`; on Windows it uses process termination through the Windows
process API. The child is not asked to close transports, flush application
buffers, run `finally` blocks, or take another snapshot.

The test requires a non-zero child exit status and confirms the checkpoint is
still readable after the child has exited.

### Process 2 — restore and continue

The supervisor launches the same script in `restore` mode using a new Python
interpreter. This process:

1. loads and verifies the checkpoint before constructing replacement runtime
   endpoints;
2. creates fresh loopback TCP transports and restores the receiver, requester
   and worker reliable-channel state, backend manifest, evidence catalogue,
   route, retry event, and DAG;
3. retransmits branch B's exact outstanding reliable frame;
4. requires the execution ledger to return B's exact committed effect as a
   semantic replay, without invoking the replacement CPU backend;
5. commits B into the DAG, executes only branch C, then materializes and
   executes the join after all branch dependencies are committed.

A corrupted checkpoint is sent to a separate restore interpreter as a
negative control. Its outer digest mismatch must fail before any result file is
published.

## Workload and expected accounting

The common Structural Memory receipt is:

\[
x_t=(13+9t)\bmod 251,\qquad x_{23}=220.
\]

| Operation | Expected result | Backend call |
|---|---:|---|
| Branch A: \(x+19\) | 239 | 1, before termination |
| Branch B: \(3x\) | 660 | 1, before termination |
| Branch B retransmission | 660 | 0, replay from execution ledger |
| Branch C: \(2x+7\) | 447 | 1, after restart |
| Join: \(239+660+447\) | 1346 | 1, after restart |

The accounting must be exactly four CPU backend invocations: A and B before
termination, then C and the join after restart. Branch B's retry is not a new
execution. Branch A is preserved from the DAG and is not submitted again. The
join remains blocked until B and C have been committed.

## What this establishes

- The original worker interpreter can be terminated while its fault hook is
  holding the system after execution commit but before response publication.
- The saved combined checkpoint remains readable after that process is gone.
- A new interpreter reconstructs the receiver and both reliable-channel roles
  on fresh TCP sockets from the disk checkpoint.
- The saved backend manifest, route projection, retry identity, and DAG
  frontier survive that boundary and are revalidated during restore.
- A committed-but-unpublished pure CPU effect is replayed without a second
  backend call.
- Completed sibling work is preserved; only unexecuted work is dispatched.
- A modified checkpoint is refused before runtime reconstruction.

## Proof boundary

This is a genuine operating-system process-termination test, not an in-process
exception or object reconstruction. It proves recovery from abrupt loss of the
child process while the local filesystem remains available and retains the
checkpoint that was fsynced before termination.

It does **not** prove recovery from power loss, kernel panic, storage-controller
failure, filesystem corruption, or a remote storage outage. The directory fsync
is best-effort on platforms where opening/fsyncing a directory is unsupported.
The SHA-256 envelope detects modification; it is not an authenticated
signature, MAC, anti-rollback mechanism, or proof against a malicious storage
provider.

The requester endpoints and receiver worker are all hosted inside the
supervised child in this first subprocess harness. Their semantic channel
cursors are checkpointed and rebound to fresh transports, but the requester is
not yet an independently surviving process. The next useful boundary is a
separate client process that stays alive while only the receiver is killed,
followed by testing restart races, repeated kill/restart cycles, and checkpoint
generation/anti-rollback policy.

The CPU jobs are deterministic and side-effect-free. The result does not prove
exactly-once behavior for arbitrary external side effects: those require a
durable effect journal or idempotency contract at the actual side-effect owner.

## Run

    python -m pytest tests/test_process_crash_recovery.py -q
    python scripts/verify_invariants.py
    python scripts/verify_repo.py

The full Linux/Windows and Python-version CI matrix remains the merge gate.
