# Hypervisor-Governed Host-Service Lifecycle

## Purpose

The host-service adapter connects the existing virtual Hypervisor authority path to
real host subprocesses. It does not create a second classifier, policy engine,
scheduler, or remote shell.

The composition is:

```text
virtual process + local capability
  -> HeadlessOS.hypervisor_host_service_event
  -> Hypervisor arbitration and effect ledger
  -> HostServiceLifecycleAdapter allowlist
  -> SubprocessServiceSupervisor
  -> real host process
```

The Hypervisor governs whether an operation may occur. The adapter selects a
pre-registered host service. The subprocess supervisor owns the concrete PID,
readiness proof, termination, and bounded restart policy.

## Authority and request shape

A caller supplies only a `HostServiceCommand` containing:

- an action from `start`, `stop`, or `inspect`;
- a registered local service identifier.

It cannot supply a command, executable path, working directory, log path, readiness
directory, or process environment. Those remain in the trusted local
`SubprocessServiceSpec` installed during host bootstrap.

The resource is `/host-service/<name>`. The virtual process must hold the
corresponding right: `execute` for start, `control` for stop, or `read` for
inspect. `HeadlessOS` derives those grants from the live kernel process table;
a caller-provided grant is never trusted. The classifier must then select the
SERVICE domain and return ALLOW before the host adapter is invoked.

Each event retains the existing `(source, channel, sequence)` identity and is
processed by `HypervisorArbitrationLoop.execute`. Exact repeats return the
stored effect; a changed request at the same identity is rejected. The Host
adapter is local code and only maps the typed request onto its registered
supervisor entry.

## Lifecycle semantics

- `start` means ensure the registered child is running and readiness-verified.
  Repeating start while that child is alive returns its existing report.
- `stop` clears desired state, terminates the child, and escalates to hard kill
  only after the configured shutdown timeout.
- `inspect` returns the current supervisor report without creating a child.
- Automatic restarts remain owned by `SubprocessServiceSupervisor.reconcile`
  and are bounded by the service's declared `RestartPolicy` and restart budget.

An initial launch/readiness failure is not an exception to restart policy:
`NEVER` remains terminal during later reconciliation. This is enforced at the
restart transition itself.

## Deliberate boundary

The Hypervisor effect ledger is part of the `HeadlessOS` checkpoint. The real
subprocess supervisor and its PIDs are host-side objects and are not serialized
into that virtual checkpoint. Replaying a checkpoint while the same supervisor
remains live reuses the committed effect; it does not re-run the child operation.

This adapter does **not** claim crash-atomic exactly-once effects across a crash
of the host supervisor's own parent process. The deployment must keep that root
manager under an outer operating-system service manager/watchdog. Safe parent
reattachment and durable host-operation generations require an OS service-unit
identity or a separate side-effect-owner journal with PID identity validation.

A dedicated `restart` action is intentionally absent. Stop-then-start is not
replay-safe across a process cut without a durable operation/generation identity;
adding it before that invariant exists would make a retry capable of restarting
the same service more than once. The supported start/stop operations converge
on desired state while the configured supervisor remains the process owner.

## Acceptance coverage

`tests/test_host_service_lifecycle.py` checks allowlisted start/inspect/stop,
virtual capability denial, exact event replay, replay after a `HeadlessOS`
checkpoint, and refusal of non-portable or unregistered request values.

`tests/test_subprocess_service.py` checks that `RestartPolicy.NEVER` remains
enforced when the first child fails before readiness and the next reconciliation
runs without a live `Popen` handle.
