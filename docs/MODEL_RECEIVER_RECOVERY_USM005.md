# USM-005 — A model survives receiver loss without a second Ground effect

USM-005 is a direct continuation of the earlier model-operated E-CPU experiments
[USM-001](https://github.com/Kier73/E-CPU/pull/138),
[USM-002](https://github.com/Kier73/E-CPU/pull/139), and
[USM-004](https://github.com/Kier73/E-CPU/pull/140). It deliberately reuses
existing E-CPU recovery machinery instead of inventing a second runtime.

## Operational question

**Can the model retain its active computational intention when its receiver
process disappears after committing a Ground read but before returning its
transport acknowledgment?**

The experiment launches two distinct receiver OS processes and keeps the
model-driving process alive throughout the crash and replacement.

1. The live model communicates over E-CPU's real mTLS SocketTransport and
   ReliableChannel. It chooses `observe`, `propose`, and `read` calls.
2. The first receiver obtains actual observations, admits a witness-grounded
   structural memory through its own authorization policy, and navigates to
   logical coordinate `1_000_000_000_137`.
3. While still inside `ReliableChannel.receive(commit=...)`, *after*
   `GroundSystemCallSession.apply` and *before* `consume+ACK`, the receiver
   persists a composite state artifact: model artifact digest, receiver-owned
   source, structural memory registry, admitted revision, exact operation
   trace, and both directional ReliableChannel snapshots.
4. E-CPU's existing `RecoveryStateManifest`, `RecoveryLineageCoordinator`,
   and `RecoveryLineageAuthority` seal the checkpoint's byte identity into
   a three-member strict-majority durable ledger. Only then does the receiver
   call `os._exit(86)` — a hard process termination, not a graceful return.
5. The model's original send remains pending. A new receiver process validates
   the **latest** quorum-anchored state against the durable data bytes, restores
   `StructuralMemoryRegistry.from_snapshot`, reconstructs the original
   `GroundSystemCallSession`, and rebinds
   `ReliableChannel.from_snapshot` to a **new authenticated TLS socket**.
6. The model retransmits the **same reliable sequence and semantic request**
   on the fresh socket. The replacement receiver recognizes the exact
   previously committed call, leaves the stored Ground and read receipt
   unchanged, and lets ReliableChannel consume and acknowledge the retried
   frame. The model then receives the old value and receipt through the new
   connection. A second quorum-anchored checkpoint records the advanced ACK
   cursor.

The experiment preserves model-session causality and evidence while
changing the physical process hosting the receiver.

## Existing infrastructure deliberately reused

| Capability | E-CPU implementation |
|---|---|
| Authenticated reconnection | `mailcpu.mtls_transport` |
| Sequenced retry / dedup state | `mailcpu.reliability.ReliableChannel` |
| Ground certificate, admission, registry snapshot | `mailcpu.structural_memory.StructuralMemoryRegistry` |
| Fixed-membership recovery high-water | `mailcpu.recovery_lineage.RecoveryStateManifest` and `RecoveryLineageCoordinator` |
| Durable quorum authority journals | `RecoveryLineageAuthority` |
| Model-issued, receiver-gated operating ABI | `examples/model_system_calls.py` |

This inherits concepts demonstrated by earlier cross-process recovery, terminal
peer replacement, quorum recovery lineage, and frontier rehoming experiments.
It does **not** replace or subsume those more general facilities.

## Reproduce

From the E-CPU repository root with OpenSSL installed:

```bash
python -m pytest -q tests/test_model_receiver_recovery.py
python -m examples.model_receiver_recovery demo --output usm005-report.json
```

The tests check that the first receiver exits at the designated hard-crash cut,
the same model host resumes on another authenticated socket, its original
sequence 3 remains pending, the eventual result agrees with an independently
computed affine source value, and the replacement receiver performs **zero
semantic re-entries**. They also reconstruct the restored registry and
read its admitted revision, reject the valid *older* checkpoint once generation
two has been sealed, reject changed checkpoint bytes, and reject changed
manifest data.

## Evidence interpretation

- The model-side process stays alive across the receiver death and reconnect.
  The execution does not require survival of the first E-CPU receiver OS
  process, its socket, or its in-memory Ground object.
- The replacement receiver *replays a committed response*; it does not
  recompute the already committed semantic read. No duplicate semantic effect
  is claimed for this specifically instrumented crash window.
- The three lineage authorities are **three durable journal files within a
  single test runner and one filesystem failure domain**. The code exercises
  strict-majority lineage and stale-head refusal; it does not provide three
  independent network/physical fault domains in this test.
- The model is a deliberate high-request control checkpoint for the precise
  crash-cut experiment, not a new language model or a learned failure detector.
  Learned-controller behavior is separately exercised in USM-001–004.
- The observation source is a known mathematical fixture. Neither TLS peer
  authentication nor a hash-chain transforms a fixture into physical evidence.
- The crash occurs at one explicit point: **after the Ground read and durable
  quorum seal, before the reliable ACK**. This does not prove all conceivable
  failures, shared-disk power loss, quorum partition tolerance, stale
  competing process fencing, general exactly-once computation, or true
  independent-machine deployment.
- CI execution and actual evidence artifacts remain necessary before this
  milestone can be classified as operationally verified.

## Next frontier

Distribute the lineage authorities across genuinely independent authenticated
hosts and test **competing receiver owners**, not only sequential replacement.
Require a fresh owner-generation certificate before publishing an admitted
read. Run failure cuts both before and after Ground admission, during network
partitions, and after ACK publication. Bring the independent IFS/VGI verifier
to the recovered trace so the observer can distinguish transport redelivery
from semantic duplication.

The central objective is not merely to recover a dead process; it is to keep
the model's mathematical intention addressable and verifiable while its
physical realization changes.
