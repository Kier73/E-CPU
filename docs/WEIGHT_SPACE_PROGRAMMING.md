# Weight-space programming: exact Boolean seed

## Scope

`mailcpu.weight_space` is a constructive, deterministic realization of a bounded computational specification as neural-network parameters. It is a first experiment in hand-creating model weights, not a general neural-network compiler, optimizer, training system, or reverse interpreter.

The supported function family is intentionally small: two-input XOR and AND over the complete Boolean domain \(\{0,1\}^2\). The target architecture is the dense 2–85–112–1 multilayer perceptron with ReLU hidden layers and a linear output.

## Construction

All matrices are stored output-major. Every layer includes a bias for each output unit. Therefore:

\[
(2+1)85 + (85+1)112 + (112+1)1
=255+9632+113
=10{,}000.
\]

The generator starts all entries at zero, then assigns a small number of coefficients:

First hidden layer:

\[
h_0=\operatorname{ReLU}(a+b),\qquad
h_1=\operatorname{ReLU}(a+b-1).
\]

The remaining 83 units are zero. For binary inputs, \(h_1=a\land b\).

The second hidden layer copies \(h_0\) and \(h_1\) into its first two units; its remaining 110 units are zero.

The linear output is:

\[
y_{xor}=h_0-2h_1,\qquad y_{and}=h_1.
\]

For all four input pairs, these equations return the exact Boolean XOR and AND values. The network therefore has 10,000 declared parameters but only nine nonzero entries for XOR and eight for AND. The difference between parameter count and active parameter count is deliberate and is exposed by the API.

## Semantic intervention

`edit_boolean_gate(model, "and")` changes only the final output coefficients:

\[
(W_{out,0},W_{out,1}):(1,-2)\longrightarrow(0,1).
\]

The returned `ParameterIntervention` identifies the source and target model digests and the exact two tensor coordinates. The edit refuses to operate if the network no longer matches its declared compiler template. Repeating the same target edit is idempotent and reports zero changed parameters.

The model snapshot contains its schema, architecture, activation contract, gate label, full tensors, parameter count, and digest. Snapshot restoration checks dimensions, finite values, declared count, and digest. Snapshot data is detached from the live model so a caller cannot mutate the model by editing a returned dictionary.

## Independent executable representation

`boolean_gate_program` creates a MailCPU reference program for the same function:

- AND uses `MUL` over binary integer registers.
- XOR compares the two input registers and branches to a constant output.

The test suite compares the neural output with both `ReferenceInterpreter` and `QueueInterpreter` over all four input combinations. It also builds an E-CPU `TranslationContract` for each case and checks exact equality of the declared output projection. These paired checks establish equivalence for each recorded case; they are not a universal proof about all inputs or all models.

## Connection to VGI

VGI's existing `Z/8Z` Ground contains a Boolean subgroup under the embedding:

\[
0\mapsto0,\qquad1\mapsto4.
\]

Then:

\[
4a+4b\pmod 8=4(a\oplus b).
\]

The VGI experiment uses `ADD` for XOR and an equality/conditional expression for AND. It does not add a multiplication opcode to VGI or change its value algebra. Its finite test suite checks all four inputs with differing observer coordinates.

## Relationship to existing E-CPU model components

This module is separate from `ProceduralDecisionModel`, which computes an addressable deterministic decision field without allocating a dense tensor, and `DistilledRungHead`, which provides an advisory classifier head whose output is gated by deterministic law recovery. The new module addresses a different question: can a specified finite function be written directly into an explicit dense neural parameterization, inspected, and modified locally?

## Reproduction

From the E-CPU repository:

```bash
python -m pytest tests/test_weight_space.py -q
```

For the VGI tests, run `python -m unittest discover -s tests -p 'test_boolean_subgroup.py' -v` from the `virtual_ground_interpreter` package directory.

## Limitations and next experiments

This exact compiler exploits known algebraic structure in a four-case problem. It does not show that an arbitrary algorithm, a learned statistical pattern, or a pretrained network can be compiled to weights. It does not test generalization, noisy inputs, numerical quantization, model acceleration, or physical hardware.

The next useful increase in difficulty is to replace the hand-shaped Boolean features with a small finite-state transition function whose hidden representation is not directly supplied. The compiler should still expose a semantic reference, a target architecture, all active parameters, a bounded input domain, and an independent verifier. A later experiment can compare multiple architectures for the same specification rather than merely increasing parameter count.
