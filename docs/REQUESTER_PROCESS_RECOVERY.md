# Requester-process recovery with a surviving receiver

## Purpose

The receiver-only tests prove that a requester which remains alive can reconnect
after receiver termination. This experiment moves the failure to the other side:
the requester process is hard-killed after sending a request and durably saving
its own reliable-channel state, while the receiver process remains alive.

The requester capsule includes both the outbound request channel and inbound
result channel. The receiver separately persists its in-flight Transit session
after committing the CPU effect and publishing the response but before
acknowledging the request.

## Process protocol

### Initial requester and receiver

The supervisor launches one persistent receiver process. It opens fresh TCP
listeners and accepts a separate requester child process.

The requester sends reliable operation sequence 1, a pure CPU program whose
answer is 12. Immediately after sending, but before receiving any response, it
writes an integrity-digested client checkpoint containing:

- the exact pending request frame and sender sequence counter;
- the result channel receive cursor and delivered set;
- the semantic result ledger, initially empty;
- the requester PID for audit.

The requester publishes a marker and blocks. The receiver executes the CPU
operation once, commits the execution ledger, and publishes response transport
sequence 1. At the `after_response_publish` hook, before it consumes and
acknowledges the request, it atomically saves its receiver-side Transit session
checkpoint. The receiver marker records request cursor 1 and response sequence
1 pending.

### Requester death

The supervisor validates both checkpoints and hard-kills the original client
interpreter. The receiver remains alive in the same operating-system process;
its PID does not change.

The receiver's hook is released. It closes only the old TCP transports, opens
new listeners, and reconstructs its Transit session from the saved receiver
checkpoint over fresh accepted sockets. The original requester has no live
objects left: only its durable client checkpoint survives.

### Fresh requester interpreter

A new client interpreter reads and digest-validates the client checkpoint,
connects to the receiver's new TCP listeners, and restores the two reliable
channel wrappers from disk. It retransmits exact request sequence 1.

The receiver's reliable request cursor is restored at 1, and its execution
ledger already contains the committed effect. The retransmission therefore
returns a ledger replay without a backend call. The receiver also retransmits
the already-published response frame from its pending response ledger. The
new client has not previously seen the response, so it sees the first copy as
fresh and the replay response as a semantic duplicate.

The client acknowledges request sequence 1 and both response transport frames,
then submits a new sequence 2 operation. It receives answer 42, and the
reconstructed receiver backend is entered exactly once for that new operation.

## Expected accounting

| Transition | Result | Backend entries |
|---|---:|---:|
| Sequence 1 before requester death | 12 | 1 |
| Sequence 1 replay after requester restart | 12 | 0 |
| Original response retransmitted to new requester | 12 | 0 |
| New sequence 2 after recovery | 42 | 1 |
| **Total** | — | **2** |

## What this establishes

- The first requester PID is different from the restored requester PID.
- The receiver PID is identical before and after client-process termination.
- The client checkpoint survives the first requester interpreter's hard kill.
- The client checkpoint preserves pending sequence 1 and result receive cursor 1.
- A modified client checkpoint is rejected before the new requester opens replacement TCP connections.
- The receiver checkpoint preserves execution commit, response sequence 1,
  request receive cursor 1, and journal state.
- The restored requester receives one fresh response and one semantic duplicate
  for the same operation identity.
- The replay does not enter the replacement backend.
- A new operation executes once after requester recovery.
- Both request ACKs and all response ACKs are observed; no response frame
  remains pending.
- The restored receiver execution journal verifies.

## Proof boundary

The receiver process remains alive, but its in-memory Transit session is
reconstructed from a receiver-side disk checkpoint and rebound to new sockets.
The requester itself is truly killed and restarted from its own durable,
digest-checked channel capsule.

This uses local filesystems and pure CPU work. It does not prove power-loss or
storage-controller durability, anti-rollback protection, authenticated
checkpoints, distributed consensus, or exactly-once semantics for arbitrary
external side effects. The checkpoint digest detects accidental modification;
it is not a MAC or digital signature.

## Run

    python -m pytest tests/test_requester_process_recovery.py -q
    python scripts/verify_invariants.py
    python scripts/verify_repo.py
