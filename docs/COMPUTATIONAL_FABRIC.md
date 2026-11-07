# Computational Fabric: Peer Discovery and Network Route Planning

## Purpose and design boundary

This specification connects semantic computational addresses to remote logical hosts without conflating a host with its physical placement or treating a network path as an execution engine.

The implemented first network slice is:

1. each peer owns a portable directory snapshot of its own logical host/operator advertisements and outgoing directed links;
2. configured peers exchange those snapshots directly over mutual TLS and the existing reliable MailCPU channel abstraction;
3. each receiving peer admits snapshots only after checking transport identity, TLS DNS identity, monotonic revision, and a receiver-local lease;
4. the local directory exposes the active peer/host/link view;
5. a bounded resolver plans a cost-feasible directed multi-hop route to an advertised host;
6. the route remains non-authoritative. It does not forward or execute the workload.

The receiver-local `ComputationalAddressResolver` and `ComputationalExecutionAdmissionCoordinator` remain the terminal semantic and execution boundaries. The fabric is a directory and planner, not a new Hypervisor.

## 1. The repository's graphs are different layers

The codebase already contains several useful graphs. They are related, but they have different vertices, edges, evidence, and authorities.

| Component | Graph / state domain | Existing responsibility | How the fabric composes |
|---|---|---|---|
| `EGPUHost` / `EGPUOperationalLocus` | operational loci within one composite host | Finds dispatch → SIMT/reduction/workgroup/shared-memory → verification paths | A remote host may itself contain this internal graph; network path planning ends at its peer/host identity |
| `ComputationalHostCatalogue` / `ComputationalAddressResolver` | receiver-local logical host/operator loci | Checks exact contract, Ground, program policy, placement, state references, budget, live process and capabilities | Remains the authoritative *local candidate check* at the destination |
| `ComputationalFabricDirectory` | active peer-owned snapshots | Federates portable host advertisements and directed peer links under direct TLS trust, monotonic revisions and leases | Makes remote logical host identities discoverable without exporting execution authority |
| `ComputationalFabricResolver` | directed peer topology | Finds a bounded cost/hop-feasible route from an origin peer to an advertised remote host | Selects a network path; it does not dispatch |
| `EvidencePathResolver` | representation identities and translation contracts | Chains exact source/target representations with projection evidence, context, prerequisites, invariants, live authority, and multidimensional cost | Can separately plan how a request/result representation must be translated; it is not a peer network router |
| `ContextualNavigator` / formal navigation | states of a described process or abstract transition system | Concrete and abstract reachability, causal ordering, invariants and bisimulation | May be used to reason about state inside a host after locating it |
| `NavigableComputationDAG` | operation dependency DAG | Owns node dependencies, readiness and committed predecessor results | Determines which computation is ready to request; fabric does not duplicate it |
| `TransitOrbitScheduler` | collection of live Transit paths | Deterministic round-robin/quantum selection among ready sessions | Continues to own path scheduling; peer routing does not become another scheduler |
| `TransitComputeSession`, `TransitComputeWorker`, `TransitBackendRouter` | one receiver execution path and exact operation/resource backend map | Reliable receive, receiver-side authority reconstruction, exact backend dispatch, effect/replay and result publication | A future forwarding/terminal service can use these existing path and backend boundaries |
| `VirtualLayerRuntime` + Hypervisor | local operator execution and policy | Rebuilds local capability grants, checks System Ground and operator contract, arbitrates and commits/replays effects | Remains the final execution authority at the destination |
| Structural Memory | revision/certificate/context/coordinate state family | Stores compact generative state, validates pinned reads and supplies VFS/VM/VLayer inputs | Host advertisements can state generic support; the destination must verify each exact pinned reference locally |
| `TransitPathBinding` / `TransitPathState` | live path telemetry and path-local memory/sensor/processor state | Separates physical RTT, local service time, queue depth, ACK and retry behavior | Can later supply measured data to calibrate peer link cost estimates |
| RecoveryLineage / RecoveryCheckpointBundle | checkpoint generations, provenance and quorum high-water | Verifies durable recovery lineage, membership and implementation manifests | Can later anchor a persisted directory/topology checkpoint and reject rollback |

