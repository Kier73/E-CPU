# SAB-001 — Substrate-adaptive observer-host bootstrap

**Status:** bounded experimental implementation. **Not** an autonomous Internet-discovery agent, bare-metal chip, external host rental scheme, or proof that latency/passive links execute code.

## Question

Can one semantic intention survive a change in available infrastructure by constructing a virtual computational environment **from sensed capabilities and admitted information transitions**, rather than from preselected CPU/port/server types?

This extends the E-CPU [Communication Host Model](COMMUNICATION_HOST_MODEL.md), `OwnedNetworkFabric`, `ComputationalHostCatalogue`, `ComputationalAddressResolver`, and the conceptual Computational Ground. It does *not* replace those authority/execution mechanisms. A real production integration would translate its local candidate contracts into native Virtual Layer / computational-fabric admissions and use receiver-side Hypervisor policy.

## The bootstrap mapping

Given a finite observed infrastructure inventory

\[
\mathcal O_t=(R_t,L_t,E_t),
\]

where `R` are observed resource loci, `L` are observed information pathways, and `E` is probe provenance with validity ranges, construct an *admitted* virtual graph

\[
V_t = \operatorname{Compile}(\mathcal O_t, K_{\text{receiver}}, B_{\text{local}}).
\]

`K_receiver` is a receiver-owned allowlist; `B_local` is locally bound execution and transport code. A resource advertisement and a SHA-256 evidence digest alone cannot extend either authority or physically available capacity. The compiler projects a node for each observed resource and an edge only for an operation with a matching local binding and permission or a transport channel with a locally bound delivery mechanism. Passive media normally contribute transport edges, **not** executable transitions. Port electronics are execution loci only when actual observable functions are exposed and admitted.

For an intention

\[
I=(G,\text{source},\text{input description},\text{target observation},\text{budget})
\]

find the lowest declared-cost path over states `(resource, representation)`. At each step choose either (a) a typed, locally admitted transformation at a locus or (b) an observed directed channel carrying the unchanged typed representation. The algorithm is Dijkstra with bounded path length and deterministic tie ordering; no trust is inferred from the resource's descriptive label.

Only the finite request coordinates are realized. A locally registered mathematical navigator may jump to an arbitrary coordinate if its own Ground permits it. Path planning **does not perform** the desired computation, and a route witness never grants authority.

### Observable substrate families

| Sensed resource | Potential observation | Permitted virtual role *after local binding* | Incorrect inference explicitly rejected |
|---|---|---|---|
| On-chip port / queue | frames, clock/occupancy, state changes | observer, carrier; sometimes admitted simple transform | passive I/O makes a new processor |
| CPU/process/memory | explicit local operator/driver + Ground | interpreter, navigator, verifier, memory | advertised CPU means authorization |
| Optical/electrical link | attenuation, carrier status, arrival, timestamp | carrier; tapped active observer | uninstrumented fiber performs arbitrary arithmetic |
| DNS / protocol exchange | declared resolver results, timestamps or behavior | observational input, bounded measurement | querying public infrastructure grants external execution rights |
| Communication latency | observed delay under declared clock and sampling conditions | temporal observation or lawful time-state representation | delay is durable storage with arbitrary read/write semantics |

A subject can expose multiple roles; a single physical device can produce many logical observer-host projections. Their failure and throughput domains are **not** independent simply because the names differ.

## Test implementation

- `mailcpu/substrate_bootstrap.py` implements typed observation, lease, offer, channel, local implementation, receiver policy, task, plan, receipt chain, and bounded verification types. It uses the standard library except for the **optional real E-CPU OwnedNetworkFabric adapter**.
- `owned_network_probe` senses real `OwnedNetworkFabric.interfaces`, `find_route`, and `route_mtu`. It does not synthesize a processing offer. The caller must explicitly supply offered operations, which remain unusable without receiver bindings.
- `owned_network_carriers` commits actual E-CPU `send_routed` / `receive` transitions rather than assuming bytes teleport. This is an internal software network; it is not an attached fiber or an actual bare-metal port.
- `tests/test_substrate_bootstrap.py` exercises cost selection; rebinding from fast to slow infrastructure; resource-name irrelevance; missing or expired lease; absent authority; unauthenticated advertisement; channel corruption; byte and step budgets; independent receiver-owned checks; receipt-chain mutation; and a real E-CPU network and direct algebraic navigation to a coordinate above `10^12`.

### What counts as verification

A receiver-controlled `oracle` can check a numeric transition independently of its implementation before the result is admitted. `require_oracle` rejects a plan that cannot include such a check. The report separately records the checked stages. A canonical digest verifies byte identity and internal continuity; **it does not authenticate the host, prove an oracle independent, guarantee exact semantics for all inputs, or attest physical execution**. Source policy is local and static in this prototype; dynamic distributed authority is an open integration.

### Reconfiguration / continuity

For an initially selected inexpensive path `start -> fast -> checker`, removing `fast` and its channels from the next observed inventory causes a new plan `start -> slow -> checker`. The semantic request and Ground digest stay unchanged, while the route witness and inventory digest change. The independently checked result remains equal. A stale plan bound to the former inventory refuses execution.

This is **replanning after observation**, not recovery of an interrupted active network transaction. Runtime mutable state and message retries are not checkpointed by SAB-001. E-CPU's recovery lineage and checkpoint facilities should be used at the next stage.

### Scope and falsifiers

The prototype would fail its claim if it fabricated operators on passive links, inferred physical parallelism from multiple virtual names, continued using expired or unreachable resources, allowed observed advertisements to install new code, accepted a changed result as if the same bytes had been delivered, ignored local policy, or changed the mathematical result when the substrate layout changed while the admitted operation semantics remained equivalent.

It does **not** demonstrate real-time automatic discovery of arbitrary Internet infrastructure, uninvited use of remote hosts, unbounded complex actions, general program synthesis, external resource optimization, low-power chip implementation, or machine-checkable proofs of arbitrary transitions. Physical port count, capacity, energy, and latency must be measured separately. The result is a grounded *virtual environment compiler* over an explicit set of observations, not the claim that any arbitrary physical medium can be made computational.

## Next frontier: SAB-002

Construct actual sensor adapters (chip MMIO/loopback interface, local socket/host telemetry, authorized DNS timing), feeding typed evidence with clock domains and calibration; integrate proposals into native `ComputationalHostCatalogue` and `ComputationalExecutionAdmissionCoordinator`, then use E-CPU's existing recovery-lineage paths for dynamic discovery, admission and failover. Preserve the critical relation:

\[
\text{what is observed}\ne\text{what is authorized}\ne\text{what can physically realize a state transition}.
\]

The most revealing measurement would compare a **single interpreter** running the entire bootstrapped logical network to **active observation circuitry** or a permitted remote operator, separating interpretation, transport, admitted navigation, and verification costs. No speedup follows from graph expressiveness alone.