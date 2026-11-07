# Computational Addressing and Execution in Transit

## Purpose

This note formalizes one architectural direction for E-CPU: a computational system can be treated as a persistent, addressable transition structure whose state and operations are reached through communication. The execution substrate may be a local CPU, an E-GPU method, another server, or a later distributed backend. Computational identity should not be confused with the machine or process that realizes one transition.

This is an architectural synthesis, not a claim that E-CPU already has a universal network-wide state-space resolver. The current implementation supplies several necessary primitives: typed Virtual Layer workloads, Ground and operator identities, exact Transit routing, receiver-local authority reconstruction, execution ledgers, durable channel state, and quorum-gated recovery bundles.

## 1. Computational structure

Represent one declared computational domain as:

\[
\mathcal{C}=(G,P,\Sigma,\Delta,\mathcal{R})
\]

where:

- \(G\) is the computational Ground: domain, valid representations, assumptions, and observation rules;
- \(P\) is the program or declared transition relation;
- \(\Sigma\) is its state space, including materialized states and states that can be procedurally reconstructed;
- \(\Delta\) is the set of permitted state transitions;
- \(\mathcal{R}\) resolves a request to an eligible execution capability and verified path.

Ground and program descriptions may be finite even when the set of possible executions is very large. The system does not need to enumerate every possible state. It needs sufficient rules and identity to generate, locate, restore, and verify states relevant to admitted requests. Every real implementation remains bounded by declared execution, memory, time, and placement limits; this is not a claim of unbounded physical computation.

A computation path is a composition of transitions:

\[
s_n = T_n \circ T_{n-1} \circ \cdots \circ T_1(s_0)
\]

A transition may be realized by a different host from its predecessor. The path is therefore the logical composition of verified transformations, not necessarily one process or one chip.

## 2. Computational address

A request can be represented by a semantic address:

\[
A=(G_s,G_c,P,\theta,x,\tau,O)
\]

where:

- \(G_s\): admitted E-CPU System Ground and causal frontier;
- \(G_c\): computational Ground under which the operation has meaning;
- \(P\): program/task identity and, after compilation, its compiled fingerprint;
- \(\theta\): intention and requested operation;
- \(x\): a state coordinate, content reference, checkpoint, or Structural Memory address;
- \(\tau\): logical execution coordinate and causal position;
- \(O\): requested observation or output projection.

An address is semantic rather than physical. It does not contain a required server IP, process ID, or CPU core. It names what is requested and the conditions under which a result is valid. A resolver may choose a physical implementation later, subject to policy, capability, budget, Ground compatibility, and refinement evidence.

### Existing E-CPU correspondence

| Address component | Existing E-CPU representation |
|---|---|
| System Ground \(G_s\) | VirtualGroundRef(origin_digest, state_digest, coordinate, frontier_digest) |
| Computational Ground \(G_c\) | Domain fingerprint, such as VGI SIGNAL8_GROUND.fingerprint |
| Program \(P\) | Typed task payload and compiled program fingerprint in the execution receipt |
| Intention \(\theta\) | VirtualLayerWorkload.intention, operator reference, and event operation/resource |
| State coordinate \(x\) | Input digest, Structural Memory references, state/checkpoint data and recovery bundle references |
| Logical/causal coordinate \(\tau\) | Workload logical time, event channel/sequence, reliable cursors, Ground frontier, and execution journal |
| Observation \(O\) | Declared output kind, result digest, execution trace, translation evidence, and oracle evidence |
| Candidate placement | eligible_nodes, substrate constraints, hop budget, and receiver-local Transit backend registration |

VirtualLayerWorkload already carries most of the semantic address. E-CPU should extend that existing structure only when a new field adds a distinct, enforced proof obligation; it should not create a second parallel request/address protocol.

The correspondence has an important limit: the current TransitBackendRouter resolves an exact operation/resource pair against a receiver-local registry. It is not yet a global resolver that searches all reachable hosts, checkpoints, and execution paths for an arbitrary semantic address.

## 3. One interface, four different operations

The address can expose several operation modes. They share identity and validation, but they must not be conflated.

### Locate

