# Architectural Emergence Review

## Purpose and evidence discipline

This is a historical architectural review for E-CPU / MailCPU, originally written around the implementation state following PRs #16–22. Its evidence discipline and hypotheses remain useful, but its Sections 1–2 are not a current capability inventory and are not exhaustive of later work in persistent sessions, authenticated forwarding, subprocess recovery, or VGI host transit. For the current implementation state, use [README.md](../README.md), [SYSTEM_MATHEMATICAL_MAP.md](SYSTEM_MATHEMATICAL_MAP.md), [COMPUTATIONAL_FABRIC.md](COMPUTATIONAL_FABRIC.md), and [VGI_PERSISTENT_SESSIONS_AND_TRANSIT.md](VGI_PERSISTENT_SESSIONS_AND_TRANSIT.md), then verify each claim against the modules and tests named there. This review is not a feature checklist and does not claim that every possible capability has been built.

Every observation belongs to one of four evidence classes:

| Class | Meaning | How to report it |
|---|---|---|
| Demonstrated | Implemented and exercised by a test or reproducible run | State the exact capability and its tested boundary |
| Integrated | Existing components are connected through an executable contract | Identify the connected state, authority and replay boundaries |
| Building | The next implementation step has a concrete interface or branch, but is not merged or fully validated | Name the missing obligations |
| Hypothesis | A possible consequence of the architecture, not yet implemented or experimentally established | State a falsifiable experiment and a failure condition |

An architectural possibility can be important before it is implemented. It must not be presented as a demonstrated capability. Likewise, this document does not claim that an idea is the first of its kind in the history of computing. Such a priority claim would require a dedicated prior-art review.

The cross-subsystem mathematical inventory is maintained in
[SYSTEM_MATHEMATICAL_MAP.md](SYSTEM_MATHEMATICAL_MAP.md). Read it as a map of
composable models and evidence boundaries, not as a claim that all subsystems
share one graph, clock, or solver.

## 1. Historical system snapshot: post-PR #16–22

The following records the historical mainline as it stood after PRs #16–22; later additions are covered only where explicitly noted. In addition to the original Structural Memory registry, the merged work now binds pinned structural references to Virtual Layer operators, exposes them through a read-only VFS provider, and uses them as content-addressed demand-page backing for virtual memory. This review records integrated boundaries, not claims of universal execution or production deployment.

### 1.1 Execute a deterministic machine over a communication model

- MailCPU has a defined deterministic transition algebra and reference and message-backed execution implementations.
- Instructions, registers, mailboxes, process state, kernel requests, outputs, and semantic traces have explicit state projections.
- The scheduler coordinates multiple programs, FIFO messages, blocking and wake-up, and deterministic logical-time progression.
- The virtual OS supplies files, processes, private and shared memory, descriptors, devices, syscalls, services, and owned network abstractions.
- Existing conformance tests compare observable results and traces across the admitted execution implementations.

Evidence: README.md; docs/ARCHITECTURE.md; tests/test_conformance.py; tests/test_checkpoint.py.

### 1.2 Mediate effects and preserve causal identity

- The hypervisor separates model or classifier proposals from authority. Kernel capabilities determine whether an effect is permitted.
- Arbitration uses stable request identities, payload fingerprints, journal receipts, and checkpointed ledgers.
- Navigation admission replays plans against trusted live context and derives rights from the kernel. Navigation execution revalidates the grant and delegates a bounded commit to the state-owning backend.
- Reliable channels, durable mailboxes, replicated mailboxes, and recovery coordinators preserve protocol identity and distinguish transport retries from semantic operation identity.

Evidence: docs/ARCHITECTURE.md; docs/NAVIGATION_ADMISSION.md; docs/NAVIGATION_EXECUTION.md; docs/TRANSIT_PATH_STATE.md.

### 1.3 Navigate structured state rather than only enumerate transitions

- Contextual process navigation searches declared transition systems and emits replayable path witnesses.
- Abstract navigation reasons over supported integer-affine intervals and constraints; causal dependency and bisimulation checks remain separate evidence classes.
- The unified coordinator combines the applicable evidence without turning abstract possibility into a concrete execution witness.
- The algebraic law certifier can recover and navigate admitted recurrence families, including integer progression, LCG, GF(2), and finite-orbit structures. Guarded navigation enforces prefix horizons.
- The native vCPU context backend can edit a real suspended task's PC and integer registers at an instruction safepoint after revalidation and checkpointed commit. This is context relocation, not instruction retirement or a semantics-preserving macro-transition.

