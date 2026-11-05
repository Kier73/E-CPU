# Hypervisor-Owned Navigation Execution

## Purpose

Navigation admission ends with a bounded, journal-backed grant. This stage
consumes that grant and asks the host that owns the target state to commit the
derived transition path.

The sequence is:

~~~text
intent
  -> contextual and formal navigation
  -> hypervisor admission
  -> journal provenance verification
  -> live PID and capability revalidation
  -> live start-state and readiness revalidation
  -> exact deterministic path replay
  -> write-ahead execution intent
  -> backend atomic compare-and-swap
  -> final execution receipt
~~~

The executor does not interpret a grant as an instruction to mutate an
arbitrary kernel object. It is a constrained adapter around a trusted host
state provider and an atomic commit boundary.

## Host integration contract

Construction requires four inputs:

~~~python
HypervisorNavigationExecutionAdapter(
    operating_system,
    state_provider,
    commit_callback,
    commit_lookup,
)
~~~

### Live state provider

The provider has the form:

~~~python
state_provider(pid, descriptor, address) -> ProcessContext
~~~

It must return the current state and the same bindings, dependencies, resource
capacities, capability labels, search budgets, and temporal frame used to
coordinate the proposal. The executor compares the full context digest and
starting-state digest with the grant. Missing, stale, or differently scoped
context is refused.

### Atomic commit callback

The callback has the form:

~~~python
commit_callback(
    pid,
    execution_id,
    expected_start_state_digest,
    candidate_state,
    grant,
) -> NavigationCommitReceipt
~~~

The host owning the state must implement this as one atomic compare-and-swap:

1. Revalidate the PID, grant rights, grant time interval, and current backend
   state while holding the host's relevant transaction/serialization boundary.
2. Require the current state digest to equal
   expected_start_state_digest.
3. Apply the complete candidate state atomically, or apply nothing.
4. Persist an idempotency record keyed by execution_id in the same durable
   transaction as the state mutation.
5. Return the same durable receipt for every retry with that execution ID.

A rejected compare-and-swap returns a typed receipt with
committed=False. A callback exception is treated as an indeterminate outcome:
the adapter does not guess whether the backend mutated.

### Durable receipt lookup

The lookup has the form:

~~~python
commit_lookup(execution_id) -> NavigationCommitReceipt | None
~~~

It must retrieve the durable backend receipt by idempotency key without
performing a mutation. This is essential for recovering the crash window
between backend commit and publication of the final journal receipt.

The backend receipt binds the execution ID, starting and final state digests,
commit outcome, backend revision, and whether it was recovered as a replay.

## Admission provenance

Before path evaluation, the adapter verifies the complete hash chain and
requires all three journal records:

- hypervisor.decision with action=ALLOW, domain=CPU, and the same model
  revision as the grant;
- hypervisor.arbitration.accept with the grant's source, channel, sequence,
  decision receipt, fingerprint, and issue tick;
- hypervisor.navigation.admit whose stored grant projection and digest equal
  the supplied NavigationAdmissionResult.

The sequence order must be decision, arbitration acceptance, then admission.
A constructed grant or copied SHA-256 value without the corresponding verified
journal records cannot authorize execution.

## Live revalidation and deterministic replay

The executor rechecks:

- the kernel process still exists and has not exited;
- every required right still exists on that PID for the normalized resource;
- the scheduler tick remains inside the grant's half-open validity interval;
- descriptor, semantic address, process identity, full context, and starting
  state still match the grant;
- process readiness and declared invariants still hold;
- every admitted transition ID exists and is enabled in sequence;
- every per-transition resource requirement is covered by current capacity;
- the replayed path produces the exact target digest and the same resource
  envelope as the grant;
- the final state satisfies the semantic address goal.

No backend callback is invoked until this entire local replay succeeds.

## Write-ahead intent and crash recovery

The executor derives:

~~~text
execution_id = SHA256("mailcpu.navigation-execution.v1" || grant_digest)
~~~

It appends hypervisor.navigation.execute.begin before calling the backend.
The same execution ID is reused on every retry.

If an earlier begin record exists and there is no final execution receipt, the
adapter calls commit_lookup(execution_id) before attempting path replay:

- A durable committed receipt matching the grant is written into the journal
  as a recovered execution receipt. No transition is applied again.
- A durable rejected receipt remains a compare-and-swap conflict.
- No receipt means no committed operation is proven; the adapter proceeds only
  if the live state still matches the original starting state.
- An untyped, mismatched, or unavailable receipt produces an indeterminate or
  unverified outcome, never a fabricated success.

A completed hypervisor.navigation.execute.commit record is replayed directly.
The backend commit callback is not called again.

This gives effectively-once state mutation when the host satisfies the atomic
CAS plus durable-idempotency contract. A hash-chained journal alone cannot
provide exactly-once semantics for a separate mutable backend.

## Results and receipts

NavigationExecutionResult distinguishes:

- executed: first verified backend commit;
- replayed: completed journal receipt returned without another backend call;
- recovered: durable backend commit found after a process-loss window and
  reconciled into the journal;
- typed refusals for provenance, process, rights, expiry, context, or path;
- compare-and-swap conflict;
- commit unverified or indeterminate outcomes requiring backend reconciliation.

The backend NavigationCommitReceipt and the journal execution receipt are
separate evidence. A successful result contains both. Refusals and uncertain
outcomes carry a general journal receipt where the journal remains valid.

## Deliberate scope boundary

This adapter executes declarative TransitionRule state transformations only.
It does not claim that an arbitrary declarative state is the native CPU
register file, filesystem tree, process table, service state, or GPU memory.
A native subsystem must provide its own state projection and transactional
commit implementation before its state can be safely navigated this way.

The next integration step is to build specific state providers and commit
backends for one native MailCPU subsystem at a time, preserving its existing
kernel and transaction invariants.
