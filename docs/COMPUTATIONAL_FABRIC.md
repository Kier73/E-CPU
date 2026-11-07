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
| RecoveryLineage / RecoveryCheckpointBundle / `ComputationalFabricRecoveryStore` | checkpoint generations, provenance and quorum high-water | Verifies durable recovery lineage, membership and implementation manifests; the fabric store seals its single-state directory artifact through the same coordinator | Preserves directory anti-rollback state without reviving expired remote leases |

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

A lower revision is rejected. Reuse of the current revision with changed content is rejected as equivocation. Equal revision and equal digest is idempotent, although it refreshes the local lease because a new authenticated observation was received. Expiry uses the directory's injected monotonic clock on the receiving peer; peer wall clocks are not compared. Local policy caps the maximum accepted lease. Expired snapshots are excluded from active route views and can be purged. Aggregate peer/host/link capacity is measured against live leases, so an expired last-known snapshot cannot indefinitely prevent a fresh peer from being admitted even before explicit purge.

The directory applies finite bounds to peers, host advertisements and links. `ComputationalFabricAuthority.from_snapshot()` can restore a peer's portable advertisement revision, host records and outgoing links. That restores directory metadata only: the peer must rebind/re-register its local executable runtimes and handlers; no PID or callable is recovered from the snapshot.

`ComputationalFabricDirectory.checkpoint()` exports the trust map, local policy limits, and every peer's revision/digest high-water mark, including marks retained after lease expiry. `from_checkpoint()` verifies the canonical checkpoint digest and restores those rollback guards, but deliberately restores **no remote snapshots and no monotonic lease deadlines**. The local peer must re-register its current snapshot; each remote peer must be contacted directly over mutual TLS to obtain a new active lease. A restored lower revision is rejected, and a same-revision content change remains equivocation. This avoids comparing monotonic timestamps across process or machine lifetimes.

The checkpoint digest detects accidental or partial content modification; it is not an authentication signature and can be recomputed by an actor able to rewrite the checkpoint. The bare checkpoint API does not itself persist bytes or establish a quorum commitment.

`ComputationalFabricRecoveryStore` closes that gap using the existing `RecoveryLineageCoordinator` without overloading the requester/receiver Transit bundle. It writes a canonical `directory.json` artifact and a typed `RecoveryStateManifest` into an immutable generation directory, fsyncs the files and directory, then seals the manifest root through the configured strict-majority quorum. Restore reads the quorum high-water first, checks the artifact digest and canonical manifest, requires an exact match to the current generation, and only then reconstructs the directory. A locally durable but unanchored artifact, modified artifact, or older generation is refused. The recovered directory retains peer revision anti-rollback marks and trust policy, but still has no active remote snapshots or leases until fresh direct mutual-TLS observations are accepted.

The checkpoint artifact digest is an integrity binding; the independent recovery authority quorum supplies the rollback-resistant high-water decision. Recovery membership/owner configuration remains local trusted bootstrap state and must match at reopen. The existing `RecoveryCheckpointBundleStore` remains dedicated to requester/receiver Transit bundles.

A peer may publish only its own hosts and outgoing links; it cannot use its snapshot to impersonate another peer's host ownership or add a reverse edge on behalf of another peer.

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

**Demonstrated by this slice:** portable host advertisement strips receiver authority; peer snapshots enforce ownership; direct peer identity and DNS trust are checked; revisions cannot roll back or equivocate within a directory process or across its checkpoint reconstruction; restored remote peers have no live lease until directly re-authenticated; expired snapshots do not consume live directory capacity; route search follows directed links, respects cost/hop/frame limits, selects deterministically, preserves short feasible alternatives, and round-trips its non-authoritative route receipt; a live three-peer test directly discovers B and C over distinct mutual-TLS identities, resolves A→B→C, expires the lower-cost destination's receiver-local lease, fails over to a compatible but more expensive host on B, then re-observes C over its authenticated channel and returns to the lower-cost A→B→C route; a single-artifact directory checkpoint is persisted and sealed through the existing strict-majority RecoveryLineage coordinator, and restore rejects modified, stale, and unanchored generations without reviving remote leases; a second integration test carries the discovered host identity through a fresh destination-local semantic resolution and Hypervisor execution, without treating the fabric witness as authority.

**Next:** add an authenticated multi-peer topology discovery protocol (gossip or directory federation) without trusting relayed peer claims; implement hop-by-hop request forwarding with its own Hypervisor admission and end-to-end operation identity; dispatch at the terminal host through the existing local resolver and execution coordinator; calibrate route estimates from measured path/service telemetry; exercise peer loss, forwarding retries, intermediate crash, destination crash and end-to-end recovery.


## 8. Authenticated hop-by-hop forwarding

The new ComputationalFabricForwardingEnvelope carries the portable computational address, the non-authoritative origin route proposal, the original (origin peer, origin channel, origin sequence, logical time) identity, and one exact peer-path cursor. It carries no PID, handler, runtime object, capability grant, or executable code. The forwarding channel is a deterministic namespace derived from the origin peer and origin channel; the original sequence remains the operation sequence at every hop.