Evidence: docs/FORMAL_NAVIGATION.md; docs/NAVIGATION_COORDINATOR.md; docs/NATIVE_VCPU_CONTEXT.md; mailcpu/law_certifier.py; tests/test_native_cpu.py.

### 1.4 Execute bounded work inside receiver-side communication paths

- Transit compute has a receiver-side worker, reliable input and result channels, receiver-local capability checks, and semantic result/replay ledgers.
- The main-line operation router includes scalar MailCPU arithmetic, a bounded SIMT reference interpreter, and private process-memory transfer.
- The SIMT implementation is a deterministic CPU reference model for lane masks, divergence, reconvergence, and a conservative barrier rule. It is not a GPU driver or evidence of GPU acceleration.
- Process-restart tests exercise the logical receiver state over loopback and restore the semantic operation ledger. They do not establish deployment across separate physical hosts or atomicity with arbitrary external side effects.

Evidence: docs/TRANSIT_PATH_STATE.md; tests/test_transit_compute.py; tests/test_external_connections.py; tests/test_seed_commit_process_recovery.py.

### 1.5 Store generative descriptions of state families

Main-line Structural Memory E0 provides:

- immutable, digest-addressed specifications and evidence certificates;
- a closed generator registry over four deterministic law families;
- witness-grounded and prefix-grounded verification classes;
- exact context-bound reads and evidence-bearing receipts;
- staged proposals and host-authorized revision admission;
- revision lineage and an exact-key read cache;
- registry checkpointing for staged proposals, admitted history, active heads, and read receipts;
- proposal, admission, and read journal events tied to the exact VM checkpoint journal cut;
- restore-time witness replay, lineage checks, read-receipt recomputation, and trusted host-policy rebinding.

A witness-grounded certificate means agreement with the finite witness set. It does not prove an infinite law. A prefix-grounded certificate refuses reads at or beyond its observed first-bad coordinate. Host admission policy remains executable configuration and is never restored from checkpoint data.

Evidence: docs/STRUCTURAL_MEMORY.md; tests/test_structural_memory.py; tests/test_checkpoint.py; docs/INVARIANTS.md (S-1 through S-13).

## 2. Integrated capabilities added after the original Structural Memory registry

The following integrations are on mainline, not merely planned branches. Their portable descriptions remain separate from executable authority: a sender can name a pinned structural object, but the receiver must resolve it against its own admitted registry and local policy.

### 2.1 Virtual Layer / Structural Memory operator binding

Workload schema v2 adds operator-scoped references that pin memory identity, revision, context, coordinate, specification digest, and certificate digest. The address crosses the workload channel; generator code and registry state remain receiver-local.

The receiver validates the workload's admitted Virtual Ground, obtains hypervisor authorization for the operator, and only then lets the local handler resolve the reference under a separate receiver-local `read` capability on `/structural-memory/read`. The operator receives the original input plus resolved integer values and full read receipts. Its effect binds the resolved-input digest and receipts, allowing semantic replay without re-reading the generator.

This composes portable intent, admitted generative state, receiver-side authorization, and semantic replay. It does not distribute registry contents, make operator handlers portable, or grant the sender the receiver's local authority.

### 2.2 Structural Memory as a VFS provider

A bounded read-only file can expose an exact interval of an admitted revision. Its descriptor pins memory identity, revision, context, coordinate start, byte size, specification digest, and certificate digest. A byte offset maps to one generator coordinate; the provider rejects non-byte values and returns an aggregate range receipt linked to the ordered coordinate receipts.

The provider descriptor is checkpointed without its registry pointer. Restore reconstructs the registry and rebinds the provider to that local registry. The VFS permission and open checks remain the normal authorization boundary.

### 2.3 Structural Memory as VM demand-page backing

PR #22 connects the same byte-range reference to the existing `PageBacking` interface:

- A page digest is registered against exactly one immutable, pinned file reference. Page geometry is constrained to a power of two no larger than 65,536 bytes.
- A reserved virtual page remains non-resident until first access. The backing reconstructs the referenced bytes and validates both the exact length and SHA-256 page identity before the VM publishes the resident mapping.
- Multi-page accesses resolve all external pages before consuming any reservation, so failure on a later page does not leave an earlier reservation partially materialized.
- Writes diverge through the VM's existing copy-on-write mechanism; the structural source remains immutable.
- Snapshots store symbolic structural references and local non-structural page bytes, not live registry pointers or callbacks. Restore requires trusted host code to rebind the structural backing.

