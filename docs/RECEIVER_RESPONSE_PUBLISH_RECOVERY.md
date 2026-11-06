# Response-published / request-unacknowledged recovery

## Purpose

The receiver-only subprocess proof has two distinct transaction cuts:

1. execution committed, response not yet published, request not acknowledged;
2. response already published and received by the requester, request not yet acknowledged.

This experiment exercises the second cut. The requester has already observed the first result before the receiver process is terminated. Both ends therefore hold partial but complementary protocol facts: the client has advanced its response receive cursor and stored a semantic result identity, while the receiver has not consumed the request or emitted its request ACK.

## Process protocol

The test starts the receiver child in `prepare-published` mode. It sends one pure CPU job as reliable request sequence 1. At the `after_response_publish` hook the receiver:

- has committed the execution effect in its hypervisor ledger;
- has published response transport sequence 1;
- still has request transport sequence 1 at the receiver's queue head;
- has not consumed that request or emitted its ACK;
- has response transport sequence 1 pending acknowledgement.

It writes a receiver-only session checkpoint and a marker, then blocks inside the hook.

The independent requester receives the already-published response before it kills the receiver. It validates the result, translation evidence, and oracle evidence. Its in-memory response-channel snapshot now contains the delivered transport cursor and the semantic result identity in its `seen` ledger. Its request sender still has sequence 1 pending because the receiver has not ACKed it.

After hard-killing the receiver, the requester reconnects over fresh TCP streams and restores its own channel wrappers from those in-memory snapshots. It retransmits the exact sequence 1 request.

The restarted receiver restores the session checkpoint. The execution ledger replays the committed effect without invoking the replacement CPU backend. The replay publishes another transport result for the same semantic operation. The receiver then retransmits the original response transport sequence 1, which was pending at the saved cut.

The requester must recognize both returned results as semantic duplicates. It acknowledges both reliable response frames, allowing the receiver to clear both pending response sequences. It then submits a new request sequence 2 and receives answer 42 through the recovered path.

## Expected accounting and invariants

| Transition | Expected result | Backend entries |
|---|---:|---:|
| Sequence 1 before receiver kill | 12 | 1 |
| Sequence 1 execution-ledger replay after restart | 12, semantic duplicate | 0 |
| Original published response sequence 1 retransmitted | 12, semantic duplicate | 0 |
| New sequence 2 after recovery | 42, fresh result | 1 |
| **Total** | — | **2** |

The test requires:

- the requester PID to survive unchanged while the receiver PID changes;
- the first response to be observed before receiver termination;
- request sequence 1 to remain pending at the requester and unacknowledged by the receiver at the cut;
- the requester response receive cursor and semantic result identity to survive in memory;
- the restored receiver to replay the effect without a replacement-backend call;
- both post-restart responses for the prior operation to be marked replayed by the requester result wrapper;
- both reliable response frames to be acknowledged;
- the new operation to return 42 and execute exactly once;
- the receiver execution journal to verify.

The semantic duplicate flag is not the same as the reliable transport sequence. Two distinct response transport sequences can carry one semantic operation identity; the result wrapper must suppress them as repeats of the already-observed event.

## Proof boundary

The requester stays alive in the supervising pytest process. Its channel snapshots are held in memory, not persisted to a client-side disk checkpoint. The test uses deterministic pure CPU jobs and does not prove exactly-once behavior for external side effects. It does not simulate power loss, kernel failure, filesystem corruption, or malicious storage.

This experiment complements the receiver-only execution-commit-before-publish test. Together they cover two adjacent transaction cuts but do not yet test every possible instruction-level or storage-level crash point.

## Run

    python -m pytest tests/test_receiver_only_process_recovery.py -q
    python scripts/verify_invariants.py
    python scripts/verify_repo.py
