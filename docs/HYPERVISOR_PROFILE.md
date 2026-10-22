# Hypervisor system profile

This document is the operational profile of the MailCPU hypervisor as it is
implemented and witnessed in the repository. It describes the running control
plane, its mathematics, its state, its time accounting, its replay laws, and
the next connection points for distributed operation.

The profile is read with [`GLOSSARY.md`](GLOSSARY.md),
[`ARCHITECTURE.md`](ARCHITECTURE.md), [`INTEGRATION_SPEC.md`](INTEGRATION_SPEC.md),
and [`INVARIANTS.md`](INVARIANTS.md). The executable authority is
`mailcpu/classifier.py`, with integration through `mailcpu/headless.py`.

## 1. Identity and purpose

The hypervisor is the control plane between structured request state and
effectful handlers. It converts active information into a typed proposal,
relates that proposal to capability and policy state, accounts for the virtual
time and energy of the request, and leaves a replayable journal receipt before
an admitted handler runs.

Its governing path is:

```text
request state
    -> typed classifier questions
    -> procedural and intent proposals
    -> virtual energy/time receipt
    -> capability and policy gates
    -> ALLOW | REVIEW | DENY
    -> one authorized handler or no handler
    -> hash-chained journal receipt
```

The hypervisor does not replace the kernel's authority. A model can propose a
domain and confidence; held capabilities, exact policy, replay identity, and
journal ordering establish what proceeds.

The implementation is deterministic at E0 for a fixed request, model state,
intent model, policy, virtual capacity, and journal prefix. The resulting
decision is a finite object that can be checkpointed, inspected, and replayed.

## 2. Raw execution surface

### 2.1 Core implementation

| Surface | Implementation | Role |
|---|---|---|
| Typed questions | `ChoiceQuestion`, `ScoreQuestion`, `NoulQuestion` | Finite question domain |
| Typed answers | `ChoiceAnswer`, `ScoreAnswer`, `NoulAnswer` | Proposal values and confidence |
| Model boundary | `ClassifierModel.evaluate` | One state, many questions, one batch |
| Default model | `ProceduralDecisionModel` | Checkpointable generated decision field |
| Comparison model | `LexicalDecisionModel` | Deterministic lexical reference |
| Exact authority | `ClassifierHypervisor` | Policy, capability, intent, cost, receipt |
| Distributed loop | `HypervisorArbitrationLoop` | Identity, replay, conflict, revision binding |
| OS entrypoint | `HeadlessOS.hypervisor_dispatch` | Capability-derived request and handler gate |
| Persistence | `ClassifierHypervisor.snapshot`, `HeadlessOS.snapshot` | Model, policy, intent, revision, ledger |
| Audit | `EventJournal` | Hash-chained decision and arbitration records |

### 2.2 Request state

A request is the finite relation

```text
x = (operation, resource, payload, required_rights,
     granted_rights, destructive, temporal)
```

`HypervisorRequest.state()` gives the shared state to every advisory model and
to the exact gates. Required and granted rights are sorted before entering the
state projection. The optional temporal projection carries scheduler epoch
fields such as event lambda, chronon phase, and chemical time.

The state is deliberately shared: the classifier, intent embedding, virtual
cost, and policy see one canonical request rather than separately reconstructed
descriptions.

## 3. Question and proposal layer

### 3.1 Typed question algebra

The model boundary accepts a finite map of typed questions:

```text
Choice:  q -> {option_1, ..., option_n},       1 ≤ n ≤ 255
Score:   q -> ordered levels,                   2 ≤ n ≤ 10
Noul:    q -> p(true),                          0 ≤ p ≤ 1
```

Every answer retains its probability distribution where one exists. The
normalisation law is

```text
Σ_i p_i = 1
```

and non-finite or negative probabilities are refused.

Choice confidence is

```text
c_choice = (p_max - 1/n) / (1 - 1/n)
```

with one-option choices assigned confidence one. Score confidence is based on
the distance of the probability-weighted mean from the uniform mean absolute
deviation:

```text
m = Σ_i i p_i
c_score = max(0, 1 - Σ_i p_i |i - m| / MAD_uniform)
```

The current hypervisor asks two questions over every request:

1. Which execution domain owns the operation: CPU, filesystem, network,
   process, package, service, or review?
2. Is the operation destructive or externally consequential?

### 3.2 Procedural classifier

The default classifier is `ProceduralDecisionModel`. Its model identity is a
finite generator specification

