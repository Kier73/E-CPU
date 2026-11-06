# Joint requester and receiver process recovery

## Purpose

The receiver-only and requester-only experiments prove each side can be
reconstructed independently. This experiment combines those two boundaries:
both original processes are hard-killed, and each new interpreter restores
only its own durable checkpoint.

The system must recover the logical operation without relying on either
original process's memory, then accept a fresh operation through the restarted
pair.

## Process cut

The initial requester sends reliable request sequence 1, a pure CPU program
whose result is 12. It durably writes a digest-checked client capsule containing
the exact pending request frame, next sender sequence, response receive cursor,
delivered set, and semantic result ledger. It blocks before receiving a result.

The receiver executes sequence 1 exactly once and publishes response transport
sequence 1. At the `after_response_publish` cut, before request consumption
and ACK, it writes an in-flight Transit session checkpoint. That checkpoint
contains the committed execution ledger, request receive cursor 1, and pending
response sequence 1. The receiver writes a marker only after the checkpoint
has been published.

The supervisor validates both markers and then hard-kills both original
interpreters. Neither process is allowed to survive or donate in-memory state
to its replacement.

## Independent restoration

The supervisor starts a new receiver interpreter first. It opens new TCP
listeners, restores the receiver-side session checkpoint, verifies the
execution journal, and verifies that response sequence 1 is still pending.
It retransmits that already-published response frame.

A new requester interpreter then opens new client streams and restores its
request and response channels from its own checkpoint. It retransmits the
exact original request sequence 1.

The restored receiver's execution ledger returns the committed effect without
entering the replacement backend. This creates a second reliable response
frame for the same semantic operation. The new requester therefore observes
the stored response as a fresh delivery and the replay response as a semantic
duplicate.

After acknowledging request sequence 1 and both response frames, the requester
sends new sequence 2. The new receiver executes that operation once and returns
42. Both processes finish with their reliable windows drained and the receiver
journal valid.

## Expected accounting

| Transition | Result | Backend entries |
|---|---:|---:|
| Sequence 1 before both processes die | 12 | 1 |
| Stored response retransmitted | 12 | 0 |
| Execution-ledger replay after joint restart | 12 | 0 |
| New sequence 2 after joint restart | 42 | 1 |
| **Total** | — | **2** |

## What this establishes

- The original requester PID differs from the restored requester PID.
- The original receiver PID differs from the restored receiver PID.
- Both independent checkpoints were durably written before either process
  was killed.
- The client capsule preserves the exact pending request and receive cursor.
- The receiver checkpoint preserves the committed effect, request cursor, and
  unacknowledged published response.
- Neither restored process receives memory state from its predecessor.
- The new requester observes one fresh delivery and one semantic duplicate
  for sequence 1.
- The receiver backend is not re-entered for the committed operation.
- A new operation returns 42 and executes once after joint restart.
- All request and response ACKs drain, and the receiver journal verifies.

## Proof boundary

Both OS processes are terminated and recreated, but the two checkpoints live
on the same local test filesystem and are independently restored. The SHA-256
client envelope detects accidental modification; neither digest is an
authentication mechanism.

This does not prove power-loss or storage-controller durability, anti-rollback
protection, malicious checkpoint resistance, distributed consensus, or
exactly-once semantics for arbitrary external side effects. The workload is
pure CPU computation, with no external side effects to reconcile.

## Run

    python -m pytest tests/test_joint_process_recovery.py -q
    python scripts/verify_invariants.py
    python scripts/verify_repo.py
