# Observer Contract and Contextual Orbit Navigation

## Status and scope

This document specifies the executable observer and contextual-orbit integration introduced by mailcpu.observer_orbit. It composes existing identity, semantic Ground, Virtual Ground, temporal, and Structural Memory types. It does not replace those subsystems or create a second authority, checkpoint, or storage model.

The first executable orbit profile intentionally returns a **symbolic Virtual Ground projection**: one value produced by one admitted Structural Memory generator at one coordinate, anchored to an exact system Virtual Ground. It is not a complete HeadlessOS snapshot, a SystemSeed, or a claim that a scalar is sufficient to reconstruct an arbitrary machine.

## 1. Observer as a typed operational contract

An observer-host has a stable identity and a bounded observation projection:

\[
O=(i,r,S,G,\Pi,C,L)
\]

- \(i,r\): observer identity and contract revision.
- \(S\): content-addressed representation being observed.
- \(G\): content-addressed Computational Ground that gives the subject meaning.
- \(\Pi\): versioned ObservationContract defining the projection.
- \(C\): exact context digest.
- \(L\): optional lineage digest.

This is represented by ObserverContract. The existing RepresentationRef is reused for subject and interpretation identity; the existing ObservationContract is reused for projection identity. No second representation or comparison vocabulary is introduced.

One observation receipt binds:

\[
R_O=(O,\mathrm{op},H(x),C,\Pi(x),\tau,S_b,S_a,E)
\]

where \(x\) is the input, \(\tau\) is an optional typed TemporalFrame, \(S_b,S_a\) are optional before/after state digests, and \(E\) is a set of content-addressed evidence references. ObserverReceipt.issue canonicalizes the projection and binds its digest. verify_observer_receipt checks that the receipt still matches the exact contract.

A content digest provides content identity and integrity under the hash assumption. It is not a signature, peer authentication, hardware attestation, or authority grant. An observer can be stateless; an observation receipt does not implicitly grant execution, persistence, routing, or commit rights.

## 2. Composition is aggregation, not consensus

ObserverComposition declares the observer contracts expected for one composite observation. Its members must agree on subject, interpretation, and context, but may use different projection contracts.

\[
\operatorname{Collect}(O_1,\ldots,O_n)
\rightarrow
(R_1,\ldots,R_n,R_{\Sigma})
\]

The aggregator verifies exactly one receipt for every declared member and binds each member's receipt and projection digest. It preserves each projection independently. It does not average, vote, infer equivalence, or claim consensus. Scheduler coordinates are compared only when observers actually provide them; a mismatch is refused.

This distinction allows multiple sensors or computational observers to provide complementary views of one subject without flattening those views into a synthetic result.

## 3. Contextual orbit address

The address is a product of existing identities:

\[
A_O=(I,G_s,G_c,\tau,M)
\]

- \(I\): SystemIdentity (including incarnation).
- \(G_s\): exact base VirtualGroundRef (origin, state, coordinate, input frontier).
- \(G_c\): RepresentationRef for the Computational Ground.
- \(\tau=(scheduler\_id,k)\): typed absolute SchedulerReading.
- \(M\): exact VirtualStructuralMemoryRef (memory id, revision, context, relative coordinate, spec digest, certificate digest).

Let \(k_0=G_s.coordinate\). The address is valid only when:

\[
k\geq k_0,\qquad t=k-k_0,\qquad M.coordinate=t.
\]

The Structural Memory context is an exact canonical binding of \(I,G_s,G_c,scheduler\_id\), plus explicitly named JSON extensions. The scheduler identifier is required because VirtualGroundRef v1 contains a numeric coordinate but does not itself name the scheduler clock domain. No conversion between wall time, monotonic duration, scheduler ticks, and causal order is inferred.

## 4. Symbolic Virtual Ground projection

For an admitted Structural Memory version \(M\) with certified generator \(g_M\), contextual location evaluates:

\[
v=g_M(t)
\]

and returns:

\[
G'_V=\operatorname{Project}(I,G_s,G_c,M,\tau,t,v).
\]

ContextualOrbitNavigator.locate resolves the exact pinned revision from the receiver-local StructuralMemoryRegistry, rechecks the spec and certificate digests, validates the observer's subject and Computational Ground, and performs read_revision at \(t\). The registry validates the exact context and GROUND/PREFIX-GROUND horizon and returns a StructuralMemoryReadReceipt.

The projection identity includes the system identity, base Ground, Computational Ground, transition/spec identity, absolute scheduler coordinate, relative offset, pinned memory revision/context/certificate, value, and value digest. It deliberately excludes per-read cache metadata and receipt identity; those remain attached as evidence. Thus the logical projection has stable content identity while each read retains its own provenance.

### Direct navigation and cost

The E0 Structural Memory generator families have direct coordinate operations:

