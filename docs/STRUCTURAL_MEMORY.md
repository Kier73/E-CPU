# Adaptive Structural Memory Service (E0)

## Purpose

The Structural Memory Service is the first executable layer of Adaptive Structural Emulation. It stores a verified generative description of a state family rather than requiring every state to be materialized.

A structural memory version binds:

- a stable memory identity and immutable revision;
- a typed generator family and its canonical parameters;
- a domain label;
- exact context/boundary metadata;
- a verification certificate tied to the spec and context digests;
- a parent digest linking the revision to its predecessor.

The service is built above MailCPU's existing transition and law-certification code. It does not change the meaning of MailCPU instructions, create a second interpreter, or grant execution authority.

## E0 implementation boundary

The first registry admits only four existing deterministic law families:

| Family | Representation | Runtime navigation |
|---|---|---|
| int | Integer arithmetic progression, optionally modular | Existing guarded arithmetic-law navigation |
| lcg | Affine modular recurrence | Existing guarded affine recurrence navigation |
| gf2 | Linear recurrence over GF(2) | Existing guarded LFSR jump |
| fgraph | Finite orbit with a pre-period and cycle | Existing guarded orbit projection |

The registry rejects kreg, mixtures, arbitrary callables, generated Python, FITTED, and TAPE laws in this stage. Those are not declared invalid mathematical objects; they are simply outside this E0 admission contract.

The generator registry validates each family's exact parameter shape before reconstructing a Law. This avoids turning a memory description into an unrestricted code-execution mechanism.

## Objects and responsibilities

### StructuralMemorySpec

An immutable, canonical description of the generator, domain, context, revision, and parent. The digest covers all of those fields. Parameter and context dictionaries are stored internally as canonical JSON strings; accessors return detached copies.

### StructuralMemoryCertificate

A separately digest-addressed evidence object bound to the exact spec and context. It carries the witness digest, witness count, generator identity/version, and verification class.

The certificate is not a universal proof. It records the precise finite evidence that was replayed.

### GeneratorRegistry

A closed adapter registry over the four existing law families. It uses the law-certifier's guarded navigation interface for all runtime state reads.

### ContextMapper

E0 treats context as an exact boundary identity. The context object is canonicalized and hashed. A read under a different context is refused. Context-to-generator-parameter adaptation is deliberately deferred to a later revision of the service.

### StructuralMemoryVerifier

Reconstructs the deterministic law from the spec and independently replays the supplied observations before issuing a certificate. A staged proposal is rechecked again at admission.

### StructuralNavigator

Checks spec/certificate correspondence, context identity, coordinate type, and any prefix horizon before navigating to a state.

### StructuralMemoryRegistry

Owns staged proposals and active immutable versions. It provides propose, propose_trace, admit, and read.

## Proposal and admission sequence

A law may be supplied directly, or recovered from an observed training window and a withheld suffix:

1. STRUCTURE_PROPOSE / StructuralMemoryRegistry.propose_trace calls the existing recover_law routine.
2. The registry only proceeds when recovery returns GROUND or PREFIX-GROUND within the admitted family whitelist.
3. It replays all supplied observations against the candidate generator.
4. It stages an immutable proposal and certificate. No active memory changes.
5. STRUCTURE_ADMIT / StructuralMemoryRegistry.admit compares the candidate's parent and revision against the caller's expected active revision.
6. A trusted host-supplied admission policy must return the literal Boolean True.
7. The registry re-verifies the certificate and only then installs the new active version.

The admission callback is an authority boundary supplied by trusted host code. A model or a proposal cannot authorize itself. With no callback configured, admission fails closed.

Two competing proposals created against the same active revision cannot both win: after one is admitted, the other fails its parent/revision compare-and-swap.

## Evidence and horizons

The existing law certifier uses GROUND, PREFIX-GROUND, FITTED, and TAPE. The Structural Memory Service maps only the first two into admitted evidence classes:

- WITNESS_GROUNDED: every coordinate in the supplied witness set matches the deterministic generator. This is finite witness agreement, not a proof for every possible coordinate.
- PREFIX_GROUNDED: all supplied observations before first_bad match, and a witness at first_bad demonstrates escape from the proposed law. The valid coordinate interval is strictly t < first_bad.

FITTED and TAPE cannot be admitted. For a prefix-grounded memory, a read at or beyond the exclusive horizon is refused. The implementation uses the raw law evaluator at exactly first_bad only while checking the escape witness; runtime reads always use navigate_guarded.

Verification status travels with every read receipt. Consumers should not strip the verification class, witness digest, spec digest, or context digest when forwarding a generated value.

## Read contract

STRUCTURE_READ / StructuralMemoryRegistry.read(memory_id, coordinate, context=...) returns a StructuralMemoryReadReceipt containing:

- the integer value;
- memory identity and revision;
- spec and certificate digests;
- the coordinate and context digest;
- a value digest;
- verification class and witness digest;
- deterministic receipt identity and cache-hit indication.

Coordinates must be non-negative integers; Boolean values are rejected even though Python treats Booleans as integers. Context must exactly match the context bound to the active revision.

The receipt is provenance for a structural read. It is not an execution grant, hypervisor authorization, CPU retirement event, or proof that an external machine has been mutated.

## Example

    from mailcpu.structural_memory import StructuralMemoryRegistry

    training = [(65500 + 17 * t) % 65536 for t in range(30)]
    withheld = [(65500 + 17 * t) % 65536 for t in range(30, 40)]

    registry = StructuralMemoryRegistry(
        admission_policy=lambda proposal: proposal.spec.domain == "integer-orbit"
    )
    proposal = registry.propose_trace(
        "counter-orbit",
        training,
        withheld,
        context={"source": "example"},
    )
    active = registry.admit(proposal.proposal_id, expected_revision=0)
    result = registry.read("counter-orbit", 1000)

The example uses a modular progression; actual candidate admission still depends on what the law certifier and withheld witnesses establish. Applications should choose a domain and observations that match the actual process semantics.

## Explicit non-goals and next stages

E0 is an in-process registry and read path. It does not yet:

- persist staged proposals, active versions, receipts, or cache state into HeadlessOS checkpoints;
- append structural-memory admission/read receipts to the event journal;
- adapt context fields into a changed generator boundary;
- use learned models to prioritize or propose generator families;
- compose heterogeneous generators or coordinate systems;
- lazily materialize filesystem pages or files;
- perform CPU instruction macro-transitions or change native vCPU state;
- execute model weights, recurrent state, or neural operators.

Those require their own typed contracts, checkpoint/replay obligations, authority rules, and differential or trajectory-level conformance tests.

The next development step is to connect the registry's immutable records and proposal/admission results to the existing checkpoint and hypervisor journal, then implement context-only revisions while keeping the generator fixed. Memory-provider integration and CPU macro-transitions should follow only after those persistence and correspondence obligations are tested.

## Test scope

The E0 conformance suite covers proposal staging, host authorization, revision compare-and-swap, immutable parent lineage, canonical context binding, witness replay, prefix escape/horizon behavior, trace-based law recovery, and each admitted generator family. These tests establish the implemented finite contract; they do not certify universality or performance beyond their measured domains.
