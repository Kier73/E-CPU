# Repeated joint-process recovery across consecutive crashes

## Purpose

The joint requester/receiver experiment proves one hard termination of both
processes. This extension repeats the same failure after the receiver has
already restored once. It asks whether a committed operation can remain
committed while its response is withheld through multiple independent process
generations.

The experiment deliberately stops at one transaction boundary:
`after_execution_commit`. The backend effect is committed,
but the response has not been published and the request has not been consumed
or acknowledged.

## Process protocol

### Generation 0: original pair

The requester sends reliable request sequence 1, a pure CPU program returning
12, and fsyncs its exact pending request frame and response-channel cursor.
The receiver executes the backend once, commits the hypervisor effect ledger,
and saves its own in-flight session checkpoint at
`after_execution_commit`.

The supervisor verifies both markers, then hard-kills both interpreters.

### Generation 1: first replacement pair

A new receiver restores its own checkpoint and a new requester restores its
own channel checkpoint over fresh TCP transports. The requester retransmits
the exact sequence-1 frame.

The receiver finds the already committed effect in its execution ledger. It
does not enter the replacement backend. Before publishing the replay response,
the test saves a second receiver checkpoint at the same transaction boundary.
The requester saves its updated reliable-channel snapshot. The supervisor then
hard-kills this replacement pair as well.

### Generation 2: second replacement pair

A third receiver and requester restore the latest independent checkpoints.
The requester retransmits sequence 1 again. The receiver replays the original
effect with zero backend entries, now publishes the response, consumes and
acknowledges the request, and returns the result 12.

The requester then submits sequence 2. It returns 42 through a fresh backend
entry. Both reliable windows drain and the receiver journal verifies.

## Expected accounting

| Transition | Result | Backend entries |
|---|---:|---:|
| Sequence 1, original receiver | 12 | 1 |
| Sequence 1 replay, first replacement receiver | response withheld at crash cut | 0 |
| Sequence 1 replay, second replacement receiver | 12 | 0 |
| New sequence 2 after the second restart | 42 | 1 |
| **Total across all receiver generations** | — | **2** |

The central accounting law is that process replacement does not reset the
semantic operation identity or erase its committed effect:

\[
\operatorname{backendEntries}(e_1,\;3\text{ receiver generations})=1
\]

The fresh sequence-2 operation proves the recovered system can advance rather
than merely replaying historical state.

## What this establishes

- Both original peers are hard-killed, then both first replacements are
  hard-killed; the final pair has new process identities.
- The same request identity survives two consecutive crash/restart cycles.
- The first receiver enters the backend exactly once.
- Both restored receivers replay the committed effect without backend entry.
- Response publication is withheld across both crash cuts.
- The final restored pair publishes the committed result and accepts new work.
- Request and response windows drain and the execution journal verifies.
- The requester and receiver restore from independent durable checkpoints.

## Proof boundary

This is a local-filesystem and loopback-TCP experiment using pure CPU work.
It proves process-death recovery and preservation of an execution-ledger entry
across successive checkpoint rewrites. It does not simulate power loss,
storage-controller failure, malicious checkpoint modification, rollback of
the checkpoint and every external anchor together, distributed consensus, or
exactly-once behavior for arbitrary external side effects.

The checkpoint digest detects accidental content modification. It is not an
authentication mechanism or an anti-rollback authority. A generation number
inside a checkpoint would not solve rollback by itself: stale-state rejection
requires comparison with a high-water mark held by a separately protected
authority.

## Run

    python -m pytest tests/test_repeated_joint_process_recovery.py -q
    python scripts/verify_invariants.py
    python scripts/verify_repo.py
