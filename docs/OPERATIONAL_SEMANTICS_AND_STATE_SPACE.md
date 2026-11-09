# Operational Semantics and State-Space Navigation

## Purpose

This document records a design interpretation for E-CPU: a portable operation is a stable semantic relation, while a concrete execution is that relation interpreted under an exact Ground, input state, memory context, observation contract, and admitted host implementation.

The operation is not a VM image. It is not inherently tied to one processor instruction sequence. It is a typed relation that can be realized wherever an eligible host can establish the same declared meaning.

This interpretation composes existing E-CPU systems. It does not replace the Computational Ground, System Ground, Virtual Ground, Structural Memory, Observer, Virtual Layer, Computational Fabric, or Hypervisor models.

## 1. The operation is portable; meaning is contextual

A pure operation can be described abstractly as a relation:

\[
o:X\rightarrow Y
\]

For integer addition:

\[
o(a,b)=a+b
\]

That definition does not identify which values are supplied, where they originate, how they are encoded, what integers mean in the selected computational domain, or what output projection the caller needs.

A concrete request therefore binds the semantic operation to context:

\[
Q=(I,G_s,G_c,X,C,M,B,\Omega)
\]

where:

- \(I\) is the operation identity and version;
- \(G_s\) is the exact System and base Virtual Ground anchor;
- \(G_c\) is the Computational Ground that defines the operation's interpretation;
- \(X\) is the input, including inline values or symbolic state references;
- \(C\) is the exact context and program/frontier identity;
- \(M\) is the declared Structural Memory identity/revision/coordinate evidence, when required;
- \(B\) is the resource and authority envelope; and
- \(\Omega\) is the declared output observation.

The portable operation is the stable relation. The request binds it to a particular meaning. A host supplies a local implementation of that relation and must preserve the declared observation. Two hosts may share the same operator-contract digest while retaining distinct implementation fingerprints.

This is the operational interpretation of an operation that travels through E-CPU: the network carries a typed description and its required state references; it does not require the sender to ship a whole VM or executable handler.

## 2. Three distinct topologies

The execution model composes three different relations.

The algorithm topology is its dependency graph:

\[
\mathcal D=(O,\prec)
\]

It says which semantic operations must precede others.

The communication topology is the directed graph of reachable peers and paths:

\[
\mathcal F=(H,E)
\]

It says which logical hosts can exchange the bounded information required by an operation.

Each host may contain its own operational topology:

\[
\mathcal L_h=(V_h,E_h)
\]

For example, the current E-GPU reference host has dispatch, SIMT execution, and verification loci.

A placement maps algorithm operations to logical hosts:

\[
\pi:O\rightarrow H
\]

A route witnesses how the operation and its required information reach the selected host. The dependency DAG, communication graph, and local host graph must remain separately identifiable. Flattening them into one generic "distributed VM" loses the distinction between what the algorithm means, where the information can go, and how a receiver realizes its local operation.

A passive link transports signals. An active host on the path may interpret the request, read local state, perform a transformation, verify a result, or relay the next operation. A path segment can itself host a computation only when it exposes an explicit observation/transition contract and required authority. Transit is not automatically computation.

## 3. Virtual Ground and Structural Memory supply state coordinates

A Virtual Ground is an identity-bearing anchor for a particular system state and input frontier. It should not be conflated with a complete process snapshot or a generic memory address.

