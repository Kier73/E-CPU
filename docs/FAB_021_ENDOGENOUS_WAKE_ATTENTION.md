# FAB-021 — Endogenous wake attention

## Contract

An admitted wake event names a namespace, 24-bit machine identity, exact predecessor revision and checkpoint digest, admitted transition contract digest, bounded input bytes and resource demand. Its operation identity is SHA-256 of the canonical versioned event. The receiver-controlled resolver binds an event to the exact native session and configured transition adapter. This is not a remote authentication or capability admission mechanism; publish must be called only by a trusted receiver after applicable admission. The resource demand is advisory.

The native ReplicatedMailboxStore.send_once uses an operation-derived immutable message identity and the existing _commit journal fingerprint: exact retry (including after consumption) does not enqueue again, changed content under the same identity is refused. It does not alter the ordinary send behavior or claim peer quorum acknowledgement. The local store and controller assume one owner/writer; native journal replay is unchanged.

The controller examines only the pending wake mailbox. For each represented machine it selects its first FIFO event, observes the native FAB-020 quorum head without state pages, and admits an offer only for the exact predecessor or an immediate retry of that same committed operation. It uses the merged FAB-014 allocator. Before materialization, it reobserves the selected head, checks the grant revision/evidence and exact event contract, then uses the original M3 transition adapter. The adapter verifies input and backend identity, materializes state, qualifies the candidate and publishes the native successor via its existing CAS. A deterministic, side-effect-free follow-up function may derive a child intention from that successor; the child must name the same machine, contract and exact successor checkpoint. The child is durably published before the parent is consumed. No pending wake means no controller observation of that machine.

The recovery order is:

1. Enqueue exact parent event.
2. Observe and select.
3. Native successor commit (or exact immediate retry).
4. Publish deterministic child, if any.
5. Consume parent.

A loss before step 3 leaves pending work; a loss after 3 but before 5 leaves the original event for immediate M3 replay. A duplicate child publication is a native mailbox no-op. The native adapter does not reenter its execution backend on an exact immediate retry. This is a recoverable local protocol, not a distributed atomic transaction spanning mailbox and M3. A single owner must prevent unrelated writers advancing the same session between commit and acknowledgement; an externally advanced head is reported stale and left pending. A stale first event can block later events for that machine until explicitly reconciled. The current implementation scans the pending mailbox each epoch, not the full machine space; it does not yet maintain a persistent incremental heap or enforce a bounded mailbox scan. Epoch capacity bounds selected offers, not all metadata overhead. Service history is caller-owned.

## Local results

Exact locally tested wake_attention.py blob 2b605df5bd041a5e83cc8e77cae08def9621adbb, with merged FAB-014 attention.py blob 258a6a9ab7b141e16ed03646b82b3aeb0c3da2. Three controller tests passed: canonical wire/refusal, interrupted parent acknowledgement after child publication with SQLite mailbox reopen and exact fixture retry, stale/scope refusal. The mailbox and session/adapter are explicitly test doubles; actual native mailbox and quorum integration remain hosted tests.

The local experiment initialized 256 fixture machine identities spread across the 24-bit space, including ffffff. Each had one initial wake, followed by three successor-generated wake events. Grants were limited to 32 per epoch. All 1024 fixture transitions completed in 32 epochs; every final fixture state equaled 4. The resolver was invoked 7296 times for pending machines, zero times for dormant addresses. The run measured 0.239305175 s initial publication and 4.668620258 s for epochs, including a deliberately simple service-accounting loop and SQLite FULL-synchronous test-double publication/acknowledgement. The fixture mailbox database retained 946176 bytes including consumed events. These are single-run local controller measurements, not native M1/M3 or independent-host performance. A separate interrupted-ack trial proves fixture replay without a second execution. Native source checkout remains blocked by DNS locally.

## Hosted native application trial

Tests use the actual ReplicatedMailboxStore journal and stable enqueue, including abrupt producer exit and reopening after consumption; native M3 and its actual HeadlessOS closed-state transition verifier; four active plus four dormant native applications, including addresses 000000 and ffffff. Each active application performs three two-tick scheduler grants; the exact verified runnable successor generates the next message. Candidate execution uses disposable interpreter subprocesses, and the native backend independently verifies the result. An injected acknowledgement interruption after child publication exercises reopen of actual mailbox and lineage journals and exact native replay. The fixture retains native M1 pages in memory across these reopen operations. Tests assert 12 successor commits, 12 candidate calls, one replay, no dormant state-page reads, exact final register values and exit state. Old differing intentions must stay pending without candidate execution. These are configured assertions, not observed native results.

Stacked on FAB-020 for native observe_head. It is independent of the snapshot and page representation experiments. To Do: durable pending-set projection and reconciliation, explicit ingress authority and delivery receipts over authenticated communication, independently replicated mailbox and M1/M3 recovery, cross-machine successor intents with explicit target admission, and native readiness observations for blocked/woken processes and DAG dependencies.
