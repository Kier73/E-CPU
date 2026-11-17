"""LENS-003: quorum-recoverable lens navigation over E-CPU's native Fabric.

No new router, executor, authentication layer or recovery authority is defined.
A pre-admitted Structural Memory revision is bound through the existing Virtual
Layer input ABI. The receiver must own its law, Hypervisor rights and history.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Mapping

from .computational_resolver import ComputationalAddress
from .computational_fabric_forwarding import (
    ComputationalFabricForwardingEnvelope, ComputationalFabricHopReceipt,
)
from .federated_ground_continuity import (
    AtomicGroundEvidenceStore, GroundContinuityRefused, NativeGroundDispatcher,
    NativeRoutePlan, _verify_receipt_chain,
)
from .lens_native_fabric import independent_lens_value
from .recovery_lineage import (
    RecoveryLineageCoordinator, RecoveryLineageProof, RecoveryStateManifest,
)
from .runtime_qualification import canonical, digest
from .seed import SystemIdentity
from .structural_memory import (
    StructuralMemoryProposal, StructuralMemoryReadReceipt, StructuralMemoryVerifier,
    StructuralMemoryError,
)
from .virtual_layer import (
    OperatorSpec, VirtualBudget, VirtualGroundRef, VirtualLayerWorkload,
    VirtualOperatorRef, VirtualStructuralMemoryRef,
)

SCHEMA = "mailcpu.lens003.fabric-structural-ground-continuity.v1"
OPERATOR = "lens.fabric.read"
BINDING = "lens"
MAX_COORDINATE = 10**18


class LensFabricRefused(GroundContinuityRefused):
    """A topology, mathematical Ground, host permission or recovered receipt is invalid."""


def lens_fabric_spec() -> OperatorSpec:
    """Mathematics: declare the fixed pure receiver-side Structural Memory read contract."""
    return OperatorSpec(
        operator_id=OPERATOR, version=1,
        description="Read a pinned lens Structural Memory revision",
        input_kind="object", output_kind="object", substrates=("cpu",),
        required_rights=frozenset({"compute"}), base_energy=8,
        energy_per_byte=1, max_input_bytes=8192, max_output_bytes=256,
        deterministic=True, effect_mode="pure",
    )


def lens_fabric_handler(resolved_input: Mapping[str, Any], _workload: VirtualLayerWorkload) -> dict[str, int]:
    """Mathematics: project the receiver-authorized read value without reimplementing its law."""
    try:
        reference = _workload.operator_ref(OPERATOR)
        inline = resolved_input["input"]
        resolved = resolved_input["structural_memory"][BINDING]
        value, receipt = resolved["value"], resolved["receipt"]
    except (TypeError, KeyError, AttributeError) as exc:
        raise LensFabricRefused("receiver has not resolved the pinned Structural Memory binding") from exc
    if (len(reference.structural_memory) != 1
            or reference.structural_memory[0].binding != BINDING
            or not isinstance(inline, Mapping) or set(inline) != {"coordinate"}
            or type(inline["coordinate"]) is not int
            or inline["coordinate"] != reference.structural_memory[0].coordinate
            or not isinstance(receipt, Mapping)
            or receipt.get("coordinate") != inline["coordinate"]
            or receipt.get("spec_digest") != reference.structural_memory[0].spec_digest
            or receipt.get("certificate_digest") != reference.structural_memory[0].certificate_digest
            or type(value) is not int or receipt.get("value") != value):
        raise LensFabricRefused("receiver coordinate or resolved revision differs from pinned intention")
    return {"value": value}


@dataclass(frozen=True)
class LensFabricIntent:
    """One host-independent Ground, exact revision, projection and logical coordinate."""

    proposal: StructuralMemoryProposal
    coordinate: int
    request_id: str

    def __post_init__(self) -> None:
        """Mathematics: replay finite witnesses and certify the coordinate's admitted horizon."""
        if not isinstance(self.proposal, StructuralMemoryProposal):
            raise LensFabricRefused("typed lens Structural Memory proposal required")
        if (type(self.request_id) is not str or not 1 <= len(self.request_id) <= 100
                or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-"
                       for c in self.request_id)):
            raise LensFabricRefused("invalid mathematical request identity")
        if type(self.coordinate) is not int or not 0 <= self.coordinate <= MAX_COORDINATE:
            raise LensFabricRefused("lens coordinate exceeds native budget")
        if self.proposal.spec.family != "lens64":
            raise LensFabricRefused("only lens64 Grounds may use this verifier")
        try:
            StructuralMemoryVerifier().verify_proposal(self.proposal)
            independent_lens_value(self.proposal, self.coordinate)
        except (StructuralMemoryError, ValueError, TypeError) as exc:
            raise LensFabricRefused("lens witness or coordinate does not justify navigation") from exc

    @property
    def fingerprint(self) -> str:
        """Mathematics: bind the source Ground, certificate, projection, coordinate and request."""
        return digest({
            "schema": SCHEMA + ".intention", "request_id": self.request_id,
            "proposal_id": self.proposal.proposal_id,
            "spec_digest": self.proposal.spec.digest,
            "certificate_digest": self.proposal.certificate.digest,
            "coordinate": self.coordinate, "observer": "value",
        })

    @property
    def expected_value(self) -> int:
        """Mathematics: independently compute the requested value from the admitted law."""
        return independent_lens_value(self.proposal, self.coordinate)

    @property
    def memory_ref(self) -> VirtualStructuralMemoryRef:
        """Mathematics: address exactly one admitted revision without carrying a generator."""
        p = self.proposal
        return VirtualStructuralMemoryRef(
            BINDING, p.spec.memory_id, p.spec.revision, p.spec.context,
            self.coordinate, p.spec.digest, p.certificate.digest,
        )


