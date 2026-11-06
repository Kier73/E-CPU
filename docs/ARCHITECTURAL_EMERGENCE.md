# Architectural Emergence Review

## Purpose and evidence discipline

This is a living architectural review for E-CPU / MailCPU. It is not a feature checklist and it is not a claim that every possible capability has been built. Its purpose is to observe the system from multiple scales while implementation proceeds.

Every observation belongs to one of four evidence classes:

| Class | Meaning | How to report it |
|---|---|---|
| Demonstrated | Implemented and exercised by a test or reproducible run | State the exact capability and its tested boundary |
| Integrated | Existing components are connected through an executable contract | Identify the connected state, authority and replay boundaries |
| Building | The next implementation step has a concrete interface or branch, but is not merged or fully validated | Name the missing obligations |
| Hypothesis | A possible consequence of the architecture, not yet implemented or experimentally established | State a falsifiable experiment and a failure condition |

An architectural possibility can be important before it is implemented. It must not be presented as a demonstrated capability. Likewise, this document does not claim that an idea is the first of its kind in the history of computing. Such a priority claim would require a dedicated prior-art review.

## 1. Present system: what it can do

The following describes mainline after PRs #16–22. In addition to the original Structural Memory registry, the merged work now binds pinned structural references to Virtual Layer operators, exposes them through a read-only VFS provider, and uses them as content-addressed demand-page backing for virtual memory. This review records integrated boundaries, not claims of universal execution or production deployment.

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

`scripts/benchmark_structural_memory.py` compares three equivalent representations of a byte-valued modular progression: a materialized byte array, a direct `StructuralMemoryFileProvider` range, and a demand-paged VM page. It reports cold and hot sequential reads, deterministic random single-byte reads, journal-event counts and serialized journal size, plus generator/reference and VM snapshot sizes. The smoke tests assert byte equivalence and verify the cold-versus-hot journal boundary without asserting unstable wall-clock thresholds.

The implementation makes one measurable cost visible before any optimization: the current provider asks the registry for each coordinate independently, and each registry read is journaled—even on registry cache hits. Therefore a cold page of (N) bytes currently creates (N) structural-read events. The harness records this cost; it does not yet establish an end-to-end performance advantage or justify weakening provenance.

A range-oriented registry API is a candidate next step. It should only be introduced if it can reduce lock/journal overhead while retaining a receipt for every value, a range receipt binding order and content, the exact revision/context boundary, checkpoint/replay integrity, and the same refusal semantics. It is not part of the current implementation.

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