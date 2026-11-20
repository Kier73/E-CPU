# NCB-006 — A constructed system discovers actual cross-controller resource contention

**Status:** red/green source-generated E-CPU development research. This is an opt-in **receiver-owned local resource reservation** for native *pure* E-CPU actions. It does not create independent physical hardware, an IPS-008 effect authorization, a lease-timeout recovery policy, or quorum-bound physical-capacity attestation.

## Research objective

NCB-003 and NCB-004 allowed a mathematical NCP-002 `CoupledBrief` to describe a shared resource of capacity one. E-CPU separately provisioned a matching `NativeResourceBinding`, then independently checked that one controller's *joint step* required no more than one unit before native execution. NCB-005 fixed cross-representation type identity.

But real systems compete in continuous time. Two independently valid controllers can each claim one unit while both execute at once. A capacity one declaration alone is **not an atomic reservation across independent executions**.

We used the original pinned Navigable-Compute NCP-002 source to construct **two distinct controller implementations** of the exact same coupled intention. Their first source-selected joint steps at state `(2,2)` each require one unit of the same receiver resource, `shared-actuator`. A minimal conflicting schedule is:

    t0: Controller A: acquire 1 shared-actuator unit
    t1: Controller B: acquire 1 shared-actuator unit, before A releases
    t2: A and B both execute native pure handlers concurrently

Only two requests are necessary for a conflict at capacity one; deleting either request makes the schedule feasible. The source chooses the action identities; the test harness controls scheduling through independent native host handler callbacks.

## Original observed defect: RED

[Original unrepaired experiment, CI run #44828590800](https://github.com/Kier73/E-CPU/actions/runs/44828590800) used two independent live native E-CPU `HeadlessOS` instances and the existing `ComputationalExecutionAdmissionCoordinator`/Hypervisor for the two controller instances.

Both handlers were allowed to enter the same resource concurrently. The source-derived safe occupancy bound was **1**; measured maximum was **2**. Initial Linux result: **1 failed test, 19 passed**. This was a **real failure to serialize simultaneously active pure handler calls**, not evidence that a physical actuator or distributed external effect was actually modified.

This counterexample differs fundamentally from NCB-005: both requests and both mathematical packets were valid. Only their **overlapping temporal execution** violated the global resource invariant.

## Targeted green correction: receiver-owned SQLite capacity admission

`mailcpu/constructed_resource_reservations.py` adds an opt-in `ReceiverOwnedResourceReservations` adapter. It deliberately reuses the proven receiver-local design pattern from `mailcpu/fenced_effect_receiver.py` (IPS-007): an independent SQLite database, synchronous durable writes, `BEGIN IMMEDIATE` serialization and atomic commit of the resource check **together with** its local claim.

The receiver installs an exact, bounded resource policy independently of any NCP source. A second process reopening the database with a changed resource name, capacity or action-claim grammar is refused. Every acquired joint request must match that installed policy; the requested amount per resource is computed from the **independently checked** NCP-002 selected action.

Under one database transaction the resource receiver:

1. Reads every currently outstanding reservation.
2. Calculates the total used units per receiver-owned resource.
3. Rejects any new request that would exceed the local capacity.
4. On success, records all required resource units together with exact controller and action digests, and commits atomically.

The new `execute_reserved_constructed_action` wraps the **existing** E-CPU NCB-003 `execute_constructed_action` without altering its resolver, native system Ground, Hypervisor or operator implementation:

- Acquire the receiver's *real* durable capacity claim.
- Re-resolve current native host and operator identity; execute the original **pure** native operation under original capability and Hypervisor admission.
- Independently validate observed successors against the mathematical Ground and rank.
- Always release the local claim when this **pure operation** completes or normally refuses, including a simulated host disappearance after reservation.
- Attach separate content-digested reservation and release receipts to the actual native execution receipt; these are local integrity observations, **not cryptographic or physical authority**.

The earlier NCB-003 entrypoint remains **static**. The new atomic admission requires explicitly choosing `execute_reserved_constructed_action` with a receiver-controlled database. It would be incorrect to claim that all existing callers now acquire atomic capacity.

## Recovery and topology experiments

The generated benchmark uses the same source controller family and evaluates several distinct classes of evidence:

- **Two independent native hosts in concurrent threads:** one controller occupies the shared resource while its real registered handler runs. The other controller, independently qualified and using another native HeadlessOS, must be refused **before handler invocation**. Once the first releases, the second can retry and execute; measured maximum simultaneous native resource occupation is exactly one.
- **Host topology changed between reserve and dispatch:** remove the chosen native host route immediately after acquiring capacity. E-CPU's original fresh route revalidation rejects the operation, and `finally` releases the reservation. A differently provisioned native HeadlessOS can then execute the same pure controller on a live eligible host.
- **Independent OS process holds and releases:** a subprocess checks the original source and reserves one unit in the same SQLite database. A separate process/observer sees its occupancy and refuses until the owner releases. After release, native execution succeeds.
- **Hard process death:** a subprocess acquires the resource and calls `os._exit(73)`. A successor process sees the original durable claim and **refuses to reuse** that resource.
- **Local source/policy mismatch:** reinitializing the database with increased capacity refuses the change, regardless of a mathematical packet's claims.
- **Bad native semantic observation:** a registered pure operator returns an unlisted state; E-CPU refuses the observation and releases the local capacity.

The hard-crash case is deliberately fail-closed. Because this adapter supports only *pure* bounded work, releasing capacity on a normal rejection is safe; but **it does not silently expire or reclaim reservations after process death**. Otherwise an orphan process could be mistaken for inactive while holding a resource or while its effects remain ambiguous. Actual safe reclamation requires separately verifiable receiver-owned process-epoch fencing and/or IPS-008 quorum-admitted handoff—work for a subsequent experiment.

## Reproducibility

The dedicated GitHub Actions workflow runs on Linux and Windows, Python 3.11 and 3.13. It checks out the immutable already-merged Navigable-Compute source `e607fd80c00630f6b31e4c86b9b5ee8faebda410` independently, installs the native E-CPU under test, runs new generated contention/topology/crash tests plus NCB-003/005 and computational coordinator regressions, then executes a separate benchmark that records independently rerun scenarios and wall time to per-platform JSON artifacts.

From E-CPU repository root:

```sh
python -m pip install -e '.[dev]'
git clone https://github.com/Kier73/Navigable-Compute ncp-peer
cd ncp-peer && git checkout e607fd80c00630f6b31e4c86b9b5ee8faebda410 && cd ..
python -m pip install -e ./ncp-peer
python -m pytest -q tests/test_constructed_resource_contention.py tests/test_constructed_controller_admission.py tests/test_generated_counterexample_repair.py tests/test_computational_execution.py
python scripts/ncb006_contention_benchmark.py --output ncb006-evidence.json
```

## Scope and subsequent work

This experiment is **actual receiver-owned local capacity contention for pure operations** across distinct native E-CPU OS hosts/processes. The independently source-generated conflicting schedule and its reduction are finite, not universally optimal adversarial scheduling. The simulation of host removal after reservation is local and deterministic; it is **not authenticated remote mTLS rehome**. The receiver database is trusted by its local process/OS permissions; arbitrary hostile writers with direct database-file access are outside this demonstration.

A next discriminating experiment must connect the same source-generated conflicting schedule to the existing **IPS-008 authenticated effect receiver** and bind assignment advancement to independently validated durable **receiver-owned capacity reclamation** under fencing. Do not reuse this pure-work adapter to permit actual mutable effects or infer a global distributed resource capacity across multiple independent databases.