def lens_fabric_address(
    intent: LensFabricIntent, *, system: SystemIdentity, ground: VirtualGroundRef,
    eligible_nodes: tuple[str, ...] = (), logical_time: int = 29,
) -> ComputationalAddress:
    """Mathematics: compile one Ground-relative observation into native semantic address ABI."""
    if not isinstance(intent, LensFabricIntent):
        raise LensFabricRefused("typed lens intention required")
    workload = VirtualLayerWorkload(
        workload_id="lens003-" + intent.request_id, system=system, ground=ground,
        intention={"goal": {
            "kind": SCHEMA, "intention": intent.fingerprint,
            "spec_digest": intent.proposal.spec.digest,
            "certificate_digest": intent.proposal.certificate.digest,
            "coordinate": intent.coordinate,
        }},
        operators=(VirtualOperatorRef(
            OPERATOR, 1, "cpu", structural_memory=(intent.memory_ref,),
        ),),
        input_value={"coordinate": intent.coordinate},
        budget=VirtualBudget(100000, 100000, 10000),
        logical_time=logical_time, eligible_nodes=eligible_nodes,
        max_hops=4, schema_version=2,
    )
    return ComputationalAddress.from_workload(
        workload, OPERATOR, lens_fabric_spec(), intent.proposal.spec.digest,
    )


def _match_intention(intent: LensFabricIntent, address: ComputationalAddress) -> None:
    """Mathematics: require identical typed Ground, operator, coordinate and pinned revision."""
    if not isinstance(intent, LensFabricIntent) or not isinstance(address, ComputationalAddress):
        raise LensFabricRefused("typed lens intention and ComputationalAddress required")
    workload = address.workload
    try:
        bound_operator = workload.operator_ref(OPERATOR)
        refs = bound_operator.structural_memory
        goal = json.loads(canonical(workload.intention["goal"]))
        inputs = json.loads(canonical(workload.input_value))
    except (KeyError, TypeError, ValueError) as exc:
        raise LensFabricRefused("native workload lacks a canonical Ground address") from exc
    target_goal = {
        "kind": SCHEMA, "intention": intent.fingerprint,
        "spec_digest": intent.proposal.spec.digest,
        "certificate_digest": intent.proposal.certificate.digest,
        "coordinate": intent.coordinate,
    }
    if (len(workload.operators) != 1 or workload.schema_version != 2
            or address.operator_id != OPERATOR
            or address.operator_contract_digest != lens_fabric_spec().digest
            or address.computational_ground_fingerprint != intent.proposal.spec.digest
            or address.observation_kind != "object"
            or address.program_fingerprint is not None
            or inputs != {"coordinate": intent.coordinate}
            or goal != target_goal or len(refs) != 1
            or bound_operator.to_dict() != VirtualOperatorRef(
                OPERATOR, 1, "cpu", structural_memory=(intent.memory_ref,),
            ).to_dict()
            or refs[0].to_dict() != intent.memory_ref.to_dict()):
        raise LensFabricRefused("native lens semantic address differs from intention or pinned revision")