| Family | Forward navigation | Bound |
|---|---|---|
| \`int\` | Arithmetic coordinate formula | \(O(1)\) |
| \`fgraph\` | Preperiod/cycle coordinate indexing | \(O(1)\) |
| \`lcg\` | Modular exponentiation and geometric sum | \(O(\log n)\) |
| \`gf2\` | Binary companion-matrix exponentiation | \(O(L^3\log n)\), where L is recurrence order |

The result reports \`expanded_states = 0\`: it does not construct states at \(k_0+1,\ldots,k-1\). The generator itself is still evaluated according to its family-specific arithmetic; zero intermediate expansion does not mean every generator has constant computational cost.

The contextual path is deliberately **no-fallback**. An unknown revision, mismatched context, non-admitted law, prefix-horizon escape, or unsupported family refuses. It does not silently switch to BFS or SystemSeed replay.

### Target-state inversion without trajectory enumeration

\`ContextualOrbitNavigator.locate_value\` derives the first supported relative coordinate for a requested scalar value:

| Generator | Inverse used | Cost |
|---|---|---|
| \`int\` | Exact modular or non-modular progression inversion | \(O(1)\) |
| eligible \`lcg\` | Full-period power-of-two 2-adic bit lifting | \(O(\log m)\) |
| \`gf2\` | Initial register inspection and feedback parity for one scalar output bit | \(O(L)\) |
| \`fgraph\` | Earliest-coordinate hash index over stored preperiod/cycle | \(O(N)\) build, then expected \(O(1)\) |

The finite-graph inverse index is retained by a \`ContextualOrbitNavigator\` and keyed by the admitted Structural Memory spec digest. The first query compiles the stored orbit; later queries against the same revision reuse the index. It does not execute or scan additional transitions.

The GF(2) inverse is deliberately for the scalar output bit, not an arbitrary LFSR register vector. Since the first L outputs are the initial register, a missing target bit implies a uniform all-zero or all-one register, whose next output is determined by feedback parity.

The candidate coordinate is forward-verified with the guarded law before a target address is formed. The resulting address is then read from the pinned Structural Memory revision and observed through the normal receipt path. PREFIX-GROUND horizons are enforced during forward verification and again by the registry read.

### General path-dependent transitions

A universal inverse does not exist for arbitrary guarded, context-dependent, non-injective transitions. \`ProcessPathIndex\` therefore compiles a supplied declarative transition path. Compilation applies only those named transitions, validating every guard, resource requirement, update and invariant; its cost is linear in the supplied path length P. It stores state digests and prefix resource envelopes so exact-state lookup is expected O(1), with zero path expansions at query time.

The index is bound to the exact descriptor, context and start-state digest. A locally built index is immediately validated; a portable index reconstructed from JSON must be revalidated against the descriptor and context before lookup. Its witness can then be independently checked with \`verify_navigation_witness\`.

This is an inverse of the supplied path, not the entire branching state graph. Absence from one path index is not proof of global unreachability. Finding a new route still requires the existing bounded \`ContextualNavigator\` or another explicitly budgeted graph/index construction. \`SystemSeed\` remains exact replay when the complete OS transition semantics are needed and no admitted symbolic representation applies.

The VirtualGroundRef v1 structure contains a numeric base coordinate but no scheduler identifier. The contextual address binds the declared scheduler ID into the Structural Memory context; it cannot independently prove which scheduler originally minted the base coordinate. The caller that forms the address must therefore supply that mapping from trusted system context.

## 5. Virtual Ground generation and Structural Memory

Structural Memory stores a certified generator description and evidence, not every generated state. VirtualStructuralMemoryRef points to a locally admitted immutable revision without shipping its generator or granting authority. The contextual address combines that symbolic generator with the admitted base Virtual Ground.

The generated projection is consequently a new coordinate view under an existing system anchor—not a replacement for that anchor. The base origin, state, and input-frontier digests remain explicit. A later vector-valued projection can compose several independently certified memory bindings, each with its own field/representation identity and receipt; it must not assume that a single integer generator is a complete VM state.

A revision's context is exact. A changed system identity, base Ground, Computational Ground, scheduler domain, or extension requires a newly staged and admitted Structural Memory revision. A PREFIX-GROUND generator can only be read strictly before its first-bad coordinate. Neither symbolic generation nor an observer receipt bypasses host admission policy.

## 6. Operational guarantees and limits

The executable contract establishes:

1. Stable observer, subject, interpretation, projection, and context identities.
2. A typed scheduler coordinate and explicit base-relative orbit offset.
3. Exact pinning to an admitted Structural Memory revision and certificate.
4. Guarded generator evaluation and a read receipt.
5. A symbolic Virtual Ground projection with a distinct content digest.
6. An observer receipt binding the request, time coordinate, projection, and evidence.
7. Deterministic aggregation of a complete observer set without asserting consensus.

It does not establish remote authenticity, general semantic equivalence, arbitrary state reconstruction, permission to execute, cross-host atomicity, or universal sublinear navigation. Those remain obligations of the corresponding authority, translation, recovery, and state-owning subsystems.

The central design rule is:

\[
\boxed{\text{Address by identity; navigate by law; admit by evidence; observe by contract.}}
\]
