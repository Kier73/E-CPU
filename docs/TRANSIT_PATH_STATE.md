# Transit Path State Model

## Design intent

E-CPU treats a communication path as more than a byte pipe. A path is a bounded operational context: it receives a typed request, interprets that request under receiver-local authority, applies a declared transition algebra, commits a result, and retains enough causal state to acknowledge retries without applying the same semantic operation twice.

The first implementation is deliberately narrow. `TransitComputeSession` composes an existing `TransitComputeWorker`, inbound `HypervisorOperationChannel`, and outbound `HypervisorOperationResultChannel`. It does not add a second mutable job ledger. Its state is the product of the protocol cursors, receiver execution/replay ledger, and result-channel replay ledger already used to enforce the operation.

## Structural memory

For a receiver path, write its state as

\[
\Sigma_P = \Sigma_{in} \times \Sigma_{exec} \times \Sigma_{out}.
\]

- \(\Sigma_{in}\): inbound reliable-channel sequence cursor, peer binding, queued request, and acknowledgement state.
- \(\Sigma_{exec}\): receiver-local capabilities, hypervisor admission decision, and semantic execution/result ledger.
- \(\Sigma_{out}\): typed result queue, semantic duplicate ledger, and unacknowledged result sequences.

This is the structural memory invested in causality. The path remembers which frame arrived, which semantic operation it denotes, whether the receiver authorized it, which effect was committed, and whether the result has been acknowledged. Delivery identity and semantic identity remain distinct: a retry can arrive in a new transport frame while denoting an operation whose effect is already committed.

The path does not need an additional phase variable that can drift out of agreement with the channels. `TransitComputeSession.phase` derives a diagnostic phase from live state:

| Phase | Meaning |
|---|---|
| `idle` | No inbound request is ready and no response remains unacknowledged |
| `request-ready` | An inbound operation frame is available for the worker |
| `response-unacknowledged` | A committed response remains in the sender's reliable window |

The phase is an observation, not an authorization decision. The worker and hypervisor remain authoritative.

## Causal operation relation

A request follows the constrained relation

\[
q_{wire}
\rightarrow q_{decoded}
\rightarrow q_{authorized}
\rightarrow e_{committed}
\rightarrow r_{published}
\rightarrow ack.
\]

The receiver reconstructs the operation's grants from local process capabilities. It does not trust a sender-provided grant set. The arbitration loop binds the semantic identity to the effect ledger. The typed result is sent on the reverse reliable channel before the request is acknowledged. A retry under a new transport sequence can therefore retrieve the committed result without rerunning the computation.

This is not a claim of general exactly-once execution across arbitrary crashes or external side effects. The current arithmetic capsule is pure and bounded. The existing worker checkpoint requires a quiescent boundary; it is a coordinated continuation snapshot, not an atomic transaction across a process crash, a network, and an external system.

## Meaning of "computation in the path"

The intended direction is to move interpretation and execution selection into the receiver path:

1. A sender emits a portable operation description rather than a hardware-specific command stream.
2. The path validates its shape, resource budget, identity, and required authority.
3. A receiver-side execution adapter translates it into a representation supported by a local backend.
4. The backend executes the admitted transition.
5. The path commits a typed result and causal receipt, then acknowledges delivery.

The current path can host bounded reference backends for scalar MailCPU arithmetic, a lane-oriented SIMT interpreter, private process-memory transfer, and structural-memory coordinate reads. A typed router selects the backend by the exact operation/resource pair after the receiver has reconstructed local authority. These are semantic reference implementations, not GPU hardware or proof of a speed advantage over local execution.

## Structural-memory reads inside the path (E0.4 branch)

The E0.4 branch adds a receiver-side resource for addressing an admitted structural-memory revision. The request carries exactly four semantic fields:

- `memory_id`: the stable structural-memory identity;
- `revision`: the explicit admitted immutable revision;
- `context`: the exact context object bound to that revision;
- `coordinate`: the non-negative integer state coordinate to resolve.

The operation is routed under the exact pair `(read admitted structural-memory revision coordinate, /structural-memory/read)`. The receiver worker replaces peer-supplied grants with capabilities held by its own authority process. The classifier recognizes this as a read/data-resource request and selects the existing `FILESYSTEM` policy domain. The worker exposes that domain to its router only when the exact structural-memory operation/resource pair is in the restored backend manifest. The router still dispatches by the exact pair, and the backend independently rechecks the receiver-local `read` capability before calling `os.structural_memory.read_revision(memory_id, revision, coordinate, context=...)`.

