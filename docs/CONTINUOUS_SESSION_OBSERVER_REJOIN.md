# Continuously navigable E-CPU sessions and observer-host paths

**Experiment: CONTINUOUS-001 · November 22, 2026**

## Objective

Bootstrap an E-CPU session once, retain a **revision-independent address**, and
navigate back to its latest quorum-committed state after the original process
and its transport session have ended. Separate *identity continuity* from
*continuous execution* and *availability*. The result should survive many
independent process attachments without pinning a backend, socket, URL,
mutable `latest` pointer, or individual state revision into the address.

E-CPU already owns this state through `ComputationalSessionStore` (M3), M1
object storage, and the fixed-membership `RecoveryLineageCoordinator`.
`mailcpu.continuous_session` adds only an addressing/route selection/attach
adapter. It introduces **no new state authority, recovery quorum, transport
protocol, or execution scheduler**.

## Expand the observer-host model through the network

The physical internet is not automatically an E-CPU execution authority.
Different network parts can participate by different **observed relations**:

| Network element | Possible E-CPU relation | Evidence needed before admission |
|---|---|---|
| Copper, optical fiber, radio, satellite, optical amplifiers | **Carrier** of a representation; possibly a measured delay/transfer Ground | Calibrated observation, relevant representation, lease and accessible endpoints; *no inferred host execution* |
| NIC, transceiver, Wi-Fi AP, switch, bridge, router, MPLS hop | **Forwarder**, possibly bounded observer of headers, frame counts, timing or queue state | Owned instrumentation/permission, packet/path observations; no payload transform unless demonstrated |
| TCP/UDP/QUIC, NAT, firewall, VPN, TLS termination | **Transporter or stateful translator**; may retain bounded flow/connection state | Source/destination, parser/transform contract, capability and authenticated endpoint |
| DNS, service discovery, load balancer, service mesh | **Locator/selector**; gives candidate routes and leases | Provenance and expiry; route knowledge is not execution permission |
| WebSocket, HTTP, MQTT, AMQP, email relay, message queue | **Session ingress or durable carrier** | Delivery/acknowledgment semantics, identity, replay policy, authorization |
| Object storage, databases, caches, NAS, repositories | **State or object resolver** | Content digests, durability/fault domain, ACL and exact readback |
| Browser, sensor, mobile app, DPU, edge worker, inference server | **Observer, transducer, executor or verifier** as actually implemented | Typed operation, implementation identity, bounded resource contract, local policy |
| Recovery authority and Hypervisor | **Authority** | Authenticated member identity, durable votes, quorum and exact policy; never conferred by being on a route |

A single device may combine these roles; a compound service may have
sub-observers at ports, queues, protocol stages, verifiers and checkpoints.
Yet a passive carrier is not promoted to a processor, and an observer is not
automatically allowed to execute. Reuse the existing `ResourceObservation`,
`ChannelObservation`, `ObserverContract`, `ObserverReceipt`,
`VerifiedObserverPath`, Fabric directory, and receiver authority.

## The stable rejoin address

`SessionRejoinAddress.bootstrap(store)` first calls M3 `load_latest()` to
require a committed quorum-verified starting state. It stores only:

```text
session_id
artifact_manifest_digest
state_schema_id
membership_digest
schema = mailcpu.continuous-session-address.v1
digest = SHA256(canonical preceding fields)
```

There is intentionally no process ID, physical node, IP address, TCP
connection, current revision, mutable tip, or backend fingerprint in this
address. Backend compatibility is evaluated **at attachment time** by M3.
The address digest is tamper-evident data naming, **not an authentication
signature**. Back it up away from the original bootstrap host.

The address is valid for the **existing fixed authority membership and
term**. Member reconfiguration requires a new binding and explicit
continuity proof; it cannot be silently substituted by a new network route.

## How navigation works

1. Observe an inventory of `ResourceObservation` and
   `ChannelObservation`. Each carries an evidence digest, an observed
   coordinate, and an expiry; these are *claims to be evaluated*.
2. A candidate target resource must advertise the exact typed operation:
   `session.rejoin: session.address.v1 -> session.snapshot.v1`.
   A store for that resource must be **explicitly bound by the receiver**
   and match the address's session, artifact, schema and membership.
3. Receiver-provided `admit_host(resource)` and
   `admit_channel(channel)` must return literal `True`. A digest or an
   operation advertisement never grants permission.
4. Directed channels must be live at the selected coordinate, carry the
   address's representation, and accommodate its bounded encoded size.
   Dijkstra-style bounded cost selection chooses the lowest-cost
   route, breaking ties by hop count then exact channel IDs.