This is an integrated demand-page path, not a claim that every VM page or every foreign memory source is generative. It also does not make the generator itself resident in the virtual address space: the first fault still reconstructs and validates a full page.

### 2.4 First empirical comparison harness

`scripts/benchmark_structural_memory.py` compares three equivalent representations of a byte-valued modular progression: a materialized byte array, a direct `StructuralMemoryFileProvider` range, and a demand-paged VM page. It reports cold and hot sequential reads, deterministic random single-byte reads, journal-event counts and serialized journal size, plus generator/reference and `VirtualMemory.snapshot()` sizes. The VM snapshot measurement is only that memory-state projection; it excludes the enclosing `HeadlessOS` checkpoint, Structural Memory registry, journal, and host backing rebind state. The smoke tests assert byte equivalence and verify the cold-versus-hot journal boundary without asserting unstable wall-clock thresholds.

The implementation makes one measurable cost visible before any optimization: the current provider asks the registry for each coordinate independently, and each registry read is journaled—even on registry cache hits. Therefore a cold page of (N) bytes currently creates (N) structural-read events. The harness records this cost; it does not yet establish an end-to-end performance advantage or justify weakening provenance.

A range-oriented registry API is a candidate next step. It should only be introduced if it can reduce lock/journal overhead while retaining a receipt for every value, a range receipt binding order and content, the exact revision/context boundary, checkpoint/replay integrity, and the same refusal semantics. It is not part of the current implementation.

### 2.5 First semantic translation contract

`mailcpu/semantic_translation.py` introduces a shared declarative edge
between representations. It pins source and target type/schema/content
identities, a content-addressed mapping definition, an observation projection
and its definition digest, exact context, precondition and invariant digests,
resource ceilings, declared receiver-side capability requirements, and
effect/replay classes.

The first conformance pairing runs the same validated MailCPU program
through `ReferenceInterpreter` and `QueueInterpreter`; the existing
`canonical_result` projection compares status, state, trace, and outputs.
The contract also pins a content-addressed mapping definition, so changing the
claimed adapter/rule changes contract identity even when both endpoint
representations remain the same.

A second pairing now exercises a real representation change: an admitted
Structural Memory specification is resolved into coordinate values and then
materialized as a demand-paged VM page through `StructuralMemoryPageBacking`.
The paired observation compares exact bytes, the page digest, and ordered
coordinate receipt IDs from the two paths. This verifies one pinned page and
context while preserving structural provenance; it does not extend the finite
witness-grounded certificate into an infinite proof.

This remains a declarative contract plus paired checker, not a general
translation runtime. It does not execute arbitrary translators, verify that
the caller applied the declared projection correctly, prove equivalence for
untested inputs, infer preconditions, or authorize effects. Capability
declarations remain non-authoritative labels until a receiving host checks
live policy. New contract fields should be added only when an integration
requires them.


### 2.6 Semantic evidence travels with the Transit effect

The translation contract now reaches the receiver-side operation path. For each
newly executed allowed Transit handler result, `TransitComputeWorker` binds
the receiver-authorized event, exact operation identity, selected backend
manifest, hypervisor decision receipt, and raw handler effect into a
`TransitTranslationEvidence` record. The paired comparison checks that the
handler effect survives canonical JSON normalization unchanged.

The record is embedded in the effect before the hypervisor commits it. The
execution ledger therefore stores the contract and comparison alongside the
effect; semantic duplicates replay that same record without re-entering the
backend. The existing quiescent worker checkpoint carries the execution
ledger, so restored workers can return and validate the same evidence under a
new transport frame.

This closes an important provenance gap between a portable request and a
receiver-produced result. It is not a proof that the handler computed the
correct answer, a signed remote attestation, or a transaction across arbitrary
external side effects. Those require independent operation-specific
oracles/invariants, a trusted evidence-signing model, and stronger external
effect recovery respectively.


## 2.7 Independent oracle checks become part of operation cost

The receiver-side effect path now performs an independent semantic check for
pure CPU arithmetic and Structural Memory coordinate reads before commit.
The CPU oracle interprets the admitted arithmetic subset through a separate
transport-free transition loop. The Structural Memory oracle derives the
requested value from an exact admitted specification and certificate without
calling the production generator adapter. Each comparison is bound to the
authorized request and records the expected/observed projection plus
deterministic oracle work units and a hard ceiling.

