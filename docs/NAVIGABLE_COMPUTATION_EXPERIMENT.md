# Navigable Computation: Vertical Integration Experiment

## Purpose

This experiment composes four existing E-CPU capabilities into one bounded
workload:

1. Structural Memory resolves one coordinate from an admitted immutable
   revision at the receiver.
2. The returned, oracle-checked receipt supplies a literal operand to a
   second Transit CPU request.
3. A paired translation contract connects the exact Structural Memory receipt
   representation to the exact receiver-authorized CPU request. The committed
   CPU result is ingested as the next edge with its independent oracle evidence.
4. The evidence-path resolver searches the exact two-edge route under live
   receiver capabilities, explicit cost units, aggregate ceilings, and finite
   search budgets.

The workload is deliberately small. Its purpose is to verify composition and
refusal boundaries, not to establish a performance advantage or a general
model-hosting capability.

## Workload

The test admits the modular integer recurrence

\[
x_t=(7+5t)\bmod 97
\]

under context {tenant: alpha, partition: 4}. At coordinate \(t=17\), the
receiver returns \(x_{17}=92\) with a receipt bound to the exact memory ID,
revision, context, coordinate, specification digest, and certificate digest.

The client then constructs the pure CPU program:

    set memory_value 92
    set offset 8
    add answer memory_value offset
    halt

The receiver executes it through the existing Transit worker. The independent
CPU oracle checks the bounded arithmetic observation before the hypervisor
commits the effect. The expected result is answer = 100.

The test uses loopback TCP operation and result channels. The Structural
Memory read and CPU computation are separate authorized operations; the CPU
request does not carry a sender-supplied grant.

## Representation route

The route contains two exact content-addressed edges:

| Edge | Source | Target | Evidence |
|---|---|---|---|
| 1 | Structural Memory read receipt | Receiver-authorized CPU request | Successful paired observation of the embedded immediate |
| 2 | Receiver-authorized CPU request | Committed CPU handler effect | Transit translation evidence plus independent CPU oracle |

The first edge's mapping identity binds the receipt digest and exact CPU
request. Its observation compares the read value with the literal operand
embedded in the CPU program. The second edge is accepted only from the typed
receiver-committed execution result.

The route request explicitly supplies the prerequisite and invariant digests
for both edges. These are caller-asserted facts whose identities the resolver
checks; this test's construction and assertions establish the stated
one-case relation. The resolver does not authenticate arbitrary caller claims.

The receiver process must possess both the Structural Memory read capability
and CPU execute capability. Costs are declared test inputs, not measured
latency or energy:

- receipt-to-request mapping: 4 us, 12 nJ;
- CPU execution edge: 18 us, 240 nJ;
- route ceiling: 30 us, 300 nJ.

The selected path therefore has a declared total of 22 us and 252 nJ. These
figures exercise the multidimensional cost model and are not benchmark data.

## Replay and retained identity

The same CPU request is sent again under a new transport frame. The worker
must return the exact committed effect and evidence without invoking the CPU
backend a second time. The test also serializes and restores the evidence-path
catalogue and requires its digest to remain identical.

Structural Memory revisions and read receipts, as well as the worker's
semantic execution ledger, remain governed by their existing checkpoint and
journal contracts. This experiment checks the journal chain and same-process
semantic replay; it does not yet perform a combined process-restart test across
the complete two-operation workload and route catalogue.

## Falsifiable checks

The test fails unless all of the following hold:

- the Structural Memory read is admitted under receiver-local read authority;
- the returned coordinate equals the recurrence's expected value and carries
  the exact revision/certificate identity;
- Structural Memory and CPU oracle evidence both agree and remain within
  their declared work limits;
- the embedded CPU immediate equals the verified receipt value;
- the two route edges join by complete representation identity;
- the route satisfies both live capability requirements and aggregate cost
  ceilings;
- the resolver returns a non-authoritative two-edge proposal;
- replay returns identical effect/evidence without a second CPU backend call;
- the route catalogue round-trips without changing its digest; and
- the kernel event journal verifies.

A follow-up negative test should mutate the embedded literal or remove either
live capability and require the translation comparison or route search to
refuse the path.

## Boundaries

This is one finite deterministic arithmetic workload over one admitted
Structural Memory family. It does not demonstrate arbitrary translation,
universal equivalence, measured energy or latency, GPU acceleration, language
model hosting, distributed catalogue replication, multi-edge route execution,
or atomic recovery across an arbitrary external side effect.

The route remains a non-authoritative proposal. Every operation is separately
admitted and executed by the receiver's existing hypervisor boundary.

## Run

    python -m pytest tests/test_navigable_computation.py -q
    python scripts/verify_repo.py
    python scripts/verify_invariants.py

The full repository CI matrix remains the merge gate.
