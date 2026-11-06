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

```text
Observe_C(Source(x)) == Observe_C(Target(x))
```

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
`RepresentationRef` to another, with a third content-addressed reference that
pins the mapping definition itself. The mapping may describe a named adapter,
compiler rule, interpreter relation, or externally supplied transform; the
contract carries its identity, not its executable code.

| Field | Meaning |
|---|---|
| `contract_id`, `revision` | Stable translation identity and immutable revision |
| `source`, `target` | Representation type, schema version, and content digest |\n| `mapping` | Content-addressed identity of the translation rule or adapter definition |
| `observation` | Projection ID/version/digest and comparison relation |
| `context_digest` | Exact context boundary the declaration is scoped to |
| `precondition_digests` | Content identities of required preconditions |
| `invariant_digests` | Content identities of required invariants |
| `resource_bounds` | Named ceilings with explicit units |
| `authority_requirements` | Receiver-side resource/right declarations; never grants |
| `effect_class` | `pure`, `journaled`, or `external` |
| `replay_class` | `deterministic`, `semantic-ledger`, or `non-replayable` |

All digests are SHA-256 over canonical JSON or an existing canonical content
identity. Changing the mapping definition changes the contract digest, even
when the source and target representations remain the same. Set-like declarations are sorted before hashing, and duplicate
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

A second conformance case exercises the existing Structural Memory demand-page
path. It pins one admitted structural-memory specification, resolves its
coordinate values directly with receipts, then registers the exact byte-range
reference with `StructuralMemoryPageBacking` and faults the page into
`VirtualMemory`. The paired observation includes bytes, content digest, and
the ordered coordinate receipt IDs. This checks the resident page's content
and coordinate provenance for that pinned case, not an infinite generator law.

## Receiver-side Transit execution evidence

`TransitComputeWorker` now uses the existing hypervisor effect-encoder seam
for every newly executed, allowed object-valued backend result. The worker
captures the event after receiver-local capability reconstruction, obtains
the committed policy decision receipt, and binds the selected operation,
resource, domain, and complete sorted backend manifest.

The resulting `TransitTranslationEvidence` contains:

- the semantic request identity and canonical event fingerprint;
- the receiver's policy decision receipt;
- source and target representation references for the authorized event and
  raw handler effect;
- a content-addressed backend-dispatch mapping identity;
- the declared receiver-side authority requirements and effect/replay model;
- a paired comparison of the raw handler effect and its canonical JSON
  round-trip; and
- the backend manifest used for dispatch.

The record is embedded in the committed effect under
`_semantic_translation`. It is created inside
`HypervisorArbitrationLoop.execute` before the effect is stored. Exact
semantic retransmissions therefore return the same evidence with the stored
effect; they do not invoke the backend or rebuild the evidence. The worker's
existing checkpoint restores the hypervisor execution ledger, so the same
binding survives worker reconstruction and transport rebinding.

`TransitTranslationEvidence.validate_execution_result` cross-checks the
record against the outer `HypervisorExecutionResult`: request identity,
fingerprint, decision receipt, policy domain, and the digest of the effect
with the evidence field removed. The replay flag remains on the outer result;
it is deliberately excluded from the evidence digest so an original result
and its exact replay carry identical translation evidence.

### What this proves—and what it does not

The paired comparison checks that the handler's returned effect survives
canonical JSON normalization without changing. The enclosing contract ties
that effect to a specific authorized request and selected receiver-side
dispatch mapping, while the hypervisor ledger binds its semantic identity and
replay behavior.

This does **not** independently prove that a backend computed the correct
answer for the request. That requires an operation-specific oracle, invariant,
or differential test. It also does not sign evidence against a malicious
receiver, grant capabilities, or extend worker checkpointing into an atomic
transaction across arbitrary external side effects.

## Independent operation oracle evidence

For two receiver-side operation families, the worker now runs an independent
semantic oracle after the backend handler returns and before the hypervisor
commits the effect. Its typed record is embedded beside
`_semantic_translation` under `_semantic_oracle`.

