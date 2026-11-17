# INTERNET-002 — Navigate an existing Internet service's state graph

**Status (2026-11-16):** Authorized live GitHub service graph created and examined through the GitHub connection; **9/9 native comparison results** agreed with an independent bounded ancestry oracle; **12/12 remote commit/tree/parent objects** independently cross-checked; 24/24 local pure-Python tests passed. The direct HTTPS recheck and HTTP-ETag probe are configured but **not yet verified on GitHub Actions**. This is an existing *Internet application-service operator*, not an experiment in optical computation, router arithmetic, or worker distribution.

This experiment extends [INTERNET-001](INTERNET_NATIVE_GROUND_001.md), [The Internet Is the Computer](THE_INTERNET_IS_THE_COMPUTER.md), [Latent Path Capacity](LATENT_PATH_CAPACITY.md), [State-Space Navigation](STATE_SPACE_NAVIGATION.md), and [Observer-Host Path Cohesion](OBSERVER_HOST_PATH_COHESION.md). It follows the design principle that **capacity precedes recognition, intention selects an observation, and path evidence is separate from execution authority**.

## The active relation was already available on the internet

A pre-existing Git service retains immutable commit/tree/blob references, a causal multi-parent graph, named reference states, and a native compare operation. No E-CPU interpreter or custom network worker was installed at the service. An authorized caller *only* used the service's existing API to construct a bounded graph on user-owned experimental branches.

A mathematical Ground describes the *declared finite experiment slice* of the Git DAG:

- `V`: 12 exact Git commit SHA-1 identities, one pinned root plus eleven new service-created commits;
- `E`: the returned first- and second-parent edges, including one two-parent join;
- `S`: three stable, user-owned branch references selecting heads in the observed state graph;
- `I(base, head)`: an intention requesting the service's ancestry/divergence relationship;
- `O(I)`: `(ahead_by, behind_by, merge_base, status)`;
- `C`: actual HTTPS reads and local verification/proof work, measured separately from transmission-propagation and service processing, which are not visible here;
- `E_G`: exact Git IDs, receiver-supplied manifest SHA-256, each returned parent/tree/ref and compare outcome.

The independent reference uses only the *pinned parent relation* to calculate ancestor sets. For a base state `a` and target `b`, it counts `|Anc(b) - Anc(a)|` and `|Anc(a) - Anc(b)|` and finds the unique maximal common ancestor. The remote Git service supplies those same quantities from its existing persistent graph. The receiver then compares them. This tests a nontrivial service-native relation; the locally computed oracle is **verification**, not what produced the remote answer.

The experiment does not claim that the internet graph or Git service magically represents all mathematical states. It recognizes a real operator over a *declared finite domain*. Beyond that domain, unknown relations remain unadmitted.

## Actual live observation

Root: `9a34c11147db7d8619b65b6058fa121ab9b1c43c`, the independently anchored INTERNET-001 state. A four-transition branch `A1→A4` and five-transition branch `B1→B5` were independently formed from this root; `M` joins their heads, and `M2` continues the join.

Remote branch refs:

- [`research/internet-002-graph-a`](https://github.com/Kier73/E-CPU/tree/research/internet-002-graph-a) → `6fa468a69f165e74c611e8ec448125d8713a6141`;
- [`research/internet-002-graph-b`](https://github.com/Kier73/E-CPU/tree/research/internet-002-graph-b) → `c18f8de3f2b818d96149b0833d7086b8d1c46649`;
- [`research/internet-002-graph-merge`](https://github.com/Kier73/E-CPU/tree/research/internet-002-graph-merge) → `afcd39be08ee2f64992763e913c5370968232b84`.

The service itself created commit `M` with **both** `A4` and `B5` as its parents; a separate Git API GET returned both parent identities in order. The code branch and these evidence branches are separate: an experimental ref must not silently change while a pinned observation is being verified.

| Remote service query | Actual observed classification | Service counts | Unique service merge base | Independent result |
|---|---|---|---|---|
| Root → A4 | ahead | ahead 4, behind 0 | Root | match |
| Root → B5 | ahead | ahead 5, behind 0 | Root | match |
| A4 → B5 | diverged | ahead 5, behind 4 | Root | match |
| A2 → B4 | diverged | ahead 4, behind 2 | Root | match |
| B2 → B5 | ahead | ahead 3, behind 0 | B2 | match |
| A4 → M2 | ahead | ahead 7, behind 0 | A4 | match |
| B5 → M2 | ahead | ahead 6, behind 0 | B5 | match |
| M2 → A4 | behind | ahead 0, behind 7 | A4 | match |
| Root → M2 | ahead | ahead 11, behind 0 | Root | match |

All nine results come from live GitHub compare operations and were checked against an independent in-process reference. They are preserved with exact SHAs in [`reports/internet_native_ground/internet_002_live_comparisons.json`](../reports/internet_native_ground/internet_002_live_comparisons.json). The commit identifiers and parent bindings are preserved in the **canonical** [`internet_002_graph.json`](../reports/internet_native_ground/internet_002_graph.json), whose receiver-owned SHA-256 is:

```
98dfca4156e985feb08cb595ded5f37a92eb826cfe52415e7f5307a959d63347
```

The source file is not an independent external signature. A receiver has to retain or supply that exact digest from a trust context **other than the unverified remote result**. Any change to the file requires a new separately admitted pin.

## Code, proof, provenance and refusal

[`examples/verify_internet_graph_ground.py`](../examples/verify_internet_graph_ground.py) is the independent typed observer. It verifies exact manifest bytes before remote calls; checks every returned commit identity, tree and parent edge; verifies exact remote reference heads; and compares **each GitHub-computed relation** against the local DAG oracle. It rejects forged service answers, stale branch refs, wrong tree identity, missing merge parents, cycles, duplicate JSON, unknown queries, and ambiguous multiple merge bases. It does not use the GitHub comparison implementation as its oracle.

The Python oracle's full graph traversal is a *verification cost* for this deliberately small bounded slice. It is not silently claimed as fast-forwarding a huge arbitrary Internet state-space. The remote service's native response nevertheless allows E-CPU to select a required relationship without copying all its Git objects to the caller first.

The complete success witness is `mailcpu.internet-native-git-graph-observation.v1` and includes a content-binding SHA-256. This is **not** an independently signed receipt, an end-to-end physical link measurement or a Hypervisor grant. Remote attribution follows the HTTPS origin and the authenticated GitHub connection; remote hardware provenance is unobserved.

The historical Git objects before the separately pinned root are outside this finite Ground. The remote root may have parents in the broader repository, which are **not** used to justify claims about unobserved commit history.

## Second protocol-level observation: HTTP conditional state

[`examples/probe_internet_http_validators.py`](../examples/probe_internet_http_validators.py) tests another pre-existing internet relation, **HTTP entity validation**, with three read-only requests to a fixed Git commit:

1. Ordinary GET yields a `200` representation and an `ETag`, if the origin supplies one.
2. `If-None-Match` with that validator may produce `304 Not Modified` with no response entity, under RFC 9110 conditional semantics.
3. A deliberately nonmatching validator should yield `200` and the identical pinned representation.

The probe retains observed status, ETag, Cache-Control, Age, Via (if present), response-entity body length/hash, and **requester-side** monotonic elapsed time for each request. It explicitly refuses to assert that an origin versus intermediary cache produced the response without instrumentation or network-path provenance; it cannot measure one-way transit time or attribute processing to cable propagation.

**Evidence status:** six local protocol unit tests passed using an injected synthetic HTTP responder. The real conditional HTTPS probe is configured on the GitHub-hosted workflow; **it has not been observed in the current local environment**, which has no general outbound DNS/network access. A `200` response on the matching validator would be reported as *not established*, not fabricated into a `304` observation.

This follows [RFC 9110](https://www.rfc-editor.org/rfc/rfc9110.html#section-13.1.2) and [RFC 9111](https://www.rfc-editor.org/rfc/rfc9111.html#section-4.3.3). The compare semantics follow [GitHub's REST documentation](https://docs.github.com/en/rest/commits/commits#compare-two-commits). A reference-update API promises fast-forward checks, **not** a general-purpose GitHub compare-and-swap on an arbitrary expected SHA; the earlier opaque stale-update error is not promoted to evidence of a lease algorithm.

## Architectural synthesis and next step

This directly extends the original notion *the Internet itself is the computer*: the selected Ground relation already existed as a usable information capability on the Internet. E-CPU discovered, addressed and independently checked it without requiring that remote observer-host to implement E-CPU. The computational request and its correctness evidence belong to E-CPU; the transition relation and persistent state remain where they already existed.

The next stronger test is not another GitHub API feature. It is to characterize a **controlled nontrivial path operator** whose mathematical output can be attributed to a permitted path stage, with source/receiver-bypass controls, held-out predictions, real endpoint and network measurements, and an exact declaration of which stage did the work. This could be an owner-controlled programmable packet processing element, an explicitly instrumented delay/feedback line, or an independently characterized optical/RF transfer function.

Use existing E-CPU `mailcpu.observer_path_evidence` to retain typed carrier versus transform stages, `mailcpu.transit_path_binding` for RTT/queue/ACK evidence, `mailcpu.intention_measurement_fabric` for permitted observed features, `mailcpu.evidence_path_resolver` for route selection, and M1/M3 for retained certified state. **Do not create a parallel transport, authority, session ledger or scheduler.**

## Reproduce

Offline, Python 3.11+:

```sh
python -m unittest discover -s tests -p 'test_internet_graph_ground.py' -v
python -m unittest discover -s tests -p 'test_internet_http_validators.py' -v
```

Hosted or on an authorized Internet-connected environment (read-only, 24 bounded GitHub GETs; `GITHUB_TOKEN` optional for API rate budget):

```sh
PIN=98dfca4156e985feb08cb595ded5f37a92eb826cfe52415e7f5307a959d63347
python examples/verify_internet_graph_ground.py \
  --manifest reports/internet_native_ground/internet_002_graph.json \
  --expected-manifest-sha256 "$PIN" \
  --out /tmp/internet-002-verified.json
python examples/probe_internet_http_validators.py \
  --repo Kier73/E-CPU \
  --commit 9a34c11147db7d8619b65b6058fa121ab9b1c43c \
  > /tmp/internet-002-http-validator.json
```

The normal GitHub CI test must be checked at its actual exact-head run before any hosted result or HTTPS timing figure is declared verified.
