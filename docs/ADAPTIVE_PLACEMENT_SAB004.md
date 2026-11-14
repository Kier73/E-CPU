# SAB-004 — Adaptive composition of qualified observer-hosts

**Status: bounded experiment.** This work composes SAB-003 finite-behaviorally-qualified
resources using SAB-001's existing `AdaptiveBootstrap` Dijkstra planner and typed
`BootstrapTask`; it does not install an entire E-CPU runtime on a foreign host.

## Question

If an environment exposes some but not all of computation, communication,
and retained state, can E-CPU combine those capabilities into one virtual
execution path, preserve the semantic identity of the requested observation,
and later recover without the original compute or relay host?

The experiment does **not** assume that a chip, DNS resolver, optical fiber,
CPU, or service has a particular operation. Each host must first demonstrate
an explicitly authorized fixed-vocabulary role under SAB-003 probing.

## Construction and execution

A `CompositeIntent` is an affine-modular state navigation with a stable Ground
identity and request identity. It names the mathematical observation, not its
execution placement. The qualified inventory contains independent nodes:

1. `computational_fragment`: a known permitted separate worker capable of
   `affine_mod`, independently checked against E-CPU's `lcg_navigate` and a
   second affine-composition implementation.
2. `framed_ipc`: another permitted worker that returns exact bounded bytes
   through its framed stdin/stdout request protocol.
3. `retained_state`: one or more workers that perform immutable key-addressed
   disk writes and answer from a subsequent, separately launched process.

The source `mailcpu.adaptive_placement.AdaptivePlacement` converts valid SAB-003
reports to typed SAB-001 `ResourceObservation`, `OperationOffer`,
`ChannelObservation`, `RealizerBinding`, and `CarrierBinding` objects. It then
asks SAB-001 to select the lowest **declared** logical-cost path:

```
request → [computer: affine_mod] → computed
         → [relay: transfer]      → relayed
         → [store: retain]        → committed
```

The three executable roles must be on **different qualified endpoint identities**.
Six SAB-001 steps include three logical carry edges and three fixed-vocabulary
worker operations. Logical carry edges are local orchestration of typed data;
this experiment does not claim that those edges are authenticated network
transmissions. The `transfer` role does perform a real bounded child-process
IPC exchange. It does not test a remote NIC, a fiber path or a real independent
physical machine.

The route witness does not authorize execution. Before execution, the
controller requalifies the **report against its exact observed challenge
coordinate**, checks that the current coordinate is within its finite lease,
intersects roles with receiver-owned **exact host/operator grants**, and
replans against the current available-host inventory. Every worker exchange
checks the request/reply schema, host echo, nonce echo, framing, and fixed
operation vocabulary. No untrusted source code is installed or executed.

## Crash/recovery and re-placement

An admitted compute result is checked against two independent local affine
navigation implementations, then relayed and written to a data key determined
by the stable intention. For `copies > 1`, the controller writes and reads back
identical records on separately qualified storage loci. Only **after** all
required data copies are present does it issue an immutable durable *decision*
record at a different deterministic key, then read back the decision at every
selected storage locus.

A new controller object can recover the same result using only the intention,
locally admitted storage endpoint, and its decision record. The resumed path
does not execute `affine_mod` or `transfer` again. A lost fast computer can be
replaced with a slower qualified computer; the Ground and result remain stable
while the route and cost change. Retrying a pure request may re-run pure
computation; immutable data and decision keys prevent conflicting accepted
values. **This is not a general exactly-once-effects protocol.**

A crash may leave prepared data without a decision; such data is **not** a
committed result and recovery refuses it. A crash during decision distribution
may leave a valid decision on only a subset of replicas. The decision is
published only after every requested data copy passed readback, but no
Byzantine quorum, external rollback protection, or crash-atomic distributed
commit guarantee is claimed. A disappearing storage host reduces recovery
availability to whichever previously marked copies remain reachable.

## Verification and measurements

- Distinct child interpreters for compute, relay, and two optional storage hosts.
- Qualification/report replay, receiver-owned role admission, independent
  native-Ground numeric oracle, exact byte relay, durable cross-process store,
  and reread of the decision from a new controller instance.
- Tests for resource removal before execution, stale plan, revoked permission,
  missing role, expired lease, switched computation implementation, forged role
  report even when rehashed, insufficient replica count, prepared-but-uncommitted
  state, corrupted checkpoint, idempotent retry, and data recovery after the
  original compute/relay/primary-store loci disappear.
- `measured_controller_ns` measures *only* local elapsed controller operation
  duration. `estimated_quanta` is a declared routing cost. Neither metric
  infers hardware throughput, physical failure-domain independence, power,
  external Internet execution, or quantum/time navigation without physical cost.

## Authority and evidence boundaries

SAB-003 `QualificationReport` is **finite behavioral evidence**, not a hardware
attestation or an authentication mechanism. Known local subprocess commands
are preinstalled and trusted as test interfaces. Nonces here are correlation
checks, not a cryptographic challenge-response protocol with a shared secret.
The controller policy is a local experimental allowlist, **not an E-CPU
Hypervisor admission**. A future implementation must route remote operations
through real authenticated transports, receiver-side Hypervisor decisions,
`ComputationalExecutionAdmissionCoordinator`, and durable recovery lineage.

The output explicitly records `remote_hypervisor_authority_granted=false` and
`independent_physical_hosts_attested=false` so the evidence cannot be silently
promoted into a claim it does not establish.

## Next falsifier: untrusted changes during hosting

Replace one worker with another that uses the same host ID but changes its
operation after qualification. A wrong math result must fail independent
verification. More difficult is a malicious implementation that returns the
expected answer to probes and lies only after an arbitrary later coordinate.
Finite probes cannot prove a universal host contract. True portable E-CPU
hosting will require a receiver-executable trusted interpreter or independently
verifiable transition proofs alongside authenticated endpoint identities and
revocable authority.
