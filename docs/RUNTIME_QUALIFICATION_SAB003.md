# SAB-003 — Behavioral runtime qualification of code-and-data observer hosts

**Status:** bounded, experimental; not a general-purpose runtime, remote host attestation, arbitrary-program sandbox, universal law proof, or grant of authority.

## Research question

Can a resource be qualified for a useful portion of E-CPU without its identity being tied to a CPU, chip, port, network path, server, or specific operating system?

SAB-001 compiles observed resources and locally admitted operations into typed routes. SAB-002 discovers a candidate navigable Ground from finite measurements. SAB-003 distinguishes *what a code/data environment actually demonstrates* from the hosting roles E-CPU may safely infer.

## Qualification protocol

The locally approved worker at `mailcpu/runtime_qualification_worker.py` is a **fixed Python interpreter program**, never downloaded source. It accepts one bounded, typed JSON request and exits. Each `SubprocessQualificationEndpoint` exchange launches a fresh process with explicit argv, no shell, timeout, output-size limit, echoed correlation nonce, and strict response schema. The process can retain a small immutable JSON record in a local directory via atomic rename and fsync. The experiment directly checks a subsequent fresh interpreter can read it. It does not claim persistence across a machine failure or prove that separately named hosts occupy separate physical hardware.

SAB-003 runs at most eight finite probes, subject to the receiver-owned host allowlist, permitted roles, observation coordinate/lease and per-request bounds. Unsupported features remain unavailable; *contradictory successful results* fail closed. The resulting transcript is content-bound; a separate report verifier reconstructs each role from the raw observations rather than trusting the profile's claims.

| Qualification role | Actual probe | Not thereby proven |
|---|---|---|
| `observer` | exact challenge and content digest | authenticated endpoint identity |
| `framed_ipc` | exact 64-byte transport loop | Internet connectivity, transport bandwidth or physical NIC |
| `computational_fragment` | multiple independently checked affine recurrence values, including a distant coordinate | general instruction execution or behavior on unseen coordinates |
| `retained_state` | immutable data read after a new process launch | host crash recovery, fault independence or authenticated storage |
| `restricted_dispatch_observed` | one disallowed source-operation request is refused | safe sandbox for arbitrary code, Hypervisor permission |

An optional worker flag disables computation, storage, or transport; `--volatile` acknowledges writes but fails subsequent reads; `--wrong-compute` and `--unsafe-dispatch` deliberately contradict the contract for negative tests. Arbitrary source code is **never evaluated**, including in the negative fixture.

A successful report always states:

- `evidence_grade = finite_behavioral_witness_only`
- `hardware_attested = false`
- `full_ecpu_runtime_verified = false`
- `local_hypervisor_permission_granted = false`

The source process may be considered an **observer**, **computational fragment**, **framed IPC endpoint**, or **retained-state resource**, depending on the exact observed results. Its full E-CPU host status remains unproven.

## Composition and authority

`QualificationReport.to_resource()` can project verified computation into a SAB-001 `ResourceObservation` with an `affine_mod` *offer*. It does not install a `RealizerBinding`, invent a capability, or promote an observed contract to receiver execution authority. A production use must continue through E-CPU's native Host Catalogue, Ground admission, Virtual Layer, Hypervisor and recovery-lineage mechanisms, with separately authenticated remote transport as appropriate.

The native E-CPU `lcg_navigate` function is checked for agreement on the same remote contract. A real, separate subprocess is invoked; a separate hardware failure domain is not demonstrated. The SHA-256 transcript proves canonical byte consistency, not who physically produced the message.

## Falsifiers and future work

Tests reject an unauthorized endpoint before I/O, expired lease, unperformed probes, forged host or nonce, false but rehashed reports, changed storage after commit, unsupported operations elevated to execution, and incorrectly computed arithmetic. They distinguish a volatile write from retained state. Probes are bounded and voluntary; public DNS delay or arbitrary Internet resources are not implicitly repurposed as processors.

**Next:** SAB-004 should connect qualified operator roles to actual receiver-owned E-CPU computational admission and authenticated separate-host transport, verify restart/recovery from independently retained state, and measure observation, communication, interpretation and navigation costs separately. A candidate runtime profile must never bypass the existing Hypervisor/Structural Memory authority boundary.
