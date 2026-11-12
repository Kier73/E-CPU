# Stateful transition runtime

## Purpose

`mailcpu.stateful_transition.StatefulTransitionRuntime` turns a typed finite Boolean transition program and its liveness-compiled ReLU realization into a small stateful execution object.

It keeps four concepts distinct:
1. **State:** the live values carried between logical ticks.
2. **Time:** the monotone transition tick, advanced only by a committed step.
3. **Model revision:** the version of the typed transition program and compiled neural weights.
4. **History:** an append-only digest-linked sequence of steps and revisions.

The runtime does not train or infer a new program. A proposed revision is an explicit typed transition program and must compile successfully before it is installed.

## Construction and stepping

The runtime accepts:
- A `FiniteTransitionProgram`.
- An initial state vector.
- The ordered names of the program inputs that represent state registers.

All other declared inputs are controls supplied on every step. Program outputs replace the state vector in output-name order. The number of state inputs must equal the number of output bits.

For a two-bit counter, the live input vector is:

[
(state_1,state_0,advance,reset)
]

and the output vector is:

[
(next_state_1,next_state_0).
]

Each step forms one complete input mapping, evaluates the typed source expression and active ReLU model, and requires exact equality between their Boolean outputs before state or tick changes. A mismatch fails closed.

The returned `TransitionStep` identifies the new tick, revision, state, source-program digest, model digest, and committed event digest.

## Revision continuity

`revise(target_program)` requires the target to preserve the exact ordered input and output names. It compiles the target into a liveness-compacted ReLU model and exhaustively verifies the finite Boolean domain before any runtime fields change.

A successful revision:
- preserves the current state vector;
- preserves the logical tick;
- increments the model revision counter;
- records source and target program digests;
- records source and target model digests;
- stores the typed target program in the revision event so replay can reconstruct it.

No-op revisions and interface changes are rejected. A compilation failure leaves the active program, model, state, tick, revision, and event history unchanged.

## Event chain

Each committed step or revision appends one event. An event includes a contiguous sequence number and the digest of its predecessor. The event digest is:

[
d_i=SHA256(CanonicalJSON(payload_i))
]

where the payload includes `previous_event_digest` and all event-specific fields. The genesis digest binds the initial state, initial program digest, initial model digest, state-register names, schema, and compiler identity.

Step events include the full ordered input mapping, controls, before/after state, tick, model revision, and source/model digests. Revision events include the preserved state and the complete target program representation.

The event accessor returns detached copies. Mutating a returned event cannot modify the runtime's internal log.

## Snapshot and replay

`snapshot()` exports the initial program, current program, current model snapshot, initial and current state, counters, complete event list, genesis digest, and current chain head.

`StatefulTransitionRuntime.from_snapshot(snapshot)` does not merely trust the recorded final state. It:
1. Reconstructs the initial runtime and checks the genesis digest.
2. Replays every step using the controls recorded in the event.
3. Replays every revision by restoring and compiling its recorded typed program.
4. Regenerates and compares each event and digest.
5. Confirms the final program, model snapshot, state, tick, revision, and chain head.

A changed event payload, reordered/removed event, altered model snapshot, or incorrect terminal state is rejected.

Snapshots are versioned and tied to the named compiler identity. They are replayable evidence for this implementation version, not a guarantee that an arbitrary future compiler will reproduce identical weights.

## Verification

`tests/test_stateful_transition.py` checks:
- all 16 single-step combinations of two state bits and two controls;
- state and tick continuity across a model revision;
- the revised one-row exception becoming active after patching;
- snapshot round-trip after multiple steps and a revision;
- altered, reordered, or removed event rejection;
- revision interface and no-op rejection;
- strict bit and control validation;
- detached event access.

The cross-repository IFS experiment adds a revision-continuity scenario in which the current machine holds state `01`, accepts a new transition program without changing state/tick, then uses the revised law for the next transition. VGI Signal8 and both MailCPU interpreters independently check the resulting output.

## Limits

The runtime is a deterministic Boolean-state execution object. It does not implement concurrent mutation, durable storage, signatures, distributed consensus, hardware atomicity, learned updates, or rollback across external side effects. SHA-256 event chaining detects accidental or unsophisticated tampering when the chain head is trusted; it is not a digital signature or an external trust anchor.
