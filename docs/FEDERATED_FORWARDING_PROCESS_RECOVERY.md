# Federated forwarding process recovery

## Scope

This experiment advances the per-peer forwarding image in COMPUTATIONAL_FABRIC_FORWARDING_RECOVERY.md from in-process rebind to a hard operating-system process kill of relay B.

The topology is A→B→C. A owns the original request sender state. B is an independent Python child process and owns the relay's local HeadlessOS/Hypervisor ledger, inbound request receive state, outbound response sender state, and B→C downstream client ledgers. C is a separate terminal service in the supervising test process; its local execution image is independently captured and re-created before B returns. Two more child processes, anchor C and anchor D, independently own durable recovery-lineage journals. B is the owner member for its own peer-scoped lineage.

This is deliberately not a single-process mock quorum. B's local journal is reopened by a new B process; the two other fixed-membership members remain alive as independent authority processes and are contacted over reliable recovery-lineage streams.

## Process topology and state ownership

| Participant | Process boundary | Durable/retained state |
|---|---|---|
| A | Test/supervisor process | Original forwarding-client request/result channel snapshots; original pending request frame and semantic result history |
| B | Child Python interpreter; killed and relaunched | Quorum-anchored forwarding checkpoint generation, B's local owner authority journal, exact Hypervisor effect/replay ledger and hop-local reliable channels |
| C | Terminal forwarding server in supervisor process | Independently captured HeadlessOS/Hypervisor state, incoming B channel state, terminal catalogue/runtime reconstructed against the restored OS |
| Anchor C | Independent child interpreter | Its own durable RecoveryLineageProcessParticipant journal, served across owner reconnects |
| Anchor D | Independent child interpreter | Its own durable RecoveryLineageProcessParticipant journal, served across owner reconnects |

B is quorum member/owner for a peer-scoped lineage. The two remote anchor processes are the other members. They remain alive when B is hard-killed and accept B's new owner-side recovery connections on restart. They do not host B's VM, Hypervisor, forwarding server, or route execution.

The test uses direct test-fixture directory observations to construct each peer's active receiver-local view. Each actual A↔B and B↔C forwarding stream is nevertheless established through mutual TLS and the forwarding constructors revalidate the exact neighboring certificate DNS identity and peer endpoint. Directory leases are re-created for the test view; no lease or TLS socket is restored from B's checkpoint.

## Crash-cut protocol

The forwarding operation handler exposes these exact cuts:

| Cut | B's state at death | Expected B behavior after restart | Expected C operator behavior |
|---|---|---|---|
| before_execution | Request remains unacknowledged; no B Hypervisor effect committed; no B response published | Receive the exact A retransmission, perform the operation and publish one result | Execute once after B restarts |
| after_execution_commit | B Hypervisor effect/replay record committed; incoming request unacknowledged; B response not published | Receive A's exact retransmission and replay B's stored receipt without invoking the forwarding handler again | Reuse C's already committed receipt; no second terminal call |
| after_response_publish | B effect committed; result frame 1 published and pending; request unacknowledged | Retransmit the saved response frame, accept the retried request, replay B's stored receipt, and publish another transport response for the same semantic result | Reuse C's already committed receipt; no second terminal call |
| after_request_ack | B effect committed; incoming request cursor advanced/ACKed; result frame remains pending | Retransmit the saved response frame; duplicate request transport delivery is suppressed by the restored receive cursor | No second terminal call |

For the published-before-ACK cut, A's requester result ledger receives both transport frames: the original stored result and the retransmitted semantic duplicate. It should expose the first as fresh and the second as duplicate, while both carry the same hop-receipt digest.

For the request-ACK cut, A's sender checkpoint is captured before it consumes B's later ACK. It deliberately retransmits the original sequence after reconnecting. B's restored receive cursor/delivered set suppresses the duplicate without re-entering the Hypervisor operation.

## Recovery sequence exercised

For each cut the test:

1. Starts independent anchor-C and anchor-D authority processes, each with its own durable journal, and starts B with its separate owner journal.
2. Starts terminal C, which accepts B over mutual TLS and owns its own local execution/replay state.
3. Connects A to B over mutual TLS, sends one exact semantic forwarding operation, and saves A's requester channel pair.
4. Lets B execute until the selected fault hook. At the hook, B calls ComputationalFabricForwardingRecoveryStore.seal(server, cut). That call holds B's service transition lock until the peer image is durably published and the fixed-membership quorum commits its manifest root.
5. Records the B PID, committed execution count, receive cursor, response queue, downstream semantic-result ledger, manifest digest, and journal integrity. The marker is written only after the checkpoint/quorum operation completes.
6. Stops C's service loop and captures C's own checkpoint. For post-execution cuts, it confirms C's response to B has already been ACKed, so the terminal state is a stable independently retained image.
7. Hard-kills only B. B performs no Python shutdown cleanup and does not publish another frame after the cut.
8. Restores C from its independently retained image over a new B↔C mutual-TLS connection.
9. Starts a new B child interpreter. It reopens B's owner journal, reconnects to both independent anchor processes, verifies the latest quorum-anchored generation, reconstructs the saved HeadlessOS/Hypervisor ledger, binds the exact downstream transport set, accepts A over a fresh mutual-TLS stream, and rebinds its reliable-channel snapshots.
10. Restores A's sender/result channels over a fresh A↔B stream and retransmits the original request frame.
11. Verifies B returns the same successful downstream receipt, that C's operator call count remains one, that B's input and output channels settle, and that B's event journal verifies.

## What the test establishes

When its test matrix passes, this experiment establishes for the tested pure deterministic operator:

- B is a genuinely terminated and newly started operating-system process; the PID changes.
- B's recovered state comes from its durable per-peer checkpoint and quorum-anchored owner/anchor journals, not from an in-memory server object retained by the supervisor.
- A retains and retransmits the original semantic operation identity from its independently saved sender channel.
- The new B process reconnects to the same independent recovery authorities and reuses its exact committed generation.
- Fresh mutual-TLS streams replace the dead A↔B and B↔C streams.
- A post-commit B replay does not re-enter B's downstream forwarding handler.
- C's separately restored Hypervisor ledger prevents a second terminal operator invocation.
- The four cuts have distinct and asserted receive cursor, pending response, replay, and operator-entry behavior.

The test intentionally kills B only. C is stopped and restored from its independent image by the supervisor, but C is not itself a child process in this first relay-specific test. The existing general Transit process-crash tests already exercise independent requester/receiver child interpreters; this experiment's new variable is B's nested forwarding call and downstream replay chain.

## Boundaries and next tests

This does not establish a globally atomic multi-peer checkpoint. A, B, C, and the recovery authorities own separate durable state and recover through the original operation identity. It does not establish arbitrary external side-effect exactly-once semantics; the test workload is pure deterministic computation. The directory observations are supplied by the test fixture rather than discovered from a production peer directory service. The lineage authority streams in this test use peer-identified loopback SocketTransport; the forwarding A↔B and B↔C streams are mutual TLS.

The next stronger experiment is to move terminal C into its own child process and hard-kill it at the terminal execution/publication/ACK cuts while B and A independently survive. After that, a repeated two-crash experiment can kill B, restore it, then kill C (or vice versa) while preserving the same operation and quorum history.
