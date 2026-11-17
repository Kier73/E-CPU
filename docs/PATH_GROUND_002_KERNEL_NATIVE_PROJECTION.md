# PATH-GROUND-002 — Recognizing an Internet-protocol operation as navigable capacity

**Status:** experimental native **IPv4/UDP kernel-stack** relation on owned
`127.0.0.1` interfaces, finite observed calibration and withheld validation,
an E-CPU `Law`/Structural Memory bridge, and a direct symbolic state-space read.
This experiment **does not** claim an observed cross-machine Internet hop,
optical processing, authenticated third-party endpoint, or a physical network
producing an affine arithmetic result. Full repository CI is needed before
claiming integrated cross-platform validation.

## Motivation and connection to foundational intent

The [Internet Is the Computer](THE_INTERNET_IS_THE_COMPUTER.md),
[Computational State-Space Architecture](COMPUTATIONAL_STATE_SPACE_ARCHITECTURE.md)
and [Latent Path Capacity](LATENT_PATH_CAPACITY.md) documents establish the
reversal: investigate computational relations **already present** in information
paths, rather than requiring an E-CPU executor on every endpoint.

PATH-GROUND-001 observes real TCP transport and endpoint timing but leaves a
nontrivial FIR mathematical operator as a **software reference**, not a
measured medium transform. CAPACITY-001 independently recognizes a finite
modular affine relation inside opaque *software-specified* paths, but does not
observe that relation in a native OS network protocol.

PATH-GROUND-002 deliberately chooses a narrower, falsifiable Internet-protocol
operation that **is physically present on this machine**: a connected UDP
socket's native kernel selects packets by peer endpoint. The socket receive
queue retains accepted packets while no application `recv` is running. The
sender does not transmit an E-CPU operation to the kernel, and the receiver
application never filters out decoy packets. The operation is built into the
host's TCP/IP stack. This is an **active protocol endpoint**, not arithmetic in
a passive optical carrier, and not remote application execution.

## Composed mathematical Ground

Let the source generate bounded integer test words

\[
x_{n+1}=a x_n+c\pmod M.
\]

**Source-side Python code generates** and encodes these words as four-byte
unsigned UDP payloads. It alternately emits even-coordinate words from allowed
source port A and odd-coordinate words from decoy source port B:

\[
(A,x_0),(B,x_1),(A,x_2),(B,x_3),\ldots
\]

The receiver's actual OS socket is connected to A. With its current network
stack and bounded test conditions, the observable projection is

\[
\mathcal P_{A}\big((p_i,x_i)_{i\ge0}\big)
=\big(x_i\mid p_i=A\big)
= (x_0,x_2,x_4,\ldots).
\]

This is a **real tested input-dependent projection**, not identity transport:
the application observes a different selected stream than the interleaved
source events, and the selection occurs inside the kernel stack before the
receiver reads. A separate unconnected-socket bypass control receives both
streams, showing what happens without this socket operation.

For an affine source stream, the admitted candidate observation law is:

\[
y_k=x_{2k},\qquad
y_{k+1}=a^2 y_k+c(a+1)\pmod M.
\]

For the reproducible stimulus `a=5,c=1,M=257,x0=7`, the receiver's observed
law should be `A=25,C=6`, with initial `y0=7`.

**Crucially:** the network stack supplies the peer-selection and buffering,
not the affine arithmetic. The affine source sequence and its projected law
are separately attributed. The test must fail if the actual receiver bytes
or withheld physical socket observations disagree, regardless of what the
source claims was sent. The same mathematical relation could be applied to
an entirely different pre-existing source stream; its reproducibility would
still require independent evidence for that stream.

## Three distinct computational contributions

| Component | Real contribution | What is not inferred |
|---|---|---|
| Source controller | Generates and encodes test words, chooses sending ports and schedule | Source arithmetic was performed by fiber or router |
| OS IPv4/UDP path | Actual kernel peer filtering, datagram delivery, receive-queue retention during delayed application read | Payload filtering is arbitrary code execution, IP address equals authenticated identity, or remote independently owned hardware was involved |
| E-CPU observer/navigator | Independently verifies receiver bytes, fits a bounded Ground from **selected outputs only**, checks a second socket binding, then symbolically navigates the observed law and optionally stages it in Structural Memory | Direct navigation caused a distant future network event or proves all future packet behavior |

The kernel contribution is a useful **information operation** whether or not
E-CPU has been installed. Its native observability is produced by controlled
socket interaction; a self-hashed report is **not remote attestation**.

