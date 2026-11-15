"""SAB-007: native Computational Fabric forwarding with quorum-anchored Ground continuity.

Only native authenticated forwarding clients can dispatch a route. The bridge
validates non-authoritative routes against the active directory both before
and after forwarding, checks the terminal Hypervisor outcome against a stable
mathematical intention, then (separately) seals those bytes through E-CPU's
fixed-membership RecoveryLineageCoordinator. No directory advertisement grants
execution, and neither a digest nor a receipt claims independent silicon.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

from .adaptive_placement import CompositeIntent, expected_result
from .computational_fabric import (
    ComputationalFabricDirectory, ComputationalFabricResolver,
    ComputationalFabricRouteWitness, ComputationalFabricStatus,
)
from .computational_fabric_forwarding import (
    ComputationalFabricForwardingClient, ComputationalFabricForwardingEnvelope,
    ComputationalFabricHopReceipt,
)
from .computational_resolver import ComputationalAddress
from .recovery_lineage import (
    RecoveryLineageCoordinator, RecoveryLineageProof, RecoveryStateManifest,
)
from .runtime_qualification import canonical, digest

SCHEMA = "mailcpu.sab007.fabric-ground-continuity.v1"
MAX_EVIDENCE_BYTES = 512_000


class GroundContinuityRefused(ValueError):
    """An intention, active native path, semantic receipt or quorum cut is invalid."""


def _strict_sequence(value: Any) -> int:
    """Reject Boolean, negative, zero and unbounded original sequence numbers."""
    if type(value) is not int or not 1 <= value <= 2**63 - 1:
        raise GroundContinuityRefused("origin sequence must be a positive bounded integer")
    return value


def _decoded(value: Any) -> Any:
    """Normalize native frozen structures into detached finite JSON values."""
    return json.loads(canonical(value))


def _matches_intent(address: ComputationalAddress, intent: CompositeIntent) -> None:
    """Bind exact input and goal to host-independent SAB-004 mathematical intention."""
    if not isinstance(address, ComputationalAddress) or not isinstance(intent, CompositeIntent):
        raise GroundContinuityRefused("typed computational address and CompositeIntent required")
    workload = address.workload
    if _decoded(workload.input_value) != intent.input():
        raise GroundContinuityRefused("native workload input differs from intended state coordinate")
    goal = _decoded(workload.intention.get("goal"))
    if goal != {"kind": "sab007.affine", "intention": intent.fingerprint,
                "ground": intent.ground}:
        raise GroundContinuityRefused("workload goal does not pin the same mathematical intention")
    if address.computational_ground_fingerprint != intent.ground or address.observation_kind != "object":
        raise GroundContinuityRefused("native computational Ground or observation kind differs")


def _verify_receipt_chain(envelope: ComputationalFabricForwardingEnvelope,
                          receipt: ComputationalFabricHopReceipt) -> Mapping[str, Any]:
    """Reconstruct *every* envelope cursor, checking hop and operation identities."""
    if not isinstance(envelope, ComputationalFabricForwardingEnvelope) or not isinstance(receipt, ComputationalFabricHopReceipt):
        raise GroundContinuityRefused("native forwarding envelope and typed hop receipt required")
    cursor = envelope
    current = receipt
    path = cursor.route.peer_path
    for index in range(1, len(path)):
        cursor = cursor.advance()
        if (current.peer_id != path[index]
                or current.previous_peer_id != path[index - 1]
                or current.hop_index != index
                or current.operation_digest != cursor.operation_digest
                or current.envelope_digest != cursor.digest):
            raise GroundContinuityRefused("hop receipt differs from the native route cursor")
        if index < len(path) - 1:
            if (current.next_peer_id != path[index + 1]
                    or current.downstream is None
                    or current.next_envelope_digest != cursor.advance().digest):
                raise GroundContinuityRefused("relay receipt does not bind the next native envelope")
            current = current.downstream
        else:
            if current.next_peer_id is not None or current.downstream is not None:
                raise GroundContinuityRefused("terminal receipt contains a further forwarded hop")
    if not receipt.succeeded or not isinstance(current.terminal_execution, Mapping):
        raise GroundContinuityRefused("native forwarding did not commit a successful terminal execution")
    return current.terminal_execution


def validate_native_result(intent: CompositeIntent, address: ComputationalAddress,
                           envelope: ComputationalFabricForwardingEnvelope,
                           receipt: ComputationalFabricHopReceipt) -> dict[str, Any]:
    """Check native receiver execution and complete receipt chain before recording evidence.

    Hashes bind records; the receiver's own Hypervisor and authenticated
    transport supply authority. This recheck neither authenticates a forged
    receipt outside that transport nor proves an external machine identity.
    """
    _matches_intent(address, intent)
    if envelope.address.digest != address.digest or envelope.route.address_digest != address.digest:
        raise GroundContinuityRefused("forwarding envelope refers to another semantic address")
    terminal = _verify_receipt_chain(envelope, receipt)
    execution = terminal.get("execution")
    if (terminal.get("accepted") is not True or terminal.get("executed") is not True
            or terminal.get("status") not in {"executed", "replayed"}
            or not isinstance(execution, Mapping)):
        raise GroundContinuityRefused("terminal coordinator did not authorize execution")
    effect = execution.get("effect")
    if (not isinstance(effect, Mapping)
            or effect.get("kind") != "virtual_layer.operator_result"
            or effect.get("operator_contract_digest") != address.operator_contract_digest
            or _decoded(effect.get("ground")) != _decoded(address.workload.ground.to_dict())
            or _decoded(effect.get("result")) != {"value": expected_result(intent)["value"]}):
        raise GroundContinuityRefused("terminal result contradicts the pinned Ground or operator contract")
    return {"schema": SCHEMA, "intention_digest": intent.fingerprint,
            "ground_digest": intent.ground, "address_digest": address.digest,
            "operation_digest": envelope.operation_digest,
            "route_digest": envelope.route.digest,
            "origin_peer_id": envelope.origin_peer_id,
            "origin_channel": envelope.origin_channel,
            "origin_sequence": envelope.origin_sequence,
            "terminal_peer_id": envelope.route.peer_path[-1],
            "observed": expected_result(intent),
            "forwarding_envelope": envelope.to_dict(),
            "hop_receipt": receipt.to_dict(),
            "hop_receipt_digest": receipt.digest}


@dataclass(frozen=True)
class NativeGroundPlan:
    """Pinned native routing choice for one exact mathematical intention."""

    intent: CompositeIntent
    address: ComputationalAddress
    envelope: ComputationalFabricForwardingEnvelope
    directory_digest: str
    topology_digest: str

    @property
    def fingerprint(self) -> str:
        """Bind the original sequence, Ground, directory and non-authoritative path."""
        return digest({"schema": SCHEMA, "intent": self.intent.fingerprint,
                       "address": self.address.digest, "envelope": self.envelope.digest,
                       "directory": self.directory_digest, "topology": self.topology_digest})


class NativeGroundDispatcher:
    """Select a live native multi-hop route and require receiver-side fabric admission."""

    def __init__(self, directory: ComputationalFabricDirectory,
                 client: ComputationalFabricForwardingClient, *,
                 allowed_hosts: frozenset[tuple[str, str]],
                 max_candidates: int = 64) -> None:
        """Bind only a genuinely authenticated adjacent-peer forwarding client."""
        if not isinstance(directory, ComputationalFabricDirectory):
            raise GroundContinuityRefused("native directory required")
        if not isinstance(client, ComputationalFabricForwardingClient):
            raise GroundContinuityRefused("native authenticated forwarding client required")
        if client.local_peer_id != directory.local_peer_id or client.origin_peer_id != directory.local_peer_id:
            raise GroundContinuityRefused("forwarding origin differs from directory identity")
        if (type(max_candidates) is not int or not 1 <= max_candidates <= 128):
            raise GroundContinuityRefused("invalid candidate budget")
        if not isinstance(allowed_hosts, frozenset) or not allowed_hosts or any(
            not isinstance(pair, tuple) or len(pair) != 2
            or any(not isinstance(x, str) or not x for x in pair)
            for pair in allowed_hosts
        ):
            raise GroundContinuityRefused("exact peer and host admission required")
        self.directory = directory
        self.client = client
        self.allowed_hosts = allowed_hosts
        self.max_candidates = max_candidates
        self.resolver = ComputationalFabricResolver()

    def _options(self, address: ComputationalAddress) -> Any:
        """Resolve finite non-authoritative candidates from *current* native leases."""
        return self.resolver.resolve_candidates(
            address, self.directory, origin_peer_id=self.directory.local_peer_id,
            max_candidates=self.max_candidates,
        )

    def prepare(self, intent: CompositeIntent, address: ComputationalAddress, *,
                origin_sequence: int, excluded_hosts: frozenset[tuple[str, str]] = frozenset()) -> NativeGroundPlan:
        """Choose a new candidate after failure; never transfer the previous route's authority."""
        _matches_intent(address, intent)
        _strict_sequence(origin_sequence)
        if not isinstance(excluded_hosts, frozenset):
            raise GroundContinuityRefused("exclusions must be explicit immutable host identities")
        options = self._options(address)
        if options.status is not ComputationalFabricStatus.FOUND:
            raise GroundContinuityRefused("no native Fabric route satisfies the intended Ground")
        for witness in options.candidates:
            identity = (witness.target_host.peer_id, witness.target_host.host_id)
            if identity in excluded_hosts or identity not in self.allowed_hosts:
                continue
            if (len(witness.peer_path) < 2
                    or witness.peer_path[1] != self.client.remote_endpoint.peer_id
                    or witness.peer_endpoints[1] != self.client.remote_endpoint):
                continue
            envelope = ComputationalFabricForwardingEnvelope.begin(
                address, witness, origin_channel=self.client.origin_channel,
                origin_sequence=origin_sequence,
            )
            return NativeGroundPlan(intent, address, envelope,
                                    options.directory_digest, options.topology_digest)
        raise GroundContinuityRefused("no locally admitted route uses the authenticated first hop")

    def execute(self, plan: NativeGroundPlan) -> dict[str, Any]:
        """Forward via *native* ReliableChannel/Hypervisor transport and recheck live route."""
        if not isinstance(plan, NativeGroundPlan):
            raise GroundContinuityRefused("native typed plan required")
        _matches_intent(plan.address, plan.intent)
        before = self._options(plan.address)
        if (before.status is not ComputationalFabricStatus.FOUND
                or before.directory_digest != plan.directory_digest
                or before.topology_digest != plan.topology_digest
                or all(x.digest != plan.envelope.route.digest for x in before.candidates)):
            raise GroundContinuityRefused("native route changed before the receiver could admit it")
        if ((plan.envelope.route.target_host.peer_id,
             plan.envelope.route.target_host.host_id) not in self.allowed_hosts):
            raise GroundContinuityRefused("local host permission revoked before dispatch")
        receipt = self.client.forward(plan.envelope, self.directory)
        evidence = validate_native_result(plan.intent, plan.address, plan.envelope, receipt)
        after = self._options(plan.address)
        if (after.status is not ComputationalFabricStatus.FOUND
                or after.directory_digest != before.directory_digest
                or after.topology_digest != before.topology_digest
                or all(x.digest != plan.envelope.route.digest for x in after.candidates)):
            raise GroundContinuityRefused("native peer lease or topology changed during forwarding")
        return evidence


