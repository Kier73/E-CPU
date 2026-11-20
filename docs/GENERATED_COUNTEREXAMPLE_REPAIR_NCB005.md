# NCB-005 — A constructed system finds, minimizes and helps repair its interpreter's defect

**Status:** reproducible development-use experiment using the original NCP-002 mathematical constructor and E-CPU NCB-003/004 native admission/runtime. The counterexample was observed against E-CPU commit \`80ee5fc70fe97dac670fc57e84c903f85f3ae320\`, before the repair.

## Motivation

NCB-004 used intention-derived processors as a regression generator: six constructed processor instances, 46 generated winning-state cases and 68 real native \`VirtualLayerRuntime\` pure-handler calls across a four-platform GitHub Actions matrix. But generating only *valid* processor states can overlook incorrect admission of **invalid but value-equal representations**.

NCP-002 and E-CPU's own documentation already require **exact integer coordinates**, not Python-coerced values. A constructed system's action/identity must not change when it crosses observers or is serialized into a new representation. We used the constructor to hunt for an admission contradiction to this requirement, not to forecast a system trajectory.

## The actual red experiment

[Pre-repair red CI](https://github.com/Kier73/E-CPU/actions/runs/44824034666), using a separate pinned NCP-002 producer at \`e607fd80c00630f6b31e4c86b9b5ee8faebda410\`, independently reproduced three failures on Linux:

- The checked NCP-002 source packet \`world["states"]\` was compared against a regenerated integer basis with ordinary Python list equality. Substituting \`false\` for \`0\` or \`1.0\` for \`1\` and **recomputing the packet SHA-256** preserved the old value-equality result, while violating the mathematical integer-index requirement. The receiver mistakenly qualified the invalid typed packet.
- \`execute_constructed_action\` compared its receiver-provisioned native workload \`input_value\` dictionary against the source-bound request using ordinary equality. A Boolean or float in place of integer \`factor_index=1\` or \`source_state=1\` could pass its exact-binding gate. The receiver's pure native handler could still return the expected value, making a successful execution receipt insufficient to reveal the identity mismatch.
- \`CheckedCoupledController.next_action((...,True))\` or \`(...,1.0)\` could select the same state as integer coordinate \`1\`, again violating the declared exact integer observation domain.

**Recorded pre-repair test result: 3 failing new regression tests, 17 passing existing tests.** These failures were genuine admissions of invalid types, not expected rejections or a broken test harness.

## What is constructed and how the counterexample is reduced

The generator \`tests/generated_counterexample_probe.py\` starts with an actual NCP-002 \`CoupledGround.packet()\` produced from the same already-verified coupled component specification used in NCB-004. It does **not** invent a processor table or assert a trajectory.

It enumerates integer cells in the source-generated joint state enumeration that can be replaced by Python's value-equal but type-distinct JSON Boolean/float forms. It deliberately begins with **three disjoint changed state cells**.

An independent simple oracle, \`exact_type_oracle\`, requires the source packet's state coordinates to be exact Python \`int\` values after parsing JSON. Another explicit predicate models the old receiver's equality comparison. The generator then repeatedly removes a mutation if the legacy receiver would still accept the table but the independent type oracle refuses.

The result has **one changed state cell**. Removing that last change recovers the unmodified, independently accepted NCP-002 certificate. Both forms have well-formed SHA-256 content digests; digest recomputation cannot make a bool/float an integer. This is *deletion-minimal under the chosen edit grammar*, not a global minimum among all possible malformed packets.

The second counterexample set is derived from a certified state where the source-selected processor actually executes factor 1 with local state 1. The generator changes exactly one field in the *receiver's native* \`ComputationalAddress.workload.input_value\` while leaving the source Ground, operator identity and binding otherwise unchanged. Four cases test \`True\` and \`1.0\` substitutions in both \`source_state\` and \`factor_index\`. These are independently valid JSON values but **invalid program input identities**.

## Corrective change

The repair changes **only the interpretation/admission boundary**:

1. Validate each untrusted source state-table coordinate with the existing receiver's \`_coord\` helper, enforcing exact non-Boolean integer type and bounds before comparing to its independently reconstructed mathematical state basis.
2. Require each observer-supplied \`next_action\` coordinate to be a tuple of exact integers, with source-matching arity and membership.
3. Compare native \`input_value\` to the source-bound expected action by **canonical JSON bytes**. \`true\`, \`1.0\` and \`1\` have different encodings, even when Python's generic object equality would consider them equal.

No new code-generation privilege, Hypervisor permission, authority token, network scheme or external effect is added. The runtime still uses the existing \`ComputationalHostCatalogue\`, exact \`ComputationalAddress\`, receiver-owned \`NativeResourceBinding\`, \`ComputationalExecutionAdmissionCoordinator\` and original Hypervisor.

## Falsification and control cases

The repair is qualified only if:

- the **original genuine** NCP-002 packet continues to verify and execute through native E-CPU;
- the rehashed minimized invalid source packet is **refused**;
- all four typed native-workload substitutions are **refused before any handler invocation**;
- Boolean and float current-state coordinates are **refused** even when numerically equal to allowed integers;
- the existing complete NCB-003 checks and NCB-004 source-generated development regressions remain green, including correct refusal of mathematically valid but locally unsupported resource capacity.

The CI runner separately checks out exactly the original NCP-002 producer source and provides the E-CPU implementation under test. It runs Linux/Windows Python 3.11/3.13 and retains per-host \`ncb005-repair-evidence.json\` with minimized source mutation path, source hashes, admitted/refused status, native regression receipts and measured local elapsed time. A content hash binds the resulting **report bytes**, not the identity of the host or the authenticity of physical observations.

## Reproduction

From E-CPU root, install the normal E-CPU development requirements and the separately pinned NCP-002 producer:

\`\`\`sh
python -m pip install -e '.[dev]'
git clone https://github.com/Kier73/Navigable-Compute ncp-peer
cd ncp-peer && git checkout e607fd80c00630f6b31e4c86b9b5ee8faebda410 && cd ..
python -m pip install -e ./ncp-peer
python -m pytest -q tests/test_generated_counterexample_repair.py tests/test_constructed_controller_admission.py tests/test_generated_controller_conformance.py tests/test_computational_execution.py
python scripts/ncb005_counterexample_benchmark.py --output ncb005-repair-evidence.json
\`\`\`

For before-and-after comparison, the original failing native code is in \`80ee5fc70fe97dac670fc57e84c903f85f3ae320\`; the initial *red* GitHub Actions job retains the exact three observed test failures. The corrected revision must pass the full four-job matrix before merging.

## What was and was not achieved

This is a direct demonstration of **using the constructed computational space to assist in the development and testing of its own receiving interpreter**:

**Intention → constructed mathematical model → source-selected test inputs → observed contradiction → counterexample reduction → targeted implementation correction → independent positive and negative verification.**

The current generator explores one narrow, intentionally defined family of representation-level faults; it did not autonomously discover the entire class of bugs or construct the code repair without developer interpretation. Its minimality is relative to dropping the three generated edits. It does not certify arbitrary JSON inputs, prove overall E-CPU safety, act on external systems, or authorize shared capacity under concurrent effectful load.

Future work: build structure-aware mutation operators from all invariant-preserving coordinate representations, automatically persist and replay minimized counterexample witnesses across releases, independently validate candidate repairs against broader generated operators, and add concurrency/receiver-barrier probes for real shared effects.
