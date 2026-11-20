"""IPS-005: quorum-fenced publication of intention-generated Ground stages.

Reuse IPS-004 stage execution and E-CPU's existing durable recovery-lineage
strict-majority protocol. Stage assignments and completed DAG prefixes are
separately sealed as whole-state roots. Only the latest assignment may publish
a candidate; a slow former host may have performed pure work, but cannot
commit that work after rehoming.

This is a single-owner/fixed-term reference implementation, not arbitrary
Byzantine consensus or a claim of at-most-once physical execution. The quorum
authorities must retain their journals outside the checkpoint rollback scope.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from .generative_ground_construction import (
    AffineBehaviorIntention, AffinePrimitive, GroundConstructionPlan,
)
from .qualified_generated_ground import (
    QualifiedGroundExecution, QualifiedStageHost,
)
from .recovery_lineage import (
    RecoveryLineageCoordinator, RecoveryLineageProof, RecoveryStateManifest,
)
from .semantic_translation import canonical_value_digest
from .headless import HeadlessOS

_SCHEMA = "mailcpu.ips005.quorum-fenced-ground.v1"
_MAX_ARTIFACT_BYTES = 2_097_152


class FencedGroundError(ValueError):
    """Current assignment, manifest, publication or quorum validation refused."""


def _bytes(value: Any) -> bytes:
    """Encode bounded, finite canonical JSON using the existing digest law."""
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise FencedGroundError("state is not canonical JSON") from exc
    if len(raw) > _MAX_ARTIFACT_BYTES:
        raise FencedGroundError("state artifact exceeds bounded record size")
    return raw


def _copy(value: Any) -> Any:
    """Detach stored evidence objects from caller-controlled mutable references."""
    return json.loads(_bytes(value))


def _sha(raw: bytes) -> str:
    """Identify a stored artifact by SHA-256 without claiming a signature."""
    return hashlib.sha256(raw).hexdigest()


def _check_label(value: Any, name: str) -> str:
    """Check bounded host and capture labels before using them in a record."""
    if not isinstance(value, str) or not 1 <= len(value) <= 128 or "\x00" in value:
        raise FencedGroundError(f"invalid {name}")
    return value


@dataclass(frozen=True)
class FencedGroundHead:
    """One quorum-sealed state root plus a detached, immutable JSON representation."""

    manifest: RecoveryStateManifest
    _state_json: str

    @property
    def state(self) -> dict[str, Any]:
        """Return a detached copy of the exact persisted state."""
        return json.loads(self._state_json)

    @property
    def checkpoint(self) -> dict[str, Any]:
        """Expose the IPS-004 checkpoint, which remains non-authoritative alone."""
        return self.state["checkpoint"]

    @property
    def assignment(self) -> dict[str, Any] | None:
        """Read only the latest proposed owner of the next DAG frontier."""
        return self.state["assignment"]


@dataclass(frozen=True)
class FencedGroundCandidate:
    """Computed but not yet quorum-published next-stage evidence."""

    assignment_manifest_digest: str
    assignment_epoch: int
    host_id: str
    next_checkpoint: dict[str, Any]

    @property
    def digest(self) -> str:
        """Bind the proposal to a specific sealed assignment and candidate bytes."""
        return canonical_value_digest({
            "assignment_manifest_digest": self.assignment_manifest_digest,
            "assignment_epoch": self.assignment_epoch, "host_id": self.host_id,
            "next_checkpoint": self.next_checkpoint,
        })

    @property
    def authoritative(self) -> bool:
        """A worker-produced candidate never publishes itself."""
        return False


class FencedGroundLineage:
    """Commit generated Ground assignments and stage receipts via native quorum.

    The local artifact directory holds fsynced, content-addressed bytes; the
    majority journals hold their monotonically committed manifests. A fresh
    coordinator can reconstruct the exact latest state from both sources.
    """

    def __init__(
        self,
        lineage: RecoveryLineageCoordinator,
        artifact_directory: str | Path,
        plan: GroundConstructionPlan,
        intention: AffineBehaviorIntention,
        primitives: Sequence[AffinePrimitive],
    ) -> None:
        """Bind one already-configured independent authority quorum and Ground."""
        if not isinstance(lineage, RecoveryLineageCoordinator):
            raise FencedGroundError("a native recovery lineage coordinator is required")
        self.lineage = lineage
        self.root = Path(artifact_directory)
        self.plan = plan
        self.intention = intention
        self.primitives = tuple(primitives)
        self.root.mkdir(parents=True, exist_ok=True)
        if not self.root.is_dir():
            raise FencedGroundError("artifact directory is not accessible")

    def _material(self, generation: int, digest: str, kind: str) -> Path:
        """Choose only internally derived file names inside the trusted artifact root."""
        return self.root / f"{kind}-{generation:08d}-{digest}.json"

    def _persist(self, path: Path, raw: bytes) -> None:
        """Atomically create immutable content-addressed artifact bytes and fsync."""
        if path.exists():
            if path.read_bytes() != raw:
                raise FencedGroundError("artifact path conflicts with existing bytes")
            return
        try:
            fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            if path.read_bytes() != raw:
                raise FencedGroundError("concurrent artifact write differs")
            return
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                parent_fd = os.open(str(self.root),
                                    os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
                try:
                    os.fsync(parent_fd)
                finally:
                    os.close(parent_fd)
            except OSError:
                # Windows directory handles do not support O_DIRECTORY/fsync.
                # The quorum's independent journal still governs admission.
                pass
        except BaseException:
            raise

    def _session(self, checkpoint: Mapping[str, Any]) -> QualifiedGroundExecution:
        """Check the complete generated DAG and every historic stage independently."""
        try:
            session = QualifiedGroundExecution.from_checkpoint(
                self.plan, self.intention, self.primitives, checkpoint
            )
        except (ValueError, TypeError, KeyError) as exc:
            raise FencedGroundError("generated Ground checkpoint failed replay") from exc
        if (session.system.system_id != self.lineage.membership.system_id
                or session.system.incarnation != self.lineage.membership.incarnation):
            raise FencedGroundError("checkpoint virtual system identity differs from quorum")
        return session

    def _validate_state(self, state: Any) -> QualifiedGroundExecution:
        """Require a complete, internally consistent state+assignment schema."""
        if (not isinstance(state, Mapping)
                or set(state) != {"schema", "plan_digest", "intention_digest",
                                  "checkpoint", "epoch", "assignment", "event"}
                or state["schema"] != _SCHEMA
                or state["plan_digest"] != self.plan.digest
                or state["intention_digest"] != self.intention.digest
                or type(state["epoch"]) is not int or state["epoch"] < 0
                or state["event"] not in ("bootstrap", "assign", "reassign", "publish")):
            raise FencedGroundError("sealed state differs from requested Ground")
        session = self._session(state["checkpoint"])
        assignment = state["assignment"]
        if assignment is not None:
            if (not isinstance(assignment, Mapping)
                    or set(assignment) != {"host_id", "epoch", "stage", "source_checkpoint_digest"}
                    or not isinstance(assignment["host_id"], str)
                    or not 1 <= len(assignment["host_id"]) <= 128
                    or type(assignment["epoch"]) is not int
                    or assignment["epoch"] != state["epoch"]
                    or type(assignment["stage"]) is not int
                    or assignment["stage"] != len(session.stages)
                    or assignment["source_checkpoint_digest"] != state["checkpoint"]["digest"]
                    or session.complete):
                raise FencedGroundError("assignment does not name next admissible stage")
            if state["event"] not in ("assign", "reassign"):
                raise FencedGroundError("publication and bootstrap cannot retain an assignment")
        elif state["event"] in ("assign", "reassign"):
            raise FencedGroundError("assignment event missing its selected host")
        return session

    def _check_head(self, head: FencedGroundHead) -> QualifiedGroundExecution:
        """Enforce current majority high-water before any local publication."""
        if not isinstance(head, FencedGroundHead):
            raise FencedGroundError("typed sealed Ground head required")
        state = head.state
        raw = _bytes(state)
        head.manifest.verify_payload(raw)
        self.lineage.verify_state(head.manifest)
        return self._validate_state(state)

    def _seal(
        self, state: dict[str, Any], *, capture_cut: str,
        expected_parent: tuple[int, str],
    ) -> FencedGroundHead:
        """Fsync only a transition extending its caller-pinned quorum parent.

        Explicit expected-parent comparison prevents a delayed publisher from
        treating a newly committed reassignment as permission to append its
        obsolete candidate at a later generation. Native one-vote-per-slot
        quorums close the remaining concurrent prepare race.
        """
        self._validate_state(state)
        generation, predecessor = self.lineage.high_water()
        if (generation, predecessor) != expected_parent:
            raise FencedGroundError("expected parent was superseded by quorum high-water")
        raw = _bytes(state)
        manifest = RecoveryStateManifest(
            self.lineage.membership.system_id,
            self.lineage.membership.incarnation,
            self.lineage.membership.owner_id,
            self.lineage.membership.owner_term,
            self.lineage.membership.digest,
            generation + 1,
            predecessor,
            _sha(raw),
            capture_cut,
        )
        self._persist(self._material(manifest.generation, manifest.state_digest, "state"), raw)
        self._persist(self._material(manifest.generation, manifest.digest, "manifest"),
                      _bytes(manifest.snapshot()))
        self.lineage.seal(manifest)
        self.lineage.verify_state(manifest)
        return FencedGroundHead(manifest, raw.decode("utf-8"))

    def bootstrap(self, session: QualifiedGroundExecution) -> FencedGroundHead:
        """Anchor the unassigned IPS-004 checkpoint as generation one."""
        if not isinstance(session, QualifiedGroundExecution):
            raise FencedGroundError("native generated Ground session required")
        if self.lineage.high_water() != (0, self.lineage.membership.genesis_state_digest):
            raise FencedGroundError("quorum already has a committed Ground state")
        saved = session.checkpoint()
        self._session(saved)
        return self._seal({
            "schema": _SCHEMA, "plan_digest": self.plan.digest,
            "intention_digest": self.intention.digest,
            "checkpoint": saved, "epoch": 0, "assignment": None,
            "event": "bootstrap",
        }, capture_cut="ips005.bootstrap", expected_parent=(0, self.lineage.membership.genesis_state_digest))

    def restore(self, head: FencedGroundHead) -> FencedGroundHead:
        """Re-admit one persisted state only if it remains the quorum high-water."""
        manifest = head.manifest
        raw = self._material(manifest.generation, manifest.state_digest, "state").read_bytes()
        if raw != _bytes(head.state):
            raise FencedGroundError("artifact bytes differ from supplied checkpoint")
        manifest.verify_payload(raw)
        restored = FencedGroundHead(manifest, raw.decode("utf-8"))
        self._check_head(restored)
        return restored

    def restore_latest(self) -> FencedGroundHead:
        """Find the exact latest root by the independent quorum, never by mtime."""
        proof = self.lineage.latest_proof()
        if proof is None:
            raise FencedGroundError("no sealed IPS-005 Ground exists")
        generation, root_digest = proof.proposal.slot, proof.proposal.result_state_digest
        path = self._material(generation, root_digest, "manifest")
        if not path.is_file():
            raise FencedGroundError("quorum head has no matching persisted manifest")
        try:
            manifest = RecoveryStateManifest.from_snapshot(json.loads(path.read_bytes()))
        except (ValueError, TypeError, KeyError) as exc:
            raise FencedGroundError("persistent state manifest malformed") from exc
        if manifest.digest != root_digest:
            raise FencedGroundError("manifest differs from latest quorum root")
        raw = self._material(generation, manifest.state_digest, "state").read_bytes()
        manifest.verify_payload(raw)
        result = FencedGroundHead(manifest, raw.decode("utf-8"))
        self._check_head(result)
        return result

    def assign(self, head: FencedGroundHead, host: QualifiedStageHost) -> FencedGroundHead:
        """Select a new owner of the next stage and seal its assignment epoch."""
        session = self._check_head(head)
        if not isinstance(host, QualifiedStageHost):
            raise FencedGroundError("assignment requires independently qualified host")
        if session.complete:
            raise FencedGroundError("already completed Grounds have no stage to assign")
        prior = head.assignment
        if prior is not None and prior["host_id"] == host.locus:
            raise FencedGroundError("reassignment requires a distinct qualified host")
        epoch = head.state["epoch"] + 1
        state = {
            "schema": _SCHEMA, "plan_digest": self.plan.digest,
            "intention_digest": self.intention.digest,
            "checkpoint": head.checkpoint,
            "epoch": epoch,
            "assignment": {
                "host_id": host.locus, "epoch": epoch,
                "stage": len(session.stages),
                "source_checkpoint_digest": head.checkpoint["digest"],
            },
            "event": "reassign" if prior else "assign",
        }
        return self._seal(
            state, capture_cut="ips005.reassign" if prior else "ips005.assign",
            expected_parent=(head.manifest.generation, head.manifest.digest),
        )

    def compute(
        self,
        head: FencedGroundHead,
        host: QualifiedStageHost,
        operating_system: HeadlessOS,
        pid: int,
    ) -> FencedGroundCandidate:
        """Execute pure work under IPS-004 and native Hypervisor without publishing it."""
        self._check_head(head)
        assignment = head.assignment
        if (assignment is None or not isinstance(host, QualifiedStageHost)
                or assignment["host_id"] != host.locus):
            raise FencedGroundError("host is not current quorum-assigned stage owner")
        session = self._session(head.checkpoint)
        snapshot = session.advance(operating_system, pid, host)
        return FencedGroundCandidate(
            head.manifest.digest, assignment["epoch"], host.locus, _copy(snapshot),
        )

    def publish(
        self, head: FencedGroundHead, candidate: FencedGroundCandidate
    ) -> FencedGroundHead:
        """Admit only the exact currently assigned, independently checked stage.

        The native quorum's one-vote-per-generation rule serializes a racing
        rehome/publish pair. The losing candidate may have done pure work, but
        cannot become the authoritative latest checkpoint.
        """
        session = self._check_head(head)
        assignment = head.assignment
        if (assignment is None or not isinstance(candidate, FencedGroundCandidate)
                or candidate.assignment_manifest_digest != head.manifest.digest
                or candidate.assignment_epoch != assignment["epoch"]
                or candidate.host_id != assignment["host_id"]):
            raise FencedGroundError("candidate is fenced by a different assignment")
        completed = self._session(candidate.next_checkpoint)
        if (len(completed.stages) != len(session.stages) + 1
                or completed.stages[:-1] != session.stages
                or completed.stages[-1]["host"] != candidate.host_id
                or candidate.next_checkpoint["payload"]["ground"] != head.checkpoint["payload"]["ground"]
                or candidate.next_checkpoint["payload"]["system"] != head.checkpoint["payload"]["system"]):
            raise FencedGroundError("candidate changed identity, prior work or selected host")
        # Confirm exactly one native ready stage and no other graph mutation.
        next_stage = len(session.stages)
        if (len(session.dag.ready_nodes()) != 1
                or session.dag.ready_nodes()[0].node_id != f"ips003.stage.{next_stage:03d}"):
            raise FencedGroundError("candidate did not consume the current native frontier")
        state = {
            "schema": _SCHEMA, "plan_digest": self.plan.digest,
            "intention_digest": self.intention.digest,
            "checkpoint": _copy(candidate.next_checkpoint),
            "epoch": assignment["epoch"], "assignment": None,
            "event": "publish",
        }
        return self._seal(
            state, capture_cut="ips005.publish",
            expected_parent=(head.manifest.generation, head.manifest.digest),
        )
