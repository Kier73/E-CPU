# Semantic Translation Contracts

## Purpose

E-CPU contains several representations of computation and state: validated
MailCPU programs, queue-backed machine state, Virtual Layer workloads,
Structural Memory specifications, VFS byte references, demand-paged VM pages,
and bounded transit operators.

They should not be forced into one universal intermediate language merely to
compare them. Instead, a translation boundary needs to state:

1. which exact source and target representations are involved;
2. which observations are required to remain the same;
3. which context, preconditions, and invariants bound that claim;
4. which resource ceilings and receiver-side capabilities apply; and
5. how effects and replay are classified.

The first implementation is a declarative contract plus a paired observation
checker. It does not execute translations, issue capabilities, or prove a law
over all possible inputs.

## Semantic relation

Let (x) be one input case, (I_s) and (I_t) be source and target
realizations, and (Pi_C) be the observation projection named by contract
(C). The contract's intended obligation is:

[
Pi_C(I_s(x)) = Pi_C(I_t(x))
]

The equality is defined by canonical JSON bytes in v1. The projection itself
must be supplied by the caller and identified by a stable projection ID,
schema version, and definition digest. Comparing two values without applying
the same declared projection is not a valid semantic comparison.

A successful paired check establishes equality for the exact case digest
recorded in that check. It does **not** establish equality for untested inputs,
prove the correctness of either projection implementation, or certify a
universal translator. Those require additional evidence—such as bounded
exhaustion over a declared finite domain, an independently checked proof, or
differential tests over a larger corpus.

## Contract structure

`TranslationContract` is a versioned directed edge from one
`RepresentationRef` to another.

| Field | Meaning |
|---|---|
| `contract_id`, `revision` | Stable translation identity and immutable revision |
| `source`, `target` | Representation type, schema version, and content digest |
| `observation` | Projection ID/version/digest and comparison relation |
| `context_digest` | Exact context boundary the declaration is scoped to |
| `precondition_digests` | Content identities of required preconditions |
| `invariant_digests` | Content identities of required invariants |
| `resource_bounds` | Named ceilings with explicit units |
| `authority_requirements` | Receiver-side resource/right declarations; never grants |
| `effect_class` | `pure`, `journaled`, or `external` |
| `replay_class` | `deterministic`, `semantic-ledger`, or `non-replayable` |

All digests are SHA-256 over canonical JSON or an existing canonical content
identity. Set-like declarations are sorted before hashing, and duplicate
resource names, capability rights, and proof-obligation digests are rejected.
Unknown schema fields are refused rather than silently ignored.

### Authority and effect boundaries

An authority requirement is descriptive metadata. A receiver must still
resolve the requirement against its live capability state and policy; possession
of a translation contract grants nothing.

The declared effect and replay classes must also agree. A pure translation must
be deterministic. An external effect cannot claim deterministic replay without
a semantic ledger. The contract records the obligation; it does not implement
the external effect or make it atomic.

## Paired observation check

`compare_projected_observations` accepts:

- one `TranslationContract`;
- the exact input/case payload;
- the source observation, already projected under the declared observation
  contract; and
- the target observation, projected under that same contract.

It returns an `ObservationComparison` bound to the contract digest, case
payload digest, projection digest, and both observation digests. Its
`equivalent` value is true exactly when the canonical source and target
observation bytes are identical. The check record is suitable for persistence
or later aggregation, but it is not a signed attestation.

## Existing concrete integration

The first conformance example uses the existing reference and queue
interpreters:

- `program_representation_ref` content-addresses the validated ordered
  instruction/operand sequence.
- `canonical_result` supplies the existing observable projection:
  status, state, trace, and outputs.
- The test runs one exact program through `ReferenceInterpreter` and
  `QueueInterpreter`, then compares the two projections under one contract.

This turns an existing conformance property into a typed semantic-translation
record without changing either interpreter or the instruction algebra.

`structural_memory_spec_representation_ref` similarly adapts the canonical
Structural Memory specification projection to the same representation
reference. It preserves the existing spec digest, so the new contract does
not invent a second identity for that object.

## Composition

Suppose translations (T_1:A\rightarrow B) and (T_2:B\rightarrow C)
preserve the same observation contract and compatible context. Then equality
is transitive over the observations that were actually checked:

[
Pi(I_A(x)) = Pi(I_B(T_1(x)))
quad\land\quad
Pi(I_B(y)) = Pi(I_C(T_2(y)))
]

But composition also requires the output identity of the first edge to match
the input identity of the second, plus compatible preconditions, invariants,
resource budgets, authority boundaries, and effect/replay semantics. A chain
of matching labels is not enough. The current module records individual edges
and paired checks; it does not yet build or execute translation paths.

## Deliberate limits and next integration

The v1 relation is exact canonical equality only. Approximate numeric
equivalence, trace refinement, bisimulation, partial observational equivalence,
and proof-carrying translations need distinct comparison relations and explicit
evidence semantics; they must not be smuggled into this one.

The next useful integration is to attach contracts to one actual translation
path—first a bounded MailCPU-to-Transit operator path or a Structural
Memory-to-byte-page realization—and verify the resulting observations and
receipts. Only after a real path demonstrates the necessary fields should the
contract schema grow. In particular, the descriptor must not become a second
authority engine or an untyped generic AST.