\[
\operatorname{Locate}(A)\rightarrow (s,\rho)
\]

Find an already materialized or committed state/effect and return a receipt \(\rho\). In current E-CPU, exact event retry can locate a committed execution effect through the hypervisor execution ledger and replay it without invoking the backend again.

This is not yet arbitrary random access to every intermediate program state or every historical snapshot. A general state index and queryable state catalogue would be a future capability.

### Restore

\[
\operatorname{Restore}(A,B)\rightarrow s
\]

Reconstruct state from a digest-checked checkpoint and recovery bundle \(B\), only after its lineage proof, backend domain, implementation identities, and local runtime constraints are accepted. Recovery can replace the process and transport connections while retaining the committed computation.

### Continue

\[
\operatorname{Continue}(A,s,m)\rightarrow s'
\]

Admit a new transition from a known state using message or task input \(m\). The new event receives a new execution identity. An exact retry of an already committed event returns its effect; a different input under the same execution identity is a conflict, not a new continuation.

### Transform

\[
\operatorname{Transform}(G,P,s,\theta)\rightarrow (s',O)
\]

Apply the declared operator or program transition and produce an observation under the declared Ground. For VGI Signal8, the workload is compiled to typed VGI IR, executed with a bounded step limit, and returned with Ground, program, trace, checkpoint, and execution digests.

## 4. Resolution and path selection

A future general resolver can be expressed as:

\[
\operatorname{Resolve}(A,\mathcal{H})\rightarrow(h,\rho,s,\pi)
\]

where \(\mathcal{H}\) is the available host/capability set, \(h\) is a selected host, \(\rho\) is its receiver-local authority context, \(s\) is the located or restored state, and \(\pi\) is the transition route.

The candidate path set is:

\[
\Pi(A)=\{\pi\mid \pi\text{ satisfies Ground, causal, capability, and budget constraints}\}
\]

A route objective can be represented as a vector rather than collapsing incomparable quantities into one arbitrary scalar:

\[
\mathbf{C}(\pi)=(L(\pi),E(\pi),B(\pi),R(\pi))
\]

where declared dimensions may represent latency, energy, byte movement, and recovery/verification risk. Selection may use a policy-defined lexicographic order or explicit ceilings:

\[
\pi^*=\operatorname*{arg\,min}_{\pi\in\Pi(A)}^{\text{policy}}\mathbf{C}(\pi)
\]

No route is admissible merely because it is cheap. It must first satisfy semantic compatibility, local authority, causal dependencies, workload budgets, and the required verification tier.

Today, E-CPU has exact local dispatch and several specialized navigation/path-resolution components. A global resolver across networked hosts, persistent streams, and checkpoint catalogues remains proposed work.

## 5. The required order of operations

A safe request path should preserve this order. Exact internal call boundaries may vary, but proof dependencies should not.

1. **Canonicalize and bind the request.** Validate the typed request, input digest, and stable execution identity.
2. **Validate both Grounds.** Check the admitted System Ground and causal frontier; separately check the computational Ground fingerprint and its assumptions.
3. **Resolve the declared program and operator contract.** Match operator ID, version, schema, contract digest, and program identity.
4. **Resolve state and candidate placement.** Locate an existing effect/state or select an admissible checkpoint and receiver-local backend. Keep physical placement late-bound.
5. **Reconstruct local authority.** Derive permissions from the receiving system's own capability state. Never accept remote claims of authority as grants.
6. **Select the operation mode.** Locate, restore, continue, or transform. Do not execute a committed effect merely to rediscover it.
7. **Execute and verify.** Enforce resource bounds and check the result against declared observations, translation contracts, or independent oracles where available.
8. **Commit semantic effect.** Bind the result and evidence to the event identity in the execution ledger/journal.
9. **Publish and acknowledge.** Only after commit, make the effect available over the replaceable communication connection and acknowledge reliable delivery.

The commit-before-publication order is the continuity boundary exercised by the Transit VGI process-death experiment.

## 6. Communication path as execution path

Communication is a carrier and causal structure; it does not compute by itself. A computation is realized when a participating endpoint applies an admitted transition and makes the resulting state/effect available to the next step.

The full logical path can therefore be:

\[
m_0\xrightarrow{T_1,h_1}m_1
\xrightarrow{T_2,h_2}m_2
\xrightarrow{T_3,h_3}\cdots
\xrightarrow{T_n,h_n}m_n
\]

Each \(T_i\) is a declared transformation; \(h_i\) is the host/substrate that realizes it. Hosts may be heterogeneous or replaced between steps. The composition behaves as one computational path only when each edge preserves the required identity, causal, authority, and observation invariants.

### Causality is not a universal wall clock

logical_time is a logical coordinate, not a claim that all distributed transitions share one physical clock or one global total order. Channel sequence, execution identity, Ground frontier, and recorded dependencies help establish causal ordering. Independent branches may progress concurrently. Non-commuting transitions cannot be reordered merely because separate hosts are available; reordering requires an explicit independence or commutativity argument.

### Durable state is not the socket buffer

For recovery, distinguish the durable logical path state:

\[
X=(C,Q,L,E)
\]

where:

- \(C\): persistent checkpoints and admitted structural state;
- \(Q\): durable queued/retry frames and reliable-channel cursors;
- \(L\): execution/commit/replay ledger;
- \(E\): execution receipts, event journal, and verification evidence.

Raw bytes unread in a particular TCP connection are not durable state. A terminated connection may lose them. E-CPU's recovery design retains the sender's reliable frame and receiver's committed execution state, then reconnects over a fresh transport and retransmits. Thus the communication relationship and protocol state can persist while a particular socket does not.

## 7. Implementation identity and semantic refinement

A host follows the normative definition in [COMMUNICATION_HOST_MODEL.md](COMMUNICATION_HOST_MODEL.md):

\[
H=(I,C,S,T,K,L)
\]

It is an identifiable operational locus with logical identity \(I\), communication interfaces/adjacency \(C\), operational state \(S\) (which may be empty for a stateless transform), transition relation \(T\), permitted capabilities \(K\), and operational lineage \(L\). A host is therefore not synonymous with a server, process, CPU, or placement node. A passive network link is a substrate edge; a queue, router, filter, or scheduler becomes a host only when it owns a defined operational transition and capability. A logical host may be realized by different resources over time, provided its identity and lineage continuity obligations are preserved.

For this address model, the **host** is the locus that owns or exposes the requested operation; the **implementation** is the concrete source/profile used to realize its transition; and **placement** is the current physical or virtual realization. A process ID and in-memory objects may disappear. A replacement host is admissible only if it reconstructs the required authority and rebinds an implementation satisfying the saved contract and continuity conditions. The source fingerprint below identifies implementation, not the logical host itself.

Keep these identities separate:

1. **System Ground** — admitted E-CPU system context and causal frontier.
2. **Computational Ground** — the domain's formal meaning and observation rules.
3. **Program** — the typed task and compiled transition relation.
4. **Input/context** — the concrete request, values, constraints, and context digest.
5. **Operator contract** — declared operation, version, types, resources, and rights.
6. **Implementation** — concrete source identity and relevant execution profile.
7. **Host** — current placement and receiver-local authority.
8. **Execution** — one event identity, decision, committed effect, and receipt.

The VGI Transit path records a source fingerprint for the E-CPU/VGI Python implementation and concrete host class. Transit checkpoint schema v3 binds each registered dispatch key to an optional implementation fingerprint; restore compares the replacement backend manifest before reconstructing the worker. For VGI, the configured step bound is also part of the backend implementation identity. The VGI execution receipt carries the source-package fingerprint, while the outer Transit effect and checkpoint carry the concrete backend fingerprint.

This fingerprint is deliberately scoped. It hashes the installed mailcpu and VGI Python source packages and the concrete host class source. It is not a signature, hardware/firmware attestation, Python ABI identity, complete operating-system image identity, or proof that a remote machine is trustworthy. Deployment authenticity and measured runtime attestation would require a separate trust model.

A later heterogeneous backend will need a formal refinement claim. In one possible form, if an abstract Ground transition is \(T\) and host \(h\) realizes it with concrete implementation \(I_h\), then:

\[
\operatorname{Obs}_{O}(I_h(s))\approx_{\epsilon}\operatorname{Obs}_{O}(T(s))
\]

The observation projection \(O\), tolerance \(\epsilon\), allowed stuttering/microsteps, and proof evidence must be declared by the operator contract. Existing semantic-translation and oracle checks provide useful foundations, but general Ground-to-Operator refinement across CPU, GPU, FPGA, and network backends is not yet established.

## 8. Executable first slice: local semantic Locate/Resolve

The first executable resolver is implemented in `mailcpu/computational_resolver.py`. It intentionally reuses `VirtualLayerWorkload` rather than defining a competing request envelope:

```python
address = ComputationalAddress.from_workload(
    workload,
    operator_id="vgi.signal8.execute",
    operator_spec=host.runtime.registry.contract("vgi.signal8.execute"),
    computational_ground_fingerprint=signal8_ground_fingerprint,
    program_fingerprint=compiled_program_fingerprint,  # optional exact program pin
)

locus = ComputationalHostLocus.from_runtime(
    host_id="logical-vgi-host",
    runtime=host.runtime,
    authority_pid=host.authority_pid,
    operator_id="vgi.signal8.execute",
    computational_ground_fingerprints=(signal8_ground_fingerprint,),
    program_fingerprints=(compiled_program_fingerprint,),
    costs=declared_cost_vector,
    implementation_fingerprint=host.implementation_fingerprint,
)

catalogue = ComputationalHostCatalogue((locus,))
resolution = ComputationalAddressResolver().resolve(address, catalogue, receiver_os)
```

The executable slice is a **receiver-local** catalogue. Each locus has a stable logical `host_id`, a separately represented `node_id` placement, a local authority PID (not exported in catalogue metadata), an exact `OperatorSpec`, supported computational Grounds/programs/substrates, resource ceilings, cost estimates, and optional implementation fingerprint.

Resolution verifies the locally admitted System Ground and causal frontier, exact operator contract, computational Ground, node eligibility, substrate, observation kind, input type/bytes, virtual energy/ticks, live process status, required local capabilities, and pinned Structural Memory revision metadata where advertised. Structural Memory validation uses the immutable admitted revision plus its certificate/context/horizon validator; it does not evaluate the coordinate or append a read event. If the address pins a program fingerprint, the host must advertise that exact fingerprint; an unpinned program is admissible only when the host explicitly advertises Ground-bounded dynamic compilation. It then chooses a feasible candidate by the address's ordered metric vector with stable logical-host/node tie-breaking. If no candidate passes, the result records deterministic blockers instead of inventing a route.

The resulting `ComputationalRouteWitness` binds the address/catalogue digests, logical host, placement node, authority snapshot digest, both Ground identities, operator contract, input/state digests, program/implementation identity, resource estimate, and selected costs. In this version the observation constraint is the operator's declared output kind; a richer projection identity must wait until the operator contract itself exposes a typed observation-projection contract. Both witness and resolution result explicitly expose `authoritative=False`: route discovery does not grant rights, create a Hypervisor decision, or execute an operation. The normal Virtual Layer/Transit preparation and Hypervisor arbitration must still happen at execution time.

For this first slice, **Locate** means that inline workload input is already materialized, or that every pinned Structural Memory reference can be resolved under the selected host's local read capability. Arbitrary intermediate-machine-state lookup, general checkpoint catalogues, and remote host discovery are not claimed. Advertised route costs are caller-supplied estimates, not measured latency/energy guarantees. The existing evidence-path resolver remains responsible for a different problem: chaining verified representation translations with evidence and cost constraints.

## 9. Executable second slice: witness revalidation and execution handoff

The next executable layer is implemented in \`mailcpu/computational_execution.py\`. It accepts the existing non-authoritative route witness, resolves the address again against the current receiver-local catalogue and live OS state, requires the exact witness digest to be reproduced, verifies that the concrete runtime still matches the selected locus, and then invokes the existing Virtual Layer execution method.

\`\`\`python
admission = ComputationalExecutionAdmissionCoordinator(receiver_os)
outcome = admission.execute(
    address,
    resolution.witness,
    catalogue,
    selected_runtime,
    source="semantic-client",
    channel="computational.execution",
    sequence=1,
)
\`\`\`

The coordinator does not issue a capability grant or execute an operator directly. It verifies the current catalogue, System Ground/frontier, process state and rights, operator contract, route costs, and selected host identity. It separately checks the supplied runtime's node, exact receiver-local runtime object and handler binding, operator contract, substrate selection, and resource profile against that host locus. Execution requires an explicit host implementation fingerprint that matches the witness; the fingerprint is a trusted source/profile declaration, not independent attestation. A stale witness, changed catalogue, changed authority snapshot, unavailable host, missing implementation pin, or runtime mismatch fails closed before dispatch.

For an accepted handoff, the coordinator derives a deterministic computational-admission context from the address and witness. \`VirtualLayerRuntime.build_event()\` and \`execute_operator()\` now accept this optional context. The runtime validates its digest and checks that its node, operator/version/contract, workload time, input/state digests, System Ground digest, observation kind, and selected substrate match the actual event. The context is included in the event payload; consequently the ordinary Hypervisor execution fingerprint and effect/replay ledger bind the route witness and its admission context to the operation identity.

Execution still follows the existing path: the runtime reconstructs receiver-local capabilities, checks the current System Ground and exact local operator implementation, and delegates to the Hypervisor's CPU execution/effect ledger. Structural Memory values are read only inside the normal post-ALLOW operator handler. An exact retry with the same source/channel/sequence and the same address, witness, and context replays the committed effect without re-entering the handler. Reusing that event identity for a changed address or witness changes the event fingerprint and is rejected by the existing replay-conflict rule.

The wrapper returns a typed result distinguishing executed, replayed, Hypervisor-refused, stale-witness, host-mismatch, and execution-failure outcomes. Its journal receipt correlates revalidation and the actual Hypervisor result. A receipt or route witness is not a reusable grant: every call resolves again, and the ordinary Virtual Layer/Hypervisor checks remain mandatory.

The slice remains receiver-local. An implementation fingerprint in a locus is still trusted advertised source/profile identity, not independent runtime or hardware attestation. The optional program fingerprint is likewise a host-advertised exact identity; this layer does not load arbitrary program bytes or prove hardware refinement. Global discovery and multi-hop routing remain future work.

## 10. Executable third slice: authenticated fabric discovery and multi-hop route planning

The first network-wide layer is implemented in `mailcpu/computational_fabric.py`. It composes the existing mutual-TLS framed transport and reliable-channel protocol with portable host advertisements and a bounded directed peer graph.

A peer publishes its own host/operator advertisements and outgoing links through `ComputationalFabricAuthority`. Its `ComputationalFabricPeerServer` answers snapshot requests over a direct mutual-TLS connection. A configured peer uses `ComputationalFabricPeerClient` to fetch the snapshot and merge it into `ComputationalFabricDirectory`:

```python
directory = ComputationalFabricDirectory(
    local_peer_id="peer-a",
    trusted_peers={"peer-b": "compute-b.example.net"},
)
directory.register_local_snapshot(local_authority.snapshot())

client = ComputationalFabricPeerClient.connect_mutual_tls(
    "peer-a",
    remote_endpoint,
    client_tls_context,
)
client.refresh(directory)

route = ComputationalFabricResolver().resolve(
    address,
    directory,
    origin_peer_id="peer-a",
    max_hops=8,
    max_expansions=4096,
)
```

Trust begins with an explicit local mapping from peer identity to expected TLS DNS identity. The underlying TLS helper validates the certificate chain and peer name. The directory merge also checks that the authenticated transport peer, configured DNS identity, and snapshot peer/endpoint identities agree. A snapshot revision cannot move backwards; different content at the same revision is treated as peer equivocation. A received snapshot receives a receiver-local monotonic lease, bounded by local policy. Wall-clock timestamps are not used to order peer revisions or lease expiry.

A portable host advertisement is deliberately not a local execution locus. It contains logical host identity, placement node, operator contract/version, Ground/program support, substrate and resource declarations, estimated cost vector, and an optional implementation source/profile fingerprint. It does **not** contain the receiver PID, capability set, runtime object, or callable handler. Remote claims identify candidates; they do not create local authority or prove the remote process is currently alive.

Peers advertise only their own host records and outgoing directed links. The directory accepts remote snapshots only from a directly authenticated configured peer. The resolver plans across the active peer graph, with explicit direction, deterministic lexicographic additive metrics, tie-breaks, hop and expansion limits, per-link frame ceilings, operator/Ground/program/placement/substrate/observation checks, resource ceilings, and a required implementation identity pin. It preserves separate best path labels by peer and hop count so a cheaper but too-long prefix cannot suppress a shorter feasible alternative.

The result is a digest-bound `ComputationalFabricRouteWitness` with the ordered peer path, link identities, peer endpoints, candidate logical host, and separate network, host, and total cost vectors. Both the result and witness explicitly remain `authoritative=False`. Peer costs are advertised estimates; they are not measured latency or energy guarantees. The frame-size check uses the canonical serialized address size as a bounded planning estimate, not a guarantee of final transport frame size.

### What this connects—and what it does not

This is the first federated discovery and multi-hop **planning** slice, not a multi-hop execution or forwarding service. The origin currently needs a direct authenticated snapshot for each peer represented in its directory, including peers that are intermediate nodes or the destination. The planner does not recursively query a peer for its neighbours, does not ask peers to forward requests, and does not dispatch the planned operation.

When forwarding is added, each hop will need its own peer-bound admission, request/replay identity, resource and payload checks, deadline, causal receipt, and failure handling. At the destination the request must still be resolved against that receiver's local `ComputationalHostCatalogue` and then pass through `ComputationalExecutionAdmissionCoordinator`, the Virtual Layer, local capability reconstruction, and Hypervisor policy/effect ledger. A fabric route witness will never replace those checks.

The route also solves a different problem from the existing navigation components:

- `EGPUHost` navigates a directed graph **inside one composite logical host** (dispatch, SIMT, workgroup/shared memory, reduction, verification).
- `ComputationalFabricResolver` navigates a directed graph **between peer identities** to reach an advertised remote host.
- `EvidencePathResolver` navigates a graph **between representation identities** through exact translation contracts, observation comparisons, prerequisites, invariants, and evidence.
- `ContextualNavigator` and the formal navigation modules traverse a described process's **state space**.
- `NavigableComputationDAG` owns operation dependencies/readiness; `TransitOrbitScheduler` owns deterministic path-quanta selection. Fabric discovery does not duplicate either one.

These graphs may eventually compose. A DAG node may require a representation translation, a network route to an E-GPU host, and then an internal E-GPU method path. Each graph keeps its own identity and proof obligations; one route receipt does not silently prove the others.

## 11. What exists now and what remains proposed

**Already present in E-CPU:** typed Virtual Layer workloads; separate System and Computational Grounds; versioned operator contracts; local capability reconstruction; exact Transit dispatch; reliable message channels; causal sequence/frontier data; execution commit/replay ledgers; Structural Memory references; checkpoints; quorum-verified recovery bundles; backend dispatch manifests; VGI source-implementation fingerprint checks during restoration; receiver-local semantic-address resolution; witness revalidation and Hypervisor-governed execution handoff; and the first authenticated peer directory plus cost/hop-bounded multi-hop route planner.

**Not yet a general capability:** recursive discovery/gossip or a global name service; hop-by-hop forwarding and end-to-end dispatch across the selected peer path; terminal remote invocation through a network RPC execution service; an index for arbitrary intermediate state or checkpoint coordinates; transparent migration of arbitrary live processes between CPU/GPU/FPGA substrates; independently attested remote runtime/hardware identity; or general proofs that any replacement implementation refines any Ground.

The prudent direction is compositional: keep peer trust and logical host identity explicit, connect each graph only through typed contracts, measure route costs from real path observations, and require each destination to re-establish local authority. A continuous computational environment should emerge from persistent commitments and procedural reachability—not from equating advertised addresses with execution authority or treating network transport itself as a processor.

