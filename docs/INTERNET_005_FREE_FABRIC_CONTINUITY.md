# INTERNET-005 — Free-fabric path-native bootstrap and checkpoint continuity

**Status:** bounded implementation proposed for verification, not an always-on processor, M3 deployment, or physical WAN path attestation.

## Intention

Bootstrap a computational workspace entirely from the E-CPU GitHub repository
using ordinary public GitHub Actions capacity. Without deploying E-CPU at
every Internet locus, use **real existing Internet-native service operations**
as selected computational Grounds. Retain an exact, self-checked checkpoint on
a dedicated Git branch. A subsequent independently created runner should
reconstruct the workspace and publish its next revision.

The current implementation has no external cloud account, subscription,
dedicated GPU, paid API, or SSH host requirement. It uses the Python standard
library plus E-CPU packaging. Public-repository GitHub-hosted runner eligibility,
GitHub API rate limits and scheduled workflow availability still apply.

## Existing E-CPU foundations

- [INTERNET-002](INTERNET_NATIVE_GROUND_002.md): a pinned Git service graph
  and independently verified merge-base/ahead/behind observations.
- [INTERNET-003](INTERNET_NATIVE_GROUND_003.md): intermediary HTTP retention
  and conditional predicates.
- [PATH-GROUND-004](PATH_GROUND_004_IPV4_FORWARDING.md),
  [005](PATH_GROUND_005_AUTHENTICATED_ROUTER_WITNESS.md) and
  [006](PATH_GROUND_006_CAPTURE_TIME_ATTESTATION.md): owned kernel routing and
  authenticated witnesses, not generalized access to public routers.
- [CONTINUOUS-001](CONTINUOUS_SESSION_OBSERVER_REJOIN.md): stable E-CPU M3
  rejoin addresses and identity independent of process life.
- MSF-001: pinned external sources and real receiver-local native Hypervisor
  qualification. Its owned-network route remains an in-process simulator.

INTERNET-005 does **not** replace M3's recovery authority with GitHub. The
checkpoint below is a separate *bootstrap witness* with one GitHub repository
as its administrative and physical failure domain.

## Computation performed by existing Internet services

The first admitted intention is a small, fixed reference workload:

1. Read a pinned GitHub Git commit object using the Git data service, verify
   its exact SHA and retain its response body digest.
2. Re-observe the same representation with the actual ETag as
   `If-None-Match`. Require an actual HTTP 304 and zero response bytes.
3. Re-observe using a nonmatching ETag. Require HTTP 200 with identical source
   bytes. Both controls distinguish the native service conditional operation
   from local imitation.
4. Ask GitHub to compare two immutable Git commit SHA values from INTERNET-002.
   Require ahead=11, behind=0, status=ahead, and the exact pinned merge base
   from the independently retained reference graph.
5. Construct a bounded, exact path-observation receipt, separately identifying
   Git service graph and HTTP predicate operators. The receiver validates
   pinning and the permitted observation semantics.

The Git repository's graph service and the HTTP conditional handler are
**external native computational operators**, not E-CPU programs installed on
GitHub's systems.

A receiver-local adapter also takes the checked remote-service receipt through
**native E-CPU** `RepresentationRef`, `ObservationContract`,
`ObserverContract`, `ObserverReceipt`, `ObserverPathStage` and
`verify_observer_path`. Its exported witness explicitly says
`receiver_callbacks_not_external_attestation`: it qualifies a local
observation of service evidence, **not** a packet-level WAN carrier or remote
GitHub identity signature. The resulting path digest is retained in the live
report but does not grant execution capability.
 These services do not provide evidence that intermediary
routers, copper or optical links performed arithmetic.

For all versions, the observer uses exact, read-only, allowlisted HTTPS
endpoints, an explicit 2 MB response budget, no redirected requests, a
20-second request timeout, bounded ETags and strict JSON parsing. It does not
download source blob payloads or model weights.

## Durable revision and new-runner continuation

`mailcpu.internet_free_fabric` derives a stable workspace ID from the
content-hashed mathematical intention, never from the runner identity.
The stored checkpoint contains:

