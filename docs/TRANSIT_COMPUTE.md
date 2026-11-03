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

A compute request uses operation name "execute deterministic CPU arithmetic program", resource "/cpu/compute", and an execute right. The compute capsule itself requires the exact singleton right set `{execute}` and rejects requests marked destructive. Its payload contains:

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


## Authenticated host-to-host transport

The initial `SocketTransport` uses framed TCP with an integrity digest. That digest detects accidental or malicious frame alteration only when the transport stream itself is trusted; it does not authenticate a peer. Do not expose a plain `SocketTransport` transit worker to an untrusted network.

The `mailcpu.mtls_transport` adapter adds mutual TLS around the same framed transport, preserving the MailCPU message and reliable-channel APIs:

- The client context must verify a trusted certificate chain and the configured server hostname, and must present its client certificate.
- The server context must require a trusted client certificate.
- The server also checks the client's DNS Subject Alternative Name against an explicit expected peer identity.
- Both sides require TLS 1.2 or newer.
- The adapter returns the existing `SocketTransport`, so operation channels and worker arbitration remain unchanged.

Example client setup:

```python
import ssl
from mailcpu import connect_mutual_tls

client_tls = ssl.create_default_context(
    ssl.Purpose.SERVER_AUTH,
    cafile="worker-ca.pem",
)
client_tls.load_cert_chain("client.pem", "client-key.pem")

transport = connect_mutual_tls(
    "worker.example.net",
    9443,
    "client-node",
    "worker-node",
    client_tls,
    server_hostname="worker.example.net",
)
```

Example server setup:

```python
import ssl
from mailcpu import SocketTransport, accept_mutual_tls

server_tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
server_tls.load_cert_chain("worker.pem", "worker-key.pem")
server_tls.load_verify_locations(cafile="worker-ca.pem")
server_tls.verify_mode = ssl.CERT_REQUIRED

listener = SocketTransport.listen("0.0.0.0", 9443)
transport = accept_mutual_tls(
    listener,
    "worker-node",
    "client-node",
    server_tls,
    expected_peer_dns="client.example.net",
)
```

Certificate issuance, rotation, revocation, DNS/PKI trust management, listener lifecycle, and authorization of a certificate identity to a specific MailCPU process remain deployment responsibilities. A valid TLS identity is not itself a MailCPU capability: the receiver still recomputes operation grants from its local capability state. TLS authenticates the connected peer; the hypervisor authorizes the requested effect.

The focused TLS integration test creates ephemeral test-only CA and leaf certificates, performs an actual loopback mutual-TLS handshake, checks both peer identities, and sends framed MailCPU messages in both directions. It does not demonstrate a deployed separate-host service.

## Three-mode compute benchmark

Run:

```bash
python examples/transit_compute_benchmark.py --iterations 20 --warmups 2 --work-units 64
```

The benchmark evaluates the same repeated-addition workload in three modes. For `n` work units, each path computes `A_n = Σ(19+23+6) = 48n`; MailCPU runs a bounded loop and the Python reference runs the corresponding loop:

1. A minimal local Python reference.
2. Direct `TransitComputeHost.handle` execution, including assembly, isolated HeadlessOS creation, VM scheduling, and state digest generation.
3. A persistent `TransitComputeWorker` over reused loopback TCP operation and result channels, including receiver-local capability authorization, hypervisor arbitration, reliable delivery, response handling, and acknowledgement processing.

It reports median and nearest-rank p95 latency, VM instruction/scheduler-event counts, full encoded request/result frame bytes, acknowledgement bytes, reliable retransmission count, a semantic replay check, and one-time remote stack setup cost. Warmup frames are excluded from wire-byte totals. One extra same-identity request is intentionally sent after the measured jobs to verify that semantic replay returns the committed effect.

The byte counter measures exact ECPU frame encodings at the `SocketTransport.send` boundary, rather than estimating JSON payload sizes. This counts protocol framing and integrity digests. It does not measure Ethernet/IP/TCP headers, retransmissions performed below the application transport, or kernel buffering.

### Initial CI observation

A one-unit baseline run on GitHub Actions Linux / Python 3.11 (6 measured iterations, 1 warmup; run 41703175898) reported:

