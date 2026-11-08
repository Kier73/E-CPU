# Communication Host Model

## Normative definition

A **host** is an identifiable **observer**: a logical operational locus that can receive or inspect information, distinguish or measure some property of it, or change information through observation and interaction. In this architecture, *host* and *observer* name the same underlying kind of locus. An observer is therefore not limited to a human viewpoint, an external analyst, or a passive monitoring tool; it is a possible operational construct in the system.

A host is not necessarily a physical machine, server, CPU, process, operating system, or persistent object. Observation is the minimum host relation. Execution, transformation, routing, persistence, verification, coordination, and authority are additional capabilities that may be composed with it; they are not prerequisites for being an observer-host. Each host performs only the operations declared by its own contract and admitted by the relevant local policy.

Let a logical host be:

\[
H=(I,C,S,T,K,L)
\]

where I is stable logical identity; C is communication interfaces and adjacency; S is operational state (possibly empty for a stateless observer or transform); T is the defined observation and/or information-transition relation; K is the set of capabilities available and permitted; and L is operational lineage, including continuity, revision, provenance, and recovery identity.

An observational contract can be represented as:

\[
\mathsf{O}_H:(X,S_H)\rightarrow(Y,S'_H,X',E)
\]

where X is the information made available to the observer, Y is its bounded observation or result, S_H and S'_H are the host's state before and after observation, X' is the observed information after any interaction, and E is the evidence or receipt exposed by the contract. A read-only observation may leave both states unchanged; an active observation may update the observer, the observed information, or both. The contract must say which case applies.

The distinction between S and T matters. A stateless observer can be a host because it has a defined observation relation. A stateful object is not automatically a host if no information operation is defined.

## Substrate, host, and path

A **substrate** is the medium and connectivity through which information can move. A **host** is an operational locus with a defined information contract. A **path** is an ordered or constrained relation among substrate edges and host loci.

A passive communication link that only carries signals is normally a substrate edge, not a host. A link, port, or path segment that observes its traffic or condition—by sampling, measuring, decoding, admitting, queueing, acknowledging, filtering, or otherwise interacting with information—is an observer-host for that operation. It need not execute a general-purpose program. Thus a path can contain observer-hosts as well as passive edges, and an active path segment can itself host computation when its observation contract is composed with a declared transition.

## Roles are composable capabilities

Roles are not mutually exclusive kinds:

| Role | Operation | Example |
|---|---|---|
| Sensor / transducer | Convert a measured phenomenon to information | Sensor interface, decoder |
| Observer-host | Sample, distinguish, compare, measure, or publish a bounded view; optionally interact with the observed state | Monitor, trace reader, receiver, timing probe |
| Transit | Queue, route, filter, schedule, or reshape information | Mailbox, active router |
| Execution | Apply a bounded transition | CPU worker, SIMT interpreter |
| Memory | Retain and resolve by identity or coordinate | Page store, Structural Memory |
| Verification | Compare effects with an oracle or contract | Result verifier |
| Authority | Admit, deny, or commit under policy | Hypervisor, recovery authority |
| Coordination | Compose transitions across loci | DAG coordinator |

Observation is the minimum host role; the remaining roles are composable capabilities. One host can expose many roles. Several hosts can cooperate as one composite service. A host may create or contain subordinate logical hosts without requiring physical containment. A queue can observe, retain, and transit; a worker can execute and verify. A pure observer-host is not thereby granted execution, storage, forwarding, or authority capabilities.

## Identity is not placement

Let \(\pi_t(H)\) be the set of physical or virtual resources realizing logical host H at time t. A change in realization,

\[
\pi_{t_1}(H)\ne\pi_{t_2}(H),
\]

does not by itself imply a change in logical identity. A service may migrate or restart while preserving identity if its state and lineage continuity obligations are met.

Keep these coordinates separate:

- **Logical host identity:** which operational locus is addressed.
- **Placement node:** physical or virtual infrastructure currently realizing one or more logical hosts.
- **Failure domain:** boundary within which failures may be correlated.
- **Resource:** CPU, memory, storage, connection, or accelerator capacity consumed.
- **Authority:** capabilities and policy required for an operation.

Two processes on one machine are not automatically independent failure domains. Two distinct network names do not prove distinct machines.

### Recovery topology schema-v1 compatibility

The merged recovery deployment schema uses a JSON field named host_id. In schema v1 only, this field has the narrower historical meaning of a declared infrastructure placement-node identifier for a recovery member. It is not the general host abstraction in this document. The field remains unchanged to preserve existing snapshots and canonical digests; a future schema version should rename it placement_node_id.

