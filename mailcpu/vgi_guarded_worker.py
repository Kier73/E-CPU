"""Real child-process E-CPU VM hosting receiver-pinned VGI guarded execution.

stdin is a data-only JSON workload. This module owns the HeadlessOS,
capability-bearing process, M2 source artifact, and admitted VGI handlers.
One invocation is one isolated receiver process; continuation is explicitly
receipt-carried until a durable M3 session is integrated.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping

from . import (
    Capability, HeadlessOS, HypervisorAction, HypervisorPolicy, LexicalDecisionModel,
    SystemIdentity, SystemSeed, SystemSeedEnvelope,
    VirtualBudget, VirtualGroundRef, VirtualLayerRuntime,
    VirtualLayerWorkload, VirtualOperatorRef, OperatorRegistry,
)
from .computational_host import LocalComputationalHost, register_computational_host_operator
from .model import Instruction, Op, Program
from .vgi_guarded_runtime import (
    VGI_GUARDED_OPERATOR_ID, VGI_GUARDED_PROTOCOL,
    VGIGuardedBackendAdapter, admit_vgi_guarded_runtime,
    vgi_guarded_backend_profile,
)

WORKER_SCHEMA = "mailcpu.vgi-guarded-worker.v1"
MAX_WIRE_BYTES = 1_048_576
NODE = "vgi-guarded-receiver"


def execute_one_shot(payload: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(payload, Mapping) or set(payload) != {"schema", "workload_id", "logical_time", "request"}:
        raise ValueError("worker envelope fields differ")
    if payload["schema"] != WORKER_SCHEMA:
        raise ValueError("worker schema differs")
    request = payload["request"]
    if not isinstance(request, Mapping) or set(request) != {"operation", "input"}:
        raise ValueError("worker request fields differ")
    operation = request["operation"]
    if operation not in ("guarded.advance", "guarded.migrate", "guarded.jump"):
        raise ValueError("operation is not in the admitted VGI catalogue")
    logical_time = payload["logical_time"]
    if type(logical_time) is not int or not 0 <= logical_time <= 1_000_000:
        raise ValueError("logical_time outside finite worker bounds")
    workload_id = payload["workload_id"]
    if type(workload_id) is not str or not 1 <= len(workload_id) <= 80 or not all(
        c.isascii() and (c.isalnum() or c in "-_.:") for c in workload_id
    ):
        raise ValueError("workload_id is invalid")

    manifest, root = admit_vgi_guarded_runtime()
    profile = vgi_guarded_backend_profile(manifest)
    host = LocalComputationalHost(
        host_id="vgi-guarded-host", manifest=manifest, artifact_root=root,
        profile=profile, adapter=VGIGuardedBackendAdapter(),
    )
    registry = OperatorRegistry()
    register_computational_host_operator(registry, host, operator_id=VGI_GUARDED_OPERATOR_ID)
    runtime = VirtualLayerRuntime(registry, NODE, frozenset({"cpu"}))

    machine = HeadlessOS()
    machine.hypervisor.classifier = LexicalDecisionModel()
    machine.hypervisor.policy = HypervisorPolicy(embedding_review_confidence=1.0)
    identity = SystemIdentity("vgi-guarded-e-cpu", 1)
    envelope = SystemSeedEnvelope(
        identity, "executor", "vgi-guarded-worker", SystemSeed.from_system(machine),
    )
    if not machine.seed_admission.admit(envelope).accepted:
        raise RuntimeError("receiver system seed admission refused")
    ground = VirtualGroundRef.from_envelope(envelope)
    receiver_pid = machine.environment.kernel.spawn(
        "vgi-guarded-host-service",
        capabilities=(Capability("/virtual-layer/operators", frozenset({"compute"})),),
        parent_pid=machine.environment.init_pid,
    )
    native_pid = machine.spawn(
        Program((
            Instruction(Op.SET, ("validation", 7)),
            Instruction(Op.SET, ("delta", -2)),
            Instruction(Op.ADD, ("validation", "validation", "delta")),
            Instruction(Op.HALT),
        )),
        "vgi-guarded-native-supervisor",
    )
    machine.run(max_ticks=10)
    native = machine.process(native_pid)
    if native.status != "exited" or native.registers["validation"] != 5:
        raise RuntimeError("native E-CPU supervisor failed")

    workload = VirtualLayerWorkload(
        workload_id=workload_id, system=identity, ground=ground,
        intention={"goal": {"kind": "certified-guarded-process-execution"}},
        operators=(VirtualOperatorRef(VGI_GUARDED_OPERATOR_ID, 1, "cpu"),),
        input_value={"operation": operation, "input": request["input"]},
        budget=VirtualBudget(max_energy=4_194_304, max_bytes=1_048_576, max_virtual_ticks=1000),
        logical_time=logical_time, eligible_nodes=(NODE,), max_hops=2,
    )
    decision = runtime.execute_operator(
        machine, receiver_pid, "vgi-guarded-controller", "vgi-guarded-channel",
        logical_time + 1, logical_time + 1, workload, VGI_GUARDED_OPERATOR_ID,
    )
    if decision.action is not HypervisorAction.ALLOW or decision.executed is not True:
        raise RuntimeError("E-CPU Hypervisor did not authorize VGI execution")
    result = decision.effect["result"]
    if result["output"]["schema"] != VGI_GUARDED_PROTOCOL:
        raise RuntimeError("VGI M2 receiver returned an unknown protocol")
    return {"schema": WORKER_SCHEMA, "workload_id": workload_id,
            "native_process": {"status": native.status, "register_validation": native.registers["validation"]},
            "m2_receipt": result["receipt"], "vgi": result["output"],
            "journal_verified": machine.environment.kernel.journal.verify()}


def main() -> None:
    parser = argparse.ArgumentParser(description="One-shot E-CPU VGI guarded host (data-only)")
    parser.parse_args()
    try:
        raw = sys.stdin.buffer.read(MAX_WIRE_BYTES + 1)
        if len(raw) > MAX_WIRE_BYTES:
            raise ValueError("worker request exceeds byte ceiling")
        data = json.loads(raw.decode("utf-8"))
        result = execute_one_shot(data)
        sys.stdout.write(json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n")
    except (ValueError, TypeError, RuntimeError, KeyError) as exc:
        sys.stderr.write(f"vgi-guarded-worker: {exc}\n")
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