## Exact experiment and validation

Implementation: `mailcpu/udp_path_projection_ground.py`.

1. **Predeclare the input language and cost bounds.** Each packet holds four
   bytes, the source has two distinct owned IPv4 ports, the observation
   channel has an explicit lease and size ceiling, and each run has 4–48
   selected datagrams with two source events per selected output.
2. **Connected kernel operator.** Connect the real receiving UDP socket to
   sender A, send interleaved A/B events, pause before any receiver
   application read, check socket readability, then read A's frames. An
   additional readiness check refuses unexpected queued frames.
3. **Bypass.** Use an unconnected receiver under the same source schedule and
   confirm delivery of **both** sources. The bypass does not receive a
   connected-selection receipt.
4. **Observation evidence.** Keep the exact source trace separate from
   received bytes; bind both to immutable canonical content digests, socket
   identities, a native `ChannelObservation`, a pause interval and a
   mechanism/scope label. The source and receiver are controlled by one
   local experiment; this is not independent network authentication.
5. **Mathematical extraction.** E-CPU's existing
   `mailcpu.law_certifier.fit_affine` fits **only** the selected receiver
   sequence. It then applies the existing `Law.navigate` to check each
   observation from a **new socket topology and channel identity**, at the
   next unseen logical coordinates. No source-side parameters enter the
   recognition function.
6. **Navigation.** A request at `10**30 + 113` obtains the symbolic Ground
   value using E-CPU's existing `lcg_navigate` in logarithmic time. The
   result explicitly reports zero additional network packets for the
   symbolic navigation, and says it is **not a future physical measurement**.
7. **Admission and memory.** The observed law is only a proposal.
   `KernelProjectionGround.propose_to_structural_memory` stages it in the
   pre-existing `StructuralMemoryRegistry` with *all* measured witness
   values and the evidence digest. Its trusted receiver `admission_policy`
   must grant admission. The original registry then provides
   `read_revision` with exact certificate and context receipts. No second
   store or authority is introduced.

### Topology change

Training and withheld runs use different ephemeral UDP ports and distinct
`ChannelObservation` identities but the same finite mathematical model.
Thus their **path evidence digests differ** while the recovered mathematical
Ground digest remains independent of placement. This is **logical socket
topology** rebinding on one machine, not independent network paths or failure
domains; a true remote-path experiment remains outstanding.

### Negative controls

`tests/test_udp_path_projection_ground.py` includes real socket bypass and
filter comparisons; changed source law on the second path; contradictory
receiver bytes; modified sender trace or channel identity; channel reuse
masquerading as rebinding; absent ready/empty-queue evidence; forged optical
mechanism labels; malformed numeric/size/lease inputs; symbolic coordinate
limits; Structural Memory refusal without local admission authority; and
witnesses that do not match the supposedly admitted law.

The tests use actual OS UDP sockets. There is **no synthetic UDP filter
or fake Hypervisor** in the network exercise. Structural Memory is native.
No execution-capability grant is inferred from `ChannelObservation`;
the separate runtime Hypervisor remains the owner of effectful execution.

## Reproduce

\`\`\`sh
python -m pytest -q tests/test_udp_path_projection_ground.py
python -m pytest -q tests/test_latent_path_capacity.py tests/test_path_ground_probe.py
python -m examples.run_udp_path_projection_ground > udp-path-ground-report.json
\`\`\`

The JSON report preserves both communication-path identities, the
counterfactual bypass and selected-output counts, observed idle interval,
independently recovered mathematical law, finite witness identity,
Structural Memory version/read receipt, and distant symbolic observation.

## Next physically distributed experiment

A real internet-wide version should have **two separately authorized,
instrumented receivers** with an authenticated control channel and source
identity independent of UDP source IP/port. It should exercise the same
selection and retention contract over actual traversed IP routes, measure
loss/reordering/window occupancy under declared clock domains, and require
held-out observation agreement before admitting a common Ground.

Then investigate route-native operators *not already reducible to receiver
socket filtering*: IP hop-limit evolution, independently observed queueing
dynamics, permitted programmable network-path transforms, or calibrated
physical analog kernels. Keep a control that places the same operation at the
endpoint, and measure the added value of the network stage itself. Do not
treat an ordinary checksum, RTT, packet echo or DNS lookup as evidence for
arbitrary path computation.

The research question remains: **which admitted information relations are
already realizable within the internet's communication architecture, and
which observations can be obtained directly from those relations without
reconstructing a conventional full-state execution?**
