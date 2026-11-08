# Computational Objects and Time

## Status

This is the M0 mathematical and architectural contract for general computational hosting. M1 supplies the first byte-object implementation described in TRANSIT_BYTE_OBJECTS.md. The document is normative for the distinctions and proof boundaries stated here; it does not claim a universal runtime or resolver.

## 1. The question

The motivating question is:

> Can the description of a system produce the same information virtually as the system it describes?

For a CPU, a description may be interpreted by another CPU and produce a useful state or result. The interpreter introduces cost, but also creates an opportunity: the description may be moved, inspected, verified, checkpointed, transformed, or executed by a different host.

The relevant objective is not merely to make an emulator resemble its reference machine. It is to determine when a described transition system can produce the required observable information with a better or more useful combination of time, memory, communication, compute, verification and recovery costs.

The claim is always relative to a declared representation, observation and resource boundary. It is not a universal claim that every description can be cheaper than the system it describes.

## 2. Separate the object, its host, and its path

A computational object is an identity-bearing description and collection of byte representations:

\[
\mathcal{O}=(I_B,B,G,P)
\]

- \(I_B\) is the immutable identity of the represented artifact and its manifest.
- \(B\) is the byte content, possibly divided into content-addressed pages.
- \(G\) is the computational Ground: representation rules, assumptions, domain and observation semantics.
- \(P\) is the declared program, task, operator or transition description associated with the object.

A live computational domain adds mutable state and permitted transitions:

\[
\mathcal{C}=(\mathcal{O},\Sigma,\Delta)
\]

- \(\Sigma\) is mutable operational state, including materialized state and reconstructible state references.
- \(\Delta\) is the declared family of permitted transitions.

A host is not the object and is not necessarily the physical machine. E-CPU's Communication Host Model remains the governing abstraction:

\[
H=(I_H,C,S,T,K,L)
\]

where \(I_H\) is logical host identity, \(C\) is communication interface and adjacency, \(S\) is operational state, \(T\) is the host's transition relation, \(K\) is its permitted capability set, and \(L\) is its operational lineage.

A host interprets an admitted object or request under a local implementation and authority context. Its physical realization may change while logical identity is retained, provided the required state and lineage continuity obligations are satisfied.

A passive communication link is a substrate edge. A queue, router, scheduler, page provider or executor becomes an operational host when it owns a defined information transition and capability.

## 3. Bytes are common representation, not common semantics

An executable image, transformer tensor, KV-cache page, ELF segment, filesystem block, operating-system checkpoint and MailCPU message can all be represented as bytes.

That common representation does not make their meanings interchangeable.

A useful typed object reference binds at least:

\[
R_B=(h_M,h_C,n,\mu)
\]

- \(h_M\): digest of the complete manifest.
- \(h_C\): digest of the logical content bytes.
- \(n\): logical byte length.
- \(\mu\): declared media or representation type.

A consumer still needs a Ground and an implementation that understand the representation. An object reference does not authorize execution, load native code, establish ABI compatibility, or prove semantic correctness.

The byte substrate should therefore remain neutral. Domain-specific runtimes interpret the representation through typed contracts.

## 4. Content identity and logical extent

For fixed page size \(P\), divide a logical byte sequence \(b\) into ordered chunks:

\[
b=b_0\Vert b_1\Vert\cdots\Vert b_{m-1}
\]

For chunk \(i\), let its logical length be \(\ell_i\), and form a fixed-size page:

\[
p_i=b_i\Vert 0^{P-\ell_i}
\]

The page identity is:

\[
h_i=\operatorname{SHA256}(p_i)
\]

The content identity is independent of padding:

\[
h_C=\operatorname{SHA256}(b)
\]

The manifest binds schema, representation type, total logical length, page size, content identity, and the ordered sequence of \((i,\ell_i,h_i)\):

\[
M=\operatorname{Canonical}
(\text{schema},\mu,|b|,P,h_C,\{i,\ell_i,h_i\})
\]

\[
h_M=\operatorname{SHA256}(M)
\]

This gives three distinct checks:

1. A page digest identifies the exact fixed-size bytes stored at one page address.
2. The manifest digest identifies the descriptor, including ordering and logical extents.
3. A complete object read recomputes the content digest over the unpadded logical bytes.

A partial range read can verify the manifest and every page it actually resolves. It cannot claim to have recomputed the complete content digest unless the complete object was read.