Structural Memory represents an admitted law or generator with a specific revision, interpretation context, and certificate. A \`VirtualStructuralMemoryRef\` names one exact coordinate:

\[
R=(m,r,c,q,d_s,d_c)
\]

where \(m\) is the memory identity, \(r\) the admitted revision, \(c\) the immutable context, \(q\) the coordinate, \(d_s\) the specification digest, and \(d_c\) the certificate digest.

The reference is not the value, the generator code, a read grant, or a portable execution authority. It says which value the receiver is being asked to resolve. The receiving host performs the read through its own Structural Memory registry after local Hypervisor admission and explicit read capability. The receiver returns a typed read receipt. The caller verifies the receipt against the exact reference before using the value in an operation result.

This is a useful separation:

- compile-time description preserves the symbolic source;
- transit preserves the pinned address;
- receiver-side realization resolves the value under local authority;
- result verification binds both the returned operation result and the read evidence.

The new operation-native dataflow profile supports this form for ADD operands. It does not yet resolve arbitrary symbolic values for every MailCPU instruction.

## 4. A process is an orbit of a state-space, not always a sequence to replay

For a declared Ground \(G\), let \(\Omega_G\) be its admitted state-space and \(T_G\) its transition relation. From a starting state \(s_0\), a discrete trajectory can be written:

\[
\tau_G(s_0)=(s_0,T_G(s_0),T_G^2(s_0),\ldots)
\]

A query may ask for a state coordinate whose observation satisfies a predicate:

\[
q^\star=\min\{q\geq 0:
P(\operatorname{Obs}_G(S_G(q),x))=\mathrm{true}\}
\]

Here \(x\) is the input context, \(S_G(q)\) is the state represented at coordinate \(q\), and \(P\) is the caller's desired observation condition. The minimum is meaningful only when the coordinate order and the search/inversion policy are declared.

The system must distinguish three different tasks:

1. **Coordinate evaluation:** a coordinate is already known. Use the admitted generator to evaluate that location.
2. **Direct inverse navigation:** the target observation is known and the admitted generator family has a proven inverse/index method. Derive the first matching coordinate, then forward-verify it under the same Ground and horizon.
3. **General path search:** no direct inverse applies. Search a declared finite/bounded transition graph or supplied path under explicit expansion, depth, and resource bounds. Do not silently substitute an unbounded scan.

The repository already implements the first two for a bounded set of Structural Memory generator families through \`ContextualOrbitAddress\`, \`ContextualOrbitNavigator.locate\`, and \`locate_value\`. In the current implementation:
- integer progression inversion is \(O(1)\);
- eligible full-period power-of-two LCG inversion is \(O(\log m)\);
- GF(2) scalar-output inversion is bounded by recurrence order;
- finite functional-graph inversion builds a reusable index in \(O(N)\), then performs expected \(O(1)\) lookup.

The exact supported conditions and refusal boundaries are in \`OBSERVER_ORBIT_CONTRACT.md\`. Unsupported inverse conditions refuse; they do not fall back invisibly to BSGS, BFS, or state replay.

This is the strongest current expression of the idea that E-CPU should navigate to a matching moment rather than always step through every preceding state. It is a bounded mathematical capability, not a universal state-space oracle.

## 5. Interpretation speed versus iteration speed

A direct coordinate evaluation can avoid materializing intermediate states. An inverse method can derive a matching coordinate without replaying every transition. A compact Structural Memory law can represent a large family of possible states without storing the entire family as resident memory.

These are forms of *interpretive compression*: the receiver resolves a state by applying an admitted description and evidence, rather than by rebuilding every earlier state.

That does not erase computation. It changes which computation is necessary.

The cost depends on the admitted generator, inverse method, data residency, host placement, and observation. Some coordinates are constant-time formulas; others require modular exponentiation, matrix powering, index construction, or bounded path search. If no lawful direct method exists, the system must refuse or use a separately declared bounded search.

Physical execution also retains serialization, network, queue, host-compute, verification, and result-return costs:

\[
T_{\mathrm{remote}}=
T_{\mathrm{serialize}}+
T_{\mathrm{route}}+
T_{\mathrm{queue}}+
T_{\mathrm{resolve}}+
T_{\mathrm{compute}}+
T_{\mathrm{verify}}+
T_{\mathrm{return}}
\]

The "speed of interpretation" hypothesis is therefore precise: when an admitted Ground and Structural Memory law provide a direct representation or inverse coordinate method, the system may avoid unnecessary trajectory expansion or full-state reconstruction. It is not a claim that communication or physical computation takes zero time.

## 6. Current composition and proof boundary

The existing modules establish complementary pieces:

| Capability | Existing implementation | Boundary |
|---|---|---|
| Stable operation DAG | MailCPU dataflow compiler | Bounded straight-line pure subset |
| Heterogeneous operation placement | Virtual Layer + Computational Fabric | Receiver must advertise compatible Ground, operator and capabilities |
| Receiver-local memory resolution | Virtual Layer `VirtualStructuralMemoryRef` | Exact pinned coordinate; receiver read authority required |
| Authority-only navigation access | Virtual Layer schema-v3 `structural_memory_access="navigate"` | Receiver validates an exact revision and coordinate after Hypervisor ALLOW without materializing that coordinate |
| Contextual coordinate evaluation | `ContextualOrbitNavigator.locate` | Admitted Structural Memory generator families |
| Target-value coordinate inversion | `ContextualOrbitNavigator.locate_value`, exposed through `ContextualOrbitLocateValueDispatcher` | Explicitly supported inverses only; bounded receiver descriptor/index profiles; unsupported families refuse |
| Verified inverse-to-DAG predecessor | `ContextualOrbitDataflowInput` and `MailCPUDataflowCompiler.contextual_orbit_inputs` | Explicit coordinate/value projections; complete request, observer, route and located-coordinate receipt retained without trajectory expansion |
| State/path navigation | Contextual Process Navigation | Finite declared rule language and bounded BFS |
| Result integrity | Translation contracts, receipts, DAG commits, contextual orbit route receipt | Digests bind content and provenance; they are not signatures or remote hardware attestation |

The operation-native dataflow profile composes symbolic memory references with remote ADD execution and checks receiver read receipts plus an independent scalar operation oracle before committing a frontier. The contextual orbit profile routes a typed target-value query through the existing fabric: the destination validates its local Structural Memory authority, invokes the existing inverse navigator, forward-verifies the candidate, and returns the selected projection and located-coordinate receipt. The explicit navigate access mode prevents the receiver's authorization step from eagerly reading the base coordinate. A three-peer integration test asserts that the relay performs no Structural Memory read and the destination journals only the selected coordinate read.

The next composition is now implemented on top of those capabilities. ContextualOrbitDataflowInput binds the original inverse request to its origin-verified routed receipt and exposes a selected coordinate or value. The v3 compiler emits a distinct predecessor node for each such input and attaches normal dependency edges to consuming instructions. The DAG retains the typed request, selected projection, observer evidence and read receipt; it does not copy intermediate states or replay transitions. When a downstream ADD is routed, the operation-native executor recovers the compact evidence through the DAG ancestry and carries it alongside the scalar operand. The receiving CPU/E-GPU operator revalidates that evidence, and the origin still checks the scalar arithmetic result independently before commit.

These remain bounded operation profiles, not arbitrary predicate search over arbitrary state-spaces. The current bridge accepts coordinate/value projections and routes ADD frontiers; it does not make every opcode remotely executable. Ground, observer, memory-revision, route and read-receipt identities remain bound, and a digest receipt is not treated as a proof of trusted hardware execution.

## Design rule

\[
\boxed{
\text{Transport the operation; bind its meaning; navigate by admitted laws; materialize only the required state.}
}
\]
