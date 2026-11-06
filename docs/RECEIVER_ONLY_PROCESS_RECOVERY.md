# Receiver-only subprocess recovery with a surviving requester

## Purpose

The first subprocess experiment killed the interpreter that owned both ends of
the requester/receiver path. This experiment moves the requester into the
supervising pytest process and kills only the receiver child. The client process
and its in-memory sender/response ledgers remain alive across receiver death.

This is a different recovery topology: a live requester remains connected to
the system while its receiver child is terminated and replaced by a fresh
receiver interpreter.

The client reconnects to new TCP streams, reconstructs its channel wrappers
from snapshots held in its own memory, and retransmits the original pending
request. The receiver restores only its own TransitComputeSession checkpoint.

## Process protocol

### Initial receiver process

The receiver-only helper starts a child interpreter with two loopback listeners.
The pytest process connects as the client and creates its own reliable request
and result channels.

The requester submits reliable sequence 1: a pure CPU program with expected
answer 12. The receiver authorizes the operation and commits its hypervisor
execution result. At the after_execution_commit hook, before response
publication or request ACK, the receiver:

1. persists TransitComputeSession.save_checkpoint with allow_inflight enabled;
2. records its PID, backend invocation count, request receive cursor, queued
   request identity, response pending set, and kernel journal verification;
3. blocks inside the fault hook.

The test checks that the requester still owns pending sequence 1 and has not
received a response.

### Receiver termination

The pytest process hard-kills the receiver child. It does not exit or restart.
It retains the requester-side reliable-channel snapshots in its own memory,
including the exact pending frame for sequence 1 and its response receive
cursor.

### Fresh receiver process and client rebind

A new receiver interpreter reads the session checkpoint, binds a new pair of
TCP listeners, and restores the TransitComputeSession over accepted sockets.
Its request receive cursor must still be 1 and its backend call count must be
zero. The visible phase may be idle or request-ready: the requester can safely
retransmit as soon as the listener is available, even while the receiver is
finishing restoration. The old inbound socket queue is not treated as durable
state; the surviving requester owns the unacknowledged outbound frame.

The still-live pytest process connects new client sockets and reconstructs
ReliableChannel objects from its in-memory channel snapshots. It retransmits
the original sequence 1 without changing its event identity.

The receiver execution ledger recognizes the already-committed event and
returns its effect as a replay. The replacement CPU backend is not called.
The requester receives the result for the first time, so the receiver's
execution replay flag is true while the client's response duplicate flag is
false.

The same requester then submits a new sequence 2 operation. It returns 42 and
enters the replacement backend exactly once, proving that recovery restored a
live execution path rather than a replay-only endpoint.

## Expected accounting

| Transition | Answer | Backend entries |
|---|---:|---:|
| Sequence 1 before receiver kill | 12 | 1 |
| Sequence 1 replay after receiver restart | 12 | 0 |
| Sequence 2 submitted after recovery | 42 | 1 |
| **Total** | — | **2** |

If sequence 1 enters the replacement backend, or sequence 2 cannot run, the
experiment fails.

## What this establishes

- The requester process PID is unchanged before, during, and after receiver
  termination.
- Only the receiver child is hard-killed.
- The original requester retains the exact pending reliable frame in memory.
- Both client-side channels rebind to fresh TCP streams without resetting
  sequence identity or receive cursors.
- The receiver's committed operation replays from its restored execution
  ledger with zero replacement-backend calls.
- A new operation succeeds through the same recovered route.
- Semantic translation and oracle evidence are validated for both responses.
- The receiver's execution journal verifies after restart.

## Proof boundary

The requester survives because the supervising pytest process remains alive.
Its protocol state is reconstructed from in-memory snapshots, not from a
client-side durable checkpoint. This is not client-process recovery: if the
requester itself dies, this experiment does not preserve its unacknowledged
frame.

The receiver checkpoint is local and fsynced, but the test does not simulate
power loss, kernel panic, storage failure, or corruption. The workload is a
pure CPU program; exactly-once guarantees for external side effects require
durable idempotency or an effect journal at the side-effect owner.

This test uses a CPU-only receiver manifest. Structural Memory plus
multi-branch DAG recovery remains covered by the combined-checkpoint process
test; the two experiments prove complementary failure topologies rather than
claiming one universal test.

## Run

    python -m pytest tests/test_receiver_only_process_recovery.py -q
    python scripts/verify_invariants.py
    python scripts/verify_repo.py