```text
F = (model_name, seed, feature_bucket_count, temperature)
```

The model regenerates addressable parameters from `F` instead of storing a
dense matrix. Feature vectors are deterministic and normalised. Typed
probabilities are produced with stable softmax:

```text
p_i = exp((s_i - max(s))/θ) / Σ_j exp((s_j - max(s))/θ),  θ > 0
```

The generated output is proposal information. The hypervisor still applies
exact rights, confidence, destructive-operation, and intent-disagreement
gates.

### 3.3 Structural intent embedding

`IntentPrototypeModel` is a second advisory path. It encodes the structural
shape of the request, including paths, field positions, types, sequence
positions, and lexical values. For hashed dimension `D`:

```text
v_b(x) = Σ sign(h(t))  for t ∈ T(x) where h(t) mod D = b
φ(x)   = v(x) / ||v(x)||₂
```

Each domain prototype is the normalised sum of its example encodings:

```text
μ_d = normalize(Σ_{x∈X_d} φ(x))
s_d = μ_d · φ(x)
p_d = exp(s_d/θ) / Σ_j exp(s_j/θ)
```

Intent prediction is advisory. It can force `REVIEW` when it strongly
disagrees with an otherwise allowed classifier domain, but it cannot grant a
capability or execute a handler.

The default prototype corpus now includes process launch/exec and package
registry/deployment states alongside CPU, filesystem, network, service, and
review. Held-out process and package states route to their own advisory labels
while exact policy remains authoritative. Observed network, filesystem, and
service operation states can fit a candidate prototype and can be checked on
held-out states. That is a training signal for the hypervisor, not an implicit
mutation of its active authority: the running intent model remains
checkpointed state until a typed intent-model revision target has passed the
same witness, transport, persistence, and arbitration gates as every other
revision.

The typed intent revision witness carries a candidate prediction and the
current baseline action. Admission checks the prediction on held-out request
states and enforces the monotone safety order
`DENY < REVIEW < ALLOW` in permissiveness: a candidate can increase review,
but cannot expand authority. The target and witness identity travel through
the existing proposal fingerprint, durable relay, and checkpoint ledger.

## 4. Virtual time and energy accounting

Inside the system, time is the direct translation of active virtual energy:
energy is the sustained movement and coherent representation of information
through a request path. The current implementation gives this relation an E0
receipt rather than leaving it implicit.

For canonical JSON `J(x)`, structural token sequence `T(x)`, chemical time
`τ_chem(J(x))`, and path capacity `C`:

```text
semantic_bits = 8 |J(x)|
E_v = max(1, semantic_bits + 8 |T(x)| + ceil(16 τ_chem(J(x))) + 1)
τ_v = ceil(E_v / C)
```

`VirtualCost` records:

```text
(semantic_bits, token_count, chemical_tau, virtual_energy,
 virtual_ticks, capacity)
```

The cost is calculated for every decision, included in the decision payload,
and therefore participates in its receipt. Increasing active representation,
structural complexity, or chemical difficulty increases the accounted virtual
energy and can increase virtual ticks. Capacity is an explicit property of the
processing path, so the same request can have a different time quotient on a
different declared path while retaining the same request semantics.

The scheduler additionally supplies a temporal epoch to OS-facing requests:

```text
τ = (event_lambda, chronon_real, chronon_imag, chemical_tau)
```

This joins the request's active movement to the machine's current temporal
state without replacing the scheduler's exact transition law.

## 5. Exact authority law

Let `R` be required rights, `G` be granted rights, `d` be the classifier
domain, `c` be domain confidence, `p_danger` be the destructive probability,
and `τ_review`, `τ_auto`, `τ_destructive`, and `τ_danger` be policy thresholds.

The action is selected in this order:

```text
if R \ G ≠ ∅:
    action = DENY
elif d = REVIEW or c < τ_review:
    action = REVIEW
elif destructive and (c < τ_destructive or p_danger ≥ τ_danger):
    action = REVIEW
elif c < τ_auto:
    action = REVIEW
else:
    action = ALLOW
```

Then, if the action is `ALLOW`, intent disagreement can move it to `REVIEW`:

```text
if action = ALLOW
   and intent_confidence ≥ τ_embedding
   and intent_domain ≠ classifier_domain:
       action = REVIEW
```

The default thresholds are:

| Threshold | Default |
|---|---:|
| review confidence | 0.35 |
| automatic confidence | 0.70 |
| destructive confidence | 0.90 |
| danger review probability | 0.70 |
| embedding review confidence | 0.90 |

