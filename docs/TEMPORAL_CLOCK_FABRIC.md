# Temporal Clock Fabric

## Purpose

The observed-stream integration records these domains together in an immutable [TemporalPathTrace](OBSERVED_ORBIT_PIPELINE.md#8-latency-is-a-temporal-vector-carried-by-the-path). Its TemporalDelta calculation only subtracts monotonic readings from the same actor and segment, compares scheduler readings only within one scheduler, and retains causal relations across actors.

E-CPU has several distinct temporal coordinates already in use. This specification adds a process-scoped interface for selecting and observing them without collapsing their meanings into one scalar clock.

The temporal context is a clock adapter and causal ledger. It does not change MailCPU instruction semantics, the orbit scheduler's fairness policy, the reliable-channel sequence numbers, or the existing `SystemEpoch`.

## 1. Temporal domains

| Domain | Representation | Valid use | Not valid for |
|---|---|---|---|
| Local monotonic | Integer nanoseconds, scoped to actor and boot/restore segment | Durations measured by one process | Direct comparison across processes, hosts, or restore segments |
| Wall/calendar | Signed UTC nanoseconds from the local wall clock, plus sample index | Calendar deadlines and external timestamp correlation | Causal ordering or dependable elapsed duration |
| Causal | Lamport scalar plus vector clock | Message/event ordering and concurrency detection | Measuring physical duration |
| Scheduler | Integer tick scoped to one scheduler ID | Deterministic virtual deadlines and work budgets | Host elapsed-time claims |
| Event | `SystemEpoch.event_lambda` | Existing event/transition coordinate | Calendar time |
| Chronon | Complex unit phase from `SystemEpoch.chronon_phase` | Existing geometric/reversible operation coordinate | A timestamp or duration |
| Chemical | Non-negative `SystemEpoch.chemical_tau` | Structural parsing difficulty and its existing resource/retention mappings | Seconds or a physical clock |

The event, chronon, and chemical coordinates are inherited from `mailcpu.chemical_time.SystemEpoch`. The current scheduler advances the event coordinate during task transitions, the chronon phase from active-transition state, and chemical difficulty from the configured task cost. The difficulty coordinate is an algorithmic/structural metric; despite its name, it is not a calibrated physical duration.

A validity horizon from `HorizonTracker` is a bound over a mathematical trajectory. It is not another clock source.

## 2. Process-selected clocks

Each process creates a `TemporalContext(actor_id, TemporalProfile(...))`. The profile is an explicit set of domains. A process may request only monotonic and causal time; a scheduler-facing service may additionally request scheduler ticks and the three SystemEpoch coordinates. A call to `observe()` returns only the selected coordinates and fails when a selected external coordinate is not supplied.

The profile creates a typed boundary between processes. A process that does not declare wall time cannot read wall time through this context. The context does not autonomously advance scheduler or SystemEpoch state; the owning scheduler remains authoritative for those coordinates.

## 3. Physical clocks are endpoint-local

### Monotonic time

A monotonic reading is the accumulated duration observed within one process context:

```text
elapsed_ns = saved_elapsed_ns + (monotonic_now_ns - segment_origin_ns)
```

Each reading carries `(actor_id, segment)`. Duration subtraction is allowed only for readings with the same actor and segment. A backwards sample raises `ClockRegressionError`.

On restore, the context preserves the accumulated elapsed value but increments its segment and establishes a new local monotonic origin. Downtime between checkpoint and restore is deliberately excluded. This avoids pretending that the restored process's new host clock shares the old host's monotonic epoch.

### Wall time

Wall time is a local UTC calendar estimate. It may jump forward or backward due to clock correction. A new sample index identifies the observation order made by this context; it does not turn wall time into a monotonic clock. Wall timestamps from separate hosts are not causal evidence and may carry different offsets.

### No cross-host subtraction

Requester RTT must be measured using two readings from the requester's own monotonic context. Receiver service duration must be measured using two readings from the receiver's own monotonic context. They are two different measurements. Neither side subtracts its monotonic time from the other side's timestamp.

The system may compare these durations as separately measured quantities once their units and measurement provenance are known; it must not derive one-way delay by subtracting unsynchronized endpoint clocks.

The operation-native execution path uses `OperationTimingProbe` to record those endpoint-local intervals with the existing `TemporalContext`. Each sample retains actor identity, monotonic segment, elapsed nanoseconds, correlation ID, and actor-local causal start/end stamps. It records no cross-host timestamp subtraction and does not turn scheduler or SystemEpoch coordinates into physical duration. The measured stages and their nested/inclusive relationships are specified in [OPERATION_FRONTIER_TIMING.md](OPERATION_FRONTIER_TIMING.md).

## 4. Distributed causality

A `CausalStamp` contains:

```text
(actor_id, lamport, vector_clock)
```

A local event increments both the Lamport scalar and the local actor's vector component. On receive, the process merges the vector componentwise, sets its Lamport scalar to `max(local, remote) + 1`, and increments its own vector component.

Vector clocks define a partial order:

- `before`: every component of A is less than or equal to B, with at least one strict inequality;
- `after`: the reverse;
- `equal`: equal vector frontiers;
- `concurrent`: each vector has at least one component greater than the other.

Concurrent events are not forced into a fictitious global physical order. Lamport time supplies a monotone scalar for logical event sequencing; vector time retains the additional information needed to detect concurrency.

An `actor_id` identifies one logical process clock. A migrated process may retain its actor identity while the monotonic segment changes. A deployment must prevent two active writers from using the same actor identity; split-brain identity ownership would invalidate the vector-clock model.

Causal stamps are typed ordering evidence, not authentication. Their digest or JSON representation does not authenticate a sender. A later telemetry protocol must bind the actor identity to an authenticated transport identity and enforce replay policy at its protocol boundary.

## 5. Scheduler and SystemEpoch coordinates

Scheduler ticks remain owned by their named `DeterministicScheduler`. A `SchedulerReading` requires both `scheduler_id` and a non-negative tick, so tick 12 from scheduler A is not silently confused with tick 12 from scheduler B.

`TemporalContext.observe()` can combine a scheduler reading with selected values from the existing `SystemEpoch`. It keeps these fields separate:

```text
scheduler_tick
event_lambda
chronon_phase = (real, imaginary)
chemical_tau
```

No conversion function is defined between these coordinates. A process that needs to decide a virtual scheduler deadline uses scheduler ticks; a process measuring a network wait uses its own monotonic clock; a process examining novelty/retention may use chemical difficulty.

## 6. Checkpoint semantics

A temporal context checkpoint stores:
- logical actor identity and declared profile;
- causal Lamport and vector state;
- accumulated local monotonic duration and its segment number;
- local wall sample index.

The snapshot is canonical and digest-checked. It does not store a wall-clock sample as a causal anchor, and it does not persist a host monotonic origin. Restore creates a new monotonic segment and does not count the offline interval. The digest is an integrity check, not authentication.

Scheduler ticks and SystemEpoch remain checkpointed by their owning scheduler. They are passed into a temporal observation when the process requests those domains; the temporal context does not duplicate their source-of-truth state.

## 7. Relationship to live transit paths

The existing `TransitPathSessionBinding` currently holds requester-side channels and the receiver session in one same-process reference object. It measures RTT with a single local monotonic source and receiver service time with a separate invocation interval. This temporal layer is the prerequisite for splitting that object into endpoint-local requester and receiver observers:

- requester observer: requester monotonic context, requester causal context, RTT, request ACK and operation timeout;
- receiver observer: receiver monotonic context, receiver causal context, service duration, queue readiness and response protocol state;
- telemetry envelope: typed causal stamp and endpoint-owned measurements, exchanged through an authenticated protocol.

The split observers and authenticated telemetry transport are not implemented by this increment. The present implementation establishes the clock contracts and the causal ordering primitive they will use. It does not claim wall-clock synchronization, one-way delay measurement, global event order, or clock consensus.

## 8. Tests

`tests/test_temporal.py` covers profile gating, independent clock domains, wall-clock rollback, monotonic regression, monotonic segment restore, causal merge, vector concurrency, scheduler/SystemEpoch projection, invalid temporal state, and checkpoint tampering.
