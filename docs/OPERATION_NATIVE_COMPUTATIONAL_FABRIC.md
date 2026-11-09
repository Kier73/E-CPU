# Operation-Native Computational Fabric

## Purpose

This specification composes the bounded MailCPU dataflow compiler with the existing Virtual Layer, Computational Address Resolver, authenticated Computational Fabric, and E-GPU method graph.

The computational object distributed by this profile is not a VM image or a complete process. It is a semantic operation over an explicitly described set of inputs. The algorithm remains a dependency graph. The fabric locates a receiver that advertises a compatible local implementation, and the receiver revalidates and executes the operation under its own Ground and Hypervisor authority.

The initial implementation is deliberately bounded: ready ADD nodes in one dataflow frontier are grouped into one integer vector-add operation. Other admitted instructions (SET, COPY, COMPARE, HALT) are evaluated by the local DAG coordinator. The same versioned operator contract has both a CPU realization and an E-GPU realization.

## The topologies are separate objects

Let the communication topology be:

\[
\mathcal F=(H,E)
\]

where H is the set of logical computational hosts and E is the set of directed, admitted communication paths between their owning peers.

Let the algorithm's computational topology be:

\[
\mathcal D=(O,\prec)
\]

where O is the set of semantic operations and \prec is the dependency relation. For an acyclic dataflow plan, \mathcal D is a DAG. A stateful process with loops must be represented by bounded repeated transitions or by a separate session/machine profile; this compiler does not silently turn cycles into DAG nodes.

Each host may itself have an internal operational topology:

\[
\mathcal L_h=(V_h,E_h)
\]

For example, E-GPU has dispatch, SIMT execution, reduction or workgroup methods, and result verification. That internal graph is independent of both the application's operation DAG and the peer communication graph.

A placement is a partial mapping:

\[
\pi: O \rightarrow H
\]

and a communication route maps the selected host to a path through the peer graph:

\[
\rho: \pi(o) \rightarrow (h_0,h_1,\ldots,h_n)
\]

The combined execution description is therefore not one flattened graph. It is a relation among \mathcal D, \mathcal F, each participating \mathcal L_h, the semantic Ground, and the selected placement/route evidence.

The dependency graph says what must happen before what. The communication topology says where information can travel. The host's internal topology says how a selected implementation realizes its local operation.

## Semantic operation contract

An operation is addressed by its declared Virtual Layer contract, not by sending executable handler code:

\[
Q_o=(I_o,G,T_o,X_o,C_o,B_o,\Omega_o)
\]

where I is the operation/workload identity; G is the Computational Ground fingerprint; T is the versioned operator contract; X is the bounded input or content-addressed input references; C is the exact program/frontier context; B is the hard resource budget; and Ω is the declared output observation.

The remote host advertises portable operator metadata, Ground compatibility, substrate, implementation fingerprint and bounded resource costs. It does not advertise a PID or executable handler. Those remain local.

The receiver independently checks the exact operator contract, local System Ground, selected implementation fingerprint, local runtime/handler binding, current host catalogue and process capability. A remote route witness is a proposal, not execution authority. Only the receiving host's fresh resolution and Hypervisor admission authorize the local transition.

Different realizations may share one semantic operator contract. The CPU implementation and E-GPU implementation of mailcpu.dataflow.add_frontier have the same operator contract digest but different implementation fingerprints. A realization is acceptable only when it preserves the declared observation:

\[
\operatorname{Obs}(I_h(Q_o))=
\operatorname{Obs}(T_o(X_o))
\]

The first implementation uses strict integer addition and returns the ordered values vector. This contract is deliberately narrow and does not imply that arbitrary CPU, GPU, signal or programmable-network implementations are interchangeable.

## Operation context and state-space navigation

The portable object is the semantic operation contract; its meaning is instantiated by a particular Ground, input and observation context. A simple ADD law can be written independently of any one machine:

[
o(a,b)=a+b
]

But an execution is not identified by that law alone. It also requires the concrete operand sources, the Ground that defines their interpretation, the state/Virtual Ground coordinate, any pinned Structural Memory references, resource limits, and the terminal observation expected by the caller.

This matches the state-space view. For a Ground (G), let (Omega_G) be the state-space admitted by that Ground and let (T_G) be its transition relation. A trajectory is:

[
	au_G(s_0)=(s_0,T_G(s_0),T_G^2(s_0),ldots)
]

A desired output can be expressed as an observation predicate (P). A navigation problem is to find a coordinate or representation (q) such that:

[
P(operatorname{Obs}_G(S_G(q),x))=mathrm{true}
]

