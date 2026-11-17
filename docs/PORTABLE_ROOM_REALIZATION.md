# ROOM-001 — Portable computational rooms and continuous E-CPU realization

**Status:** architectural reference and executable cross-runtime experiment, November 2026. The GitHub repository is the current code authority. This document proposes an approach to deployment and continuity; it does not claim that an autonomous intelligence has already installed E-CPU on arbitrary hosts, that Cloudflare infrastructure has been provisioned, or that a browser has been verified on an independent physical machine.

## The room metaphor

Imagine four walls, a floor, and a roof. An interior designer sees a closed room and has access to a warehouse containing any furniture they can describe. The room can become a studio, workshop, library, or residence according to **(a)** the designer's ability to specify the desired arrangement and **(b)** the room's actual capacity to support it. A description does not grant structural support, electrical power, or permission to enter the room.

The Internet contains many analogous rooms: isolated processes, browsers, cloud functions, database engines, object stores, message brokers, specialized hardware, collaborative execution services, and hosts capable of receiving and forwarding representations. Some can execute transformations, some can retain information, some can observe events, and some can only move already-realized information between other rooms.

The E-CPU ambition is not to clone a complete conventional machine into every room. It is to **preserve one mathematical intention across diverse compatible realizations**. The intelligence can discover and recommend how a room might be furnished; the local environment and receiver retain the right to determine what is implementable and authorized.

The first distinction is between *information capacity* (what a description can represent), *operational capability* (what the environment can actually realize), and *admitted authority* (which realized operations are permitted to count). These are related but never identical.

## A portable seed rather than a complete installation

The seed should be compact, immutable where possible, versioned, and interpreter-neutral. It specifies:

1. **Intention:** the mathematical source relationship, target observation, input/context, and resource budget without encoding a preferred deployment host.
2. **Representation:** a canonical, typed and content-addressed serialization of that intention and of accepted observations.
3. **Realization contract:** the functions a room must implement, their exact input/output representations, and the verification predicate.
4. **Authority boundary:** an independently supplied permitted host/method pair, authenticated deployment identity, and receiver-owned interpretation policy. A hash or endpoint advertisement never grants these permissions.
5. **Recovery lineage:** a predecessor-bound revision history with a separately retained monotone high-water anchor. Content hashing is necessary but does not by itself prevent replay of an earlier valid snapshot.
6. **Reconstruction:** a receiver that can re-derive the intention and check the evidence without executing producer code or relying on a live producer.

A room does not need the entire E-CPU codebase if it implements one compatible subset. It must refuse a demand outside that subset instead of implicitly changing the intention.

### Which rooms can take which roles?

| Environment | Possible role | Reawakening / retention | Grounded limitation |
| --- | --- | --- | --- |
| GitHub Actions / CI runner | Temporary builder, experimenter, or verifier | Another workflow run receives a retained, pinned artifact | Jobs terminate; workflow permissions and artifact provenance matter |
| Cloudflare Worker + Durable Object | Event-triggered HTTP interface with attached persistent state | Request, and potentially a configured alarm | Requires explicit cloud deployment/bindings; identity and access policy stay outside content hashes |
| Browser + WebAssembly | Portable independent mathematical realizer and observer | User interaction or permitted browser events | A page may be closed, service workers evicted, and browsers have CSP/runtime constraints |
| Serverless function | Bounded on-demand transformation | Authorized invocation or event | Execution is time- and resource-bounded |
| Database / object store | Addressable structured memory or supported native transformation | Another interpreter queries stored state | A passive store does not run arbitrary operators |
| Broker / durable queue | Retained observations and work notifications | A permitted consumer reconnects | Message delivery is not equivalent to semantic acceptance |
| Embedded/edge device or sensor | Fixed observer, local transformer or interpreter | Device-specific events or authorized remote sessions | Capability varies; remote access does not imply installation rights |
| DNS / cache / ordinary network path | Observation, address resolution or transient state | A future request or matching cache read | Transport and caching are not arbitrary computation or persistence guarantees |

This classification follows E-CPU's [Communication Host Model](COMMUNICATION_HOST_MODEL.md), [SAB-001 adaptive bootstrap](SUBSTRATE_ADAPTIVE_BOOTSTRAP.md), [SAB-008 Ground-native realization](GROUND_NATIVE_REALIZATION_SAB008.md), [SAB-007 forwarded continuity](FEDERATED_GROUND_CONTINUITY_SAB007.md), [EvidencePathResolver](EVIDENCE_PATH_RESOLVER.md), and [Recovery Lineage](RECOVERY_LINEAGE.md). The new experiment does **not** reimplement their production security or mathematical authority mechanisms.

## The role of intelligence

The intended intelligence resembles the interior designer:

- **Recognize** the room's interfaces and concrete affordances from permitted measurements, rather than inferring them from a marketing label.
- **Propose** a useful local realization of a particular intention; a learned model can rank proposals and information-gathering actions.
- **Acquire** only those observations needed to distinguish candidates under the declared intention and evidence budget.
- **Construct** a locally permitted adapter using known implementation methods; publication or installation is an authorized action, not a consequence of finding a URL.
- **Verify** observable behavior with a separately supplied Ground and checker, not a model confidence score.
- **Retain** accepted evidence, model revisions, and pending intentions so that an unrelated room can reconstruct work after the original execution disappears.
- **Learn** which representations and adapters are useful in unfamiliar environments, measuring both successes and counterexamples.