| Mode | Median | p95 |
|---|---:|---:|
| Local Python reference | 0.000611 ms | 0.000681 ms |
| Direct MailCPU | 4.526 ms | 4.643 ms |
| Remote MailCPU over loopback TCP | 6.378 ms | 6.843 ms |

Each VM path executed 6 instructions per one-unit job. The remote stack setup was 3.876 ms. Across the six measured requests plus one replay, the run counted 5,607 request bytes, 6,726 result bytes, and 4,137 ACK bytes (16,470 bytes total in both directions), with one semantic replay and zero reliable retry frames.

This tiny arithmetic task does not amortize MailCPU setup or transport costs. The result is a protocol-cost baseline, not a performance claim; increase workload size and run repeated samples before considering optimizations.

CI runs 64 work units per job with 6 measured iterations and 1 warmup. Use a larger iteration count locally for comparative timing. Treat results as E0 evidence: the TCP endpoints are loopback sockets in one process, so latency is not a WAN or separate-host estimate. The Python path is a minimal arithmetic reference, not a like-for-like Python VM implementation; the benchmark exposes the added cost of MailCPU execution and the additional remote protocol layers rather than claiming a speed advantage.

## Next architectural test

The next step is not to broaden the opcode set or add concurrency immediately. Compare the cost and evidence of three execution modes for the same job: local Python reference, direct MailCPU execution, and reliable remote MailCPU execution through the persistent worker. Measure request bytes, result bytes, instruction count, scheduler transitions, wall time, retries and replay count. Only then add durable worker checkpoints or concurrent-job scheduling, and require restored workers and isolated jobs to preserve the same state relation.


## Persistent receiver worker

`TransitComputeWorker` binds a long-lived service object to one receiver `HeadlessOS` and one local authority PID. For every request it recomputes grants from that receiver's current capability state, routes the event through the existing hypervisor arbitration loop, and commits the result through the reliable response channel before the request is acknowledged. The intended deployment pattern is a dedicated service PID with only `execute` on `/cpu/compute`; the integration tests and benchmark now use that least-privilege capability rather than the init process.

The worker is persistent; each computation is not. `TransitComputeHost` still creates a fresh isolated `HeadlessOS` for every admitted job. This separates service lifetime from job state and prevents one arithmetic program from inheriting another program's VM state.

The worker currently serves one request per `serve_once` call. The caller owns the transport lifecycle and decides when to call it again.

The worker exposes `snapshot(request, response)` and `TransitComputeWorker.from_snapshot(...)`. A worker checkpoint combines the HeadlessOS continuation state (including the hypervisor execution/replay ledger), authority PID, compute admission bounds, request ReliableChannel state, and response-channel replay ledger. Restore requires caller-supplied request and response transports, which must themselves be recovered or reconnected by the caller. The checkpoint state is canonical-JSON encoded and protected by a SHA-256 integrity digest; restore rejects altered or noncanonical state. This detects corruption or accidental edits, but is not a signature and does not authenticate the checkpoint's source.

Checkpoint creation is restricted to a quiescent boundary: no pending request transport data and no unacknowledged response frame. This avoids silently dropping queued messages at the checkpoint boundary. It is a coordinated state snapshot, not an atomic transaction across VM execution, network delivery, and external side effects. A crash between effect execution and publication of a new checkpoint can still lose the latest in-memory ledger. The current compute capsule is pure arithmetic, so it has no external effect to duplicate; do not use this checkpoint API as an exactly-once guarantee for future side-effecting handlers.

A restart integration test now pairs the worker checkpoint with two `DurableMailboxTransport` logs. It completes and acknowledges one job, persists the worker checkpoint, discards the live worker/channel objects, reopens the hash-chained mailbox logs, reconstructs the worker and reliable channels, and sends a new transport frame carrying the original semantic operation identity. The restored hypervisor effect ledger returns the original effect without entering the compute host again. This is disk-backed object-reconstruction evidence in one test process, not a process-kill/power-loss test or a multi-host test.

The checkpoint is not yet a daemon, concurrent worker pool, fully durable cross-process network service, or authenticated public endpoint.

The integration test sends two distinct requests through the same worker instance and checks both result paths and reliable acknowledgements.