where (S_G(q)) is the state represented at coordinate (q) and (x) is the input. Structural Memory can support direct coordinate resolution when an admitted generator and certificate define that mapping. If the Ground only provides transitions, finding the first matching point may still require bounded iteration, indexing, or a separately justified navigation algorithm.

E-CPU's current integration accepts a supplied, revision-pinned coordinate and asks a host capable of resolving it to instantiate the operation. It does **not** yet infer an arbitrary coordinate, search every possible state-space, or jump to an unknown desired output. The “speed of interpretation” hypothesis is that a suitable certified description and local representation can avoid reconstructing an entire state trajectory when only one state or projection is needed. It is not a claim that physical execution or communication latency disappears.

A state-space coordinate is logical time/state position, not wall-clock time. The same operation can be realized by different physical hosts at different placements while preserving one semantic contract and observation.

## Frontier dispatch and commit

The compiled MailCPU plan supplies immutable ComputationNode identities and deterministic ready frontiers F_0,...,F_k. For a frontier F_i, every node is ready only after its dependencies have committed.

The operation-native executor:

1. Reads the exact operands from immutable initial values or already committed predecessor results. A symbolic Structural Memory operand remains an address at this point; it is not eagerly read by the compiler or coordinator.
2. Selects the ADD nodes in the ready frontier and orders them by stable node_id.
3. Constructs one DataflowAddFrontierRequest binding the plan digest, context digest, frontier index, node digests, destination registers and ordered operand pairs.
4. Builds one pure VirtualLayerWorkload for the vector-add contract. Inline values travel as values; symbolic references travel as schema-v2 Virtual Layer addresses containing the memory identity, exact revision, context, coordinate, specification digest and certificate digest. Only the operation inputs and frontier description are sent; the full VM image, complete MailCPU program and unrelated register state are not shipped.
5. Uses ComputationalFabricResolver to select an advertised host and directed peer route.
6. Sends the operation through the existing authenticated per-hop forwarding protocol. Relay peers apply their local forwarding policy; the terminal peer re-resolves the workload and executes its local operator.
7. Verifies that the typed terminal effect binds the workload, Ground, operator contract, input and implementation route. When symbolic memory is present, it also requires the exact receiver-generated read receipts for every requested binding.
8. Independently recomputes every returned lane with the scalar integer law z_i=a_i+b_i, using the value from a receipt only after checking its pinned memory identity. It checks lane cardinality and the exact ordered node-ID map.
9. Only after all lanes pass does it commit the results to their original ComputationNode IDs.

The route receipt and scalar oracle establish different properties. The receipt provides path and receiver-local admission provenance; the scalar oracle checks operation meaning. Neither is substituted for the other. A failed identity or value check prevents the affected frontier from being committed.

This first profile dispatches one ADD batch per ready frontier. A frontier is not yet split across several hosts, and the RPCs are sequential. The local DAG coordinator retains the result mapping and sends the next dependent frontier only after its predecessor frontier has committed.

## Demonstrated topology

The integration test compiles this algorithm:

\[
x=3+5,\qquad y=7+11,\qquad z=x+y
\]

Its two ADD frontiers are placed on different logical hosts:

| Stage | DAG operation | Selected host | Peer route | Local realization |
|---|---|---|---|---|
| First ADD frontier | Independent x and y lanes | logical-host-c-egpu | A → B → C | E-GPU vector.add |
| Second ADD frontier | Dependent z lane | logical-host-b-cpu | A → B | CPU strict integer vector add |

The first stage traverses B as a forwarding relay and terminates at C. In the second stage, B itself is the terminal execution host. Each result lane is mapped back to its original DAG node. The final register observation is then compared with ReferenceInterpreter for the same validated MailCPU Program.

This experiment demonstrates operation-level placement across different hosts and two different local implementations under one operator contract. It does not migrate a VM or distribute one full machine image.

## Shared arithmetic domain

The CPU and E-GPU implementations of `mailcpu.dataflow.add_frontier@1` implement one explicit shared domain:

- 1 to 64 aligned lanes per operation;
- strict integers (booleans are not integers in this contract);
- each input and result has at most 4096 bits;
- deterministic, pure, ordered vector-add output.

The CPU handler enforces those bounds even though Python integers are unbounded. The E-GPU handler is admitted for this contract only when its configured SIMT lane and integer bounds can realize the whole declared domain. A smaller E-GPU profile must not advertise this operator contract as fully compatible. The two implementations retain distinct implementation fingerprints even though their semantic operator contract is identical.

