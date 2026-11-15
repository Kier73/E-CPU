# USM-009 — Let E-CPU navigate its own research verification frontier

**Purpose:** Make E-CPU useful to the researchers developing it. The task
is not a synthetic arithmetic series: it is the actual dependency graph,
GitHub HEAD revisions and CI evidence of the open model-operated research
PRs in E-CPU and In-Formation-Space.

This experiment runs independently of the unverified USM-001–008 branch
stack. It builds directly on the existing, already merged E-CPU
`mailcpu.computation_dag.NavigableComputationDAG`.

## The real intention

> From currently observable GitHub evidence, identify the earliest research
> operation whose verification could unlock the most dependent work. Never
> treat a queued, missing, skipped, or canceled check as success, and never
> allow a model recommendation to merge an unverified PR.

This goal exercises E-CPU as a developer's navigable computation OS:

1. The *observer* reads public GitHub PR metadata and workflow runs over
   HTTPS, pinning each observation to its exact 40-hex commit SHA.
2. A receiver-owned, reviewed manifest declares the intended research
   workflows and actual stacked PR dependency edges.
3. The native E-CPU `NavigableComputationDAG` creates one immutable node
   per PR, bound to the content digest of the complete observation.
4. The DAG commits a dependency **only if** it is both merged and each
   required workflow's latest exact-HEAD run has completed successfully.
   Green-but-unmerged changes do not silently unblock dependent research.
5. A separate, bounded advisory process sees **only** the exact
   `ready_nodes()` frontier. It ranks unverified candidates by the number
   of downstream operations they would eventually unblock.
6. The trusted receiver rejects any model response referring to a blocked
   PR, mismatched source digest, modified action, or unverified merge.
   There is **no GitHub write permission or merge action** in this
   capability.
7. An independently reconstructable report preserves the DAG snapshot,
   committed ancestor set, ready frontier, blocked dependencies, model
   proposal, exact HEAD and workflow evidence digest.

The adviser is a deliberately small **deterministic linear ranking model**,
not a language model or a learned proof verifier. Its score is only a
scheduling preference. In the next experiment, it can be replaced with a
trained controller or another hosted model without changing E-CPU's
readiness and authority checks.

## Operational use

```bash
python -m pip install -e . pytest
python -m pytest -q tests/test_research_frontier.py

# Start with an exact real source observation archived on Nov 15, 2026 UTC.
# No network access or GitHub token is required for this replay.
python -m examples.research_frontier \
  --snapshot examples/research_frontier_observation_2026_11_15.json \
  --output archived-research-frontier.json

# Fetch actual current public evidence (18 read-only GitHub API requests
# for the current 9 PRs; optional GITHUB_TOKEN avoids anonymous rate caps):
python -m examples.research_frontier --live \
  --evidence-output research-observation.json \
  --output research-frontier.json

# Later, replay and verify precisely the same observation without network:
python -m examples.research_frontier \
  --snapshot research-observation.json \
  --output research-frontier-replayed.json
```

The data source is always clearly labelled `github-api-https` or
`fixture`. The checked-in snapshot
`examples/research_frontier_observation_2026_11_15.json` is a
**real time-pinned GitHub observation** at 2026-11-15 00:32:07 UTC,
containing all nine PR HEAD hashes and two required workflow runs each.
Its canonical evidence digest is
`3a37b6920cc719e7fde30af022df4947c98e5224b0f2a037b02d3d1384290988`.
It is valuable for reproduction, but is **not live status** after its
capture timestamp. An offline fixture is **not** a current GitHub status.
A SHA-256 digest proves that a report has not changed since observation; it
does not make an untrusted JSON export a GitHub-signed attestation.

## Meaningful output

With the open November 14, 2026 model-recovery PR stacks, the
first frontier is the two unmerged roots:

- E-CPU PR #138, whose dependencies include the model-issued system call,
  authenticated model transport, receiver recovery, remote quorum and
  quorum publication experiments.
- IFS PR #229, whose dependencies include the independent receiver
  reconstruction and competing route-epoch publisher experiments.

The model can recommend investigating or verifying one of them. As an
initial **live evidence review on November 15, 2026 UTC**, E-CPU PR #138's
USM-001 run (43649815778) remained queued from 22:46 UTC on November 14,
and IFS PR #229's USM-003 run (43651237055) remained queued from 23:03 UTC.
Their corresponding jobs had no assigned runner in the retrieved records.
The observed state supports investigating runner availability, but not
asserting its cause. Only a complete current source observation determines
which action is actually admissible. If source statuses change, rerun the observer rather than using
this documentation as an availability or check-status claim.

## Verification and safety contract

- Missing workflow or HEAD mismatch is not a green run.
- Status `completed/success` is required for **every** configured workflow.
- Failed, skipped, neutral and canceled runs do not grant verification.
- A newly queued run means `monitor_queued_verification`. An unfinished run
  already queued for 30 minutes or more at the **observed source timestamp**
  means `investigate_queued_runner`, rather than dispatching duplicate
  jobs. Canceled runs without a live replacement mean
  `reassess_cancelled_verification`. These are diagnostic classifications,
  not a conclusion about why GitHub has not assigned a runner.
- The selected report includes the exact run IDs and GitHub URLs to help
  the developer inspect the current blocker.
- Exact real branch parents must match the declared local dependency
  edges, refusing invented graph connections.
- Closed-but-unmerged PRs are excluded from the actionable frontier.
- Cyclic, out-of-budget or malformed graphs are refused by E-CPU's
  existing computation DAG, not a new graph algorithm.
- Model advice is refused if its digest, request correlation, selected
  node or action disagrees with the receiver's independent observation.
- Every report explicitly states `merge_authorized=false` and
  `github_state_mutated=false`.
- A second pass can reconstruct the result from the source evidence
  without running the model adviser again.

**Important:** This is source-evidence-informed development assistance,
not proof that a workflow passed, and not an automatic code reviewer.
The source is public mutable GitHub state; checks can change immediately
after observation, and merges must revalidate at their commit boundary.
No claim that this process is isolated by a hardware security boundary.

## Follow-up research usage

The next practical change would extend the same receiver-owned task ABI
to an **actual proof obligation** from VGI or an E-CPU invariant
counterexample. The model would select the obligation, E-CPU would
dispatch it to the existing proof action adapter or verifier, and the
returned proof/rejection evidence would be admitted as a DAG commit only
after an independent observer reconstructs it.

That next step should be motivated by a real development blocker
identified by this experiment, rather than a fabricated theorem.
