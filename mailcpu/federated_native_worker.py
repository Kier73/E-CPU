"""SAB-005 receiver-side fixed-worker admission through native E-CPU Hypervisor."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import secrets
import sys
from typing import Any

from .runtime_qualification import REQUEST_KIND, RESPONSE_KIND, canonical, digest
from .runtime_qualification_worker import serve as fixed_worker, _write_atomic


def native_affine(request: dict[str, Any], *, authority_enabled: bool) -> tuple[dict[str, int], dict[str, Any]]:
    """Execute a pure affine transition only through local Virtual Layer authorization."""
    from . import (
        Capability, HeadlessOS, HypervisorAction, HypervisorPolicy, LexicalDecisionModel,
        OperatorRegistry, OperatorSpec, SystemIdentity, SystemSeed, SystemSeedEnvelope,
        VirtualBudget, VirtualGroundRef, VirtualLayerRuntime, VirtualLayerWorkload,
        VirtualOperatorRef,
    )
    from .law_certifier import lcg_navigate

    values = request["payload"]
    if (not isinstance(values, dict) or set(values) != {"a", "c", "mod", "x0", "coordinate"}
            or any(type(x) is not int for x in values.values())):
        raise ValueError("native operator payload has invalid schema")
    a, c, mod, x0, t = (values[k] for k in ("a", "c", "mod", "x0", "coordinate"))
    if not (2 <= mod <= 2**31 - 1 and all(0 <= x < mod for x in (a, c, x0)) and 0 <= t <= 10**18):
        raise ValueError("native affine input outside admitted domain")
    operating_system = HeadlessOS()
    operating_system.hypervisor.classifier = LexicalDecisionModel()
    operating_system.hypervisor.policy = HypervisorPolicy(embedding_review_confidence=1.0)
    identity = SystemIdentity("sab005-receiver", 1)
    envelope = SystemSeedEnvelope(
        identity, "sab005", "receiver-local", SystemSeed.from_system(operating_system)
    )
    if not operating_system.seed_admission.admit(envelope).accepted:
        raise ValueError("receiver system Ground admission refused")
    spec = OperatorSpec(
        operator_id="sab005.affine_mod",
        version=1,
        description="Native receiver-owned modular navigation",
        input_kind="object",
        output_kind="object",
        substrates=("cpu",),
        required_rights=frozenset({"compute"}),
        base_energy=8,
        energy_per_byte=1,
        max_input_bytes=4096,
        max_output_bytes=256,
        deterministic=True,
        effect_mode="pure",
    )
    registry = OperatorRegistry()
    registry.register(
        spec,
        lambda x, workload: {
            "value": lcg_navigate(x["a"], x["c"], x["mod"], x["x0"], x["coordinate"])
        },
    )
    runtime = VirtualLayerRuntime(registry, "sab005-node", frozenset({"cpu"}))
    capabilities = (
        Capability("/virtual-layer/operators", frozenset({"compute"})),
    ) if authority_enabled else ()
    pid = operating_system.environment.kernel.spawn(
        "sab005-receiver-worker",
        capabilities=capabilities,
        parent_pid=operating_system.environment.init_pid,
    )
    workload = VirtualLayerWorkload(
        workload_id="sab005-" + request["nonce"],
        system=identity,
        ground=VirtualGroundRef.from_envelope(envelope),
        intention={"goal": "bounded-affine-observation"},
        operators=(VirtualOperatorRef("sab005.affine_mod", 1, "cpu"),),
        input_value=values,
        budget=VirtualBudget(10_000, 10_000, 1000),
        logical_time=17,
        eligible_nodes=("sab005-node",),
        max_hops=1,
    )
    outcome = runtime.execute_operator(
        operating_system, pid, "sab005.remote", "sab005.operation", 1, 17,
        workload, "sab005.affine_mod",
    )
    expected = {"value": lcg_navigate(a, c, mod, x0, t)}
    if (outcome.action is not HypervisorAction.ALLOW or not outcome.executed
            or outcome.effect.get("kind") != "virtual_layer.operator_result"
            or outcome.effect.get("operator_contract_digest") != spec.digest
            or outcome.effect.get("result") != expected):
        raise ValueError("receiver Hypervisor refused or exact result verification failed")
    return expected, {
        "native_operator": spec.digest,
        "hypervisor_action": outcome.action.value,
        "executed": outcome.executed,
        "hypervisor_receipt_digest": digest(outcome.to_dict()),
    }


def serve_native(message: Any, *, host_id: str, directory: Path,
                 allowed: frozenset[str], native_authority: bool = True) -> dict[str, Any]:
    """Handle only locally granted operations; never accept remote source or capability."""
    if (not isinstance(message, dict)
            or set(message) != {"kind", "host", "nonce", "operation", "payload"}
            or message["kind"] != REQUEST_KIND or message["host"] != host_id
            or type(message["nonce"]) is not str or not 8 <= len(message["nonce"]) <= 64
            or type(message["operation"]) is not str or not isinstance(message["payload"], dict)):
        raise ValueError("native worker request schema or host mismatch")
    operation = message["operation"]
    if operation not in allowed:
        return {
            "kind": RESPONSE_KIND, "host": host_id, "nonce": message["nonce"],
            "boot": secrets.token_hex(16), "ok": False,
            "result": None, "error": "unsupported",
        }
    if operation != "affine_mod":
        return fixed_worker(
            message, host_id=host_id, directory=directory, no_compute=True,
            no_storage=not {"retain", "retrieve"}.issubset(allowed),
            no_transfer="transfer" not in allowed,
        )
    result, evidence = native_affine(message, authority_enabled=native_authority)
    audit_dir = directory / "native-receipts"
    audit_dir.mkdir(parents=True, exist_ok=True)
    audit = {
        "host": host_id, "nonce": message["nonce"],
        "request_digest": digest(message), "result": result,
        "receiver_evidence": evidence,
    }
    path = audit_dir / (
        digest({"host": host_id, "nonce": message["nonce"]}) + ".json"
    )
    if path.exists():
        old = json.loads(path.read_bytes())
        if (old["request_digest"] != audit["request_digest"]
                or old["result"] != result):
            raise ValueError("conflicting native replay or local receipt")
    else:
        _write_atomic(path, audit)
    return {
        "kind": RESPONSE_KIND, "host": host_id, "nonce": message["nonce"],
        "boot": secrets.token_hex(16), "ok": True,
        "result": result, "error": None,
    }


def main(argv: list[str] | None = None) -> int:
    """Run a single bounded request in an isolated, receiver-owned interpreter."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True)
    parser.add_argument("--directory", required=True)
    parser.add_argument("--allow", action="append", default=[])
    parser.add_argument("--revoke-native", action="store_true")
    args = parser.parse_args(argv)
    try:
        raw = sys.stdin.buffer.readline(8193)
        if len(raw) > 8192 or not raw.endswith(b"\n"):
            return 2
        output = serve_native(
            json.loads(raw), host_id=args.host, directory=Path(args.directory),
            allowed=frozenset(args.allow), native_authority=not args.revoke_native,
        )
        sys.stdout.buffer.write(canonical(output) + b"\n")
        return 0
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
