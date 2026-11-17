# INTERNET-004 — The repositories navigate the public Internet

**Status:** executable, bounded, read-only public Internet navigator with independent offline replay and native E-CPU observer-path adapter. A local test does **not** establish a live public fetch; the exact-head GitHub Actions live run must be observed before counting it. No privileged access, arbitrary crawl, remote E-CPU installation, path-fiber computation, unattended background agent, or adversarial website traversal is claimed.

## Question

Can E-CPU use existing Internet information relations to **discover an observation path** from one public document to a requested one and preserve evidence sufficiently for a separate observer to independently reconstruct the claimed path?

Earlier Internet experiments demonstrate native Git object/ref/graph operations (INTERNET-001/002) and actively retained HTTP cache/representation operations (INTERNET-003). Existing In-Formation-Space PON-003 implements stricter source-pinned multi-origin retrieval. The intent here is *actual information-space navigation* rather than inference on a purely synthetically generated Ground or distributing a computation to rented CPU workers.

## Bounded observation Ground

The supported Ground is intentionally narrow: RFC HTML documents on the **exact `www.rfc-editor.org` HTTPS host**, with canonical paths of the form `/rfc/rfcN.html`. One given intention is `RFC 9293 (TCP) -> RFC 793 (earlier TCP specification)`.

- **States:** site-supplied RFC HTML representations, identified by their URL and observed bytes, not by their asserted semantic authority.
- **Transition:** a page contains an actual RFC-to-RFC hyperlink; the navigator checks that link against the observed HTML, resolves the referenced RFC number, and requests its explicitly allowed canonical `.html` representation. RFC Editor links may use `/rfc/rfc793` without `.html`; mapping that RFC identity to `/rfc/rfc793.html` is **local address translation**, not a server-side computation or an automatically followed redirect.
- **Intention:** target RFC number, start RFC number(s), strict maximum depth and page/byte budgets.
- **Internet observer-host:** the *existing* RFC website provides content over HTTPS; E-CPU's configured local HTTP client observes and interprets links. The site is not an E-CPU worker.
- **Evidence:** full bounded raw response bytes, SHA-256, media type, logical parent link, local elapsed time and canonical link set. Body bytes are retained only in the output artifact, not runtime logs.
- **Proof:** a separate process replays exact page content digests and parses all claimed parent-to-child links, then independently recomputes reachability within observed nodes.

Neither a link nor a page digest is permission to execute referenced code. An artifact reconstructed by the same writer can still misrepresent what remote bytes were actually received: TLS protects the *live* client connection but a later unsigned export is not a remotely attested observation. An independent trusted source pin can increase the integrity assurance of a specific version. A page that has no path to the target under the budget gives an explicit `unresolved` verdict, not an inferred result.

## Existing foundations reused

- E-CPU `mailcpu.observer_path_evidence`, `mailcpu.observer_orbit`, `mailcpu.semantic_translation`: native Ground/observer/receipt representation, accepted by local policy, with no shadow authority.
- `mailcpu.latent_path_capacity`: finite observation against model conjectures, a guide to explicit evidence scope.
- Internet-001/002/003: public HTTPS and native Internet service observations with separate remote object identity and local verification.
- In-Formation-Space `passive-orbit-cache/pon003_navigate.py`: URL restriction, bounded GET and independent source-byte verification.
- GitHub Actions provides separate public-Internet-connected observer/verifier processes with read-only repository permissions. The tool execution runtime used to author this experiment has no functional external DNS, so the hosted run is the **live repo execution gate**.

## Reproduce

```bash
python -m unittest discover -s tests -p 'test_public_internet_navigation.py' -v
python -m unittest discover -s tests -p 'test_public_internet_native_bridge.py' -v
python examples/navigate_public_internet.py observe \
  --seed 9293 --target 793 --max-pages 4 --max-depth 2 \
  --file /tmp/rfc-observation.json
python examples/navigate_public_internet.py verify \
  --seed 9293 --target 793 --max-pages 4 --max-depth 2 \
  --file /tmp/rfc-observation.json
```

The first two commands use fake HTML only for adversarial and parser tests. The `observe` command actually makes GET requests to `www.rfc-editor.org` with TLS verification, `Accept-Encoding: identity`, a fixed user-agent, 8-second timeouts, no redirects, at most four fetched RFCs and 4 MiB total content. The `verify` command is offline and checks original page bytes; it never uses the source server or untrusted page claims as a new authority. Both commands fail closed if the target is unavailable within the finite budget.

The GitHub Actions workflow has an offline Python 3.11/3.13 matrix and separate network observation and independent verification jobs. Artifacts are short-lived. A queued workflow is **not** successful deployment and is not evidence of a fetched document.

## What this demonstrates when verified

- A repo-owned E-CPU module itself can resolve a bounded target across public internet links without installing E-CPU code on those services.
- The HTTP source provides actual information states and links; the local E-CPU observer supplies *navigation strategy* and local verification. The path is not represented as a passive medium doing arbitrary arithmetic.
- A new target can be addressed without changing the E-CPU execution substrate, as long as it belongs to the constrained declared Ground and the permitted website actually provides a path.

This is **not yet** autonomous general internet research, active deployment to unknown hosts, or physical signal-level computation. The next stage is to compose multiple qualified Internet observer-hosts (DNS, Git state, HTTP cache, programmable paths) under the existing `EvidencePathResolver` and Ground authority, using measured costs and retaining external trust anchors where required.