The important composition is **nested navigation**. A DAG node may first require an evidence-backed representation conversion, then a network route to a remote E-GPU host, then an internal E-GPU method route, and finally a locally authorized operator execution. Each graph preserves its own identity and proof obligations. A route witness in one graph does not prove the others.

## 2. Host identity, placement, peer identity and implementation

Keep these coordinates separate:

- **Peer identity**: the configured endpoint that participates in a direct authenticated directory exchange.
- **TLS DNS identity**: the exact peer name checked against the certificate SAN and local trust mapping.
- **Logical host identity**: a named operational locus and its advertised operator contract.
- **Placement node**: the node to which a logical host is bound by its advertisement.
- **Implementation fingerprint**: a peer-declared source/profile identity. It is not independent runtime or hardware attestation.
- **Receiver authority**: local PID, capabilities, handler and live runtime object. These never cross the directory protocol.

Do not overload the historical `host_id` in `RecoveryLineageDeployment`: that schema uses it as an infrastructure placement-node identifier. The general host definition in `COMMUNICATION_HOST_MODEL.md` remains broader.

## 3. Peer-owned snapshots

`ComputationalFabricAuthority` is local to one peer. It registers only host loci owned by that peer and directed links whose source is that peer. When passed a `ComputationalHostLocus`, `ComputationalHostAdvertisement.from_locus()` projects only portable metadata; it strips PID/runtime/handler bindings.

A `ComputationalPeerSnapshot` binds:
- one `ComputationalPeerEndpoint`;
- a monotonic per-peer revision;
- a bounded lease duration;
- zero or more peer-owned host/operator advertisements;
- zero or more peer-owned outgoing directed links.

The receiver's `ComputationalFabricDirectory` has an explicit bootstrap trust map `peer_id → expected TLS DNS identity`. A remote snapshot is merged only when the transport peer ID, server certificate DNS identity, snapshot peer ID, and endpoint DNS identity agree. The TLS connection must also have required and verified the peer certificate chain.

A lower revision is rejected. Reuse of the current revision with changed content is rejected as equivocation. Equal revision and equal digest is idempotent, although it refreshes the local lease because a new authenticated observation was received. Expiry uses the directory's injected monotonic clock on the receiving peer; peer wall clocks are not compared. Local policy caps the maximum accepted lease. Expired snapshots are excluded from active route views and can be purged.

The directory applies finite bounds to peers, host advertisements and links. A peer may publish only its own hosts and outgoing links; it cannot use its snapshot to impersonate another peer's host ownership or add a reverse edge on behalf of another peer.

## 4. Mutual-TLS and reliable snapshot exchange

`ComputationalFabricPeerClient.connect_mutual_tls()` reuses `mtls_transport.connect_mutual_tls()` and `SocketTransport`. `ComputationalFabricPeerServer.accept_mutual_tls()` reuses the server-side mutual-TLS accept helper. The snapshot request and response use `ReliableChannel` with explicit request/response channel names, sequence/ACK handling, correlation IDs, bounded frame sizes, and a finite RPC deadline.

The client refresh flow is deliberately narrow:
1. open a direct authenticated stream to one configured peer;
2. request its current snapshot;
3. validate response peer ID and request correlation;
4. reconstruct the strict portable snapshot;
5. require the snapshot endpoint to equal the authenticated/configured endpoint;
6. merge it under the directory's peer/DNS/revision/lease checks.

No PID, callable, handler, capability grant, or executable code is transmitted. The server returns only the peer's own current snapshot.

## 5. Multi-hop route selection

`ComputationalFabricResolver` consumes one captured active directory view and binds its directory and topology digests into every result. It builds adjacency only from enabled directed links whose destination peer has an active authenticated snapshot, whose route-cost dimensions and units match the address objective, and whose advertised frame bound can carry the canonical address planning envelope.

