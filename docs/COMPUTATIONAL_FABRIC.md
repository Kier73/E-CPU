# Computational Fabric: Peer Discovery and Network Route Planning

## Purpose and design boundary

This specification connects semantic computational addresses to remote logical hosts without conflating a host with its physical placement or treating a network path as an execution engine.

The implemented fabric path has two distinct parts:

1. each peer owns a portable directory snapshot of its logical host/operator advertisements and outgoing directed links;
2. configured peers exchange those snapshots directly over mutual TLS and the existing reliable MailCPU channel abstraction;
3. each receiver admits snapshots only after checking transport identity, TLS DNS identity, monotonic revision, and a receiver-local lease;
4. `ComputationalFabricDirectory` exposes the active peer/host/link view and preserves revision/digest high-water state across restart without reviving remote leases;
5. `ComputationalFabricResolver` plans a bounded cost-feasible directed multi-hop route to an advertised logical host;
6. `ComputationalFabricForwardingClient` and `ComputationalFabricForwardingServer` carry the request one authenticated edge at a time. Each receiver revalidates its adjacent links and leases, reconstructs local NETWORK authority, and emits a typed hop receipt;
7. the terminal peer performs fresh receiver-local semantic resolution and invokes the Virtual Layer/Hypervisor CPU execution path.

The route witness remains non-authoritative. It is not an execution grant. The forwarding service composes the existing per-hop Hypervisor and reliable-channel boundaries; it does not replace them or create a global Hypervisor. Per-peer images can be quorum-anchored and rebound to fresh TLS streams, but this does not create a distributed atomic snapshot or make arbitrary external effects exactly-once.

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
| `TransitComputeSession`, `TransitComputeWorker`, `TransitBackendRouter` | one receiver execution path and exact operation/resource backend map | Reliable receive, receiver-side authority reconstruction, exact backend dispatch, effect/replay and result publication | Federated forwarding composes these receiver-local execution and replay boundaries without adding a second backend router |
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

The directory applies finite bounds to peers, host advertisements and links. The peer bound reserves one slot for the local peer even before its own snapshot is registered, and counts only live remote leases for the remaining slots. The configured trust map is an allowlist and may be larger than the number of peers permitted to be active concurrently; an authenticated peer is still refused when the live topology is at capacity. `ComputationalFabricAuthority.from_snapshot()` can restore a peer's portable advertisement revision, host records and outgoing links. That restores directory metadata only: the peer must rebind/re-register its local executable runtimes and handlers; no PID or callable is recovered from the snapshot.

`ComputationalFabricDirectory.checkpoint()` exports the trust map, local policy limits, and every peer's revision/digest high-water mark, including marks retained after lease expiry. `from_checkpoint()` verifies the canonical checkpoint digest and restores those rollback guards, but deliberately restores **no remote snapshots and no monotonic lease deadlines**. The local peer must re-register its current snapshot; each remote peer must be contacted directly over mutual TLS to obtain a new active lease. A restored lower revision is rejected, and a same-revision content change remains equivocation. This avoids comparing monotonic timestamps across process or machine lifetimes.

The checkpoint digest detects accidental or partial content modification; it is not an authentication signature and can be recomputed by an actor able to rewrite the checkpoint. The bare checkpoint API does not itself persist bytes or establish a quorum commitment.

`ComputationalFabricRecoveryStore` closes that gap using the existing `RecoveryLineageCoordinator` without overloading the requester/receiver Transit bundle. It writes a canonical `directory-state artifact file` artifact and a typed `RecoveryStateManifest` into an immutable generation directory, fsyncs the files and directory, then seals the manifest root through the configured strict-majority quorum. Restore reads the quorum high-water first, checks the artifact digest and canonical manifest, requires an exact match to the current generation, and only then reconstructs the directory. A locally durable but unanchored artifact, modified artifact, or older generation is refused. The recovered directory retains peer revision anti-rollback marks and trust policy, but still has no active remote snapshots or leases until fresh direct mutual-TLS observations are accepted.

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

### Restart-aware discovery and lease refresh

`ComputationalFabricDiscoveryService` manages direct peer refresh for a local
directory. Its bootstrap inputs are the configured direct peer endpoints,
the local mutual-TLS client context, RPC timeout, and refresh cadence.