This turns verification into explicit operation structure rather than
decorative metadata: the path can see which oracle ran, which case was checked,
what observation was compared, and what bounded work was consumed. A failure
to agree or stay within the bound prevents the backend effect from entering
the hypervisor execution ledger. A semantic duplicate then reuses the stored
effect and evidence rather than paying the oracle cost again.

The accounting is deliberately not called physical latency or energy. A CPU
instruction count, an affine-map composition, and a GF(2) matrix row operation
are different logical cost units. Converting them into comparable time,
bandwidth, or energy estimates will require measurement on concrete execution
substrates. The current oracle still checks one finite case; it does not turn
witness-grounded laws into universal proofs or attest against a malicious
receiver.



## 2.8 Evidence-indexed representation routing

The next navigation layer now has a concrete implementation. The existing
contextual navigator explores the state space of one process description;
the evidence-path resolver instead connects exact representation identities
through successful translation contracts. It retains the evidence and
cost vector for each edge, checks exact context and prerequisite digests,
reads live receiver capabilities, and searches a bounded graph for a feasible
route.

The route objective is an explicit lexicographic order over named metrics.
Latency, energy, work, and data movement remain separate dimensions with
separate units; ceilings filter paths before selection. Nondominated partial
routes are retained so a locally attractive path cannot erase another path
that is feasible under a global budget. The output is a digest-bound,
non-authoritative proposal, not a permission to execute the steps.

The current catalogue stores finite-case evidence and locally declared cost
vectors. It does not yet replicate catalogues between hosts, calibrate cost
metrics automatically, or dispatch a whole route. Those are separate
experiments: the next step is to connect an admitted route edge to a concrete
receiver backend and have each edge pass through its own hypervisor admission.


## 2.9 Authenticated computational fabric discovery and multi-hop planning

The semantic-address layers now have a first network-level counterpart. A peer can publish a bounded snapshot of its own portable logical-host/operator advertisements and directed outgoing links. Configured peers exchange these snapshots over the repository's existing mutual-TLS framed transport and reliable-channel protocol. The local directory requires peer identity, TLS DNS identity, snapshot endpoint, monotonic revision, and locally measured lease validity to agree before an advertisement enters the active view.

A bounded network resolver then selects a cost-feasible peer path to a host whose advertised operator contract, computational Ground, program policy, placement, substrate, observation kind, state capability, resource bounds, and implementation identity fit the address. The path witness binds the active directory/topology digests and decomposes network and host cost. A regression test demonstrates why the planner keeps alternatives indexed by hop count: the globally cheapest prefix can be too long even though a slightly more costly shorter route is feasible.

This connects remote host discovery to multi-hop cost-aware planning. It deliberately stops before forwarding or execution. Portable advertisements do not carry PIDs, handlers, runtime objects, or capabilities; leases are receiver-local; the peer route is non-authoritative. The route must still terminate at the receiver-local semantic resolver and the existing Virtual Layer/Hypervisor execution boundary.

The repository's other graphs remain distinct and composable: E-GPU's internal operational graph routes methods inside one host; EvidencePathResolver connects representations under evidence and observation contracts; NavigableComputationDAG governs dependencies; TransitOrbitScheduler selects ready path quanta; Structural Memory supplies revision-pinned state; TransitPathBinding can later inform empirical path-cost calibration; and RecoveryLineage can anchor future persistent directory/topology checkpoints. The new fabric graph does not duplicate any of those roles.

See [COMPUTATIONAL_FABRIC.md](COMPUTATIONAL_FABRIC.md) for the full integration map and proof boundary.

## 3. Novel-to-this-architecture possibilities

This section records research opportunities created by the combination of integrated and planned primitives. These are not claims of global historical priority. Related ideas may exist in symbolic execution, program synthesis, proof-carrying computation, procedural generation, distributed systems, databases, and other fields. The question is what a working combination inside E-CPU enables that its current components do not provide separately.

### 3.1 Generative memory as an addressable state resource

Conventional memory interfaces usually return stored bytes or values. A structural memory can instead resolve a typed coordinate through a verified generator and return both the value and the evidence describing why that value is admitted.

Potential consequence: a large state family can be represented by a compact law, boundary, and verification record rather than materializing every member. This is especially useful for periodic or algebraically navigable state spaces.

