# Navigable Computation DAG

## Purpose

A computation that has been routed through Transit should be able to preserve more than one operation identity. It should preserve a dependency structure: which operations share an input, which may proceed independently, and which result must wait for the complete set of predecessor results.

`NavigableComputationDAG` adds that dependency structure as a bounded, content-addressed object. It is a state and readiness layer, not an alternate execution engine. Every operation still travels through the existing receiver-side Transit authorization, backend dispatch, semantic translation, and oracle checks.

## Formal model

Let:

\[
G=(V,E)
\]

be a finite directed acyclic graph. An edge \((u,v)\in E\) means that operation \(v\) depends on the committed result of operation \(u\).

Let \(C\) be a partial map from node identities to immutable result commits. The dispatch frontier is:

\[
F(C)=\{v\in V\setminus\operatorname{dom}(C):
\operatorname{pred}(v)\subseteq\operatorname{dom}(C)\}
\]

Only nodes in \(F(C)\) may be committed. The commit contains the exact node digest and the digest of its canonical JSON result. A repeated commit with the same node and result digests is an idempotent replay. A changed result under the same node identity is a conflict.

The graph is bounded at 256 nodes and 1,024 dependency edges. Node payloads and results use a closed JSON value algebra, with string object keys and finite numbers. The graph snapshot includes its node definitions and commits in deterministic topological order, bound by a SHA-256 digest.

A pending operation may be revised by increasing its revision number. A committed operation cannot be revised. This is used when a join node begins as a declaration of its dependencies and is later materialized into an exact CPU request after every branch result exists.

## Executed experiment

The integration test begins with a receiver-admitted Structural Memory recurrence:

\[
x_t=(13+9t)\bmod 251
\]

The receiver reads coordinate \(t=23\), obtaining \(x=220\). That receipt becomes the shared committed predecessor of three CPU operations:

| Branch | Operation | Result |
|---|---|---:|
| `plus-19` | \(x+19\) | 239 |
| `triple` | \(3x\) | 660 |
| `double-plus-7` | \(2x+7\) | 447 |

The three branches become ready together. Each is separately submitted to Transit and receives its own receiver-authorized execution result, semantic translation record, and independent CPU oracle evidence.

After two branch commits, the graph is serialized and reconstructed. The third branch remains ready; the join remains blocked. After the final branch commits, the join becomes the sole ready node. Its pending declaration is advanced to revision 2, whose exact CPU program consumes the three committed values:

\[
239+660+447=1346
\]

The join is itself submitted through Transit. It is not an implicit in-memory shortcut around the hypervisor.

## Invariants

- Every dependency identifier names a node in the same graph.
- A graph must have a deterministic topological ordering; cycles are refused.
- A node is ready only when every declared predecessor has a committed result.
- A node result binds both the exact node revision and a canonical result digest.
- An exact repeated commit returns replay; a changed result under the same identity is refused.
- A pending node revision must increase monotonically; committed nodes are immutable.
- Snapshot restore verifies the envelope digest, every node digest, every result digest, and dependency order before exposing the reconstructed frontier.
- Decoding a node payload or result returns a detached JSON value; caller mutation cannot change the stored identity.

## Relation to recovery and Transit

This graph snapshot is currently a separate digest-bound object. PR #30's combined Transit checkpoint captures the receiver, both requester channel cursors, route catalogue/query/result, and retry event at explicit in-flight cuts. The next integration step is to compose the DAG snapshot with that combined checkpoint so the computation frontier, committed branch effects, receiver ledgers, and transport retry state are published as one atomic recovery envelope.

The current fan-out/fan-in test serializes the graph after two branch commits and reconstructs it in the same test process. The four transaction-cut tests separately reconstruct the receiver and transports across in-flight cuts. They are not yet a single test that crashes and restores an entire multi-branch workload.

## Proof boundary

The demonstrated workload is one modular Structural Memory input, three deterministic pure CPU programs, and one deterministic CPU join. The branches are deliberately executed sequentially by the test harness; the DAG exposes a frontier that a scheduler could dispatch concurrently, but this does not demonstrate parallel execution or throughput scaling.

The experiment does not establish distributed DAG consensus, arbitrary side-effect transactions, GPU execution, automatic path-cost calibration, or universal program translation. Each branch is an independently committed Transit operation. The join does not retroactively make all branches one atomic transaction. A failed branch can be retried without repeating already committed siblings, subject to the receiver's semantic execution ledger and checkpoint policy.

The graph digest detects accidental or uncoordinated modification. It is not a signature, MAC, authenticated provenance claim, or anti-rollback mechanism.
