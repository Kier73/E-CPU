# USM-010 — Research choice as a verifiable formal obligation

**Purpose:** Give the existing E-CPU research navigator a structured
answer to three questions:

1. Which actual source operation did the model adviser select?
2. What exact evidence does that operation still require?
3. What can the system **prove from current observation**, and what
   remains unknown about future verification?

This is an extension of [USM-009](LIVE_RESEARCH_FRONTIER_USM009.md),
not a competing proof engine or an alternative DAG.

## Native components reused

- `NavigableComputationDAG` continues to determine what is ready,
  committed, or blocked on verified+merged predecessor results.
- `mailcpu.navigation_formal.LinearExpression`, `LinearConstraint`,
  `IntInterval` and `ConstraintDisposition` classify the exact
  verification predicate with E-CPU's existing formal methods.
- `examples.research_frontier.verify_research_report` reconstructs
  and validates the original source-bound model recommendation.
- The existing read-only GitHub observer remains the source of PR
  head hashes, required workflows, job status and linked run evidence.

There is no new GitHub write capability, proof kernel, merge token,
consensus algorithm or scheduling authority in this adapter.

## The precise proof obligation

For each observed PR, let `r` be the number of distinct required
workflows and `s` the number whose most recent observed run for the
**exact PR HEAD SHA** has state `completed` and conclusion `success`.

The proposition `s = r` is represented natively as:

```text
LinearConstraint(
    LinearExpression.variable("successful_checks") - r,
    ConstraintRelation.EQ
)
```

Its classification against the observed singleton interval `[s,s]`
is **entailed** only when every required check is successful; otherwise
it is **refuted in the captured observation**.

The *separate future possibility* uses the interval `[s,r]`. If some
checks are missing, native formal navigation returns **unknown**, not
refuted. This preserves the difference between:

- “The PR's required verification has not completed successfully **now**,”
- and “The PR can never complete verification,” which is **not** proved.

A successful verification equality also does not authorize a merge.
The existing DAG requires a verified **and merged** predecessor before
committing it as an ancestor. A green-but-unmerged parent leaves its
dependent research blocked.

Each obligation retains exact PR HEAD SHA, prerequisite ancestry,
native DAG readiness, status, current/future formal disposition,
outstanding workflow names and exact run URLs (or explicit `no_run`),
and whether it was in the model-adviser's authorized frontier.

## Direct research task: archived real GitHub observation

`examples/research_frontier_observation_2026_11_15.json` is an
actual source observation captured at 2026-11-15 00:32:07 UTC. It
contains nine real open research pull requests. Its source is labelled
`github-api-https`; it is **not live status** after that instant.

In this archived observation, E-CPU PR #138 had zero out of two required
successful exact-HEAD checks and five downstream PRs. The formal
obligation is therefore **refuted now / unknown for the future**. The
model-side adviser chose `investigate_queued_runner`, and the
receiver preserves both unresolved workflow links.

IFS PR #229 is another available root, while seven descendant
operations remain blocked by their unmerged predecessors.

That is useful research assistance: the system does not try to
“solve” a queued Actions job by assuming its tests passed. It names
the missing evidence, records its reach through the dependency graph
and retains what would have to change before advancing the work.

## Reproduce

```bash
python -m pip install -e . pytest
python -m pytest -q \
  tests/test_research_frontier.py \
  tests/test_research_proof_obligations.py

# Reconstruct the real archived GitHub observation without a live API call:
python -m examples.research_frontier \
  --snapshot examples/research_frontier_observation_2026_11_15.json \
  --output research-decision.json

# Reuse E-CPU's native formal-navigation constraints on that decision:
python -m examples.research_proof_obligations \
  --source examples/research_frontier_observation_2026_11_15.json \
  --decision research-decision.json \
  --output research-obligations.json
```

The dedicated USM-009 GitHub Actions workflow also exercises both
modules and attempts a fresh live observation, retaining original
source, selected action, formal obligations and exact offline replay.

Unit tests include actual archived GitHub metadata, 152 different
bounded `(required, successful)` combinations, green-but-unmerged
predecessors, a verified+merged predecessor, missing/queued/cancelled
checks, tampered formal claims, and an observation changed *after* the
model's original decision.

## Scope and next functional improvement

This is an exact formal classification of observed CI evidence, **not
a Lean-kernel theorem or attestation of the GitHub service**. A source
artifact could have been altered before collection; its digest and
internal reconstruction do not prove the upstream service generated it.
The source is mutable over time, and the model policy is a small
deterministic adviser rather than a trained general model.

No feature in USM-010 automatically launches Actions, reviews commits
or merges pull requests. This work is deliberately on E-CPU `main`
in PR #144, independent of the unverified USM-001–008 stack.

The next research use is to feed one **actual code or proof failure**
identified in these verification workflows into VGI's existing
`ProofGround` and IFS's `build_proof_attention_plan`. That planner
already distinguishes candidate tactics from elaborated AND/OR
subgoals and external kernel receipts. It should be integrated only
when a real failure trace becomes available, rather than inventing
a theorem or treating CI completion as kernel proof.
