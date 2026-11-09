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

## Frontier transaction boundary

`commit_frontier()` extends the node-level commit rule to one complete readiness frontier. It accepts a node-to-result mapping and optionally the compiler's expected stable node-ID tuple. Before publishing anything, it validates the exact current ready set, every node identity, every dependency, and the canonical JSON encoding/digest of every result. Only after the entire batch passes does it update the committed-result map once. A graph-level re-entrant lock serializes node revision, individual/frontier commits and snapshot capture; concurrent equivalent submissions therefore linearize to one new publication and exact idempotent replays. It returns `False` for a new frontier commit and `True` for an exact whole-frontier replay. A changed result, a partial replay, a stale frontier, or one malformed result refuses without publishing any new member of the batch.

Both the local dataflow evaluator and the operation-native fabric executor use this boundary. The operation-native executor prepares all local and remote nodes in the frontier, verifies every remote lane and receipt, then crosses one commit barrier. A remote host failure or oracle mismatch therefore cannot leave an earlier sibling lane from that same frontier committed. The transaction is scoped to one DAG frontier; effects already committed by a receiver remain governed by the separate receiver execution ledger and recovery protocol.

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

The DAG can be carried inside the combined Transit checkpoint (schema v3). Its snapshot is included under the same canonical outer digest as receiver/session state, both requester channel cursors, route catalogue/query/result, and retry event. Restore validates and reconstructs the graph before creating runtime endpoints. The crash-cut recovery test proves that a committed Structural Memory receipt and a pending CPU frontier survive together. Capture and restore both require exactly one ready DAG node to match the retry event's operation, resource, context digest, and payload. After the original request is retried or replayed, the exact result can be committed to that restored node. This composes the persistent frontier with protocol recovery without claiming that every node in a multi-branch DAG executes as one atomic transaction.

The fan-out/fan-in test serializes the graph after two branch commits and reconstructs it in the same test process. The four single-operation transaction-cut cases separately serialize the combined receiver/channel/route/DAG envelope with a committed memory node and a pending CPU node.

The multi-branch recovery experiment goes further. It commits branch A, then sends branch B and injects a cut after the receiver's hypervisor execution ledger commits B but before the result is published or the request is acknowledged. At this point:

- branch A is committed in the DAG;
- branch B is uncommitted in the DAG but its exact effect is committed in the receiver execution ledger;
- branch C remains ready and unexecuted; and
- the join remains blocked because B and C have not both entered the graph's commit map.

The single schema-v3 checkpoint binds this graph state to the receiver ledger, requester/worker cursors, exact route, and branch-B retry event. Restore rebuilds the graph with A committed and B/C ready. Retrying B returns the receiver's stored result without entering the replacement CPU backend; the test then commits B, executes only C as new work, materializes the join from all three committed results, and runs that join through Transit. The same transaction cut is also exercised by a separate supervisor/child-process test that hard-terminates the worker interpreter and restores in a new interpreter; see `PROCESS_CRASH_RECOVERY.md`. The DAG branches in both harnesses are still executed sequentially, not concurrently.

## Proof boundary

The demonstrated workload is one modular Structural Memory input, three deterministic pure CPU programs, and one deterministic CPU join. The branches are deliberately executed sequentially by the test harness; the DAG exposes a frontier that a scheduler could dispatch concurrently, but this does not demonstrate parallel execution or throughput scaling.

The experiment does not establish distributed DAG consensus, arbitrary side-effect transactions, GPU execution, automatic path-cost calibration, or universal program translation. Each branch is an independently committed Transit operation. The join does not retroactively make all branches one atomic transaction. A failed branch can be retried without repeating already committed siblings, subject to the receiver's semantic execution ledger and checkpoint policy.

The graph digest detects accidental or uncoordinated modification. It is not a signature, MAC, authenticated provenance claim, or anti-rollback mechanism. See `INVARIANTS.md` B-55 for the executable frontier-commit contract, including concurrent exact-retry behavior.