The CPU oracle independently interprets the admitted pure arithmetic subset
(`SET`, `COPY`, `ADD`, `COMPARE`, `BRANCH`, `HALT`) without calling the
production instruction transition function or scheduler. It shares the
assembler as the input parser, so this is an independent execution semantics
check, not an independently implemented parser. The comparison observes
terminal status, exit code, program counter, executed instruction count, and
register map; scheduler PID, scheduler-event count, and whole-OS state digest
are intentionally excluded.

The Structural Memory oracle resolves the exact admitted revision and
certificate, validates the request context and prefix horizon, then derives
the requested coordinate without calling the production generator adapter.
It currently covers the admitted `int`, `lcg`, `gf2`, and `fgraph`
families. Its comparison binds the revision/spec/certificate digests,
coordinate, context digest, value and value digest, verification class, and
witness digest.

Each `TransitOracleEvidence` binds the oracle definition reference, exact
request fingerprint and case digest, projection digest, expected and observed
canonical observations, and a deterministic work count with its limit.
The CPU work count is one unit per fetched instruction, including `HALT`,
and its limit is the request's tick budget. Structural Memory work units
count the reference algorithm's defined primitive work: one evaluation for
the direct `int` and `fgraph` paths, affine compositions plus the final
projection for `lcg`, and bit-matrix row applications/compositions for
`gf2`. These are operation-specific accounting units, not measured CPU
cycles, elapsed time, joules, or directly comparable units between oracle
families.

The current Structural Memory oracle is capped at 1,000,000 work units,
4,096-bit coordinates/parameters, and GF(2) order 64. The CPU oracle is
capped at 16 KiB source, 512 instructions, 32 initial registers, and 10,000
ticks. If a supported operation exceeds its oracle bound or the independent
observation disagrees with the backend effect, the effect encoder fails and
the hypervisor does not commit that result. Exact semantic retries replay the
stored effect and the same oracle evidence without rerunning the oracle.

### Proof boundary

An oracle comparison establishes agreement for this concrete authorized
request, exact program/input or pinned revision/context/coordinate, and
registered oracle definition. It does not prove all executions of the
program, every coordinate of a Structural Memory law, the correctness of
the assembler, or the absence of shared defects in both implementations.
Structural Memory's existing certificate remains witness-grounded or
prefix-grounded; the new oracle does not promote finite witnesses into an
infinite proof. The record is produced by the trusted receiver and is not a
signature or remote attestation against a malicious receiver.

For checkpoint compatibility, `TransitTranslationEvidence.validate_execution_result`
accepts a pre-oracle ledger effect that contains no `_semantic_oracle` when
called with its default `require_oracle=False`. This validates the original
translation provenance and effect digest only; it does **not** imply that an
independent oracle ran. Callers validating a result produced under the current
worker contract can set `require_oracle=True`; newly committed supported
CPU and Structural Memory effects always take that path and fail before
commit if their oracle comparison is absent, mismatched, or over budget.


## Composition

Suppose translations T1:A->B and T2:B->C preserve the same observation
contract and compatible context. For one case x, the composed comparison is:

```text
Observe_A(x) == Observe_B(T1(x))
Observe_B(T1(x)) == Observe_C(T2(T1(x)))
```

The intermediate B value must be exactly the same in both comparisons.

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

The first receiver-side Transit integration now attaches
`TransitTranslationEvidence` to committed allowed handler effects. It binds
the authorized event identity/fingerprint, backend operation/resource/domain
and manifest, policy decision receipt, raw effect digest, and canonical JSON
round-trip check. The evidence is committed with the existing hypervisor
execution result, so semantic replay and worker checkpoint restoration return
the same record.

The next step is to add operation-specific independent semantic oracles to
selected Transit adapters. The current paired check proves that the handler's
effect survives canonicalization unchanged; it does not prove that the
handler's answer is correct. For arithmetic, compare against a separate
reference interpreter; for structural-memory reads, compare the returned
receipt/value projection against an independently derived expected coordinate
under the same pinned admitted version. Continue to keep authority local and
leave arbitrary, unverified translators outside the executable path.
