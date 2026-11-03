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

The current backend is a bounded MailCPU arithmetic interpreter. It is not a GPU, does not execute SIMT kernels, and does not make remote execution faster than a local CPU. It is a tested first example of a request being interpreted and executed by the receiving path.

## CPU, SIMT, and memory movement

The portable request algebra should eventually describe *what must be computed*, not prescribe one chip's instruction schedule. A later backend could map a request to scalar CPU operations, vector operations, SIMT groups, or data-movement operations. The path would select among those backends using declared capabilities, resource budgets, data shape, and locality.

A GPU backend is not obtained by simply putting a GPU's instruction set into a network message. It needs a defined kernel/query contract, workgroup and lane semantics, divergence rules, synchronization/barrier semantics, memory address spaces and visibility, buffer ownership, transfer rules, and a resource model. The receiver may host a physical GPU, an emulator, or a simulator; the path protocol should not assume which one is present.

Memory movement must also be represented as an explicit operation with source/destination ownership, bounds, ordering, and completion receipts. For large workloads, data placement and transfer can dominate execution time. Batching, locality, reuse, and asynchronous overlap may matter more than the cost of interpreting one additional operation.

The target is therefore not "computation without clocks." Hardware still has clock, latency, bandwidth, energy, and capacity limits. The architectural shift is that the path's semantics and causal state decide which work is meaningful and where it should be interpreted, while the receiver's backend performs the physical work.

## Next tests

The next useful steps are:

1. Run the session lifecycle on a separate receiver process and a separately deployed host, not only two endpoints in one test process.
2. Exercise checkpoint/restore after a real process restart and reconnect, retaining the same semantic identity and proving that a committed result is replayed.
3. Add a small vector/SIMT reference backend with explicit lane, mask, and barrier semantics, then compare its results against scalar MailCPU for the same portable request.
4. Introduce memory-transfer operations only after the ownership, ordering, bounds, and completion invariants are tested.
5. Add path scheduling only after fairness, backpressure, quotas, cancellation, and failure recovery are part of the state relation.

No GPU support or cross-host deployment is claimed by the current session abstraction.
