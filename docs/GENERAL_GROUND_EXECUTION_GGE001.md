# GGE-001 — Executable Grounds for general computation

**Status:** cross-repository architectural synthesis and implementation plan; **not** a claim of universal native execution or a newly verified runtime. Inspected E-CPU main at 6fd416facdb2aefd6fc7d66a06b014e3d31b5a52, In-Formation-Space main at c9716242725be65937fda1dd7b6cb778ca1def91, VGI main at e6e1900782aeede18a4de9046511bbba234dbc6e, E-CPU-Virtual-Processor main at 60cd5cc2e0f27fef0d06170af41cb7cb372e3b60; VP-002/003 were inspected as **open draft branches**, not mainline.

## 1. Objective: executable computational structures, not an emulator collection

E-CPU should accept any **effectively described, computable** structure with specified observation semantics, and seek a qualifying realization through its own Ground, path, and observer architecture. Model size, tensor shape, instruction-set family, and host topology must not become arbitrary limits of the *semantic address space*. Finite execution and verification work are allocated, selected and measured separately for each query.

The identity of a computation belongs to its Ground, description, context, intention, state, and evidence. Neither a Python process, a continuously running server, a CUDA device, a pretrained inference package, nor a particular communication channel is its definition. After bootstrap the environment should be continuously addressable even if every prior *execution process* is gone. Qualified observer-hosts and paths may be discovered, composed, configured, or re-formed when permitted.

This is a research programme to replace **the requirement for a dedicated conventional physical machine** as the computational identity and runtime locus. It is not evidence that a result can be observed without information or a physical causal realization, nor that every effective computation has a direct or cheap closed form. These are experimental questions; missing methods are **in development**.

The object of an admission decision is not “can this CPU run this model?” It is:

> Given a typed description, Ground, intention, and observation contract, can E-CPU derive or assemble a permitted realization, demonstrate its transition relation, and reconstruct a valid result under the same computational identity?

## 2. A compositional Ground contract

A proposed general Ground is a versioned record:

    G = (L, D, S, T, P, C, E, A, V)

where:

- **L** is a typed language with representation and interpretation rules, including effects and precision.
- **D** is immutable source/data identity: architecture, parameters, code, tokenizer, tensor pages, hashes and provenance.
- **S** is state: symbolic, materialized, deferred, or reconstructible, with causal and logical-time coordinates.
- **T** is an admitted transition relation, including branches, numerical operators, communications, and state updates.
- **P** is the observable projection(s) requested by an intention; observation need not enumerate every transition.
- **C** is composition: port contracts, data dependencies, representation translations, scheduling frontiers and Ground mappings.
- **E** is evidence: exact witnesses, reference comparisons, proof certificates, numerical bounds, and unknown/partial claims.
- **A** is receiver-owned capability, identity, freshness, locality and effect authorization.
- **V** is versioned verification and recovery: receipt contracts, replay policy, content lineage, and independently protected authority where required.

Do not create a second Hypervisor, interpreter, journal, page store, quorum, or source-of-truth. This is a **composition and compilation contract** above existing MailCPU objects, observer receipts, VirtualLayerRuntime, structural memory and recovery lineage.

A first version of the Ground IR needs only a small algebra of typed nodes: constant/reference, symbolic function, tensor primitive, conditional/branch, state transition, observation/projection, dataflow composition, and authenticated external effect. These are descriptions, not arbitrary Python callbacks supplied by the requester.

Each node must bind representation identity, input/output schemas, operator semantics, pure/stateful/effect classification, precision/equality policy, dependency identities, temporal coordinate, and eligible realization evidence. A node may remain unresolved until qualified; it must never be silently treated as executed.

### Execution and observation are separate proof obligations

For intention I and observation projection P, an execution path R is admissible only if:

    Authorize(G, I, R)
    and BindSource(G, D, R)
    and VerifiedTransition(G, I, R, evidence)
    and ValidProjection(G, P, result)
    and CommittedRecoveryLineage(G, I, result)

A result receipt must state which obligations were *actually* checked. For pure mathematical transformations, a direct symbolic navigator may realize a result without an intermediate materialized trajectory. A numeric or effectful path must expose its actual evaluated work and side effects.

Result semantics must not be confused with transport ACK, worker self-attestation, checksum validity, successful graph construction, or a generated model's claimed equivalence.

## 3. Ground formation rather than host-first execution