The backend does not carry a generator, law, or Python callable over the wire. It resolves only a revision already admitted into the receiver's checkpointed structural-memory registry. The returned effect is the complete `StructuralMemoryReadReceipt` projection: value, memory/revision identity, coordinate, spec and certificate digests, context and value digests, witness digest, verification class, receipt identity, and cache indication.

This gives the path a compact state-family address rather than a materialized value stream. The path resolves the coordinate at the receiving boundary and returns the receipt through the existing result channel. The registry retains responsibility for generator whitelist enforcement, prefix horizons, context matching, caching, and journal receipts.

### Authority, replay, and recovery

The resource `/structural-memory/read` requires receiver-local `read` authority. A peer-supplied `granted_rights` field is not trusted: the worker reconstructs it from the local authority process, and the structural-memory backend checks the actual capability again before calling the registry. Context mismatch, unknown memory/revision, malformed coordinates, and missing read authority refuse before a result is returned.

The semantic operation identity remains the hypervisor event identity `(source, channel, sequence)`; the reliable transport frame sequence remains a separate delivery identity. A retry under a new transport frame but with the same semantic event is answered from the hypervisor execution ledger. The structural-memory generator is not invoked again, and the previously committed read receipt is returned unchanged.

The receiver worker checkpoint already composes the HeadlessOS snapshot, which contains the structural-memory registry and journal, with the hypervisor decision/execution ledger and reliable-channel state. Restore rebinds the exact backend manifest through a trusted `compute_host_factory`. As with the other transit backends, executable handler objects are not serialized. A restored structural-memory host binds to the restored HeadlessOS instance and the receiver authority PID, then serves the same logical request path over replacement transports.

### Exact boundary and limits

A read is always revision-pinned. It does not silently follow a later active revision; the sender must supply the intended revision. Context is exact, not inferred or transformed. The receiver must already possess the admitted revision locally, and its evidence remains finite witness or prefix evidence as defined by Structural Memory. This operation is read-only: it does not propose, admit, mutate, or replicate a structural-memory revision.

The integration demonstrates receiver-side access to a local generative state family through a communication path. It does not yet transfer structural memories between hosts, replicate registry state, prove the external origin of witness observations, learn context-to-generator transformations, provide a distributed consensus layer, or demonstrate a performance advantage over local reads.

## CPU, SIMT, and memory movement

The portable request algebra should eventually describe *what must be computed*, not prescribe one chip's instruction schedule. A later backend could map a request to scalar CPU operations, vector operations, SIMT groups, or data-movement operations. The path would select among those backends using declared capabilities, resource budgets, data shape, and locality.

A GPU backend is not obtained by simply putting a GPU's instruction set into a network message. It needs a defined kernel/query contract, workgroup and lane semantics, divergence rules, synchronization/barrier semantics, memory address spaces and visibility, buffer ownership, transfer rules, and a resource model. The receiver may host a physical GPU, an emulator, or a simulator; the path protocol should not assume which one is present.

Memory movement must also be represented as an explicit operation with source/destination ownership, bounds, ordering, and completion receipts. For large workloads, data placement and transfer can dominate execution time. Batching, locality, reuse, and asynchronous overlap may matter more than the cost of interpreting one additional operation.

The target is therefore not "computation without clocks." Hardware still has clock, latency, bandwidth, energy, and capacity limits. The architectural shift is that the path's semantics and causal state decide which work is meaningful and where it should be interpreted, while the receiver's backend performs the physical work.

## Next tests

The next useful steps are:

1. Run the session lifecycle on a separate receiver process and a separately deployed host, not only two endpoints in one test process.
2. Exercise checkpoint/restore after a real process restart and reconnect, retaining the same semantic identity and proving that a committed result is replayed.
3. Add a physical GPU or faithful GPU emulator adapter behind the SIMT contract, then compare results, masks, barrier behavior, memory visibility, and transfer cost against the reference interpreter.
4. Extend memory transfer from private resident pages to shared regions only after explicit sharing, synchronization, ordering, and lifetime rules are defined. Measure transfer locality, batching, and overlap.
5. Add path scheduling only after fairness, backpressure, quotas, cancellation, and failure recovery are part of the state relation.

