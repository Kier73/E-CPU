# Persistent Computational Sessions and State

## Status

M3 builds persistent, versioned computational state over the merged M0/M1 object substrate and M2 local-host identity.

The implementation reuses two existing foundations:

- ComputationalObjectStore stores each immutable state byte sequence in M1 pages.
- RecoveryStateManifest and RecoveryLineageCoordinator determine which session revision is the quorum-anchored high-water mark.

M3 does not create a second page store, checkpoint quorum, clock, or transport protocol.

## 1. Session identity and isolation

A computational session is a continuing state lineage attached to one immutable computational artifact:

\[
\mathcal{S}=(I_S,I_A,G_S,B_S,\{C_r\}_{r\ge1})
\]

where:

- \(I_S\) is the stable session identity;
- \(I_A\) is the immutable artifact manifest digest;
- \(G_S\) is the domain-specific state schema identity;
- \(B_S\) is the backend implementation profile for the execution that produced a revision;
- \(C_r\) is the immutable checkpoint at revision \(r\).

A session is not the backend process, host, TCP connection, or memory allocation. Those may change while the same session identity and state lineage continue.

The current implementation deliberately assigns one existing fixed SeedCommitMembership to one session:

\[
\text{membership.system\_id}=I_S
\]

Each session therefore has its own generation counter, predecessor chain, and authority journal set. Advancing session A cannot advance or roll back session B. The fixed membership and owner term remain stable for that session's lineage; membership reconfiguration is not part of M3.

## 2. State bytes remain domain-neutral

M3 does not interpret the state payload. It accepts exact bytes and stores them using M1:

\[
O_r=\operatorname{Put}_{M1}(s_r)
\]

The M1 object manifest binds the state bytes' content digest, logical extent, media type, page geometry, and ordered page references. The domain-specific state schema identifier is bound separately into the computational checkpoint.

This permits state to represent a model session, emulator register/memory image, virtual CPU context, numerical solver, database execution context, or another explicitly defined computational state. Their layouts and semantics remain domain-owned.

Large state remains in the page/object plane. The session checkpoint and Virtual Layer messages carry bounded references and identities, not the full byte payload.

## 3. Immutable checkpoint identity

For each revision \(r\), the checkpoint binds:

\[
C_r=\operatorname{Canonical}
\left(
I_S,I_A,B_r,G_S,r,H(C_{r-1}),\rho_{r-1},O_r,
q_r,op_r,h(x_r),t_r
\right)
\]

where:

- \(H(C_{r-1})\) is the previous checkpoint digest (the configured genesis digest for revision one);
- \(\rho_{r-1}\) is the predecessor quorum-lineage root (the configured genesis digest for revision one);
- \(O_r\) is the M1 manifest for this revision's state bytes;
- \(q_r\) is the transition/request identity;
- \(op_r\) is the domain operation identity;
- \(h(x_r)\) is the caller-supplied input commitment;
- \(t_r\) is the existing workload logical-time coordinate.

The checkpoint identity is:

\[
h_r=\operatorname{SHA256}(C_r)
\]

The checkpoint is immutable. A new state is a new object and a new checkpoint; it does not overwrite the previous state pages or revision descriptor.

No wall-clock timestamp or process-local monotonic duration is inserted into the checkpoint identity. Logical time is the E-CPU workload coordinate, not a newly invented global clock.

## 4. Quorum anchor and current-state selection

M1 provides immutable state bytes, but the existence of a local file or page manifest does not establish that a revision is current.

M3 wraps the canonical checkpoint bytes in the existing single-state recovery manifest:

\[
R_r=\operatorname{RecoveryStateManifest}
\left(
I_S,\text{incarnation},\text{owner},\text{term},
\text{membership},r,p_{r-1},\operatorname{SHA256}(C_r)
\right)
\]

The existing RecoveryLineageCoordinator translates this into the already-tested fixed-membership seed-commit proposal and records a strict-majority prepare certificate and commit decisions.

The recovery root is:

\[
\rho_r=\operatorname{SHA256}(\operatorname{Canonical}(R_r))
\]

The current session state is not selected by the largest local revision number or a mutable latest pointer. It is selected by the quorum-supported lineage high-water \((r,\rho_r)\). load_latest() resolves that exact record, verifies the recovery manifest, verifies the checkpoint bytes, then resolves and verifies the complete M1 state object.

The recovery authority journals must remain outside the rollback domain of the session checkpoint files and page data. If all of them are rolled back together, the independent high-water evidence is also rolled back.

## 5. Atomic continuation with compare-and-swap

A caller computes a candidate successor state from its observed snapshot. It submits the candidate with both expected coordinates:

\[
(r_{\mathrm{expected}},h_{\mathrm{expected}})
\]

The store admits the transition only when the current quorum-anchored session has exactly that revision and checkpoint digest:

