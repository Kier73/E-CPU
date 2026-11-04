# Three-mode transit path state

## Purpose

`TransitPathState` is a first experimental implementation of one logical path that can change operational role without replacing its retained state:

\[
P=(M,S,C,\mu,t)
\]

where `M` is the RRNS memory substrate, `S` is retained sensor history, `C` is processor output history, `μ` is the current role, and `t` is the path-local logical transition count.

The three roles are **memory**, **sensor**, and **processor**. They are modes of one stateful object, not three independent services. A mode transition changes which operations are admitted; it does not discard the other stores.

This is a local path-state prototype. It does not yet attach itself automatically to a live `TransitComputeSession`, instrument a TCP socket, or participate in `TransitOrbitScheduler` arbitration.

## Role contract

| Mode | Admitted operations | State retained |
|---|---|---|
| `memory` | `store`, `read`, `mark_slot_lost`, `repair` | RRNS groups, residues, slot versions, erasure state |
| `sensor` | `record_sample`, `record_round_trip`, `mark_lost` | RTT observations, sequence order, duplicate/gap/loss/recovery evidence |
| `processor` | `summarize`, `reduce_sensor_metric`, `transform_group` | deterministic results and source/result group references |

`set_mode()` changes the current role. The path identifier, memory engine, sensor history, processor outputs, and logical tick remain on the same object.

### Memory

Memory delegates to the existing `DelayLoopEngine` and its RRNS/CRT representation. `store(value, k, moduli)` projects a non-negative integer into a set of pairwise-coprime residue slots. `read()` reconstructs the value without altering the slots. `mark_slot_lost()` models an erasure, and `repair()` invokes the engine's existing k-of-n reconstruction and regeneration path.

The memory groups are finite integer registers, not a general byte-addressed memory image. The existing engine is an in-process delay-loop model here: this adapter does not transmit or circulate packets over a real network.

### Sensor

Sensor mode retains caller-supplied path observations. `record_round_trip(sequence, started_ns, completed_ns)` computes a duration from two readings of the same local monotonic clock. `record_sample()` accepts a duration already measured by the caller. Delivered observations also feed the existing engine's rolling RTT/jitter estimator, which determines the modeled slot interval.

The event record distinguishes:
- arrival sequence from observation order;
- duplicate delivery from first delivery;
- out-of-order delivery from a forward sequence gap;
- an explicitly reported loss from later recovery of that sequence.

A sequence gap is not itself declared packet loss. A delayed packet may fill it. `mark_lost()` records a loss only when a transport observer or caller has made that decision. `gap_count` counts forward gaps observed at arrival time; it is not a count of currently missing sequence numbers.

The sensor records **round-trip time** when built through `record_round_trip`; it does not infer one-way delay. The caller is responsible for using a consistent monotonic time source and for deciding when a timeout constitutes loss.

### Processor

Processor mode can summarize the retained sensor history and reduce named integer metrics. It can also apply one of the fixed integer operators `identity`, `add`, `sub`, `mul`, `xor`, `and`, or `or` to an existing RRNS memory group. The result is committed as a new RRNS group; the source group remains intact.

The first version uses non-negative operands and non-negative results within the source group's representable range. It is a small deterministic processor algebra, not a general programmable instruction set.

## Time domains

Two time domains are deliberately distinct:

\[
t_P\in\mathbb{N} \quad \text{(path-local logical transitions)}
\]

\[
\Delta t_{RTT}\in\mathbb{R}_{\ge 0} \quad \text{(measured duration)}
\]

A mode change or admitted path operation advances `logical_tick`. A measured RTT is stored in microseconds and updates the delay engine's physical-time estimator. The logical tick is not elapsed time, a scheduler tick, or a network timestamp.

The engine's slot interval is a modeled timing parameter derived from the rolling sample standard deviation:

\[
\Delta_{\mathrm{slot}}=\max(1\text{ ms},\gamma\sigma_{\mathrm{RTT}})
\]

This makes the observed timing profile influence the memory model's slot spacing. It does not yet schedule real network transmissions at those intervals.

## Minimal experiment

```python
from mailcpu import TransitPathState

mods = (101, 103, 107, 109, 113)
path = TransitPathState("path-a")

# Memory mode
source = path.store(42, k=3, moduli=mods)

# Sensor mode
path.set_mode("sensor")
path.record_round_trip(1, started_ns=1_000_000, completed_ns=11_000_000)
path.record_sample(3, 20_000)
path.record_sample(2, 35_000)  # delayed, out-of-order arrival

# Processor mode
path.set_mode("processor")
summary = path.summarize()
result = path.transform_group(source, "mul", 2)

# Return to memory mode: original and transformed values coexist.
path.set_mode("memory")
assert path.read(source) == 42
assert path.read(result) == 84

# The whole logical path, including its role and timing history, is snapshotable.
checkpoint = path.snapshot()
restored = TransitPathState.from_snapshot(checkpoint)
```

A conventional reference implementation can store `42` in a dictionary and multiply it by `2` in a worker. The conformance test checks that the path-mode result is the same while also checking that the original group, sensor history, and role history remain available.

## Snapshot and validation

`snapshot()` produces canonical JSON-compatible path state and a SHA-256 digest. `from_snapshot()` validates the envelope, allocation cursors, group/slot identities, RRNS reconstruction where enough slots survive, sensor-derived flags, mode timeline, and consistency between sensor RTT samples and the delay engine's rolling timing history.

The digest detects accidental or un-rehashed mutation. It is not a signature, peer identity, authentication mechanism, or proof that the observations are true. A caller must supply trustworthy measurements and protect the checkpoint in its deployment environment.

## Current boundary and next experiment

This increment tests the **role-switching hypothesis**, not the stronger claim that arbitrary retained state automatically becomes a sensor, processor, or host.

It does not yet include automatic live-transport instrumentation, WAN measurements, route discovery, network packet delay-line execution, shared-memory semantics, dynamic role selection, path admission into the orbit scheduler, or a physical GPU backend. It also does not claim a latency advantage.

The next integration experiment is to bind a `TransitPathState` to a `TransitComputeSession` path identifier and feed it transport-derived RTT, ACK, timeout, and queue observations. The orbit scheduler may then compare paths using a vector of properties—readiness, response capacity, retained state, observed RTT/jitter, and failure history—rather than choosing by minimum latency alone. That selection policy should be a separate change with explicit fairness and replay tests.