- `refresh_peer(peer_id)` reuses a healthy authenticated client or creates a
  fresh TLS client, obtains the peer's current revisioned snapshot, and merges
  it only through the directory's authenticated-transport validation.
- `refresh_all()` refreshes configured peers in stable peer-ID order, then
  purges leases that have expired according to this receiver's monotonic clock.
- `serve_forever(stop_event)` repeats the refresh cycle at the configured
  cadence. Failed streams are closed and discarded; a later cycle makes a
  fresh authenticated connection.
- An unchanged snapshot can still renew the receiver-local lease. A failed
  refresh does not erase a still-live last-known observation; it remains
  usable only until its local lease expires.
- `bootstrap_snapshot()` persists endpoint and cadence configuration, not
  TLS streams, certificates/private keys, active snapshots, or lease deadlines.
  The separately quorum-anchored directory checkpoint preserves revision/digest
  high-water marks. After restore, all remote leases begin inactive and the
  discovery service must authenticate each peer again.

The service therefore preserves the distinction between durable trust/rollback
memory and ephemeral authenticated observations. It discovers configured
direct peers only; it does not treat relayed topology claims as direct TLS
observations.

On the peer-owning side, `ComputationalFabricPeerListener` owns a listening
socket and repeatedly accepts mutual-TLS sessions for one configured direct
client identity. Each accepted stream receives a fresh
`ComputationalFabricPeerServer` and fresh reliable directory channels. When a
client disconnects or a session fails, the listener closes that session and
returns to accept; a replacement client must complete a new TLS handshake and
DNS identity check. The listener is a per-process service loop, not a process
supervisor: the deployment/service owner remains responsible for restarting
the listener process and re-registering its current local authority snapshot.

### Supervised peer-process lifecycle

The `ComputationalFabricAuthorityStore` persists a peer's portable advertisement snapshot by atomic replacement and file/directory sync where supported. A `ComputationalFabricAuthority` opened through the store writes each successful host/link mutation before returning the new revision. If the durable write fails, the in-memory mutation and revision are rolled back. The store digest detects accidental modification; it is not a signature, a peer identity proof, or an anti-rollback anchor. The store therefore belongs in protected local storage, with stronger generation anchoring supplied by the existing recovery-lineage path when required.

A peer process can be launched with `python -m mailcpu.computational_fabric_service` (or the `mailcpu-computational-fabric-peer` entry point). It loads the stored authority snapshot, checks the configured peer identity, and constructs its mutual-TLS listener. Its `--listen-port` is the direct discovery/control socket and is deliberately independent of the forwarding host/port in the durable peer snapshot. Readiness reports both endpoints only after the control listener is bound; the record is bound to the child PID and to a one-use startup token supplied by its parent.

`SubprocessServiceSupervisor` owns the operating-system child process. It validates the readiness schema, service name, startup token, and PID; monitors exit; and applies `RestartPolicy.NEVER`, `ON_FAILURE`, or `ALWAYS` under a finite `max_restarts` budget. Explicit stop clears desired state and suppresses restart. A hard process death leaves desired state intact, so `reconcile()` can start a replacement and require a new readiness proof.

The replacement process loads the same durable authority revision and opens a new control listener. The remote `ComputationalFabricDiscoveryService` must establish a new mutual-TLS session and obtain that snapshot before renewing its receiver-local lease. The observed snapshot may be byte-for-byte unchanged (`changed=False`) while the lease is renewed. Routes are never revived from persisted sockets or old monotonic deadlines.

The executable process-recovery tests now cover more than endpoint independence. The discovery-sidecar experiment hard-kills B's A-facing control-plane process while the A→B and B→C data-plane streams remain live; A sends a first workload while B's lease remains valid, expires the lease, confirms route refusal, restarts the sidecar under the parent supervisor, rediscovers B over fresh mutual TLS, then sends a distinct operation and an exact semantic replay over the same data-plane stream. Separate subprocess tests hard-kill relay B at named transaction cuts and restore it from its quorum-anchored checkpoint with new PID/TLS streams, and hard-kill terminal C while relay B survives, then restore C and continue with a new operation. A combined test kills B and then C in sequence while preserving one semantic operation history. These establish selected control/data-plane continuity and per-process recovery paths, not every possible node-loss ordering or parent-supervisor recovery. Each current listener process is configured for one direct client identity; a multi-identity acceptor and general topology federation remain follow-on work. The parent supervisor itself is not yet self-supervised: deployment still needs an operating-system service manager or equivalent outer watchdog to restart the parent after its own failure. Local runtime bindings and executable capabilities remain owned by the host runtime and must be reconstructed separately; the portable authority snapshot does not recreate them.

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

