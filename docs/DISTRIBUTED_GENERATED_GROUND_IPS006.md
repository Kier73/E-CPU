# IPS-006 — Degraded mTLS authority recovery for intention-generated Grounds

**Scope:** Integrate the IPS-003 generated mathematical Ground, IPS-004 native Hypervisor and qualified host execution, and IPS-005 quorum-fenced publication with E-CPU's existing independently running mutual-TLS recovery authority services. No new quorum, voting protocol or runtime authority is created.

## Discovery and cross-repository reuse

E-CPU already implemented independent fixed-membership recovery processes, reliable peer clients, reconnecting mutual-TLS authority services, and typed RecoveryStateManifest checkpoint roots. Cross-repository inspection also found [IFS CGS-009](https://github.com/Kier73/In-Formation-Space/blob/main/experiments/contextual-ground-sections/CGS-009-ECPU-QUORUM-REUSE.md) and [IFS CGS-010](https://github.com/Kier73/In-Formation-Space/blob/main/experiments/contextual-ground-sections/CGS-010-REAL-MTLS-RECOVERY.md). CGS-010 independently demonstrates a killed owner process later recovering its original signed state from surviving E-CPU mTLS quorum and an external archive.

The missing seam for generated Grounds was reconnection with temporarily unavailable members. Previously, DistributedRecoveryLineageCoordinator required a transport for every configured authority during construction, even when the original owner and one remaining member already formed the unchanged strict majority.

## Minimal implementation

The coordinator now has an explicit opt-in with_available_peers constructor. It allows omitting disconnected non-owner endpoints from the *current connection mapping*, not from the immutable SeedCommitMembership. The configured owner, owner term, member identities, quorum threshold, and voting/commit checks are unchanged. Standard construction still requires all members.

The new generated_ground_authority_fabric.py adapter defines:

- PinnedRecoveryAuthority: exact remote member ID, address, port and certificate DNS SAN.
- connect_generated_ground_quorum: fixed owner journal and identity, explicitly configured peer set, certificate-validating SSLContext, bounded reconnect attempts, original IPS-003 plan and existing IPS-005 artifact directory.
- GeneratedGroundQuorumConnection: RAII-style ownership of authenticated streams, connected and unavailable peer reports, and the existing FencedGroundLineage publisher.

Every peer must be present in the *configured* set, even when temporarily unreachable. The adapter refuses duplicate IDs, unknown members, unverified TLS settings, and wrong DNS identities. The returned coordinator still fails closed when the live peers cannot establish a read or write majority. Remote reports do not issue native Hypervisor compute rights.

## Experiment A: host rehome and alternative authority majorities

1. The original 3-member A/B/C quorum seals a generated Ground and assigns its first stage to host W1.
2. W1 computes a correct IPS-004 native stage, but has no publication authority.
3. C is killed; a new owner-side coordinator binds authenticated A+B with the original quorum threshold two.
4. A+B seal a reassignment to W2. W1's correct-but-late candidate fails the latest-root check. W2 computes and publishes the new stage through the original IPS-005 fence.
5. B is also killed. With only owner A, recovery refuses despite intact local state artifacts.
6. Restart B and C on their own persisted journals. C, which lagged the newest head, catches up via the *original* exact recovery-lineage certificates and decisions.
7. Kill B. A+C, a different majority, now restore the exact latest Ground and publish the dependent second stage using another qualified host.
8. The resulting native DAG finishes the intended result 16. W1's displaced computation is absent from the published DAG.

Every remote authority is a real E-CPU TLS service child process with its own persistent journal, not a mock vote.

## Experiment B: hard-killed owner process and zero-checkpoint recovery

The test fixture ips006_owner_process.py runs the original owner in a separate operating-system process. It seals its own IPS-004 initial Ground state, fsyncs a readiness marker and continues running until the harness invokes a hard OS kill.

A *new process* starts with provisioned trust and membership, the protected owner authority journal, B/C peer identities and TLS credentials, and the separate content-addressed archive. **No original candidate checkpoint, checkpoint hash or session object is provided to that new process.**

With C still down, it must use authenticated A+B majority to discover the latest committed root, load that exact artifact and independently recheck the intended Ground. With B also down, the same recovery procedure must refuse as lacking read quorum.

This is same-owner-identity and same-owner-term recovery, not automatic election or configuration changes.

## Evidence and deployment limits

- The authorities are independently running OS processes with separate fsynced journals and distinct mTLS certificates, but CI runs them on one machine over loopback TCP. This is not proof of geographically independent failure domains.
- Checkpoint SHA-256 checks and quorum high water do not provide Byzantine consensus, malicious-storage protection or host hardware attestation.
- The owner and all authority journals must be protected against joint rollback; data artifacts are not their own freshness authority.
- Host assignment and publication fencing apply to **pure semantics**. A delayed stateful external write outside the majority-sealed publication resource needs its own receiver-side fencing token and atomic compare-and-swap or semantic effect ledger. The existing native publication path is protected; arbitrary third-party side effects are not.
- Physical execution still consumes CPU and network resources.
- No dynamic member admission, owner-term takeover, automatic network-wide discovery or independent physical-machine test is claimed.

The independent theory sources reinforcing the resource-side fencing requirement are [Martin Kleppmann, How to do distributed locking](https://martin.kleppmann.com/2016/02/08/how-to-do-distributed-locking.html) and [Google SRE, Managing Critical State](https://sre.google/sre-book/managing-critical-state/).

## Reproduction

    python -m pytest -q tests/test_generated_ground_authority_fabric.py

Dedicated CI includes the existing IPS-005 tests, the recovery-lineage suite and upstream mTLS authority service regressions on Linux/Windows Python 3.11/3.13. OpenSSL is required for fixture certificate generation; unavailable OpenSSL results in explicit skips rather than simulated network claims.

## Next research

Integrate configured peer identity with the authenticated E-CPU fabric directory without admitting remote advertisements as authority. Produce a compact, typed proof envelope of the quorum-sealed generated Ground for independent VGI/IFS verification, test owner-term rotation under an explicit authority-transfer protocol, and measure the cost of TLS, quorum round trips and duplicated pure work.
