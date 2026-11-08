# Compositional Virtual Ground and Inverse Navigation

## 1. Two coupled descriptions

The virtual layer should preserve two distinct but coupled views of a described system:

- **Structural information**: bytes, fields, register layouts, memory regions, coordinates, component identities, transition descriptions, and content digests.
- **Interpreted structure**: the Computational Ground, state schema, meaning of each component, admissible operations, invariants, and the semantics assigned to a structural representation.

A structural representation does not by itself establish meaning. An interpretation does not replace the exact bytes or component layout it interprets. The runtime therefore binds both:

\[
R_i=(type_i,schema_i,H(payload_i)),\qquad
G_c=RepresentationRef(\text{Computational Ground}).
\]

For each state component, its representation identifies the component's structural and semantic representation, while the common Computational Ground identifies the interpretation in which the composed state is understood.

The long-term objective is to find a compact generator basis that explains and navigates as much of the described state-space as the evidence permits. A single universal model is not assumed.

## 2. Composed address

ComposedVirtualGroundAddress is a common system/time address plus a finite set of independently pinned component laws:

\[
A_C=(I,G_0,G_c,\tau,\Sigma,T,\{C_i\}_{i=1}^{m},X)
\]

where:

- \(I\): exact SystemIdentity, including incarnation.
- \(G_0\): base VirtualGroundRef (origin, current base state, scheduler coordinate, causal input frontier).
- \(G_c\): Computational Ground representation.
- \(\tau=(scheduler\_id,k)\): typed absolute scheduler coordinate.
- \(\Sigma\): interpreted state schema.
- \(T\): canonical JSON template and its content-addressed identity.
- \(C_i\): one component identifier, field path, structural representation, scalar encoding, and revision-pinned VirtualStructuralMemoryRef.
- \(X\): explicitly declared common extensions.

Let \(k_0=G_0.coordinate\). Every component is bound to the same relative coordinate:

\[
t=k-k_0,\qquad C_i.coordinate=t.
\]

The Structural Memory context for component \(i\) also binds the schema, template digest, component identity, field path, representation, scalar encoding, and scheduler domain. A change to any one of these requires a separately admitted memory revision.

Component field paths must be distinct and non-overlapping. This prevents two generators from silently writing different values to the same state location or one component replacing another component's subtree.

## 3. Composition

For admitted component generators \(g_i\), the runtime computes:

\[
v_i=g_i(t)
\]

and assembles:

\[
S_t=T[\pi_1\leftarrow v_1,\ldots,\pi_m\leftarrow v_m].
\]

Here \(\pi_i\) is the declared component field path. The implementation currently supports integer fields, byte-valued scalar fields, and bit-valued scalar fields. A byte sequence is represented as a sequence of separately addressed byte components; a dedicated byte-vector generator is a later extension.

ComposedVirtualGroundNavigator.locate performs one guarded StructuralMemoryRegistry.read_revision for each component. It does not walk the intervening system ticks. Each generated component retains its own StructuralMemoryReadReceipt, spec digest, certificate digest, context, and representation identity. The aggregate state has a separate digest, and the projection can be reconstructed from the template and component values.

The output is a **composed Virtual Ground projection**, not an automatically restorable HeadlessOS checkpoint. A template may describe selected OS state fields or a complete state-shaped representation. To promote it to a full checkpoint, the schema must establish coverage of every required VM/OS subsystem and the state owner must validate and restore it through the existing checkpoint path. Component completeness is not inferred from a successful composition.

## 4. Predictability and information change

The component model makes three different outcomes explicit:

1. **Predictable**: an admitted generator produces a value at the addressed coordinate, and the guarded read returns a receipt.
2. **Outside the current model**: a family is unsupported, a context changed, or a PREFIX-GROUND horizon was crossed. The read refuses instead of extrapolating silently.
3. **State information changes**: component values differ from the template or prior projection. The resulting state digest and component receipts make the change observable.

