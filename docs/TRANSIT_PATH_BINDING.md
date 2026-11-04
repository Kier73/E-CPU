# Live transit path binding

## Purpose

`TransitPathSessionBinding` connects the three-mode `TransitPathState` to a live `TransitComputeSession` and its paired requester-side operation channels.

The binding is observational. It does not replace the session's worker, hypervisor authority, semantic replay ledger, or reliable-channel cursors. The session and channels remain authoritative for execution and delivery. The binding adds an aligned record of physical timing, local service work, queue state, and acknowledgement/retry events.

Its reference composition is

[
mathcal B_P =
(mathcal S_P,mathcal M_P,mathcal R_P,mathcal O_P),
]

where (mathcal S_P) is the existing transit session, (mathcal M_P) is the retained three-mode path state, (mathcal R_P) is the set of paired requester-side channels, and (mathcal O_P) is bounded observational history.

## Three distinct time and state measurements

The binding deliberately refuses to collapse these into one latency:

| Measurement | Clock / authority | Meaning |
|---|---|---|
| Round-trip time (RTT) | One requester-side monotonic clock | Elapsed time from request send to result receive |
| Service duration | Receiver-side monotonic clock | Time spent inside one `session.serve_once()` call |
| Queue / ACK / retry state | Reliable-channel state | Readiness, sender-window occupancy, pending sequences, acknowledgements and retry exhaustion |

RTT is measured from two readings of the same local clock. It does not compare timestamps from different hosts or infer one-way delay. Service duration is measured separately at the receiver; it is not added to the RTT sample as a second estimate.

The binding can also accept an explicit caller-observed operation timeout through `record_request_timeout(sequence)`. A transport frame exhausting retries or failing to receive an ACK is recorded as a protocol event, **not automatically as semantic operation loss**. A request may have been executed or a result may have been received even when its ACK was not observed.

## API

A binding is constructed with:
- the receiver-side `TransitComputeSession`;
- the matching origin-side `HypervisorOperationChannel`;
- the matching origin-side `HypervisorOperationResultChannel`;
- a stable logical path identifier and optionally an existing `TransitPathState`.

The binding validates that the requester-side channel identity is the reverse of the receiver session's request/result identity.

The normal reference cycle is:

```python
binding.send_request(event)
execution = binding.serve_once()
result = binding.receive_result()
acks = binding.process_acknowledgements()
```

- `send_request` records a requester-side start reading and maps the reliable transport sequence to the semantic operation sequence.
- `serve_once` delegates to the existing session and measures receiver-local service duration. Newly pending result-frame sequences are correlated to the semantic operation.
- `receive_result` consumes and acknowledges the typed result, then measures RTT using the original requester-side start and completion readings. The sample is added to `TransitPathState` in sensor mode, after which the previous path role is restored.
- `process_acknowledgements` drains request ACKs at the requester and result ACKs at the receiver, then associates transport sequences with semantic operations.
- `tick_reliability` advances both retry clocks and records exhausted reliable-frame sequences. It does not silently assert that the semantic request/result was lost.
- `record_request_timeout` records an explicit operation-level timeout supplied by the caller.

Queue observations are diagnostic projections of the session phase, request readiness, result readiness, receive cursor, reliable sender windows, and pending sequences. They do not consume frames, alter ACKs, or make scheduling decisions.

## Observation safety and bounds

Telemetry collections have finite capacity. When a collection reaches its bound, the oldest telemetry record is evicted and a dropped-observation counter is incremented. The observer does not block a worker or reject a valid request merely because its diagnostic history is full.

The path's RRNS memory, sensor samples, and processor outputs remain in `TransitPathState`. The binding separately retains service samples, queue observations, and protocol events. This keeps requester RTT separate from receiver service duration and queue metadata.

## Checkpoint boundary

`snapshot()` requires a quiescent boundary:
- the receiver session is idle;
- no request or result frame remains queued;
- the requester has no unacknowledged request frame;
- the receiver has no unacknowledged response frame;
- all local round-trip start records and frame-to-operation ACK correlations are resolved.

The binding checkpoint contains a digest of the receiver session checkpoint, digests of the two requester-side channel states, the path-state snapshot, and the telemetry history. `from_snapshot()` requires the supplied restored session and endpoint channels to match those identities.

The endpoint transports themselves are not serialized by the binding. Callers must restore the receiver session and both reliable-channel endpoints using their existing checkpoint/transport recovery procedures first. The binding is then restored against those live objects.

A SHA-256 digest detects mutation of the canonical checkpoint; it is not peer authentication, an attestation of measurement truth, or a replacement for authenticated transport.

## Current evidence boundary

The first binding is a **same-process reference composition over real loopback TCP connections**. It holds references to the receiver session and requester-side channels so that one binding can correlate the full request/result cycle. This tests actual socket transport and reliable-channel behaviour, but it is not yet a multi-host deployment.

A distributed deployment should split the same observation contract into endpoint-local probes:
- requester-side probe measures RTT and request ACK/retry state with its own monotonic clock;
- receiver-side binding measures service duration, inbound readiness, response-window state and result ACK/retry state.

Those endpoint records can then be exchanged or reconciled through an authenticated telemetry protocol. The current module does not create that protocol and does not assume synchronized clocks.

## Next architectural experiment

The path now has enough evidence to begin evaluating more than speed. A future scheduler policy can use a feature vector such as

[
V_p =
(	ext{ready},	ext{response capacity},	ext{RTT},
	ext{jitter},	ext{service time},	ext{ACK health},
	ext{retained state}).
]

That policy should be tested as a separate increment against deterministic round-robin scheduling. It must preserve fairness, backpressure, replay semantics, and checkpoint continuation. The current binding gathers evidence; it does not yet select paths or fast-forward work.
