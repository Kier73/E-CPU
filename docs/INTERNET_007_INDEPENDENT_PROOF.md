# INTERNET-007-PROOF — Independently check the online processor's recovery claim

**Status:** independent verifier and refusal tests committed. This document
does not claim that GitHub has run the intended continuation jobs. An honest
proof report must be read from actual verified online state, not generated
from mocked responses or a local replay.

## Falsifiable proposition

**A sequence of separate GitHub Actions invocations can advance the SAME
native E-CPU `NavigableComputationDAG`, each committing one distinct
dependency-admitted semantic effect and retaining exact accepted results
through Git-owned state after the previous interpreter exits.**

This is an Internet-native, single-GitHub-administrator continuity
proposition, **not** a claim of independently governed M3 quorum, a
physically different CPU for each job, a continuously active resident
process, or arithmetic by passive network carriers.

The E-CPU receiver currently admits:
- native remote Git object observations;
- real HTTP conditional response predicates;
- native Git graph comparison against previously pinned expectations;
- E-CPU's own typed `ObserverPathStage` composition.

## Independent proof requirements

For the default `public-source-grounds` manifest, the proof auditor must see:

1. The original, exact Git genesis **commit SHA**
   `ca5c173de08866d989a319656f122c8a35886d3d`.
   This is a pinned Git commit object on the separate
   `research/internet-005-state` branch, not a mutable `latest` pointer.
2. Git's independent `commits?path=...` service returns the complete
   chronological history of that *specific* intention state file.
3. Each historical checkpoint is loaded by its exact **Git commit SHA**,
   not by branch head. The verifier recomputes Git's blob hash
   `SHA1("blob " + len(raw) + NUL + raw)` from the original retrieved bytes
   and matches the Git Contents API's blob SHA.
4. Every checkpoint passes E-CPU's own exact manifest identity, canonical
   content digest, native `NavigableComputationDAG.from_snapshot` and typed
   semantic-result verification.
5. Checkpoint revision numbers cover **0, 1, 2, 3, 4, 5** exactly.
   Each revision's `previous_digest` matches the preceding *actual Git
   historical content*. Every prior committed node retains exactly its
   accepted result after the later runner's reconstruction.
6. Publication commit messages identify the actual Actions run and attempt:
   `INTERNET-007 public-source-grounds revision 3 [run=... attempt=...]`.
   The auditor refuses missing run identities, duplicated run IDs,
   mismatched revision claims, and attempts without corroboration.
7. For each distinct run ID, GitHub's **Actions run API** independently
   confirms the exact run ID, attempt, workflow name, `main` branch,
   approved event, and **completed/success** conclusion. The commit
   message alone is not accepted as hosted-run evidence.
8. The final E-CPU DAG is complete, including the native receiver-path
   witness. A subsequent terminal invocation should not publish a new
   state or issue any native operator call; that last no-op is a separate
   operational check and is not inferred from the existence of revision 5.

The auditor is an **independent reader** of Git history. It does not write
to the state branch, invoke untrusted code, issue arbitrary HTTP queries,
or grant execution rights. The artifact is a bounded report with one record
per Git revision, its exact Git commit, independent Git blob SHA, accepted
native state digest, and committed DAG operation.

## Execute

Offline first:

```bash
python -m pip install -e . pytest
python -m pytest -q \
  tests/test_internet_intention_proof.py \
  tests/test_internet_intention_ingress.py \
  tests/test_internet_fabric_dag.py
```

Then run `INTERNET-007 independent continuity proof` in GitHub Actions
(or let the read-only scheduled verifier inspect the state after a successful
hosted operation). The default command reports honest partial progress:

```bash
python -m mailcpu.internet_intention_proof \
  --output internet007-proof.json
```

Once five separate hosted progress runs have completed, require the
full proof explicitly:

```bash
python -m mailcpu.internet_intention_proof \
  --require-complete --output internet007-proof.json
```

The command uses GitHub's built-in repository token with the **read-only**
`contents:read` and `actions:read` permissions. It needs no paid cloud,
separate credential or Git write authority.

The new workflow includes a manual `require_complete` boolean, default
true for deliberate acceptance; scheduled/automatic audits report partial
evidence without incorrectly calling it a completed proof.

## Actual service-native continuity evidence (separate from runner proof)

A three-invocation online experiment was also completed against the real
GitHub service, with evidence retained under
[research/internet-007-live-service-proof](https://github.com/Kier73/E-CPU/tree/research/internet-007-live-service-proof).
Each connector invocation had a fresh execution context:

1. Invocation 1 queried the original Git graph and verified its
   `ahead=11, behind=0` relation, plus a pinned VGI commit. It published
   [phase 1](https://github.com/Kier73/E-CPU/commit/83728a1761d16897ec9f0c44cfc041a9760d998c).
2. Invocation 2 reopened the retained Git object and independently queried
   the reverse graph; it observed `ahead=0, behind=11` and retained
   [phase 2](https://github.com/Kier73/E-CPU/commit/7f841c4c0c42421a88e4a8f0e2b2cb6950a846b9),
   content-binding its exact predecessor Git blob SHA.
3. Invocation 3 reread both Git blobs, verified predecessor identity and
   the inverse graph relationship, then asked GitHub for commit ancestry
   between the two evidence commits. GitHub returned one successor
   commit, zero behind, and phase 1 as the unique merge base. It persisted
   [phase 3](https://github.com/Kier73/E-CPU/blob/research/internet-007-live-service-proof/evidence/native-stage-3-proof.json).

This is **positive evidence** for service-native Git graph computation,
Internet-retained state, and successful reobservation across independent
caller lifetimes. It does **not** execute E-CPU's Python DAG on separate
hosted Actions runners, prove an independently governed recovery quorum,
or measure arithmetic in an uninstrumented router. The stricter five-run
auditor below is still necessary.

## Independence and remaining uncertainties

Independence here means separate verification of (a) native semantic
state, (b) original Git blob bytes and immutable Git history, and
(c) GitHub's independently served Actions execution metadata. It does
not produce an independent *administrative* fault domain: an owner with
full GitHub repo privileges can alter history, workflows or manifests.
Nor does GitHub's workflow API cryptographically attest the physical
machine used, or prove continuous computational uptime between quanta.

The current evidence gate remains **unmet** while the state file shows
revision zero or the relevant Actions jobs remain queued. No success
must be inferred from merges, branch existence, simulator output, or
the audit tool's own tests.

After successful multi-run verification, the next E-CPU experimental
step is to move state to independent M1/M3 authority replicas, validate
real cross-host mutual-TLS Transit delivery and enforce global scheduling
and budgets across multiple source-specific intentions. For physical
Internet-path computation, retain the PATH-GROUND-004/005/006
instrumentation and signature requirements and do not attribute
remote service-native Git/HTTP operations to uninstrumented routers or
optical media.