It searches the peer graph using bounded lexicographic Dijkstra. Search state includes both peer identity and hop count: a single cheapest prefix per peer is not sufficient under a hop ceiling, because a more expensive but shorter prefix can be the only feasible continuation. Cycles are excluded. Equal objective costs use stable hop-count, peer-path and link-ID tie-breaks.

At a candidate peer, the resolver filters its advertised hosts against:
- exact operator ID, version and contract digest;
- deterministic pure operator policy;
- exact Computational Ground fingerprint;
- exact program fingerprint, or explicit Ground-bounded compilation for an unpinned program;
- target node and eligible-node set;
- preferred/available substrate;
- output observation kind and input JSON kind/byte limit;
- Structural Memory support for workloads with pinned references;
- implementation fingerprint presence;
- estimated energy, virtual ticks, network/host metric dimensions, and combined cost ceilings.

The result is the least-cost feasible target after adding its declared host cost vector to the selected network path cost. The route witness preserves that decomposition rather than collapsing every metric into a single scalar. Search limits include maximum hops, maximum expansions, per-link frame bytes and aggregate resource ceilings.

The cost values are declarations supplied by the peer/host authority. They are not measured physical guarantees. Link cost calibration is a future integration with `TransitPathBinding` observations; the route code must retain separate units rather than invent a universal energy/latency conversion.

## 6. Authority and execution boundary

The fabric result and route witness both report `authoritative=False`. They are not capability tokens and do not prove that the remote process remains alive after its snapshot was observed. A lease only bounds how long a remote advertisement remains in the origin's active planning view; it does not pin remote state or authority.

This branch implements **direct peer discovery and multi-hop planning**, not multi-hop forwarding or remote execution. The origin currently needs a direct authenticated snapshot for every peer in the topology view, including intermediate and destination peers. The resolver does not recursively discover neighbours, relay requests, select a backend process at the destination, or call a remote operator.

A later execution pipeline must add a separately admitted operation at every hop. At the destination it must:
1. receive a typed workload over the existing reliable Transit operation channel;
2. resolve the address against a local `ComputationalHostCatalogue` and current HeadlessOS state;
3. verify exact local host/runtime implementation and pinned Structural Memory state;
4. invoke `ComputationalExecutionAdmissionCoordinator`;
5. allow Virtual Layer capability reconstruction and Hypervisor policy/effect/replay to decide the operation;
6. return evidence and receipts correlated with the original semantic request.

Forwarding requires its own limits and proof: peer-local authority, source/destination binding, sequence/replay identity, deadline, hop decrement, payload/frame bound, loop prevention, failure/timeout semantics, route freshness, and per-hop receipts. An intermediate router must not convert a remote route witness into rights. End-to-end result provenance and crash recovery will need checkpoint/replay identities and, for rollback-sensitive persistent fabric state, a RecoveryLineage commitment.

## 7. Testable milestones

**Demonstrated by this first slice:** portable host advertisement strips receiver authority; peer snapshots enforce ownership; direct peer identity and DNS trust are checked; revisions cannot roll back or equivocate; leases expire on receiver monotonic time; route search follows directed links, respects cost/hop/frame limits, selects deterministically, preserves short feasible alternatives, and round-trips its non-authoritative route receipt; a mutual-TLS peer exchanges a reliable snapshot that is then used to produce a multi-hop route plan.

**Next:** checkpoint the local directory and peer revision/lease state under a recovery manifest; add an authenticated multi-peer topology discovery protocol (gossip or directory federation) without trusting relayed peer claims; implement hop-by-hop request forwarding with its own Hypervisor admission and end-to-end operation identity; dispatch at the terminal host through the existing local resolver and execution coordinator; calibrate route estimates from measured path/service telemetry; exercise peer loss, expired routes, stale revisions, forwarding retries, intermediate crash, destination crash and end-to-end recovery.