For any new computational structure, E-CPU should attempt the following, preserving refusal and evidence at every stage.

1. **Recognize representation:** inspect source metadata and byte identity; construct a typed object and Ground candidate, not an inferred truth claim.
2. **Construct the semantic relation:** compile a known family contract, exact algebra or authenticated behavioral observation into transitions, state and output projections.
3. **Normalize and factor:** identify pure subgraphs, parameter-backed tensor cuts, reversible/affine components, dependency frontiers and stateful/effectful boundaries. Preserve exact semantics or declared numeric tolerance.
4. **Choose a navigation strategy:** exact law/inverse, structural-memory projection, compositional symbolic evaluation, cached content-addressed result, staged numerical evaluation, or a measured admissible substrate/path transition. No algorithm is allowed to claim a jump it cannot justify.
5. **Form realization:** bind permitted observer-host ports, finite reference interpreters, E-GPU/SIMT loci, receiver-resident parameter shards, or authenticated path operations. Authority remains with the receiver.
6. **Verify independent observations:** compare to mathematical invariants, a separately implemented oracle, exact coefficient conservation, reference numerics under stated tolerance, or third-party proof receipts as appropriate.
7. **Retain a navigable identity:** persist state, event frontier, proof references, operation identities, and recovery high water; restore on a different realization host and refuse stale publication.
8. **Improve representation:** measure the actual cost of host work, memory, wire bytes, latency, energy when observable, and verification. Promote newly established laws into Ground adapters rather than permanently invoking an opaque conventional backend.

A qualified conventional runtime is useful as an **oracle or temporary realizer**, not the eventual definition of execution. A passive path is a transport relation until a separate observed transform is established; labeling it compute is not an observation.

## 4. Ground family for every language-model requirement

The matrix maps the eleven previously identified LLM requirements onto new or existing Ground families. “Implemented foundation” means a related component exists, **not** that complete model inference is implemented on E-CPU main.

| Requirement | Proposed executable Ground / observable | Reuse first | Next missing executable contract |
| --- | --- | --- | --- |
| 1. Model identity and artifact | **ModelArtifactGround:** architecture, parameter and tokenizer manifests, revisions, trusted complete byte identity | ComputationalObjectStore; IFS HFR/NSD; VP-002 tensor addresses | Verified lazy page/header binding to exact model semantics, independent of model size |
| 2. Tokenization | **TokenCodeGround:** normalization, vocabulary, merges, special tokens, encode/decode determinism | Computational objects and typed translation; VP-003 tokenizer boundary | Native, source-pinned tokenizer operator and inverse/roundtrip observation receipts |
| 3. Tensor representation | **TensorGround:** shapes, layouts, dtypes, strides, quantization, slices, content addresses | M1 byte pages; IFS tensor-cut typed digests; VP-003 lazy Safetensors/BF16 | Bounded slice navigation, checked quantization and floating-point semantics, streaming manifests |
| 4. Neural computation graph | **OperatorGraphGround:** typed ports, dependencies, symbolic widths, layer schema | E-CPU neural_graph_bridge; NavigableComputationDAG; VGI topology obligations | Compositional graph IR not fixed to GPT-2 nor bounded by entire model node count; hierarchical and lazy frontier lowering |
| 5. Numerical operator algebra | **NumericalGround:** matmul, norm, softmax, RoPE, attention, SwiGLU, reductions, MoE routing | E-GPU/SIMT; IFS TCR-003 real numerical cuts; VP-003 sparse expert forward | Native numerical kernels and tolerances for full attention/transformer paths, with separate exact reference oracles |
| 6. Neural execution engine | **ExecutionGround:** operator admission, state/readiness, typed result, costs, receipts | VirtualLayerRuntime, Hypervisor, ComputationalExecutionAdmissionCoordinator, E-GPU | End-to-end per-layer dataflow execution and result commit; remove reliance on one model-specific Python handler |
| 7. Attention / KV state | **InferenceMemoryGround:** causal position, K/V pages, invalidation, eviction, memory version and ownership | StructuralMemoryPageBacking; RemotePageStore; checkpoint and temporal contracts | Reconstructible KV page identities and cross-host equivalence with partial replay |
| 8. Autoregressive generation | **GenerationGround:** prefill/decode transition, logits, token-selection distribution, RNG, stopping rules | State-space navigation; VP-003 query gateway; causal/event identity | Persistent token-position Ground with deterministic/random policy evidence, cached prefix composition and exact retry |
| 9. Admission and authority | **AuthorityGround:** operator rights, Ground provenance, precision/observation policy | SystemSeed, VirtualGroundRef, Hypervisor, VGI ProofGround | Receipts binding numerical result to exact operator, source model, data, permission and proof status |
| 10. Scheduling and communication | **PlacementGround:** semantic DAG fronts, partition/expert placement, transport and lease histories | TransitOrbitScheduler, federated directory, mTLS/ReliableChannel, IFS TCR-002/003 | Warm resident-shard routing, multi-host partition execution, freshness and fencing when replacement hosts race |
| 11. Persistence and verification | **LineageGround:** model/session identities, stable cursors, rollback refusal, signed evidence and independent checking | RecoveryLineageCoordinator/Service; IFS route-epoch SQLite; VGI exact/proof evidence; VP-001 journal | Recover real model/KV state after hard loss under independent authority, refuse both stale commit and semantic re-execution |

