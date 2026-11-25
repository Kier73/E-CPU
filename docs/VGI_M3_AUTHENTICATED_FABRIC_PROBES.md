# VGI minimal source observations over E-CPU's authenticated fabric

## Capability
A quorum-persistent VGI Ground can upgrade its running coordinates from a **source-host observation** without transferring the source state. The source peer runs a locally installed `vgi.guarded.source_probe` pure operator on E-CPU's existing Hypervisor, verified M3 checkpoint and source-pinned VGI implementation. The destination obtains only the necessary probe values through an existing `ComputationalFabricForwardingClient` mutual-TLS peer stream, then commits the new Ground using M4 compare-and-swap.

## Mathematics
Given an old quotient basis `B`, a new basis `B'` and current reduced state `z=Bx`, VGI computes missing probe rows `P` and a reconstruction `L` satisfying `B'=L[B;P]`. The source measures `u=Px` locally. The destination calculates `z'=L(z,u)`; it does not fetch `x`.

For the included 48-dimensional binary example, the source has 2^48 possible states. The running quotient needs two coordinates; upgrading to the next three-coordinate Ground requires **one remote probe bit**. The test executes 16 transitions, verifies M3 revision 2, migrates using one direct authenticated hop to revision 3, then advances seven transitions to revision 4.

## Execution protocol
1. The destination uses its trusted local route builder to address `vgi.guarded.source_probe`. The query binds the exact session ID, M3 revision, checkpoint digest, recovery-lineage digest, artifact digest, VGI program, stage transition, existing coordinates, probe basis, M4 operation ID, input digest and logical time.
2. E-CPU's direct forwarding client establishes a CA-verified mutual-TLS peer connection. Each terminal request is received through E-CPU's reliable channel and revalidated against the receiving peer's local route/Hypervisor state.
3. The source handler loads the *latest* M3 state and checks the exact query, lineage, old coordinates and certified probe basis. Its installed source observer supplies full state locally at the same checkpoint; it refuses contradictions with the committed quotient. It returns only the necessary values and the bound request identity, source peer and host identities.
4. The destination validates the typed source response against the same query and the terminal fabric receipt, reconstructs the coordinates with VGI's independent lift verifier and commits through the native M3/M4 transition adapter. M1 state bytes now store a probe-only event, source host/peer names and the verified hop receipt digest.
5. Recovery independently verifies VGI's saved transition/migration proof and checks that the event's predecessor checkpoint/lineage match the actual committed M3 predecessor. Existing receiver-local source-observer migrations remain supported.

## Trust and limits
Authentication belongs to the **direct E-CPU mutual-TLS transport**, receiver-local peer directory, capability and Hypervisor controls. Content digests bind bytes; they are not signed attestations. A detached copied hop receipt cannot establish peer authenticity without its authenticated channel context. A remote source's hidden numerical state is trusted at its host; the destination proves the mathematical lift of the received probe values, not remote physical truth. The source callback is installed locally; workload JSON never carries Python source or a callback.

This implementation intentionally restricts remote observations to **direct mTLS peers**. Multi-hop source authenticity and a durable source-state observation witness are next experiments. In particular, a relay's unsigned receipt must not be mistaken for end-to-end attestation.

## Verification
From a complete E-CPU checkout with the pinned VGI package:

```bash
python -m pip install -e . pytest
python -m pip install 'git+https://github.com/Kier73/Virtual-Ground-Interpreter.git@39a169b21513ffaaee85e40826c706c07a47215b#subdirectory=virtual_ground_interpreter'
python -m pytest -q tests/test_vgi_fabric_probe.py tests/test_vgi_guarded_recovery.py
```

The dedicated workflow at `.github/workflows/vgi-m3-fabric-probes.yml` also runs Virtual Layer regression. Tests cover genuine direct mutual TLS, source-resident operator execution, M3 import and continued computation, altered payloads, forged/rehashed host identities, wrong lineage and mismatched probe basis. Local VGI suites and independent lightweight protocol checks can be run without a complete E-CPU checkout, but do **not** replace the full mTLS/Hypervisor/M3 CI result.

## Next experiment
Extend the source measurement from a receiver-local installed callback into independently reconstructable durable M1/M3 evidence, then use E-CPU's existing claim epochs to admit multi-hop source authority. Record transmitted probe bytes, verified latency and recovery after hard process/host loss.