No GPU support or cross-host deployment is claimed by the current session abstraction.


## Process restart and durable checkpoint files

TransitComputeSession.save_checkpoint(path) is the file-backed persistence boundary for a quiescent path. It first asks the worker to produce its existing checkpoint, so the same queue/acknowledgement preconditions apply. It then writes canonical JSON to a temporary file in the target directory, flushes and fsyncs the file, atomically replaces the prior checkpoint, and attempts to fsync the containing directory. On platforms that support file mode changes, the temporary checkpoint is restricted to owner read/write permissions.

TransitComputeSession.from_checkpoint(path, request_transport, response_transport) reads the checkpoint, then delegates to the same schema, digest, receiver-state, and reliable-channel validation as from_snapshot. The caller must establish and authenticate replacement transports first. The checkpoint does not serialize a live TCP/TLS socket; it restores the logical protocol cursors and semantic ledgers onto a new stream. In the current full-duplex configuration, the same replacement SocketTransport is supplied for both request and response channels. Checkpoint v2 also records the sorted backend manifest of operation/resource pairs. Handler callables are executable configuration and are not serialized; from_checkpoint accepts a compute_host_factory that rebuilds the backend router against the restored HeadlessOS and authority PID. Restore refuses the checkpoint if the rebuilt manifest differs. Scalar-only v1 checkpoints remain readable.

The process integration test starts a receiver in a spawned OS process, establishes mutual TLS, executes a bounded request, receives and acknowledges the result, and writes the worker checkpoint to disk. It then exits that process, starts a second OS process, loads the checkpoint from disk, and accepts a new mutually authenticated connection. The client also restores its reliable-channel cursors onto the new stream. It resends the same semantic operation in a new reliable transport frame; the restored receiver returns the original effect as a replay rather than starting another computation. The test now starts with a three-backend router and verifies that the scalar, SIMT, and memory-transfer operation/resource manifest is reattached identically in the second process.

This is stronger than reconstructing objects in one process: the receiver's Python address space is destroyed between execution and restore. The endpoints still run on one test machine over loopback. It is not yet a separate-physical-host deployment, hard-kill/power-loss test, or a general transactional exactly-once guarantee.

### Important crash boundary

The checkpoint is taken only after the response has been acknowledged. Therefore a process failure after an effect is committed but before the updated checkpoint reaches durable storage can restore an older execution ledger. A retry could then repeat an operation if the effect had external side effects. The arithmetic capsule is pure, so this test does not create an external duplicate effect.

To close that window for side-effecting backends, E-CPU will need a durable commit protocol that atomically records the semantic operation identity and its effect/replay result before acknowledging the request, or a transactional outbox/inbox whose recovery semantics cover both the effect and the message. The current checkpoint API is a durable quiescent continuation, not that transaction.


## SIMT reference backend

The first SIMT backend is a bounded semantic reference interpreter, not a GPU driver or emulator. It lets the path accept a portable lane-oriented query and interpret it at the receiver without binding the query to a particular GPU instruction set.

A request carries four finite fields:

- lane count;
- named integer input arrays, each with exactly one element per lane;
- a finite instruction sequence;
- a maximum instruction-step budget.

The current instruction algebra is:

| Instruction | Meaning |
|---|---|
| CONST | Set an integer register on active lanes |
| LANE_ID | Write each active lane's index |
| LOAD | Load one lane's element from a named input array |
| COPY | Copy one lane-local register |
| ADD, SUB, MUL | Apply integer arithmetic lane-wise |
| LT | Produce a per-lane Boolean predicate |
| IF, ELSE, ENDIF | Execute structured branches under active-lane masks |
| BARRIER | Record a workgroup barrier after full reconvergence |
| STORE | Write one output array element per active lane |
| HALT | End the finite kernel |

The SIMT interpreter runs one program counter for the whole workgroup. An IF creates a mask by intersecting the parent mask with a lane predicate. The then-path and else-path execute under complementary masks; ENDIF restores the parent mask. This is a deterministic lockstep reference model of branch divergence and reconvergence, not an attempt to model every vendor GPU's scheduling details.

A barrier is currently admitted only outside a structured branch region, after explicit reconvergence, with every lane active. A barrier inside a divergent region is rejected before execution. This conservative rule avoids silently treating a partially active workgroup as synchronized. The barrier receipt records its epoch, program counter, and lane-arrival count.