The directory and resolver remain the discovery/planning layer: they do not recursively discover neighbours, grant execution rights, or call a remote operator. The origin still needs directly authenticated snapshots for the peers in its topology view, including intermediate and destination peers. A separate forwarding layer now carries the planned workload one authenticated directed edge at a time; every relay independently admits the NETWORK operation, and the terminal performs fresh local semantic resolution and Virtual Layer/Hypervisor execution. The route witness itself remains non-authoritative throughout.

The first forwarding execution pipeline now adds a separately admitted operation at every hop. At the destination it:
1. receives a typed workload over the existing reliable operation channel;
2. resolves the address against a local `ComputationalHostCatalogue` and current HeadlessOS state;
3. verifies exact local host/runtime implementation and pinned Structural Memory state;
4. invokes `ComputationalExecutionAdmissionCoordinator`;
5. allows Virtual Layer capability reconstruction and Hypervisor policy/effect/replay to decide the operation;
6. returns evidence and receipts correlated with the original semantic request.

Forwarding has explicit peer-local authority, source/destination binding, sequence/replay identity, hop decrement, payload/frame bounds, route freshness, and digest-linked per-hop receipts. An intermediate router does not convert a remote route witness into rights. The receipt tree is content-linked but not digitally signed: immediate neighbors authenticate one another with mutual TLS, while origin trust remains transitive through configured relays.

## 7. Testable milestones

**Demonstrated by this slice:** portable host advertisement strips receiver authority; peer snapshots enforce ownership; direct peer identity and DNS trust are checked; revisions cannot roll back or equivocate within a directory process or across its checkpoint reconstruction; restored remote peers have no live lease until directly re-authenticated; expired snapshots do not consume live directory capacity; route search follows directed links, respects cost/hop/frame limits, selects deterministically, preserves short feasible alternatives, and round-trips its non-authoritative route receipt; a live three-peer test directly discovers B and C over distinct mutual-TLS identities, resolves A→B→C, expires the lower-cost destination's receiver-local lease, fails over to a compatible but more expensive host on B, then re-observes C over its authenticated channel and returns to the lower-cost A→B→C route; a single-artifact directory checkpoint is persisted and sealed through the existing strict-majority RecoveryLineage coordinator, and restore rejects modified, stale, and unanchored generations without reviving remote leases; a second integration test carries the discovered host identity through a fresh destination-local semantic resolution and Hypervisor execution, without treating the fabric witness as authority.

**Next:** extend the supervised one-client peer process into a multi-identity listener and authenticated multi-peer topology federation without treating relayed claims as direct observations; add endpoint revision/rotation and parent-supervisor recovery; calibrate route estimates from measured path/service telemetry; continue exercising peer loss, forwarding retries, intermediate crash, destination crash and end-to-end recovery. Hop-by-hop forwarding, per-peer channel recovery, process restart, and direct-lease reacquisition now have executable specifications and tests.


The NETWORK-domain hop event governs receiving and forwarding the transport request. Before local capability derivation, `ComputationalFabricForwardingServer` decodes the complete envelope and derives a compact, bounded intent projection from the operation identity, route/cursor, destination, Ground/Program, operator contract, workload/input digests and payload byte extent. A supplied projection must exactly match this receiver-derived value; older callers without one are upgraded locally. The full envelope remains in the event payload and its replay fingerprint, and the handler receives the full decoded value. Thus a large VGI state bundle is not interpreted as thousands of intent tokens at each relay, but its complete digest and bytes remain bound to the network operation. The terminal computation is a nested, separate CPU-domain operation with its own independently recomputed Virtual Layer intent projection, and still requires the selected local host process's compute right. The two projections do not collapse the NETWORK and CPU authority planes.

