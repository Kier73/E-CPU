# NCB-004 — Use constructed computation to test the development system itself

**Research question:** Can an intention-derived mathematical processor generator be directly useful in developing its own receiving E-CPU runtime—not just demonstrating a static, already-known mathematical example?

**Method:** Use the existing, independently developed and pinned [Navigable-Compute NCP-002](https://github.com/Kier73/Navigable-Compute/blob/e607fd80c00630f6b31e4c86b9b5ee8faebda410/navigable_compute/coupled.py) as a **test generator**. Let it construct several correct alternative processors from declared system goals and resource constraints. The generated controller action tables—not a developer's hardcoded trace—choose the test inputs for real E-CPU NCB-003 host resolution, admission and Hypervisor execution.

This is a model-based *development* benchmark. It is not a training loop, self-modifying agent, autonomous code-writing model, or claim of physical acceleration.

## What is directly used

NCP-002 already accepts a `CoupledBrief` containing finite factor state spaces, possible operation effects, goals, shared resource capacities and forbidden joint states. It synthesizes rank-optimal guaranteed policies under adversarial outcomes and selects a complete implementation at a mixed-radix controller coordinate.

This experiment constructs two **real test-generation source families**:

1. **Shared-capacity system:** two 3-state components, one shared `advance` resource of capacity 1, starting state (2,2), terminal (0,0).
2. **Joint-safety system:** the same components and capacity, but with joint state (1,1) explicitly forbidden.

For each source, the benchmark selects up to four valid processor coordinates: 0, 1, the middle of the controller family and the final valid controller index (deduplicated). It independently verifies every generated processor with both the producer's existing NCP-002 checker and E-CPU's *separately implemented* `verify_coupled_controller`.

**Test cases are derived, not hand-authored:** for each controller, it examines *every certified winning nonterminal joint state*, asks the constructed processor which joint operation must be performed, derives its permitted successor set, then has E-CPU's actual host/catalogue/Hypervisor execute the selected actions. The observed output must equal the fixed tiny `advance/hold` reference and belong to the independently reconstructed coupled successor relation. Every declared rank must descend.

This expands the fixed four-step trace in NCB-003 into source-generated regression coverage of many previously untested source states, processor instances, and different coupled safety contexts.

## Real native admission, not a simulated test executor

- The source repository is pinned at immutable commit `e607fd80c00630f6b31e4c86b9b5ee8faebda410` and installed **separately** in every CI job. The E-CPU admission logic does not import the producer implementation.
- `_native` in the existing NCB-003 test fixture provisions **real E-CPU** `HeadlessOS`, admitted system seed, native `ComputationalHostCatalogue`, `ComputationalAddress`, `ComputationalExecutionAdmissionCoordinator`, `OperatorRegistry`, `VirtualLayerRuntime` and Hypervisor-authorized pure handlers.
- The test generator supplies `NativeResourceBinding('shared-actuator',1, ...)` **independently** of source construction. It never grants a source-declared new resource.
- A separate mathematically *valid* system requests capacity 2, while the current receiver only authorizes capacity 1. That execution is explicitly **refused before any handler call**.
- Positive cases require a real native execution receipt for every nonterminal selected local action, including verified observed outputs. This is not external side-effect publication: every operation is deterministic and pure.

## Measured cost categories

The executable records monotonic elapsed time per CI host for:

| Measurement | What is included |
| --- | --- |
| `construction_ns` | Actual NCP-002 source-to-controller construction for a source family |
| `producer_verification_ns` | Existing producer's separate semantic checker on the canonical construction |
| `receiver_verification_ns` | E-CPU's independent receipt and source-clause validation for each selected controller |
| `direct_reference_steps_ns` | Direct simple `advance/hold` operations without mathematical proof, routing or Hypervisor |
| `native_verified_steps_ns` | Native E-CPU resolution, admission, Hypervisor and receipt checks across all generated states |
| `packet_bytes` | The canonical NCP-002 controller certificate submitted to E-CPU |
| `native_handler_invocations` | Actual count of receiver-registered handler executions |
| `source_winning_states_tested` | Independently selected nonterminal source states for each controller |
| `total_suite_elapsed_ns` | All generator, checker, native execution and refusal work |

Construction and source verification measurements are repeated in records for controllers belonging to the same source family; **do not sum them** as if they were independently recomputed. Per-host monotonic clocks cannot be compared for distributed synchronization. There is **no measured energy**, no WAN transport, no separate trust domain and no claim that state-space navigation is cheaper than direct arithmetic. The point here is the engineering coverage and separate cost disclosure.

A JSON report binds all data with a canonical SHA-256. This is integrity evidence only, not a signature or independently witnessed measurement. Each matrix job uploads the complete report as a CI artifact; stdout contains the report as well.

## Acceptance and falsification

- Generated source Ground and *every selected architecture coordinate* independently verify.
- A positive native step can only be accepted when it is actually executed by the locally admitted Hypervisor and its result satisfies the generated possible-successor relation.
- The generated source-state count, processor-instance count, unique identity count and real native handler calls are recorded rather than implied.
- Two independently constructed geometries (with and without forbidden joint state) contribute cases.
- A valid mathematical design requiring unavailable local capacity is **refused before a handler call**; mathematical possibility does not create an actuator.
- Direct reference outcomes must agree with the verified native output for the narrowly declared arithmetic fixture.
- Existing NCB-003 native and execution-admission regression tests remain green.

## Reproduce

From E-CPU root with Python 3.11 or 3.13:

```shell
python -m pip install -e '.[dev]'
git clone https://github.com/Kier73/Navigable-Compute ncp-peer
cd ncp-peer && git checkout e607fd80c00630f6b31e4c86b9b5ee8faebda410 && cd ..
python -m pip install -e ./ncp-peer

python -m pytest -q tests/test_generated_controller_conformance.py tests/test_constructed_controller_admission.py
python scripts/ncb004_development_benchmark.py --max-instances 4 --output ncb004-measurement.json
```

Dedicated `.github/workflows/ncb004-development-benchmark.yml` tests the exact producer and receiver implementations on Linux/Windows with Python 3.11 and 3.13; it retains the evidence JSON for every CI worker.

## Why this is useful in development

Instead of writing one fixed test corresponding to a known successful demonstration, developers can describe additional resource couplings, illegal global states and possible effects to the *existing* mathematical constructor. It then produces new controller implementations and their action/state coverage, which can probe regression behavior of an independently implemented runtime.

A developer can use these cases when modifying the route resolver, Hypervisor, source checker, controller interpreter or resource bindings. The resulting discrepancies become concrete reproducible failing source packets and native receipts to debug; there is no need to invent expected outputs by intuition.

This is the first direct benchmark of **the system assisting with the development and verification of its own next iteration**, not a claim of autonomous software engineering. A future version should turn a discovered failure into a minimized counterexample and a proposed patch with an independently reviewed acceptance gate. It should also widen the fixed reference vocabulary and include process-separated authority tests, adversarial nonsmooth observations and real resource-side reservations.