The differential test evaluates absolute value for input lanes [-4, -1, 0, 3, 8]. The SIMT kernel's output is compared with five independent scalar MailCPU executions of the same mathematical operation. The test also checks lane IDs, addition, multiplication, both branch masks, reconvergence, and a five-lane barrier arrival.

The same reference kernel is also sent through a persistent TransitComputeSession. A TransitBackendRouter selects the SIMT handler by its exact operation/resource key. The receiver derives the execute capability for resource /gpu/simt, dispatches the request in the CPU-owned execution domain, returns a typed result, and processes the reliable acknowledgements.

The SIMT reference backend is registered in the persistent worker's operation router by its exact operation/resource identity. The session test exercises that exact dispatch path. It provides a semantic oracle for a future hardware or emulator adapter. Performance claims, GPU memory semantics, asynchronous workgroup scheduling, and vendor-specific occupancy behavior remain outside this implementation.


## Heterogeneous backend routing

A persistent transit worker can now hold a TransitBackendRouter in place of the scalar TransitComputeHost. The router maintains a partial function R from the pair (operation, resource) to a handler.

It begins with the scalar MailCPU arithmetic host and can register the SIMT and memory-transfer handlers. Duplicate keys are refused. A request with no exact registered key is refused rather than falling through to an unrelated backend. Receiver-local capability reconstruction and the hypervisor execution ledger still happen before handler invocation; the router is not an authorization layer.

The current registrations are:

| Query algebra | Operation | Resource |
|---|---|---|
| Scalar arithmetic | execute deterministic CPU arithmetic program | /cpu/compute |
| SIMT reference | execute deterministic CPU SIMT reference program | /gpu/simt |
| Private memory transfer | execute CPU instruction memory transfer | /memory/transfer |

All three currently enter the CPU-owned hypervisor execution domain and are dispatched by the exact router key. This is a provisional domain arrangement; a future domain taxonomy may separate memory and GPU execution from CPU execution without changing the operation channel contract.

The router is executable configuration, not serialized code. Checkpoint v2 records its sorted key manifest. A restore factory receives the restored OS and authority PID and must reconstruct the same manifest. This prevents a process from silently resuming with missing operation handlers. It does not prove that handler implementations are byte-for-byte identical; deployments must pin and verify their executable versions separately.

## Private process-memory transfer

The first memory operation copies a finite byte interval between two receiver-owned private virtual-memory images. Its request names the source PID/address, destination PID/address, and byte length. The transfer service requires the receiver's local authority process to hold read permission on /memory/{source_pid}, write permission on /memory/{destination_pid}, and the outer execute permission on /memory/transfer. Peer-provided rights are not trusted.

The request also carries SHA-256 preimage digests for the exact source and destination byte intervals. The receiver checks both before mutation. A stale source or changed destination is refused. These preconditions make a retry from a checkpoint that predates the transfer deterministic: if the same source and destination preimages are restored, the same bytes and completion receipt are reproduced; if either endpoint has changed, the operation does not overwrite it. The host also rejects non-positive lengths, transfers larger than its configured byte limit, missing process memory images, nonresident pages, read-only destination pages, and shared-region mappings. Shared pages are deliberately refused: their synchronization and lifetime rules are not yet defined by this operation.

For an admitted transfer, the host reads the source interval, applies the bytes to a copy-on-write clone of the destination memory image, commits the candidate mapping state only after the full write succeeds, then verifies the destination bytes. It returns the copied byte count, a SHA-256 digest of the transferred bytes, and a journal completion receipt. The integration test copies an 80-byte interval across virtual-page boundaries, verifies the data and journal receipt, checks receiver-local read/write authority, tests stale source/destination digests, and restores the pre-operation receiver snapshot to demonstrate deterministic reapplication with the same completion receipt. It also proves reliable semantic retry does not invoke the transfer handler a second time.

This is an in-process memory-image commit, not a crash-atomic transaction spanning the memory update, event journal, hypervisor replay ledger, network result, and durable checkpoint. A process failure after the memory mapping changes but before the full causal record is durable can still leave an incomplete operation record. The current operation is tested in a single receiver process; hard-kill recovery and cross-host memory ownership are not claimed.


## Deterministic orbit scheduling