\[
\operatorname{CAS}(r,h)=
\begin{cases}
\operatorname{anchor}(C_{r+1}) &
  \text{if }(r,h)=(r_{\mathrm{current}},h_{\mathrm{current}})\\
\operatorname{refuse} & \text{otherwise}
\end{cases}
\]

The successor checkpoint names both the prior checkpoint digest and prior recovery-lineage root as separate fields, and the recovery manifest repeats that exact predecessor lineage root. Competing writers may prepare different candidate state objects, but the fixed-membership one-vote-per-slot and strict-majority intersection permit at most one of those candidates to become the committed high-water under the same membership term. A losing or stale writer cannot overwrite the winner.

The caller-supplied transition identity, operation identity, input digest, logical time, and resulting state digest are also committed. An exact retry of the immediately preceding transition returns the same revision as a replay. Reusing a transition identity with different input or state bytes is refused.

This is a state-publication boundary. The store does not execute the domain transition function and does not atomically commit arbitrary external side effects. A caller that computes state through a backend must keep that computation replay-safe or use the existing Hypervisor effect/commit contract for external effects.

## 6. Durable publication order and recovery

The commit order is intentionally one-way:

1. Publish the candidate state bytes through M1.
2. Verify the complete state object.
3. Construct the canonical checkpoint and RecoveryStateManifest.
4. Write the immutable checkpoint envelope and fsync the file and session directory.
5. Prepare, certify, and commit the recovery root through the existing quorum lineage.
6. Re-read and verify the exact quorum high-water before returning the committed snapshot.

There is no mutable current-state pointer. A candidate envelope written before quorum commitment is not returned by load_latest().

### Crash and retry cases

| Crash boundary | Recovery behavior |
|---|---|
| During M1 page admission | Any already written pages remain immutable CAS material; no checkpoint or quorum root is published. |
| After M1 verification, before checkpoint envelope fsync | No checkpoint is available for quorum sealing. |
| After checkpoint envelope fsync, before any prepare vote | The envelope is not current. It may remain as an unanchored local artifact. |
| After a minority prepare or commit | The exact prepared proposal and certificate are reused; a different proposal at the occupied slot is refused. resume_pending() completes the original proposal when a quorum is available. |
| After quorum commit, before response delivery | load_latest() selects the new revision; an exact immediate retry returns that revision as replayed rather than creating another one. |
| During host replacement | The new host imports the checkpoint envelope and quorum proof, verifies the same high-water, then resolves the M1 state pages through its configured page backing. |

If competing conflicting proposals occupy the same session revision, M3 fails closed. The existing fixed-membership protocol does not silently rewrite the occupied slot. Resolving such a conflict requires the existing recovery/membership lifecycle rather than inventing a new generation locally.

## 7. Recovery across host changes

export_latest() exports:

- the immutable computational checkpoint;
- its RecoveryStateManifest;
- the existing RecoveryLineageProof.

It does not embed the state bytes. Those remain in M1 pages, which the target host must be able to resolve through a shared or replicated page backing.

restore_export() verifies that the exported proposal and certificate match the target's locally verified quorum high-water, and that the complete state object is readable and matches its content identity.

Recovery requires an exact artifact identity and state schema identity. A different backend fingerprint is refused by default. A target may supply an explicit compatibility predicate:

\[
K(B_{\mathrm{source}},B_{\mathrm{target}},G_S)\rightarrow\{\text{true},\text{false}\}
\]

Only an affirmative result permits the state to be admitted on the target. M3 does not infer device, precision, runtime, or state-layout compatibility. The next committed revision records the target backend fingerprint, making the migration explicit in the lineage.

A compatible backend profile is not hardware attestation. A compatibility callback is a local policy decision; production deployments may want it backed by a versioned, auditable compatibility contract.

## 8. Implemented and unimplemented boundaries

M3 implements:

- a session identity isolated by its own fixed recovery membership;
- immutable, versioned checkpoint manifests bound to M1 state objects;
- quorum-anchored current-state selection through RecoveryStateManifest;
- compare-and-swap continuation using expected revision and checkpoint digest;
- exact immediate-transition retry recognition;
- durable checkpoint envelope publication before quorum commit;
- resume of an exact pending proposal after partial quorum commit;
- portable checkpoint/proof export and restore through existing M1 pages;
- explicit backend compatibility gating during host replacement.

M3 does not yet implement:

- a global session catalogue or automatic placement/resolution of session ownership;
- membership reconfiguration or authority migration for a session;
- backend execution semantics for a domain-specific state transition;
- an atomic transaction between state anchoring and arbitrary external side effects;
- automatic replication or transfer of the M1 state pages;
- state schema conversion;
- a policy for concurrent stateful requests beyond revision CAS and fail-closed quorum slot conflicts;
- a universal interpreter for state bytes.

The next useful extension is a domain-neutral transition adapter that consumes a verified session snapshot, computes a candidate successor state under a declared transition contract, and submits it through this CAS boundary. Replicated and partitioned hosting can then share the same session identity and revision semantics.
