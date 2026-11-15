# Open research PR topology and integration gates — 2026-11-15

This checkpoint is an observed **GitHub API state**, not an evergreen claim. Workflow conclusions must be rechecked at the exact current head SHA before a merge decision. `mergeable=true` means GitHub sees no immediate merge conflict; it is **not** proof of successful tests or semantic readiness. The remote project and local machine may differ; this sandbox has no direct authenticated access to the user's Windows checkout or physical network.

## Consolidation performed

VGI [#24](https://github.com/Kier73/Virtual-Ground-Interpreter/pull/24) through [#31](https://github.com/Kier73/Virtual-Ground-Interpreter/pull/31) are all merged into `main` (terminal merge commit `e6e1900782aeede18a4de9046511bbba234dbc6e`). They were reviewed in dependency order, each retargeted to `main` with the expected changed-file scope, and merged using ancestry-preserving merge commits. The combined experimental focused harness passed **81 tests and 14 subtests**; it uses an API-compatible affine adapter and is **not native VGI package CI**. At merge time GitHub Actions jobs were queued and yielded no passing conclusions. This is an explicit exception to waiting for CI based on the user-authorized consolidation and the isolated tests; it should be called out honestly.

## E-CPU open PR dependency graph (20 at audit)

- **Physical/path-local observer hosts (SHN):** #120 → #121. The root supplies self-hosted one/two-port virtual network; #121 adds time-multiplexed nested hosts. Native/chip claims require real physical measurements, not virtual host counts.
- **Federated observer-ground (SAB, independent branches):** #127 and #128 address self-organizing native peer leases and quorum-backed Ground continuity; both are root PRs and require native fabric/recovery checks.
- **Ground-native host formation (SAB):** #129 → #130 → #132 → #134 → #136. The first stages have local tests, but #129 skipped native mTLS integration, and #136 had seven native tests unavailable locally. Keep source installation receiver-authorized. Ancestry must be preserved and full native tests checked before merging into main.
- **Intention/observation (IOS):** #137 is independent. Local checks explicitly excluded three TLS integration cases.
- **Model-operated E-CPU (USM):** #138 → #139 → #140 → #141 → #142 → #143; #144 is an independent research-verification tool and report. Native authenticated transport, durable receiver recovery and publication fencing are integration gates for the stacked branch.
- **Portable mathematical Ground in Transit:** #145 → #146 → #147. The VGI mathematical dependency is now in `main`, but E-CPU's real Hypervisor + Transit post-commit replay and fresh navigation tests remain unverified. #147's intended test kills a receiver, removes the original record, requires zero backend re-entry for the committed effect and successful new navigation from the native recovered revision.

At audit, the relevant E-CPU GitHub Actions runs were consistently **queued**. No passing conclusion was available to support merging the branches that explicitly require native integration. Parent-child stack changes must be retargeted in order and reviewed after each merge.

## In-Formation-Space complementary PRs (7 at audit)

- Observation-evidence chain #227 → #228 → #230 (the observed proof and live E-CPU receiver evidence are different authorities).
- Independent model receiver chain #229 → #231 → #232.
- #233 is a separate real Python 3.11 invariant and proof-navigation repair.

These are not E-CPU code dependencies for the path-evidence adapter; they are complementary independent-observer research. Merge decisions require repo-local CI evidence and current head checks.

## Host/path coherence rules for integration

1. **Logical host = observer locus.** Route node, placement node, physical process and failure domain are distinct coordinates. A passive edge is not an executor or host unless an observation/interaction contract exists.
2. **Information path = directed architecture.** Carry identity, representation, Ground, context, observation/transform contracts, channel lease, evidence and protocol-specific bounds across all stages. Do not reduce a path to an opaque list of CPUs.
3. **Authority remains separate.** Peer advertisement, content digest, selected route and mathematical proof do not grant host rights. Receiver-local Hypervisor/Virtual Layer and recovery authorities decide admission and publication.
4. **Time has multiple roles.** Logical navigation coordinate, causal sequence, scheduler ticks and physical latency are separate; a huge mathematical step need not imply billions of host operations.
5. **Continuity is evidential.** Process restarts, host moves, topology changes and representation changes retain semantic identity only when exact Ground, lineage, and effects are independently checked. Do not replay a committed effect as a new semantic effect.

## Machine-based follow-up gate

Once a machine checkout and real host/channel access are available: synchronize three repos using `git fetch` and explicit head SHA records; run native full suites on Python 3.11/3.13, mTLS receiver and quorum-lineage checks, and real two-host transport tests; record placement and failure domains separately from observer IDs. For every ready PR use expected head SHA and retain merge-commit ancestry for stacked branches; compare changed file scope after each base retarget. If a dependency fails, repair it in its own branch without prematurely merging descendants.