The path session above defines one persistent receiver-side path. The orbit
scheduler composes several independent sessions without copying their execution
ledgers:

\[
\mathcal{S}_{orbit}
=
\left(\prod_{p\in P}\Sigma_p\right)
\times (c,t,n,r),
\]

where \(\Sigma_p\) remains authoritative in its `TransitComputeSession`,
\(c\) is the next round-robin cursor, \(t\) is the scheduler logical tick,
\(n\) contains dispatch/idle counters, and \(r\) is the rolling receipt head.

At each scheduling quantum, the scheduler scans the canonical sorted path IDs
cyclically from \(c\) and selects the first session whose inbound request is
ready. It calls that session's `serve_once()` at most once, then advances the
cursor to the path after the selected path. If no path is ready, it records one
idle quantum and leaves the cursor unchanged. An idle quantum is an observation
of the current ready set; it is not a worker instruction or a wall-clock sleep.

This is deterministic interleaving, not global lockstep. A path with multiple
queued requests can make progress over successive turns, while other ready
paths receive intervening turns. Under the assumptions that the scheduler is
called repeatedly and a path remains dispatchable, cyclic selection prevents a
continuously dispatchable path from being skipped indefinitely. Before invoking
a worker, the scheduler also requires a free slot in that session's bounded
response channel. If a request is ready but the response window is full, the
scheduler records a `backpressured` receipt and does not consume the request
or invoke its handler. After the caller receives and acknowledges an earlier
result, a later quantum can resume that path.

This is a narrow admission guard, not a general queue-management policy. The
current version does not implement dynamic path admission/removal, cancellation,
queue capacity planning, deadline scheduling, or parallel execution. Existing
reliable-channel windows and receiver hypervisor checks remain in force.

### Logical path identity and physical transport

The orbit manifest binds each path ID to a digest of its logical request and
response channel identity. It deliberately excludes the concrete transport
object. A quiescent `TransitComputeSession` checkpoint separately commits to
the receiver, worker, backend manifest, and reliable-channel state.

To restore an orbit, first restore each session from its own checkpoint using
newly established transports; then restore the orbit checkpoint against those
sessions. The scheduler admits this rebinding only when path membership,
logical channel contracts, and session checkpoint digests match. This allows
a replacement stream to carry the same logical continuation without resetting
the orbit cursor. It is not route discovery or automatic rerouting: the caller
must establish and authenticate the replacement transport, and the replacement
must preserve the logical peer/channel identity.

The scheduler checkpoint is a manifest over session checkpoint digests, not a
container for the full session checkpoints. Each path checkpoint must be
persisted independently. As with `TransitComputeSession`, snapshotting requires
the worker's existing quiescent boundary: no pending inbound request data and
no unacknowledged response data. The orbit scheduler does not weaken that
precondition.

### Scheduling receipts

Each quantum extends a hash-linked receipt:

\[
r_t=H(r_{t-1},\;t,\;p_t,\;d_t,\;a_t,\;x_t,\;q_t),
\]

where \(p_t\) is the selected path (or null for an idle quantum), \(d_t\)
is the disposition, \(a_t\) is the hypervisor action, \(x_t\) records
whether execution occurred or was replayed, and \(q_t\) is a digest of the
session's diagnostic state after the quantum. The receipt links scheduler
ordering to the path state observed at that boundary. Each record can be
serialized to a finite dictionary and reconstructed only after its own
canonical payload digest verifies.

These receipts are scheduler evidence, not a replacement for the hypervisor
journal or semantic effect ledger. Their digest chain detects mutation of the
recorded sequence when the records are available; it does not authenticate a
peer, prove a handler correct, or reconstruct omitted session state. The
session checkpoint and hypervisor journal remain the sources of execution and
replay evidence.

### Initial conformance boundary

The first integration test interleaves two independently connected loopback
TCP sessions. Each receives two requests; the orbit dispatch order is
`path-a`, `path-b`, `path-a`, `path-b`. The tests also cover idle quanta,
receipt-chain verification, logical path membership validation, and restoring
the scheduler cursor after both sessions are restored onto replacement TCP
connections.

This establishes deterministic local orchestration across multiple transit
sessions. It does not establish separate-physical-host deployment, wide-area
fairness under failure, automatic network route selection, physical GPU
execution, or a performance advantage. Those require independent deployment
and measurement.
