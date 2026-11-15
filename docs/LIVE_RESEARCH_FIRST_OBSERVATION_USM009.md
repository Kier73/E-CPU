# USM-009 — First actual research observation (2026-11-15 00:32 UTC)

This is a **record of a direct, public-source evidence examination**
conducted during development of E-CPU's research frontier adapter. It is
not a claim that the native USM-009 integration test has passed.

## Source and reproducibility

The exact nine-PR GitHub observation is committed as
`examples/research_frontier_observation_2026_11_15.json`,
with canonical digest
`3a37b6920cc719e7fde30af022df4947c98e5224b0f2a037b02d3d1384290988`.

It contains the observed source revision of every PR and the latest
required-workflow run for that exact HEAD. The observer retrieved public
GitHub PR/run metadata through the connected GitHub API.

The test workflow now replays this frozen observation through the *native*
`NavigableComputationDAG` and model advisory subprocess before attempting a
live refresh. That execution is currently **queued, not confirmed passed**.
The source observation itself can be inspected without a runner.

## Immediate verification frontier

| Candidate | Downstream stacked PRs | Required verification runs | Source observation |
|---|---:|---|---|
| [E-CPU #138](https://github.com/Kier73/E-CPU/pull/138) | 5 | [USM-001](https://github.com/Kier73/E-CPU/actions/runs/43649815778), [verify](https://github.com/Kier73/E-CPU/actions/runs/43649815811) | Both queued |
| [IFS #229](https://github.com/Kier73/In-Formation-Space/pull/229) | 2 | [USM-003](https://github.com/Kier73/In-Formation-Space/actions/runs/43651237055), [Encounter](https://github.com/Kier73/In-Formation-Space/actions/runs/43651237044) | Both queued |

The bounded adviser prioritizes E-CPU #138 because it is a currently
unblocked root and has the largest downstream dependency closure.
This recommendation prioritizes **investigation/verification**, not merge.

The USM-001 job was created at 2026-11-14 22:46:14 UTC and the USM-003 job
at 23:03:02 UTC. Both were still queued after more than 30 minutes.
Their sampled job records contained no runner assignment. The cause is not
yet established. GitHub's published status page listed Actions as
operational and reported no November 14 incident at the time examined;
this does not rule out a repo/account-specific backlog.

The source review also showed the last 100 observed E-CPU Actions runs
comprised 59 queued and 41 cancelled runs, and the last 100 IFS runs
comprised 99 queued and one failed run. These counts are point-in-time
observations, not a conclusion about GitHub's global service.

## Practical action

**Investigate why the queued verification jobs are not being assigned to
runners**, starting with the exact E-CPU #138 and IFS #229 run links above.
Inspect runner eligibility, Actions settings/concurrency, and repository
or account restrictions. These are candidate explanations to check—not
claims that one of them caused the queue.

Do not make another duplicate dispatch simply to generate more pending
runs. If a local physical-machine test is available, its results should be
captured with exact source SHA, interpreter/runtime details, assertions,
and a portable report before being used as evidence.

## Boundary between observation and native execution

The first priority computation was independently reproduced from the
retrieved PR and run metadata using the same declared priority rule; this
is useful research guidance. Full execution of the newly committed
E-CPU DAG + separate advisory-model implementation remains unverified
until the corresponding GitHub Actions job completes or an equivalent
physical-host test is run.

No pull request was merged as a consequence of this research guidance.