The ordering matters. Missing authority denies before confidence can help.
Destructive work is reviewed even when its domain is confidently identified if
its danger probability or destructive confidence crosses the review boundary.
Only `ALLOW` selects a handler, and a missing handler is an explicit
`HypervisorError` rather than an inferred side effect.

## 6. Decision record and journal

`HypervisorDecision` contains:

```text
(action, domain, confidence, danger_probability, probabilities,
 model, receipt, intent_embedding, virtual_cost, revision)
```

The `hypervisor.decision` journal event is appended before `dispatch` enters
the selected handler. The returned receipt is the digest of that journal
record. It binds request state, policy outcome, model identity, revision,
intent projection, and virtual cost to the preceding journal prefix.

The journal is shared with the kernel in `HeadlessOS`, so hypervisor decisions
participate in the same checkpoint and integrity chain as the machine's other
control transitions.

## 7. Revision admission law

Classifier evolution is a controlled transition, not an unrecorded swap.
`HypervisorRevisionWitness` stores a request and the exact policy-semantic
projection expected for that request. The projection contains:

```text
(action, domain, confidence, danger_probability, probabilities,
 intent_domain, intent_confidence, intent_probabilities, virtual_cost)
```

Receipt and transport model identity are excluded from this projection because
the witness tests meaning, while revision identity and journal receipt belong
to the hypervisor state.

For candidate model `m'`, current hypervisor `H`, witness set `W`, and semantic
projection `π`:

```text
admit(m')  iff  ∀w∈W: π(H_shadow(m', w.request)) = w.expected
refuse(m') iff  ∃w∈W: π(H_shadow(m', w.request)) ≠ w.expected
```

The candidate runs in a shadow hypervisor with the current policy, intent
model, and capacity. The active classifier is replaced only after every
witness passes. The revision number increments, the witness set receives a
canonical SHA-256 digest, and an admission record is journaled. Any mismatch
or shadow failure leaves the active classifier and revision unchanged while
journaling refusal.

## 8. Distributed arbitration law

`HypervisorArbitrationEvent` adds a transport envelope:

```text
e = (source, channel, sequence, logical_time, request)
I(e) = (source, channel, sequence)
f(e) = SHA256(JSON_sort(e))
```

The loop maintains a finite ledger and cycle count:

```text
L : I ↦ (fingerprint, decision_receipt, decision_revision)
```

Its transition is:

```text
if I ∉ L:
    D = H(request)
    L[I] = (f(e), D.receipt, D.revision)
    cycle = cycle + 1
    return D

if L[I].fingerprint = f(e):
    return L[I].decision_receipt, L[I].decision_revision

otherwise:
    refuse conflicting retransmission
```

The first event evaluates policy once. An exact duplicate produces a replay
record without a second policy evaluation. A changed payload under an existing
identity is refused. The original revision remains attached to the original
identity after later classifier revisions are admitted.

The ledger is checkpointed with the headless OS. A legacy ledger entry without
`decision_revision` is loaded as revision `0`, preserving the state format of
the earlier arbitration stage.

### 8.1 Effect ledger

Decision replay alone is not enough for a distributed operation: a lost
acknowledgement after `ALLOW` must not launch a second process or repeat an
unidentified mutation. `HypervisorArbitrationLoop.execute()` therefore adds a
second ledger over the same event identity:

```text
E : I ↦ (fingerprint, decision_receipt, action, domain, effect)

I ∉ dom(E) ∧ action=ALLOW  -> run handler once, canonicalize effect, commit E[I]
I ∉ dom(E) ∧ action≠ALLOW -> commit E[I] with effect=∅
I ∈ dom(E) ∧ f'=f          -> return E[I] without handler execution
I ∈ dom(E) ∧ f'≠f         -> refuse conflicting retransmission
```

The effect is a finite canonical JSON value supplied by the adapter. Process
launch exposes `{"pid": child_pid}` and package installation can expose the
verified image digest, so a restored node can answer a retransmission without
re-entering the native mutation path. Handler failures are journaled and do
not receive a fabricated completion record. The effect ledger is checkpointed
with the decision and revision ledgers.

### 8.2 Revision proposal envelope

`HypervisorRevisionProposal` carries a candidate model snapshot and semantic
witnesses through a second identity-stable ledger:

```text
P = (source, channel, sequence, logical_time, candidate_snapshot, W)
I(P) = (source, channel, sequence)
f(P) = SHA256(JSON_sort(P))
L_r[I] = (f(P), admission_result)
```