5. The selected route is a **plan**, not proof of message delivery.
   `attach` recomputes the plan at the supplied coordinate. Expired,
   changed, or reselected routes are refused.
6. The selected bound host calls M3 `load_latest()`. This re-verifies
   the *current* recovery high-water, checkpoint digest, complete M1
   state bytes, schema and backend-compatibility requirements.
7. An attachment returns the current verified `ComputationalSessionSnapshot`
   and a bounded evidence projection. Execution, where needed, continues
   via the existing `ComputationalSessionTransitionAdapter` and revision CAS,
   not through a second state machine.

Use the same M3 authority journals, state checkpoint records, and M1
page backing when creating a **new** store instance after a process restart.
Reopening the journals is not itself a vote or a new lineage.

### Minimal local demonstration

```python
# Bootstrap: after constructing an M3 store and committing revision 1
address = SessionRejoinAddress.bootstrap(store)
address.save("rejoin-address.json")

# Later: new process, reconstructed M3 store backed by existing durable
# journals + checkpoint records + M1 pages, with fresh observed paths
address = SessionRejoinAddress.load("rejoin-address.json")
navigator = SessionRejoinNavigator(
    inventory=observed_substrate,
    stores={"eligible-local-host": recovered_store},
    admit_host=trusted_receiver_host_policy,
    admit_channel=trusted_receiver_channel_policy,
)
plan = navigator.plan(address, origin_id="trusted-entry", coordinate=coordinate)
attachment = navigator.attach(address, plan, coordinate=coordinate)
assert attachment.snapshot.checkpoint.session_id == address.session_id
# attachment.snapshot.state_bytes is the current M3-verified state
```

The callbacks and stores above must be **real trusted receiver bindings**.
A test lambda returning `True` is not a deployment authorization
implementation. A local store binding is not a network RPC transport.

## Demonstrated vs. continuing work

**Implemented in CONTINUOUS-001**

- Portable, content-checked, atomically saved rejoin address.
- Revision-independent session identity binding to existing M3 authority.
- Observer-host candidate selection across typed directed, lease-bounded paths.
- Distinction between observed carrier, offered host, and trusted local binding.
- Fresh receiver admission and route revalidation for every attach.
- Current quorum-high-water state verification and exact lineage evidence.
- A process-restart test against reopened durable recovery journals and
  separately retained M1 page backing.

**Still in active development**

- Wire this adapter into a mutually authenticated ingress that can resolve
  a remote host binding instead of a trusted local `stores` mapping.
- Replicate M1 pages, immutable checkpoint envelopes, and authority journals
  across independent physical failure domains and measure real crash recovery.
- Implement persistent discovery/locator distribution with independently
  managed entry points; the supplied inventory does not live forever.
- Add safely fenced receiver ownership transfer, membership/term change and
  placement failover on a continuously available session endpoint.
- Drive a session in a supervised service loop with restart policies and a
  health/readiness contract, rather than treating rejoin as continuous CPU
  execution during outage.
- Qualify physical fiber/router/optical path operations separately from
  software simulations and authenticated host-side transformations.

**Failure model.** The session remains *rejoinable* while its authoritative
fixed-membership lineage, complete current M1 state, trusted entry path and
eligible compatible host can be recovered. Its identity can outlive any
individual process. It cannot be guaranteed to outlive the coordinated loss
of its state and recovery authorities, revocation of credentials, permanent
network partitions, incompatible backends, or loss of all reachable entry
points. Wall-clock uptime and network availability are not inferred from a
logical coordinate.

## Verification

```bash
python -m pytest -q tests/test_continuous_session.py
```

The tests require no production internet access. They exercise real M3
checkpoint/quorum machinery with local authority journals and an immutable
page backing. They are **not** an end-to-end multi-machine deployment or a
proof of indefinite service availability.

See also [COMMUNICATION_HOST_MODEL.md](COMMUNICATION_HOST_MODEL.md),
[OBSERVER_HOST_PATH_COHESION.md](OBSERVER_HOST_PATH_COHESION.md),
[COMPUTATIONAL_SESSIONS_AND_STATE.md](COMPUTATIONAL_SESSIONS_AND_STATE.md),
[SUBSTRATE_ADAPTIVE_BOOTSTRAP.md](SUBSTRATE_ADAPTIVE_BOOTSTRAP.md),
and [THE_INTERNET_IS_THE_COMPUTER.md](THE_INTERNET_IS_THE_COMPUTER.md).
