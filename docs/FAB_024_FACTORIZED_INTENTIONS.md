# FAB-024 — Factorized computational intentions

## Structural quotient of pure workflow families

Given a family of independently named finite topologically ordered pure operation graphs, select the backward dependency cone of each requested output. For node v, let b be its explicitly receiver-selected pure binding, C its full PureContract digest, p its exact payload bytes and k_1,...,k_m the structural identities of its ordered predecessor positions. Then

    K(v) = SHA256(frame("fabric.pure-structure.v1", b, C, p, k_1, ..., k_m))

where frame concatenates each field with its four-byte big-endian length prefix. Repeated operand positions remain repeated; noncommutative order is preserved. Original node and workflow names are excluded from this key only for explicitly admitted pure bindings. The plan retains every live original (workflow,node) -> K mapping and the selected output mapping. A single pass interns identical descriptors, refusing conflicting descriptors under the same hash. A source-coverage checker reconstructs the live cones and each mapped descriptor from the original graph and verifies that there are no missing or extraneous work classes, edges, members or outputs. This is exact structural common-subexpression elimination over declared pure dependency graphs, not general semantic equivalence detection.

For each work class, frame the original payload plus actual ordered predecessor results. Independently verify the produced bytes under the receiver-selected contract. For classes with multiple original members, optionally use the FAB-023 result bank; exact input hits are still checked, and different structural classes can also converge to the same actual contract/input key. Unique classes are evaluated directly rather than paying for persistent writes. No effects or hidden state are inferred to be shareable. Bindings must include every relevant semantic/context/verification dependency, and the caller must qualify purity and trusted verification. A digest is not runtime attestation. The work graph is bounded to 65,536 declared nodes, 256 nodes per intention, 256 dependency positions per node, 32 MiB declared payload bytes, per-contract input/output bounds and 128 MiB retained result bytes. These are local execution geometry choices. Python metadata, operator runtime, storage and transport costs require separate resource accounting.

Plan.affected(key) returns original workflow names containing that live class; the current implementation scans the member map, not a persistent incremental reverse index. The benchmark changes one shared input, selects its affected workflows and independently realizes their updated plans. It does not atomically update any native application state.

## Native composition

prepare_native and realize_native are an opt-in adapter for fresh receiver-owned NavigableComputationDAG instances. The adapter maps each exact (operation,resource,context_digest) triple to an explicit pure binding whose contract context must equal that native node context. It retains all native graph digests (including original identities and revisions), original ordered dependencies, and canonical native payload bytes. All original native nodes are selected, rather than bypassing the native DAG's full completion requirements. The adapter reprojects the source before execution, refuses a stale preparation, verifies the entire work plan and all result bytes, then publishes the original native ready frontiers with an opt-in result record {schema, value_hex, factor_key}. The original DAG binds results to original node digests and remains the frontier-commit authority. Native frontiers are atomic within each graph, not across graphs; caller-exclusive graph ownership is required for the duration. The new result schema does not replace arbitrary existing operator schemas. It does not claim Transit dispatch, M3 quorum publication or a durable cross-DAG transaction. The reusable result bank persists verified pure bytes, not native graph commit history; the benchmark verifies exact snapshots and snapshot recovery separately.

## Local evidence

Exact Git blobs: factorized_intentions.py 089612880a7658693e153e1b86a3b88234e70d2e; native_factorization.py 637b02b6fbd661988952465e6ec0fb247fb3f4aa; shared_result_bank.py 18ca4a1cb2c8b2d011798f6feb0763987ad5f672; native computation_dag.py ea66eda9b7ba3c35854812d4b14102ed5b80d84b. Direct Git checkout remained blocked by DNS. Native DAG source was recovered exactly via the repository connector and its Git blob checked before local tests. Six local tests passed (four pure core and two actual native DAG integration tests), including omission/tamper, ordered/repeated operands, context separation, changed-input refusal, exact native frontier commits and snapshot reconstruction. The small pure test fixture uses a simple arithmetic oracle; the measured signal benchmark uses a distinct mathematical checker.

### Pure multi-stage signal experiment

Each workflow has a 128-byte signal autocorrelation, a second autocorrelation over the first result reduced modulo 256, a unique private projection consuming both results, and one unused branch. Literal producer uses the circular sum; independent checker uses carry-free packed integer convolution. Both baseline and factorized routes realize only the requested three-stage cone. All private outputs match exactly. Timings in seconds, one run:

| Workflows | Inputs | Live nodes | Work classes | Literal + check | Formation | Verified execution | Cold bank | Reopened bank |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1024 | 32 | 3072 | 1088 | 2.483187 | 0.022989 | 0.154591 | 0.203419 | 0.039845 |
| 256 | 256 | 768 | 768 | 0.618442 | 0.005261 | 0.644492 | 0.658924 | 0.622009 |
| 1024 | 1 | 3072 | 1026 | 2.580086 | 0.021152 | 0.034167 | 0.037466 | 0.032345 |

Execution, cold and reopen columns include plan replay/checking and exclude formation; add formation for the first use of a plan. Database open/close and initial source construction are excluded. In the 32-input case: 2048 expensive producer calls become 64; 1024 private producer calls remain. On reopen 1024 private producer calls remain and all 1088 classes are checked. One changed source affected 32 workflows; the selected reformation and durable realization took 0.007888 s with 34 producer calls (two expensive common operations and 32 private projections), 34 checks. Independent literal oracle for that update was run outside the timer. The 32-input database was 208,896 bytes after the update. The all-distinct case declines persistence by fanout; formation overhead still loses to literal execution. No general asymptotic speed claim.

### Actual native DAG benchmark

512 independently named native DAGs, with distinct private projection payloads, spread over 24-bit address labels including ffffff. Each contains three original native nodes; 16 shared inputs. Literal producer/checker and native commit vs factorized producer/checker and original native commit. Both paths use the same opt-in result schema; the literal control receives the prepared structural labels solely to produce identical result records, without using them to avoid execution. Factorization is charged the 0.118751 s plan formation; literal time excludes that label formation. Native graph construction excluded on both routes.

| Metric | Value |
|---|---:|
| Original committed nodes, both routes | 1536 |
| Distinct factor classes | 544 |
| Literal native producer calls | 1536 |
| Factorized producer calls/checks | 544 / 544 |
| Native literal seconds | 1.324318 |
| Native formation seconds | 0.118751 |
| Native factorized realization seconds | 0.194206 |
| Cold bank realization seconds | 0.243264 |
| Reopened bank realization seconds | 0.158155 |
| Reopened producer calls/checks | 512 / 544 |
| Exact native snapshots and successful reconstructions | 512 |
| Snapshot comparison + reconstruction seconds | 0.194041 |
| Durable result database bytes | 118784 |

The cold and reopened paths use fresh original graphs with the same exact preparation and commit all original nodes. Their complete native snapshots equal the literal and in-memory factorized snapshots. Native formation plus in-memory realization is 0.312957 s, versus 1.324318 s for literal native execution. Snapshot comparison/reconstruction is separate from both timing intervals. These are native DAG measurements with synthetic pure operators, not complete M3 machines or independent network hosts.

## Next development

Maintain a durable incremental dependency index and dispatch only unresolved shared classes using native Transit frontier execution and receiver-side qualification. Preserve independently verified result receipts across failed workers; rehome only unresolved classes; retain original consumer commit identities and their independent native admission. Measure total discovery, verification, publication, delivery and per-consumer commit costs. Extend equivalence discovery beyond syntactic structural identity using independently checked operator-specific rewrites, and decline representation construction where measured overhead dominates.