def _verify_memory_receipt(
    intent: LensFabricIntent, payload: Any,
) -> StructuralMemoryReadReceipt:
    """Mathematics: reconstruct receipt identity H(spec, certificate, coordinate, value) exactly."""
    try:
        receipt = StructuralMemoryReadReceipt.from_dict(payload)
    except (StructuralMemoryError, KeyError, TypeError, ValueError) as exc:
        raise LensFabricRefused("terminal lacks a typed Structural Memory read receipt") from exc
    ref, proposal = intent.memory_ref, intent.proposal
    expected = intent.expected_value
    value_digest = digest({"type": "integer", "value": expected})
    read_id = digest({
        "memory_id": ref.memory_id, "revision": ref.revision,
        "spec_digest": ref.spec_digest, "certificate_digest": ref.certificate_digest,
        "coordinate": ref.coordinate, "context_digest": proposal.spec.context_digest,
        "value_digest": value_digest,
    })
    if (receipt.memory_id != ref.memory_id or receipt.revision != ref.revision
            or receipt.spec_digest != ref.spec_digest
            or receipt.certificate_digest != ref.certificate_digest
            or receipt.context_digest != proposal.spec.context_digest
            or receipt.coordinate != ref.coordinate or receipt.value != expected
            or receipt.value_digest != value_digest or receipt.receipt_id != read_id
            or receipt.verification_class is not proposal.certificate.verification_class
            or receipt.witness_digest != proposal.certificate.witness_digest):
        raise LensFabricRefused("terminal read receipt does not reproduce from the pinned Ground")
    return receipt


def validate_lens_fabric_result(
    intent: LensFabricIntent, address: ComputationalAddress,
    envelope: ComputationalFabricForwardingEnvelope,
    receipt: ComputationalFabricHopReceipt,
) -> dict[str, Any]:
    """Mathematics: check every native hop and independently regenerate receiver's exact read."""
    _match_intention(intent, address)
    if envelope.address.digest != address.digest or envelope.route.address_digest != address.digest:
        raise LensFabricRefused("fabric envelope does not refer to the same semantic address")
    terminal = _verify_receipt_chain(envelope, receipt)
    execution = terminal.get("execution")
    if (terminal.get("accepted") is not True or terminal.get("executed") is not True
            or terminal.get("status") not in {"executed", "replayed"}
            or not isinstance(execution, Mapping)):
        raise LensFabricRefused("terminal did not admit a receiver-local execution")
    effect = execution.get("effect")
    if not isinstance(effect, Mapping):
        raise LensFabricRefused("terminal execution has no typed Virtual Layer effect")
    effect = json.loads(canonical(effect))
    memory = effect.get("structural_memory_receipts")
    if not isinstance(memory, dict) or set(memory) != {BINDING}:
        raise LensFabricRefused("terminal did not resolve a receiver-local Ground revision")
    read = _verify_memory_receipt(intent, memory[BINDING])
    value = intent.expected_value
    expected_resolved = {
        "input": {"coordinate": intent.coordinate},
        "structural_memory": {BINDING: {"value": value, "receipt": read.to_dict()}},
    }
    if (effect.get("kind") != "virtual_layer.operator_result"
            or effect.get("operator_id") != OPERATOR
            or effect.get("operator_contract_digest") != address.operator_contract_digest
            or effect.get("ground") != address.workload.ground.to_dict()
            or effect.get("workload_digest") != address.workload.digest
            or effect.get("input_digest") != digest({"coordinate": intent.coordinate})
            or effect.get("resolved_input_digest") != digest(expected_resolved)
            or effect.get("result") != {"value": value}
            or effect.get("result_digest") != digest({"value": value})):
        raise LensFabricRefused("terminal result or bound read disagrees with exact intention")
    return {
        "schema": SCHEMA, "intention_digest": intent.fingerprint,
        "spec_digest": intent.proposal.spec.digest,
        "certificate_digest": intent.proposal.certificate.digest,
        "witness_digest": intent.proposal.certificate.witness_digest,
        "address_digest": address.digest, "operation_digest": envelope.operation_digest,
        "route_digest": envelope.route.digest, "terminal_peer_id": envelope.route.peer_path[-1],
        "observed": {"value": value}, "structural_memory_read": read.to_dict(),
        "forwarding_envelope": envelope.to_dict(),
        "hop_receipt": receipt.to_dict(), "hop_receipt_digest": receipt.digest,
    }


@dataclass(frozen=True)
class LensFabricPlan:
    """Host-independent intention coupled to one revocable native topology proposal."""

    intent: LensFabricIntent
    route: NativeRoutePlan


class LensFabricDispatcher:
    """Reuse SAB-007 native candidate routing with lens-specific semantic verification."""

    def __init__(self, native: NativeGroundDispatcher) -> None:
        """Mathematics: bind only the established native authenticated Fabric route selector."""
        if not isinstance(native, NativeGroundDispatcher):
            raise LensFabricRefused("native Fabric dispatcher required")
        self.native = native

    def prepare(
        self, intent: LensFabricIntent, address: ComputationalAddress, *,
        origin_sequence: int,
        excluded_hosts: frozenset[tuple[str, str]] = frozenset(),
    ) -> LensFabricPlan:
        """Mathematics: separate immutable Ground identity from revocable host assignment."""
        _match_intention(intent, address)
        route = self.native.prepare_route(
            address, origin_sequence=origin_sequence, excluded_hosts=excluded_hosts,
        )
        return LensFabricPlan(intent, route)

    def execute(self, plan: LensFabricPlan) -> dict[str, Any]:
        """Mathematics: recheck live native topology before and after verified lens realization."""
        if not isinstance(plan, LensFabricPlan):
            raise LensFabricRefused("typed lens fabric plan required")
        _match_intention(plan.intent, plan.route.address)
        return self.native.execute_route(
            plan.route,
            lambda envelope, receipt: validate_lens_fabric_result(
                plan.intent, plan.route.address, envelope, receipt,
            ),
        )


