# SAB-002 — Active Ground discovery over portable code/data hosts

**Experimental:** bounded, permissioned, finite-witness inference. This is not proof that arbitrary devices can execute E-CPU, a sandbox for untrusted executable code, or unrestricted Internet discovery.

## Question

If an unfamiliar environment retains data and supports an authorized observation operation, can E-CPU recognize a compact navigable state law without knowing whether the source is a process, port, NIC, machine, or virtualized service?

SAB-001 compiled offered operations into an admitted observer-host graph. SAB-002 first asks a resource to produce bounded observations, derives a candidate mathematical Ground, tests withheld coordinates, and then *separately* requires local authority and a trusted implementation before exposing that Ground as an executable SAB-001 path.

## Test protocol

The declared observer supports observe(t) -> integer modulo m. The tested law family is an affine recurrence:

    x_(t+1) = (a*x_t + c) modulo m

Probe coordinates are [0, 1, 2, 3, 7, 11, 19, 7]. Initial observations at 0, 1, 2 propose a and c; later coordinates test the proposal, including a repeat to catch simple temporal instability. Ambiguous initial differences (without a modular inverse) are refused. The observation transcript is content-addressed.

A locally preapproved subprocess command can launch a separate Python interpreter holding a fixed program and parameters. It accepts one strict JSON observation request, returns a typed value with echoed host identity and coordinate, and has timeout and response-size bounds. This is real process separation, not independent hardware. No executable code comes from the observed resource. The echoed fields are not cryptographic peer authentication.

An independently provided callback can expose the same observation relation. These two different substrates yield the same host-independent mathematical Ground digest for matching law parameters, while their host-bound observation transcripts differ.

## Admission, execution, verification

The candidate may *advertise* the navigate.affine_mod operation. Advertisement is not permission. GroundAdmission requires an exact approved host ID and Ground digest, a valid lease, and a local trusted handler. That handler uses E-CPU's native law_certifier.lcg_navigate. SAB-001 still requires explicit operation permissions, available carriers, and a current typed plan. A separately implemented binary affine-map composition checks the produced result at large requested coordinates; that is an independent arithmetic comparison for the stated law, not a proof the source uses this law everywhere.

One test constructs an ingress -> discovered observer -> checker path, executes a query at t greater than 10^15, and verifies SAB-001's content-bound receipt chain. Another replaces the preferred host and shows the mathematical intention and result remain unchanged while the inventory/route identities change.

Adversarial tests cover unauthorized probes with zero I/O, expired observations, observer identity mismatches, non-affine traces, unstable repeated observations, ambiguous recurrences, malformed types, bad transcripts, forged response fields, timed-out subprocesses, missing Ground authority, altered inputs, and stale plans.

**Important counterexample:** A deceptive source matches *every* finite test coordinate and disagrees at a later one. The recovered description therefore carries the explicit grade finite_witness_only, never a universal mathematical certificate. A SHA-256 digest establishes record identity, not source authenticity.

## What hosting means here

This experiment establishes a finite observer-host plus a *locally* realized navigable mathematical law after admission. It does not show an entire E-CPU runtime inside the subprocess, arbitrary third-party code execution, persistence, robust remote transport, genuine separate failure domains, or general-purpose computational discovery. A code interpreter plus storage may be a plausible substrate, but runtime qualification needs observed contracts for durability, execution authority, clocks, transport, and recovery.

## Next frontier

SAB-003 should test bounded storage/retrieval after restart, program interpreter capabilities, authenticated communication, clock observations, and independent recovery as *separate* discoverable capabilities. Only then combine them into a portable E-CPU runtime profile. Reuse the existing E-CPU Hypervisor, Structural Memory, computational-fabric directory and recovery lineage; do not invent authority from sensor observations. Probe only explicitly controlled endpoints. Passive DNS latency and fiber delay alone do not provide arbitrary processing or reliable addressable memory.