The current per-connection peer server services one authenticated stream at a time. The discovery client can discard and recreate its outbound stream. A peer listener can accept a new stream after the prior authenticated session closes; independent listener supervision and parent-supervisor recovery remain explicit service-lifecycle concerns.

The original origin identity and semantic operation sequence are carried through the path and used by receiver-side replay ledgers, but this version does not include an origin signature. Intermediate peers authenticate their immediate neighbors with mutual TLS; trust in the end-to-end origin claim is therefore transitive through those explicitly trusted relays.

## 8. Per-peer forwarding recovery

The detailed per-peer checkpoint schema, capture-cut state table, sender/receiver recovery ordering, and proof boundaries are specified in [COMPUTATIONAL_FABRIC_FORWARDING_RECOVERY.md](COMPUTATIONAL_FABRIC_FORWARDING_RECOVERY.md).

`ComputationalFabricForwardingServer.snapshot()` captures one peer's local operational state under a service transition lock. The image contains:
- the complete receiver-local `HeadlessOS` snapshot, including Hypervisor decisions, committed effects, replay identities and the event journal;
- the inbound reliable request channel, including its receive cursor and delivered-frame history. At a pre-ACK cut, the unacknowledged request payload remains in the previous peer's outbound sender checkpoint until that peer observes the ACK;
- the outbound `HypervisorOperationResultChannel`, including its reliable pending response frames and semantic result ledger;
- each downstream `ComputationalFabricForwardingClient` request and response channel pair, including the downstream semantic-result `seen` ledger;
- the operation's origin identity, peer adjacency identity, authority PID, and bounded service settings.

The snapshot is local to one peer. It does not serialize TLS sockets, active remote snapshots/leases, local runtime callables, or portable capability grants. After restart, the caller must load the checkpoint, restore the local `HeadlessOS`, rebuild any terminal catalogue/runtime binding against that restored OS, reconnect every adjacent peer using mutual TLS, and supply a freshly observed `ComputationalFabricDirectory`. `ComputationalFabricForwardingServer.from_snapshot()` rejects a downstream transport map whose peer keys differ from the captured client set. The normal constructor rechecks the authenticated previous peer, configured certificate DNS name, and active directory lease before the reliable channel snapshots are rebound.

`ComputationalFabricForwardingRecoveryStore` writes a canonical peer image and `RecoveryStateManifest` into an immutable generation directory, fsyncs both files and the directory where supported, then anchors the exact image digest through the existing strict-majority `RecoveryLineageCoordinator`. A modified image, an unanchored generation, or a valid but older generation is refused. The capture-cut names correspond to the existing operation-channel order:
- `before_execution`: authority has been reconstructed and the inbound request remains unacknowledged; the handler has not started;
- `after_execution_commit`: the local Hypervisor effect/replay entry is committed, but the response has not yet been published and the inbound request remains unacknowledged;
- `after_response_publish`: the response is in the outbound reliable queue, while the inbound request is still unacknowledged;
- `after_request_ack`: the inbound request is consumed/acknowledged, while the response remains available for reliable retransmission until its own ACK;
- `idle`: the service is between operations.

The transition lock makes each local capture internally consistent with respect to `serve_once` and downstream `forward` calls. The fault hook can capture these cuts on the serving thread; the lock is re-entrant for that purpose. This is **not a distributed atomic snapshot**: the upstream requester, this peer, and its downstream peer each own independent channel and recovery state. A multi-hop recovery sequence must restore peers from their own quorum-anchored images and reconcile the same immutable semantic operation identity through the existing replay ledgers. It must not infer a global commit from one peer's checkpoint.

The in-process A→B→C integration executes over mutual TLS, captures the requester plus B and C state, tears down the original streams, restores both receiver services and the requester over fresh mutual-TLS streams, and replays the same semantic operation identity. The receipt is unchanged and the terminal operator is not invoked a second time. Separate subprocess experiments now complement this in-process proof with hard kills of relay B and terminal C at named cuts, fresh process identities and TLS connections, quorum-sealed checkpoint restoration, replay of the original operation, and continuation with a distinct new operation. The process tests verify the exact owner of the terminal CPU effect rather than treating the intermediate NETWORK authorization as duplicate computation. These are selected deterministic recovery proofs, not a global atomic snapshot or a guarantee for arbitrary external side effects; such effects still require a durable journal or idempotency contract at their actual owner.
