"""SAB-012: connect formed receiver-native execution to existing recovery lineage.

The formation/Hypervisor proof comes through the pinned TLS endpoint; the
SAB-004 data + decision must be readable on an admitted retention peer before
we ask the native RecoveryLineageCoordinator for a strict-majority seal.
The seal admits one immutable state root, not general exactly-once effects.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping

from .adaptive_placement import (
    AdaptivePlacement, CompositeIntent, CompiledPlacement, PlacementAuthority,
    QualifiedHost, expected_result,
)
from .ground_native_realization import AffineGround, GroundIntention
from .receiver_formed_native import (
    AttestedFormedEndpoint, ReceiverFormationRefused, SCHEMA as FORMED_SCHEMA,
)
from .runtime_qualification import canonical, digest
from .recovery_lineage import (
    RecoveryLineageCoordinator, RecoveryLineageError, RecoveryLineageProof,
    RecoveryStateManifest,
)

SCHEMA = "mailcpu.sab012.formed-quorum-continuity.v1"


class FormedQuorumRefused(ValueError):
    """Reject stale, unanchored, unauthenticated or incomplete formed state."""


def _semantic(intent: CompositeIntent) -> GroundIntention:
    return GroundIntention(intent.request_id,
        AffineGround(intent.a, intent.c, intent.modulus, intent.x0),
        intent.coordinate)


@dataclass(frozen=True)
class FormedFederatedPlan:
    """A non-authoritative SAB-004 route requiring a TLS-attested formed computer."""
    placement: CompiledPlacement
    compute_host: str
    semantic: str

    @property
    def fingerprint(self) -> str:
        return digest({"schema": SCHEMA + ".plan",
            "placement": self.placement.fingerprint,
            "compute_host": self.compute_host, "semantic": self.semantic})


class FormedFederatedController:
    """Require receiver-formed native proof alongside native SAB-004 semantics."""

    def __init__(self, hosts: Mapping[str, QualifiedHost],
                 authority: PlacementAuthority, *,
                 quanta: Mapping[tuple[str, str], int] | None = None) -> None:
        if not hosts:
            raise FormedQuorumRefused("controller has no qualified hosts")
        self.hosts = dict(hosts)
        self.placement = AdaptivePlacement(hosts, authority, quanta=quanta)

    def compile(self, intent: CompositeIntent, *, active_hosts: tuple[str, ...],
                coordinate: int) -> FormedFederatedPlan:
        plan = self.placement.compile(intent, active_hosts=active_hosts,
                                      coordinate=coordinate)
        host = plan.assignment[0]
        if not isinstance(self.hosts[host].endpoint, AttestedFormedEndpoint):
            raise FormedQuorumRefused("selected computation host is not TLS-attested formed receiver")
        return FormedFederatedPlan(plan, host, _semantic(intent).fingerprint)

    def execute(self, intent: CompositeIntent, plan: FormedFederatedPlan, *,
                active_hosts: tuple[str, ...], coordinate: int,
                copies: int = 2) -> dict[str, Any]:
        fresh = self.compile(intent, active_hosts=active_hosts, coordinate=coordinate)
        if (not isinstance(plan, FormedFederatedPlan)
                or fresh.fingerprint != plan.fingerprint):
            raise FormedQuorumRefused("formed federated placement became stale")
        ep = self.hosts[plan.compute_host].endpoint
        if not isinstance(ep, AttestedFormedEndpoint):
            raise FormedQuorumRefused("compute endpoint lost its TLS-attested binding")
        ep.last_attestation = None
        result = self.placement.execute(intent, fresh.placement,
            active_hosts=active_hosts, coordinate=coordinate, copies=copies)
        proof = ep.last_attestation
        sem = _semantic(intent)
        if (not isinstance(proof, Mapping)
                or proof.get("ground") != sem.ground.fingerprint
                or proof.get("result") != {"value": expected_result(intent)["value"]}
                or proof.get("evidence", {}).get("hypervisor_action") != "allow"
                or proof.get("evidence", {}).get("hypervisor_executed") is not True
                or result["result"] != expected_result(intent)):
            raise FormedQuorumRefused("receiver-native formation proof did not bind committed observation")
        body = {"schema": SCHEMA + ".execution", "intention": intent.fingerprint,
            "semantic": sem.fingerprint, "ground": sem.ground.fingerprint,
            "coordinate": intent.coordinate, "result": dict(result["result"]),
            "sab004_receipt_digest": result["receipt_digest"],
            "checkpoint_digest": result["checkpoint_digest"],
            "decision_digest": result["decision_digest"],
            "replicas": list(result["replicas"]),
            "formed_host": plan.compute_host,
            "formed_receiver_audit": json.loads(canonical(dict(proof))),
            "physical_independence_attested": False, "quorum_sealed": False}
        body["digest"] = digest(body)
        return body

    def resume(self, intent: CompositeIntent, *, active_hosts: tuple[str, ...],
               coordinate: int) -> dict[str, Any]:
        """Read SAB-004 checkpoint plus decision without contacting a compute host."""
        return self.placement.resume(intent, active_hosts=active_hosts,
                                     coordinate=coordinate)


def _exact_execution(value: Mapping[str, Any], intent: CompositeIntent) -> None:
    """Check the entire declared semantic and native evidence projection."""
    if (not isinstance(value, Mapping)
            or set(value) != {"schema", "intention", "semantic", "ground",
                "coordinate", "result", "sab004_receipt_digest",
                "checkpoint_digest", "decision_digest", "replicas", "formed_host",
                "formed_receiver_audit", "physical_independence_attested",
                "quorum_sealed", "digest"}
            or value["schema"] != SCHEMA + ".execution"
            or value["intention"] != intent.fingerprint
            or value["semantic"] != _semantic(intent).fingerprint
            or value["ground"] != _semantic(intent).ground.fingerprint
            or value["coordinate"] != intent.coordinate
            or value["result"] != expected_result(intent)
            or value["physical_independence_attested"] is not False
            or value["quorum_sealed"] is not False
            or not isinstance(value["replicas"], list)
            or not isinstance(value["formed_receiver_audit"], Mapping)
            or value["digest"] != digest({k:v for k,v in value.items() if k != "digest"})):
        raise FormedQuorumRefused("execution receipt contradicts the admitted intention")
    for item in ("sab004_receipt_digest", "checkpoint_digest", "decision_digest"):
        if (type(value[item]) is not str or len(value[item]) != 64
                or any(c not in "0123456789abcdef" for c in value[item])):
            raise FormedQuorumRefused("execution receipt has an invalid content identity")
    audit = value["formed_receiver_audit"]
    if (audit.get("schema") != FORMED_SCHEMA + ".audit"
            or audit.get("host") != value["formed_host"]
            or audit.get("ground") != value["ground"]
            or audit.get("result") != {"value": value["result"]["value"]}
            or audit.get("digest") != digest({k:v for k,v in audit.items() if k != "digest"})
            or audit.get("evidence", {}).get("hypervisor_action") != "allow"
            or audit.get("evidence", {}).get("hypervisor_executed") is not True):
        raise FormedQuorumRefused("stored native formation proof is incomplete")


def _atomic_new(path: Path, data: bytes) -> None:
    """Fsync an immutable local artifact before requesting an authority seal."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise FormedQuorumRefused("conflicting immutable state for one generation")
        return
    fd, name = tempfile.mkstemp(prefix=".sab012-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        # The majority journal controls decision uniqueness; a staged file is
        # never an accepted result until verify_state succeeds.
        if path.exists() and path.read_bytes() != data:
            raise FormedQuorumRefused("concurrent conflicting generation")
        os.replace(name, path)
        try:
            directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except OSError:
            pass
    finally:
        if os.path.exists(name):
            os.unlink(name)


class FormedQuorumAnchor:
    """One strict-majority lineage for data already admitted by SAB-004 readback."""

    def __init__(self, coordinator: RecoveryLineageCoordinator,
                 state_directory: str | Path) -> None:
        if not isinstance(coordinator, RecoveryLineageCoordinator):
            raise FormedQuorumRefused("native recovery-lineage coordinator required")
        self.coordinator = coordinator
        self.root = Path(state_directory)
        if not self.root.is_dir() or self.root.is_symlink():
            raise FormedQuorumRefused("pre-authorized recovery directory required")

    def _paths(self, generation: int) -> tuple[Path, Path]:
        if type(generation) is not int or not 1 <= generation <= 10**12:
            raise FormedQuorumRefused("invalid recovery generation")
        return (self.root / f"state-{generation}.json",
                self.root / f"manifest-{generation}.json")

    def seal(self, intent: CompositeIntent, execution: Mapping[str, Any], *,
             controller: FormedFederatedController, active_hosts: tuple[str, ...],
             coordinate: int, generation: int) -> dict[str, Any]:
        """Require storage readback, then persist state, then obtain native quorum."""
        _exact_execution(execution, intent)
        recovered = controller.resume(intent, active_hosts=active_hosts,
                                      coordinate=coordinate)
        if (recovered["checkpoint_digest"] != execution["checkpoint_digest"]
                or recovered["decision_digest"] != execution["decision_digest"]
                or recovered["replicas"] != execution["replicas"]
                or recovered["result"] != execution["result"]
                or recovered["ground"] != intent.ground):
            raise FormedQuorumRefused("SAB-004 retained checkpoint or decision is not currently readable")
        state = {"schema": SCHEMA + ".retained-state",
            "intention": intent.fingerprint, "semantic": _semantic(intent).fingerprint,
            "ground": _semantic(intent).ground.fingerprint,
            "coordinate": intent.coordinate,
            "result": dict(recovered["result"]),
            "checkpoint_digest": recovered["checkpoint_digest"],
            "decision_digest": recovered["decision_digest"],
            "replicas": list(recovered["replicas"]),
            "formation_execution_digest": execution["digest"],
            "formed_receiver_audit": dict(execution["formed_receiver_audit"]),
            "reexecuted_computation": False,
            "physical_independence_attested": False}
        data = canonical(state)
        previous_generation, previous_root = self.coordinator.high_water()
        if generation != previous_generation + 1:
            raise FormedQuorumRefused("lineage generation must advance exactly one")
        membership = self.coordinator.membership
        manifest = RecoveryStateManifest(
            machine_id=membership.system_id,
            incarnation=membership.incarnation,
            owner_id=membership.owner_id, owner_term=membership.owner_term,
            membership_digest=membership.digest,
            generation=generation, predecessor_digest=previous_root,
            state_digest=hashlib.sha256(data).hexdigest(),
            capture_cut="sab012.after_sab004_decision_and_forming_hypervisor",
        )
        state_path, manifest_path = self._paths(generation)
        _atomic_new(state_path, data)
        _atomic_new(manifest_path, canonical(manifest.snapshot()))
        proof = self.coordinator.seal(manifest)
        self.coordinator.verify_state(manifest)
        return {"kind": SCHEMA + ".sealed", "generation": generation,
            "state_digest": manifest.state_digest, "manifest_digest": manifest.digest,
            "decision_digest": execution["decision_digest"],
            "native_proof": proof.snapshot(), "quorum_sealed": True,
            "physical_independence_attested": False}

    def recover(self, intent: CompositeIntent, *, generation: int) -> dict[str, Any]:
        """Recover only the quorum-high-water state from independently saved bytes."""
        state_path, manifest_path = self._paths(generation)
        try:
            data = state_path.read_bytes()
            manifest = RecoveryStateManifest.from_snapshot(
                json.loads(manifest_path.read_bytes()))
            state = json.loads(data)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise FormedQuorumRefused("durable formed state or lineage manifest unavailable") from exc
        manifest.verify_payload(data)
        proof: RecoveryLineageProof = self.coordinator.verify_state(manifest)
        if (not isinstance(state, dict)
                or set(state) != {"schema", "intention", "semantic", "ground", "coordinate",
                    "result", "checkpoint_digest", "decision_digest", "replicas",
                    "formation_execution_digest", "formed_receiver_audit",
                    "reexecuted_computation", "physical_independence_attested"}
                or canonical(state) != data
                or state["schema"] != SCHEMA + ".retained-state"
                or state["intention"] != intent.fingerprint
                or state["semantic"] != _semantic(intent).fingerprint
                or state["ground"] != _semantic(intent).ground.fingerprint
                or state["coordinate"] != intent.coordinate
                or state["result"] != expected_result(intent)
                or state["reexecuted_computation"] is not False
                or state["physical_independence_attested"] is not False):
            raise FormedQuorumRefused("quorum record has invalid semantic content")
        audit = state["formed_receiver_audit"]
        if (not isinstance(audit, dict)
                or audit.get("schema") != FORMED_SCHEMA + ".audit"
                or audit.get("ground") != state["ground"]
                or audit.get("result") != {"value": state["result"]["value"]}
                or audit.get("digest") != digest({k:v for k,v in audit.items() if k != "digest"})):
            raise FormedQuorumRefused("quorum record's receiver formation evidence is invalid")
        return {"kind": SCHEMA + ".recovered",
            "intention": intent.fingerprint, "semantic": state["semantic"],
            "ground": state["ground"], "result": state["result"],
            "checkpoint_digest": state["checkpoint_digest"],
            "decision_digest": state["decision_digest"],
            "replicas": state["replicas"], "native_proof": proof.snapshot(),
            "reexecuted_computation": False,
            "quorum_sealed": True,
            "physical_independence_attested": False}