def recheck_lens_evidence(
    intent: LensFabricIntent, address: ComputationalAddress, evidence: Mapping[str, Any],
) -> dict[str, Any]:
    """Mathematics: independently deserialize and verify the complete hop and structural-read tree."""
    if not isinstance(evidence, Mapping) or evidence.get("schema") != SCHEMA:
        raise LensFabricRefused("unrecognized lens evidence schema")
    try:
        envelope = ComputationalFabricForwardingEnvelope.from_dict(evidence["forwarding_envelope"])
        receipt = ComputationalFabricHopReceipt.from_dict(evidence["hop_receipt"])
    except (KeyError, ValueError, TypeError) as exc:
        raise LensFabricRefused("stored native forwarding receipt cannot be reconstructed") from exc
    checked = validate_lens_fabric_result(intent, address, envelope, receipt)
    if json.loads(canonical(evidence)) != checked:
        raise LensFabricRefused("stored lens evidence differs from independently replayed observation")
    return checked


def seal_lens_fabric_result(
    intent: LensFabricIntent, address: ComputationalAddress,
    evidence: Mapping[str, Any], *,
    coordinator: RecoveryLineageCoordinator,
    storage: AtomicGroundEvidenceStore,
    generation: int, predecessor_digest: str,
) -> tuple[RecoveryStateManifest, RecoveryLineageProof]:
    """Mathematics: seal only reverified native evidence under the existing quorum high-water."""
    if not isinstance(coordinator, RecoveryLineageCoordinator):
        raise LensFabricRefused("receiver recovery-lineage coordinator required")
    if not isinstance(storage, AtomicGroundEvidenceStore):
        raise LensFabricRefused("native evidence store required")
    if type(generation) is not int or generation < 1:
        raise LensFabricRefused("invalid lineage generation")
    if (type(predecessor_digest) is not str or len(predecessor_digest) != 64
            or any(c not in "0123456789abcdef" for c in predecessor_digest)):
        raise LensFabricRefused("invalid predecessor digest")
    checked = recheck_lens_evidence(intent, address, evidence)
    encoded = canonical(checked)
    state_digest = storage.put(encoded)
    members = coordinator.membership
    manifest = RecoveryStateManifest(
        machine_id=members.system_id, incarnation=members.incarnation,
        owner_id=members.owner_id, owner_term=members.owner_term,
        membership_digest=members.digest, generation=generation,
        predecessor_digest=predecessor_digest, state_digest=state_digest,
        capture_cut="lens003.fabric-structural-read-verified",
    )
    manifest.verify_payload(storage.get(state_digest))
    proof = coordinator.seal(manifest)
    if coordinator.verify_state(manifest).snapshot() != proof.snapshot():
        raise LensFabricRefused("quorum state proof changed during native Ground sealing")
    return manifest, proof


def recover_lens_fabric_result(
    intent: LensFabricIntent, address: ComputationalAddress, *,
    manifest: RecoveryStateManifest, proof: RecoveryLineageProof,
    coordinator: RecoveryLineageCoordinator,
    storage: AtomicGroundEvidenceStore,
) -> dict[str, Any]:
    """Mathematics: recheck quorum-current state and recover value without reexecuting law."""
    if not isinstance(manifest, RecoveryStateManifest) or not isinstance(proof, RecoveryLineageProof):
        raise LensFabricRefused("typed recovery lineage manifest and proof required")
    if manifest.capture_cut != "lens003.fabric-structural-read-verified":
        raise LensFabricRefused("quorum state belongs to a different semantic capture cut")
    if coordinator.verify_state(manifest).snapshot() != proof.snapshot():
        raise LensFabricRefused("stored proof is not the current accepted quorum decision")
    raw = storage.get(manifest.state_digest)
    manifest.verify_payload(raw)
    checked = recheck_lens_evidence(intent, address, json.loads(raw))
    return {
        "schema": SCHEMA + ".recovered",
        "intention_digest": intent.fingerprint,
        "spec_digest": intent.proposal.spec.digest,
        "certificate_digest": intent.proposal.certificate.digest,
        "observed": checked["observed"],
        "state_digest": manifest.state_digest,
        "lineage_proof_digest": digest(proof.snapshot()),
        "reexecuted_computation": False,
    }
