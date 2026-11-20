# IPS-008 — A receiver-acknowledged barrier before generated-Ground rehome

## Purpose

IPS-005/006 preserved one majority-published pure computational result despite changing worker and recovery-authority process topology. IPS-007 made a receiver-owned SQLite effect resource reject an obsolete result *after the newer quorum root was installed at that receiver*. That still left a gap: **what if the coordinator publishes the new assignment while the effect receiver still permits its old root?**

IPS-008 establishes a stricter opt-in ordering for one resource:

    majority verifies current Ground head
       -> receiver mTLS: PREPARE(source root, next host)
       -> receiver SQLite: atomic durable freeze + ACK
       -> original E-CPU majority: assign/reassign to next host
       -> receiver mTLS: ACTIVATE(exact successor quorum root)
       -> receiver SQLite: verify successor, atomically install + unfreeze
       -> only newly published qualified stage may write

The receiver-side freeze is a local durable barrier. It is not a certificate that the quorum has already committed anything, and it does not grant execution permissions.

## Native components reused

- FencedGroundLineage (IPS-005): majority read-high-water, exact input/previous root, stage/host/epoch assignments, independent recheck of original IPS-004 native DAG and SAB-008 observation receipts.
- FencedGroundEffectReceiver (IPS-007): resource/plan-pinned SQLite database; register changes, deduplication and effect receipts share a single BEGIN IMMEDIATE write transaction.
- E-CPU mutual TLS: connect_mutual_tls / accept_mutual_tls, exact DNS SAN check for the expected owner identity, SocketTransport framing and typed Message envelopes. The service refuses plaintext fallback.
- Existing independent subprocess TLS test fixtures and locally fsynced E-CPU authority journals.

No new consensus, authenticated fabric directory, unbounded arbitrary program executor, signature format or alternative Hypervisor is introduced.

## Receiver-owned barrier

The original IPS-007 database now has an effect_handoffs table, one slot per protected resource. A barrier identifies exact source generation/root, expected successor epoch/host, and a canonical barrier digest.

The authorized owner uses a mutually authenticated service request to request PREPARE. The service first finds the exact current quorum-supported head through the original FencedGroundLineage. It compares the requested source root and rechecks all previously committed Ground evidence. Only then does the receiver, under BEGIN IMMEDIATE, require that source to equal its locally installed head and persist the freeze before ACK.

Every effect write uses the same SQLite writer lock and rejects writes while a barrier exists. A duplicate exact prepare is idempotent. A conflicting prepare for another future host is refused.

ACTIVATE looks up the *latest exact quorum-supported root*, then invokes the original IPS-007 install operation with require_handoff=True. A newer assign/reassign cannot install unless the already-fsynced barrier matches all of: previous generation/root, exact successor generation and predecessor, epoch, and new host identity. Installation and deletion of the barrier are in one SQLite transaction.

An owner that dies after receiving the barrier ACK but before sealing the quorum assignment leaves the receiver **frozen**. Recovery must reopen the same durable quorum and the original receiver DB, recommit the exact matching successor assignment, then activate it. It is intentionally not permitted to silently thaw an old result just because no new quorum record exists.

## Authenticated process experiment

One independently launched Python process hosts the receiver's original SQLite DB and a TCP TLS listener. A certificate-authorized E-CPU owner calls ACTIVATE on the initial published result, makes an effect, then calls PREPARE for a specific future host.

The process is hard-killed after ACK. A fresh Python process reopens the same independent DB and certificate identity. Before any new quorum assignment, the old effect remains forbidden. A separate new coordinator reopens the preserved quorum authority journals and seals the exact specified next-host assignment. The restarted receiver ACTIVATEs its exact proof; the old host still cannot change its register. After the new IPS-004 stage is verified and published, the receiver installs and accepts the correct new value.

Negative checks include wrong CA-trusted client subject, wrong pinned server DNS, request for a stale quorum root, a directly committed assignment without the receiver barrier, target-host mismatch, duplicate preparation idempotency, receiver restart and previous IPS-007 atomicity regressions. Native CI covers Linux and Windows on Python 3.11 and 3.13.

## Precise claims and outstanding contracts

1. **Safety within this protocol:** For a *participating effect resource*, after a durable PREPARE ACK, no old effect can commit. The receiver checks the freeze inside the exact same transaction as its effects, including after restart. Activation permits only the specifically acknowledged quorum successor.
2. **Ordering is an opt-in orchestration rule**, not enforced by E-CPU's general-purpose RecoveryLineageCoordinator. A different owner path can still seal a quorum assignment without first contacting the receiver. Such an unprepared assignment will be refused by this receiver, not retroactively prevented from being committed.
3. **Liveness tradeoff:** If the effect receiver is offline before ACK, a safe caller must not commit the new assignment under this protocol. If it dies after ACK, the durable barrier stays. If quorum chooses an incompatible host or becomes unavailable, recovery must reconcile the decision or remain frozen.
4. **Trust and failure model:** The tested receiver is a separate mTLS process on the same runner. The quorum journals are durable independent local files, not separate physical machines in this test. The owner certificate authorizes only the fixed protocol operations on the receiver; the underlying root still needs independent E-CPU quorum qualification.
5. **External side effects:** The tested operation is a receiver-owned SQLite register mutation. Effects performed directly in nonparticipating external services are not covered. Arbitrary downstream side effects, simultaneous cross-resource commits, Byzantine storage, physical host attestation, owner-term election and independent geographic deployment remain future work.
6. **Recovery proof:** Hash-chained checkpoint content is not alone evidence of freshness. The receiver must recheck the original majority-supported current root before any installation.

## Evidence and next steps

Reproduce with:

    python -m pytest -q tests/test_effect_receiver_service.py
    python -m pytest -q tests/test_effect_receiver_service.py tests/test_fenced_effect_receiver.py tests/test_fenced_generated_ground.py tests/test_recovery_lineage.py

A stronger distributed next experiment is to bind the barrier acknowledgement to a typed quorum assignment-intent record so the quorum rejects unbarriered assignments *by design*. Also extend to authenticated owner/journal services on separate hosts and introduce a portable independently checked receipt for VGI/IFS. Measure actual prepare/activate and effect write latencies, not presumed computation cost reductions.

For related resource-side fencing context: [Martin Kleppmann, How to do distributed locking](https://martin.kleppmann.com/2016/02/08/how-to-do-distributed-locking.html) and [SQLite isolation](https://www.sqlite.org/isolation.html).
