# Document and Comment Style Standard

This document defines the writing conventions for the MailCPU repository. It is
normative. A change that violates this standard is a defect regardless of
whether the underlying code is correct.

Terms used as defined terms in this document appear in bold on first use.

## 1. Scope

This standard governs:

- all Markdown under `docs/` and the repository `README.md`;
- all docstrings and comments in `mailcpu/`;
- all commit messages and pull-request descriptions.

It does not govern test function names, which follow existing conventions and
are not prose.

## 2. Normative language

The key words **MUST**, **MUST NOT**, **SHALL**, **SHALL NOT**, **REQUIRED**,
**SHOULD**, **SHOULD NOT**, **MAY**, and **OPTIONAL** are to be interpreted as
described in RFC 2119 and are used only where a statement imposes a binding
obligation or an explicit permission.

Prose that describes current behaviour without imposing an obligation uses
present tense and indicative mood: "the kernel validates", not "the kernel will
validate" or "the kernel validates now".

## 3. Prohibited content

The following are defects. Each is prohibited in tracked files.

### 3.1 Development narrative

Any statement describing the process of constructing, sequencing, correcting,
or planning the software rather than its specified behaviour.

Prohibited forms, with the reason each is rejected:

| Form | Reason |
|---|---|
| First-person and second-person pronouns ("I", "we", "our", "you") | The specification is written by no one and addressed to no one. |
| Temporal development markers ("now", "currently", "at present", "today", "latest") | A specification is not anchored in time. Behaviour that is a property of the design is stated in present tense; behaviour that is a property of a release is stated as version-scoped text. |
| Progress ordinals ("the first version of", "the initial implementation", "phase N") | Ordinals are relative to a sequence that a reader does not have. |
| Supersession narrative ("was replaced by", "was corrected", "used to") | A specification describes the current contract. Historical change is recorded in version history. |
| Roadmap narrative ("the next step is", "future work will", "once this lands") | Intended future behaviour is an obligation or a non-goal, never a promise. |

### 3.2 Rhetorical and epistemic qualifiers

"simply", "obviously", "clearly", "of course", "just", "actually", "pretty
much", "arguably", "somewhat", "quite", "literally", "very", "really".

Qualifiers that carry meaning are not prohibited; rhetorical ones are. "must
hold even under adversarial input" is a constraint. "obviously holds" is
padding.

Deliberate architectural choices are stated as facts with their rationale, not
with an adverb marking the authorial choice: "the model stores no weight
matrix" rather than "deliberately no weight matrix is stored".

### 3.3 Aspirational and promotional language

"witness", "proof", "demonstrates", "powerful", "robust", "seamless",
"blazing", "first-class", "production-ready", "battle-tested".

Where a demonstration is genuinely required, it is expressed as a test
obligation: "a test MUST demonstrate that ...". A command-line demonstration
command does not discharge a proof obligation and MUST NOT describe itself as
doing so.

### 3.4 Self-verification and self-praise

Comments that state the comment's own value ("obviously correct", "this is the
important bit", "careful here") or that congratulate the implementation.

### 3.5 Redundancy

A comment that restates the code it annotates. Comments exist to state a
constraint, a rationale, or a boundary that the code cannot express. If the
code states it, the comment is removed.

### 3.6 Environment and identity leakage

- Absolute filesystem paths.
- Operating-system-specific user names, home directories, or machine names.
- Organisation names, internal hostnames, or ticket identifiers.
- Credentials of any kind. A credential found in a tracked file is a security
  incident; rotate it before staging.

Every referenced path MUST be repository-relative and forward-slash separated,
including in command examples. Shell commands shown for a POSIX environment
MUST use POSIX separators; PowerShell examples are permitted only where the
command is genuinely PowerShell-specific.

### 3.7 Dead vocabulary

Words that denote a project stage rather than a specification concept are not
used: "scaffold", "vertical slice", "witness", "milestone recap", "phase
complete".

## 4. Defined terms

A **defined term** is a term given a precise meaning by this repository. Defined
terms are set in **bold** on first use in each document, and thereafter referenced
consistently. A document MUST NOT introduce a term as a defined term that is not
registered in `docs/GLOSSARY.md`.

Core defined terms:

