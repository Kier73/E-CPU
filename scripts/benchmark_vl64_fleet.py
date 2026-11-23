#!/usr/bin/env python3
"""Measure actual VL-64 runtimes under independently booted E-CPU VM supervisors.

Each admitted VM lives in its own real subprocess, loads the pinned VL-64
package and E-CPU M2 host, and runs through the native Hypervisor capability
gate. The parent enforces a declared guest-page capacity and concurrent
process ceiling. This is *observer-hosted Python* paired with a native MailCPU
OS, not Python bytecode running on MailCPU opcodes, nor a memory-isolated
hypervisor for foreign guest kernels.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
from time import perf_counter_ns
from typing import Any

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
    ComputationalHostReceipt,
    LocalComputationalHost,
    register_computational_host_operator,
)
from mailcpu.headless_relation import compare_headless_os_states, observe_headless_os_state
from mailcpu.model import Instruction, Op, Program
from mailcpu.vl64_runtime import (
    VL64BackendAdapter, VL64_OPERATOR_ID, admit_vl64_runtime, vl64_backend_profile,
)

PAGE_SIZE = 4096
REPORT_SCHEMA = "mailcpu.vl64-hosted-fleet-benchmark.v1"
PYTHON = sys.executable


def _linux_rss_bytes() -> int | None:
    """Measure actual Python process resident bytes when Linux procfs is available."""
    if not sys.platform.startswith("linux"):
        return None
    try:
        with open("/proc/self/statm", "r", encoding="ascii") as source:
            pages = int(source.read().split()[1])
        return pages * int(os.sysconf("SC_PAGE_SIZE"))
    except (OSError, ValueError, IndexError):
        return None


def _canonical(value: object) -> bytes:
    """Make deterministic receipt bytes independent of display formatting."""
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _worker_case(index: int) -> dict[str, Any]:
    """Construct and execute one complete VM/OS plus genuine vld host process."""
    started = perf_counter_ns()
    manifest, source_root = admit_vl64_runtime()
    profile = vl64_backend_profile(manifest)

    operating_system = HeadlessOS(max_resident_pages=2)
    native_pid = operating_system.spawn(
        Program((
            Instruction(Op.SET, ("heartbeat", 9)),
            Instruction(Op.SET, ("delta", -4)),
            Instruction(Op.ADD, ("heartbeat", "heartbeat", "delta")),
            Instruction(Op.HALT),
        )),
        f"vl64-vm-supervisor-{index}",
        max_pages=2,
    )
    guest_memory = operating_system.vm.memories[native_pid]
    guest_memory.write(0, bytes([index & 255]) * (PAGE_SIZE * 2))
    if operating_system.vm.resident_pages() != 2:
        raise RuntimeError("native VM guest-page admission differs from expected budget")
    operating_system.run(max_ticks=10)
    native = operating_system.process(native_pid)
    if native.status != "exited" or native.registers["heartbeat"] != 5:
        raise RuntimeError("native MailCPU scheduler did not execute its supervisor program")

    operating_system.hypervisor.classifier = LexicalDecisionModel()
    operating_system.hypervisor.policy = HypervisorPolicy(embedding_review_confidence=1.0)
    identity = SystemIdentity(f"vl64-vm-fleet-{index:06d}", 1)
    seed = SystemSeedEnvelope(
        identity, "executor", "vl64-fleet", SystemSeed.from_system(operating_system),
    )
    if not operating_system.seed_admission.admit(seed).accepted:
        raise RuntimeError("native OS seed admission rejected VL-64 VM")
    ground = VirtualGroundRef.from_envelope(seed)
    host = LocalComputationalHost(
        host_id=f"vl64-fleet-host-{index:06d}",
        manifest=manifest,
        artifact_root=source_root,
        profile=profile,
        adapter=VL64BackendAdapter(),
    )
    catalogue = OperatorRegistry()
    register_computational_host_operator(catalogue, host, operator_id=VL64_OPERATOR_ID)
    runtime = VirtualLayerRuntime(
        catalogue, f"vl64-fleet-node-{index:06d}", frozenset({"cpu"}),
    )
    authorized_pid = operating_system.environment.kernel.spawn(
        "vl64-compute-service",
        capabilities=(Capability("/virtual-layer/operators", frozenset({"compute"})),),
        parent_pid=operating_system.environment.init_pid,
    )
    cases = (
        ("affine.navigate", {
            "a": 5, "b": index % 257, "x0": index % 257,
            "steps": 10**12 + index, "modulus": 257,
        }),
        ("intention.realize", {
            "a": 5, "b": index % 257, "x0": index % 257,
            "steps": 10**12 + index, "modulus": 257,
        }),
        ("ground.cycle", {"initial": index % 4, "steps": 10**12 + index}),
        ("page.cow", {"payload_hex": ("vl64-vm-%04d" % index).encode().hex()}),
        ("core.verify", {}),
        ("vm.nested", {"payload_hex": ("nested-vm-%04d" % index).encode().hex()}),
    )
    receipts = []
    outputs = []
    for sequence, (operation, arguments) in enumerate(cases, 1):
        workload = VirtualLayerWorkload(
            workload_id=f"vl64-vm-{index:06d}-op-{sequence}",
            system=identity,
            ground=ground,
            intention={"goal": {"operation": operation}},
            operators=(VirtualOperatorRef(VL64_OPERATOR_ID, 1, "cpu"),),
            input_value={"operation": operation, "input": arguments},
            budget=VirtualBudget(max_energy=1_000_000, max_bytes=8192, max_virtual_ticks=1000),
            logical_time=sequence,
            eligible_nodes=(f"vl64-fleet-node-{index:06d}",),
            max_hops=2,
        )
        execution = runtime.execute_operator(
            operating_system, authorized_pid, "fleet-controller",
            f"vl64-fleet-channel-{index:06d}", sequence, sequence,
            workload, VL64_OPERATOR_ID,
        )
        if execution.action is not HypervisorAction.ALLOW or not execution.executed:
            raise RuntimeError(f"Hypervisor rejected admitted VL-64 operation {operation}")
        effect = execution.effect
        if effect["kind"] != "virtual_layer.operator_result":
            raise RuntimeError("missing native Virtual Layer committed effect")
        inner = effect["result"]
        receipt = ComputationalHostReceipt.from_dict(inner["receipt"])
        if (receipt.host_id != host.host_id
            or receipt.artifact_manifest_digest != manifest.manifest_digest
            or receipt.backend_fingerprint != profile.fingerprint
            or receipt.status != "EXECUTED"):
            raise RuntimeError("M2 receipt identity differs from admitted VL-64 host")
        receipts.append(receipt.receipt_digest)
        outputs.append(inner["output"]["result"])

    # Check the actual VL-64 behavior against separate mathematical witnesses.
    if outputs[0]["value"] != outputs[1]["value"]:
        raise RuntimeError("VL-64 monoid interpreter and compiler disagree")
    if outputs[1]["selected_plan"] != "monoid_jump":
        raise RuntimeError("VL-64 compiler unexpectedly selected iterative execution")
    if outputs[2]["terminal_state"] != f"{((index % 4) + (10**12 + index)) % 4:02x}":
        raise RuntimeError("VL-64 observed cycle result is wrong")
    if not outputs[3]["isolated"]:
        raise RuntimeError("VL-64 PageSpace fork did not isolate its writes")
    if outputs[4]["status"] != "PASS" or outputs[4]["total_assertions"] != 5:
        raise RuntimeError("VL-64 complete core verification failed")
    if not outputs[5]["isolated"] or not outputs[5]["wx_refused"]:
        raise RuntimeError("nested real VL-64 HeadlessOS failed CoW or W^X protection")

    observed = observe_headless_os_state(operating_system)
    state = operating_system.snapshot()
    recovered = HeadlessOS.from_snapshot(state)
    if not compare_headless_os_states(operating_system, recovered).equivalent:
        raise RuntimeError("recovered OS state differs from live Hypervisor host")
    if recovered.vm.resident_pages() != 2:
        raise RuntimeError("restored guest-memory budget differs")
    if recovered.vm.memories[native_pid].read(0, 2 * PAGE_SIZE) != bytes([index & 255]) * (2 * PAGE_SIZE):
        raise RuntimeError("VM guest physical page data changed after checkpoint")
    if not recovered.environment.kernel.journal.verify():
        raise RuntimeError("quorum host OS journal hash chain is invalid")
    host.unload()
    return {
        "vm_index": index,
        "host_pid": os.getpid(),
        "artifact_manifest_digest": manifest.manifest_digest,
        "backend_fingerprint": profile.fingerprint,
        "os_observation_digest": observed.digest,
        "os_snapshot_bytes": len(_canonical(state)),
        "host_rss_bytes_at_completion": _linux_rss_bytes(),
        "vl64_source_bytes": manifest.total_size_bytes,
        "guest_resident_pages": recovered.vm.resident_pages(),
        "guest_resident_bytes": 2 * PAGE_SIZE,
        "native_supervisor_steps": native.steps,
        "vl64_operations": len(receipts),
        "operation_receipt_digests": receipts,
        "observed_affine_value": outputs[0]["value"],
        "observed_cycle_value": outputs[2]["terminal_state"],
        "journal_valid": True,
        "checkpoint_recovered": True,
        "elapsed_ns": perf_counter_ns() - started,
    }


def benchmark_case(
    vm_count: int,
    *,
    max_concurrent_processes: int = 8,
    max_total_resident_pages: int = 64,
) -> dict[str, Any]:
    """Run a process-isolated fleet with exact guest-page capacity and invariants."""
    if type(vm_count) is not int or vm_count <= 0 or vm_count > 256:
        raise ValueError("vm_count must be between 1 and 256")
    if type(max_concurrent_processes) is not int or not 1 <= max_concurrent_processes <= 64:
        raise ValueError("max_concurrent_processes must be between 1 and 64")
    if type(max_total_resident_pages) is not int or max_total_resident_pages < 2:
        raise ValueError("max_total_resident_pages must admit at least two pages")
    admitted = min(vm_count, max_total_resident_pages // 2)
    began = perf_counter_ns()
    script = str(Path(__file__).resolve())
    results: list[dict[str, Any]] = []

    def launch(index: int) -> dict[str, Any]:
        """Start a fresh Python interpreter; accept one valid exact JSON receipt."""
        child = subprocess.run(
            [PYTHON, script, "--worker", str(index)],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if child.returncode != 0:
            raise RuntimeError(f"VL-64 VM {index} failed: {child.stderr[-3000:]}")
        result = json.loads(child.stdout)
        if result.get("vm_index") != index:
            raise RuntimeError("VL-64 VM result has incorrect index")
        return result

    with ThreadPoolExecutor(max_workers=min(admitted, max_concurrent_processes)) as executor:
        futures = [executor.submit(launch, index) for index in range(admitted)]
        for future in as_completed(futures):
            results.append(future.result())
    results.sort(key=lambda item: item["vm_index"])
    identities = [item["os_observation_digest"] for item in results]
    all_valid = (
        len(results) == admitted
        and len(set(identities)) == admitted
        and len({item["host_pid"] for item in results}) == admitted
        and len({d for item in results for d in item["operation_receipt_digests"]}) == admitted * 6
        and all(item["guest_resident_pages"] == 2
                and item["vl64_operations"] == 6
                and item["checkpoint_recovered"]
                and item["journal_valid"]
                for item in results)
    )
    if not all_valid:
        raise RuntimeError("fleet isolation, receipt identity or checkpoint invariant failed")
    measured_rss = [value["host_rss_bytes_at_completion"] for value in results
                    if value["host_rss_bytes_at_completion"] is not None]
    return {
        "schema": REPORT_SCHEMA,
        "requested_vm_count": vm_count,
        "admitted_vm_count": admitted,
        "refused_vm_count": vm_count - admitted,
        "max_concurrent_host_processes": max_concurrent_processes,
        "max_total_resident_pages": max_total_resident_pages,
        "guest_resident_pages": admitted * 2,
        "guest_resident_bytes": admitted * 2 * PAGE_SIZE,
        "real_vl64_host_process_count": len({item["host_pid"] for item in results}),
        "vl64_operation_count": 6 * admitted,
        "all_vm_checks_passed": all_valid,
        "total_snapshot_bytes": sum(item["os_snapshot_bytes"] for item in results),
        "vl64_source_bytes_per_host": results[0]["vl64_source_bytes"] if results else 0,
        "host_rss_bytes_at_completion_min": min(measured_rss) if measured_rss else None,
        "host_rss_bytes_at_completion_mean": (sum(measured_rss) // len(measured_rss)) if measured_rss else None,
        "host_rss_bytes_at_completion_max": max(measured_rss) if measured_rss else None,
        "fleet_wall_ns": perf_counter_ns() - began,
        "vm_results": results,
    }


def main() -> None:
    """Select an isolated worker or an executable fleet-capacity measurement."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", type=int)
    parser.add_argument("--vm-count", type=int, default=16)
    parser.add_argument("--max-concurrent", type=int, default=8)
    parser.add_argument("--guest-page-budget", type=int, default=64)
    parser.add_argument("--output", type=Path)
    options = parser.parse_args()
    if options.worker is not None:
        result = _worker_case(options.worker)
    else:
        result = benchmark_case(
            options.vm_count,
            max_concurrent_processes=options.max_concurrent,
            max_total_resident_pages=options.guest_page_budget,
        )
    rendered = json.dumps(result, sort_keys=True, indent=2)
    if options.output is not None:
        options.output.parent.mkdir(parents=True, exist_ok=True)
        options.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
