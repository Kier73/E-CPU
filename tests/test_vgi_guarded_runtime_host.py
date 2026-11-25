"""Execute merged certified VGI code through real E-CPU Hypervisor and OS processes."""
from __future__ import annotations

from copy import deepcopy
import json
import subprocess
import sys

import pytest

pytest.importorskip("vgi.guarded_reduction")
from vgi.symbolic_reduction import AffineAction
from vgi.guarded_reduction import (
    GuardedAction, GuardedGround, discover_guarded_reduction,
    admit_guarded_reduction, verify_guarded_receipt, plan_migration,
    observe_migration_probes,
)
from mailcpu import (
    Capability, HeadlessOS, HypervisorAction, HypervisorPolicy,
    LexicalDecisionModel, OperatorRegistry, SystemIdentity, SystemSeed,
    SystemSeedEnvelope, VirtualBudget, VirtualGroundRef, VirtualLayerRuntime,
    VirtualLayerWorkload, VirtualOperatorRef,
)
from mailcpu.computational_host import (
    ComputationalBackendError, ComputationalHostReceipt, ComputationalHostRequest,
    LocalComputationalHost, register_computational_host_operator,
)
from mailcpu.model import Instruction, Op, Program
from mailcpu.vgi_guarded_runtime import (
    VGI_GUARDED_OPERATOR_ID, VGI_SOURCE_COMMIT, VGIGuardedBackendAdapter,
    admit_vgi_guarded_runtime, vgi_guarded_backend_profile,
)
from mailcpu.vgi_guarded_worker import WORKER_SCHEMA


def _identity(n):
    return tuple(tuple(int(i == j) for j in range(n)) for i in range(n))


def _sources(n=64):
    direction = (0, 1) + (0,) * (n-2)
    inc = (1,) + (0,) * (n-1)
    act = GuardedAction(
        "tick", direction, 1,
        AffineAction("tick", _identity(n), inc),
        AffineAction("tick", _identity(n), (0,) * n),
    )
    first = (1,) + (0,) * (n-1)
    second = (0, 0, 1) + (0,) * (n-3)
    old = GuardedGround(2, n, (act,), (first,), (0,))
    new = GuardedGround(2, n, (act,), (first, second), (0, 0))
    return old, new


def _vm():
    manifest, root = admit_vgi_guarded_runtime()
    assert manifest.metadata["source_commit"] == VGI_SOURCE_COMMIT
    assert {"guarded_reduction.py", "symbolic_reduction.py"} <= {c.path for c in manifest.components}
    profile = vgi_guarded_backend_profile(manifest)
    adapter = VGIGuardedBackendAdapter()
    host = LocalComputationalHost(
        host_id="vgi-guarded-host", manifest=manifest, artifact_root=root,
        profile=profile, adapter=adapter,
    )
    registry = OperatorRegistry()
    register_computational_host_operator(registry, host, operator_id=VGI_GUARDED_OPERATOR_ID)
    runtime = VirtualLayerRuntime(registry, "vgi-guarded-receiver", frozenset({"cpu"}))
    machine = HeadlessOS()
    machine.hypervisor.classifier = LexicalDecisionModel()
    machine.hypervisor.policy = HypervisorPolicy(embedding_review_confidence=1.0)
    identity = SystemIdentity("vgi-guarded-e-cpu", 1)
    envelope = SystemSeedEnvelope(identity, "executor", "vgi-guarded-receiver", SystemSeed.from_system(machine))
    assert machine.seed_admission.admit(envelope).accepted
    ground = VirtualGroundRef.from_envelope(envelope)
    pid = machine.environment.kernel.spawn(
        "vgi-guarded-service",
        capabilities=(Capability("/virtual-layer/operators", frozenset({"compute"})),),
        parent_pid=machine.environment.init_pid,
    )
    native_pid = machine.spawn(Program((
        Instruction(Op.SET, ("check", 7)),
        Instruction(Op.SET, ("delta", -2)),
        Instruction(Op.ADD, ("check", "check", "delta")),
        Instruction(Op.HALT),
    )), "vgi-native-controller")
    machine.run(max_ticks=10)
    assert machine.process(native_pid).registers["check"] == 5
    return machine, identity, ground, runtime, pid, host, adapter


def _request(vm, operation, data, sequence, *, pid=None):
    machine, identity, ground, runtime, admitted_pid, _, _ = vm
    workload = VirtualLayerWorkload(
        workload_id=f"vgi-ground-{sequence:03d}", system=identity, ground=ground,
        intention={"goal": "execute certified guarded transition"},
        operators=(VirtualOperatorRef(VGI_GUARDED_OPERATOR_ID, 1, "cpu"),),
        input_value={"operation": operation, "input": data},
        budget=VirtualBudget(max_energy=4_194_304, max_bytes=1_048_576, max_virtual_ticks=1000),
        logical_time=sequence, eligible_nodes=("vgi-guarded-receiver",), max_hops=2,
    )
    return runtime.execute_operator(
        machine, admitted_pid if pid is None else pid, "vgi-guarded-controller",
        "vgi-guarded-channel", sequence, sequence,
        workload, VGI_GUARDED_OPERATOR_ID,
    )


