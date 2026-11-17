# PATH-GROUND-006 — Signed observations at the real packet-acquisition boundary

**Status:** implementation, signed-event verifier, negative controls, real
Linux network-namespace runner integration, and an E-CPU-free independent
auditor are committed. Neither the privileged Linux experiment nor the
cross-platform CI should be described as passing until GitHub Actions
actually completes successfully.

The next proposition is stronger than PATH-GROUND-005:

> Can a network observer **sign each Ethernet frame when it is received by
> its actual packet-capture interface**, before a saved trace even exists,
> and can the receiver verify those observations against its preissued
> mathematical intention, original packet data, and authorized Ground?

The goal is to move from *credential signs a later file* to *credential
signs the observation event at acquisition time*. This is still one
controlled runner and an ephemeral locally issued CA, **not** independent
physical hardware or administrative trust.

## Continuity and existing mechanisms

- [PATH-GROUND-004](PATH_GROUND_004_IPV4_FORWARDING.md) supplies the
  actual Ethernet/IPv4/UDP raw-frame observer, 0/L2-bridge/1/2-router
  paths, receiver kernel `IP_RECVTTL`, and typed native
  `ObserverPathStage` / `ObserverReceipt` verification. It checks
  what occurred **inside** an intermediate Linux kernel forwarding path.
- [PATH-GROUND-005](PATH_GROUND_005_AUTHENTICATED_ROUTER_WITNESS.md) uses
  existing E-CPU mutual TLS, nonce and leaf-key ECDSA signatures to
  authenticate *post-capture claims*. Its separate key identities do not
  independently establish packet acquisition.
- This experiment reuses the exact E-CPU `RouterTTLGround`,
  `verify_router_route`, `bind_router_packet_observer_path` and
  `verify_router_packet_path_binding`. It reuses PATH-GROUND-005's
  ECDSA/P-256 certificate verifier and ephemeral test identity issuer.
  It introduces only a **sensor-acquisition event chain**, not another
  scheduler, hypervisor, runtime, network router or trusted Ground.
- In-Formation-Space's [GCI-004](https://github.com/Kier73/In-Formation-Space/blob/main/experiments/cross-ground-continuity/gci004/README.md)
  demonstrated distinct TLS observer processes and signed request-bound
  projections under an ephemeral CA. E-CPU's
  [observer path evidence](../mailcpu/observer_path_evidence.py) already
  separates passive carriers, observation and active transformation.
  Those roles are preserved here.

## What is actually signed, and when?

Before sending any test packet, the receiver issues **four distinct fresh
128-bit challenges** and four constrained capture plans. Each binds:

- exact router/bridge observer identity, expected DNS SAN, ingress/egress
  interface, source/destination IPv4 addresses and destination UDP port;
- the intended mathematical Ground fingerprint and the
  receiver's **own policy digest**;
- expected six source probe identities, hence 12 exact paired
  ingress/egress packet observations;
- a unique challenge established **before** packet acquisition.

The real Linux router/bridge observer process reads its private test leaf
key and that plan before it raises the `ready` signal. Its
`AF_PACKET.recvfrom` loop then calls
`CaptureTimeSigner.observe(side, interface, raw_bytes)` directly,
*before* adding the frame to the JSON output. The code parses and filters
actual Ethernet/IPv4/UDP bytes. For each accepted frame it signs:

```text
schema + plan_digest + event_ordinal + interface + ingress_or_egress
+ SHA256(original_frame_bytes) + local_monotonic_ns
+ SHA256(previous_signed_event)
```

These form an **ordered, signed chain**, rather than twelve unrelated
hashes. The sensor also signs a final session seal binding the last
event, exact raw-capture digest and count 12. The raw Ethernet files
remain independently readable and byte-identical to PATH-GROUND-004's
expected format. The signer never modifies the packet or performs
forwarding; **the Linux kernel alone** executes TTL decrement or L2
bridging.

The sensor's `monotonic_ns` value is a locally reported acquisition
coordinate. Its signature authenticates the statement by that process,
not the physical clock or an independent hardware timestamp.

## Receiver-owned admission

`mailcpu/live_router_capture.py` exposes the receiver-side contract:

1. Reconstruct the raw IPv4/UDP path, one packet at a time, using
   PATH-GROUND-004. Reject altered payloads, missing frames, unobserved
   hop transformations and changed source identities.
2. Compare each event to the **original corresponding raw frame** and
   the receiver's independently held **preissued plan**.
3. Verify a separately pinned CA and expected sensor DNS certificate,
   server identity, validity and P-256 key; reject unrecognized keys.
