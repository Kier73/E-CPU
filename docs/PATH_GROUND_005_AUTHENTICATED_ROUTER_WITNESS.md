# PATH-GROUND-005 — Authenticated claims about in-network observations

**Status (November 16, 2026):** implementation, receiver-owned certificate
and signature verifier, cross-platform negative tests, an executable real
mutual-TLS observer experiment, and a dedicated privileged Linux GitHub
Actions workflow are committed on a PR **stacked on PATH-GROUND-004**.
Neither the privileged PATH-GROUND-004 experiment nor this new mTLS
integration should be described as passing until their jobs complete.

## Why the next authentication relation matters

E-CPU's [The Internet Is the Computer](THE_INTERNET_IS_THE_COMPUTER.md)
and [Communication Host Model](COMMUNICATION_HOST_MODEL.md) define hosts as
information observers rather than processor machines. PATH-GROUND-004
sets out to observe IPv4 forwarding at actual intermediate network loci,
with a direct path, a state-preserving L2 bridge, a one-router path and a
two-router path. It reconstructs raw Ethernet/IP/UDP header bytes and reads
kernel `IP_RECVTTL` at the destination. Its native
`ObserverPathStage`, `ObserverContract`, and `ObserverReceipt` objects
bind information identity and the declared operation. **They are not
cryptographic proof that a remote person, machine or kernel collected the
underlying frame.**

The open question is therefore:

> Can the receiving E-CPU establish **which credential asserted the observed
> path state** over an actual authenticated communication channel, while
> retaining the independent mathematical and raw-byte verification needed
> to decide whether that observation is sufficient?

