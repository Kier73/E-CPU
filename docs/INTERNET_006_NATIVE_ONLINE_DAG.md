# INTERNET-006 — Recoverable native E-CPU DAG across free ephemeral Internet runners

**Status:** implementation and offline tests committed; hosted workflow evidence
is pending. This is a bounded research milestone, not native M3 quorum continuity,
unlimited free compute, or a demonstrated continuous general-purpose CPU.

## Architectural advance

INTERNET-005 demonstrated the shape of a GitHub-bootstrapped Internet service
Ground and an exact separately retained checkpoint. INTERNET-006 exercises
E-CPU's **own** `ComputationNode` and `NavigableComputationDAG`:
each fresh GitHub Actions process observes and commits **one** ready native DAG
operation, publishes a new snapshot to a separately retained branch, then
exits. Its successor reopens the original DAG, rejects any altered snapshot,
finds the next eligible dependency frontier, and continues without redoing
previously accepted semantic effects.

No external host needs an E-CPU interpreter to supply GitHub's existing Git
comparison or HTTP conditional predicate. A GitHub-hosted Python runner is
the receiver and E-CPU interpreter. It is not an authenticated remote GitHub
peer or an independently controlled WAN observation of router hardware.

## Mathematical contract

The admitted fixed experimental intention has exactly four nodes:

```text
Git object read (pinned commit)
        |
        v
HTTP conditional predicate (304 match, 200 mismatch)
        |
        v
Git graph comparison (independent exact reference)
        |
        v
Compose source Grounds / native observer-path receipt
```

Each stage is separately persisted as a native `ComputationNode` result
inside E-CPU's original `NavigableComputationDAG.snapshot()`, not an
uncontrolled side ledger. A native `commit` fails if predecessors are missing.
`from_snapshot` revalidates digest, node identity, exact commit dependencies,
result digests, and replay order.

The externally observed operators are **pure/read-only**. If a runner dies
before publication, the next runner may repeat the observation, but it does
not repeat any accepted publication-side semantic effect. The Git service,
HTTP response, and native receiver are distinct causal loci; no claim is
made that a passive link performs an arbitrary algorithm.

The final node uses existing E-CPU `ObserverReceipt`,
`ObserverPathStage`, and `verify_observer_path`, retaining a native
path digest. Its explicitly scoped meaning is
`receiver_callbacks_not_external_attestation`.

## Source bootstrap and retained existence

Source: `main` branch of `Kier73/E-CPU`.
Execution: the built-in hosted GitHub Actions runner.
Durable identity: the SHA-256 of the fixed source-pinned intention.
Persistent checkpoint: `research/internet-005-state` branch, path
`state/internet006-dag.json`.
First anchor: an **explicit GitHub-committed revision-zero genesis** with
digest `9394f894ce6b245c40fe8b941fb02e6386d3f8d3c1aa287ee10367f21bce4c7e`.
Successors bind their `previous_digest` to the exact preceding checkpoint.

The first successor is permitted only if its predecessor is this genesis.
A missing state file, missing branch, malformed base64, altered native DAG
snapshot, wrong intention, changed node result, stale revision or different
predecessor is refused rather than silently initialized as a fresh workspace.
The resulting GitHub Contents API write includes the *original blob SHA*
in its update payload to detect conflicting concurrent writes.

The 005 and 006 workflows use the same Actions concurrency key
`internet-005-state-branch`, so hosted writers share an exclusive
administrative deployment lane. The blob SHA guard remains necessary because
other authorized publishers may operate outside GitHub Actions.

The new file is under a separate path from 005 and never rewrites 005's
workspace checkpoint. The initial Git SHA does not convey cryptographic
authority independent of the repository owner; GitHub history can be changed
by authorized administrators. This is **single-administrator Git continuity**,
not M3's quorum recovery.

## Free operational mode

`.github/workflows/internet-006-native-dag.yml` runs:

- PR checks in read-only GitHub Actions, with source-verified native DAG tests,
  INTERNET-005 controls and E-CPU's original DAG regression suite.
- One live, write-authorized quantum on a qualifying merge to `main`.
- Optional manual `workflow_dispatch` and best-effort schedule every three
  hours, advancing the next ready node without rerunning earlier nodes.
- A JSON report retained as GitHub Actions artifact for each live quantum.

After the fourth node, the native DAG is complete; further invocations
produce no additional state publication or remote service requests.
The next user intention must be explicitly added rather than causing
an infinite loop of meaningless benchmark executions.

No other cloud subscription, credit card, separate paid virtual machine or
long-lived secret is required. GitHub Actions free quota, network admission
and rate limit policies are still binding deployment constraints.

## Tests and acceptance

```bash
python -m pip install -e . pytest
python -m pytest -q \
  tests/test_internet_fabric_dag.py \
  tests/test_internet_free_fabric.py \
  tests/test_computation_dag.py
```

Verification includes exact E-CPU native DAG snapshots reopened in fresh
Python interpreters; four dependency-qualified transitions; no repeated
external observations after terminal completion; corrupted checkpoint,
operator, result and predecessor refusal; unexpected Git or HTTP result
refusal; and Git blob-SHA guarded publication.

**Live success is not yet claimed.** To accept the milestone, inspect actual
Actions jobs and four successive runner process/host instances, confirm the
Git state branch contains revisions 1–4 in order, verify native receipt hashes
and predecessor chain, and invoke a fifth run to confirm it performs zero
new source observations or writes.

## What this advances and does not

INTERNET-006 makes online computation a **reconstructable native DAG**, not
a fully active independent CPU. It separates:

1. the stable mathematical intention,
2. completed semantic effects,
3. transient physical hosts,
4. external service-native operations,
5. durable state carrier,
6. E-CPU's own independently verified observer receipts.

The next substantive steps are a generic intention-ingress format,
multiple distinct DAGs concurrently admitted under receiver authority,
M1 persisted pages, M3 quorum-backed checkpoints across independently
administered hosts, mutual-TLS Internet peer ingress, and real physical
path instrumentation. Larger workloads and arbitrary external paths
must respect their own budgets, authentication and measured semantics.
