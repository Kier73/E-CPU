# MailCPU Program Dataflow Compilation

## Purpose

This experiment compiles a bounded subset of native MailCPU assembly into the existing NavigableComputationDAG. It is a structural compiler, not a second VM or a remote execution engine.

The input is an exact UTF-8 assembly byte sequence (or an already validated Program) plus an initial register state. Initial values may include typed StructuralMemoryReadReceipt records. The compiler keeps the byte representation, validated instruction representation, Computational Ground, initial-state identity, dataflow graph, and terminal observation contract as distinct but linked views.

## Supported program domain

The first version admits only:

- SET
- COPY
- ADD
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

A caller may supply a StructuralMemoryReadReceipt for an initial register. The compiler checks the typed receipt and the digest relationship between its integer value and value_digest, then binds the full receipt into the initial-state representation and every relevant initial-register operand reference.

This stage consumes an already obtained receipt. It does not perform the Structural Memory read, grant receiver authority, or claim the receipt is a signature. The existing receiver-side Structural Memory and Virtual Layer boundaries remain responsible for producing and authorizing reads. A register cannot be supplied both inline and by a receipt.

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

The immediate next integration is to bind DAG nodes to versioned pure Virtual Layer operators, execute ready frontiers through the computational fabric, and compare actual measured host/communication costs against the structural topology profile. That step must keep route estimates distinct from observed execution and preserve receiver-local authority at every operation boundary.

## Run

    python -m pytest tests/test_program_dataflow.py -q
    python scripts/verify_repo.py --check links
    python scripts/verify_invariants.py