This adapts the verified [In-Formation-Space GCI-004
experiment](https://github.com/Kier73/In-Formation-Space/blob/main/experiments/cross-ground-continuity/gci004/README.md),
which uses E-CPU's own mutual-TLS `SocketTransport`, job-local X.509 CA,
leaf-key ECDSA signatures, receiver-supplied nonce, authenticated
`ComputationalPeerSnapshot`, and a separate auditor. It is deliberately
not a new TLS implementation, scheduler, memory authority or router.

## A separable three-part proof

1. **Mathematical transition:** reconstruct the original source, exact
   raw packet ingress and egress byte sequences, and destination kernel
   observation. The PATH-GROUND-004 verifier refuses absent packets,
   altered UDP content, incorrect IP identities, invented hops, and
   unjustified TTL decrement. Bridge: state-preserving `observe`.
   IPv4 router: observed `transform` with TTL decrement `-1`.
2. **Credential provenance:** establish a real two-way TLS handshake
   with the declared observer process; verify CA trust and exact server
   DNS identity; obtain the actual TLS peer's DER certificate from
   `SocketTransport.socket.getpeercert(binary_form=True)`; verify that
   the same leaf P-256 key signed the precisely challenged raw-capture
   commitment. The signature binds
   `(route, router, raw capture hash, Ground hash, route evidence hash,
   receiver policy hash, fresh challenge, observer DNS)`.
3. **Receiver authority:** even when a signature is valid, the receiver
   independently checks the source/receiver/capture triple and invokes
   its own `admit_local_capture` policy before constructing native
   `ObserverPathStage` witnesses. A captured byte digest cannot mint
   the permission to accept itself.

The signed observation is **a statement by a credential**, not a claim
that all measurements made by that credential are truthful.

## Exact protocol

`mailcpu/router_witness_auth.py` provides a bounded optional adapter:
`make_capture_request`, `signed_capture`,
`verify_signed_capture` and `verify_authenticated_router_route`.
The verification module imports `cryptography` lazily: core E-CPU does
not gain a mandatory cryptography runtime dependency. Test suites that
require its implementation install `cryptography>=42`.

One source data-plane route contains three separately typed records:
a source-send log, one or two intermediate raw captures, and a receiver
log. The bridge is also a real intermediate raw capture and does **not**
change IPv4 TTL.

The receiver first reconstructs the route and pins its Ground, evidence
digest and own policy digest. It then sends a fresh, uniformly generated
128-bit challenge in a MailCPU `OBSERVE` message through the native
`connect_mutual_tls` / `accept_mutual_tls` channel, with separate SAN
identities for `bridge.r1`, `one.r1`, `two.r1` and `two.r2`.

Each observer has one **distinct leaf private key**. Its receiver-owned
observation service reads its local saved capture and checks the exact
requested router identity, source bytes, mathematical Ground and policy
pins before returning its capture and an ECDSA/SHA-256 signature using
the same leaf key used for the TLS handshake. It rejects a second use
of an already answered challenge.

The coordinator checks the received raw capture against the independently
known source record, revalidates the signature against the actual TLS peer
DER certificate and a receiver-pinned CA, replays all native
`ObserverPathStage` constructions and consumes each challenge only
when the **complete route has been accepted**. A failed route consumes
no partial nonce set. All data remains bounded by a 128-KiB capture
budget and the underlying MailCPU framed-message limit.

A route with **no intermediate observers** is retained as a local
source/receiver Ground only. It is not mislabelled as having an external
cryptographically authenticated witness.

## Actual live test

```sh
python -m pip install -e ".[dev]" "cryptography>=42"
python -m pytest -q tests/test_router_witness_auth.py tests/test_router_witness_audit.py
# Linux privileges required for real packet forwarding:
bash scripts/run_ip_router_path_ground.sh artifacts/path-ground-005
# Distinct observer OS processes exchange signed raw captures over real mTLS:
python -m examples.run_authenticated_router_witness \
  --input-dir artifacts/path-ground-005 \
  --output artifacts/path-ground-005/authenticated-observers.json
```

`.github/workflows/path-ground-authenticated-router.yml` runs:
- Signed-witness and receiver refusal tests, the independent audit parser
  controls, and a real unprivileged mTLS observer-process exchange on
  Ubuntu and Windows, Python 3.11 and 3.13.
- On an owned privileged Ubuntu runner: the actual **four PATH-GROUND-004
  network topologies**, then four independent observer **OS processes**
  with real E-CPU mTLS sessions, four distinct ephemeral P-256 identities,
  native raw capture exchange, exact signed response verification and
  deliberate repeated challenge refusal.
- 24 native packet-path reconstructions (six source observations across
  direct / L2 / one router / two routers), resulting in **0/1/1/2**
  signed intermediary assertions by route, never incorrectly counting
  the local direct path as an independent external observer.
- A saved raw/certificate/public signed-receipt evidence artifact.
  Private keys stay in an ephemeral temporary directory and are
  **never** uploaded as workflow artifacts.

Any failure in a privilege, timeout, signature, identity, raw-packet or
native observation step fails the live job. No synthetic packet fixture
may be reported as a passing real routed-network experiment.

### Unprivileged real mTLS regression and independent audit

The cross-platform tests now contain an **actual TCP mutual-TLS process
exchange**, not only an in-memory ECDSA signature fixture. For this
unprivileged regression, its raw Ethernet frames are explicitly synthetic
and cannot establish physical forwarding. It starts the exact
`examples.run_authenticated_router_witness` observer service in another
OS process; a real MailCPU `SocketTransport` negotiates TLS using
certificate SANs and a pinned test CA; the coordinator obtains
`getpeercert(binary_form=True)`, verifies the exact leaf used to sign
the response and proves the second use of that challenge is rejected.
This isolates transport/protocol problems from the privileged Linux
real-router proof obligations.

A third GitHub Actions job, running on a **different runner without
E-CPU installed**, invokes
`scripts/audit_authenticated_router_witness.py` with only
`cryptography` and Python standard libraries. It downloads the public
raw/certificate/signature artifact from the privileged job and
independently reconstructs:

- The original six packet payloads, IP source/destination and UDP ports;
  all four exact L2/L3 route topologies; TTL and IP identification
  continuity; the bridge's zero decrement and the routers' minus-one
  transition;
- The route and shared mathematical Ground SHA-256 identities from
  **original raw records**, not an E-CPU serialized verdict;
- All four distinct P-256 server certificates, expected SAN and server
  role, public CA and leaf signature chain, raw-capture hash commitments,
  challenge uniqueness, exact request/receipt scope and ECDSA signatures.

Its authority scope is intentionally narrower than the full E-CPU
receiver: native `ObserverPathStage` digests are checked for shape and
count, **not rebuilt** by the E-CPU-free auditor; the producer's claim
that a TLS handshake occurred is **not independently observed** by the
auditor; and the ephemeral test CA is transported inside the same
artifact rather than independently provisioned. This is useful
independent consistency verification, not an external-root attestation
of hardware truth.

### Refusals

The tests separately reject incorrect test CA, swapped leaf, false DNS
identity, invalid signature, changed packet, changed Ground or route,
changed receiver policy, unknown router, challenge replay, incomplete
route signer topology, expired certificate, unauthorized collector and
malformed/unbounded request. They demonstrate that signed bytes can
still be rejected as *mathematically unverified*. They do **not** prove
external kernel capture provenance when the observer signs a JSON file
provided by another local process.

## What the experiment does — and does not — establish

Four separate OS processes share **one GitHub-hosted Linux kernel,
runner filesystem and test CA generator**. The processes authenticate
as distinct mTLS identities, but the test runner is a shared physical
failure and administrative domain. The observer service signs **already
captured raw files**; it does not independently operate a packet sensor
on different hardware. This is a deliberate intermediate step toward
physically independent, independently keyed observer loci.

The result proves the system can distinguish:
- a mathematical Ground and its input/output evidence;
- the credential whose private key signed a specific receiver challenge;
- the authorized receiver policy that permits native use of that
  signed-but-not-infallible evidence.

It does not demonstrate public Internet router access, arbitrary
in-network computation, physical sensor honesty, key custody outside
the test runner, credential revocation, or proof of independently
administered operational control. A private network test may later
incorporate operator-held keys and *live packet capture attestation*.

## Next frontier

Take this exact request/receipt contract, with independently
provisioned trust roots, onto **two actually separate authorized
physical hosts**. Keep capture acquisition, certificate key custody,
authenticated receiver authorization, and actual routing in separate
trust domains. Treat result equivalence as intention-relative, as
already emphasized by
[IFS transition congruence](https://github.com/Kier73/In-Formation-Space/blob/main/bridges/observation-equivalence/README.md)
and VGI's observational equivalence studies: the same terminal TTL
does not imply all routes support the same future intentions.