Immutable page identity is separate from residency. A page may be resident, locally backed, structurally generated, or resolved through an existing remote page provider. The object reference does not change merely because its current physical location changes.

## 5. Time belongs to transitions and communication state

The object manifest is immutable. It does not contain a host clock reading or a global timestamp.

Time becomes meaningful when the object participates in an operation: admission, transfer, queueing, interpretation, state transition, commit, publication, retention, or recovery.

E-CPU already distinguishes temporal domains. Keep those meanings separate:

| Coordinate | What it orders or measures | Scope |
|---|---|---|
| Event coordinate | Accepted system event/transition progression | Owning event or SystemEpoch domain |
| Reliable-channel sequence | Frame delivery, acknowledgement and retransmission | One channel direction |
| Semantic execution identity | One logical operation and its replay identity | Workload/source/channel/sequence context |
| Lamport/vector clock | Causal order and concurrency | Declared actors and observed messages |
| Scheduler tick | Deterministic virtual progress and deadlines | One named scheduler |
| Monotonic duration | Elapsed physical time | One actor and boot/restore segment |
| Wall/calendar sample | Local calendar correlation | One endpoint's clock observations |
| Chronon phase | Existing reversible/geometric coordinate | Owning SystemEpoch |
| Chemical difficulty | Structural parsing/resource metric | Its declared algorithmic model |

These coordinates are not interchangeable. In particular:

- A channel sequence is not a semantic execution identity.
- A logical tick is not a wall-clock duration.
- Vector-clock order is not a physical latency measurement.
- Monotonic readings from different hosts must not be subtracted to invent one-way delay.
- Chemical difficulty is not calibrated seconds.
- A checkpoint restore starts a new local monotonic segment; it does not imply that downtime was measured.

The Temporal Clock Fabric is the existing clock contract. This M0 layer reuses its coordinates rather than defining a competing clock.

## 6. A communication path is a temporal composition of interpretations

A path is not only a route through physical links. It is an ordered or causally constrained composition of host transitions:

\[
s_{i+1}=T_{h_i}(s_i,m_i,\theta_i)
\]

where:
- \(s_i\) is the admitted state or reference at one path boundary;
- \(m_i\) is a message, byte-object reference, state reference or typed input;
- \(\theta_i\) is the declared operation context;
- \(h_i\) is the logical host that interprets and realizes the transition;
- \(T_{h_i}\) is that host's admitted transition relation.

A path can therefore carry references to large byte objects while moving only the data required for the next transition. The object may remain resident at one node while a small operation description travels to its host. Alternatively, a missing page can be resolved through an existing page provider.

The logical communication path survives replacement of a physical socket only when its reliable frames, semantic identities, committed effects, state references and recovery lineage are preserved. Raw bytes in a socket buffer are not durable logical state.

Communication does not compute by itself. Computation occurs where an admitted host interprets information and makes a resulting state or effect available to the next transition.

## 7. One hosting contract, two execution topologies

Both forms of distributed model execution use the same object, Ground, host, time, authority and recovery distinctions.

### 7.1 Replicated hosting

A complete computational artifact is admitted at multiple hosts. Each host advertises the same immutable artifact identity and its own runtime/implementation profile.

A request is resolved to an eligible host. The model artifact normally remains resident; the request, session reference and required state continuation travel through the fabric.

This topology distributes independent sessions and service capacity. It does not imply that one inference operation is divided across the replicas.

### 7.2 Partitioned execution

One declared computation is decomposed into typed partitions. Each partition is an independently identifiable operational locus with input/output representations, local state, implementation identity, budget and permitted transitions.

A dependency graph describes which partition outputs become which later inputs:

\[
G=(V,E)
\]

An edge is a typed data dependency, not an assertion that all nodes execute concurrently. A partitioned path may be pipelined, sequential, batched, or synchronized according to its declared execution method and available interconnect.

For a transformer, an initial pipeline may place different layer ranges at different hosts. Tensor parallelism and expert parallelism add different collective communication and synchronization contracts; they are not implied by basic partition routing.

### 7.3 Other computational domains

The same hosting contract can describe operating-system images, virtual CPUs, servers, databases, emulators, accelerator methods and other byte-representable structures.

Their internal semantics remain domain-specific. A common byte-object format does not make an ELF image executable by the MailCPU instruction scheduler, make a tensor interpretable by a CPU backend, or make an operating-system checkpoint portable across incompatible implementations.