## Receiver-resolved Structural Memory

The receiver-side read is a part of operation realization, not compilation. The receiving Virtual Layer first validates the workload and its route-bound operator context, obtains local Hypervisor admission, and then resolves each `VirtualStructuralMemoryRef` using the receiver's own Structural Memory registry. The executing process must hold the explicit `/structural-memory/read` capability.

The returned `StructuralMemoryReadReceipt` identifies the exact memory, revision, coordinate, context, specification and certificate. The receiver's operator handler receives the resolved values and receipt envelope; the effect returns the receipts with the operator result. The origin compares each receipt to the reference that was actually sent and independently recomputes the operation before publishing DAG commits.

A relay does not need the memory, nor does it read memory merely because the workload contains a reference. The memory-owning host can be selected as the terminal execution host; a later dependent operation may be sent to another host using only the compact predecessor result. The memory value itself need not be sent as an input to that subsequent operation.

## Both execution granularities remain available

Operation-native distribution and VM/session distribution solve different problems.

Operation-native placement is appropriate when the computation can be represented as bounded, typed, deterministic transformations with explicit inputs, outputs, Ground and replay semantics. It allows a scheduler to send one operation or one frontier to the host that already has the relevant capability or data.

VM/session transfer remains appropriate when a computation depends on long-lived mutable memory, instruction pointer, process resources, control flow, stateful device interaction, or continuity of a machine execution context. A complete session may be checkpointed, moved and resumed when the cost or semantic requirements favor that approach.

The system should choose between operation dispatch, operation fusion, data movement, representation movement and session transfer. These are complementary execution modes, not competing definitions of E-CPU.

## Transit is not automatically faster

A passive communication edge transports the operation and required information. Arithmetic is performed by an active host on the route. A host can be a CPU, GPU-backed operator, signal processor, SmartNIC, FPGA or another admitted implementation, but the link itself is not presumed to compute.

For a remote operation, end-to-end time includes at least:

\[
T_{\mathrm{remote}}=
T_{\mathrm{serialize}}+
T_{\mathrm{route}}+
T_{\mathrm{queue}}+
T_{\mathrm{compute}}+
T_{\mathrm{verify}}+
T_{\mathrm{return}}
\]

This must be compared with local execution, including the cost of obtaining any remote data:

\[
T_{\mathrm{local}}=T_{\mathrm{local\ compute}}+
T_{\mathrm{data\ acquisition}}
\]

The remote path can win when it avoids moving a large data set, reaches information already resident at the target, exploits a capable parallel implementation, performs a reduction near data sources, overlaps work with an already-required communication transit, or avoids reconstructing a larger execution environment. Very small operations can lose because serialization, routing, queueing and verification dominate. Fusion may therefore be preferable to dispatching every arithmetic instruction independently.

Selection should be based on a cost vector rather than one processor's nominal speed:

\[
C(o,h,\rho)=
(L,E,B,M,V,R)
\]

where the dimensions may include end-to-end latency L, energy E, bytes moved B, memory residency/reconstruction M, verification cost V, and recovery risk R. Semantic compatibility, authority, observation equivalence and hard resource bounds are admission constraints, not negotiable cost terms. Estimated route costs must remain distinct from observed timings.

This integration does not claim that E-CPU is faster than a physical CPU or GPU. E-GPU in this profile is a bounded Python SIMT reference implementation, not a physical GPU driver, ISA, occupancy model or measured accelerator. A meaningful speed claim requires paired benchmarks of local execution, remote CPU operation and remote E-GPU operation using the same inputs and observation contract, reporting transport, queue, compute and verification costs separately.

## Boundaries and next work

This first implementation does not:

- compile arbitrary opaque bytes or programs outside the pure straight-line MailCPU subset;
- distribute branches, loops, side effects, syscalls or stateful sessions as independent operation requests;
- split one frontier across multiple target hosts;
- pipeline intermediate results directly from one terminal host to the next without returning through the origin coordinator;
- execute concurrently merely because the DAG contains independent nodes;
- resolve symbolic Structural Memory for operations other than ADD in this first integration profile;
- choose a host by an empirically trained adaptive cost model; target eligibility is declared by the caller in the current experiment;
- perform computation inside passive network links; or
- demonstrate physical GPU acceleration or lower end-to-end latency.

The next research step is to benchmark this same operation graph under local, remote CPU, remote E-GPU, and fused/partitioned placements. Then extend symbolic memory operands beyond ADD, partition wide frontiers across multiple hosts, and support content-addressed result movement without weakening exact revision and certificate binding.
