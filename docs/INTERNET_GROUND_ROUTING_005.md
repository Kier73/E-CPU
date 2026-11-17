# INTERNET-005 — EvidencePathResolver for intention-selected Internet Grounds

**Status: implementation and native integration tests proposed; native GitHub
Actions must pass before a live E-CPU routing claim is accepted.**

## The development step

The E-CPU proposition is **the Internet is the computer**, with observer-host
and state-space semantics independent of the placement of conventional
processors. INTERNET-001–004 established bounded Git state, HTTP intermediate
retention/transforms, and a read-only RFC link navigator. These experiments
must not become parallel transport stacks, route schedulers or unverifiable
claims about a passive physical medium.

INTERNET-005 connects their **already verified observations** to existing
E-CPU machinery. It uses:

- `EvidencePathCatalogue` and `EvidencePathResolver` for a real,
  multi-dimensional, capability-gated, non-authoritative route decision;
- `RepresentationRef`, `TranslationContract`, `ObservationContract`, and
  `compare_projected_observations` for exact-case meaning preservation;
- `HeadlessOS` process capabilities for **current receiver-local authority**;
- `active_ground_discovery.GroundCandidate` and `GroundAdmission` for one
  already discovered finite-witness navigable affine Ground;
- `public_internet_navigation.Policy` and `verify_capsule` to convert an
  independently retained and verified Internet HTTPS/RFC observation into a
  routable exact case.

This module **does not send a network packet**. Its inputs are observed cases,
not speculative provider promises. An external provider cannot authorize itself:
`InternetGroundRouter` only accepts a provider with a **receiver-installed
validator callback** that checks real source pins, bytes, protocol metadata,
observation scope and costs as appropriate. Each proposed edge must have
exactly equal expected and observed projections for **one** admitted case.
Rehashing an altered value does not make it match the receiver's independent
expected projection. A digest alone is neither a signature nor authority.

## Typed substrate graph

An intention is an exact (source representation, desired representation,
Ground identity, context, logical observation time, cost objective, budgets)
tuple. Observation cases can describe:

| Family | Admitted exact-case operation | Source of qualification |
|---|---|---|
| Git | `observe.graph`, `observe.object` | independently verified Git commit/object/compare results (INTERNET-001/002) |
| HTTP | `observe.content`, `observe.conditional`, `observe.range` | source-pinned HTTP client/proxy receipts (INTERNET-003) |
| DNS | `observe.rrset` | receiver-checked exact RRset and source/TTL evidence; **test fixture only** in this increment |
| RFC | `navigate.references` | replay-verified captured HTML and link path (INTERNET-004) |
| Law | `navigate.affine` | SAB-002 `GroundCandidate` + receiver `GroundAdmission` and independent oracle |

Only exact matching typed representations compose. A DNS name/address
observation is **not** automatically interchangeable with a Git commit, HTTP
body or RFC citation. To compose a DNS step with an HTTP step, the target
`RepresentationRef` of the DNS observation must equal the source
`RepresentationRef` of the verified HTTP observation, and both steps must
preserve the requested Ground/context. The same requirement applies when
switching transports or host topology.

### Example multi-substrate intention

```text
                        +--- Git object observer ----------------+
                        |                                         |
   original intention --+--- DNS RRset observer -> HTTP observer --+--> required representation
                        |                                         |
                        +--- RFC link observer -> HTTP observer --+
```

The native resolver chooses by lexicographic declared cost and resource
ceilings **after** filtering evidence, active leases, process rights, context,
Ground identity, and required observation types. A currently unqualified edge
cannot win because it is cheap; a route never issues its own capability grant.
Service latency or byte counts are *inputs from vetted measurements* and must
not be reinterpreted as propagation speed or universal performance. The test
fixtures use synthetic costs, explicitly not measurements of public DNS.

### Discovery is separate from authority and universal proof

SAB-002's `discover` produces `finite_witness_only` Grounds. `admitted_affine_observation`
requires the existing native `GroundAdmission.bind`, evaluates a single
requested coordinate using E-CPU `law_certifier`, and checks it with the
independent affine-map oracle. It does **not** claim an unknown outside host
actually realized that distant-time state.

The shared resolver's `INDEPENDENT_ORACLE` evidence tier is deliberately
**not** claimed for these case edges. It is reserved for native verified
Transit-oracle evidence with its own exact execution/result binding. A
request requiring that stronger tier must reject the available INTERNET-005
paired-case edges. This avoids promoting a URL/HTTP/DNS receipt into a proof
of arbitrary behavior.

## Test and evidence gates

`tests/test_internet_ground_routing.py` checks:

- route choice across qualified Git, DNS, HTTP and RFC alternatives;
- metric priorities and aggregate ceilings without mixing units;
- missing live HeadlessOS process capability and provider verifier;
- expired and future leases, changes of source and context;
- rehashed forged results, rehashed evidence, pre/post-selection revocation;
- protocol name refusal and detached immutable observation projections;
- the native `INDEPENDENT_ORACLE` requirement refusing paired-case evidence;
- native SAB-002 Ground admission, direct temporal navigation and its oracle;
- INTERNET-004's replay-verified RFC capsule entering the native route.

The RFC fixture is **local bytes**, not a public Internet observation.
The `.github/workflows/internet-ground-routing.yml` job first tests the
actual native resolver and discovery on Python 3.11 and 3.13; separately it
runs an actual internet-connected RFC fetch from the inherited INTERNET-004
navigator, then reads the retained capsule through the new native route
adapter. The worker's newly captured digest is a locally retained receiver
pin, not a publisher signature or independent off-machine attestation.

```sh
python -m unittest discover -s tests -p 'test_internet_ground_routing.py' -v
python -m pytest -q tests/test_evidence_path_resolver.py tests/test_active_ground_discovery.py

# Live, bounded Internet observation; requires access to rfc-editor.org:
python examples/navigate_public_internet.py observe \
    --seed 9293 --target 793 --max-pages 4 --max-depth 2 \
    --file /tmp/rfc-capsule.json

# A receiver must independently supply its exact accepted capsule digest:
python examples/resolve_public_internet_ground.py \
    --file /tmp/rfc-capsule.json \
    --expected-capsule-sha256 <64-hex-receiver-pin>
```

## Next operational frontier

1. Attach **actual source-specific recipient verifiers** to DNS, Git and HTTP
   observations; do not admit mocked fixture outcomes as public Internet facts.
2. Add a **bounded prospective qualification pass**: probe one candidate
   observation only when an independent receiver has approved its host and
   operation. Before qualification, an advertisement is *not* a route edge.
3. Once a route has been selected, execute through existing Transit/
   Hypervisor, check exact before/after and oracle receipts, and preserve
   M1/M3 identity and recovery. That transition remains outside the current
   non-authoritative planner.
4. Measure end-to-end discovery, TLS, carrier, queue, service, verification,
   recovery and state-addressing costs separately, and compare against direct
   endpoints and non-transforming path controls.

**Interpretation:** A family of mathematically addressable internet services
can become a compositional computational architecture without every service
running E-CPU. Each real operation still requires evidence from the place
where it occurred, bounded permissions, and a verifier that understands its
particular Ground.