Experiment: run `python scripts/benchmark_structural_memory.py --sizes 256,4096,16384 --repeats 5 --pretty` on the same host and Python build. The harness compares materialized storage with cold/hot file-provider reads and VM demand-page faults, and records random-access cost, journal growth, and serialized descriptors/snapshots. Extend the workload with more generator families and larger horizons before generalizing the result. The current event model predicts one registry journal event per coordinate on a cold page; the benchmark tests that prediction.

Failure condition: the generator description is not materially smaller or cheaper than the stored representation for the intended workload, or its evidence is too weak to meet the use case.

### 3.2 A request path that carries its own operational memory

Transit paths already carry causal state: request identity, receiver-side authority, effect identity, result publication, and acknowledgement. Structural memory adds a way to represent deterministic state families and navigate them under typed context.

Potential consequence: a path could host a bounded structural operator, not merely transport a command. A request could be interpreted in the path's current context, resolve a structural state, pass local policy, and return a result whose causal and structural provenance are linked.

Experiment: define one pure structural-read operation as a transit backend. Bind its request to memory ID, revision, context digest, and coordinate. Exercise duplicate frames, new transport sequences for an already-committed semantic read, receiver restart, policy denial, and stale revision.

Failure condition: the path cannot reproduce the same receipt after restart, can read under an unbound context, or accidentally conflates transport identity with structural operation identity.

### 3.3 Navigation as a first-class system operation

E-CPU already has concrete path search, abstract reachability, guarded algebraic jumps, hypervisor admission, and native context editing. These are presently distinct layers and evidence contracts.

Potential consequence: the machine may eventually answer not only how to execute the next transition, but which verified route or state coordinate reaches a required condition with the lowest declared cost. The route could then be admitted and applied by a state-owning backend.

Experiment: connect one structural-memory navigator to the existing coordinator and admission path. Compare direct generator evaluation, explicit stepping, and verified jump-ahead while preserving state and evidence identities.

Failure condition: a proposed jump changes observable state, trace, resource, or side-effect semantics, or its verification cost dominates the saved work.

### 3.4 Context becomes a boundary transformation rather than a new program

**Demonstrated:** E0.3 provides immutable context-only revisions. It copies the active generator specification and changes only canonical context, revision number, and parent digest. A new supplied witness set must replay against the unchanged generator before host admission. Explicit revision-pinned reads preserve access to older contexts after a newer one becomes active, including after HeadlessOS checkpoint restore.

**Integrated:** Virtual Layer workload schema v2 carries an operator-scoped structural reference. The receiving runtime resolves it against its local admitted registry under receiver-local read authority, and the operator effect retains resolved-input provenance for semantic replay. The address, rather than generator code or a materialized state table, crosses the workload boundary.

Potential consequence: one compact deterministic law can be rebound to multiple exact boundary instances and queried through different communication paths without transmitting a materialized state table. Each boundary remains independently addressable and evidence-bearing.

Experiment: use the same modular progression through two tenant contexts, send requests over two receiver paths with different read capabilities, and compare generator identity, values, receipts, stale-context refusal, replay, and checkpoint restore. Measure transport and verification cost against direct local reads and explicit stepping.

Failure condition: a context change mutates generator-defining fields; a mismatching witness or stale context is admitted; one path reads a revision outside its local authority; a retry repeats the generator operation; or the restored path cannot reproduce the exact receipt.

Boundary: these integrations do not infer generator parameters from context fields, authenticate the external provenance of supplied witnesses, distribute registry state between hosts, or provide distributed consensus.

### 3.5 Heterogeneous structural composition

The system already has scalar, SIMT-reference, memory-transfer, temporal, navigation, and recurrence representations. They do not yet share one general composition algebra.

Potential consequence: a structural object could compose operators across coordinate families—for example, an orbit generator feeding a lane mapping, or a memory provider exposing a deterministic page family to a CPU or SIMT backend.

Experiment: start with a pure product or composition of two finite generators. Specify coordinate mapping, ordering, ownership, clock domains, resource bounds, error propagation, and one joint certificate. Compare the composed result against a reference stepper.

Failure condition: composition drops provenance, changes ordering, combines incompatible clocks without a declared map, or cannot produce a replayable correspondence witness.

### 3.6 An internally maintained model of the machine

The hypervisor can already stage and witness candidate policy revisions. The structural-memory registry now has immutable version identities and explicit host admission. Native and transit backends expose typed state boundaries.

Potential consequence: the machine could maintain structural descriptions of its own processes, pages, operators, devices, and communication paths. A model could propose a more useful description or route; deterministic verification and host policy would decide whether it becomes active.

