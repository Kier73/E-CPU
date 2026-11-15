# PATH-GROUND-001 — Communication as an observed computational relation

**Status:** bounded live localhost TCP experiment + mathematical **software reference**. This is **not** physical optical computation or permission to operate third-party infrastructure.

## Why this is an E-CPU experiment

The foundational proposition [The Internet Is the Computer](THE_INTERNET_IS_THE_COMPUTER.md) asks whether computation can be formed from information relations already present in communication architecture, rather than always executing on a conventional processor at the far end of a link.

The minimal falsifiable step is to observe *two different Grounds of the same path* without claiming a CPU is the only meaningful part or that the path can perform arbitrary operations:

1. **Payload Ground:** ordered input bytes must emerge as the same ordered byte stream through a controlled transport. Sender write boundaries are not meaningful receiver message boundaries in TCP. The OS's TCP machinery supplies a byte-stream abstraction, while application code performs the reads and verification.
2. **Temporal observation Ground:** the endpoint-to-endpoint wall of elapsed monotonic nanoseconds is a measured property of the same experiment. It includes application scheduling, stack and kernel handling, loopback delivery and receiver copy costs, so it **must not be interpreted as optical fiber time-of-flight** or stable physical delay.

`mailcpu.path_ground_probe.probe_tcp_loopback` runs actual `socket.AF_INET/SOCK_STREAM` traffic solely on `127.0.0.1`, using a background receive thread and preallocated byte buffer. The typed receipt is tied to `mailcpu.substrate_bootstrap.ChannelObservation`, an explicit lease, payload limit, SHA-256 of transmitted and observed bytes, and the actual elapsed measurement.

The adapter `bind_tcp_carrier_witness` takes *independently supplied endpoint bytes* and uses the **already merged** `mailcpu.observer_path_evidence.ObserverPathStage`, `verify_observer_path`, and `check_observer_path_receipt` to construct a single passive-carrier path witness. The receiver-local validator checks actual endpoint bytes, and the caller selects the Ground and policy identity. The link is **not** relabeled as a CPU merely because we measured it. The SHA-256 stage identity is not authentication.

The optical-level transformation is a different Ground; a future actual optical instrument would be required to observe it. The optional `characterize_temporal_span` attempts a **bounded, explicitly policy-specified** endpoint-duration envelope using calibration and held-out TCP observations; variability exceeding tolerance refuses the temporal candidate. It cannot assert a pure propagation-time or constant-delay law.

## A separate model for the physical-path hypothesis

For a candidate finite linear time-invariant transfer relation we can describe

\[
y_i = \sum_{j=0}^{K-1} h_j x_{i-j}, \qquad x_{i<0}=0.
\]

An impulse observation proposes `h`, a shifted impulse probes time-shift invariance, and at least two independent held-out inputs must agree within a declared tolerance. This is the `characterize_transfer`/`TransferGroundCandidate` implementation. It checks all original probe samples and stores a digest binding their complete content, environment identity, mechanism and measured mismatch.

For the **local reference only**, inputs are passed through a **Python FIR function**, with kernel `(0.625, 0.25, -0.125)`. The recovered kernel and held-out predictions verify the *characterization logic*, not a physical path. The mechanisms are explicitly tagged `software_fir_reference` or `instrument_observation`; merely claiming an instrument type cannot confer trusted provenance. A real host-side instrument adapter must independently establish source/receiver identity, clock domain, calibration, output measurements, and authorization. External measurements cannot be accepted solely from a sender-provided hash.

The experiment refuses drift, nonlinear or non-LTI counterexamples on the checked samples, altered holdouts, wrong frame, mismatched environment, duplicate receipt identities, stale channels, oversize transport, and unsupported claims of universal proof. Observations support only an empirical, scoped Ground candidate—not an assertion about all inputs or all possible physical conditions.

## Reproduction

From E-CPU repository root, with E-CPU installed in the test environment:

```bash
python -m unittest discover -s tests -p 'test_path_ground_probe.py' -v
python -m examples.run_path_ground_probe > path-ground-report.json
```

The example binds the **real TCP** result into a **native E-CPU carrier witness**. It also runs a wholly separate synthetic FIR control. The generated JSON includes source environment, 32 TCP probes, exact digital continuity, elapsed min/median/max, a bounded or refused temporal candidate, native path witness, a separately labeled FIR candidate and explicit non-claims.

In the initial **isolated Python 3.13 compatibility harness** (standing in for native `ChannelObservation`, `RepresentationRef`, and the carrier-only `ObserverPath` dependencies), **24 of 24 focused tests passed**. The run observed 32 successful TCP byte streams with a median elapsed observation of **76,991.5 ns** and a range **54,428–1,618,734 ns** on that single ephemeral loopback environment. These timing numbers include endpoint operations and are not speed or optical propagation benchmarks. Timing is environment-dependent and should be remeasured, not treated as a universal constant.

The timing-envelope decision (accepted or refused) is retained in the JSON report; it depends on the measured jitter and the declared 25,000 ns tolerance, and is **not** a physical propagation certification.

The dedicated repository CI workflow runs the **real E-CPU classes** on Python 3.11 and 3.13 on Linux and Windows. To actively reuse rather than duplicate existing infrastructure, it also runs the native `test_transit_path_modes`, `test_transit_path_binding`, `test_observer_path_evidence`, and `test_observer_orbit` suites. These remain pending until CI executes; local API-compatible tests do not establish integrated behavior on every platform.

## Next physical-path work

With explicitly controlled hardware (fiber, calibrated delay network, or instrumented photonic signal processor), replace the `software_fir_reference` output with independently acquired input/output samples from the medium. Preserve at least three distinct control cases:

- **Bypass path**: measure source/receiver electronics and transducers without the candidate medium.
- **Candidate medium**: measure the actual physical input/output operator, environment stability and held-out prediction errors.
- **Host-side software operation**: characterize digital computation deliberately performed in source, receiver or network-stack software as a separate accounting category, not as a property of the fiber.

Record input encoding, bandwidth, detector calibration, noise, phase/clock identifiability, transfer duration, setup cost, energy and actual trust provenance. A physical-path claim succeeds only if a measured transformation attributable to the medium satisfies the declared Ground better than relevant controls and survives held-out tests under the admitted operating conditions. Do not infer independent physical hosts or fiber computation from the local software fixture.

Once that evidence exists, candidate mathematical models can be carried through VGI's geometry-first structural extraction, representation changes and independently verifiable certificates, while E-CPU's existing Hypervisor/Transit/StructuralMemory systems determine **who may execute, store, read and recover** the result. The physical path does not grant itself new authority.