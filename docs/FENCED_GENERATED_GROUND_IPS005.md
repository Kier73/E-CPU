# IPS-005 — Quorum-fenced generated Ground publication

**Status:** Experimental adapter integrating IPS-004 generated Ground execution with E-CPU's existing fixed-membership durable recovery-lineage quorum. It does not create another consensus implementation, grant rights to hypothetical relations, claim Byzantine agreement, or guarantee physical exactly-once execution.

## Question

IPS-004 showed that a generated virtual computation can outlive an observer-host process. IPS-005 investigates **late old-host publication**: when an unfinished stage is reassigned, can E-CPU preserve one authoritative result despite an earlier host returning the same correct mathematical value?

## Execution model

    Intention -> IPS-003 generated operator word -> IPS-004 native DAG
              -> Quorum-sealed initial state
              -> Quorum-sealed {stage, host, epoch, input checkpoint} assignment
              -> Assigned host computes pure stage (unpublished result)
              -> Optional quorum-sealed rehome to new host and epoch
              -> Publication requires the latest assignment
              -> Quorum-sealed completed DAG and verified receipts

A mathematical result computed on an obsolete assignment may still be correct, but cannot become the published result.

## Mechanisms reused

- RecoveryLineageCoordinator and RecoveryLineageAuthority: independently recorded fsynced votes and decisions, single owner, fixed membership and term, strict-majority prepare and commit quorums, exact generation and predecessor roots, durable high-water reads, and stale-state refusal.
- RecoveryStateManifest: binds one state artifact to the independent authority lineage. The state contains the original IPS-004 checkpoint, epoch and current assignment.
- QualifiedGroundExecution: the existing IPS-004 receiver Hypervisor-authorized pure computation, qualified SAB-003 endpoint, SAB-008 Ground observation, typed predecessor value and native NavigableComputationDAG. The IPS-005 adapter does not duplicate the execution runtime or authority.
- IPS-003: the exact generated mathematical operator word and the imposed Ground intention.

State and manifest artifacts are written as content-addressed files with file fsync before each quorum seal. The independent authority journals retain the monotonic root. A hash is not a signature, and the payload directory is not itself an independent high-water authority.

## Late-result race

1. At generation 1 a quorum anchors the unassigned initial Ground checkpoint.
2. At generation 2 it assigns the first unfinished stage to host A, epoch 1.
3. A computes the stage through the actual IPS-004 Hypervisor and locally qualified subprocess endpoint. The result is a *candidate* only.
4. At generation 3 a majority reassigns the same unfinished stage to host B, epoch 2, without publishing A's work.
5. A's late candidate is refused as stale despite its correct numeric value.
6. B executes and publishes at generation 4. A's completed work is absent from the committed DAG.
7. A new coordinator reopens all three durable journal files, identifies the latest quorum root, restores the IPS-004 checkpoint, and authorizes another qualified host to perform the next DAG stage.
8. The intended computation finishes at the exact result 16 for input 9.

Additional tests cover conflicting same-slot assignments from separate coordinators, missing read-majority, a valid but outdated state artifact, corrupted candidate and assignment binding, absent origin Hypervisor compute rights, missing payload files, and changed source semantics.

## Contract scope

The public IPS-005 interface comprises FencedGroundLineage, FencedGroundHead and FencedGroundCandidate. Assignment and publication are **separate durable transitions**. The caller must supply a qualified host; the adapter never discovers peers or runs untrusted code. A state candidate is reverified as a native IPS-004 checkpoint, then bound to the newest quorum assignment before a successor root can be sealed.

There is a **single published semantic frontier** under this tested fixed membership, not a guarantee of at-most-once worker invocation. A slow former worker and its replacement can both physically execute deterministic pure operations. Effects requiring an external semantic ledger are not eligible for this contract.

### Evidence boundaries

- Each quorum journal is independently fsynced, but the native CI harness uses separate files on one machine rather than separate fault-isolated devices or independently administered machines.
- Full power-loss durability depends on the storage and filesystem deployment. Orphaned uncommitted artifact files are possible after a failed quorum seal.
- The owner term and membership are fixed; leader takeover, Byzantine consensus and changing memberships are not addressed.
- A rechecked arithmetic receipt does not provide cryptographic physical-host provenance. IPS-004 demonstrates authenticated loopback peer operation, not geographic fault isolation.
- A read-majority failure is a refusal, not permission to trust the newest local file.
- No measurement of physical performance advantage over conventional computation is claimed.

## Reproduce

    python -m pytest -q tests/test_fenced_generated_ground.py
    python -m pytest -q tests/test_fenced_generated_ground.py tests/test_qualified_generated_ground.py tests/test_generative_ground_construction.py tests/test_recovery_lineage.py

Dedicated CI covers Linux and Windows on Python 3.11 and 3.13.

## Next research experiment

Use existing DistributedRecoveryLineageCoordinator and RecoveryLineageAuthorityService with independent authenticated authority processes. Rehome from the authenticated fabric directory while old and replacement network responses race, and require the latest proof at publication. Test loss of one authority and refusal after a quorum outage, then measure message costs, recovery latency and duplicate pure work.
