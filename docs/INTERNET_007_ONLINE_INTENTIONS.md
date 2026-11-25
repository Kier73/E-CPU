# INTERNET-007 — Online research intentions as native computational DAGs

**Research milestone:** a zero-cost, GitHub-bootstrapped *intention ingress* for
E-CPU's existing `NavigableComputationDAG`. Implementation and focused tests
are committed; live GitHub Actions qualification is a separate requirement.

## The reversal

The online computer is not a fleet of GitHub runners. The finite research
intention, immutable operation identities, accepted Ground evidence and native
computation DAG persist independently of any runner. GitHub runners are
interchangeable E-CPU interpreter processes. The Git service and HTTP
representation predicate are existing native Internet computational
operators, observed without installing E-CPU at their loci.

The first admitted intention can be read as:

```text
E-CPU pinned Git object -----------.
                                     \
                                      --> Native E-CPU Ground join
VGI pinned Git object --------------/       ^
                                            |
E-CPU HTTP conditional predicate -----------|
                                            |
E-CPU Git graph compare --------------------'
```

The actual committed DAG follows exact declared dependencies and picks the
lexicographically first ready node per quantum. Five operations create five
durable semantic states; an additional invocation after completion performs
no new Internet service requests or state writes.

## An intention is *not* arbitrary executable code

A user-owned, approved public E-CPU source manifest lives at
`intentions/internet007/<intention-id>.json`. It declares:
- schema and durable intention ID;
- bounded textual research purpose;
- zero-dollar budget and strict per-quantum GitHub read/response limits;
- no more than 32 typed native E-CPU computation nodes;
- ordered, exact dependency IDs and typed operator parameters.

The initial operation language has four admitted operators:

| Operator | Native observed relation | Execution locus |
|---|---|---|
| `github.git.commit` | Pinned Git commit/tree/parents and response ETag | Existing GitHub Git service |
| `http.etag.check` | Actual 304 on matching validator, 200 on mismatch, identical source bytes | Existing GitHub HTTP handler |
| `github.git.compare` | Native ancestry/divergence and merge-base, checked against independently pinned expectations | Existing GitHub Git service |
| `ground.join` | Exact predecessor result projections and E-CPU native `ObserverPathStage` witness | Authorized E-CPU receiver |

A manifest **cannot** request Python execution, shell commands, deployment,
arbitrary HTTP URLs, Git writes to other repositories, credential disclosure,
provider provisioning, or paid computation. Public source repositories are
explicitly allowlisted: E-CPU, Virtual-Ground-Interpreter,
In-Formation-Space, VL-I and VL-64 under `Kier73`.

A new research intention cannot extend the operator language or acquire
authority by changing its own JSON. Any new operator needs an implementation,
typed receiver policy, verification, and tests in the E-CPU repository.
External computation can later be admitted through authenticated native E-CPU
peers, not through source-controlled self-authorization.

**Private repository note:** do not place private P-NP source contents,
branches, proof candidates or result digests in these publicly readable
manifests or state files. Private intentions require independently scoped
credentials and private retained storage before joining this public demo.

## Native state and continuity

`mailcpu.internet_intention_ingress` converts the manifest directly to
E-CPU's `ComputationNode` values and `NavigableComputationDAG`. It persists
the original native DAG `snapshot()`, not a replacement scheduler or a
shadow commit ledger.

The workspace identity is the SHA-256 of its canonical manifest. Each
manifest has a separate immutable-name state path:

```text
research/internet-005-state branch
  state/internet007/<intention-id>-<manifest digest prefix>.json
```

A state checkpoint includes schema, manifest digest, intention ID, revision,
previous checkpoint digest, native DAG snapshot and canonical content digest.
For a new intention, a separate **explicit initialization** writes a genesis
record. A `step` refuses absent state, wrong manifest, altered node result,
foreign state or missing branch. A changed manifest creates a new state path
and must be explicitly initialized; it cannot appropriate a previous
workspace identity.

The state update uses GitHub's Contents API with the previously read Git
blob SHA, so a changed old object causes a publication refusal. Failed or
killed workers may re-observe the *read-only* Git/HTTP operator for an
uncommitted node; accepted DAG effects are retained and not repeated.

The E-CPU observer-path receipt from `ground.join` is receiver-local
verification of admitted external service evidence. It is **not** physical
WAN carrier attestation, proof of trustworthy remote hardware, or M3 quorum
commit.

## Online operation

The workflow `.github/workflows/internet-007-intentions.yml` supports:

1. **Read-only PR verification** — source manifests and exact native DAG
   admission/reconstruction tests, without execution privileges.
2. **Manual `initialize`** — user-authorized one-time genesis for an approved
   manifest. An existing state refuses reinitialization.
3. **One live `step`** — run exactly one ready native DAG node and publish
   a Git-blob-SHA-fenced successor.
4. **Best-effort recurrence** — the default public demo advances on a schedule
   every four hours. A qualifying `main` push may also trigger one quantum.
   Runner scheduling/quotas and service availability are not guaranteed.
5. **Durable evidence** — the Git state branch is the retained checkpoint and
   each Actions invocation may emit a bounded report artifact.

The default public demo manifest is
`intentions/internet007/public-source-grounds.json`. Its first genesis
may be pre-provisioned in the state branch, enabling the first
post-merge `push` trigger to execute a quantum. Other manifests must be
explicitly initialized using GitHub Actions `workflow_dispatch` and
the exact `intention_file` path.

Every workflow run has a 10-minute job time budget and uses public GitHub
Services only. Per-operation read count and response byte budgets are
enforced at the receiver. The experiment never invokes a paid infrastructure
API and rejects any declared nonzero monetary budget. GitHub's public
repository and hosted runner fair-use policies still govern availability.

## Acceptance experiment

```bash
python -m pip install -e . pytest
python -m pytest -q \
  tests/test_internet_intention_ingress.py \
  tests/test_internet_fabric_dag.py \
  tests/test_computation_dag.py
```

The focused tests exercise: native DAG formation, cycle/unknown operator
refusal, prohibited hosts and fees, immutable source/Ground bindings, exact
predicate refusals, five independently reconstituted quanta, a fresh Python
process reopening a partially committed DAG, changed manifest isolation,
malformed source and checkpoint refusal, read budgets, and original Git
blob-SHA optimistic concurrency.

**Do not count a hosted success without inspecting Actions jobs and the actual
state branch.** Acceptance requires a real GitHub run advancing each distinct
native operation on new runner processes, a complete linked checkpoint
history, the E-CPU receiver's independent Ground witness, and a final
terminal run with zero new Internet service observations or checkpoint writes.

## Next developments

- Move the persistent checkpoint transport from one GitHub-administered Git
  branch into independently governed M1 objects and M3 quorum authority.
- Develop a bounded online intention inbox and receiver-controlled capability
  admission for multiple repositories and independent research sessions.
- Add authenticated E-CPU Transit ingress and physical cross-host
  reconstitution of the original native computational session.
- Admit measured optical, routing, cache, and other communication-path
  relations as typed Ground operators under actual instrument and
  authorization evidence, not simply because a path can be named.
- Extend virtual parallelism with sparse demand-driven navigation and
  producer reuse; measure actual execution and communication cost separately.
- Require private namespaces/credentials/storage for nonpublic research.

The desired result is a computational workspace whose meaningful accepted
state belongs to E-CPU and whose realizers can change. INTERNET-007 is a
bounded step in that direction, not the conclusion of the larger premise.
