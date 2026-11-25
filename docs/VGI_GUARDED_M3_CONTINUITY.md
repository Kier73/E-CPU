# VGI guarded computation as durable E-CPU process state

## Capability

A mathematically certified VGI quotient is the **current active state** of an E-CPU computational session. Its coordinates, current Ground stage and proof-carrying transition evidence are encoded in immutable M1 pages, published through native M3 quorum checkpoints and advanced only by the existing M4 CAS transition adapter. Source modules are locally installed and pinned to the VGI commit `39a169b21513ffaaee85e40826c706c07a47215b` using `mailcpu.vgi_guarded_runtime`.

The previous M2 host interface (`vgi.guarded.execute`) still handles one-shot pure mathematical execution with Hypervisor authority. The new module composes that admitted mathematical implementation with persistent M3 state and receiver-local M4 execution. It does **not** accept arbitrary Python in a workload or replace E-CPU's checkpoint, object-store, quorum, or process mechanisms.

## State and transition

State schema: `mailcpu.vgi.guarded.reduced-session.v1`

```json
{"schema":"mailcpu.vgi.guarded.reduced-session.v1","program":"sha256...","stage":0,"coordinates":[0,1],"virtual_steps":"16","last_event":{"kind":"advance","receipt":"...","predecessor_checkpoint":"...","predecessor_lineage":"..."}}
```

The example above is schematic; production advance receipts are structured VGI objects, not strings. `GuardedProgram.admit(((source, certificate), ...))` independently checks all VGI stage certificates. It binds the fixed catalogue of permitted stages, observations and dynamics to a SHA-256 interpretation fingerprint. Each transition checks that M4's `ComputationalTransitionContext.interpretation_fingerprint` matches this program. M3 also pins the state schema, M2 artifact manifest, backend identity, predecessor checkpoint and quorum lineage root.

An M4 input may request:

- `advance`: at most 128 action symbols; VGI executes and independently replays the receipt. M3 commits the updated quotient state and exact receipt under one operation ID.
- `migrate`: exactly the next pre-admitted observer Ground. A **receiver-installed** checkpoint-keyed source observer returns an immutable source snapshot for that committed revision. The backend checks its predecessor checkpoint digest and consistency with the old quotient, computes the *only* necessary new probe rows, constructs the new coordinates and records a recheckable migration witness. A remote workload cannot supply either a Python callback or probe values.
- `jump`: a decimal bounded macro count, with VGI's invariant-branch proof; stores starting coordinates and step count so a later receiver can reconstruct the jump.

The same proof-carrying state is checked when loaded again. Every update goes through `ComputationalSessionTransitionAdapter.apply`, which computes the input digest, verifies the M3 high-water, constructs a trusted context, applies the deterministic backend, then calls native `ComputationalSessionStore.commit_state(...)`. Exact retries return the committed result, competing writers are rejected, and partial quorum commits must be resumed using native `resume_pending()` rather than invented transitions.

The mathematical equivalence is observation-relative, not a claim that an arbitrary nonlinear Python program has been optimized. State reduction lowers resident representation; real-world speed depends on verification, source-admission and I/O costs.

## Process transfer

The stand-alone example uses two independent Python processes:

```bash
python -m pip install -e . pytest
python -m pip install -e ../Virtual-Ground-Interpreter/virtual_ground_interpreter
python examples/vgi_guarded_recovery_demo.py bootstrap /tmp/vgi-m3
python examples/vgi_guarded_recovery_demo.py resume /tmp/vgi-m3
```

Process A executes 16 guarded steps and commits revision 2; process B imports the same M3 checkpoint and quorum proof after **separately re-admitting** its M1 state bytes, migrates using one new receiver-local observation, executes 7 further steps, and commits revision 4. Because authority journals are durable, a new process can reopen and re-verify the same quorum lineage rather than trusting a serialized receipt. The test passes the local source snapshot through a file fixture to model a checkpoint-scoped receiver observer; **that file is not a signed or network-attested source**. No real external peer-to-peer TLS transfer is claimed.

## Evidence and adversarial checks

- Reopened authority journals, independent M1 page stores, distinct receiving process IDs and monotone M3 revisions.
- Exact-retry idempotence, stale-revision rejection and conflicting operation-ID rejection.
- A mathematically correct probe at the **wrong** checkpoint is rejected.
- A checkpoint-matched but contradictory full source observation is rejected.
- Corrupted M1 page data prevents checkpoint recovery.
- Old exports are rejected after newer quorum commits.
- Loaded VGI execution, migration, and jump evidence is independently reconstructed.

**Remaining frontier:** verify a source observation received from a distinct authenticated E-CPU host under its M3 state/epoch, connect the observation event to the same quorum lineage via signed receiver policy or independently reconstructed durable source bytes, and then route migration over the existing mTLS computational fabric. The receiver-local callback is a precise interface for that next step, not a substitute for remote authorization.
