# Persistent VGI Session Composition over the Computational Fabric

## Purpose

This document records the first end-to-end composition of M5-M7 persistent VGI sessions with authenticated multi-hop computational forwarding. It answers a deliberately narrow question:

> Can a source host transfer a bounded persistent VGI session through a communication path, have a distinct destination host admit it under the original identity and quorum lineage, and continue the computation without changing its meaning or replay behavior?

The experiment composes existing owners rather than introducing a separate migration authority:

- A owns the source VGI session and exports its M7 transfer bundle.
- B is an authenticated relay. It advances the route and performs local NETWORK admission, but it does not decode the VGI session.
- C is the terminal logical host. It admits the M7 transfer into its local M1 backing, verifies the M3 lineage and the exact VGI interpretation, then advances one bounded M4 quantum.
- C's Virtual Layer and Hypervisor independently admit the terminal operator. The route witness remains non-authoritative.

The implementation is `mailcpu/computational_fabric_vgi.py`; the integrated exercise is `test_persistent_vgi_session_transfers_through_fabric_and_replays_once` in `tests/test_computational_fabric.py`.

## 1. Typed stream request

The sender builds a normal `VirtualLayerWorkload`. Its input value contains a typed VGI quantum request:

\[
Q=(schema,\ bundle,\ q)
\]

where `bundle` is an M7 `VGISessionTransferBundle` mapping and \(q\) is the requested bounded VGI instruction quantum. The workload separately binds:

- the E-CPU System Ground and causal frontier;
- the destination operator contract and version;
- the VGI Computational Ground and Program fingerprints used by the destination advertisement;
- the declared workload logical time;
- energy, bytes, and virtual-time ceilings;
- eligible destination node and maximum network hops.

The semantic M4 operation identity is derived from the workload digest, source session ID, descriptor digest, M7 bundle digest, source revision/checkpoint digest, and requested quantum. It is not a TCP frame number. Repeated delivery of the same typed request therefore retains the same semantic operation identity even when the reliable transport retransmits a frame.

At each NETWORK hop, the forwarding receiver separately derives a compact control-plane projection from the complete forwarding envelope. This keeps route interpretation bounded while the full envelope, transfer bytes, and semantic operation identity remain bound to the event fingerprint. At C, the Virtual Layer independently recomputes its workload/input projection before CPU capability admission. The NETWORK projection describes the communication transition; the Virtual Layer projection describes the computation.

## 2. Receiver-side composition

At C the terminal VLayer operator follows this order:

1. Bound and canonically decode the M7 bundle. The Virtual Layer control-plane intent projection carries the workload goal and full input/workload digests, while the Hypervisor event retains the complete payload.
2. Before local capability admission, C reconstructs and exactly compares that projection against its received workload, input, operator contract and resource bounds.
3. Verify the complete bundle digest and exact descriptor mapping against C's locally admitted `VGICompiledSessionDescriptor`.
4. Extract the M3 checkpoint and confirm its session ID, revision, and checkpoint digest.
5. If the session has no local latest checkpoint, import the exact state bytes through C's own M1 object store and require the admitted manifest to equal the source manifest.
6. Verify the source recovery manifest and quorum proof against C's local view of the same fixed recovery membership.
7. Confirm that C is at the exact source CAS base, or at the exact immediate successor of this same semantic quantum for a retry. Reject unrelated advancement.
8. Invoke `VGIPersistentSession.advance()` with the source revision/checkpoint as compare-and-swap preconditions and logical time incremented once.
9. Return a typed receipt binding the original session and interpretation to the new revision, checkpoint, lineage digest, predecessor checkpoint, backend profile, state schema, logical time, and replay status.

The VGI machine is reconstructed from canonical state under the locally admitted Ground and Program. Python handlers, PIDs, capabilities, and source process objects do not travel inside the session bundle. C must bind its own local operator handler and capability process.

## 3. Identity continuity and replay

The receipt deliberately keeps distinct identities:

| Coordinate | Required continuity |
|---|---|
| Session identity | Exact M3 session ID |
| Semantic descriptor | Exact Ground, typed TaskSpec, Program IR, implementation and interpretation fingerprints |
| Artifact identity | Exact M2 artifact manifest digest |
| State format | Exact M3 state schema and media type |
| State lineage | Source checkpoint's recovery manifest and quorum proof |
| CAS predecessor | The exact source revision and checkpoint digest |
| Continuation | One successor revision with the same predecessor and the derived M4 operation identity |
| Logical time | Source checkpoint logical time plus one |
| Backend | Source producer profile retained for the restored state; target profile recorded on the first migrated transition if compatibility approval is used |
| Transport | New hop/transport sequences may differ; semantic operation identity does not |

Three separate retry boundaries are checked:

- **M3/M4 session retry:** the exact semantic quantum returns the already committed successor checkpoint and does not rerun the VGI transition backend.
- **Terminal CPU/Hypervisor retry:** the C execution ledger returns its cached result, so the operator handler is not invoked twice.
- **Relay forwarding retry:** B may re-enter its local NETWORK forwarding transition after process recovery. Its downstream client and C's terminal receipt ledger preserve the original semantic request, so the terminal effect is not repeated.

The third distinction matters: a relay re-forward is not the same thing as repeating the terminal computation. The exactly-once claim is confined to the deterministic pure terminal operation and the stored M3 transition identity under the exercised crash cuts. It is not a claim of exactly-once arbitrary external side effects.

## 4. Measurements collected

`VGIFabricSessionOperator.last_measurement` records bounded receiver-side measurements for the most recent semantic quantum:

- transfer bundle byte extent;
- exact VGI state byte extent;
- M7 bundle decode time;
- target M1 import plus M3 lineage verification time;
- M4 transition, M1 persistence, and M3 quorum commit time;
- total operator handler time;
- whether the M1/M3 session was imported during this call.

The end-to-end test separately measures source M7 export, complete A→B→C forwarding round trip, and a full target M1 manifest verification. The test emits a `FABRIC_VGI_MEASUREMENTS=` JSON line when run with output capture disabled, for example:

```sh
python -m pytest -q -s tests/test_computational_fabric.py::test_persistent_vgi_session_transfers_through_fabric_and_replays_once
```

These are observed wall-duration measurements for the test environment, not abstract operation costs or portable performance guarantees. Compare them with the same host, Python/runtime version, page size, payload size, fixed quorum topology, and warm/cold storage conditions. The per-operator fields isolate target-side stages; the end-to-end forwarding measurement includes transport, queueing, relay admission, and result receipts.

## 5. Demonstrated boundary and remaining work

The experiment uses a small deterministic Signal8 addition task and a two-edge loopback TLS path. It demonstrates that:

- A and C use independent M1 page backings;
- C can import the exact source state while preserving the original session and artifact identity;
- M3 validates the original fixed-membership quorum root at the destination;
- the destination restores the exact declared VGI Ground and Program;
- C advances a new bounded quantum and commits a successor M3 revision with the expected predecessor and logical time;
- repeated delivery returns the same forwarding result, and terminal execution is not re-entered.

It does not yet demonstrate a WAN-scale topology, arbitrary page geometry conversion, streamed M1 page transfer, membership reconfiguration, a target without the source quorum lineage, hardware attestation, neural/tensor partitioning, or exactly-once behavior for arbitrary side effects.

The current M7 wire form embeds bounded state bytes as base64 in one JSON transfer object. This is appropriate for the small proof but creates a payload-size and duplicate-materialization cost. The next data-plane improvement should transmit M1 pages as independently bounded content-addressed chunks while the control stream carries the manifest, descriptor, M3 proof, CAS base, and operation identity. That change should preserve the same admission and replay contracts and should be justified by measured serialization, transfer, verification, and storage costs.

The broader development direction is a fabric in which receivers are interpreters and state-transition hosts: communication locates and composes available capabilities; it does not perform semantic work merely by transporting bytes. The host boundary remains the point where meaning, authority, resource bounds, and durable state are independently established.