def test_e_cpu_executes_certified_vgi_under_hypervisor_and_rejects_unprivileged_process():
    old, _ = _sources(64)
    cert = discover_guarded_reduction(old)
    q = admit_guarded_reduction(old, cert)
    source_state = (0, 1, 0) + (0,) * 61
    vm = _vm()
    result = _request(vm, "guarded.advance", {
        "source": old.to_dict(), "certificate": cert,
        "initial": list(q.project(source_state)), "inputs": ["tick"] * 11,
    }, 1)
    assert result.action is HypervisorAction.ALLOW and result.executed is True
    output = result.effect["result"]
    receipt = ComputationalHostReceipt.from_dict(output["receipt"])
    actual = output["output"]["result"]
    assert verify_guarded_receipt(q, actual["execution_receipt"])["steps"] == 11
    assert receipt.artifact_manifest_digest == vm[5].manifest.manifest_digest
    assert receipt.backend_fingerprint == vm[5].profile.fingerprint
    assert vm[6].executions == 1 and vm[0].environment.kernel.journal.verify()
    hidden = vm[0].environment.kernel.spawn("unprivileged-guest",parent_pid=vm[0].environment.init_pid)
    denied = _request(vm, "guarded.advance", {
        "source": old.to_dict(), "certificate": cert,
        "initial": list(q.project(source_state)), "inputs": ["tick"],
    }, 2, pid=hidden)
    assert not denied.executed and denied.action is not HypervisorAction.ALLOW
    assert vm[6].executions == 1


def _child(operation, input_value, logical_time):
    request = {"schema": WORKER_SCHEMA, "workload_id": f"guarded-run-{logical_time}",
               "logical_time": logical_time, "request": {"operation": operation, "input": input_value}}
    process = subprocess.run(
        [sys.executable, "-m", "mailcpu.vgi_guarded_worker"],
        input=json.dumps(request), text=True, capture_output=True,
        check=False, timeout=35,
    )
    assert process.returncode == 0, process.stderr
    result = json.loads(process.stdout)
    assert result["journal_verified"] is True
    assert result["native_process"] == {"status": "exited", "register_validation": 5}
    return result


def test_separate_real_e_cpu_processes_continue_ground_and_migrate_one_probe():
    old, new = _sources(80)
    cert_old, cert_new = discover_guarded_reduction(old), discover_guarded_reduction(new)
    q_old = admit_guarded_reduction(old, cert_old)
    q_new = admit_guarded_reduction(new, cert_new)
    x = (0, 1, 1) + (0,) * 77
    first = _child("guarded.advance", {
        "source": old.to_dict(), "certificate": cert_old,
        "initial": list(q_old.project(x)), "inputs": ["tick"] * 16,
    }, 1)
    host_receipt = ComputationalHostReceipt.from_dict(first["m2_receipt"])
    assert host_receipt.status == "EXECUTED"
    body = first["vgi"]["result"]
    assert verify_guarded_receipt(q_old, body["execution_receipt"])["steps"] == 16
    assert q_old.dimension == 2
    for _ in range(16): x = old.step(x, "tick")
    plan = plan_migration(q_old, q_new)
    assert plan.probe_count == 1
    probes = observe_migration_probes(new, x, q_new, plan)
    migrated = _child("guarded.migrate", {
        "old_source": old.to_dict(), "old_certificate": cert_old,
        "new_source": new.to_dict(), "new_certificate": cert_new,
        "previous_receipt": body["execution_receipt"], "probe_values": list(probes),
    }, 2)
    result = migrated["vgi"]["result"]
    assert result["required_probes"] == 1
    assert result["probe_authority"] == "CALLER_SUPPLIED_NOT_ATTESTED"
    assert result["final"] == list(q_new.project(x))
    resumed = _child("guarded.advance", {
        "source": new.to_dict(), "certificate": cert_new,
        "initial": result["final"], "inputs": ["tick"] * 7,
    }, 3)
    for _ in range(7): x = new.step(x, "tick")
    assert resumed["vgi"]["result"]["final"] == list(q_new.project(x))
    assert first["m2_receipt"]["request_id"] != resumed["m2_receipt"]["request_id"]


def test_forged_certificate_and_arbitrary_python_are_not_executable():
    src, _ = _sources(16)
    cert = discover_guarded_reduction(src)
    q = admit_guarded_reduction(src, cert)
    vm = _vm()
    manifest = vm[5].manifest
    invalid = deepcopy(cert)
    invalid["actions"][0]["on_true"]["offset"][0] ^= 1
    for operation, data in (
        ("guarded.advance", {"source": src.to_dict(), "certificate": invalid,
                             "initial": list(q.project((0,) * 16)), "inputs": ["tick"]}),
        ("python.eval", {"source": "print('never executed')"}),
    ):
        with pytest.raises(ComputationalBackendError):
            vm[5].execute(ComputationalHostRequest(
                request_id="attempt", artifact_manifest_digest=manifest.manifest_digest,
                operation=operation, input_value=data, logical_time=1,
            ))
    assert vm[6].executions == 0


def test_immense_invariant_jump_via_e_cpu_child_process():
    stable = GuardedAction("tick", (1,), 0,
        AffineAction("tick", ((1,),), (0,)),
        AffineAction("tick", ((1,),), (1,)))
    src = GuardedGround(5, 1, (stable,), ((1,),), (0,))
    cert = discover_guarded_reduction(src)
    output = _child("guarded.jump", {
        "source": src.to_dict(), "certificate": cert,
        "initial": [0], "symbol": "tick", "steps": str(10**100),
    }, 7)
    assert output["vgi"]["result"]["final"] == [0]
    assert output["vgi"]["result"]["steps"] == str(10**100)
