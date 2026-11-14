# USM-002 — Model-issued E-CPU system calls

**Experiment.** This is the next use-the-system step after USM-001's model
inference, learning, and structural-memory interaction. A model in another
local Python process now **issues system-call requests**, rather than simply
returning a class probability that the host converts to a service call.

## Working contract

The receiver supplies a typed stage and a model checkpoint to the model
process, retaining the actual observation source and all authority:

```text
receiver-owned observed stream
     |
model process -- observe --> receiver returns a bounded witnessed window
     |
model process -- propose --> E-CPU trace recovery / Ground certificate /
                              authorized StructuralMemoryRegistry admission
     |
model process -- read(t) -> E-CPU revision-pinned Ground navigation /
                             verified read receipt
     |
append-only receiver journal -> digest-linked operation trace
```

The controller in this experiment is a trainable logistic classifier from
USM-001. In the `observed` phase, its actual inference selects `propose` or
`stop`. The other phases are a typed operating protocol: `observe` and
`read` represent actions requested by the model, not decisions invented by
the E-CPU host.

**This is neither a new OS kernel nor a security sandbox.** The worker runs as
a separate local Python interpreter, potentially with the same filesystem
permissions as its parent. The privilege separation demonstrated here is
the *software API* boundary: only the receiver has E-CPU registry objects,
admission policy, source samples, and read capabilities. A next step is to
enforce this separation with independent authenticated hosts.

## Run

From the E-CPU repository root:

```bash
python -m examples.model_system_calls
python -m pytest -q tests/test_model_system_calls.py
```

The host verifies exact session identity, ordered sequence number, previous
journal head, permitted operation, current phase, authorized Ground, and a
receiver-owned target coordinate. It rejects duplicate/cross-session calls
before executing any registry action.

A successful response includes the real registry's spec/certificate digests,
pinned revision, committed value, and read receipt ID. Model probability
does not grant rights. A model can defer or request a Ground; the E-CPU
certifier can reject a seemingly plausible but incorrect Ground.

Each session retains a SHA-256-linked event chain. The independent
`verify_system_call_trace` checks ordering, transitions, cross-session
identity, and integrity of that *record*. A digest does not authenticate a
remote witness, independently prove a law, or validate a model's quality.
The receiver's underlying StructuralMemoryCertificate remains the evidence
source for its admitted Ground.

## Tests and next questions

The tests exercise actual separate-process decisions, a distant coordinate
`1_000_000_000_137`, adversarial high-confidence model misclassification,
host authorization refusal, replay/cross-session attacks, capability
exclusion, target-coordinate rewriting, and trace manipulation.

This is an intentionally narrow model-native ABI for observation-derived
integer Grounds. The generalization path is to introduce a versioned
Ground-independent `observe / propose / navigate / verify / retain` interface;
persist and recover execution sessions together with receiver journals;
and admit authenticated remote model workers through E-CPU's existing
transport, authority and continuity layers. VGI can independently test
Ground interpretation; IFS can independently reconstruct the operation trace.

The more ambitious goal is an adapting model that operates E-CPU services and
constructs new suitable environments while remaining separately accountable
to observed evidence and the receiver's authority.