ComputationalFabricForwardingClient.forward() advances exactly one directed edge. Each receiver uses ComputationalFabricForwardingServer and the existing HypervisorOperationChannel, HypervisorOperationResultChannel, ReliableChannel, and local HeadlessOS.hypervisor_authorize_event() path. No new fabric scheduler or second execution ledger is introduced.

Every receiving peer performs these checks before an effect:
1. The request event is bound to the immediate authenticated TLS peer, the configured origin channel, and the original operation sequence.
2. The envelope cursor names this peer as its current coordinate and the TLS peer as its previous coordinate.
3. The previous peer's active, receiver-local snapshot owns the exact incoming directed link; this peer's own active snapshot owns the exact outgoing link.
4. The next endpoint equals both the next route endpoint and the active directly observed endpoint, and the configured TLS DNS identity matches the authenticated certificate.
5. The envelope fits the receiver, transport, and directed-link frame bounds; the route remains cycle-free and within both the workload and forwarding hop ceilings.
6. The local process is granted the exact /network/computational-fabric/forward forward right at a relay, or /network/computational-fabric/execute execute right at the terminal peer, by the receiver's own Hypervisor.

An intermediate peer forwards only after its local Hypervisor has admitted the forwarding operation. The next peer repeats the same checks with its own directly observed directory view. A peer does not trust the origin's directory digest as a substitute for its local edge/lease checks; the route witness is still only a route proposal.

At the terminal peer, the server compares the advertised target host against the exact current local ComputationalHostLocus, calls ComputationalAddressResolver against the live local catalogue and HeadlessOS, and then invokes ComputationalExecutionAdmissionCoordinator. The coordinator revalidates the witness again and enters the existing Virtual Layer and Hypervisor path. The terminal operation uses the original origin identity, so its semantic replay key is stable across intermediate hops. The terminal peer's execution capability and the selected host process's Virtual Layer compute capability are separate local grants.

Each peer returns a ComputationalFabricHopReceipt containing its local Hypervisor decision receipt and either a child receipt bound to the exact next envelope digest or the terminal ComputationalExecutionResult. The receipt tree is content-addressed and validates peer adjacency, hop index, operation identity, and child-envelope continuity. The origin reports success only when the terminal outcome is both accepted and executed; a refused terminal result propagates as a failed receipt tree.

ReliableChannel supplies at-least-once delivery and bounded retries. The receiver's existing Hypervisor execution ledger supplies semantic deduplication: retrying the same operation identity and payload reuses its committed result; changing the payload under the same identity conflicts. In particular, a relay whose downstream operation committed but whose response was lost can retry the same child request and obtain the downstream peer's stored result without re-entering its operator.

### Proof boundary and remaining gaps

The first exercised network path is A→B→C over two distinct mutually authenticated TLS streams. It demonstrates direct-neighbor authentication, receiver-local admission at the relay and terminal, fresh terminal semantic resolution, a result receipt chain, and same-identity replay without a second operator call. It does not demonstrate arbitrary topology size, high availability, or full service lifecycle management.

The receipt chain is digest-linked, not digitally signed. TLS authenticates each immediate connection, and each hop records a local Hypervisor journal decision, but a SHA-256 receipt does not independently prove who created it to a third party. This is not non-repudiation, hardware attestation, or a cryptographic chain of relay signatures.

Each sender enforces a finite local monotonic RPC deadline, each route is hop-bounded, and payload/frame sizes are bounded. There is no globally comparable absolute deadline carried between machines; peer monotonic clocks must not be compared. A future protocol revision should introduce a carefully decremented remaining-work budget or hop-specific service budget if a strict end-to-end deadline is required.

This slice does not yet checkpoint the complete forwarding session across hard process death. The reliable channels and Hypervisor ledgers have checkpoint/replay facilities elsewhere in the system, but their forwarding-specific state is not yet captured and restored as one receiver transaction. The next recovery experiment should bind each hop's request/result channels, local Hypervisor replay state, operation channel identity, and receipt publication cut into the existing checkpoint/recovery machinery. A later trust extension may add relay signatures if receipts need independent verification beyond the directly authenticated peers.

Topology gossip, route-witness authority, and a second scheduling system are intentionally absent.


The hop-level Hypervisor event is classified in the NETWORK domain because its effect is a peer-to-peer transport operation. The terminal's nested semantic computation is separately resolved and arbitrated in the CPU domain by the existing Virtual Layer path; a network-forwarding grant does not substitute for the host process's compute capability.

The NETWORK-domain hop event governs the act of receiving/forwarding the transport request. The terminal computation is a nested, separate CPU-domain operation and still requires the selected local host process's compute right. The forwarding receipt does not collapse those authority planes.

The current server loop stops on an unhandled downstream failure while leaving the reliable request unacknowledged; it does not spin indefinitely on that same frame. A supervisor must decide whether and how to rebind the per-peer service. That restart path is not yet a forwarding-specific crash-recovery proof.

The original origin identity is carried through the path and used by the terminal semantic execution ledger, but this first version does not include an origin signature. Intermediate peers authenticate their immediate neighbors with mutual TLS; trust in the end-to-end origin claim is therefore transitive through those explicitly trusted relays.
