# Navigable Computation: Crash-Recovery Experiment

## Purpose

The preceding vertical slice composed Structural Memory, Transit CPU
execution, independent semantic oracles, and evidence-indexed path resolution.
This experiment challenges a stronger property:

> After a receiver restart, can the system reconstruct the same structural
> memory identity, committed CPU operation, route catalogue, and non-authoritative
> route, then replay the pending CPU operation without executing it again?

The answer is tested for one finite deterministic arithmetic workload, using
fresh TCP streams after restoring both requester and receiver protocol state.

## Persisted computation

The experiment admits the modular integer recurrence

\[
x_t=(13+9t) mod 251
\]

under context {tenant: recovery, partition: 12}. The receiver reads coordinate
t=23, obtaining x_23=220 with an immutable revision- and
certificate-bound receipt.

The receipt supplies an operand to the CPU program:

    set structural_value 220
    set bias 19
    add answer structural_value bias
    halt

The expected terminal register is answer = 239. The operation is executed
once by the receiver and committed with its Transit translation and independent
CPU oracle evidence.

## The combined checkpoint envelope

NavigableComputationCheckpoint composes state that previously belonged to
separate checkpoint surfaces. Its canonical, digest-bound envelope contains:

| Component | Recovered identity/state |
|---|---|
| Transit worker/session checkpoint | Receiver HeadlessOS state, kernel journal, Structural Memory registry, hypervisor decision and execution ledgers, backend manifest, worker request/result cursors |
| Client request channel | Requester send/receive cursors and semantic transport progress |
| Client result channel | Requester response cursors and already observed semantic results |
| Evidence path catalogue | Exact memory, bridge, and CPU translation edges, receipts, comparisons, oracle evidence, and declared costs |
| Route request and result | Exact endpoint identities, primary and accepted context digests, evidence/prerequisite/invariant gates, cost ceilings, and the selected non-authoritative route projection |
| Retry event | Exact CPU operation identity and payload that the requester may retransmit |
| Computation DAG (schema v3) | Bounded operation graph, immutable node revisions, already committed predecessor results, and the exact ready frontier reconstructed before runtime exposure |

Quiescent capture (schema v1) is allowed only at an idle boundary. In-flight
capture (schema v2) explicitly preserves reliable-channel cursors and may be
taken at a named transaction cut. Schema v3 adds the computation DAG to either
capture mode, binding its complete node/commit state under the same outer digest.
This does not make a multi-node DAG one atomic execution transaction; it makes
the selected graph state and protocol state one published recovery envelope.

The envelope is canonical JSON with a SHA-256 integrity digest. That digest
detects accidental or uncoordinated modification; it is not a digital
signature and does not authenticate an untrusted storage provider.

## Restore protocol

Restore requires fresh transports and a trusted backend factory.

1. Validate the outer schema and digest before reconstructing any runtime state.
2. Restore the receiver and worker checkpoint, rebind the registered backend
   manifest, and restore requester-side reliable channel cursors.
3. Reconstruct the content-addressed evidence catalogue and typed route query.
4. Re-authorize the saved retry event against the restored receiver's live
   capability table. Its exact authorized-event representation must occur as
   a source node in the persisted route catalogue.
5. When schema v3 includes a DAG, require exactly one ready node to match
   the retry event's operation, resource, context digest, and payload.
6. Re-run the evidence-path resolver using restored live capabilities.
   Restore is refused unless the result exactly reproduces the saved route
   projection.
7. Resubmit the same CPU event under the next reliable transport sequence.
   The hypervisor semantic execution ledger must return the original committed
   effect and evidence without entering the replacement CPU backend.

The checkpoint restores protocol and computation state, not the original TCP
connections. New authenticated transports are supplied by the caller.

## Falsifiable checks

The recovery experiments fail unless:

- the Structural Memory revision and receipt are restored exactly;
- the receiver's execution ledger and kernel journal survive restoration;
- client and worker reliable cursors continue on new streams;
- the catalogue digest and route request digest remain unchanged;
- the restored resolver finds the exact previously selected route;
- schema-v3 restore reconstructs the same DAG digest, committed receipt, and ready CPU frontier before retry;
- the saved retry event maps to the exact authorized CPU request representation;
- retransmission produces a semantic replay with the same effect, translation,
  and oracle evidence;
- the replacement CPU handler invocation count remains zero; and
- the journal verifies after replay.

A modified checkpoint envelope must fail its integrity check before transport
or runtime restoration is attempted.

## Proof boundary

This demonstrates deterministic same-process test harnesses simulating a
receiver/requester restart using JSON serialization, fresh TCP transports,
restored HeadlessOS state, a trusted local backend factory, and a combined
schema-v3 envelope containing the DAG. The graph frontier and reliable retry
state are reconstructed together. It is not a power-loss test, authenticated
remote checkpoint protocol, replicated durable catalogue, or adversarial
storage proof.

The envelope digest is not a signature or MAC. Production deployment would
need authenticated storage and transport, explicit key ownership, anti-rollback
policy, atomic durable publication of the combined checkpoint, host-specific
backend attestation, and a recovery policy for a checkpoint whose external
resources have changed.

The workload is still one deterministic Structural Memory family and one CPU
program. It does not establish universal translation, arbitrary program
recovery, route execution as one atomic transaction, GPU acceleration, model
hosting, or measured energy/latency.

## Run

    python -m pytest tests/test_navigable_computation_recovery.py -q
    python scripts/verify_invariants.py
    python scripts/verify_repo.py

The full repository CI matrix remains the merge gate.
