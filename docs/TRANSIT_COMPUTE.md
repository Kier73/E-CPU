# Transit Compute Host

## Purpose

This experiment puts a bounded computation request in transit through the existing MailCPU hypervisor operation protocol and executes it on a receiver-side MailCPU virtual CPU.

It does not attempt to host a language model, move model weights, or route ChatGPT's private reasoning into MailCPU. The model or external coordinator remains the planner. MailCPU becomes an independently addressable execution substrate for operations that can be serialized as a bounded request and returned as a finite result.

## Existing transport path reused

The path is:

1. The sender serializes a HypervisorArbitrationEvent with a stable source, channel, sequence and logical time.
2. The event travels over HypervisorOperationChannel and ReliableChannel using SocketTransport.
3. The receiver reconstructs grants from its own process capabilities. Sender-supplied granted rights are not trusted.
4. HypervisorArbitrationLoop selects the operation domain and applies its policy gate.
5. The event-aware handler receives the authorized event and delegates the pure program to a MailCPU compute host.
6. The result is committed to HypervisorOperationResultChannel before the request frame is acknowledged.
7. Semantic duplicates replay the stored effect instead of creating a second VM execution.

The new event-aware reply path is an extension of the existing operation channel, not a second transport protocol.

## Compute request contract

A compute request uses operation name "execute deterministic CPU arithmetic program", resource "/cpu/compute", and an execute right. Its payload contains:

- source: MailCPU assembly text;
- initial_registers: a finite mapping from valid register names to integers;
- max_ticks: a positive scheduler-tick budget.

The receiver admits only SET, COPY, ADD, COMPARE, BRANCH and HALT. SYSCALL, SEND and WAIT are refused, as are oversized source programs, instruction sequences, register maps and tick budgets. This keeps the first host limited to deterministic, side-effect-free arithmetic.

Each admitted request runs in a fresh HeadlessOS instance. A successful result includes terminal status, exit code, program counter, step count, final registers and a digest of the complete observed HeadlessOS state.

## What the test establishes

The real TCP integration test sends a program to another MailCPU endpoint, executes it through the receiver's scheduler, and returns its result through the reverse reliable channel. It checks that the result is correct, that the receiver's capability gate is authoritative, and that a second frame with the same semantic identity replays the result without invoking the compute handler again.

This demonstrates a bounded operation hosted by E-CPU while in transit. It does not yet provide a general-purpose RPC shell for arbitrary host tools, a persistent multi-tenant worker pool, or an external connector gateway.

## Boundary of the assistant integration

Suitable delegated work includes exact arithmetic, finite-state transitions, bounded interpreters and deterministic transformations whose input and output fit the request algebra.

Natural-language interpretation, model inference, private reasoning, browsing, GitHub connector access and other external services remain outside this host. To move a specific external operation behind MailCPU, a separate receiver-side adapter must be implemented, given narrow local capabilities, and tested for replay, failure and side effects before it is enabled.

## Three-mode compute benchmark

Run:

```bash
python examples/transit_compute_benchmark.py --iterations 20 --warmups 2
```

The benchmark evaluates the same (19+23+6=48) integer job in three modes:

1. A minimal local Python reference.
2. Direct `TransitComputeHost.handle` execution, including assembly, isolated HeadlessOS creation, VM scheduling, and state digest generation.
3. A persistent `TransitComputeWorker` over reused loopback TCP operation and result channels, including receiver-local capability authorization, hypervisor arbitration, reliable delivery, response handling, and acknowledgement processing.

It reports median and nearest-rank p95 latency, VM instruction/scheduler-event counts, full encoded request/result frame bytes, acknowledgement bytes, reliable retransmission count, a semantic replay check, and one-time remote stack setup cost. Warmup frames are excluded from wire-byte totals. One extra same-identity request is intentionally sent after the measured jobs to verify that semantic replay returns the committed effect.

The byte counter measures exact ECPU frame encodings at the `SocketTransport.send` boundary, rather than estimating JSON payload sizes. This counts protocol framing and integrity digests. It does not measure Ethernet/IP/TCP headers, retransmissions performed below the application transport, or kernel buffering.

CI runs a short smoke configuration. Use a larger iteration count locally for comparative timing. Treat results as E0 evidence: the TCP endpoints are loopback sockets in one process, so latency is not a WAN or separate-host estimate. The Python path is a minimal arithmetic reference, not a like-for-like Python VM implementation; the benchmark exposes the added cost of MailCPU execution and the additional remote protocol layers rather than claiming a speed advantage.

## Next architectural test

The next step is not to broaden the opcode set or add concurrency immediately. Compare the cost and evidence of three execution modes for the same job: local Python reference, direct MailCPU execution, and reliable remote MailCPU execution through the persistent worker. Measure request bytes, result bytes, instruction count, scheduler transitions, wall time, retries and replay count. Only then add durable worker checkpoints or concurrent-job scheduling, and require restored workers and isolated jobs to preserve the same state relation.


## Persistent receiver worker

`TransitComputeWorker` binds a long-lived service object to one receiver `HeadlessOS` and one local authority PID. For every request it recomputes grants from that receiver's current capability state, routes the event through the existing hypervisor arbitration loop, and commits the result through the reliable response channel before the request is acknowledged.

The worker is persistent; each computation is not. `TransitComputeHost` still creates a fresh isolated `HeadlessOS` for every admitted job. This separates service lifetime from job state and prevents one arithmetic program from inheriting another program's VM state.

The worker currently serves one request per `serve_once` call. The caller owns the transport lifecycle and decides when to call it again. This is a reusable service boundary, not yet a daemon, concurrent worker pool, durable worker checkpoint, or authenticated public endpoint.

The integration test sends two distinct requests through the same worker instance and checks both result paths and reliable acknowledgements.