## Host qualification is not authority qualification

Every authority is a host, but not every host is an authority. An authority needs protocol-specific qualifications: declared authority identity, authenticated relationships, durable decision/vote state, membership position, and the ability to preserve valid decisions under a specified failure model. A sensor, compute worker, queue, or path router does not acquire authority merely by being addressable.

Route selection and permission are also separate. A route witness identifies an available operational path; it cannot grant a capability or bypass receiver-side policy.

## Navigable operational structures

A navigable structure is a finite or bounded relation of host loci connected by permitted transitions. A request resolves against a goal, required capability, information representation, available context, and resource budget.

\[
Q \rightarrow H_{\text{dispatch}}
\rightarrow H_{\text{capability}}
\rightarrow H_{\text{verification}}
\rightarrow R
\]

The selected path is a witness naming the loci traversed and the transitions used. Resolution should be deterministic for equal evidence and costs, and must fail closed when no eligible path exists.

E-CPU can therefore treat a query as navigation through described computation. The query reaches a host that owns the required transition, passes through its execution relation, then returns through an evidence-bearing result path. It need not instantiate an entire CPU, GPU, or memory system for each query.

## E-GPU application

The E-GPU is a composite logical host containing dispatch, execution-method, reduction, and verification loci. The existing bounded SIMT interpreter supplies the lane execution primitive. The E-GPU adds method identity and graph navigation around it. A tree-reduction method follows a separate reduction locus rather than pretending shared-memory reduction already exists inside SIMT.

See EGPU_NAVIGABLE_FABRIC.md for the executable reference structure.

## Design consequences and proof boundary

New subsystems should expose logical identity, transitions, capabilities, and lineage independently of placement. Active paths may host computation when they have operational state and a transition contract. Composite hosts should expose bounded sub-loci and return route witnesses. Physical migration requires continuity evidence; fault-domain claims require placement evidence.

This model defines vocabulary and a design contract. Any documented observer is a possible observer-host construct; that statement is a classification rule, not a claim that every sensor, path element, remote process, or machine is already instantiated, reachable, trusted, or authorized as a live MailCPU host. A concrete observer-host must still establish its identity, observation contract, resource bounds, and any required state/lineage. The first E-GPU implementation proves a bounded local example of composable loci and deterministic capability navigation. Physical GPU execution, arbitrary path-host execution, general migration, and distributed identity continuity remain later targets.


## Executable observer receipts and contextual orbit addressing

The common runtime observer contract is implemented by mailcpu.observer_orbit.ObserverContract and ObserverReceipt. It reuses the repository's content-addressed RepresentationRef, versioned ObservationContract, typed TemporalFrame, and evidence references. Receipt digests bind content and provenance; they are not remote signatures, peer authentication, or capability grants.

ObserverComposition aggregates a complete declared set of observer receipts while preserving each member's distinct projection. It does not infer consensus or equivalence.

ContextualOrbitAddress pins a SystemIdentity, base VirtualGroundRef, Computational Ground, typed absolute scheduler coordinate, and an exact admitted VirtualStructuralMemoryRef. ContextualOrbitNavigator resolves the pinned law and directly evaluates its relative coordinate to create a symbolic Virtual Ground projection. The projection is deliberately not represented as a complete machine snapshot. Direct-navigation failures refuse; they do not trigger an invisible BFS or replay fallback.

See [OBSERVER_ORBIT_CONTRACT.md](OBSERVER_ORBIT_CONTRACT.md) for the formal address, context binding, complexity boundaries, evidence model, and non-goals.


## Structural information and interpreted structure

A composed virtual state keeps the byte/field description distinct from the meaning assigned to it. Structural information identifies layouts, fields, bytes, component references, generator revisions and content digests. Interpreted structure identifies the Computational Ground, state schema, field meaning, scalar encoding, invariants and permitted transitions.

`ComposedVirtualGroundAddress` binds these views through content-addressed component representations and the exact template/schema context. Each component can be generated by a different admitted Structural Memory law at one shared typed scheduler coordinate. The resulting projection preserves per-component read receipts and a composed state digest. It is a state-shaped virtual projection, not a full operating-system checkpoint unless the state owner separately establishes complete subsystem coverage and validates restoration.

General path inversion has an equally important boundary: a `ProcessPathIndex` indexes a supplied, validated declarative transition path. It can locate states already on that path without expanding alternatives, but it is not evidence that a physical host executed the path. Actual execution and recovery evidence remain owned by the corresponding host.
