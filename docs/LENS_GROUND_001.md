# LENS-001 — Reversible observation frames as admitted Structural Memory

**Status:** first integrated vertical slice; witness-grounded, not a universal
law prover and not yet a cross-host network demonstration.

## Problem and relation to the lattice experiment

The external lens-lattice experiment explored Gray frames, rotations,
bit reversal, byte swapping, Newton ladders, CRT-time decomposition,
2-adic logarithms, and GF(2) word recurrences. It reported seven additional
families fitting sixty reserved observations. Those results are an experimental
input, not an E-CPU admission authority.

LENS-001 implements **one deployable subset**: bounded reversible 64-bit
value frames composed with the **existing** affine modular law. E-CPU can
observe an orbit `x(t)`, discover an admissible representation `P` in which
`y(t)=P(x(t))` obeys `y(t+1)=a*y(t)+c (mod 2^64)`, and later directly
navigate `x(t)=P^-1(y(t))`. No intermediate orbit states are materialized.

## Implementation

- `mailcpu/lens_ground.py`: strictly typed `lens64` parameter ABI
  (`width, frames, a, c, x0`); whitelisted invertible Gray, bit reversal,
  byte reversal, and fixed rotation frames; deterministic bounded depth 1–2
  search; reuse of `law_certifier.fit_affine` and `lcg_navigate`.
- `mailcpu/law_certifier.py`: `Law.navigate` and `Law.find` dispatch
  to the lens implementation. Direct inverse accepts only modular increments
  or the full-period 2-adic affine case; it never invokes unbounded BSGS.
- `mailcpu/structural_memory.py`: opt-in `propose_trace(..., allow_lens=True)`
  only **after** the original certifier declines a trace as TAPE. Serialized
  lens parameters pass a closed whitelist, versioned Ground admission,
  independent witness re-evaluation, read receipts, and snapshots via the
  same existing registry. Default `allow_lens=False` preserves legacy behavior.
- `mailcpu/observer_orbit.py` and `mailcpu/composed_ground.py`:
  register the declared direct-navigation cost; observer inverse uses the
  same bounded conditions and independent forward check.

A `lens64` descriptor is data, **never executable code**. It cannot add a
new privilege, host, predicate, or unbounded search operation. Ordinary
receiver-owned Structural Memory admission is still required.

## Minimal example

```python
from mailcpu.lens_ground import transform
from mailcpu.structural_memory import StructuralMemoryRegistry

origin = (1 << 40) + 23
trace = [transform((origin + i) % (1 << 64), "gray.encode") for i in range(120)]
registry = StructuralMemoryRegistry(admission_policy=lambda proposal: True)
proposal = registry.propose_trace(
    "gray-stream", trace[:80], trace[80:], allow_lens=True,
    context={"source": "bounded-synthetic-gray"},
)
version = registry.admit(proposal.proposal_id, expected_revision=0)
t = (1 << 50) + 987
receipt = registry.read_revision(
    "gray-stream", version.spec.revision, t,
    context={"source": "bounded-synthetic-gray"},
)
expected = transform((origin + t) % (1 << 64), "gray.encode")
assert receipt.value == expected
assert receipt.spec_digest == version.spec.digest
```

## Verification and epistemic status

`python -m pytest -q tests/test_lens_ground.py` exercises frame
bijections, one- and two-frame orbit identification, far navigation,
direct inverse, reserved-probe tampering, random refusal, explicit opt-in,
admission and receipt identity, checkpoint reconstruction, malformed
descriptors, and PREFIX-GROUND escape refusal.

The model coefficients are fitted **only on the training window**;
the withheld suffix is used for candidate selection. Therefore the
withheld suffix is a finite agreement check, **not** an independent
post-selection replication set. A long-horizon seek without an external
oracle remains a prediction under the admitted model, not a measured state.

All admitted parameters are anchored to the full 64-bit word ring.
The width is a specified representation assumption, not inferred from an
observed rollover. The `GROUND` label retains the established E-CPU
finite-witness meaning, not a claim of universal equivalence.

## Next build checkpoints

1. Add a *third*, untouched validation set or independent generated
   coordinate oracle, algebraic conjugacy witnesses, and adversarial
   counterexamples beyond the original training range.
2. Implement additional **typed** ladders, CRT-time and word-GF(2)
   generators only where existing E-CPU operations cannot already express
   them. Do not substitute interleaving mixture for additive CRT-time.
3. Carry exact Ground/representation digests across authenticated
   observer-hosts, with receiver-owned admission and independent result
   verification; demonstrate kill/rehome/recovery.
4. Use admitted word-navigation as a synthetic addressable parameter
   field in E-GPU/SIMT experiments; measure description overhead,
   host work, transport latency and amortized repeated reads.

The current code does not claim that an arbitrary pretrained neural model
can be reconstructed from its architecture or that a passive network path
has become a compute processor.
