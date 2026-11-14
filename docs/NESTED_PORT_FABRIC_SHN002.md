# SHN-002 — Nested observer-hosts behind time-multiplexed chip ports

**Status:** falsifiable architecture experiment; virtualized single-interpreter model, **not** a bare-metal E-CPU port controller.

This experiment extends [SHN-001](SELF_HOSTED_PORT_NETWORK.md) without redefining a host as a physical computer. As in E-CPU's [Communication Host Model](COMMUNICATION_HOST_MODEL.md), an active port is an observer-host if it can sample, queue, reject, or transform information. A passive signal conductor is not an execution host merely because data passes through it.

## Hypothesis

A *single E-CPU interpreter* can create a hierarchical network of several logical observer-hosts behind **one or two capacity-limited port lanes**, communicate among them by typed messages, and navigate large computational state coordinates. It should not require one physical CPU core or one external pin per virtual host.

But this **does not** say that adding host names yields extra processors, that signals execute themselves, or that arbitrary state changes are free. Every nontrivial transition needs a physical realization. The experiment explicitly compares the case where the port device itself can carry out bounded result observation against the case where even that step returns to the sole interpreter.

## Real E-CPU components reused

- `OwnedNetworkFabric`: namespaces, point-to-point links, deterministic shortest paths, bounded queues, byte frames, evidence and snapshot restoration.
- `SelfHostedPortNetwork._navigated` and `._projected`: actual E-CPU logarithmic `lcg_navigate` from `law_certifier`, plus the separately defined projection observer; no orbit iteration to large `t`.
- Finite, canonical JSON packets with exact source/route checks, content-addressed worker observations and bounded input limits. Receipts are **not signed** and do not by themselves authenticate hardware.

## Topology

```text
                           ONE INTERPRETER
                                 |
               core.tx0 ------------------- core.tx1
                 |                            |        (tx1 absent for 1-port)
             port0.in                     port1.in
                |                            |
        +-------+--------+             +-----+-----+
        |       |        |             |           |
      v0      v2       v4           v1           v3 ...
        |       |        |             |           |
     guest0   guest2   guest4        guest1      guest3 ...
        \_______ observer-hosts use a single on-chip interpreter _______/
```

Each branch `core.txN -> portN.in -> portN.vK -> guestK.in` is an **actual `OwnedNetworkFabric.find_route`**, not merely a drawing. The `physical_ports` parameter specifies the number of **serialized port-service lanes in the model**, not the number of network namespace endpoints and not externally measured pin hardware. There is zero external data transfer.

A guest's message to the dispatcher returns along its respective lane. The admission clock is logical, not wall-clock time.

## Bounded execution model

Every scheduler quantum has **two explicit budgets**:

1. At most **one interpreter** operation: read a queued query and navigate+project its result, or (in conservative mode) collect/validate a returned answer.
2. At most **one message transmission per physical port lane**, including its internal on-chip route. A one-port chip has one grant; a two-port chip may have two. Each lane multiplexes multiple virtual guests with a bounded round-robin cursor and queue backpressure.

A virtual guest does not run an OS or Python worker independently. `guestK` is a typed observational locus interpreted by the same E-CPU execution engine. On the implemented LCG Ground, `t` can be as large as `10^18` because the **law evaluator** jumps in logarithmic operations. This is conditional on that admitted law, not a universal shortcut for arbitrary programs.

### Two distinct physical hypotheses

**`active_port_observer=True`:** The port's terminal acceptance/compare is credited to an **active-port operation**; a result does not consume a second interpreter slot. This demands real port-side state/control logic in hardware. The simulator still executes that code on its own Python CPU, so this is an *accounting hypothesis*, not independent physical processing.

**`active_port_observer=False`:** The sole interpreter must collect each answer as an additional operation. No port logic is assumed able to finish it. Extra message lanes may have no effect once the interpreter is saturated.

## Falsification and observations

For a fixed workload of **32 requests over eight guests**, the deterministic local scheduler model observed:

| Mode | Physical lanes | Interpreter operations | Port observer operations | Port grants | Logical quanta |
|---|---:|---:|---:|---:|---:|
| Active port observer | 1 | 32 | 32 | 64 | 64 |
| Active port observer | 2 | 32 | 32 | 64 | 33 |
| Interpreter finalizes | 1 | 64 | 0 | 64 | 65 |
| Interpreter finalizes | 2 | 64 | 0 | 64 | 65 |

These are results of the local **test harness's logical semantics** and need confirmation against the exact committed E-CPU code in GitHub Actions. They are not measurements of CPU instructions, energy, nanoseconds, or real port occupancy. In particular, the port-observer mode assumes a physical interface that can discharge completion without interpreter invocation; this requires hardware validation. The conservative result is the negative control: adding a second port **cannot remove the interpreter bottleneck**.

Each request requires exactly two port grants (query+answer). All results are checked against a bounded literal recurrence for small coordinates; large coordinates use the law-based evaluator and receipt checks. Costs track actual canonical packet payload bytes and ports visited; simulation does **not** count electrical framing, routing hardware, serialization bits, energy or Python overhead.

## Reproduce

```bash
python -m pip install -e '.[dev]'
python -m pytest -q tests/test_nested_port_fabric.py tests/test_self_hosted_port_network.py tests/test_owned_network.py
```

The separate `.github/workflows/nested-port-fabric.yml` checks Python 3.11 and 3.13 and uploads `shn002-evidence.json` per job.

Failure controls cover: one interpreter transition per quantum, at most one grant per physical lane, bounded FIFO, duplicate jobs, bad coordinates and host placements, tampered receipts and cost counters even after recomputing an unsigned checkpoint hash, unexpected raw frames, topology changes, and restart from partially completed work.

## Checkpoint and trust scope

The checkpoint contains topology, queues, all jobs, scheduler cursors, frame IDs, provenance receipts, counters and the owned-network journal. `from_snapshot` reconstructs and checks the expected queued frame set and every job's number of port grants, navigation result, and interpreter cost. The `snapshot_digest` protects against accidental change only; an attacker who can rewrite the entire checkpoint and all local authority can forge a new digest. This is not a signed recovery-lineage certificate. It does not demonstrate recovery from power loss in SRAM or cryptographic rollback prevention.

## Next questions

1. Implement an actual small RTL or microcontroller prototype in which port-side active observers and the interpreter have independently measured execution and energy costs.
2. Contrast physical ports as external I/O pins with **on-chip communication transducers**: if no signal crosses an external pin, external pin count alone is not the bottleneck. SHN-002 explicitly budgets the latter *internal port lanes*.
3. Test host-in-host composition with distinct contexts and trust capabilities, instead of a single hard-coded recurrence/projection chain.
4. Replace receipt hashes with receiver-authenticated evidence and durable recovery only when the substrate actually supports it.

The claim supported here is **logical compositional hosting and resource-accounted navigation on one interpreter**. Parallel chip execution, computation in passive wires, and unlimited virtual resources remain unestablished.
