"""Direct real-VL-64 hosting tests: E-CPU M2 + native Hypervisor/Virtual Layer."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from mailcpu import (
    Capability,
    HeadlessOS,
    HypervisorAction,
    HypervisorPolicy,
    LexicalDecisionModel,
    OperatorRegistry,
    SystemIdentity,
    SystemSeed,
    SystemSeedEnvelope,
    VirtualBudget,
    VirtualGroundRef,
    VirtualLayerRuntime,
    VirtualLayerWorkload,
    VirtualOperatorRef,
)
from mailcpu.computational_host import (
    ComputationalBackendError,
    ComputationalHostReceipt,
    ComputationalHostRequest,
    LocalComputationalHost,
    register_computational_host_operator,
)
from mailcpu.headless_relation import compare_headless_os_states, observe_headless_os_state
from mailcpu.model import Instruction, Op, Program
from mailcpu.vl64_runtime import (
    VL64BackendAdapter,
    VL64_OPERATOR_ID,
    VL64_SOURCE_LIMIT,
    admit_vl64_runtime,
    vl64_backend_profile,
)

vld = pytest.importorskip("vld")


def _build_vm(index, manifest, root, profile):
    """Create independently booted native OS and bind a real vld M2 operator."""
    machine = HeadlessOS()
    machine.hypervisor.classifier = LexicalDecisionModel()
    machine.hypervisor.policy = HypervisorPolicy(embedding_review_confidence=1.0)
    identity = SystemIdentity(f"vl64-fleet-system-{index:03d}", 1)
    envelope = SystemSeedEnvelope(
        identity, "executor", "vl64-runtime-fleet", SystemSeed.from_system(machine)
    )
    assert machine.seed_admission.admit(envelope).accepted
    ground = VirtualGroundRef.from_envelope(envelope)
    adapter = VL64BackendAdapter()
    host = LocalComputationalHost(
        host_id=f"vl64-host-{index:03d}",
        manifest=manifest,
        artifact_root=root,
        profile=profile,
        adapter=adapter,
    )
    registry = OperatorRegistry()
    register_computational_host_operator(registry, host, operator_id=VL64_OPERATOR_ID)
    runtime = VirtualLayerRuntime(registry, f"vl64-node-{index:03d}", frozenset({"cpu"}))
    authority_pid = machine.environment.kernel.spawn(
        f"vl64-host-service-{index:03d}",
        capabilities=(Capability("/virtual-layer/operators", frozenset({"compute"})),),
        parent_pid=machine.environment.init_pid,
    )
    native_pid = machine.spawn(
        Program((
            Instruction(Op.SET, ("service_checks", 7)),
            Instruction(Op.SET, ("offset", -2)),
            Instruction(Op.ADD, ("service_checks", "service_checks", "offset")),
            Instruction(Op.HALT),
        )),
        f"vl64-native-supervisor-{index:03d}",
    )
    machine.run(max_ticks=10)
    assert machine.process(native_pid).status == "exited"
    assert machine.process(native_pid).registers["service_checks"] == 5
    return machine, identity, ground, runtime, authority_pid, host, adapter


def _execute(machine, identity, ground, runtime, pid, index, operation, input_value, sequence):
    """Use only E-CPU's real receiver-local Hypervisor authorization path."""
    workload = VirtualLayerWorkload(
        workload_id=f"vl64-vm{index:03d}-request{sequence:03d}",
        system=identity,
        ground=ground,
        intention={"goal": {"kind": "real-vl64-core-operation"}},
        operators=(VirtualOperatorRef(VL64_OPERATOR_ID, 1, "cpu"),),
        input_value={"operation": operation, "input": input_value},
        budget=VirtualBudget(
            max_energy=1_000_000,
            max_bytes=8192,
            max_virtual_ticks=1000,
        ),
        logical_time=sequence,
        eligible_nodes=(f"vl64-node-{index:03d}",),
        max_hops=2,
    )
    result = runtime.execute_operator(
        machine, pid, "vl64-controller", f"fleet-channel-{index:03d}",
        sequence, sequence, workload, VL64_OPERATOR_ID,
    )
    assert result.action is HypervisorAction.ALLOW
    assert result.executed is True
    effect = result.effect
    assert effect["kind"] == "virtual_layer.operator_result"
    evidence = effect["result"]
    receipt = ComputationalHostReceipt.from_dict(evidence["receipt"])
    assert receipt.host_id == f"vl64-host-{index:03d}"
    assert receipt.status == "EXECUTED"
    assert receipt.logical_time == sequence
    return evidence["output"], receipt


