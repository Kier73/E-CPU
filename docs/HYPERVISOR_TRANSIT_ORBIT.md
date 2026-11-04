# Hypervisor-owned transit-orbit control

## Architectural decision

The transit scheduler is an **automatic control-plane service owned by a hypervisor**, not the classifier itself and not an unrestricted background worker.

Three responsibilities remain separate:

| Layer | Responsibility | Authority |
|---|---|---|
| Coordinator hypervisor | Decide whether the local control process may advance the transit scheduler | Coordinator-local capabilities and exact hypervisor policy |
| Orbit scheduler | Select the next ready path using deterministic round-robin order and response-window admission | Scheduler state and path readiness |
| Receiver hypervisor | Reconstruct local rights and authorize the semantic job before its handler runs | Receiver-local process capabilities and policy |

A classifier may advise which execution domain owns a scheduling operation. It does not choose the path, grant a capability, or invoke a worker. The current orbit policy remains deterministic round-robin. The classifier is deliberately not given authority to optimize path placement from latency or inferred “intelligence”.

## Control operation

`HypervisorTransitOrbitController` wraps an existing `TransitOrbitScheduler` and a coordinator `HeadlessOS` authority process.

Each call to `step()` submits one internal operation through `HeadlessOS.hypervisor_dispatch`:

- operation: `execute CPU transit orbit scheduling quantum`;
- resource: `/system/transit/orbit`;
- required right: `schedule`;
- handler: the existing scheduler's `step()`.

The coordinator derives granted rights from the local process capability set. Without `schedule` on the resource, the scheduler is not advanced and the inbound request remains queued. When the coordinator admits the control operation, the scheduler selects at most one path. The selected `TransitComputeWorker` then performs its existing receiver-side authorization before dispatching the actual computation.

The orbit controller exposes one fixed internal handler under every executable domain label, except `REVIEW`. This is intentional: the classifier's domain proposal is advisory and must not redirect this single-purpose control primitive to an unrelated subsystem. The policy action still gates the handler, and the exact `/system/transit/orbit:schedule` capability remains necessary. A `REVIEW` result has no handler and therefore cannot advance the scheduler.

This gives two distinct gates: permission to operate the local path scheduler, and permission to perform the requested operation on its receiving node. The first does not imply the second.

## Automatic operation and continuity

`pump(max_quanta)` is a bounded event-loop adapter. The host calls it when its transport runtime observes new request readiness or acknowledgement progress. It continues while paths are dispatchable, then stops on idle, response backpressure, or a hypervisor decision other than `ALLOW`.

It does **not** start a thread, poll sockets indefinitely, sleep on a wall clock, or invent work when the ready set is empty. The current socket transport contract does not yet expose a unified readiness callback, so the runtime still has to call `pump()`. Logical scheduler quanta remain distinct from wall-clock time and measured RTT.

The orbit cursor, path contracts, and authoritative session checkpoint digests remain in `TransitOrbitScheduler`. The controller snapshot binds that scheduler snapshot to the coordinator authority PID. The coordinator `HeadlessOS` and each transit session are checkpointed and restored separately; `from_snapshot()` requires those already-restored objects. A restored controller rechecks its capability through the hypervisor on every scheduling quantum, so revoking the right stops future scheduling.

## Distributed target architecture

The intended distribution is hierarchical rather than one global classifier with unrestricted authority:

```text
query / job intent
      |
origin hypervisor: classify intent, enforce origin policy
      |
federation navigator: discover eligible node/path contracts
      |
node-local hypervisor: enforce node capabilities and policy
      |
node-local transit orbit: fair scheduling among ready sessions
      |
path transducer: retained memory + observations + bounded operators
      |
registered backend: CPU / SIMT / memory / other verified operator
      |
typed result + receipts + endpoint-local telemetry
```

Each node keeps its own execution and authorization source of truth. Higher levels navigate among advertised capabilities and path contracts; they do not replace receiver-side authorization. Path-local memory, sensor history, and processor state can remain attached to a stable logical path while transport connections are replaced under the existing recovery rules.

The current controller is a local orchestration seam. It does not yet implement peer discovery, authenticated capability advertisements, cross-node consensus, dynamic path admission/removal, automatic route replacement, deadlines, parallel worker execution, or distributed endpoint telemetry. PR #5's live path binding remains a separate observational increment and is not a dependency of this controller.

## Deliberate next step

Before using observed RTT, jitter, service time, retained state, or a learned classifier to rank paths, the project should split probes into requester-local and receiver-local agents and exchange authenticated, typed observations. Scheduling should then compare a fairness-preserving adaptive policy against this round-robin baseline, with explicit starvation bounds and replay/checkpoint conformance. The baseline must remain available as a deterministic fallback.

## Tests

The controller tests verify:
- the coordinator capability gates scheduling and denial does not consume a request;
- admitted pump bursts preserve round-robin order;
- multiple ready paths do not starve under sustained load;
- idle and backpressured boundaries stop a pump without fabricating work;
- controller snapshots restore only against matching sessions and reject tampering;
- invalid pump budgets and invalid authority identities are rejected.
