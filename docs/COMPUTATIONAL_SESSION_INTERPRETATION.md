# Stateful computational interpretation and compiled virtual grounds

## Purpose

M4 joins the M3 persistent session state machine to domain-owned interpretation without making the session layer depend on one runtime. It also reduces repeated VGI interpretation work by compiling immutable task representations once for an exact declared Ground and reusing only those representations.

The central distinction is:

- a session checkpoint establishes **which bytes and causal revision are current**;
- a computational Ground establishes **what representations and operations mean**;
- a compiled interpretation plan establishes **how a declared task is represented for one Ground and compiler implementation**;
- a transition backend establishes **how one verified state and input produce candidate successor bytes**;
- the session CAS and quorum lineage establish **whether those candidate bytes become current**.

None of these identities substitutes for another.

## 1. Can a virtual Ground be compiled from information?

Yes, when “the information” includes an explicit, versioned declaration of the Ground and the task or transition language to be interpreted. The compiler can turn those declarations into a finite operational representation: validated instructions, control-flow edges, representation constraints, observation rules, and a Program IR.

It cannot safely infer a computational Ground from arbitrary opaque state bytes alone. A byte sequence has no universal semantics. It could encode registers, tensor values, a database page, a VGI signal store, or something else. A schema and Ground contract must define the interpretation before those bytes can be meaningfully used.

For VGI Signal8, the computational Ground is already declared as SIGNAL8_GROUND. It identifies the finite domain and assumptions, observer coordinates, instruction set, ambiguity policy, and evidence boundary. TaskSpec supplies the typed expression tree. VGI's compiler lowers that expression tree into an immutable Program. This is a compiled interpretation plan, not a newly inferred Ground.

The admitted E-CPU System Ground remains separate. It establishes the current host/system identity and causal frontier. It is not the VGI mathematical Ground. A VGI plan therefore binds the computational-Ground fingerprint; the normal Virtual Layer admission path separately checks the System Ground.

## 2. Domain-neutral transition contract

ComputationalTransitionContract declares:

- a stable transition identity;
- exact state and input schema identities;
- a Ground/program/compiler interpretation fingerprint;
- the backend implementation/profile fingerprint;
- finite input and successor-state byte limits;
- deterministic behavior and effect mode.

ComputationalSessionTransitionAdapter admits only a deterministic backend declared pure. This is necessary because a candidate may be recomputed after a crash or concurrent compare-and-swap loss. An effectful operation needs the existing Hypervisor effect/commit protocol, not this state-only adapter.

The backend exposes:

\[
T : (s_r, x, \kappa_r) \rightarrow s_{r+1}
\]

where \(s_r\) is the verified current state byte sequence, \(x\) is the exact input byte sequence, and \(\kappa_r\) is an immutable ComputationalTransitionContext. It must return exact successor bytes. The adapter does not decode either byte sequence; the backend owns the declared schema.

The adapter rejects mismatched state schema or backend fingerprints, non-pure effect declarations, malformed input, oversized state/input, and a backend that returns a non-byte result. Contract declarations and source fingerprints are identity statements, not proof that arbitrary backend code is trustworthy or actually pure.

## 3. Session-bound context, logical time, and commit

Before calling the backend, the adapter loads ComputationalSessionStore.load_latest(). That read verifies the immutable M1 state pages and resolves the exact checkpoint selected by the current quorum high-water. It then constructs a context binding:

\[
\kappa_r =
(I_S,r,H(C_r),\rho_r,H(s_r),I_A,G_S,B,I,H(K),op,h(x),t_{r+1})
\]

where:

- \(I_S\): session identity;
- \(r\): current committed revision;
- \(H(C_r)\): current checkpoint digest;
- \(\rho_r\): current quorum-lineage root;
- \(H(s_r)\): exact state-byte digest;
- \(I_A\): immutable artifact manifest digest;
- \(G_S\): state schema identity;
- \(B\): backend fingerprint;
- \(I\): interpretation fingerprint (for example a VGI compiled-plan digest);
- \(H(K)\): transition-contract digest;
- \(op\): caller-supplied operation identity;
- \(h(x)\): digest binding the input bytes, input schema, and contract;
- \(t_{r+1}=t_r+1\): next logical-time coordinate.

The context's binding_digest is the canonical digest of every field. It gives a backend a stable coordinate for interpretation, cache lookup, trace annotation, or audit. It is not an authorization token.

After the backend returns candidate bytes, the adapter submits them to the existing commit_state() with both the exact expected revision and checkpoint digest. M3 persists the immutable checkpoint envelope and asks the existing quorum lineage to seal it. The adapter introduces no second commit authority or mutable latest pointer.

New transitions advance logical time by exactly one. An explicit time may be supplied, but it must equal the current session time plus one. This preserves the existing E-CPU logical-event progression instead of letting a caller silently jump or rewind the session coordinate.

The immediate retry path recognizes the latest committed operation only when transition, input commitment, backend, and any explicitly supplied logical time match. It returns the committed snapshot as replayed without re-entering the backend. Reusing that operation identity for different input or interpretation is refused. The mechanism intentionally matches M3's immediate retry boundary; it is not a global historical operation catalogue.

## 4. VGI compiled-plan optimization

The VGI host now derives an immutable VGICompiledTaskPlan from three exact inputs:

\[
P = \operatorname{Compile}(G_c, I_{\mathrm{compiler}}, D_{\mathrm{task}})
\]

where:

- \(G_c\): explicit VGI Signal8 Computational Ground fingerprint;
- \(I_{\mathrm{compiler}}\): the E-CPU/VGI source implementation fingerprint;
- \(D_{\mathrm{task}}\): canonical typed TaskSpec digest.

The compiled plan contains the validated TaskSpec, immutable VGI Program IR, Ground and implementation fingerprints, task and Program fingerprints, and a plan digest binding all of them. The plan digest can be supplied as interpretation_fingerprint in a generic session transition contract. The session context then binds that plan to the exact state revision and input.

The plan cache is a bounded 128-entry LRU. A cache miss compiles the TaskSpec; later requests with the same three identities reuse the same immutable Program. Every execution still creates a fresh VirtualGroundInterpreter and a fresh mutable SignalStateMachine. Signal memory, registers, program counter, trace, output list, undo history, and checkpoint are never cached or shared between requests. The cache is disposable: eviction or explicit clearing changes performance, not meaning or authority.

The VGI receipt records the task fingerprint, compiled Program fingerprint, and compiled-plan digest. Those fields make it possible to observe which interpretation was reused without placing cache hit counters, machine-local timing, or process details into the deterministic execution receipt.

## 5. Proof boundaries

M4 establishes a compositional interface and tests its local invariants. It does not claim:

- automatic discovery of semantics from arbitrary bytes;
- a universal compiler or interpreter for all computational domains;
- a proof that a backend's declared purity is truthful;
- atomic commitment of external side effects;
- hardware/runtime attestation from source hashes;
- safe interchangeability of arbitrary Ground, backend, or state-schema versions;
- that compiled-plan caching improves every workload (single-use tasks may see no benefit).

For any domain, the producer must supply a versioned Ground/state schema and a backend contract. E-CPU binds these descriptions to the current session and controls the durable state transition. The domain implementation remains responsible for meaning, while the host and quorum lineage remain responsible for admission, execution authority, and current-state continuity.

During M7 migration, the backend fingerprint of the source checkpoint and
the target execution backend fingerprint can differ. The transition context
now carries both: historical provenance remains attached to the state being
interpreted, while the execution contract identifies the local backend that
will produce the candidate successor. The target compatibility predicate
must approve that source-to-target relationship on reads and commits until
the first target-side revision is anchored.