class AtomicGroundEvidenceStore:
    """Store canonical evidence by digest before asking the lineage quorum to certify it."""

    def __init__(self, directory: str | Path) -> None:
        """Use a locally controlled persistent directory, not a remote advertised store."""
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def put(self, payload: bytes) -> str:
        """Atomically persist exact canonical bytes, with fsync and collision refusal."""
        if type(payload) is not bytes or not 0 < len(payload) <= MAX_EVIDENCE_BYTES:
            raise GroundContinuityRefused("invalid evidence payload budget")
        identity = hashlib.sha256(payload).hexdigest()
        path = self.directory / f"{identity}.json"
        if path.exists():
            if path.read_bytes() != payload:
                raise GroundContinuityRefused("immutable evidence store has a conflicting payload")
            return identity
        tmp = self.directory / f".{identity}.{os.getpid()}.tmp"
        try:
            with tmp.open("xb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp, path)
            # Maintain a durable directory entry on POSIX; Windows fsync directory
            # is not always supported, and the recovery verifier still checks bytes.
            if os.name == "posix":
                descriptor = os.open(self.directory, os.O_RDONLY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
        finally:
            tmp.unlink(missing_ok=True)
        return identity

    def get(self, identity: str) -> bytes:
        """Refuse absent or corrupted content rather than guessing a prior state."""
        if (type(identity) is not str or len(identity) != 64
                or any(x not in "0123456789abcdef" for x in identity)):
            raise GroundContinuityRefused("invalid evidence content address")
        payload = (self.directory / f"{identity}.json").read_bytes()
        if hashlib.sha256(payload).hexdigest() != identity:
            raise GroundContinuityRefused("evidence bytes no longer match the content address")
        return payload


def recheck_evidence(intent: CompositeIntent, address: ComputationalAddress,
                     evidence: Mapping[str, Any]) -> dict[str, Any]:
    """Independently reconstruct a portable route and receiver result before acceptance."""
    if not isinstance(evidence, Mapping) or evidence.get("schema") != SCHEMA:
        raise GroundContinuityRefused("evidence has an unrecognized schema")
    envelope_payload = evidence.get("forwarding_envelope")
    receipt_payload = evidence.get("hop_receipt")
    if not isinstance(envelope_payload, Mapping) or not isinstance(receipt_payload, Mapping):
        raise GroundContinuityRefused("evidence has no reconstructible native envelope and receipt")
    try:
        envelope = ComputationalFabricForwardingEnvelope.from_dict(envelope_payload)
        receipt = ComputationalFabricHopReceipt.from_dict(receipt_payload)
    except (TypeError, ValueError, KeyError) as exc:
        raise GroundContinuityRefused("evidence native receipt could not be reconstructed") from exc
    reference = validate_native_result(intent, address, envelope, receipt)
    if _decoded(evidence) != reference:
        raise GroundContinuityRefused("stored evidence contains unsupported or contradictory fields")
    return reference


def seal_native_result(intent: CompositeIntent, address: ComputationalAddress,
                       evidence: Mapping[str, Any], *,
                       coordinator: RecoveryLineageCoordinator,
                       storage: AtomicGroundEvidenceStore,
                       generation: int,
                       predecessor_digest: str) -> tuple[RecoveryStateManifest, RecoveryLineageProof]:
    """Prepare content before a fixed-membership fsynced quorum seals the exact state root.

    A failed quorum leaves *prepared* bytes, not an accepted result. Retrying
    the same generation and bytes is permitted; conflicting roots are fenced
    by the recovery authority, not by this bridge or an unsigned digest.
    """
    if not isinstance(coordinator, RecoveryLineageCoordinator):
        raise GroundContinuityRefused("native recovery-lineage coordinator required")
    if not isinstance(storage, AtomicGroundEvidenceStore):
        raise GroundContinuityRefused("native prepared-evidence storage required")
    if type(generation) is not int or generation < 1:
        raise GroundContinuityRefused("invalid quorum generation")
    if (type(predecessor_digest) is not str or len(predecessor_digest) != 64
            or any(x not in "0123456789abcdef" for x in predecessor_digest)):
        raise GroundContinuityRefused("invalid predecessor lineage digest")
    reference = recheck_evidence(intent, address, evidence)
    encoded = canonical(reference)
    recorded_digest = storage.put(encoded)
    members = coordinator.membership
    manifest = RecoveryStateManifest(
        machine_id=members.system_id, incarnation=members.incarnation,
        owner_id=members.owner_id, owner_term=members.owner_term,
        membership_digest=members.digest, generation=generation,
        predecessor_digest=predecessor_digest, state_digest=recorded_digest,
        capture_cut="sab007.fabric-result-verified",
    )
    manifest.verify_payload(storage.get(recorded_digest))
    proof = coordinator.seal(manifest)
    verified = coordinator.verify_state(manifest)
    if verified.snapshot() != proof.snapshot():
        raise GroundContinuityRefused("quorum verification changed the accepted proof")
    return manifest, proof


def recover_native_result(intent: CompositeIntent, address: ComputationalAddress, *,
                          manifest: RecoveryStateManifest,
                          proof: RecoveryLineageProof,
                          coordinator: RecoveryLineageCoordinator,
                          storage: AtomicGroundEvidenceStore) -> dict[str, Any]:
    """Rebuild a previously accepted Ground observation without redoing computation."""
    if not isinstance(manifest, RecoveryStateManifest) or not isinstance(proof, RecoveryLineageProof):
        raise GroundContinuityRefused("typed recovery manifest and quorum proof required")
    verified = coordinator.verify_state(manifest)
    if verified.snapshot() != proof.snapshot():
        raise GroundContinuityRefused("supplied proof is not the live quorum's accepted decision")
    raw = storage.get(manifest.state_digest)
    manifest.verify_payload(raw)
    body = json.loads(raw)
    _matches_intent(address, intent)
    recheck_evidence(intent, address, body)
    return {"schema": SCHEMA + ".recovered",
            "intention_digest": intent.fingerprint, "ground_digest": intent.ground,
            "observed": body["observed"], "state_digest": manifest.state_digest,
            "lineage_proof_digest": digest(proof.snapshot()),
            "reexecuted_computation": False}