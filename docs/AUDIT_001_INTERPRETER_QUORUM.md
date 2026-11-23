# AUDIT-001 — Interpreter conformance and quorum certificate evidence

## Semantic Ground

The native instruction machine is the transition system
\[
S=(pc,R,Q,O),\qquad T:S\times\mathrm{Instruction}\longrightarrow S\cup\{\mathrm{BLOCKED}\}.
\]

A user mailbox `m` has its own FIFO `Q[m]`, disjoint from internal
register/code addresses. `SEND m,r` and `WAIT m,r` have the following
shared reference and transport semantics:

```text
SEND(m,r):
    v := R.get(r, 0)
    Q[m] := Q[m] ++ [v]
    O := O ++ [(m,v)]
    pc := pc + 1

WAIT(m,r):
    if Q[m] == []: BLOCKED (no register or pc transition)
    else:
        v := pop_left(Q[m])
        R[r] := v
        pc := pc + 1
```

Initial external inputs are prepended to later internal SEND values in the
same mailbox. Program `SEND shared; WAIT shared` therefore completes even
without an initial external input. The transport-free oracle and queue
backend now use the same typed input domain (integer values excluding
booleans), and `reg:` and `code:` remain reserved exclusively for internal
addressing. An unaddressable program fallthrough becomes a HALTED state on
the next run boundary; a budget exhausted immediately after the final
non-HALT instruction still reports STEP_LIMIT.

Validated instructions freeze `args` to tuples and require `Op` members.
The assembler accepts quoted commas as operand data; disassembly escapes
unrepresentable UTF-8 operands as `@u:<hex>`, including newlines, punctuation
and backslashes, so `assemble(disassemble(P)) == P` for tested names.

### Differential evidence

`tests/test_conformance.py` includes deterministic SEND/WAIT FIFO examples,
internal-mailbox alias refusal, matching input rejection, opcode/operand
immutability and deterministic program-fallthrough results. Its additional
400-case corpus composes WAIT/SEND on the same mailboxes, bounded MUL, and
backward control-flow transitions. The original `random_program` stays
available for the narrower terminating fragment.

```bash
python -m pytest -q tests/test_conformance.py tests/test_assembler.py
```

## Quorum Ground

For fixed membership `M`, proposal `p), and candidate voter set
`V`, the existing certificate contract checks:

\[
2q>|M|,\quad |V|\ge q,\quad owner\in V,\quad
\forall v\in V:\ d(v.proposal)=d(p),\quad
v.membership=d(M).
\]

The durable ledger prevents one local journal from preparing competing
slot histories and persists exact prepared artifacts and decisions using
fsynced hash-chain records. An authenticated peer channel can carry a vote
into the coordinator, but a bare certificate snapshot cannot independently
prove that a named remote member actually fsynced that vote.

`verify_certificate_against_member_journals` is an **offline local evidence
check** for environments with trustworthy copies of the member journals:

```python
from mailcpu.seed_commit_quorum import verify_certificate_against_member_journals

verify_certificate_against_member_journals(
    membership,
    proposal,
    certificate,
    {"A": "/durable/A.log", "B": "/durable/B.log", "C": "/durable/C.log"},
)
```

It loads each identified member journal and checks that the exact vote's
`journal_receipt` matches a fsynced local prepare for the exact proposal.
When a proposal binds a transition artifact, the digest must also match.
Missing journals, fabricated receipts, unknown voters and mismatched
prepares are rejected. Trust in journal provenance must be established
externally; this function is neither remote authentication nor high-water
rollback protection.

### Process-death experiment

`tests/test_seed_commit_quorum.py` now also executes a five-member
configuration `{A,B,C,D,E}` with majority `q=3`:

1. `B` and `C` fsync the exact proposal vote.
2. An independent owner Python process opens `A.log`, fsyncs prepare and
   commit with certificate `{A,B,C}`, then invokes `os._exit(91)`.
3. The parent creates a **new owner ledger** from persisted bytes only,
   checks the decision and certificate, refuses a conflicting slot value,
   and independently verifies the three durable prepare receipts.
4. `B` and `C` recover and commit the same certificate; a fresh reopen
   counts exactly three durable matching decisions.

This establishes durable ledger reconstruction after real owner-process
death at the decision boundary. It does not represent recovery of a killed
owner's live client ingress and peer socket graph.

```bash
python -m pytest -q tests/test_seed_commit_quorum.py
```

## Next experiments

- **A-40 / process death:** reuse A-40's four crash cuts and X-21–X-25's
  independent authority services. Persist an owner service/transport cut
  before the death; ensure a fresh process can resume without any
  postmortem in-memory snapshot, then check quorum, rejoin and exactly one
  semantic effect. Never reconstruct from state still resident in the
  killed process.
- **Journal canonicalization:** specify an injective versioned journal
  payload algebra and historical replay strategy. The current generic
  `EventJournal` uses permissive `json.dumps`, and the existing codec
  stringifies arbitrary mapping keys; merely swapping codecs is
  insufficient.
- **Resource accounting:** admit explicit integer-bit and trace-byte
  budgets before executing multiplicative or high-fanout state transitions.
  Step count alone is not an allocation bound.
- **Source identity:** determine whether assemblies are identified by
  source bytes or validated instruction tuples; normalize or reject
  ambiguous textual spellings at that identity boundary.

Verification workflow: `.github/workflows/mailcpu-semantic-quorum-audit.yml`.
