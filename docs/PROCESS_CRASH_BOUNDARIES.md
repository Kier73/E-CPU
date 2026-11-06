# Independent-process recovery at every Transit transaction cut

## Purpose

The earlier process experiments prove genuine requester/receiver termination at
selected boundaries, and the in-process recovery suite exercises all four
Transit worker hooks. This experiment joins those proofs: both independent
processes are hard-killed after a durable checkpoint at each transaction cut,
then restored into new interpreters over fresh TCP transports.

## Crash-cut matrix

| Cut | Receiver state at death | Backend entries before death | Expected recovery |
|---|---|---:|---|
| \`before_execution\` | Request observed and authorized; effect not committed | 0 | Execute sequence 1 once |
| \`after_execution_commit\` | Effect committed; response unpublished; request unacknowledged | 1 | Replay sequence 1 without backend entry |
| \`after_response_publish\` | Effect committed; response pending; request unacknowledged | 1 | Retransmit stored response and replay request; suppress semantic duplicate |
| \`after_request_ack\` | Effect committed; request consumed and ACK sent; response still pending | 1 | Retransmit stored response; acknowledge late duplicate request; suppress semantic duplicate |

At every cut, the requester has independently fsynced the exact pending request
frame and its response-channel receive cursor. The receiver independently
fsyncs its Transit session checkpoint. Both original interpreters are then
hard-terminated. Replacement processes receive no Python objects or memory
from their predecessors.

## Recovery protocol

The restored receiver binds new TCP listeners and restores only its own
checkpoint. If the checkpoint contains a published response frame, it
retransmits that exact reliable frame. The restored requester binds fresh
client streams, restores its two reliable channels and semantic result ledger,
and retransmits the exact original request identity.

For the pre-execution cut, the operation enters the backend for the first
time after restart. For the other three cuts, the hypervisor execution ledger
returns the previously committed effect without backend re-entry.

At the published-response and post-request-ACK cuts, the stored response and
the replay response are distinct reliable transport frames for one semantic
operation. The requester accepts the first as a fresh delivery and marks the
second as a semantic duplicate. At every cut, sequence 2 then executes as new
work and returns 42.

## Expected accounting

Across every individual cut, the combined backend-entry total is exactly two:
one execution for sequence 1 (before death or after recovery, depending on the
cut), and one fresh execution for sequence 2.

| Cut | Sequence 1 before death | Sequence 1 after restore | Sequence 2 after restore | Total |
|---|---:|---:|---:|---:|
| before execution | 0 | 1 | 1 | 2 |
| after execution commit | 1 | 0 | 1 | 2 |
| after response publish | 1 | 0 | 1 | 2 |
| after request ACK | 1 | 0 | 1 | 2 |

## What this establishes

- Both requester and receiver are actual child interpreters and both are
  hard-terminated at each named transaction cut.
- Each side independently persists and restores its own protocol state.
- The request identity and reliable cursors survive process replacement.
- An uncommitted request executes once after recovery.
- A committed operation is replayed without backend re-entry.
- A stored response is retransmitted when publication preceded the crash.
- A request retransmitted after its ACK is consumed as a late duplicate.
- Distinct response transport frames for one operation are suppressed by the
  requester's semantic result ledger.
- A new operation succeeds after every recovery topology.
- Both reliable windows drain and the restored execution journal verifies.

## Proof boundary

This is a loopback-TCP and local-filesystem process-death experiment with a
pure CPU workload. It does not simulate power loss, storage-controller failure,
authenticated checkpoint storage, anti-rollback protection, distributed
consensus, or exactly-once arbitrary external side effects.

Checkpoint digests detect accidental modification but are not authenticated
and do not prove that a checkpoint is the newest valid generation. Recovery
lineage and a separately protected high-water authority remain separate work.

## Run

    python -m pytest tests/test_process_crash_boundaries.py -q
    python scripts/verify_invariants.py
    python scripts/verify_repo.py