A read receipt proves a value was produced by the receiver's admitted generator under a particular revision and context. It does not prove the generator is a universally correct model of physical hardware or an entire OS. GROUND remains grounded by supplied witnesses; PREFIX-GROUND remains bounded by its escape coordinate.

## 5. Inverse navigation

Inverse navigation now has several distinct algorithms rather than one generic search switch.

| State description | Inverse method | Cost and boundary |
|---|---|---|
| Integer progression | Modular arithmetic inverse | \(O(1)\) |
| Eligible full-period power-of-two LCG | 2-adic bit lifting | \(O(\log m)\) |
| GF(2) scalar output bit | Initial register and feedback parity | \(O(L)\), bounded by recurrence order |
| Finite functional graph | Cached value-to-first-coordinate index | \(O(N)\) one-time index build, then expected \(O(1)\) lookup |
| General declarative path | ProcessPathIndex over a supplied validated transition path | \(O(P)\) path compilation, then expected \(O(1)\) exact-state lookup |

### GF(2)

For an L-register output recurrence, the first L outputs are already present in the initial register. If a target bit is absent from that register, the initial state is either all zero or all one. The zero state is fixed; the all-one state either remains fixed or produces zero at the next output. Therefore the earliest occurrence can be decided from a bounded register check and feedback parity. This API inverts the scalar output value, not an arbitrary LFSR register vector.

### Finite functional graph

The E0 representation already stores its finite preperiod and cycle. A cached inverse index maps each stored state value to its earliest coordinate. Index compilation is linear in the stored orbit description; a ContextualOrbitNavigator retains the compiled index per admitted Structural Memory spec, so subsequent queries through that navigator are expected constant-time. The index does not invoke the transition function to discover new states.

### General path-dependent transitions

There is no universal algebraic inverse for arbitrary guarded transitions, especially when updates are non-injective or context-dependent. ProcessPathIndex.build therefore accepts an explicit finite declarative transition path, revalidates each guard, update, invariant, and resource condition, then stores state-digest coordinates and prefix resource envelopes. This is a verified path under the descriptor, not a receipt proving that a physical host executed it.

The path index provides direct lookup for exact states already present in that validated path and returns an existing NavigationWitness. A portable index must be revalidated against the exact descriptor and context after deserialization before lookup. verify_navigation_witness independently replays the returned path under the descriptor and context.

This is an inverse of the indexed path, not an inverse of the entire branching state graph. Absence from one path index is not a proof of global unreachability. Discovering a path that has not been supplied still requires the existing bounded ContextualNavigator or another explicitly budgeted graph/index construction.

The GF(2) *forward* jump uses binary companion-matrix exponentiation and is (O(L^3\log n)) for recurrence order L; the (O(L)) inverse above is only for locating a scalar output bit.

## 6. Anti-enumeration policy

The preferred resolver order is:

1. Use an exact direct generator or algebraic inverse where available.
2. Use a cached finite-state inverse index when the state-space representation already contains its finite orbit.
3. Use a verified path index when a concrete declarative path is already known.
4. Use bounded graph search only when a new path must be discovered.
5. Use exact SystemSeed replay when the complete OS transition semantics are required and no valid symbolic representation exists.

No direct-navigation refusal silently triggers a more expensive algorithm. Every compiled index has an explicit build cost and a content identity. A later optimization layer can compare alternative generator bases using predictive coverage, withheld error, description size, navigation cost, and verification cost; this implementation provides the compositional and inverse-navigation substrate, not the optimizer itself.

## 7. What the implementation does not assert

This layer does not claim that every byte stream has already been assigned an executable meaning, that every OS state can be reconstructed from scalar generators, or that a virtual representation is already more capable than the described machine. Those are system goals to be tested.

It does establish a concrete mechanism for composing independently grounded state components, preserving both their structural identities and interpreted roles, navigating their shared temporal coordinate, and directly locating states through supported inverse mathematics or verified path history.

\[
\boxed{\text{Compose by representation; predict by law; invert by structure; verify by witness.}}
\]
