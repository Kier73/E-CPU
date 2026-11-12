# Weight-space programming: exact Boolean seed

## Scope

`mailcpu.weight_space` is a constructive, deterministic realization of a bounded computational specification as neural-network parameters. It is a first experiment in hand-creating model weights, not a general neural-network compiler, optimizer, training system, or reverse interpreter.

The supported function family is intentionally small: two-input XOR and AND over the complete Boolean domain \\(\\{0,1\\}^2\\). The compiler supports two distinct dense ReLU architectures, each with exactly 10,000 parameters:

- Two hidden layers: `2–85–112–1`.
- Three hidden layers: `2–17–254–21–1`.

Both use ReLU hidden activations and a linear output layer.

## Parameter accounting

All matrices are stored output-major. Every layer includes one bias per output unit. For `2–85–112–1`:

\\[
(2+1)85 + (85+1)112 + (112+1)1
=255+9632+113
=10{,}000.
\\]

For `2–17–254–21–1`:

\\[
(2+1)17 + (17+1)254 + (254+1)21 + (21+1)1
=51+4572+5355+22
=10{,}000.
\\]

## Shared computational structure

Both architectures implement the same two hidden features:

\\[
h_0=\\operatorname{ReLU}(a+b),\\qquad
h_1=\\operatorname{ReLU}(a+b-1).
\\]

For binary inputs, \\(h_1=a\\land b\\). Every additional hidden layer copies the first two nonnegative features into its first two units; all remaining coefficients are zero. The final linear output is:

\\[
y_{xor}=h_0-2h_1,\\qquad y_{and}=h_1.
\\]

For all four input pairs, these equations return exact Boolean XOR and AND values in both architectures. Each network has 10,000 declared weights and biases, but only nine nonzero entries for XOR and eight for AND. Total and active counts are both exposed in the API.

## Semantic intervention

`edit_boolean_gate(model, "and")` changes only the final output coefficients:

\\[
(W_{out,0},W_{out,1}):(1,-2)\\longrightarrow(0,1).
\\]

It changes two weights in either architecture: matrix layer 2 for `2–85–112–1`, and matrix layer 3 for `2–17–254–21–1`. The returned `ParameterIntervention` identifies source and target model digests and the exact tensor coordinates. The edit refuses to operate if the network no longer matches the compiler template. Repeating the same target edit is idempotent and reports zero changed parameters.

Snapshots contain schema, architecture, activation contract, gate label, full tensors, parameter count, and digest. Restoration checks architecture, dimensions, finite values, count, and digest. Snapshot data is detached from the live model.

## Independent executable representation

`boolean_gate_program` creates a MailCPU program for the same function:

- AND uses `MUL` over binary integer registers.
- XOR compares the two input registers and branches to a constant output.

Tests compare each neural architecture with the MailCPU reference and queue interpreters over all four input combinations. They also create E-CPU `TranslationContract` records for each case and check exact equality of the declared output projection. Those paired checks are scoped to each recorded case, not a universal proof about all possible inputs or models.

## Connection to VGI

VGI's existing `Z/8Z` Ground contains a Boolean subgroup under the embedding:

\\[
0\\mapsto0,\\qquad1\\mapsto4.
\\]

Then:

\\[
4a+4b\\pmod 8=4(a\\oplus b).
\\]

The VGI experiment uses `ADD` for XOR and an equality/conditional expression for AND. It does not add a multiplication opcode to VGI or change its value algebra. Its finite test suite checks all four inputs with differing observer coordinates.

## Relationship to existing E-CPU model components

This module is separate from `ProceduralDecisionModel`, which computes an addressable deterministic decision field without allocating a dense tensor, and `DistilledRungHead`, an advisory classifier head whose output is gated by deterministic law recovery. This module addresses another question: can a finite function be written directly into distinct explicit neural parameter layouts, inspected, and locally edited without training?

## Reproduction

From the E-CPU repository:

```bash
python -m pytest tests/test_weight_space.py -q
```

For the VGI tests, run `python -m unittest discover -s tests -p 'test_boolean_subgroup.py' -v` from the `virtual_ground_interpreter` package directory.

## Limits and next experiment

This compiler exploits known algebraic structure in a four-case problem. It does not show that an arbitrary algorithm, learned statistical pattern, or pretrained network can be compiled to weights. It does not test generalization, noisy inputs, numerical quantization, model acceleration, or physical hardware.

The next increase in difficulty is a finite-state transition computation whose hidden representation is not supplied directly. The compiler should preserve an independent semantic reference, declared target architectures, active-parameter accounting, a bounded input domain, and independent verification. A further experiment can then compare architecture families and intervention costs while holding the computation fixed.
