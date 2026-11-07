# Communication Host Model

## Normative definition

A **host** is an identifiable operational locus in a communication substrate at which information can be received, observed, transformed, retained, routed, or emitted under a defined capability and transition relation.

A host is not necessarily a physical machine, server, CPU, process, operating system, or persistent object. It is defined by an identifiable operation contract and the state or lineage that gives that operation continuity.

Let a logical host be:

\[
H=(I,C,S,T,K,L)
\]

where I is stable logical identity; C is communication interfaces and adjacency; S is operational state (possibly empty for a stateless transform); T is the defined transition relation; K is the set of capabilities available and permitted; and L is operational lineage, including continuity, revision, provenance, and recovery identity.

The distinction between S and T matters. A stateless transducer can be a host because it has a defined transition. A stateful object is not automatically a host if no information operation is defined.

## Substrate, host, and path

A **substrate** is the medium and connectivity through which information can move. A **host** is an operational locus with a defined information contract. A **path** is an ordered or constrained relation among substrate edges and host loci.

A passive communication link is normally a substrate edge, not a host. A path segment becomes a host when it carries an operational capability of its own: a queue with admission/dequeue transitions, a router with policy and forwarding state, a filter with a defined transformation, or a scheduler with a stateful selection relation. Thus paths can contain hosts, and active path segments can themselves host operations.

## Roles are composable capabilities

Roles are not mutually exclusive kinds:

| Role | Operation | Example |
|---|---|---|
| Sensor / transducer | Convert a measured phenomenon to information | Sensor interface, decoder |
| Observer | Sample, compare, or publish a view | Monitor, trace reader |
| Transit | Queue, route, filter, schedule, or reshape information | Mailbox, active router |
| Execution | Apply a bounded transition | CPU worker, SIMT interpreter |
| Memory | Retain and resolve by identity or coordinate | Page store, Structural Memory |
| Verification | Compare effects with an oracle or contract | Result verifier |
| Authority | Admit, deny, or commit under policy | Hypervisor, recovery authority |
| Coordination | Compose transitions across loci | DAG coordinator |

One host can expose many roles. Several hosts can cooperate as one composite service. A host may create or contain subordinate logical hosts without requiring physical containment. A queue can be memory and transit; a worker can execute and verify.

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

This model defines vocabulary and a design contract. It does not claim every sensor, path, observer, remote process, or machine is already a live MailCPU host. The first E-GPU implementation proves a bounded local example of composable loci and deterministic capability navigation. Physical GPU execution, arbitrary path-host execution, general migration, and distributed identity continuity remain later targets.
