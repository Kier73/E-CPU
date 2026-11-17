# PATH-GROUND-004 — In-network IPv4 forwarding as a verified navigable Ground

**Status:** receiver/verifier implementation, real Linux namespace/veth
forwarding harness, Linux and Windows focused tests, and a dedicated privileged
GitHub Actions test are committed. The owned multi-router test must actually
run successfully before this is reported as *verified kernel forwarding*.
This environment cannot create network namespaces because CAP_NET_ADMIN /
CAP_SYS_ADMIN are unavailable. The standalone kernel `IP_RECVTTL` read was
tested on real local UDP traffic, but that is not a router-hops proof.

## Why this goes beyond remote execution

E-CPU's [foundational Internet proposition](THE_INTERNET_IS_THE_COMPUTER.md)
asks which information relations are **already being realized** in an Internet
path, independently of a MailCPU installation on every locus.

Previous steps cover different experimental boundaries:

- [PATH-GROUND-001](PATH_GROUND_001_COMMUNICATION_OBSERVATION.md) measures
  actual local TCP bytes and endpoint timing, with a separate mathematical
  transfer-kernel control.
- [CAPACITY-001](LATENT_PATH_CAPACITY.md) recognizes a modular affine
  operation among opaque software-defined paths, then navigates symbolic
  state with the existing `law_certifier`.
