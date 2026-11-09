# Empirical Computational Placement Profiles

## Purpose

This specification defines a reusable evidence layer between operation-frontier timing and future computational placement policy.

The fabric already publishes ranked, non-authoritative host/route candidates. The timing probe already records endpoint-local phase samples. Operation-native binary frontier receipts already retain the target host, peer path, route-witness digest, implementation fingerprint, backend receipt and operator effect.

A placement profile joins those existing records. It describes how one exact implementation and route has performed for a declared workload class in one origin environment. It does not replace the resolver, receiver-local checks, Virtual Layer admission, Hypervisor authority, or result verification.

## Profile identity

**PlacementProfileKey** binds:

- a caller-defined workload-class digest;
- operator ID and version;
- exact operator-contract digest;
- Computational Ground fingerprint;
- origin-environment digest;
- target logical host;
- implementation fingerprint; and
- for remote execution, the ordered peer path.

The comparison identity deliberately excludes the selected host, implementation, and route. Profiles can therefore be compared only when they share the workload class, operator contract/version, Computational Ground, and origin environment. Within that comparison group, the profile key distinguishes the selected host, implementation and ordered peer path.

The workload-class digest is explicit because two different input instances may still belong to the same declared workload class. Each observation separately binds the exact compiled workload digest through its timing correlation ID. Callers are responsible for defining a workload class that captures the properties relevant to comparable execution (for example lane count, operand-size range, program/plan shape, state representation, and input-resolution requirements). A vague or over-broad class makes the comparison invalid even if its digest is well formed.

The origin-environment digest should identify the environment in which end-to-end durations are observed. At minimum, retain the runtime version, operating system/platform, machine architecture, and relevant CPU identity. The benchmark uses Python version, platform, machine, and processor description. A deployment that changes the origin environment should create a different comparison group.

## Observation and provenance

A **PlacementObservation** accepts only an OperationTimingSample with:

- phase total_completion;
- a correlation ID equal to the exact workload digest;
- actor-local monotonic readings from one actor and restore segment; and
- actor-local causal stamps retained as ordering provenance.

An observation also binds an execution digest, a verification-evidence digest, and the declared verification method.

For remote placement, it retains the complete typed ADD/COMPARE/MUL frontier receipt. The profile checks that the receipt matches its declared host, implementation fingerprint and ordered peer path. The exact route-witness digest remains inside each observation's receipt. This distinction is intentional: the route witness commits the request-specific computational address, so its digest may change between samples even when the selected host and peer path remain the same. Local placements have no remote peer path or frontier receipt.

The caller must create an observation only after its independent result checks have passed. The operation-frontier benchmark does this by checking the terminal execution against the MailCPU reference interpreter and checking every product lane against the scalar product oracle. Its verification digest commits those checks, the exact plan and the execution identity.

A digest is a content identity, not a digital signature, host attestation, or proof that an untrusted caller actually performed the check. Profiles are empirical records from the trusted benchmark/measurement process; they do not elevate an untrusted report into trusted evidence.

## Statistics and comparison

**PlacementProfile** is immutable. Adding an observation returns a new profile. Samples are not merged across different placement keys.

The profile reports count, minimum, median, p95, maximum and integer mean of the origin's total-completion durations. It stores no absolute timestamp comparison across hosts. Receiver phase durations remain useful diagnostics, but they are not subtracted from origin durations or added into the end-to-end result.

**rank_placement_profiles()** requires at least two profiles from one comparison group. By default, every placement must contain at least three observations. If any candidate falls below the sample floor, the ranking is explicitly incomplete and exposes no best profile.

For a complete comparison, candidates are ordered by:

1. median total-completion duration;
2. p95 total-completion duration;
3. mean total-completion duration; and
4. stable host, implementation and route identities.

This is an empirical ordering for the declared sample window, not a universal cost law. It intentionally does not blend the fabric's advertised additive cost vectors with observed nanoseconds. Those have different meanings and units. A future policy may combine calibrated quantities only through a separately specified model.

The ranking is advisory (recommendation_authoritative = false). It cannot dispatch an operation, reserve capacity, alter host advertisements, or bypass a receiver's fresh route resolution, provenance validation, local capability checks, or Hypervisor admission.

## Benchmark integration

The operation-frontier benchmark now emits placement_profiles alongside its phase-level timing output. It constructs profiles for:

- local CPU reference-DAG evaluation;
- remote CPU frontier execution; and
- remote E-GPU frontier execution.

Each remote sample carries its actual typed multiplication-frontier receipt. Profiles share a workload-class identity derived from the benchmark's lane count, multiplier width, operation contract and declared Ground. The exact compiled plan digest remains bound into every timing sample.

Run:

    python examples/operation_frontier_benchmark.py --warmups 1 --iterations 5 --lanes 64 --multiplier-bits 2048 --output operation-frontier-timing.json

At least three measured iterations are required for a complete ranking. With fewer, the report preserves the observations but marks the comparison incomplete. The benchmark remains a one-hop mutual-TLS loopback experiment using the bounded Python E-GPU/SIMT implementation; it does not establish WAN performance, physical GPU acceleration, or multi-host concurrency.

## Integration seam for adaptive placement

The profile API is intentionally below policy. A future placement planner can:

1. resolve bounded non-authoritative candidates using ComputationalFabricResolver.resolve_candidates();
2. look up profiles matching the exact workload class, operator contract, Ground, origin environment, implementation and route;
3. refuse or run a calibration workload when the evidence floor is not met;
4. rank candidates using measured end-to-end distributions while retaining advertised resource/cost vectors separately;
5. select a candidate as a proposal; and
6. let the existing receiver re-resolve the live route and independently admit the workload.

The next stage can extend this profile from one whole-frontier placement to partition-level profiles. That will allow the multi-host scheduler to estimate the cost of assigning bounded DAG partitions to different hosts without treating one benchmark as a universal throughput estimate.

## Invariant

B-53 in [INVARIANTS.md](INVARIANTS.md) registers the profile identity, receipt-binding, evidence-floor and advisory-authority requirements.