| Term | Meaning |
|---|---|
| **transition algebra** | The total, deterministic function `T` from machine state to successor machine state defined in `docs/ARCHITECTURE.md` clause 3. |
| **kernel state** `K` | The product of registers, pages, filesystem, mailboxes, processes, devices, routes, and journal. |
| **reference interpreter** | The transport-free backend whose result defines correct behaviour. |
| **transport** | Any substrate implementing the `Transport` protocol. Substitutable below `δ` only. |
| **evidence tier** | One of `E0`, `E1`, `E2`, denoting captured/emulated, owned, and public-infrastructure reach respectively. |
| **fail closed** | Refusal of an operation whose preconditions are not satisfied, as distinct from granting degraded authority. |
| **check pointable** | A state component whose complete value round-trips through `save_checkpoint` and `load_checkpoint` without loss. |
| **capability** | A pair `(resource, rights)` authorising a named subset of operations on a named resource. |
| **admission** | The act of accepting a generated, learned, or externally sourced component into the execution path. |

## 5. Document structure

Every document under `docs/` follows this structure:

```text
# <Title>

<One-sentence scope statement.>

## 1. <Clause title>
   ...
```

Rules:

1. Clauses are numbered and nested with decimal numbering (`1.`, `1.1`, `1.1.1`).
   Numbering is stable; clauses are never renumbered to preserve narrative flow.
   A clause is retired by being marked "Withdrawn", not by deletion.
2. Every clause states exactly one obligation, rule, or definition.
3. Tables state facts. A table row MUST NOT contain a temporal qualifier.
4. Normative obligations are tagged **REQUIRED** or **MUST**. Capabilities that
   are deliberately absent are tagged as **non-goals** and MUST be enumerated in
   an explicit non-goal clause rather than mentioned in passing.
5. A document ends with either an obligations clause or a non-goals clause. It
   does not end with a summary of what was achieved.

## 6. Status language

Two constructions are permitted and MUST be used in preference to temporal
narrative.

**Evidence tier.** Any statement about a working network, transport, or
substrate MUST carry its evidence tier:

> The E1 owned fabric provides deterministic multi-hop forwarding over
> point-to-point links. Evidence tier: E1.

**Version scope.** A statement about behaviour that is not guaranteed across
versions is scoped to the version that implements it:

> As of 0.1.0, the loader admits UTF-8 assembly and validated MCPB bytecode.

This is the only sanctioned form of a progress statement.

## 7. Code comment style

The repository applies four comment classes. A comment MUST belong to exactly
one class.

| Class | Form | Use |
|---|---|---|
| Module docstring | One sentence, present tense, third person singular | Responsibility only. Never history, provenance, or rationale. |
| Class docstring | One sentence stating what the type represents | Identity only. |
| Function and method docstring | One sentence stating the contract | Preceded by `Mathematics: ` when, and only when, the docstring states an invariant rather than a procedure. |
| Inline comment | No prefix, declarative, present tense | A constraint, rationale, or boundary the code cannot express. Never a restatement. |

Rules:

1. The prefix `Mathematics: ` is a marker. It is applied to an invariant and to
   nothing else. It is applied with uniformity: a reader must be able to predict
   from any single docstring whether the prefix is present.
2. `Mathematics: ` is a **docstring** marker. It is not used on inline comments.
   An inline comment stating an invariant drops the prefix and begins directly
   with the statement.
3. Every public function, method, and class has a docstring.
4. Docstrings state contracts. They do not contain implementation narrative,
   changelogs, or provenance.
5. Provenance belongs in `docs/`. A module docstring that describes where code
   came from is a defect.
6. Inline comments are sparse. A module with zero comments is normal; a module
   with one comment per statement is not.

### 7.1 Example

```python
def preflight(destination: int, length: int, capacity: int) -> None:
    """Mathematics: commit `M[a:a+|B|] := B` only when declared capacity `n >= |B|`; otherwise the transition is the undefined element with ERANGE."""

    if length > capacity:
        raise Errno.RANGE
    destination  # records the preflighted offset for the subsequent commit
```

Note what is absent: no statement that this is safe, no statement that it was
added to fix a failure, no restatement of the guard.

## 8. Verification language

Statements about what the software does are obligations on the test suite, not
assertions about the present.

Permitted:

> **REQUIRED** The differential corpus MUST include programs with blocking
> `WAIT` preceded by and followed by `SEND`.

Prohibited:

> The differential corpus includes blocking `WAIT` cases.

> The test suite covers blocking waits.

The second form is unverifiable and ages badly. The first is checkable and
becomes false the moment the obligation is violated, which is the intended
failure mode.

## 9. Cross-references

1. Documents reference each other by repository-relative forward-slash path.
2. A referenced path that does not exist is a defect. `scripts/verify_repo.py
   --check-links` enforces this.
3. Document identifiers are stable. References use identifiers, not line
   numbers.

## 10. Commit messages

1. Subject line, imperative mood, under 72 characters, no trailing period.
2. Body explains the change and its justification in normative terms. It does
   not narrate the session.
3. Subject lines do not contain "now", "finally", "again", or "cleanup".