## 8. Authority, causality and commit remain separate

A route witness proposes a candidate host and path. It cannot grant permission.

The receiving host reconstructs authority from its own capability state and applies Hypervisor policy. The operation must then validate the admitted System Ground, computational Ground, representation identity, causal prerequisites, state revision, implementation compatibility and budget.

For a state-owning operation, continuation should be guarded by the expected prior state identity:

\[
\operatorname{CAS}(h(s_i),s_{i+1})=
\begin{cases}
\operatorname{commit}(s_{i+1}) & \text{if the current state still hashes to }h(s_i)\\
\operatorname{refuse} & \text{otherwise}
\end{cases}
\]

A stateful engine may prepare a candidate transition, but it must not expose that candidate as committed state before the durable commit boundary. Publication and acknowledgement follow commitment. Exact retries locate the committed effect; they do not repeat the transition.

The existing E-CPU Hypervisor and recovery contracts remain authoritative. This document does not claim that arbitrary external side effects are already transactionally committed with the Hypervisor ledger.

## 9. When is a virtual description more effective?

A virtual description is useful when its declared transitions can produce the required observations and states under a bounded cost.

For a reference system \(R\), an implementation host \(h\), and observation projection \(O\), the semantic obligation is scoped to the declared cases:

\[
O(R(x))\approx_{\epsilon}O(T_h(x))
\]

The projection, tolerance, preconditions, context, implementation profile and evidence must be explicit. Agreement on one test case is not a proof over all inputs.

Compare the candidate and reference using a cost vector:

\[
\mathbf{C}=
(L,M,B,W,V,R)
\]

where a deployment may measure latency \(L\), resident memory \(M\), bytes moved \(B\), compute work \(W\), verification cost \(V\), and recovery risk \(R\).

These dimensions have distinct units. A policy may impose ceilings or a Pareto/lexicographic selection rule; collapsing them into one scalar is a policy choice.

A description becomes more effective only when it preserves the required observation while improving a relevant, measured cost or capability. Examples include less memory through demand paging, lower repeated work through cached state, higher availability through replicated hosting, or more useful execution through moving only the required state. Added serialization, network, verification and recovery costs must be counted.

## 10. Existing E-CPU correspondence

| Contract role | Existing E-CPU foundation |
|---|---|
| Host identity and transition | Communication Host Model |
| Semantic address | Computational Addressing and VirtualLayerWorkload |
| System Ground and causal frontier | VirtualGroundRef and admitted seed envelope |
| Computational Ground | VGI Ground fingerprint and other domain fingerprints |
| Immutable executable/byte artifacts | ExecutableImage, ArtifactIngestor, image registry |
| Fixed-size page backing | PageBacking and VirtualMemory |
| Remote content-addressed pages | RemotePageStore over replicated mailbox channels |
| Structural byte providers | StructuralMemoryFileProvider and StructuralMemoryPageBacking |
| Ordered operation path | HypervisorOperationChannel and ReliableChannel |
| Authenticated multi-hop routing | Computational Fabric and forwarding |
| Dependency structure | NavigableComputationDAG |
| Time and causal coordinates | Temporal Clock Fabric, CausalStamp, SystemEpoch and scheduler |
| Commit and replay | Hypervisor effect ledger and operation result channels |
| Recovery lineage | Recovery bundles and peer-scoped recovery stores |

The first M1 byte-object implementation deliberately composes the existing PageBacking interface and RemotePageStore. It does not create a new global clock, a competing address envelope, a second Hypervisor, or a new remote transport.

## 11. Proof boundary and next obligations

The M0/M1 foundation establishes portable object descriptions and a page-backed byte access method. It does not yet establish:

- a universal semantic interpreter for arbitrary bytes;
- automatic discovery of every object at every host;
- cross-host tensor layout conversion or numerical refinement;
- a general remote object catalog or garbage collector;
- transactional mutable session state such as an LLM KV cache;
- a partitioned model scheduler or collective tensor operations;
- native execution of arbitrary operating-system images;
- cryptographic origin authentication from a content digest alone.

The next model-hosting work should build typed model admission and backend identity over these objects, then introduce versioned inference sessions and committed state transitions. Partitioned execution should reuse the same artifact and byte references, adding only the partition and data-dependency contracts it requires.