Each family should provide: a canonical type/schema, source and Ground identities, an admission predicate, a transition/observation law, realizers, a verifier, portable receipts, recovery tests, and one named adversarial counterexample.

The model interface must expose **query / observe / resume** under one stable logical processor identity. No architectural cap of 30B, 235B, or any other model size belongs in that interface. Finite requests can instead expose *resource budgets and current qualified capacity*.

## 5. Ground closure: the general case beyond language models

The same compiler must support arbitrary well-described structures, not only neural operators.

| General structure | Needed algebra | First realization / verifier |
| --- | --- | --- |
| Integer, Boolean, finite-field logic | Arithmetic, predicates, exact transitions | Existing MailCPU instructions; VGI Signal8 and exact finite algebra |
| Functional and imperative programs | Lexical scope, typed values, control flow, mutation, exceptions | MailCPU interpreter / HeadlessOS transitions; bisimulation or trace-level conformance |
| Graphs, recursion and dependency networks | Dynamic DAGs, guarded recursion, conditional readiness | NavigableComputationDAG frontiers and checkpoint restoration |
| Numerical computation | Dtypes, reductions, matrix and tensor operations, precision policy | IFS native tensor-cut; bounded E-GPU; independent reference numerical checks |
| Stored and generative information | Content pages, structural generators, coordinate transforms | ComputationalObjectStore and StructuralMemoryRegistry |
| Stateful asynchronous systems | Message delivery, causality, timers, ownership and external effect classification | ReliableChannel, temporal frames, Hypervisor and durable checkpoints |
| Distributed operations | Identity, peers, capability, partition, transfer and fencing | mTLS fabric, recovery-lineage quorum and IFS route epochs |
| Unknown observed relation | Conservative hypothesis, probes, counterexamples, explicit unknown | SAB-002 Ground discovery; VGI partial attention and ProofGround |

**Closure criterion:** if every primitive in a structure has an admitted executable relation, composition is type-correct, state/effect boundaries remain explicit, and the requested observation has a valid verifier, E-CPU can form an executable Ground for the composite. No model-family-specific engine is required at the semantic layer.

A *universal instruction/transition substrate* is a possible fallback for effectively computable descriptions, but it does not imply a universal efficient direct navigation formula. Uncomputable relations, underspecified meanings, and absent input information cannot be declared successfully executed by fiat.

## 6. Research gates, in order

**GGE-001 — Ground representation and closure.**
Define a canonical, small Ground IR plus a compatibility adapter for existing Computational Objects, Structural Memory, Virtual Layer and observer contracts. Demonstrate three unlike structures—finite-state machine, affine law, and tensor DAG—under the same query/observation API. A novel operator is denied until its semantics and realization are admitted.

**GGE-002 — Generic lowering and dual execution.**
Lower exact finite transitions and a numerical tensor graph into native E-CPU workloads without creating a new Hypervisor. Require exact equivalence for finite algebra and independent numerical comparisons for declared float semantics. Verify that typed graph construction alone is never labeled execution.

**GGE-003 — Lazy hierarchical tensor Ground.**
Make a 235B-scale model a manifest of **addressable** parameter objects and lazily formed operation frontiers. Admit local page/slice quotas, content digests, BF16/quantized semantics, and actual bounded weight reads. Scale graph addressability without eager whole-model DAG or full weight loading.

