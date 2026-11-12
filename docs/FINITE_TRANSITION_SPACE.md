# Finite transition-table neural compiler

## Purpose

`mailcpu.transition_space` takes a complete Boolean transition table and deterministically realizes it as a dense ReLU network. It is a separate capability from the earlier XOR/AND gate compiler: the source representation is now a total relation over state and control bits.

A table declares ordered input and output register names and exactly one output row for every Boolean input pattern. The implementation currently bounds input width at eight bits, making the minterm count at most 256.

## Minterm construction

For each input pattern (r\in\{0,1\}^n), construct one hidden unit:

\[
h_r(x)=\operatorname{ReLU}\left(
\sum_{i:r_i=1}x_i+
\sum_{i:r_i=0}(1-x_i)-(n-1)
\right).
\]

If (x=r), every literal equals one and (h_r(x)=1). If (x\ne r), at least one literal is zero, so the sum is at most (n-1) and (h_r(x)=0).

The hidden layer is therefore an exact one-hot encoding of the complete input row. For output bit (j):

\[
y_j(x)=\sum_{r:F_j(r)=1}h_r(x).
\]

Because exactly one minterm is active on a Boolean input, the linear output equals the truth-table output bit exactly.

For row (r), the actual affine coefficients are:

- (w_i=+1) when (r_i=1), otherwise (w_i=-1).
- (b=1-\sum_i r_i).

Every added hidden layer is an identity-copy layer over the minterm vector. This allows multiple architectures to carry the same exact representation.

## Counter example

`two_bit_counter_table()` defines the complete 16-row transition function:

\[
s'=
\begin{cases}
0 & reset=1,\\
(s+1)\bmod4 & reset=0\land advance=1,\\
s & reset=0\land advance=0.
\end{cases}
\]

Inputs are ordered `state_1, state_0, advance, reset`; outputs are `next_state_1, next_state_0`.

Two architectures are tested:

| Architecture | Parameters |
|---|---:|
| `4–16–2` | 114 |
| `4–16–16–2` | 386 |

The count includes every dense weight and bias, including zero-valued entries.

## Intervention model

`apply_table_intervention(model, source_table, target_table)` requires the model's source-table digest to match the supplied source table, the same input/output interface and row keys, and tensors equal to a fresh compilation of that source table.

It then modifies only the output-layer coefficient for each table cell whose output bit changed. The returned record binds source and target table digests, source and target model digests, and exact weight coordinates. This makes the change inspectable and rejects unrelated or externally mutated parameter tensors.

In the experiment, one row changes:

\[
(0,1,1,1):(0,0)\longrightarrow(1,0).
\]

Only one output bit changes on that row, so exactly one final-layer weight changes. All fifteen other rows are rechecked.

## Independent MailCPU reference

`compile_transition_program(table)` converts each table row to a conjunction of literals. It computes complements as (1-x_i), multiplies the row's literals into a match register, and branches to a dedicated output block when the conjunction is one. Exactly one branch matches for every valid Boolean input. An explicit default block defines the result for unmatched inputs, which are outside the stated table domain.

## Verification

`tests/test_transition_space.py` exhausts the 16 rows through both MailCPU backends, tests both neural architectures, verifies the local one-weight intervention and confirms snapshot digest validation.

The cross-repository experiment adds VGI's typed equality/conditional task as a third semantic reference and attaches an E-CPU `TranslationContract` to each individual neural/reference comparison.

## Limits

This is exact finite-domain compilation. The hidden width equals (2^n), so this realization grows exponentially with input width. It is not an efficient compiler for large Boolean functions, a learned model, a continuous-domain approximator, or a proof of general neural synthesis. A subsequent compiler should seek structured decision graphs or compositional Boolean programs whose active representation can remain sparse without enumerating every input row.

## Compositional typed source program

The compiler can now start one level above the table. `FiniteTransitionProgram` is a typed Boolean expression tree with input, constant, NOT, AND, XOR, and conditional-select nodes. It evaluates one input vector and can enumerate its complete finite table with `to_table()`.

`two_bit_counter_program()` expresses the source law compositionally:

- Reset selects the zero state.
- Otherwise, advance selects `state_1 XOR state_0` and `NOT state_0`.
- Otherwise, both state bits are held.

The table compiler consumes the generated table, while `compile_transition_program(table)` independently lowers the table into MailCPU minterm branches. This creates the path:

```
Typed Boolean transition program
        ↓ exhaustive finite evaluation
Complete transition table
        ├──→ ReLU weight compiler
        └──→ MailCPU reference-program compiler
```

The typed program also supports `with_row_output(inputs, outputs)`, which composes a single-row conditional override around the existing outputs. The integration experiment verifies that this override's enumerated table matches an independently applied table-row edit before touching neural weights.