- [PATH-GROUND-002](https://github.com/Kier73/E-CPU/pull/168) is an open
  unmerged PR examining **real local kernel UDP source selection and queue
  retention** with exact input/output controls.
- [PATH-GROUND-003](https://github.com/Kier73/E-CPU/pull/171) is an open
  unmerged PR examining an active **Internet HTTPS service's conditional
  representation predicate**. Cross-path immutable object resolution was
  observed through connected GitHub; the live `304` check remains queued.
- This experiment examines the packet state **in intermediate kernel
  forwarding nodes**, not an operator run by the source, destination or
  remote HTTP service.

For IPv4, RFC 1812 §5.3.1 specifies that a router reduces TTL when forwarding
and discards a packet whose TTL expires. Linux virtual Ethernet interfaces
and network namespaces let us test this original Internet Protocol function
inside controlled, disposable network contexts:
[IPv4 router standard](https://www.rfc-editor.org/rfc/rfc1812#section-5.3.1).

## The Ground: a transition in the network

For an admitted unfragmented IPv4 UDP packet, let `h` denote the number of
**actual forwarding hops** and `u` its sender-selected TTL. The predicted
observation for a route whose routers each decrease the TTL once is

\[
T(u)=u-1,\qquad
T^h(u)=u-h,\qquad 0\le h <u\le255.
\]

That is a finite, explicit domain; there is no modulo-256 wraparound.
When `h >= u`, the packet cannot be modeled as arriving at the destination.
The RFC requires decrement by **at least** one; the equality above is a
specific, falsifiable candidate for the configured Linux forwarding path,
not a universal claim about all routers in arbitrary conditions.

The existing E-CPU `Law(family="int", step=-1, verdict="GROUND")` supplies
direct symbolic coordinate navigation. E-CPU does not compute the receiving
TTL by replaying `h` router processes. The mathematics can predict a
40-hop coordinate in constant time, but the observation receipt must label
it **symbolic and not physically traversed**.

An inverse intention is equally direct:

\[
u = \operatorname{TTL}_{\text{desired}}+h.
\]

For a desired receiver observation of TTL **31**, a one-router path can
send TTL **32** while a two-router path can send TTL **33**. The respective
actual receiver kernel `IP_RECVTTL` observations are required to agree on
31. This is topology-rebinding of an intention via a common Ground, **not**
an assumption that changing the physical topology leaves the input unchanged.

## Controlled real kernel topologies

`scripts/run_ip_router_path_ground.sh` creates nine **temporary owned
Linux network namespaces**, connects them with six pairs of virtual Ethernet
interfaces, installs finite local routes, and turns on kernel IPv4 forwarding
**only inside the temporary router namespaces**.

| Path | Kernel forwarding nodes | Sender / receiver expectation |
|---|---:|---|
| Direct | 0 | `u → u` |
| One | 1 | `u → u−1` |
| Two | 2 | `u → u−2` |

The source emits six independently recognizable UDP datagrams with TTLs
`4,7,32,33,64,127`. Only the sender process sets `IP_TTL`. Router
namespaces contain **no MailCPU operator, no Python packet forwarder and no
arithmetic evaluator**. Native Linux routing performs the transformation.
The packet is simply forwarded via kernel IPv4 routing tables.

Each real router launches an **observation-only AF_PACKET socket pair**:
one on its ingress Ethernet interface and one on its egress Ethernet
interface. These record the exact captured Ethernet/IPv4/UDP frame bytes.
The destination additionally enables the Linux `IP_RECVTTL` control
message and reads the actual received TTL using `recvmsg`. This field is
supplied by the receiving kernel, not parsed from the source's payload.
These interfaces are specified in Linux `packet(7)` and `IP_RECVTTL`.

### Evidence check

`mailcpu/ip_router_path_ground.py` reconstructs each raw Ethernet/IP/UDP
frame without trusting a sender-supplied decoded TTL. For every packet, it
requires:

1. Exact sender stimulus identity, private controlled IP addresses, port,
   datagram index and **original UDP payload bytes**.
2. Real destination bytes and kernel `IP_RECVTTL` equal to the predicted
   incoming value after the **declared number of actual forwarding hops**.
3. At each intermediate router, **both** ingress and egress captures.
   Their actual IP headers must agree on IP identification, source and
   destination, UDP ports and exact payload, while showing the required
   TTL decrement. Every tested packet must appear exactly once at each
   router side. No unseen packet can be reconstructed from a supplied
   mathematical description.
4. The same canonical fixed probe set across the direct, one-hop and
   two-hop paths, with **different route evidence digests**. The Ground
   digest instead identifies their shared per-hop operation and
   interpretation, independent of route names.
5. Correct destination equivalence when E-CPU inverts the intention to
   choose different source TTLs for different topology lengths.
6. An exact refusal when the desired coordinate exceeds the TTL's
   forwardable domain. The verifier does not wrap, extrapolate a physical
   route that was never observed, or claim independent failure domains.

The verifier also records how many of the raw router IPv4 headers passed an
independent header checksum check. Checksum reporting is diagnostic because
capture points can precede interface offload completion; exact observed
TTL, packet continuity, and distinct ingress/egress evidence are the
required core claims.

### Reuse of the existing E-CPU substrate

The code deliberately does **not** introduce another host catalogue,
Hypervisor, authority ledger, or route scheduler.

- `mailcpu.law_certifier.Law` performs the actual direct mathematical
  navigation; no custom orbit evaluator shadows it.
- `mailcpu.substrate_bootstrap.ChannelObservation` represents each
  independently checked end-to-end path after verification. This is a
  channel/evidence observation **not** a grant or a self-attesting router
  execution receipt.
- `mailcpu.observer_path_evidence.ObserverPathStage` specifies the
  important distinction between **carrier** and **transform** stages.
  This experiment retains actual raw router before/after evidence; it
  does **not forge an `ObserverReceipt` claiming a router signed a
  computational operation**. A future authenticated router adapter may
  attach native observer contracts once the identity and authority
  obligations can be justified.
- `docs/COMMUNICATION_HOST_MODEL.md` distinguishes a host from a
  physical machine. Here one kernel machine contains multiple logical
  router namespaces; they are **not independent physical failure domains**.

## Verification and reproducibility

\`\`\`sh
python -m pytest -q tests/test_ip_router_path_ground.py
python -m pytest -q tests/test_observer_path_evidence.py tests/test_latent_path_capacity.py
# Requires Linux, CAP_NET_ADMIN, CAP_NET_RAW and a permitted local sudo runner:
bash scripts/run_ip_router_path_ground.sh artifacts/path-ground-004
\`\`\`

The unit suite uses synthetic raw Ethernet frames strictly as **parser
and verifier negative controls** and checks a real unprivileged Linux
UDP/IP_RECVTTL loopback observation. Synthetic frames do **not** count
as physical router evidence.

`.github/workflows/path-ground-ip-router.yml` runs the exact parser and
E-CPU regressions on Linux/Windows (Python 3.11 and 3.13), then performs
**actual namespace/veth IP forwarding** on a Linux runner with the
necessary privileges. It records all source manifests, receiver ancillary
observations, real raw router ingress/egress bytes, a verification report,
Ground identity, path-specific evidence identities and a hypothetical
coordinate navigation result as an artifact. If the runner cannot create
network namespaces or capture the packets, the job **fails** rather than
manufacturing a passed result.

This model is a deliberately finite exact observational experiment. It
does not demonstrate public Internet route access, independent hosts,
router signatures, passive optical arithmetic, arbitrary neural weights,
or a physical 40-hop state. External receiver and router attestations
would require new actual authority boundaries; SHA-256 content digests
cannot substitute for them.

## Next frontier

After a successful privileged kernel check:

1. Attach **receiver-owned native ObserverContract/ObserverReceipt**
   to authorized router interfaces, retaining raw packet and clock
   evidence separately from any trust or capability grants.
2. Repeat the path-level observation between two actually separate
   permitted hosts using the same data-plane contract, with authenticated
   source/destination and independent per-hop measurements where possible.
3. Generalize from TTL to compositions of independently measured
   transformations: classifying/filtering, queueing, bounded delay,
   programmable packet processing and, eventually, calibrated physical
   transfer kernels.
4. Form a common navigable Ground across heterogeneous realizations
   **only where their observation equivalence can be verified**. Use
   E-CPU's existing context, Structural Memory, and VGI representation
   reasoning rather than treating matching route IDs as proof of a
   matching mathematical state.

**The question is not whether a remote CPU can process data.** The
question is which information transformations the communications path
already performs, how to recognize them, and how an intention can select
one of their realizable observations with independent evidence.