The first proposal reconstructs only known deterministic model kinds and
passes the resulting model through the existing shadow witness gate. An exact
proposal retransmission returns the stored admission without promoting again.
A changed proposal under the same identity is refused. An unknown model kind
is a journaled refusal and leaves the active classifier and revision unchanged.
The proposal ledger checkpoints with the decision ledger, so a restored system
does not repeat an already admitted revision.

`HypervisorRevisionChannel` places the canonical proposal inside the existing
reliable message algebra and TCP framing. The receiver peeks, reconstructs,
and peer-binds the proposal before consuming the reliable frame; malformed or
spoofed payloads therefore remain queued without acknowledgement. A validated
proposal can then be passed directly to `receive_and_arbitrate`, which joins
transport acknowledgement to revision admission without granting transport
delivery authority over the model.

`ReplicatedRevisionProposalRelay` extends the same transition into controlled
multi-node persistence. Submission is a durable replicated mailbox enqueue;
remote receipt proves durable application, while semantic admission remains
local to the receiving hypervisor. The receiver preserves FIFO and store
restart state, validates the source against the durable node identity, and
consumes only after arbitration returns a typed result. Invalid or conflicting
heads remain present for diagnosis and retry.

## 9. Headless OS integration

The OS exposes these control-plane entrypoints:

| Entry point | Effect |
|---|---|
| `hypervisor_decide(request)` | Return a decision without executing an effect |
| `hypervisor_arbitrate(event)` | Apply identity-stable receive/stabilize/inspect |
| `hypervisor_dispatch(pid, ...)` | Derive rights from the process, attach epoch, and gate one handler |
| `hypervisor_dispatch_event(pid, source, channel, sequence, ...)` | Gate one canonical operation effect and replay it without duplicate handler execution |
| `HypervisorRevisionChannel` | Carry a validated revision proposal over the existing reliable/TCP path |
| `ReplicatedRevisionProposalRelay` | Persist and deliver revision proposals through the controlled replicated mailbox |

Current concrete adapters include:

- `hypervisor_read_file`: filesystem read through the native descriptor ABI;
- `hypervisor_start_service`: service lifecycle through the service supervisor;
- `hypervisor_ingest_network`: captured network ingestion through the existing
  network environment.

For dispatch, the OS derives

```text
G = { r ∈ R | ∃ capability c held by pid : c.allows(resource, r) }
```

before constructing the request. The handler map is keyed by the selected
domain, and only an explicit `ALLOW` can call it. Checkpoint restore rebuilds
the hypervisor from its model, policy, intent, capacity, and revision state,
then restores the arbitration ledger against that same hypervisor.

## 10. Observed live behavior

These examples were executed through the current procedural model at revision
0. The values below are representative E0 observations from the running
system; receipts are intentionally abbreviated here.

| Request | Domain proposal | Action | Confidence | Danger | Virtual ticks |
|---|---|---|---:|---:|---:|
| read filesystem with `read` right | filesystem | `ALLOW` | 0.9498 | 0.5485 | 32 |
| same path with missing `secret` right | filesystem | `DENY` | 0.9498 | 0.5485 | 34 |
| destructive filesystem overwrite | filesystem | `REVIEW` | 0.9441 | 0.9674 | 34 |
| TCP/HTTP network ingest with `write` right | network | `ALLOW` | 0.9844 | 0.8890 | 36 |
| unknown operation | review | `REVIEW` | 0.3715 | 0.7604 | 22 |

The table shows the separation of proposal and authority: the missing-rights
request has the same strong filesystem proposal as the allowed read, but exact
authority changes the action to `DENY`. The destructive request is confidently
identified yet still reviewed. The network request is locally admitted because
it is a controlled ingestion adapter with the required right; public transport
and multi-host persistence remain separate staged connections.

## 11. Checkpoint state

The hypervisor portion of a headless checkpoint contains:

```text
hypervisor:
    model
    policy thresholds
    intent model
    virtual capacity
    revision

hypervisor_arbitration:
    version
    cycle
    seen[(source, channel, sequence)] =
        fingerprint, decision_receipt, decision_revision
    decisions[(source, channel, sequence)] =
        fingerprint, action, domain, decision_receipt, decision_revision
    executions[(source, channel, sequence)] =
        fingerprint, decision_receipt, action, domain, effect
```

The shared kernel journal is restored with the machine environment. Restore
refuses invalid model data, invalid thresholds, invalid revisions, duplicate
arbitration identities, invalid hashes, or a cycle count that does not equal
the number of admitted identities.