def test_real_vl64_core_is_admitted_and_hosted_under_e_cpu_hypervisor() -> None:
    """Exact real vld bytes, true Hypervisor capability, native OS journal and M2 receipts."""
    manifest, root = admit_vl64_runtime()
    assert manifest.total_size_bytes <= VL64_SOURCE_LIMIT
    assert len(manifest.components) >= 5
    assert all(item.path.endswith(".py") for item in manifest.components)
    assert manifest.metadata["version"] == vld.__version__
    profile = vl64_backend_profile(manifest)

    machine, identity, ground, runtime, pid, host, adapter = _build_vm(
        0, manifest, root, profile
    )
    args = {"a": 5, "b": 1, "x0": 3, "steps": 10**12, "modulus": 257}
    output, receipt = _execute(
        machine, identity, ground, runtime, pid, 0, "affine.navigate", args, 1,
    )
    assert output["result"]["value"] == vld.affine_navigate(5, 1, 3, 10**12, 257)
    assert output["operation"] == "affine.navigate"
    assert receipt.artifact_manifest_digest == manifest.manifest_digest
    assert receipt.backend_fingerprint == profile.fingerprint
    assert adapter.executions == 1 and host.is_loaded

    compiler_output, compiler_receipt = _execute(
        machine, identity, ground, runtime, pid, 0, "intention.realize", args, 2,
    )
    assert compiler_output["result"]["value"] == output["result"]["value"]
    assert compiler_output["result"]["selected_plan"] == "monoid_jump"
    assert compiler_receipt.input_digest != receipt.input_digest

    cycle, _ = _execute(
        machine, identity, ground, runtime, pid, 0,
        "ground.cycle", {"initial": 2, "steps": 10**12 + 3}, 3,
    )
    assert cycle["result"]["terminal_state"] == "01"
    assert cycle["result"]["skipped_steps"] > 0

    page, _ = _execute(
        machine, identity, ground, runtime, pid, 0,
        "page.cow", {"payload_hex": b"reverse-me".hex()}, 4,
    )
    assert page["result"]["isolated"]
    assert page["result"]["parent_digest"] != page["result"]["child_digest"]

    assert machine.environment.kernel.journal.verify()
    restored = HeadlessOS.from_snapshot(machine.snapshot())
    assert compare_headless_os_states(machine, restored).equivalent
    assert adapter.executions == 4
    host.unload()
    assert not host.is_loaded


def test_distinct_e_cpu_vms_run_distinct_real_vl64_host_instances() -> None:
    """Sixteen distinct OS schedulers, journals and native guest jobs host actual vld."""
    manifest, root = admit_vl64_runtime()
    profile = vl64_backend_profile(manifest)
    fleet = [_build_vm(i, manifest, root, profile) for i in range(16)]
    assert len({id(member[0]) for member in fleet}) == 16
    assert len({id(member[0].vm) for member in fleet}) == 16
    assert len({id(member[0].vm.scheduler) for member in fleet}) == 16
    assert len({id(member[0].environment.kernel) for member in fleet}) == 16
    assert len({id(member[0].environment.kernel.journal) for member in fleet}) == 16
    assert len({id(member[-1]) for member in fleet}) == 16

    for index, (machine, identity, ground, runtime, pid, host, adapter) in enumerate(fleet):
        args = {
            "a": 5, "b": (index + 1) % 257, "x0": index,
            "steps": 10**9 + index, "modulus": 257,
        }
        result, receipt = _execute(
            machine, identity, ground, runtime, pid, index, "affine.navigate", args, 1,
        )
        assert result["result"]["value"] == vld.affine_navigate(
            args["a"], args["b"], args["x0"], args["steps"], args["modulus"]
        )
        assert receipt.host_id == host.host_id
        assert machine.environment.kernel.journal.verify()
        assert compare_headless_os_states(
            machine, HeadlessOS.from_snapshot(machine.snapshot())
        ).equivalent
        assert adapter.executions == 1
        host.unload()


def test_unadmitted_vl64_operation_or_unauthorized_process_is_refused() -> None:
    """Host cannot run caller-selected Python and VM process cannot invent compute rights."""
    manifest, root = admit_vl64_runtime()
    profile = vl64_backend_profile(manifest)
    machine, identity, ground, runtime, pid, host, adapter = _build_vm(
        30, manifest, root, profile
    )
    with pytest.raises(ComputationalBackendError, match="catalogue"):
        host.execute(ComputationalHostRequest(
            request_id="unlisted",
            artifact_manifest_digest=manifest.manifest_digest,
            operation="python.eval",
            input_value={"source": "print('unsafe')"},
            logical_time=1,
            workload_id="test",
        ))
    assert adapter.executions == 0
    with pytest.raises(ComputationalBackendError, match="fields"):
        host.execute(ComputationalHostRequest(
            request_id="invalid",
            artifact_manifest_digest=manifest.manifest_digest,
            operation="affine.navigate",
            input_value={"a": 5, "b": 1, "x0": 0, "steps": 1, "modulus": 7, "code": "x"},
            logical_time=1,
            workload_id="test",
        ))
    no_rights_pid = machine.environment.kernel.spawn(
        "unprivileged-vl64-call", parent_pid=machine.environment.init_pid,
    )
    workload = VirtualLayerWorkload(
        workload_id="unprivileged-vl64-work",
        system=identity,
        ground=ground,
        intention={"goal": "compute"},
        operators=(VirtualOperatorRef(VL64_OPERATOR_ID, 1, "cpu"),),
        input_value={
            "operation": "affine.navigate",
            "input": {"a": 5, "b": 1, "x0": 3, "steps": 9, "modulus": 257},
        },
        budget=VirtualBudget(max_energy=100_000, max_bytes=8192, max_virtual_ticks=1000),
        logical_time=1,
        eligible_nodes=("vl64-node-030",),
        max_hops=2,
    )
    result = runtime.execute_operator(
        machine, no_rights_pid, "vl64-controller", "denied-channel",
        1, 1, workload, VL64_OPERATOR_ID,
    )
    assert not result.executed
    assert result.action is not HypervisorAction.ALLOW
    assert adapter.executions == 0