A particularly promising learning target is *which operation or observation would reduce uncertainty enough to accomplish the intention*. The model need not contain all facts in advance; it can preserve and rediscover relationships, but it must not certify its own extrapolations.

## ROOM-001: the three-room experiment

The accompanying code under [`experiments/portable_rooms/`](../experiments/portable_rooms/README.md) establishes a deliberately finite demonstration. Each room receives **the same Ground**:

`x(t+1) = (17*x(t) + 29) mod 65521`, with `x(0)=5`.

The intention requests the state at coordinate `1,000,000,000,137`. The law admits logarithmic-time mathematical navigation rather than replaying every transition. The target observation is `64,379`.

| Stage | Actual tested realization | Work it performs | Retained evidence |
| --- | --- | --- | --- |
| 1. GitHub-style runner | A Python process, with native E-CPU SAB-008 cross-check when installed | Creates canonical intention, computes the observation, commits initial receipt | Generation 1 with pinned intention digest |
| 2. Cloudflare-style Durable Object | A separate Node process exercising the same explicit transactional storage contract through a restricted local adapter | Rechecks the intention, reads the previous head, computes and commits the next receipt | Generation 2 with predecessor-bound digest |
| 3. Browser-compatible WebAssembly | A fresh Node WebAssembly runtime executing a compiled C function, plus a browser HTML harness | Independently computes the same value; checks prior receipt chain and expected executable-byte digest | Generation 3 and checked head |
| 4. Independent receiver | A fresh Python process | Checks the full receipt chain, the independently supplied latest head and Ground semantics, optionally against native SAB-008 | Offline verification with zero producer calls |

**Scope distinctions:** Stage 2 is a local contract simulator, not a deployed Cloudflare Durable Object or evidence of a `workerd` transaction. Stage 3 truly executes WebAssembly, but the automated test uses Node's WebAssembly engine; the included HTML page enables a future real-browser experiment. CI runs the sequence across separate GitHub Actions jobs with transferred immutable artifacts, rather than claiming that those jobs are different cloud providers. No external infrastructure account, paid plan, domain, public endpoint, or deployment token is used without explicit configuration.

The Worker source and Wrangler configuration example are ready for authorized external deployment and verification. A production deployment would also bind an authenticated ingress, the trusted Ground and bootstrap head in its *own* configuration, a durable monotonic high-water policy, real TLS/identity evidence, and an independent third-host witness. The reference code uses a bearer token at its HTTP entrance but is **not** advertised as a production-grade hosting system.

## Necessary falsifiers

The experiment should explicitly refuse:

- Any changed intention, schema, Ground coefficient, projection, or source identity.
- An incorrect observation even if an attacker rehashes the modified receipt.
- Reordered or missing receipts, wrong predecessor, or a replayed earlier head despite individually valid hashes.
- An environment asking to advance an unapproved room or use a different method.
- A Cloudflare-style adapter without externally supplied trusted pins or with stale expected-head challenge.
- A WebAssembly module whose bytes do not match the independent executable pin.
- A conclusion that a digest proves a publisher signature, durable authority, or independent infrastructure.
- A conclusion that an inactive cloud function performs new work without a triggering request, alarm, or authorized scheduler.

### Where to go next

1. **Native E-CPU authority integration:** carry the same source into `AdaptiveBootstrap`, `GroundIntention`, receiver-side Hypervisor, and the existing `RecoveryLineageCoordinator` instead of a simplified research policy alone.
2. **Actual Cloudflare runtime verification:** with explicit account authorization, run the Worker in `workerd` or Wrangler's integration harness, then deploy against a privately configured Durable Object; measure state persistence across isolate restart and exact replay/conflicting-write rejection.
3. **Real browser execution:** serve the pinned WebAssembly module with the required MIME type and CSP, run the browser verifier and verify its receipt on a separately controlled receiver.
4. **Cross-provider interruption:** kill the original runner, disable the Worker, restart the browser or alternative host, and require a new current high-water witness before admitting recovery.
5. **Learned room-selection policy:** reuse PGT-001–005's synthetic-trained query proposals as **non-authoritative** plans; compare with exact E-CPU search under observed availability, latency, costs, and loss.
6. **Broaden the semantic language:** add finite-graph navigation, exact rational arithmetic, verified neural descriptions, and typed representation translations; demand one meaning across equivalent implementations before expanding the set.

## Position

The deepest proposition is not that a description abolishes the need for executing infrastructure. It is that **a computation's identity and verifiable meaning need not be owned by any particular physical arrangement**. Environments supply capabilities, power, memory, communication, and authorized transformations; descriptions and evidence allow E-CPU to navigate among them.

Thus, the large goal becomes: *can an intelligence recognize, furnish, test, and maintain enough compatible rooms that the system's understanding and development survive the loss of each individual room?* ROOM-001 measures a first finite slice of that hypothesis.

## External technical references (platform capabilities, not claims of deployment)

- [Cloudflare Durable Objects — getting started](https://developers.cloudflare.com/durable-objects/get-started/) (as of 2026-11)
- [Cloudflare Durable Object storage and lifecycle](https://developers.cloudflare.com/durable-objects/best-practices/access-durable-objects-storage/)
- [Cloudflare Durable Object alarms](https://developers.cloudflare.com/durable-objects/api/alarms/)
- [Cloudflare Workers testing / workerd](https://developers.cloudflare.com/workers/testing/)
- [MDN — WebAssembly JavaScript interface](https://developer.mozilla.org/en-US/docs/WebAssembly/Reference/JavaScript_interface)
- [GitHub Actions documentation](https://docs.github.com/en/actions)