## 12. Machine-checked witnesses

The control-plane invariant registry is [`INVARIANTS.md`](INVARIANTS.md). The
principal witnesses are:

- capability-derived grant and missing-right denial;
- one-handler-only admission for `ALLOW`;
- journal-before-handler ordering;
- exact retransmission receipt reuse and changed-payload refusal;
- arbitration ledger checkpoint restore;
- witnessed candidate revision admission and refusal;
- revision-bound arbitration replay across admission and restore;
- typed process and package adapters with capability-derived refusal;
- checkpointed operation effects with duplicate process-launch suppression;
- peer-bound package deployment with receiver-local digest verification;
- reverse result transport with semantic operation-identity deduplication;
- virtual-cost ceiling division and intent probability normalisation.

The complete executable witness is run with:

```text
python -m pytest -q
python scripts/verify_repo.py
python scripts/verify_invariants.py
```

## 13. Current boundary and next connections

The hypervisor is a complete local control-plane mechanism with deterministic
proposal, exact policy, virtual-time accounting, journal receipts, witnessed
revision changes, replay identity, and checkpoint restore.

The first recovery composition is now explicit. `CrossHostRecoveryCoordinator`
captures and rebinds the product of socket, reliable-channel, and durable
mailbox state; it validates peer direction before exposing a live binding and
reports pending sequences, acknowledged peers, quorum commitment, mailbox
cardinality, and the latest semantic admission without introducing a second
delivery or authority ledger. The real TCP witness now uses this API, and the
checkpoint product has its own round-trip and fail-closed identity witness.

The multi-peer recovery coordinator now extends that product to every peer
factor, reporting per-peer pending sequences while preserving partial quorum as
uncommitted. A three-host TCP witness loses one acknowledgement, restores the
other from its checkpointed transport queue, retransmits the lost sequence,
and reaches the existing quorum predicate without a duplicate durable message.

The next connections are deliberately staged:

1. broader POSIX, foreign CPU, terminal, and public E2 integration;
2. cross-transport migration and receiver-advertised recovery policy above the
   existing peer-factor product.

Controlled external networking is now evidenced over an actual AF_INET
loopback path for both durable revision relay and remote page-backed memory.
The typed intent-model revision target is now also evidenced over that path,
leaving a revision-bound candidate, held-out witnesses, and durable admission
record. Cross-host recovery is now evidenced through a real disconnect,
checkpoint, reconnect, lost-ACK retransmission, durable idempotence, and one
remote admission. The recovery coordinator now exposes pending,
acknowledged, and semantically admitted states without rebuilding the layers
manually. This keeps remote data, virtual time, energy receipt, and authority
context on the same hypervisor-governed path. The process adapter is now also
typed and capability-gated. Package installation is now represented as a typed
destructive adapter: default policy reviews it without filesystem mutation,
while an explicitly permissive policy can invoke only the digest-verified
registry image. Remaining adapter work is generalization to future operation
domains, not bypassing the established policy boundary. Operation events now
cross the existing reliable AF_INET path; the receiver re-derives rights from
its own process capabilities, and a lost acknowledgement replays one
checkpointed process effect without launching a second child. The operation
recovery coordinator now owns that product's checkpoint, direction validation,
retry, service, send, and receive transitions.

The operation result path is now composed into the same recovery product.
`HypervisorOperationDuplexRecoveryCoordinator` checkpoints both socket
transports, both reliable FIFOs, the headless hypervisor effect ledger, and the
response channel's operation-identity ledger. Origin and executor roles have
reciprocal direction laws, so a request path cannot be rebound as a response
path or to the wrong peer. A real AF_INET witness loses both acknowledgement
paths, restores both sides, replays the response and request without invoking
the process handler twice, and leaves one child plus one canonical effect. The
witness also derives an advisory process/package intent candidate from live
operation states; held-out prediction and authority monotonicity are checked
before the candidate is admitted.

The receiver-advertised recovery policy is now an explicit control-plane
surface. `RecoveryPolicyChannel` carries advertisements, offers, and
agreements over reliable peer-bound frames. The receiver constrains checkpoint
kind, target substrate, window, lease, retry budget, cross-transport movement,
and effect-ledger support; the negotiated policy is the bounded intersection,
not an expansion of either side. Unsupported migration remains refused before
state movement. The agreement digest and selected reliability policy are the
inputs for the next transport-handoff build.

