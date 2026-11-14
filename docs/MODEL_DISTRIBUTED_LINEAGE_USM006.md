# USM-006 — Native remote recovery authorities for a model-operated Ground

**Experiment status:** proposed code and tests; GitHub Actions result required.

USM-005 already exercises a hard receiver-process death after a committed
model-controlled structural-memory read but before its reliable ACK. Its
original quorum anchor uses three journal files on the same model-operation
runner. USM-006 asks a sharper question: **can the receiver be replaced while
its two non-owner quorum authorities run as separate, continuously surviving
OS processes over authenticated MailCPU streams?**

The answer must come from actual test execution, not the setup alone.

## Principle: integrate, do not clone

This implementation reuses the following *existing E-CPU classes*:

- `RecoveryLineageAuthorityService`: supervises one remotely running
  authority with a durable member journal and authenticated owner identity.
- `RecoveryLineagePeerClient.connect_mutual_tls`: binds remote member
  authority to one CA-verified, DNS-pinned TLS stream.
- `DistributedRecoveryLineageCoordinator`: coordinates a fixed quorum with
  local owner A and remote service processes B/C.
- `RecoveryStateManifest`, `RecoveryLineageAuthority`, and
  `SeedCommitMembership`: retain monotonic state identity and admission.
- `StructuralMemoryRegistry.from_snapshot` and
  `ReliableChannel.from_snapshot`: preserve Ground and message continuation.
- `GroundSystemCallSession`: the model's typed observed/propose/read contract.

There is no new consensus, network framing, TLS protocol or independent event
authority in `examples/model_distributed_lineage.py`. That module is only
configuration, service wiring, test certificate generation, and orchestration.

## Operation

```text
                           Test machine (one physical failure domain)

  Model host process                 E-CPU receiver process #1
         |                            | authenticates model
         | -- observe/propose/read -->| creates Ground, navigation receipt
         |                            |
         |                            | seal generation 1 with owner A
         |                            |     + mTLS member B process
         |                            |     + mTLS member C process
         |                            |
         |                    hard exit before ACK
         |  outstanding read(seq=3)   | 
         |                            E-CPU receiver process #2
         | -- same read(seq=3) ------>| reconnects A, B, C
         |                            | verifies quorum high-water
         |<-- same result + receipt --| replays receipt, no Ground reentry
         |                            | seal generation 2 on A, B, C
```

All three authority journals are in separate files. Members B and C use
separate Python interpreters and TLS certificate identities, and remain
running across the death and replacement of the receiver. The replacement
checks the *remote* journal state and commits a second generation. After all
services stop, a new local reader independently reopens the three durable
journals and verifies that generation 2 is the high-water.

The existing USM-005 default mode, using in-process journals, remains
available unchanged for regression and comparison. Remote mode is enabled
by a strictly validated **receiver-owned configuration file** under the
recovery checkpoint directory.

## Reproduction

```bash
python -m pytest -q tests/test_model_distributed_lineage.py
python -m examples.model_distributed_lineage demo --output usm006-report.json
```

The tests verify remote service identity, distinct OS process identities,
survival across receiver replacement, native model/E-CPU effect continuity,
post-shutdown durable quorum reconstruction, rejection of a changed configured
DNS identity, and fail-closed quorum commitment when both remote authorities
are absent. This last case is intentionally negative: A alone cannot
commit a recovery manifest.

## Explicit evidence boundaries

Three **process** failure domains are not three **physical** failure domains.
All services currently run on a single GitHub runner and the checkpoint
journal files share a filesystem. The output therefore declares
`single_physical_failure_domain=true`.

Member identity authentication is real TLS over real loopback TCP.
It does not establish cross-physical-host reachability, a secure multi-tenant
sandbox, or encrypted storage. No certificate private keys are placed into
the retained report. TLS test keys are created for the experiment and
discarded with its temporary directory.

The model is still the deliberately high-request crash-cut controller from
USM-005, not a new general-purpose model that has learned recovery policy.
The source is a deterministic finite mathematical fixture. The committed
Ground's witness evidence is not a universal proof of an infinite law.
The crash cut is precisely after the durable generation-1 quorum seal and
before the model's reliable ACK.

This **does not yet fence two competing receiver owners**. E-CPU's
fixed-membership `owner_id` and `owner_term` are preserved, and this
experiment replaces a dead owner process sequentially with the same
configured authority. A real competing-owner handoff needs a newer,
quorum-authorized owner epoch and per-effect active-owner checks, not just
a stale process checking its own cached term.

## Related prior work

- E-CPU `tests/test_recovery_lineage_service.py`: mTLS authority services,
  disconnection, partition, and owner restart.
- E-CPU `tests/test_recovery_lineage_process.py`: remote durable vote and
  commit behavior after process termination.
- E-CPU `tests/test_receiver_only_process_recovery.py`: receiver loss while
  requester state survives.
- IFS `bridges/proof-attention/proof_action_route_epoch.py`: fenced route
  epochs and handoffs, requiring a shared durable authority for production.
- IFS `bridges/proof-attention/sqlite_route_epoch_store.py`: single-host
  SQLite compare-and-swap authority (not a multi-host consensus service).

A next experiment should integrate the existing route-epoch and owner fencing
concepts with E-CPU's distributed quorum authority, rather than treating
model inference as permission to change ownership.