```json
{
  "schema": "mailcpu.internet-free-fabric-checkpoint.v1",
  "workspace_id": "<intention SHA-256>",
  "revision": 1,
  "previous_digest": null,
  "observation": "<typed bounded native-service receipt>",
  "digest": "<canonical checkpoint SHA-256>"
}
```

The exact repository path is `state/internet005-checkpoint.json` on branch
`research/internet-005-state`. This branch is isolated from `main` and
holds bounded checkpoint data rather than changes to production code.

A fresh runner:
- obtains the current GitHub Contents API object, including its **Git blob
  SHA** (optimistic concurrency token);
- verifies exact schema, scope, pinned source evidence and canonical digest;
- performs new live Internet service observations;
- constructs revision n+1 pointing to the previous checkpoint digest;
- PUTs using the original Git blob SHA in the Contents API `sha` field.
  Conflicting or changed state refuses the publication rather than silently
  overwriting another published revision;
- outputs an artifact report that identifies both the new semantic checkpoint
  digest and the Git blob published.

Git commit ancestry independently retains historical state publications, but
a single owner of the Git branch can rewrite or delete that history. Checkpoint
hashes are not signatures or independent recovery authorities.

### Bootstrap prerequisites

Provision the empty state branch **once** from `main` using GitHub's
create-branch API (or `git branch research/internet-005-state main` followed
by a normal push). This is a deliberate administrative operation. The running
program never recreates a missing state branch after a possible loss.

After this PR is merged into `main`, manually invoke
`INTERNET-005 free-fabric continuity` via GitHub Actions workflow dispatch.
It will first run offline tests, then one live computational quantum. The
scheduled trigger runs every six hours on a best-effort basis; it can be delayed,
disabled or skipped by GitHub. It is *not* a guaranteed clock or uninterrupted
CPU process.

The GitHub Actions workflow uses the built-in `GITHUB_TOKEN`, grants
`contents: write` only to the live job, and forbids state writes from
pull-request jobs. The read-only test job has `contents: read` permission.
A job-level concurrency key prevents overlapping workflow-owned publications.
The GitHub Contents SHA guard remains required to prevent concurrent edits
originating outside the workflow.

### Verification

```bash
python -m pip install -e . pytest
python -m pytest -q tests/test_internet_free_fabric.py
```

The offline suite checks a genuine *fresh subprocess* reconstruction,
incremental revision identity, independent native-service operand responses,
wrong commit, wrong graph, wrong base, conditional response refusal, modified
representation refusal, duplicate JSON keys, modified receipts, malformed
checkpoint, and optimistic Git blob-SHA publication.

Live verification is **separate**: the workflow must actually run against
GitHub, publish revision 1, then run again on an independently created runner
to publish revision 2. Inspect both reports and branch commit history.
Do not claim two-run continuation before both jobs have succeeded.

## Explicit next stages

1. Replace the single-service checkpoint witness with the *existing native
   M3 + M1* recovery-backed session; qualify at least three independently
   administered authority/storage instances before claiming quorum continuity.
2. Add typed remote inlet and result delivery to E-CPU's existing
   `ComputationalFabricDirectory`, `Transit`, and native Hypervisor admission.
3. Encode measured, authorized physical/network paths as representation-relative
   candidate Grounds, never treating a name or latency sample as execution proof.
4. Form a cross-repository intention DAG with capability scope and zero-dollar
   default budget. Avoid public API fan-out and do not use unauthorized peers.
5. Attach free or permitted on-demand worker substrates and compare Internet
   service-native execution against a conventional local oracle.
6. Benchmark partial-worker loss, state rejoin, exact cold/warm costs, credits,
   rate limits, and actual computation performed outside the source interpreter.

**Success for INTERNET-005:** real Internet service-native Git and HTTP
operations contribute verified observations to a persistent GitHub-bootstrapped
workspace whose checkpoint can be opened and advanced by a different process.

**Not established:** general continuous availability, physical path
arithmetic, fully hosted native E-CPU VM fleets, cloud redundancy, unattended
unlimited computational scale, or long-running M3 execution.
