# Federated forwarding process recovery

## Scope

This specification records two complementary A→B→C process-failure experiments built on the per-peer checkpoint in `COMPUTATIONAL_FABRIC_FORWARDING_RECOVERY.md`.

The first experiment hard-kills relay B at its own forwarding transaction cuts. B owns its local HeadlessOS/Hypervisor ledger, its inbound and outbound reliable channels, its B→C client ledgers, and its peer-scoped recovery journal. A retains the original sender state. C is independently checkpointed and rebound by the test supervisor. Anchor C and anchor D are independent authority processes for B's lineage.

The second experiment reverses the failure boundary: B remains alive while terminal C is hard-killed at its own terminal execution/publication/ACK cuts. C owns its terminal HeadlessOS, Hypervisor ledger, local host catalogue and runtime, inbound/outbound channel state, and a separate peer-scoped recovery lineage. Anchor E and anchor F are separate authority processes for C. B reconnects to the replacement C over fresh mutual TLS without discarding the downstream reliable-channel image.

These are independent peer recovery generations, not a globally atomic cluster checkpoint. Each peer has its own fixed-membership quorum and owner journal.

## Process topology and state ownership

| Participant | Process boundary | State ownership |
|---|---|---|
| A | Test/supervisor process | Origin operation identity, reliable request sender, result receive cursor and semantic result history |
| B | Child Python interpreter | Relay-local HeadlessOS/Hypervisor ledger; A↔B inbound/outbound channels; B→C request/result channels |
| C | Child Python interpreter in the terminal-crash experiment; supervisor-owned service in the relay-crash experiment | Terminal HeadlessOS/Hypervisor ledger, C's inbound/outbound channels, and locally reconstructed host catalogue/runtime |
| Anchor C and Anchor D | Independent child interpreters | B's peer-scoped RecoveryLineageParticipant journals |
| Anchor E and Anchor F | Independent child interpreters | C's distinct peer-scoped RecoveryLineageParticipant journals |

In the relay-crash test, B is terminated and relaunched while C is independently stopped, checkpointed, and rebound. In the terminal-crash test, C is terminated and relaunched while B's process remains alive. The two anchor pairs never share one high-water lineage: their membership identities, owner journals, and checkpoint roots are peer-specific.

The test fixtures create the directory snapshots used by A, B, and C. The actual A↔B and B↔C forwarding streams are established with mutual TLS and verify the exact neighboring peer certificate DNS identity. Recovery-lineage authority streams use peer-identified loopback `SocketTransport`; they are not represented as TLS links. Directory fixture injection is not evidence of production directory discovery.

## Relay B crash cuts

The first test exercises B's four forwarding transaction cuts:

| Cut | B's state at death | Expected recovery |
|---|---|---|
| `before_execution` | Request is still unacknowledged; no B effect is committed; no B result is published | A retransmits the same request; B performs the first forwarding transition |
| `after_execution_commit` | B's Hypervisor effect and downstream receipt are committed; inbound request is unacknowledged; result is unpublished | A retransmits; B replays its stored receipt without invoking B's downstream handler again |
| `after_response_publish` | B effect is committed; B result frame is pending; input is unacknowledged | B restores and retransmits its stored result; A's semantic result ledger suppresses the duplicate |
| `after_request_ack` | B input is consumed/ACKed; result frame remains pending | B restores and retransmits the saved result; no second input execution is required |

For this experiment B and both remote recovery anchors are real child processes. C's terminal service is restored from its own retained image by the supervisor. The workload is the pure deterministic `core.sum_pair` operation.

## Terminal C crash cuts

The second test starts A, B, C, and four lineage anchors as independent processes (A is the supervisor-owned client process). C seals its own image at the named terminal cut, writes a durable marker only after quorum commitment, and then blocks until the supervisor hard-kills it. B remains alive throughout.

| Cut | C's state at death | Expected recovery |
|---|---|---|
| `before_execution` | C has authorized/validated the request, but no terminal Hypervisor execution effect is committed; inbound frame remains unacknowledged | B rebinds the downstream transport and retransmits its still-pending reliable request; restored C performs the first terminal execution |
| `after_execution_commit` | C's terminal effect/replay record is committed; inbound request remains unacknowledged; response is unpublished | B retransmits the same request; C's restored Hypervisor returns the stored terminal receipt without entering the replacement operator |
| `after_response_publish` | C's terminal effect is committed; response frame is pending; inbound request remains unacknowledged | C restores the pending result and replay ledger; B accepts one semantically valid receipt and acknowledges duplicate transport deliveries |
| `after_request_ack` | C's inbound cursor has advanced and its request ACK has been emitted; terminal effect is committed; result frame remains pending | C restores and republishes the saved result. If B has already consumed the request ACK, B may allocate a new transport frame for the same semantic event; C's Hypervisor identity/fingerprint ledger returns the original effect |

