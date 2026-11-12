# Sparse finite-transition ReLU realization

## Purpose

SparseTransitionReLUNetwork is an executable sparse representation derived from an existing exact finite Boolean transition ReLU model. It does not replace the dense compilers. The dense model remains the semantic source against which sparse conversion and execution are checked.

The first implementation supports both:
- TransitionReLUNetwork, compiled from a complete finite transition table;
- CompositionalTransitionReLUNetwork, produced by either direct-DAG or liveness-compacted DAG compilation.

It is a sparse execution representation, not a new Boolean compiler or training procedure.

## Construction

~~~python
from mailcpu.transition_space import (
    SparseTransitionReLUNetwork,
    compile_live_compositional_transition_program,
    two_bit_counter_program,
)

program = two_bit_counter_program()
dense = compile_live_compositional_transition_program(program)
sparse = SparseTransitionReLUNetwork.from_dense(dense)

for row in program.to_table().rows:
    assert sparse.predict(row.inputs) == dense.predict(row.inputs)

restored = SparseTransitionReLUNetwork.from_snapshot(sparse.snapshot())
assert restored.digest == sparse.digest
~~~

Conversion preserves:
- the declared input and output register names;
- exact architecture and layer order;
- the source table or typed-program digest;
- the digest of the exact dense model from which it was derived.

A source identity is not inferred from tensor shape. from_dense accepts only the two declared dense transition-network classes.

## Sparse storage and execution semantics

The dense networks use output-major matrices. The sparse form stores, for each output neuron, an ordered sequence of (input_index, weight) pairs, omitting every coefficient equal to zero. Biases are stored as ordered (output_index, bias) pairs, also omitting zero values.

For output neuron \(j\) in layer \(\ell\), sparse execution evaluates

\[
z^{(\ell)}_j
=
b^{(\ell)}_j
+
\sum_{(i,w)\in E^{(\ell)}_j}
w\,a^{(\ell-1)}_i,
\qquad
a^{(\ell)}_j=\max(0,z^{(\ell)}_j)
\]

for hidden layers, with the final layer left linear. Here \(E^{(\ell)}_j\) contains only nonzero stored weights and is ordered by ascending input index.

The sparse implementation still materializes the activation vector for every neuron in each layer. The current change sparsifies weight storage and weight arithmetic; it does not yet provide sparse activation vectors, sparse layer widths, packed bit execution, quantization, or a hardware-specific kernel.

## Explicit cost dimensions

| Field | Meaning |
|---|---|
| dense_equivalent_parameter_count | Weight and bias slots in the equivalent dense architecture, including zero values |
| stored_weight_count | Nonzero weights physically represented in the sparse payload |
| stored_bias_count | Nonzero biases physically represented in the sparse payload |
| stored_parameter_count | Sum of stored nonzero weights and biases |
| dense_weight_slot_count | Weight slots in the dense architecture |

operation_profile reports:
- dense versus sparse weight multiplication counts;
- dense versus sparse accumulator-addition counts;
- the same hidden ReLU count for each representation.

For a dense row with \(n\) input coefficients, the dense implementation multiplies all \(n\) coefficients (including zeros). The corresponding sum has \(n-1\) additions, followed by one bias addition, so the reported total is \(n\) accumulator additions. A sparse row with \(k\) stored weights performs \(k\) multiplications and \(k\) accumulator additions when \(k>0\). An all-zero row still combines its bias with zero and therefore counts one addition.

These are structural operation counts for the current Python implementations. They are not measured wall-clock time, CPU instruction counts, GPU kernel work, memory-controller traffic, or end-to-end E-CPU cost.

## Integrity and validation

The sparse snapshot uses schema mailcpu.sparse-transition-relu.v1. It includes:
- source kind, source digest, and dense source-model digest;
- interface and architecture;
- strictly ordered, nonzero sparse weight and bias entries;
- dense-equivalent and stored parameter counts;
- a canonical SHA-256 digest over the complete sparse payload.

Restore rejects changed fields, unsupported source kinds, non-finite parameters, stored zero coefficients, duplicate or unsorted indices, out-of-range references, count mismatches, and digest mismatches.

predict validates Boolean inputs and requires exact Boolean outputs. The dense/sparse equivalence suite exhausts the counter, a one-row intervention, and the deterministic generated 24-program Boolean corpus across all three dense compiler routes.

## Evidence boundary and next measurements

Passing the finite tests establishes equivalence only for the tested programs and their complete declared Boolean domains. The class can evaluate finite numeric inputs through forward, but this transition experiment does not certify equivalence over all real-valued inputs or all floating-point edge cases.

A separate cross-representation experiment should measure:
1. serialized dense and sparse snapshot sizes;
2. sparse stored parameter counts and operation profiles;
3. conversion cost separately from inference cost;
4. warm and repeated dense/sparse inference timings on an identified host;
5. exact output equality and any numeric discrepancies;
6. whether Python object overhead offsets serialized-size reductions.

The first measurements should remain descriptive and host-specific. A sparse weight count does not by itself establish lower latency or lower resident memory.
