# SAB-012 — Receiver-native formation and quorum-backed Ground continuity

**Status:** research integration; native Hypervisor, mutual-TLS, and recovery-lineage CI must pass before claims of end-to-end verification. This is a bounded affine Ground demonstration, not a generic arbitrary-code distribution system or an attestation of independent physical hosts.

## Research question

Can E-CPU **form** an operator on an independently authenticated receiving process *behind that receiver's own Hypervisor admission*, execute a host-independent mathematical intention, retain its result through a separately qualified relay/storage topology, and restore that accepted observation after compute/relay processes disappear using a distinct quorum-backed recovery authority?

The experiment composes rather than replaces:

- **SAB-008/009:** host-independent affine Ground and trusted seed generation on a receiving interpreter.
- **SAB-010:** compile a formed-seed realizer from separately bound `program.stage` and `program.activate` primitives.
- **SAB-003/004:** empirical role qualification, typed placement, immutable readback, replicated checkpoint and separate durable decision records.
- **SAB-005:** pinned mutual-TLS direct-peer transport, caller identity and receiver-local fixed-opcode allowlists.
- **Native E-CPU:** `VirtualLayerRuntime.execute_operator`, `HypervisorAction.ALLOW`, and `RecoveryLineageCoordinator` over `RecoveryStateManifest` and durable seed-commit journals.

## Distinct authorities and commitments

```text
Origin intention: Ground + coordinate + observation (no executable source)
     |
     v  authenticated mutual-TLS request; receiver DNS SAN + client SAN
Pinned receiving service: receiver-fixed Ground, engine and operation allowlist
     |
     v  native receiver Virtual Layer + Hypervisor checks compute capability
Authorized installed handler: locally constructed stage + activate primitives
     |
     v  compile trusted E-CPU seed; stage and challenge in receiver directory
Receiver observation: exact affine value + formed-seed evidence
     |
     v  independent Ground oracle and content-bound receiver audit
Origin: retrieve proof over a *separately allowed* mTLS proof operation
     |
     v  SAB-004 qualified relay + two independently stored/read-back data copies
Immutable checkpoint + separate commit decision: not an external quorum
     |
     v  re-read committed data from an admitted storage receiver
RecoveryStateManifest: SHA-256 of complete retained semantic state
     |
     v  native RecoveryLineageCoordinator majority prepare + durable COMMIT
Quorum high-water: accepted state root; recovery rejects rollback and mutation
```

A **remote request never supplies executable source, a shell command, a CPU capability, or the formation policy**. The receiving service starts with a locally fixed affine Ground and interpreter; the compute operator's handler constructs the SAB-010 primitive inventory from that *receiver-owned* stage/activate pair. No stage or activation is performed before its local Hypervisor permits the operator. The experiment uses a fresh HeadlessOS/Virtual Layer per operation, as SAB-005 does; this is not yet the long-lived general ComputationalExecutionAdmissionCoordinator path.

`ReceiverFormingTLSServer` extends the existing pinned-TLS listener. Only the receiver's CLI can enable `formation_proof`; a separately authenticated client queries a digest-bound, locally retained audit *after* computation. `AttestedFormedEndpoint` refuses returned computation results without a proof bound to the exact request and verified TLS receiver. The proof is receiver-authored provenance, **not** a hardware attestation or externally signed proof that a malicious receiver honestly executed a handler.

## Accepted state construction

`FormedFederatedController` requires a TLS-attested formed compute endpoint but delegates actual execution/replication to SAB-004. It refuses stale plans and accepts the result only when the receiver Hypervisor's ALLOW/executed evidence, formed Ground, independent mathematical result, and SAB-004 checkpoint/decision agree.

`FormedQuorumAnchor.seal()` **first** re-reads SAB-004's committed checkpoint from an available storage host. It writes the exact retained semantic state bytes and a typed recovery state manifest to local fsynced files, then asks E-CPU's existing quorum authority to prepare and durably commit the manifest. A file staged before a majority decision is *not* a published result. `recover()` reads the bytes, checks the manifest payload digest, obtains the **latest** recovery-lineage proof from the strict-majority journals, rechecks the Ground and observation, and refuses valid but superseded generations.

Recovery across a restart is read-only. It does not need to restart the computing operator or relay and does not rerun semantic effects. This demonstration is pure deterministic affine arithmetic: it does **not** prove exact-once arbitrary side effects.

## Executable bounded test

The native CI scenario uses distinct short-lived certificates and OS processes for `compute-formed`, `relay`, `store-a`, and `store-b` plus a separately authenticated origin. The receiver's Python code engine starts without the Ground seed; the formed program is written only after receiver-local Hypervisor admission. The test uses three independently fsynced quorum journals (`A`, `B`, `C`), on the **same CI machine**, and restarts the survivor after killing compute/relay and another storage peer. It checks that the recovered observation remains **46,511** for `x(t+1) = (5*x(t)+7) mod 65,521`, `x(0)=19`, `t=10^12+913`.

The test also refuses wrong client certificate identity, a storage peer asked to compute, changed input Ground, revoked formation rights (including replay), a conflicting reuse of a request nonce, ungranted source dispatch, forged native evidence, changed retained bytes, and a mismatched recovery intention. Local portable tests may run without E-CPU's full native package; **skipped native tests do not count as passing native verification**.

## What is and is not established

- A TLS session is evidence of the expected configured peer certificate identity, **not** proof of independent hardware or honest execution by a compromised peer.
- Three fsynced authority journals in one test machine verify native quorum *protocol integration* but do **not** prove independent physical failure domains or network-partition safety. Future tests must place the authority members on separate machines and connect `RecoveryLineageTransport`.
- SAB-004's two storage replicas and commit-decision marker are **not** quorum consensus. The native `RecoveryLineageCoordinator` supplies the separate majority high-water for the final retained state.
- The relay is a real SAB-003 framed operation over SAB-005 mTLS, but cross-role orchestration still occurs at the controller. This is **not** yet `ComputationalFabricForwardingServer` multi-hop execution, native transfer claims, or automatic physical host formation.
- Code installation runs under a locally configured interpreter, not a security sandbox. Deploy only on explicitly authorized receivers. A passive information carrier never acquires execution permission by receiving data.
- The affine Ground is deliberately finite. General Ground inference, host construction over unknown physical media, autonomous policy changes, and distributed recovery remain in active development.

## Next question

Can a *formed* observer-host become a first-class local `ComputationalHostLocus` and participate in the normal `ComputationalFabricForwardingServer`, with actual `RecoveryLineageTransport` participants holding independently failing quorum journals? That is the next physical and architectural verification gate.