The last case distinguishes transport identity from operation identity. A reliable request can be acknowledged at the transport layer while its semantic result is still pending. Re-sending that same semantic event after the request ACK may use a later transport sequence, but it must preserve the original Hypervisor identity and fingerprint. C's execution ledger is the authoritative semantic replay boundary.

B's new `rebind_next_hop_transport(peer_id, transport)` method holds the relay transition lock, verifies that the target is an already configured next hop and still matches the active receiver-local endpoint, rebuilds the client's request/result channels from the existing snapshot over the new stream, swaps the client, and closes the old stream. It does not discard the channel pending frame, receive cursor, or semantic-result history.

The downstream forwarding client uses `send_or_retransmit(event)`: if the exact semantic event is still represented by a pending reliable frame, it retransmits that exact transport frame and sequence; if the old transport request was already acknowledged, it allocates a new transport sequence for the same semantic operation. A conflicting payload under the same semantic identity is refused. Old semantic result duplicates are consumed and acknowledged while a newer operation is waiting.

## Recovery sequence exercised

For the terminal-C experiment, each cut follows this sequence:

1. Start independent anchor processes C/D for B's peer-scoped lineage and E/F for C's distinct lineage.
2. Start C in its prepare mode. It builds a receiver-local HeadlessOS, creates the network execute authority and separate Virtual Layer compute authority, and registers a local terminal catalogue.
3. Start B as a live relay child process. It connects to C over mutual TLS, accepts A over mutual TLS, and serves the A→B→C route.
4. A sends the original semantic operation identity. C reaches the selected fault hook, durably writes its exact per-peer checkpoint, quorum-seals the manifest, and writes the cut marker.
5. The supervisor hard-kills C only. The B process and B's in-memory state remain alive. The test checks that C's operator call log reflects zero or one entry as required by the selected cut.
6. Start a new C interpreter. It reloads C's checkpoint and C's owner/anchor journals, reconstructs the trusted local catalogue against the restored HeadlessOS, and listens at the same logical endpoint.
7. The supervisor asks B's loopback control endpoint to open a fresh B→C mutual-TLS connection and rebind its existing downstream channel snapshots to that stream.
8. The original operation settles at A. A then sends a second, distinct operation through the same still-running B and restored C.
9. The test checks B's PID did not change, C's PID did change, B and C channel windows drain, both journals verify, the terminal operator is entered once per distinct operation, and both operations return the expected receipt value.

The relay-B experiment separately launches B and its two anchors as child processes, kills B at all four relay cuts, starts a new B PID, reconnects both adjacencies over fresh mutual TLS, restores A's exact sender image, and verifies receipt/replay behavior.

## What these experiments establish

When the corresponding matrix passes, the experiments establish:

- B can recover from a true process kill using its peer-scoped quorum-anchored image and independent anchors.
- C can recover from a true process kill while B remains alive and preserves its process-local relay state.
- B can replace a failed downstream transport without losing its downstream channel identities or semantic replay ledger.
- Exact pending request frames are retransmitted when still pending; if transport ACK has already occurred, a new frame may carry the same semantic operation identity.
- C's restored Hypervisor ledger prevents a second terminal operator invocation for an already committed pure operation.
- A restored peer accepts fresh TLS streams rather than reviving sockets or TLS sessions from the prior process.
- A second distinct operation can complete through the recovered B→C path, demonstrating that recovery is not limited to replaying the first operation.

## Boundaries and next tests

A and the recovery anchors remain outside the C process kill boundary; the terminal-C experiment does not prove independent requester-process recovery. The relay-B and terminal-C experiments are separate runs; they do not yet prove two successive kills of B and C in one continuous operation history. The directory observations are fixture-supplied, not discovered through a production peer-directory service. Authority transport in these tests is loopback `SocketTransport`, while the forwarding adjacencies are mutual TLS.

The workload is deterministic pure computation. These tests do not establish exactly-once behavior for arbitrary external side effects. Such effects require durable idempotency or an effect journal at the actual side-effect owner. Nor do these tests prove a globally atomic multi-peer snapshot, hardware/storage power-loss durability, or malicious-host attestation.

The next escalation is a repeated multi-peer crash sequence: kill B, restore B, then kill C (and reverse the order), keeping the same A operation identity and peer-scoped quorum histories across both restarts. The next step after that is to replace fixture directory snapshots with restart-safe peer discovery/lease refresh over authenticated network exchanges.

## Tests

```sh
python -m pytest tests/test_federated_forwarding_process_recovery.py -q
python -m pytest tests/test_computational_fabric_forwarding_recovery.py -q
python scripts/verify_invariants.py
python scripts/verify_repo.py
```
