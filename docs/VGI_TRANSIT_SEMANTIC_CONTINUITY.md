# VGI Transit Semantic Continuity

## Purpose

This document records the first receiver-recovery experiment for hosting the Virtual Ground Interpreter (VGI) inside E-CPU's Transit execution path.

The architectural claim is deliberately narrow:

> A committed computational effect can outlive the receiver process that produced it.

The experiment does not equate a program, its computational Ground, the host that executes it, and one particular execution. Those are separate identities and must remain separately inspectable during recovery.

## Identity boundaries

| Identity | Representation in this integration | What it identifies |
|---|---|---|
| System Ground | `VirtualGroundRef(origin_digest, state_digest, coordinate, frontier_digest)` | The admitted E-CPU system context and causal frontier |
| Computational Ground | VGI `SIGNAL8_GROUND.fingerprint` | The value domain, operations, and observation rules used by Signal8 |
| Program | VGI compiled program fingerprint | The compiled transition relation for the supplied typed task |
| Input and context | Canonical workload/input digests plus workload constraints | The particular task instance, input signal values, budget, intention, logical time, and placement constraints |
| Operator | `operator_id`, version, and `OperatorSpec.digest` | The declared operation contract selected by the receiver |
| Host | Transit node identifier plus receiver-local process authority | The operational locus and authority under which the operation is admitted |
| Execution | `(source, channel, sequence)`, event fingerprint, decision receipt, and effect receipt | One logical operation attempt and its committed result |

The System Ground and Computational Ground are not interchangeable. The first determines whether the operation belongs in the receiver's admitted system context; the second determines what the VGI program means.

The host is also not the operation. Its process identifier and in-memory objects can disappear. The operator contract, program identity, Grounds, input, and committed result are the material that the receiver checkpoint must preserve.

## Transit refinement path

The integration adds `TransitVGIHost` as a receiver-local backend registered through `TransitBackendRouter`.

1. The sender constructs a typed `VirtualLayerWorkload` and `build_vgi_signal8_event` creates its normal hypervisor event. The event carries a workload and operator reference, not executable Python or remote authority.
2. The receiver reconstructs granted capabilities from its own process table. The event's workload digest, operator contract digest, input digest, budget, placement, and System Ground are checked by the existing `VirtualLayerRuntime` preparation path.
3. The Transit router resolves the exact operation/resource pair to `TransitVGIHost`. The host reuses the Virtual Layer operator contract and invokes the Signal8 interpreter only after the hypervisor selects the CPU execution domain.
4. The VGI receipt is wrapped in the normal `virtual_layer.operator_result` effect. It preserves both Grounds, the VGI interpreter version, program fingerprint, trace, outputs, and Signal8 machine checkpoint.
5. Transit adds its canonical semantic-translation evidence. The hypervisor execution ledger stores the resulting effect under the stable execution identity, and the shared event journal records `hypervisor.execution.commit`.

The Transit backend manifest records the operation/resource relation, not Python callables. A receiving process must explicitly rebind the same trusted backend relation during restore. The checkpoint does not transfer executable handler objects.

## Recovery cut and observed law

The subprocess experiment deliberately stops at:

`after_execution_commit` and before response publication or request acknowledgement.

At that cut, the receiver:

- writes its Transit session checkpoint;
- seals the requester checkpoint, receiver checkpoint, backend manifest, and checkpoint manifest through `RecoveryCheckpointBundleStore`;
- obtains the fixed-membership recovery-lineage proof; and
- publishes a marker so the test process can terminate the receiver without graceful shutdown.

A new Python interpreter then loads the bundle through the quorum-gated restore path, reconstructs the receiver, rebinds the same backend relation, and receives the same requester frame again.

The expected recovery relation is:

`Restore(Persist(receiver))` contains the same committed effect `E[I]` for the same event identity `I` and fingerprint `F`.

The replay must return the stored effect, leave the VGI backend invocation count at zero after restart, preserve one execution-ledger entry and one `hypervisor.execution.commit` record, and append a replay observation. The VGI execution digest, System Ground, Computational Ground, program fingerprint, execution trace/output, and VGI checkpoint are compared with the pre-crash committed receipt.

## Guarantee and boundary

For the tested deterministic, pure Signal8 operation, the experiment is evidence for **one committed semantic effect across receiver-process death**.

It is not a claim of exactly-once physical execution for arbitrary operations. If a receiver dies after a pure handler returns but before the hypervisor effect commit, a retry may execute the handler again. The guarantee begins at the durable execution commit represented in the captured receiver state.

The current proof also has explicit limits:

- It exercises one typed Signal8 program and its exact operator contract; it does not yet prove general Ground-to-Operator refinement across arbitrary CPU, GPU, FPGA, or distributed backends.
- The three recovery authorities in this test are independent durable journals within the test environment. The test exercises the existing strict-majority lineage protocol and bundle verification; it is not a deployment or network-partition certification.
- The requester remains alive and retains its own channel state while only the receiver is killed. Joint requester/receiver death and independent restoration of both endpoints remain separate recovery obligations.
- The receipt includes the VGI interpreter version and the pinned dependency used by the integration, but a standalone cryptographic implementation fingerprint for the complete loaded interpreter/adapter code is still a future identity refinement.

## Next proof obligations

1. Extend the process-death test to failures before execution commit and at the persistence/lineage boundary, preserving the distinction between retryable execution and committed-effect replay.
2. Add negative recovery cases for altered input under the same operation identity, mismatched System Ground, changed VGI Ground/program, corrupted VGI checkpoint, and changed backend manifest.
3. Formalize Ground-to-Operator refinement so multiple concrete backend steps may implement one abstract VGI transition while preserving declared observations and numerical tolerances.
4. Bind a stable implementation fingerprint to the operator identity and compare it during backend reattachment.
