# Workgroup Shared Memory

## Purpose

This document defines the first shared-memory contract inside the E-GPU reference workgroup. It makes memory ownership, address bounds, write conflicts, visibility, and synchronization explicit. The implementation is a deterministic reference model, not a claim of vendor GPU memory-model equivalence.

## Ownership and lifetime

A workgroup invocation is one bounded SIMT program execution over a fixed lane set. The invocation creates its own shared-memory operational host from the request's shared_buffers declaration.

The declaration is a finite mapping from buffer names to positive element counts. The host rejects invalid names, non-positive sizes, excessive buffer count, and a total element count above its configured bound. Cells begin uninitialized.

Ownership is exclusive to the workgroup invocation:

- lanes within that invocation may address the declared buffers;
- another workgroup invocation receives a different shared-memory host and cannot read this invocation's cells;
- shared memory is discarded when the invocation completes;
- a session checkpoint preserves the committed operation result and execution ledger, not a live shared-memory allocation.

This is deliberately distinct from process memory, Structural Memory, or memory-transfer resources.

## Instruction contract

Two instructions address the shared-memory host:

| Instruction | Operands | Effect |
|---|---|---|
| SHARED_STORE | buffer name, index register, value register | Stage one lane's integer write for the current barrier epoch |
| SHARED_LOAD | destination register, buffer name, index register | Read a previously published integer cell |

The address register must resolve to an integer in the buffer's finite index interval. Values must fit the SIMT interpreter's configured integer bit bound. Reads from uninitialized cells fail.

## Visibility and barrier epochs

Shared writes are staged in a pending write set. A staged write is not visible to SHARED_LOAD. Loading from a buffer with uncommitted writes fails and requires a barrier first.

A BARRIER is admitted only outside a structured divergence region and at runtime only when every lane is active. Once all lanes arrive, the shared-memory host atomically publishes all pending cells as one visibility epoch. The receipt records the epoch number, program counter, lane-arrival count, and published buffer addresses.

Each address has a single-writer rule within one epoch. A second write to the same address before the next barrier fails rather than silently selecting a lane-order winner. A later epoch may write the same address again.

A HALT with pending writes is refused. The program must publish them with a barrier before termination.

The current memory order is intentionally conservative:

1. lanes stage writes;
2. all lanes reconverge;
3. all lanes arrive at a barrier;
4. pending cells become visible together;
5. lanes may read the published cells.

There are no atomics, relaxed ordering modes, races with an implementation-defined winner, or implicit barriers.

## Example: lane-zero broadcast

Four lanes receive values [73, 11, 29, 47]. Lane zero writes 73 to scratch[0]; the other lanes do not write. After explicit reconvergence and one barrier, all four lanes load scratch[0] and produce [73, 73, 73, 73].

The route is:

\[
H_{\mathrm{dispatch}}
\rightarrow H_{\mathrm{workgroup}}
\rightarrow H_{\mathrm{shared}}
\rightarrow H_{\mathrm{verify}}
\]

The operation result includes the visible shared-memory state, visibility epoch receipt, barrier trace, and canonical state digest.

## Failure behavior

The reference host refuses:
- undeclared or out-of-range buffer addresses;
- zero, negative, Boolean, or non-integer buffer sizes;
- total shared capacity beyond the configured ceiling;
- uninitialized reads;
- reads before pending writes have been published;
- two lanes writing the same address during one epoch;
- barriers inside divergent control flow or with a partial active mask;
- HALT while writes remain pending.

No partial output is accepted after one of these failures.

## Persistent Transit boundary

The E-GPU workgroup method is dispatched as the exact outer operation/resource pair /gpu/egpu. The receiver's hypervisor reconstructs execute authority from its local kernel capability. Internal dispatch, workgroup, and shared-memory loci choose the operational path but do not confer operating-system authority.

The persistent-session integration test commits one shared-workgroup result, receives and acknowledges it, saves a quiescent checkpoint, restores the receiver and backend manifest over replacement TCP transports, then resends the same semantic identity in a new reliable transport frame. The receiver replays the stored result without re-entering the E-GPU backend. This proves the checkpointed semantic replay path in the test process; hard process death and separate physical hosts remain untested for this new backend.

## Limits and next gates

This model covers one workgroup at a time. It does not define cross-workgroup shared storage, global/device memory, atomics, asynchronous streams, event fences, cache coherence, DMA, hardware occupancy, or vendor-specific visibility rules. The next memory transition should be typed, bounded transfer with explicit source/destination ownership and completion receipts. Cross-workgroup synchronization should be added only after a distinct authority and visibility contract is specified.
