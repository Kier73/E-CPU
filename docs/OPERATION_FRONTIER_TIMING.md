# Operation Frontier Timing and Placement Benchmark

## Purpose

This document defines the phase-separated timing record for operation-native MailCPU frontiers and the first reproducible comparison across local CPU, remote CPU, and remote E-GPU placement.

The benchmark holds the semantic work constant: one compiled MailCPU MUL frontier, the same typed contextual-orbit predecessor, the same operands, the same output observation, and the same scalar reference checks. Only the placement changes.

The goal is to distinguish interpretation and admission cost from backend computation and communication cost. This is an observability baseline for future placement selection, not a performance claim.

## Run the benchmark

From the repository root:

```sh
python examples/operation_frontier_benchmark.py \
  --warmups 1 \
  --iterations 5 \
  --lanes 64 \
  --multiplier-bits 2048 \
  --output operation-frontier-timing.json
```

OpenSSL must be installed because the script creates a short-lived CA and peer certificates for mutual TLS. The script starts a one-hop receiver over loopback TCP, advertises separate CPU and E-GPU loci under the same MUL@1 operator contract, executes each remote placement, and tears the receiver down.

The default workload has 64 independent MUL nodes in one ready frontier. Each lane consumes a typed contextual-orbit predecessor, exercising receiver-side rehydration and provenance validation. A bounded 2048-bit multiplier keeps all products within the shared 4096-bit binary operand/result domain.

The local baseline uses the same compiled plan and local DAG evaluator. Remote CPU and remote E-GPU use the same plan, operation contract, mutual-TLS route and origin-side reference verification. Every run is compared with the MailCPU reference interpreter and every lane is checked against the scalar product.

## Timing model

Every duration is recorded by an `OperationTimingProbe` backed by the existing `TemporalContext` with the MONOTONIC and CAUSAL domains enabled.

A probe belongs to one logical actor/endpoint. Its monotonic reading is scoped by `(actor_id, segment)`; only readings from the same actor and segment may be subtracted. Each sample also carries actor-local causal stamps and a correlation ID so phases belonging to the same operation can be related without fabricating a global clock.

### Phases

| Phase | Actor | What it measures |
|---|---|---|
| `total_completion` | Origin | Complete local DAG or operation-native execution through verified result commit |
| `local_compute` | Local CPU | Local MUL operation evaluation within a ready frontier |
| `fabric_route_resolution` | Origin | Semantic host and peer-route selection |
| `origin_round_trip` | Origin | Full authenticated forwarding RPC interval |
| `transport_request_send` | Origin | Reliable request enqueue/send interval |
| `transport_response_wait` | Origin | Wait for the matching response |
| `transport_request_ack_wait` | Origin | Wait until the exact request transport frame is acknowledged |
| `receiver_peer_admission` | Receiver/network | Decode and validate the incoming envelope, adjacent route, and local forwarding/execute authority |
| `receiver_route_dispatch` | Receiver/network | Inclusive dispatch through terminal execution or relay forwarding |
| `receiver_semantic_resolution` | Receiver/network | Fresh receiver-local resolution of the advertised host locus |
| `receiver_witness_revalidation` | Receiver/network | Execution coordinator repeats semantic resolution against the live catalogue and exact route witness |
| `receiver_host_binding_validation` | Receiver/network | Check the selected local locus/runtime/handler binding against the addressed implementation |
| `receiver_admission` | Receiver logical host | Virtual Layer workload, Ground, operator contract, input and Hypervisor admission preparation |
| `receiver_hypervisor_execution` | Receiver logical host | Hypervisor policy arbitration and execution/effect commit after Virtual Layer admission preparation |
| `receiver_provenance_validation` | Receiver logical host | Rehydrate and validate typed operands, contextual-orbit predecessor evidence, and bounded integer inputs |
| `backend_compute` | Receiver logical host | CPU product law or E-GPU `vector.multiply` invocation |
| `receiver_backend_verification` | Receiver logical host | Independent scalar verification of the E-GPU result |
| `origin_verification` | Origin | Independent scalar verification of each returned lane and its pinned memory/provenance inputs |

The handler-level CPU and E-GPU probes are separate actors because they represent separate logical receiver implementations. The forwarding peer/network probe and the Virtual Layer implementation probes are also separate actors.

### Nested intervals are not additive

Some measurements intentionally contain other measurements:

- `origin_round_trip` contains request send, response wait, request acknowledgement, and all receiver work.
- `receiver_route_dispatch` contains terminal semantic resolution, witness revalidation, Virtual Layer admission, backend computation, and receiver verification.
- `total_completion` contains route resolution, remote round trip, origin verification, and DAG publication.

Do not sum nested intervals. The report preserves each interval because it answers a different question. For an additive end-to-end decomposition, use only disjoint spans captured on the same actor. In particular, do not subtract receiver monotonic durations from origin monotonic durations and call the remainder one-way network latency.

## Existing E-CPU time domains

This instrumentation deliberately builds on `mailcpu.temporal.TemporalContext`; it does not introduce a competing time model.

| Existing domain | Role in this benchmark |
|---|---|
| MONOTONIC | Physical elapsed duration, local to a process/actor and restore segment |
| CAUSAL | Local event ordering and operation correlation |
| SCHEDULER | Virtual scheduler tick, retained as logical execution metadata |
| WALL | Calendar observation; not used for duration subtraction |
| EVENT, CHRONON, CHEMICAL | Existing `SystemEpoch` coordinates; not physical elapsed time |

Scheduler ticks are deterministic virtual-time coordinates. Chemical time describes structural difficulty/retention, and chronon/event coordinates describe existing system state. None are converted to nanoseconds or used as a substitute for monotonic timing.

A restored TemporalContext continues accumulated elapsed time in a new monotonic segment; downtime between restore and checkpoint is not retroactively counted. A benchmark should create or retain one probe per actor for the duration of its experiment and must not share a probe across independent endpoints.

## Reading the output

The JSON contains:

- workload/plan identity and exact benchmark configuration;
- local, remote CPU, and remote E-GPU result digests and correctness flags;
- per-actor phase samples with start/end monotonic readings, actor segment, elapsed nanoseconds, causal stamps, and correlation ID;
- per-phase count, minimum, median, p95, maximum, total, and integer mean;
- explicit measurement rules and environment metadata.

The origin's `total_completion` median is the main placement-level comparison. Backend compute should be read beside provenance validation, admission and transport—not in isolation. A tiny backend duration does not imply a cheap execution if operand interpretation, admission or transport dominates.

For placement research, repeat the benchmark across representative lane counts, operand sizes, route lengths, peer loads and Structural Memory access patterns. Keep the semantic operation and correctness oracle fixed. Later selection models can use observed phase vectors, resource costs and route evidence as features; they should not optimize a single aggregate latency while ignoring the cost of interpretation or the authority boundary.

## Boundaries

This first harness measures a one-hop, loopback mutual-TLS route and the bounded Python E-GPU/SIMT realization. It does not establish:

- wide-area network latency or one-way propagation time;
- physical GPU acceleration, occupancy, driver behavior or device-kernel performance;
- a general CPU/GPU speedup;
- concurrent frontier dispatch or multi-host partitioning;
- a trained/adaptive placement model;
- global physical ordering from causal stamps.

The timing probe is side-band. It does not modify operation semantics, workload digests, operator contracts, DAG nodes, execution receipts, or recovery checkpoints. The implementation remains governed by the existing receiver-local Virtual Layer, Hypervisor, and fabric contracts.
