# MailCPU Program Dataflow Compilation

## Purpose

This experiment compiles a bounded subset of native MailCPU assembly into the existing NavigableComputationDAG. It is a structural compiler, not a second VM or a remote execution engine.

The input is an exact UTF-8 assembly byte sequence (or an already validated Program) plus an initial register state. Initial values may include typed StructuralMemoryReadReceipt records. The compiler keeps the byte representation, validated instruction representation, Computational Ground, initial-state identity, dataflow graph, and terminal observation contract as distinct but linked views.

## Supported program domain

The current bounded compiler admits only:

- SET
- COPY
- ADD
- MUL
- COMPARE
- one final HALT

The program must be straight-line. BRANCH, SEND, WAIT, and SYSCALL are refused. Register names are restricted to the same bounded identifier shape used by the Transit arithmetic capsule, and all register values are strict integers.

The compiler does not remove instructions or rewrite arithmetic. Each admitted arithmetic instruction becomes one immutable DAG node. Reads bind to the latest earlier register definition, or to the exact initial value when no earlier definition exists. A later write to the same register creates a new definition; it does not overwrite the earlier node. The final-register projection points to the definition produced by the last write in program order.

The terminal HALT node depends on every preceding instruction node. This makes terminal completion a dependency barrier.

## Representation atlas

One compiled plan retains these views:

| View | Identity / content |
|---|---|
| Source bytes | SHA-256 of the exact UTF-8 assembly bytes and byte length |
| Program | Existing program_representation_ref identity |
| Initial state | Canonical register values plus complete Structural Memory read receipts |
| Computational Ground | Versioned integer-register and opcode semantics |
| Dataflow | Typed instruction nodes, register-version edges, terminal barrier, final register sources |
| Observation | Exact terminal status, PC, step count, halted/blocked flags and final registers |
| Translation | A pure, deterministic TranslationContract from the validated program to the dataflow representation |

The byte identity does not establish program meaning by itself. Meaning comes from the validated assembler output and the declared Computational Ground. The translation record binds those identities and the finite observation the compiler promises to preserve.

## Structural Memory inputs

The compiler distinguishes three materially different input classes.

**Materialized read receipt.** A caller may supply a `StructuralMemoryReadReceipt` for an initial register. The compiler checks its typed form and the digest relationship between its integer value and `value_digest`, then binds the full receipt into the initial-state representation and relevant initial-register operands. The value is already known to the compiler caller.

**Symbolic receiver-resolved reference.** A caller may instead supply a `VirtualStructuralMemoryRef`. The compiler normalizes its binding to the register name and binds the complete reference into the initial-state and dataflow identities:

[
R=(m,r,c,q,d_s,d_c)
]

where (m) is the memory identity, (r) its exact revision, (c) the context, (q) the coordinate, (d_s) the Structural Memory specification digest, and (d_c) the certificate digest. The compiler does not read the memory, infer its value, or substitute a placeholder value. The corresponding DAG operand remains symbolic.

A plan containing symbolic references cannot be evaluated by the local `evaluate_dataflow` path, because that evaluator has no receiver-local memory authority. In the current operation-native profile, a symbolic reference may feed an `ADD`, `COMPARE`, or `MUL` operand. The executor carries it as a schema-v2 Virtual Layer memory reference. The selected receiving host resolves it only after its local Hypervisor admission and only when its execution process holds `read` on `/structural-memory/read`. It returns the value and full typed read receipt. The requester checks the receipt against the exact pinned reference, then applies the independent scalar ADD oracle before committing the DAG node.

The reference is not a read grant, capability, generator, or executable closure. It only identifies what must be read. The receiver's registry, current revision, context, certificate and process authority determine whether resolution succeeds.

**Verified contextual-orbit predecessor.** A caller may supply a ContextualOrbitDataflowInput for an initial register. The object binds the original ContextualOrbitLocateValueRequest to its origin-verified routed ContextualOrbitLocateValueReceipt. It rechecks request identity, the selected OrbitValueResult, the observer projection, the located-coordinate Structural Memory read receipt, and the operator-effect digest. Its explicit field selects either coordinate or value; both selected values remain available alongside the observer receipt and exact read receipt.

