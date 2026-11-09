# Operation-Native Computational Fabric

## Purpose

This specification composes the bounded MailCPU dataflow compiler with the existing Virtual Layer, Computational Address Resolver, authenticated Computational Fabric, and E-GPU method graph.

The computational object distributed by this profile is not a VM image or a complete process. It is a semantic operation over an explicitly described set of inputs. The algorithm remains a dependency graph. The fabric locates a receiver that advertises a compatible local implementation, and the receiver revalidates and executes the operation under its own Ground and Hypervisor authority.

The operation-native profile is deliberately bounded to three pure binary families: ADD, COMPARE and MUL. A ready frontier may contain any of these families; ADD frontiers are routed when an ADD dispatcher is supplied, while COMPARE and MUL remain local unless their operation-specific dispatchers are explicitly supplied. SET, COPY and HALT remain local. All remote families use the same binary lane, receiver-side Virtual Layer admission, fabric resolver, operation receipt structure and origin-side scalar oracle.

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

## Ranked placement alternatives

The fabric resolver exposes both the original single-winner query and a bounded ranked view:

- `ComputationalFabricResolver.resolve(...)` retains its compatibility contract and returns the least-cost feasible witness.
- `ComputationalFabricResolver.resolve_candidates(..., max_candidates=16)` returns a `ComputationalFabricPlacementSet` containing up to 16 feasible host/route alternatives by default. The bound may be set from 1 through 128.
- The set records the number of operator-version advertisements considered, the number that passed all semantic, Ground, implementation, authority-independent capability, route, and resource filters, the bounded search expansion count, and deterministic blockers.
- Candidate order follows the address's declared lexicographic metric basis, then hop count, peer path, link identity, and stable host identity. Truncation is explicit; callers can distinguish “one eligible host” from “more eligible hosts than returned”.
- Each candidate retains its own directory/topology-bound route witness and additive network/host cost vectors. The set is content-addressed and round-trippable.

This API exposes alternatives for later placement planning, comparison and bounded multi-host scheduling. It does not dispatch to several hosts, split a frontier, reserve capacity, or make an advertised cost a measured duration. All candidates are non-authoritative proposals. The selected receiver must continue to re-resolve the exact host/runtime binding, revalidate provenance and execute under its local Virtual Layer and Hypervisor.

The current ranking is deterministic and declarative. The phase timing probe is observational data, not yet an online feedback loop; no automatic learning or adaptive placement claim is made.

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

The ADD contract applies strict bounded integer addition and returns the ordered values vector. The COMPARE contract, mailcpu.dataflow.compare_frontier@1, applies the MailCPU relation compare_values(a,b)=sgn(a-b), returning exactly -1, 0 or 1. The MUL contract, mailcpu.dataflow.multiply_frontier@1, applies strict integer multiplication and returns the exact bounded product. CPU and E-GPU implementations are admissible only when they advertise the matching contract and preserve its declared observation. This does not imply that arbitrary CPU, GPU, signal or programmable-network implementations are interchangeable.

## Operation context and state-space navigation

The portable object is the semantic operation contract; its meaning is instantiated by a particular Ground, input and observation context. Binary laws can be written independently of any one machine:

[
o_ADD(a,b)=a+b;  o_COMPARE(a,b)=sgn(a-b);  o_MUL(a,b)=a*b
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

1. Reads the exact operands from immutable initial values or already committed predecessor results. A symbolic Structural Memory operand remains an address at this point; it is not eagerly read by the compiler or coordinator. A contextual-orbit source remains a typed DAG predecessor and is not flattened into an untracked initial integer.
2. Selects the remote binary nodes in the ready frontier by registered operation family and orders each family by stable node_id. COMPARE and MUL stay local when their respective operation dispatchers are not configured.
3. Constructs one operation-specific typed frontier request binding the plan digest, context digest, frontier index, node digests, destination registers, ordered scalar operands, and any contextual-orbit predecessor evidence recovered from DAG ancestry. ADD, COMPARE and MUL have distinct versioned request schemas while sharing DataflowBinaryLane.
4. Builds one pure VirtualLayerWorkload for the selected operator contract. Inline values travel as values; symbolic Structural Memory references travel as schema-v2 Virtual Layer addresses containing the memory identity, exact revision, context, coordinate, specification digest and certificate digest. A contextual-orbit operand travels as a typed descriptor containing its scalar projection and complete predecessor input(s). Only the selected query/result evidence is sent; no orbit trajectory or full VM image is shipped.
5. Uses ComputationalFabricResolver to select an advertised host and directed peer route.
6. Sends the operation through the existing authenticated per-hop forwarding protocol. Relay peers apply their local forwarding policy; the terminal peer re-resolves the workload and executes its local operator.
7. Verifies that the typed terminal effect binds the workload, Ground, operator contract, input and implementation route. When symbolic memory is present, it also requires the exact receiver-generated read receipts for every requested binding. The CPU and E-GPU handlers revalidate every contextual-orbit predecessor object in the operation input.
8. Independently recomputes every returned lane with the declared scalar law: z_i=a_i+b_i for ADD, z_i=sgn(a_i-b_i) for COMPARE, or z_i=a_i*b_i for MUL. Receiver memory values are used only after their pinned read receipts are checked. The contextual-orbit receipt remains provenance for the selected input; it does not replace the independent scalar oracle. The executor checks lane cardinality and the exact ordered node-ID map.
9. Only after all lanes pass does it commit the results to their original ComputationNode IDs. Each remote result commit retains the typed frontier receipt, receipt digest, request digest, operator ID/version and operator-contract digest inside the DAG result, so the navigable snapshot remains execution-evidence-bearing.

The route receipt and scalar oracle establish different properties. The receipt provides path and receiver-local admission provenance; the scalar oracle checks operation meaning. Neither is substituted for the other. A failed identity or value check prevents the affected frontier from being committed.

## Contextual-orbit predecessor composition

A ContextualOrbitDataflowInput binds one origin-verified routed inverse result to an explicit scalar projection: coordinate or value. The object retains the original inverse request, routed receipt, observer projection and located-coordinate Structural Memory read receipt. It does not include the intermediate orbit states.

The compiler's v3 dataflow plan creates one orbit-input source node per supplied register and adds ordinary dependency edges from consuming instructions. The source node commits the selected integer together with the typed input and receipt identities. For an operation-native descendant, the executor follows the DAG ancestry and includes the relevant typed inputs alongside the current scalar operand. This also works after intermediate DAG operations: the value may have been transformed, while the compact predecessor evidence remains traceable through its dependency lineage.

The operation-native ADD request/receipt schemas and shared CPU/E-GPU ADD operator contract are v3; COMPARE and MUL each have their own v1 request/receipt and operator contract. The receiving handler rehydrates and validates each contextual-orbit input before executing the selected binary operation; the requester still verifies the returned scalar result independently before commit. Only coordinate/value projections are accepted in this slice, the compiled profile remains bounded, and evidence digests are integrity/provenance bindings rather than signatures or hardware attestation.

This executor still dispatches at most one homogeneous binary-operator batch per ready frontier for each configured operation family, and its RPCs remain sequential. The new `BinaryFrontierPartitionPlan` describes how a homogeneous batch can be split into child requests with distinct route witnesses, but the operation-native executor does not yet consume that plan or dispatch its children across hosts. See `BINARY_FRONTIER_PARTITIONING.md` for the strict description/coverage contract. The local DAG coordinator retains the result mapping and sends the next dependent frontier only after its predecessor frontier has committed.

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

## Shared binary operand domain

The CPU and E-GPU implementations of the binary operation contracts use one explicit shared operand domain:

- 1 to 64 aligned lanes per operation;
- strict integers (booleans are not integers in this contract);
- each input and result has at most 4096 bits;
- deterministic, pure, ordered output lanes;
- ADD returns the exact integer sum and retains the 4096-bit result bound;
- COMPARE returns exactly one of -1, 0 or 1 under the sign(left-right) observation;
- MUL returns the exact integer product and refuses any result exceeding the shared 4096-bit bound.

The CPU handler enforces the operand and ADD result bounds even though Python integers are unbounded. The E-GPU handler is admitted for these contracts only when its configured SIMT lane and integer bounds can realize the whole declared operand domain. A smaller E-GPU profile must not advertise a compatible operator contract. CPU and E-GPU implementations retain distinct implementation fingerprints even when they share one semantic operator contract.

## COMPARE as the second binary operation family

COMPARE reuses the same binary frontier and fabric machinery as ADD rather than creating a separate execution stack. The compiler already emits COMPARE nodes with two typed operands and the reference interpreter already defines the observation as sign(left-right).

The v1 COMPARE frontier request carries the same DataflowBinaryLane shape as ADD, including inline values, revision-pinned Structural Memory references and contextual-orbit predecessor evidence. Its own operator contract is mailcpu.dataflow.compare_frontier@1. The shared ComputationalFabricDataflowBinaryDispatcher is specialized by thin ADD and COMPARE dispatchers; host advertisement and route resolution still match exact operator ID, version, Ground, substrate, and implementation fingerprint.

The CPU handler applies compare_values directly. The E-GPU handler uses the existing bounded TransitSIMTHost custom-kernel method: load both lane arrays, compute less-than predicates in both directions, and use structured IF/ENDIF masks to select -1, 0 or 1. The handler checks every returned lane against compare_values before returning. The origin then independently applies that same law again before committing the DAG node.

A caller opts into remote COMPARE by passing operation_dispatchers={"COMPARE": compare_dispatcher} to execute_dataflow_operation_native. Without that dispatcher, COMPARE remains in the local coordinator as before. Remote MUL is independently enabled with operation_dispatchers={"MUL": multiply_dispatcher}; without it, MUL remains local. When routed, its full typed receipt is committed into the DAG result; from_dict rehydrates ADD, COMPARE and MUL receipts under their distinct schemas. A subsequent operation can inspect the graph snapshot and recover the exact operator and route evidence associated with an earlier remote result.

The end-to-end integration test uses one authenticated A→B→C route: C first performs contextual inverse navigation on its local CPU operator, then the compiled DAG dispatches COMPARE, MUL and a dependent ADD to separately advertised E-GPU operator loci at C. Each transformed operand retains the original orbit predecessor through DAG ancestry; the selected-coordinate Structural Memory read is not repeated.

## MUL as the third binary operation family

MUL extends the same operation-neutral DataflowBinaryLane and ComputationalFabricDataflowBinaryDispatcher. It adds no new transport layer, host-selection path, receiver runtime or DAG representation. The MailCPU opcode defines the scalar law a*b; the versioned operator contract is mailcpu.dataflow.multiply_frontier@1.

The MUL request and receipt each have their own v1 schema. CPU multiplication enforces the shared 64-lane, 4096-bit operand/result domain. The E-GPU realization reuses its registered vector.multiply method, which compiles through the existing bounded TransitSIMT mul instruction. Its returned vector is checked against the same independent scalar product law, first at the receiver handler and again at the origin before the original DAG node is committed. Products that exceed 4096 bits are refused rather than silently widening the remote contract.

MUL is locally interpreted unless the caller supplies operation_dispatchers={"MUL": multiply_dispatcher}. A remote multiplication result embeds its typed receipt, request digest, operator identity/version and contract digest in the DAG snapshot, preserving the same lineage and provenance guarantees as ADD and COMPARE.

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

The first correctness-checked phase benchmark now exists in `examples/operation_frontier_benchmark.py`. It compares the same compiled MUL frontier under local CPU, remote CPU and remote E-GPU placement and records route resolution, origin round-trip, transport send/response/ack, receiver peer and semantic admission, witness/host revalidation, Virtual Layer admission, provenance validation, backend compute, origin verification, and total completion. The report is endpoint-local and marks inclusive/nested spans explicitly; it does not infer one-way network delay from unsynchronized clocks. See [OPERATION_FRONTIER_TIMING.md](OPERATION_FRONTIER_TIMING.md) for commands, phase definitions, and interpretation limits.

## Boundaries and next work

This bounded binary-operation profile does not yet:

- compile arbitrary opaque bytes or programs outside the pure straight-line MailCPU subset;
- distribute branches, loops, side effects, syscalls or stateful sessions as independent operation requests;
- split arbitrary effects, stateful sessions or non-binary operation families across target hosts;
- pipeline intermediate results directly from one terminal host to the next without returning through the origin coordinator;
- resolve symbolic Structural Memory for operation families outside the supported ADD, COMPARE and MUL binary frontiers;
- choose a host by an empirically trained adaptive cost model; target eligibility is declared by the caller in the current experiment;
- perform computation inside passive network links; or
- demonstrate physical GPU acceleration or lower end-to-end latency.

Homogeneous ADD, COMPARE and MUL frontiers can now be partitioned into independently addressed child requests and dispatched to distinct authenticated hosts through the existing forwarding path. Each child is re-resolved before dispatch and admitted locally by the receiving Hypervisor / Virtual Layer. The origin collects typed child receipts into a composite parent receipt, independently verifies every original lane, and commits the original DAG frontier atomically. Bounded concurrency is applied across independent authenticated first-hop streams; a single reliable stream remains serialized. Recovery preserves verified child receipts and replays only missing children to their same route/sequence. It deliberately refuses alternate-host reassignment after an ambiguous outcome because receiver-local deduplication cannot prove that another host will not repeat an already-completed semantic effect.

See [BINARY_FRONTIER_PARTITIONING.md](BINARY_FRONTIER_PARTITIONING.md) for the stable split, and [PARTITIONED_BINARY_FRONTIER_EXECUTION.md](PARTITIONED_BINARY_FRONTIER_EXECUTION.md) for child dispatch, receipt composition, checkpoints, sequence discipline and current recovery limits. The next research step is transferable idempotency/effect claims for safe child rehoming after host loss, followed by broader heterogeneous resource providers and correctness-checked local/remote/fused placement benchmarks.
