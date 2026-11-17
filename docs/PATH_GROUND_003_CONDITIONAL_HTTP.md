# PATH-GROUND-003 — A live Internet HTTP observer-host as a mathematical state predicate

**Status:** E-CPU implementation and bounded verifier completed; an independently
authenticated remote HTTPS **object lookup** was observed through the connected
GitHub service; the specific **conditional 304 / stale 200 / cross-access-path
experiment is implemented and queued for GitHub Actions verification.** Do not
report 304 or bandwidth savings as measured until the live job succeeds.

This experiment is intentionally different from emulating a remote CPU. Its
observation belongs to a **preexisting Internet application protocol operation**.
It is also different from treating a passive byte link as arbitrary computation.

## Research question

Can an intention to observe whether a represented state is unchanged be
realized by a state-dependent Internet service response, **without first
transmitting the entire stored state**, and can E-CPU independently verify the
result against immutable mathematical and byte identities?

The target is one already-published public E-CPU Git object. Requests use only
the owned `Kier73/E-CPU` public repository and one fixed known document:
`docs/THE_INTERNET_IS_THE_COMPUTER.md`, pinned to an **exact commit SHA**.
The address validator refuses branch names, external domains, arbitrary URLs,
other files, repository traversal, and unsupported Git object algorithms.

For a remote HTTP representation with current validator `e`, define:

\[
P(e',e)=
\begin{cases}
(304,\epsilon), & e'=e\\
(200,B), & e'\ne e,
\end{cases}
\]

where `B` is the response representation and `epsilon` denotes no
application-level response body.

This is a *protocol-state predicate*, not a numerical recurrence.
The evaluation occurs in the **HTTP service or its authorized intermediary**,
not in a Python handler shipped by E-CPU and not necessarily in a physical
router along the packet route. E-CPU observes the protocol response and
independently checks whether the stated predicate is justified.

A `304` is scoped to the exact **URL, method, request representation
headers, ETag and observation interval**. It is not a generic proof that all
remote information is unchanged. Different representations have distinct
validators; there is no universal ETag shared by the GitHub contents API,
raw file endpoint, or Git blob API.

## Native Internet proof sequence

A single `GitContentAddress` binds
`(repository, commit SHA, fixed file path)`; it constructs three controlled
HTTPS addresses. The observed sequence consists of five **serial** requests:

1. **Baseline `200`** — GET the commit-pinned contents API URL, parse its
   bounded JSON/base64 payload and read the HTTP `ETag`.
2. **Equality intention `304`** — repeat the identical request with
   `If-None-Match: <received ETag>`. A successful service comparison returns
   no representation body.
3. **Stale-validator `200`** — repeat with the exact known-impossible
   `If-None-Match: "ecpu-unmatched-validation-control"` and require complete
   representation bytes equal to step 1. This is a falsifiable counterfactual,
   not an assertion from the requester.
4. **Alternative raw HTTPS path `200`** — fetch
   `raw.githubusercontent.com/Kier73/E-CPU/<commit>/<file>` and compare its
   exact raw bytes to the decoded contents response.
5. **Immutable Git blob lookup `200`** — request
   `api.github.com/repos/Kier73/E-CPU/git/blobs/<SHA1>`; verify Git's object
   digest from its canonical blob header and actual byte content.

The server can save application-level response body bytes at step 2.
The *network packets, TLS handshake, routing, headers, request handling,
client decoding and subsequent independent verification* still cost time,
energy and bytes. ETags are generated and interpreted by the HTTP service;
a SHA-256 of the body identifies bytes, not the service's permission or
physical identity.

The experiment uses the normal TLS certificate and hostname validation of
Python's HTTPS implementation. It refuses redirects and unbounded HTTP
responses; error statuses are treated as **refusals** instead of success
states. It does not transmit secrets or credentials. Remote object endpoints
are restricted to the public E-CPU repository.

## Reuse of existing research

- [PATH-GROUND-001](PATH_GROUND_001_COMMUNICATION_OBSERVATION.md) shows a real
  bounded TCP link and a separate physical-timing Ground. It does **not**
  give the server-side comparison or cross-HTTPS representation contract.
- [PATH-GROUND-002](https://github.com/Kier73/E-CPU/pull/168) is a pending,
  independently reviewed real kernel UDP source-selection experiment. It
  demonstrates an OS-protocol projection on a single host; it is not used as
  evidence of a remote Internet comparison.
- [CAPACITY-001](LATENT_PATH_CAPACITY.md) already establishes mathematical
  capacity discovery in opaque paths and logarithmic navigation without
  installing E-CPU in those paths.
- [In-Formation-Space PON-003](https://github.com/Kier73/In-Formation-Space/blob/main/experiments/passive-orbit-cache/PON-003.md)
  addresses signed immutable object publications and origin-failure recovery.
  PATH-GROUND-003 **does not duplicate its passive-orbit catalogue or its
  independent publication signature scheme**. It tests the *active HTTP
  protocol state predicate* and checks representations across alternate
  routes to one GitHub-managed repository.
- E-CPU [Computational Objects and Time](COMPUTATIONAL_OBJECTS_AND_TIME.md)
  already separates content identity from host identity and permissions.
  `ConditionalHTTPGround.place_in_existing_object_store` revalidates the
  original observations and can pass verified bytes directly to the
  **existing** `ComputationalObjectStore`. No new authoritative object
  store, Hypervisor, transport or execution scheduler is introduced.

## Distinct evidence classes

| Evidence object | Supports | Does not confer |
|---|---|---|
| Commit SHA + Git blob OID | Exact repository state address and Git byte identity | Authorization, origin publisher identity |
| Retrieved JSON/base64 + raw bytes | Same requested bytes seen by distinct HTTPS access routes | Physically independent hosts, durable availability |
| ETag + same-URL 304 response | The remote service answered the conditional representation predicate under the checked request | Universal law, future response, no physical computation |
| Deliberately stale ETag + 200 response | A falsifier: the service returns the same complete response when validator does not match | Proof that intermediate fiber performed arithmetic |
| Ground digest | Reconstructible *meaning* of the fixed file and equality predicate | Packet authentication or permission to run a remote operator |
| Local native object-store manifest | Independently verified retained bytes and paged identity | A claim that the passive GitHub store ran the local verifier |

An observation result is labelled as **past evidence**. Querying the
`ConditionalHTTPGround.navigate` method projects an already checked
observation; it never fabricates a new remote result at an arbitrary future
time. For a fresh live condition, use the actual HTTPS probe again.

The object is immutable because the address uses a pinned commit. This alone
does not prove every CDN edge is immediately consistent or that the
service cannot be unavailable. **The remote object lookup has been observed
through the authenticated GitHub connector; the HTTP conditional behavior
and cross-access-byte comparison await the explicit live check.**

## Local and live verification

```sh
python -m pytest -q tests/test_http_conditional_ground.py
python -m pytest -q tests/test_computational_objects.py tests/test_latent_path_capacity.py
python -m examples.run_http_conditional_ground --commit "$(git rev-parse HEAD)"
```

The unit suite uses typed injected HTTP receipts to check all independent
semantic, content and path relations without claiming a network event.
The live example is **not** a mock: it issues five serial GET requests to
real GitHub HTTPS endpoints, verifies both possible conditional responses,
the remote Git blob ID, the raw file access path and the byte-for-byte local
checkout. Any refusal, 403, rate limit, missing ETag, redirect, mismatch or
unavailable Internet route is a failed observation, not an assumed pass.

`.github/workflows/path-ground-conditional-http.yml` runs the pure
semantic/verifier tests on Linux/Windows and then runs one explicit live
GitHub probe on a Linux runner. The live report is uploaded only if available.
The GitHub Actions runner is a genuine permitted Internet client but not
an independent remote provider or physical network experiment.

## Frontier after acceptance

1. Replace the single GitHub service with **two independently authorized
   state-dependent Internet services** and an independently pinned object
   identity. Keep provider-specific ETags and provenance separate.
2. Observe a declared **path-native operator** at intermediate permitted
   network elements: independently instrumented router hop-limit changes,
   queue-state transformations, or programmable eBPF/XDP service nodes.
   Require an endpoint-only bypass and real packet-level trace, rather than
   attributing software work to passive optical medium.
3. Feed independent path-ground observations into VGI's representation
   equivalence and E-CPU's existing observer-path and quorum continuity
   contracts. A common Ground requires a justified common observation
   relation, not merely the same content hash.
4. Compare the informational cost of remote conditional reads, direct Git
   object navigation, and full content transfer. Account separately for
   HTTP request count, TLS, headers, service compute and returned bytes.

**Architectural conclusion under test:** the Internet can act as an
observer-host fabric with already-existing *stateful predicates*, selectors
and storage. E-CPU's intention chooses which fact to request; evidence
decides whether the fact has been established. It does not replace a
measured information operation with an unverified mathematical assumption.
