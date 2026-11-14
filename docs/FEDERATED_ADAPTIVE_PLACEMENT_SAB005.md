# SAB-005: Authenticated adaptive placement with receiver-native execution

**Status:** bounded experimental direct-peer transport and receiver-local E-CPU Hypervisor operator. A successful loopback test is **not** proof of independent physical hosts, independent failure domains, general E-CPU federated directory deployment, or quorum-anchored recovery.

## Question

Can one SAB-004 mathematical intention be realized through independently operated, mutually authenticated receiver services, with computation admitted by the **receiver's actual E-CPU Virtual Layer/Hypervisor** and results recovered from surviving durable receivers after compute/relay services disappear?

SAB-005 preserves the SAB-001 typed planner, SAB-003 empirical role qualification, and SAB-004 checkpoint/decision records. The new MutualTLSQualificationEndpoint implements the same qualification interface; SAB-004's planner remains unchanged and non-authoritative.

## Implemented receiver protocol

1. The origin pins each service's network address, DNS SAN, CA and its own client certificate. Each listener requires a CA-verified client certificate **with its exact expected DNS SAN**, not merely a certificate from the same issuer.
2. The receiver pins its own finite opcode allowlist. A remote request carries neither executable source, process command, nor a capability. Every accepted request starts a fresh **locally installed** worker subprocess.
3. For affine_mod, that worker constructs a receiver-local HeadlessOS system Ground, registers a pure OperatorSpec, and executes through VirtualLayerRuntime.execute_operator. Only a receiver-configured compute capability can authorize it. The response is refused unless the native Hypervisor returns ALLOW, the exact operator contract, and an independently checked mathematical result.
4. The receiver saves content-bound native execution evidence before acknowledging the arithmetic response. It is receiver-owned provenance, **not a signed hardware attestation**. Pure work may repeat across restarts.
5. For framed transfer, immutable retain and fresh-process retrieve, the receiver reuses the fixed SAB-003 worker. SAB-004's checkpoint digest and separately stored decision marker preserve intended results through re-placement and partial process loss. This is **not** Byzantine quorum or general exactly-once side-effect safety.

## Tests and evidence boundaries

The mandatory CI harness starts five **separate listener processes** on loopback, each with a distinct short-lived server certificate and data directory: calc-fast, calc-slow, port-relay, store-a, and store-b. It uses an ephemeral origin certificate and a wrong-identity attacker certificate. No private keys are committed.

Adversarial cases: wrong client SAN, wrong server SAN at the same IP, forbidden operation, switched host field, receiver compute capability revoked, checkpoint retained across listener restart, receiver-native Hypervisor audit, stale placement refusal after compute-host removal, two replica commits, and survivor-only recovery after stopping compute/relay services.

**Actual physical separation has not yet been measured.** Distinct sockets, certificates and operating-system processes do not prove different machines. The listener can be configured on an owned remote interface, but the mandatory test remains on loopback.

The transport is a bounded canonical JSON direct mTLS exchange, **not yet E-CPU's normal ReliableChannel + SocketTransport + ComputationalFabricForwardingServer forwarding path**. It does not use ComputationalFabricDirectory authenticated peer snapshots or RecoveryLineageCoordinator quorum certification in this stage. Those remain the meaningful next gates.

## Next gate

Run the receiver protocol across independent, explicitly authorized hosts and independent link/failure domains; then replace direct peer dispatch with existing authenticated Computational Fabric forwarding and receiver-local ComputationalExecutionAdmissionCoordinator, anchoring checkpoint decisions through E-CPU's recovery lineage. Test competing controllers, replay fencing, changed certificate identity, authority revocation during failover, lost transport acknowledgements and rollback attempts.

This work remains under active development. Route discovery never grants computation authority; observed latency, public DNS or passive optical paths are not treated as processors without admitted physical transitions.