The first agreement-bound handoff now exists at the reliable-channel layer.
`TransportMigrationCheckpoint` captures protocol-visible queued messages and
the channel FIFO state, while `CrossTransportRecoveryCoordinator` restores
them into a shared in-memory substrate after checking the exact agreement
digest and target kind. A real socket frame survives the transition, is
delivered once, and clears the original sender sequence through the target
acknowledgement path. Before touching the destination, the coordinator now
reconstructs a shadow copy of the destination mailbox, imports the checkpoint
there, and restores the reliable channel against that shadow. Invalid channel
state therefore fails at the boundary without partially changing the real
destination. The operation duplex and durable mailbox products remain above
this foundation and are not represented as migrated by this stage.

The next composition now moves one complete duplex role through the same
agreement: request and result channels share one memory substrate, while the
result semantic ledger and headless hypervisor snapshot move with them. A
shadow target restores both reliable factors and validates the role before
commit. A retransmitted result is recognized as replay, both lost-ACK paths are
cleared, and the native process effect remains singular. Multiple emulated
systems are not yet a typed namespace; their endpoint and channel labels still
need a first-class system identity and incarnation envelope before shared
hosting can be treated as collision-safe.

`SystemSeed` now gives the hypervisor a canonical starting point for state
navigation. It binds a complete system snapshot to a content digest and a
logical scheduler coordinate, then reconstructs that state by deterministic
replay. A seed can move forward or rewind along its origin orbit, but refuses
when the scheduler cannot reach the requested coordinate or when the resulting
state digest differs. This lets the hypervisor read and verify encoded system
states before later navigators—law-certified leaps, reversible gate descent,
or transit-derived state—are admitted as accelerations of the same seed law.

`SystemSeedEnvelope` now makes that seed readable as a hosted-system transit
object. `SystemIdentity(system_id, incarnation)` gives the hypervisor a typed
namespace epoch; the derived `(identity, role, channel)` route separates shared
mailboxes even when endpoint labels are reused. The envelope carries the full
seed and a canonical external-input frontier, and its injective encoding keeps
tuple/list/bytes distinctions intact through memory and AF_INET transport. A
receiver verifies the envelope digest, reconstructs the typed frontier, checks
the message route against the identity, and only then restores the seeded
system. This is the first system-level substrate for several emulated systems;
the next hypervisor boundary is authoritative admission of frontier progress,
stale-incarnation refusal, and live multi-system scheduling over these routes.

`HypervisorSeedAdmissionCoordinator` now turns that transit object into an
authority decision. It shares the kernel journal with the classifier
Hypervisor and is checkpointed inside `HeadlessOS`. Candidate seeds are
reconstructed and replayed in shadow before registration. A new system or
higher incarnation may enter the registry; within an incarnation, origin
identity is fixed, scheduler coordinate is monotone, and each source's maximal
input receipt cannot regress or change its digest at the same sequence. Frontier
growth must advance virtual time. The envelope fingerprint ledger returns the
original receipt for exact retransmission, while stale incarnations, conflicting
origins, invalid restores, and non-monotone frontiers produce journaled
refusals without changing the hosted system.

This is the first active Hypervisor process for encoded system state: seed bytes
are no longer only readable and routable, but are admitted into a persistent
registry under a replayable temporal law. The next boundary is live frontier
advancement from external inputs and shared scheduling of the admitted systems.

`SystemSeed.advance_input` now records the missing transition material. An
external event is a digest-bound `(source, sequence, pid, mailbox, values)`
product placed immediately before its target scheduler tick. Seed restoration
replays the event prefix from the origin; `at` and `rewind` remove only events
after the requested coordinate. `HypervisorSeedAdmissionCoordinator.advance_input`
derives that next state, appends its receipt frontier, and routes it through the
same shadow restore and monotone admission law. Exact input retransmission
reconstructs the original event-prefix receipt and returns the later
authoritative envelope unchanged, while a changed payload at the same source
sequence is refused. A future host-commit layer can now compare the restored
logical state with a live process before making a durable in-place mutation.

`HeadlessOS.commit_seed_input` now performs that comparison and local commit.
The live projected digest must equal the admitted seed before any input is
accepted. A shadow copy receives the event and advances to the target tick;
only an equal candidate digest permits the live host transition and subsequent
seed admission. A live mismatch or admission refusal restores the complete
checkpoint, and an exact duplicate is answered from the existing receipt
ledger without a second injection. The result is a local atomic host witness,
not yet a multi-host ownership protocol.