The compiler accepts these inputs through contextual_orbit_inputs={"register": predecessor}. Rather than flattening the input into an untyped integer, it emits a distinct orbit-input-{register} source node containing the predecessor digest and receipt identities. Every instruction that reads that register receives a real dependency edge to the source node. The compiled plan and graph representation bind the complete typed request/receipt object. On commit, the source node retains the selected integer plus the serialized typed evidence; downstream operations can recover the evidence through DAG ancestry.

This is a compact result, not a trajectory. It carries the query, selected coordinate/value and the evidence needed to interpret that selection, but does not copy intermediate states or replay transitions. The compiler's v3 plan identity includes the new input class, with at most 64 contextual-orbit inputs. The request remains data/provenance, not a capability or proof of trusted hardware execution. A register cannot be supplied by more than one of inline state, a materialized receipt, a symbolic Structural Memory reference, or a contextual-orbit predecessor.

## Dependency and topology profile

Let the compiled dataflow be G=(V,E), where a node represents one instruction and an edge identifies a register-definition dependency. The compiler derives deterministic ready frontiers:

\[
F_0,F_1,\ldots,F_k
\]

where each node in a frontier depends only on nodes in earlier frontiers.

It reports:

- work units: number of instruction nodes, including HALT;
- dependency edges;
- critical-path nodes: number of frontiers;
- maximum frontier width;
- theoretical parallelism: work divided by critical-path nodes; and
- canonical graph-description bytes.

The topology_candidate is based only on structural frontier width. It is not a host-placement decision, a measured speedup, an energy estimate, or evidence of concurrent execution. Actual placement must still use the existing computational address resolver, live host capabilities, resource bounds, Hypervisor admission, and Transit execution path.

## Evaluation and proof boundary

evaluate_dataflow evaluates each ready frontier as independent pure work, then commits its results through NavigableComputationDAG. It retains a complete DAG snapshot. The evaluator runs locally and sequentially in this version; frontier width exposes potential independent work, not a parallel scheduler.

compare_dataflow_with_reference independently runs the same Program through ReferenceInterpreter and compares the declared terminal observation using the plan's TranslationContract.

The observation intentionally excludes the per-instruction trace. This compiler promises exact terminal status, PC, step count, halted/blocked state, and final register values for the admitted subset. It does not claim to preserve intermediate trace ordering as an execution schedule.

Compilation can be independently re-created with verify_dataflow_compilation. A plan created from source bytes requires those original bytes for re-verification. A plan created from a Program retains the exact typed program identity but makes no claim about the original source encoding.

## What this does not establish

This first version does not:

- compile arbitrary binary formats or infer semantics from opaque bytes;
- compile control flow, loops, mailboxes, syscalls, or effectful programs;
- optimize by rewriting, vectorizing, fusing, or deleting instructions;
- dispatch DAG frontiers to different hosts;
- demonstrate concurrent or GPU execution;
- measure physical latency, energy, or byte movement; or
- prove universal equivalence beyond the declared instruction subset and terminal observation.

The operation-native integration is specified in OPERATION_NATIVE_COMPUTATIONAL_FABRIC.md. It can dispatch ADD@3, opt-in COMPARE@1, and opt-in MUL@1 binary frontiers as pure Virtual Layer operations through authenticated fabric paths, admits CPU and E-GPU realizations under their respective semantic contracts, checks each returned lane independently, and commits the typed operation receipt and contract identity into the original DAG result. COMPARE and MUL remain local unless their respective dispatchers are explicitly supplied. This remains a sequential reference experiment, not a concurrency or speed claim. The next stage should benchmark local, remote CPU, remote E-GPU and fused placements while preserving the distinction between route estimates and observed execution.

## Run

    python -m pytest tests/test_program_dataflow.py -q
    python scripts/verify_repo.py --check links
    python scripts/verify_invariants.py