Experiment: have a proposer derive a description from a bounded, read-only trace of one subsystem. Run it in shadow against independent holdouts and the reference subsystem. Do not give the proposer write authority.

Failure condition: the model can alter the system it is describing, its description cannot predict unseen states within its declared envelope, or a failed proposal damages the active version.

### 3.7 Attention as a budget for selecting paths through state space

The TSQ concept suggests that attention could be represented as a finite allocation of search, verification, and navigation effort rather than as an untyped instruction to focus.

Potential consequence: attention could choose which coordinates, candidate laws, or structural compositions deserve exploration, while deterministic checks preserve correctness. This would make adaptive search steerable without letting model confidence substitute for evidence.

Experiment: define an attention budget with explicit units—for example, candidate evaluations, witness queries, or cost-weighted state-space expansions. Compare learned or heuristic allocation against uniform search while keeping the same deterministic verifier.

Failure condition: attention only changes scheduling labels without improving useful coverage per unit cost, or it permits lower verification quality to be mistaken for higher confidence.

### 3.8 A complete Structural Memory-to-CPU navigation path

A focused integration test composes the receiver-side Structural Memory Transit
read, pure CPU Transit execution, semantic translation contracts, independent
operation oracles, and evidence-indexed route resolution.

One admitted integer recurrence supplies a coordinate value to a second CPU
request. The route has three exact representation edges: the committed
Structural Memory read and its independent oracle; a paired, case-specific
receipt-to-CPU-request handoff; and the committed CPU result with its
independent oracle. Because the read and CPU request have distinct exact
Transit contexts, the route request explicitly binds both edge-local context
digests rather than rewriting either operation's identity. The bridge edge
checks the one-case value handoff; accepted context membership itself is not a
claim of general context equivalence.

Before the CPU request is submitted, a two-edge preflight route is
resolved to the exact receiver-authorized CPU-request representation. The
request is sent only after the proposal is found; the Transit worker still
performs independent live authorization and hypervisor execution. Once the
CPU result is committed, a third edge is appended and the complete route is
resolved. Both resolutions satisfy live capabilities, explicit context
scopes, and aggregate resource ceilings. A route with only the primary CPU
context is blocked.

The test also checks a semantic replay under a new transport frame, a stable
catalogue snapshot digest, negative controls for context mismatch, translation
mismatch and missing authority, and the kernel journal chain. The route remains
a non-authoritative proposal and the two operations remain independently
authorized.

A subsequent recovery experiment adds an integrity-bound envelope spanning
the receiver worker checkpoint, requester-side reliable cursors, evidence
catalogue, exact route query/result, and retry event. Restore uses fresh TCP
transports, rebinds the trusted backend manifest, reauthorizes the retry event,
and reruns route resolution against restored live capabilities. Only after
the saved route is reproduced can the requester retransmit the CPU event;
the hypervisor ledger must replay the original effect without invoking the
replacement CPU backend.

See [NAVIGABLE_COMPUTATION_EXPERIMENT.md](NAVIGABLE_COMPUTATION_EXPERIMENT.md)
for the initial composition and
[NAVIGABLE_COMPUTATION_RECOVERY.md](NAVIGABLE_COMPUTATION_RECOVERY.md)
for the combined recovery contract and proof boundaries.

## 4. Questions to ask at every milestone

1. What can now be done that was not previously executable?
2. What can be done only because two or more existing abstractions are now connected?
3. What remains a proposal, simulation, reference model, or hypothesis rather than a physical or production capability?
4. Which new state, authority, provenance, clock, resource, and recovery obligations appear because of this connection?
5. What smallest experiment could falsify the proposed emergent capability?
6. Does the new representation outperform a transparent baseline in storage, execution work, adaptability, energy, latency, or reliability after including description, verification, navigation, execution, transport, and recovery costs?

## 5. Development rule

Do not optimize only for instruction throughput or similarity to a conventional CPU. Evaluate the machine as a substrate for describing, navigating, verifying, and composing state transformations.

At the same time, do not reward novelty language by itself. A proposed new capability must eventually have a typed contract, an executable construction, a reference comparison, a refusal boundary, an evidence record, and a recovery story.

The working principle is:

> Preserve the deterministic reference machine, let structural descriptions propose shorter or more useful routes through its state space, and admit new representations only when their correspondence and authority boundaries survive independent tests.

That principle leaves room for genuinely new forms of operation without treating speculation as implementation.