**GGE-004 — Full neural-layer execution.**
Execute real source-pinned RMSNorm, QKV/RoPE, GQA attention, router, sparse SwiGLU and residual under the Virtual Layer; check every output against an independent reference and selected scalar or bounded-error certificates. Extend IFS TCR-003 rather than duplicate its receiver admission mechanism.

**GGE-005 — Retained inference State Ground.**
Prefill, decode at least two tokens, hard-kill the executor, restore K/V and generation state on another qualified observer-host, and confirm the same subsequent outputs under deterministic policy. Recovery evidence must be independent of the killed host and reject rollback.

**GGE-006 — Path-native tensor relation.**
Qualify a real communication-path transfer transformation by calibration, held-out tests, explicit locus ownership and bypass controls. Bind it as an alternative tensor realizer *only* when observed semantics pass; compare CPU/GPU/path costs without assigning those methods privileged native status. The draft E-CPU TENSOR-PATH-001 is candidate infrastructure, not mainline proof.

**GGE-007 — General computational closure.**
Accept an unseen structured program (with a new mixture of tensor, state and branching operators), construct its Ground, produce a queryable result, verify it, terminate the executor, and continue it through a different qualifying realization. Include refusal tests for noncommuting transforms, nondeterministic sampling, stale authority, partial input observations, and invalid numerical claims.

## 7. Evidence and cost ladder

Record distinct claims rather than a single “executed” Boolean:

- **Described:** syntactically typed structure; no execution.
- **Ground proposed:** semantic and observational hypotheses with explicit unresolved obligations.
- **Ground admitted:** versioned law and policy under a receiver; evidence scope declared.
- **Realized:** identifiable operations ran or were directly evaluated through an allowed navigator.
- **Independently checked:** exact proof, source oracle, numerical reference or a stated statistical/error test; report its coverage.
- **Recoverable:** independently reconstructed committed state/receipt under the same semantic identity.
- **Path-native:** demonstrated useful transformation occurring at the claimed communication-path locus, with controls excluding endpoint computation.

Compare each strategy by actual work performed, input/parameter bytes moved, materialized memory, logical coordinates traversed, latency, observed energy where available, and verifier cost. Reusing a reference backend does not make it a novel path-native result; a symbolic law jump is not necessarily a general model-inference shortcut.

## 8. Repository responsibilities

- **E-CPU (authoritative core):** common Ground IR, semantic translation, virtual operator and path admission, execution, state navigation, DAG composition, checkpoint lineage and authority. Do not implement an independent E-CPU clone in the virtual processor.
- **In-Formation-Space (research and independent evidence):** structural readers, tensor partitioning, semantic neural compilers, independent numerical and proof observers, real path experiments, counterexamples.
- **Virtual-Ground-Interpreter (semantic verifier):** typed Ground interpretation, observer-context equivalence and precise proof obligations; kernel certification must be obtained explicitly, not inferred.
- **E-CPU-Virtual-Processor (queryable operational surface):** user/agent query API, persistent logical processor and model sessions, Ground catalog, retrieved observation/receipt projection; use E-CPU's actual authority and realization routes.

Mainline and draft features should remain distinct. At inspection, E-CPU #154/#155 and virtual processor #1/#2 are open drafts; IFS uncertain Ground/intent branch lines are also open. Integrate proven interfaces on exact pinned commits; do not declare stacked experiments merged or hosted verification successful while jobs remain queued.

## 9. First concrete implementation decision

Begin with a **Ground-to-Observation Contract**, not another model-family-specific neural wrapper:

    describe(source) -> GroundCandidate
    admit(GroundCandidate, receiver_policy, witnesses) -> GroundRef
    query(GroundRef, intention, projection, budget) -> Result | Refusal
    verify(Result, contract, source_evidence) -> Verdict
    checkpoint(GroundRef, state, lineage) -> RecoverableRef

This is an *interface proposal*, not implemented callable code. It must lower onto existing MailCPU mechanisms and preserve all existing authorization gates. Build the smallest executable vertical slice over three genuinely different structures; then use that same interface for Qwen3 expert inference, GQA attention and autoregressive state.

**The decisive experiment:** After terminating every prior executor, can the same mathematical intention and model session be re-addressed and produce an independently checked next token through a newly qualified host, with no requirement that any one conventional processor contained the entire computational structure?

An affirmative result would advance E-CPU's central aim: **continuity and computational meaning in the Ground and paths; physical realizers replaceable, observable, and not privileged as the architecture.**