4. Verify all twelve signatures, event order, monotonic sequence and
   hash links, plus the final signed seal. A correct hash alone is
   never accepted as proof of key possession.
5. Require a receiver-installed `admit_capture` policy, then rebuild
   all six native E-CPU path receipts from the raw evidence.
6. Mark the challenge consumed **only after** the entire signed
   multi-sensor route and its six native witnesses pass. Partial
   verification never consumes some challenges but leaves others.

The four topologies still have different roles:

| Observed path | Intermediate observers | Raw signed events | Native packet paths |
|---|---:|---:|---:|
| Direct | 0 | 0 | 6 |
| Native L2 bridge | 1 | 12 | 6 |
| One native IPv4 router | 1 | 12 | 6 |
| Two native IPv4 routers | 2 | 24 | 6 |
| **Total** | **4 identities** | **48** | **24** |

This is a *verification target* in the workflow; no run should be
reported as successful from code inspection alone.

## Run on an owned privileged Linux machine

```sh
python -m pip install -e ".[dev]" "cryptography>=42"

# Receiver creates keys and plans BEFORE any packet is sent.
# The private directory is not uploaded to CI artifacts.
python -m examples.run_live_capture_ground --prepare \
  --private-dir /tmp/pg6-private \
  --public-dir artifacts/pg6-public

# Requires CAP_NET_ADMIN, CAP_NET_RAW and permitted sudo privileges.
# Inside each isolated router namespace, the sensor process loads its
# private key and signs real AF_PACKET bytes at the receive boundary.
PG6_SIGNING_DIR=/tmp/pg6-private \
  bash scripts/run_ip_router_path_ground.sh artifacts/pg6-public

# The receiver checks its own original trust file, not the self-provided
# plan or root embedded in a sensor's signed report.
python -m examples.run_live_capture_ground --verify \
  --private-dir /tmp/pg6-private \
  --observations-dir artifacts/pg6-public \
  --output artifacts/pg6-public/live-capture-verification.json

# A separate machine/job may independently check public records without
# installing E-CPU:
python -m scripts.audit_live_capture_time \
  --input-dir artifacts/pg6-public
```

`.github/workflows/path-ground-live-capture.yml` runs
`tests/test_live_router_capture.py` and
`tests/test_live_capture_audit.py` on Linux and Windows
(Python 3.11/3.13). Synthetic Ethernet fixtures in those unit tests are
**not evidence of physical forwarding**. A separate privileged Linux
job creates actual native kernel routes, captures traffic and signs it
at receipt; a third runner downloads only public raw/signature
artifacts and independently validates all four certificate identities,
48 packet-event signatures, 4 sealed sensor sessions, original raw
packet relations, Ground digests and event-chain order. The separate
auditor imports only `cryptography` and Python standard libraries:
it **does not install E-CPU**.

The auditor's trust root is still an **ephemeral root included in the
public experiment artifact**. This demonstrates independent
cryptographic/packet consistency verification, not independent
certificate issuance, mTLS transcript verification, physical key
custody or honest hardware capture.

## Applying the contract to genuinely distinct observer-hosts

The code accepts **externally provisioned private keys, plans and
trusted certificates**, rather than requiring observers to generate
their own trust. For an independent deployment, each operator would:

1. Operate an authorized physical network interface and install an
   observer key that the E-CPU coordinator cannot read.
2. Enroll the observer's leaf identity under a root independently
   pinned by the receiver; deliver a fresh receiver-generated plan
   over an authenticated management channel **before acquisition**.
3. Execute the same observer-side `AF_PACKET` acquisition/signature
   loop on that operator's own permitted interface, with the same
   finite packet verification and no simulated forwarding.
4. Transport raw frames and signed events to the receiver via E-CPU's
   existing mTLS/SocketTransport with actual identity
   authentication; refuse replay and unauthorized capture admission.
5. Compare observed network path, observer credentials and intended
   computation without claiming that equivalent terminal observations
   imply universally equivalent paths.

**Not yet demonstrated:** two independently administered external
machines, encrypted cross-host live sensor streaming, external CA or
hardware-protected private key custody, hardware timestamps,
attested operating-system capture, passive optical arithmetic,
or independent access to routers on the public Internet. The current
source/route address and interface set is a deliberately finite
private-Linux test topology; it must be parameterized and
independently enrolled for any actual external deployment.

The essential advance is that the sensor's cryptographic assertion
now occurs **at the packet-observation boundary**, while the receiving
E-CPU still determines the mathematical validity and sufficiency of the
observation. Neither the credential nor the path alone is allowed to
declare the result true.
