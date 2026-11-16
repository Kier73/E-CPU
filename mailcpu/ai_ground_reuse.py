"""AGA-002: evidence-directed reuse of E-CPU's existing computational Grounds.

This is a *proof-carrying selection adapter* for one deliberately finite family.
It does not create a new Hypervisor, execution engine, StructuralMemory law,
operator registration, or grant. The compiler, interpreters, observer receipts,
and semantics are existing E-CPU APIs.

The initial supported relation is {0,1}^2 -> {0,1}: XOR or AND, known to admit
both E-CPU neural realizations and a direct Boolean realization. A verified
finite-domain certificate permits the query layer to choose the simpler law.
No other AI Ground becomes executable merely by appearing in the atlas.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
from pathlib import Path
from typing import Any, Mapping

from .ai_ground_atlas import AtlasRefused, canonical, digest, find, load, representation_ref

SCHEMA = "mailcpu.ai-ground-reuse.boolean.v1"
CERTIFICATE_FIELDS = frozenset({
    "schema", "atlas_digest", "catalog_ground", "ground_identity", "finite_domain",
    "gate", "models", "source_program_digest", "observations", "comparison_policy",
    "evidence_level", "host_placement", "admission", "certificate_digest",
})
MODES = ("symbolic_ground", "weight_space_neural", "mailcpu_program")


class GroundReuseRefused(ValueError):
    """Missing Ground, unsupported semantics or evidence, or contradictory projection."""


def _require_gate(gate: Any) -> str:
    if gate not in ("xor", "and") or type(gate) is not str:
        raise GroundReuseRefused("only exact XOR/AND on two Boolean inputs is certified")
    return gate


def _bits(left: Any, right: Any) -> tuple[int, int]:
    if type(left) is not int or left not in (0, 1) or type(right) is not int or right not in (0, 1):
        raise GroundReuseRefused("queries are confined to the exhaustively verified Boolean domain")
    return left, right


def _seal(value: dict[str, Any], label: str) -> dict[str, Any]:
    sealed = dict(value)
    sealed[label] = digest(value)
    return sealed


def _check_receipt_shape(value: Any, required: frozenset[str], label: str) -> None:
    if not isinstance(value, Mapping) or set(value) != required:
        raise GroundReuseRefused(f"{label} has missing or extra fields")


def evaluate_direct(gate: str, left: int, right: int) -> int:
    """Direct exact semantic result, *not* a surrogate for general neural inference."""
    _require_gate(gate)
    left, right = _bits(left, right)
    return left ^ right if gate == "xor" else left & right


def inspection(catalog: Mapping[str, Any], target: str, *, gate: str | None = None) -> dict[str, Any]:
    """Resolve available proof recipes, never infer admission from source anchors."""
    entry = find(catalog, target)
    if gate is not None and not (target == "model.compile" and gate in ("xor", "and")):
        raise GroundReuseRefused("requested scoped realization is not known to the reuse registry")
    return {
        "target": target,
        "ground_description": representation_ref(catalog, target).to_dict(),
        "atlas_digest": catalog["catalog_digest"],
        "scope": "exact two-input Boolean gate" if gate is not None else None,
        "proven_reuse_recipe": "mailcpu.weight_space Boolean equivalence" if gate is not None else None,
        "execution_admitted": False,
        "status": "scope_requires_certification" if gate is not None else "no_general_execution_claim",
        "related_evidence": entry["realization_status"],
        "next_action": "certify known finite Ground and compare neural realizations" if gate is not None
            else "inspect admitted Ground, operator semantics and independent observation evidence",
    }


def certify_boolean(catalog: Mapping[str, Any], gate: str) -> dict[str, Any]:
    """Actually run two E-CPU neural architectures + two CPU interpreter paths.

    Four possible inputs exhaust the admitted finite domain. The certificate
    is *only* evidence of that finite semantic relation; it is not authority.
    """
    gate = _require_gate(gate)
    # An atlas entry is a *description*; reuse means selecting an existing
    # E-CPU implementation with a scoped proof, not granting arbitrary models.
    entry = find(catalog, "model.compile")
    if "ECPU:mailcpu/weight_space.py" not in entry["source_anchors"]:
        raise GroundReuseRefused("E-CPU native weight-space compiler source anchor is absent")
    from .weight_space import ARCHITECTURE, DEEP_ARCHITECTURE, compile_boolean_gate, boolean_gate_program
    from .interpreter import ReferenceInterpreter, QueueInterpreter
    from .semantic_translation import program_representation_ref

    program = boolean_gate_program(gate)
    models = [compile_boolean_gate(gate, architecture=a) for a in (ARCHITECTURE, DEEP_ARCHITECTURE)]
    model_proofs = [{
        "architecture": list(model.architecture), "parameters": model.parameter_count,
        "active_parameters": model.active_parameter_count, "weight_digest": model.digest,
    } for model in models]
    cases = []
    for left, right in itertools.product((0, 1), repeat=2):
        expected = evaluate_direct(gate, left, right)
        reference = ReferenceInterpreter(program).run(initial_registers={"a": left, "b": right})
        queued = QueueInterpreter(program).run(initial_registers={"a": left, "b": right})
        observed = [model.predict(left, right) for model in models]
        if (reference.status.value != "halted" or queued.status.value != "halted"
                or reference.state.registers.get("result") != expected
                or queued.state.registers.get("result") != expected or observed != [expected, expected]):
            raise GroundReuseRefused("existing E-CPU realizers disagree on an exhaustive-domain observation")
        cases.append({
            "input": [left, right], "expected": expected,
            "neural_outputs": observed,
            "reference_interpreter": reference.state.registers["result"],
            "queued_interpreter": queued.state.registers["result"],
        })
    if len(cases) != 4:
        raise GroundReuseRefused("finite domain coverage incomplete")
    certificate = {
        "schema": SCHEMA,
        "atlas_digest": catalog["catalog_digest"],
        "catalog_ground": "model.compile",
        "ground_identity": representation_ref(catalog, "model.compile").to_dict(),
        "finite_domain": "{0,1}^2",
        "gate": gate,
        "models": model_proofs,
        "source_program_digest": program_representation_ref(program).content_digest,
        "observations": cases,
        "comparison_policy": "exact integer equality over exhaustively enumerated Boolean domain",
        "evidence_level": "scoped_exhaustive_finite_observation",
        "host_placement": "not_part_of_ground_identity",
        "admission": "not_a_hypervisor_grant_or_general_ai_ground",
    }
    return _seal(certificate, "certificate_digest")


def verify_boolean(catalog: Mapping[str, Any], certificate: Mapping[str, Any]) -> dict[str, Any]:
    """Independently redo all bounded proofs, not merely validate a supplied hash."""
    _check_receipt_shape(certificate, CERTIFICATE_FIELDS, "certificate")
    if certificate["schema"] != SCHEMA or certificate["atlas_digest"] != catalog["catalog_digest"]:
        raise GroundReuseRefused("certificate schema or exact atlas identity differs")
    if certificate["certificate_digest"] != digest({k: v for k, v in certificate.items() if k != "certificate_digest"}):
        raise GroundReuseRefused("certificate content digest mismatch")
    expected = certify_boolean(catalog, certificate["gate"])
    if dict(certificate) != expected:
        raise GroundReuseRefused("certificate contradicts independently executed E-CPU reference realizations")
    return expected


class GroundReuseSession:
    """Verify the finite proof once; answer later observations without neural execution.

    In-memory caching is not a quorum checkpoint or a portable authorization.
    The certificate can be revalidated on each new host/process.
    """

    def __init__(self, catalog: Mapping[str, Any], certificate: Mapping[str, Any]):
        self.catalog = catalog
        self.certificate = verify_boolean(catalog, certificate)
        self.gate = self.certificate["gate"]

    def query(self, left: int, right: int, *, request_id: str) -> dict[str, Any]:
        left, right = _bits(left, right)
        if type(request_id) is not str or not request_id or len(request_id) > 128:
            raise GroundReuseRefused("request_id must be bounded nonempty text")
        # Native ObserverContract/ObserverReceipt preserve source, interpretation,
        # input, and evidence identities without issuing a capability grant.
        from .observer_orbit import ObserverContract, ObserverReceipt, verify_observer_receipt
        from .semantic_translation import ObservationContract, RepresentationRef, canonical_value_digest
        subject = representation_ref(self.catalog, "model.compile")
        interpretation = RepresentationRef.from_payload("mailcpu.boolean-semantic-ground", 1, {
            "gate": self.gate, "domain": "{0,1}^2", "function": "xor" if self.gate == "xor" else "and",
        })
        observer = ObserverContract(
            "ai-ground-reuse-observer", 1, subject, interpretation,
            ObservationContract.from_definition("mailcpu.boolean-ground.value", 1, {
                "fields": ["left", "right", "value"], "comparison": "exact", "domain": "{0,1}^2",
            }),
            canonical_value_digest({"certificate_digest": self.certificate["certificate_digest"],
                                    "atlas_digest": self.catalog["catalog_digest"]}),
        )
        value = evaluate_direct(self.gate, left, right)
        projection = {"left": left, "right": right, "value": value}
        receipt = ObserverReceipt.issue(
            observer, operation_id=request_id,
            input_digest=canonical_value_digest({"left": left, "right": right, "gate": self.gate}),
            projection_value=projection,
            evidence=(subject, interpretation),
        )
        if not verify_observer_receipt(observer, receipt):
            raise GroundReuseRefused("native observer refused Ground observation evidence")
        return {
            "schema": "mailcpu.ai-ground-reuse.observation.v1",
            "result": value,
            "method": "exact_direct_semantic_ground",
            "neural_forward_evaluations_this_query": 0,
            "verified_finite_domain": "{0,1}^2",
            "certificate_digest": self.certificate["certificate_digest"],
            "observer_contract": observer.to_dict(),
            "observer_receipt": receipt.to_dict(),
            "admission": "no_hypervisor_authority_granted",
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reuse a certified E-CPU Ground instead of replaying neural computation")
    parser.add_argument("action", choices=("inspect", "certify", "verify", "query"))
    parser.add_argument("target", nargs="?", help="Ground ID (inspect), or XOR/AND (certify)")
    parser.add_argument("--gate", choices=("xor", "and"), help="Scoped known Boolean semantic Ground")
    parser.add_argument("--certificate", type=Path, help="Certificate file for verify/query")
    parser.add_argument("--output", type=Path, help="Write the exact certificate as JSON")
    parser.add_argument("--left", type=int)
    parser.add_argument("--right", type=int)
    parser.add_argument("--request-id", default="ground-reuse-query-001")
    parser.add_argument("--catalog", type=Path, help="Select pinned catalog")
    args = parser.parse_args(argv)
    try:
        catalog = load(args.catalog)
        if args.action == "inspect":
            if args.target is None:
                raise GroundReuseRefused("inspect requires a catalog Ground ID")
            result = inspection(catalog, args.target, gate=args.gate)
        elif args.action == "certify":
            if args.target is None:
                raise GroundReuseRefused("certify requires a gate")
            result = certify_boolean(catalog, args.target)
            if args.output is not None:
                args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        else:
            if args.certificate is None:
                raise GroundReuseRefused("verify/query requires a certificate")
            value = json.loads(args.certificate.read_text(encoding="utf-8"))
            session = GroundReuseSession(catalog, value)
            if args.action == "verify":
                result = {"verified": True, "certificate_digest": session.certificate["certificate_digest"],
                          "scope": "exhaustive_finite_domain"}
            else:
                if args.left is None or args.right is None:
                    raise GroundReuseRefused("query requires --left and --right")
                result = session.query(args.left, args.right, request_id=args.request_id)
        print(json.dumps(result, sort_keys=True, indent=2))
        return 0
    except (AtlasRefused, GroundReuseRefused, OSError, ValueError) as exc:
        parser.exit(2, f"Ground reuse refused: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
