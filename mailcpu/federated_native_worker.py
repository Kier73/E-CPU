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


def native_affine(
    request: dict[str, Any], *, authority_enabled: bool,
    approved_lens_grounds: frozenset[str] = frozenset(),
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Execute a pure affine or pinned lens transition through local Virtual Layer authority."""
    from . import (
        Capability, HeadlessOS, HypervisorAction, HypervisorPolicy, LexicalDecisionModel,
        OperatorRegistry, OperatorSpec, SystemIdentity, SystemSeed, SystemSeedEnvelope,
        VirtualBudget, VirtualGroundRef, VirtualLayerRuntime, VirtualLayerWorkload,
        VirtualOperatorRef,
    )
    from .law_certifier import lcg_navigate

    values = request["payload"]
    if request["operation"] == "lens64.navigate":
        from .lens_ground import navigate_lens
        from .structural_memory import (
            StructuralMemoryProposal, StructuralMemoryVerifier, StructuralNavigator,
        )

        if not isinstance(values, dict) or set(values) != {"proposal", "coordinate"}:
            raise ValueError("native lens request has invalid schema")
        t = values["coordinate"]
        if type(t) is not int or not 0 <= t <= 10**18:
            raise ValueError("native lens coordinate outside receiver budget")
        proposal = StructuralMemoryProposal.from_dict(values["proposal"])
        if proposal.spec.family != "lens64" or proposal.spec.digest not in approved_lens_grounds:
            raise ValueError("receiver has not allowed this exact lens Ground")
        StructuralMemoryVerifier().verify_proposal(proposal)
        observed, _context_digest = StructuralNavigator().read(
            proposal.spec, proposal.certificate, t, context=proposal.spec.context,
        )
        expected = {
            "value": observed,
            "spec_digest": proposal.spec.digest,
            "certificate_digest": proposal.certificate.digest,
        }
        operator_id = "sab005.lens64.navigate"
        description = "Receiver-pinned Structural Memory lens navigation"
        goal = "bounded-lens64-observation"
        compute = lambda x, workload: {
            "value": navigate_lens(proposal.spec.parameters, x["coordinate"]),
            "spec_digest": proposal.spec.digest,
            "certificate_digest": proposal.certificate.digest,
        }
    elif request["operation"] == "affine_mod":
        if (not isinstance(values, dict) or set(values) != {"a", "c", "mod", "x0", "coordinate"}
                or any(type(x) is not int for x in values.values())):
            raise ValueError("native operator payload has invalid schema")
        a, c, mod, x0, t = (values[k] for k in ("a", "c", "mod", "x0", "coordinate"))
        if not (2 <= mod <= 2**31 - 1 and all(0 <= x < mod for x in (a, c, x0)) and 0 <= t <= 10**18):
            raise ValueError("native affine input outside admitted domain")
        from .law_certifier import lcg_navigate
        expected = {"value": lcg_navigate(a, c, mod, x0, t)}
        operator_id = "sab005.affine_mod"
        description = "Native receiver-owned modular navigation"
        goal = "bounded-affine-observation"
        compute = lambda x, workload: {
            "value": lcg_navigate(x["a"], x["c"], x["mod"], x["x0"], x["coordinate"])
        }
    else:
        raise ValueError("native operation is not permitted")
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
        operator_id=operator_id,
        version=1,
        description=description,
        input_kind="object",
        output_kind="object",
        substrates=("cpu",),
        required_rights=frozenset({"compute"}),
        base_energy=8,
        energy_per_byte=1,
        max_input_bytes=8192 if request["operation"] == "lens64.navigate" else 4096,
        max_output_bytes=1024 if request["operation"] == "lens64.navigate" else 256,
        deterministic=True,
        effect_mode="pure",
    )
    registry = OperatorRegistry()
    registry.register(spec, compute)
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
        intention={"goal": goal},
        operators=(VirtualOperatorRef(operator_id, 1, "cpu"),),
        input_value=values,
        budget=VirtualBudget(10_000, 10_000, 1000),
        logical_time=17,
        eligible_nodes=("sab005-node",),
        max_hops=1,
    )
    outcome = runtime.execute_operator(
        operating_system, pid, "sab005.remote", "sab005.operation", 1, 17,
        workload, operator_id,
    )
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
                 allowed: frozenset[str], native_authority: bool = True,
                 approved_lens_grounds: frozenset[str] = frozenset()) -> dict[str, Any]:
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
    if operation not in {"affine_mod", "lens64.navigate"}:
        return fixed_worker(
            message, host_id=host_id, directory=directory, no_compute=True,
            no_storage=not {"retain", "retrieve"}.issubset(allowed),
            no_transfer="transfer" not in allowed,
        )
    result, evidence = native_affine(
        message, authority_enabled=native_authority,
        approved_lens_grounds=approved_lens_grounds,
    )
    # Keep the semantic result stable across process restarts. The first
    # accepted receiver audit pins its Hypervisor evidence for replay.
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
        if (old["host"] != audit["host"] or old["nonce"] != audit["nonce"]
                or old["request_digest"] != audit["request_digest"]
                or old["result"] != result):
            raise ValueError("conflicting native replay or local receipt")
        saved_evidence = old.get("receiver_evidence")
        if (not isinstance(saved_evidence, dict)
                or not isinstance(saved_evidence.get("hypervisor_receipt_digest"), str)
                or len(saved_evidence["hypervisor_receipt_digest"]) != 64):
            raise ValueError("persisted native audit is malformed")
        evidence = saved_evidence
    else:
        _write_atomic(path, audit)
    if operation == "lens64.navigate":
        result = {**result, "hypervisor_receipt_digest": evidence["hypervisor_receipt_digest"]}
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
    parser.add_argument("--allow-lens-ground", action="append", default=[])
    args = parser.parse_args(argv)
    try:
        raw = sys.stdin.buffer.readline(8193)
        if len(raw) > 8192 or not raw.endswith(b"\n"):
            return 2
        output = serve_native(
            json.loads(raw), host_id=args.host, directory=Path(args.directory),
            allowed=frozenset(args.allow), native_authority=not args.revoke_native,
            approved_lens_grounds=frozenset(args.allow_lens_ground),
        )
        sys.stdout.buffer.write(canonical(output) + b"\n")
        return 0
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
