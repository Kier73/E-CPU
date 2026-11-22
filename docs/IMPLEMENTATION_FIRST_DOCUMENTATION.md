# Implementation-first documentation standard

Documentation is a second representation of the implementation: a compact, inspectable path from intention to mathematics, algorithm, API, and measured behavior. Prefer a **reconstructable description** over repeated readiness commentary.

## One capability, one inspectable contract

Use these sections for an implementation-level research document. Short components can combine sections.

| Section | Reader can answer | Source of truth |
|---|---|---|
| **Capability and domain** | What input, output, authority and resource scope exist? | Concrete types and constructors |
| **Formal contract** | What relation, state transition or invariant is implemented? | Equations reflecting code, with domains defined |
| **Algorithm** | In what order are states checked, transformed, observed and committed? | Entry point and actual call path |
| **Current syntax** | How can I invoke or inspect it now? | Importable names, exact arguments, executable example |
| **Verification** | Which exact properties were checked, and how? | Test cases, oracles, traces, measurable results |
| **Next construction** | What new behavior, experiment or invariant comes next? | Bounded acceptance criterion and expected evidence |

Keep mathematical descriptions distinguishable:

- **Implemented law:** equation exactly describing the code, including its finite domain and parameters.
- **Derived property:** proposition supported by implementation plus a mathematical argument or independent check.
- **Research hypothesis:** new equation or architecture to be tested. Put its construction and verification under *Next construction*.

A mathematical expression is not automatically evidence of physical execution. State the concrete observation mechanism once, in *Verification*.

## Editorial procedure

1. **Choose a claim-bearing document.** Locate repetitive qualifiers, duplicated scope text and architectural assertions lacking an implementation reference. Preserve security-critical warnings and empirical qualifications.
2. **Follow the code.** Identify the actual entry point, types, representation schema, source law, execution stages, authority checks, digest definitions and tests. Do not synthesize nicer APIs or silently substitute pseudocode for current syntax.
3. **Translate into a formal contract.** Define domains, functions, invariants and the exact scope of equality. Ask whether every symbol maps to a code value, test oracle or declared research object.
4. **Write operational order.** Show the real state transitions and validation gates in execution order, not a conceptual sequence that omits authority or recovery.
5. **Supply a small reproducible example.** Prefer a runnable excerpt from a real test; show input, call and asserted output. If external receiver bindings are required, name them and link to the test fixture.
6. **Attach evidence to claims.** For each major claim, cite a source function and a test with a matching assertion. Use a short evidence table; centralize domain and trust-scope qualifications there.
7. **Translate back.** Compare equations and documentation with the implementation. Any mismatch becomes a concrete choice: correct prose, correct code, or create a new experiment.
8. **Make the next construction falsifiable.** Specify what changes in the relation or interface, and what observation would demonstrate success.
9. **Review presentation.** Remove repetitive “is not yet”/“does not prove” passages that repeat the same qualification; keep one precise scope statement where it affects interpretation. Check Markdown links and executable commands.

## Editing rules

- **Current means current:** bind API examples to named source paths; include test paths and commands. Keep proposed interfaces in *Next construction*, never in an unlabeled “Usage” example.
- **State the conditions of the invariant:** say which input domain, membership/epoch, observer projection and authority contract the formula presupposes.
- **Keep evidence separate from ambition:** a receiver-local simulator, a network service observation, and a physically independent witness are distinct evidence classes; a single concise evidence table is enough.
- **Favor information density over austerity:** explanation is welcome when it teaches the mechanism. Remove only prose that cannot help a reader reconstruct, test or extend it.
- **Preserve history:** retain links to past experiments and record actual results; edits should not inflate claims or erase failed controls.
- **Do not auto-promote formulas into theorem claims:** compare implementation, independent oracle and observed traces before attaching a proof label.

## Review checklist

- [ ] Each mathematical symbol has a declared domain and code/test referent.
- [ ] Code snippets use existing callable names and valid input types.
- [ ] Operational order includes admission, validation and recovery where implemented.
- [ ] Evidence names concrete tests and includes meaningful controls.
- [ ] Repeated negative scope prose has been consolidated without losing scientifically relevant distinctions.
- [ ] Next construction has an implementation target and observable acceptance criterion.
- [ ] Translation revealed at least one potential invariant, mismatch or research question, or explicitly found none.

## First worked example

[INTENT-001: intention-formed finite observer machine](INTENT_001_OBSERVER_FORMED_FABRIC.md) formalizes partition refinement and an independent distinguishability fixed point, shows the native API and receiver-bound execution path, and extracts a new question about observation refinement and machine identity.

This document standard applies equally to E-CPU, VGI, VL-I and In-Formation-Space when the repository's actual implementation supplies the corresponding evidence.
