"""IPS-007: receiver-owned persistent effects with atomic Ground publication fencing.

The native recovery quorum decides *which* generated Ground is current. This
module makes a concrete receiver-owned resource reject delayed writes from
obsolete publications. It verifies IPS-005's original majority-supported
Ground checkpoint BEFORE installing its root and performs every actual value
write in the SAME SQLite BEGIN IMMEDIATE transaction as its local fence check.

The claim is a typed request, not a bearer capability or an independently
trusted credential. This class is an embedded/local resource adapter; a
network-exposed service must separately authenticate and authorize its caller.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Mapping

from .fenced_generated_ground import FencedGroundHead, FencedGroundLineage
from .semantic_translation import canonical_value_digest

_HEX = re.compile(r"[0-9a-f]{64}\Z")
_RESOURCE = re.compile(r"/[A-Za-z0-9][A-Za-z0-9._:/-]{0,126}\Z")
_SCHEMA = "mailcpu.ips007.fenced-receiver.v1"


class EffectFencingRefused(ValueError):
    """A caller's staged side effect lacks the receiver's installed authority."""


def _hex(value: Any, label: str) -> str:
    """Validate a canonical content digest before it participates in authority."""
    if type(value) is not str or _HEX.fullmatch(value) is None:
        raise EffectFencingRefused(f"{label} must be an exact SHA-256 digest")
    return value


def _resource(value: Any) -> str:
    """Require a bounded, path-safe receiver-owned logical effect resource."""
    if type(value) is not str or _RESOURCE.fullmatch(value) is None:
        raise EffectFencingRefused("effect resource must be a bounded safe path")
    return value


def _index(value: Any, label: str, *, zero: bool = True) -> int:
    """Validate a positive coordinate or a nonnegative stage index."""
    if type(value) is not int or value < (0 if zero else 1):
        raise EffectFencingRefused(f"{label} must be an integer coordinate")
    return value


@dataclass(frozen=True)
class PublishedGroundEffect:
    """One exact stage result and receipt proposed to a local effect receiver.

    This is not an authorization in itself. The receiver requires the same
    currently installed quorum head and local resource policy for a write.
    """

    resource: str
    generation: int
    manifest_digest: str
    plan_digest: str
    checkpoint_digest: str
    epoch: int
    stage_index: int
    host_id: str
    receipt_digest: str
    value: int

    def __post_init__(self) -> None:
        """Refuse malformed names, epochs, digests and negative register data."""
        _resource(self.resource)
        _index(self.generation, "manifest generation", zero=False)
        _hex(self.manifest_digest, "manifest")
        _hex(self.plan_digest, "plan")
        _hex(self.checkpoint_digest, "checkpoint")
        _index(self.epoch, "assignment epoch", zero=False)
        _index(self.stage_index, "stage index")
        _hex(self.receipt_digest, "Ground receipt")
        if (type(self.host_id) is not str or not 1 <= len(self.host_id) <= 128
                or "\x00" in self.host_id or type(self.value) is not int
                or not 0 <= self.value <= 2**63 - 1):
            raise EffectFencingRefused("invalid host identity or bounded receiver value")

    @property
    def operation_id(self) -> str:
        """Identify one semantic stage effect independent of retransmissions."""
        return canonical_value_digest({
            "kind": _SCHEMA, "resource": self.resource,
            "plan_digest": self.plan_digest, "stage_index": self.stage_index,
        })

    def to_dict(self) -> dict[str, Any]:
        """Return the exact JSON request for another process or socket adapter."""
        return {
            "resource": self.resource, "generation": self.generation,
            "manifest_digest": self.manifest_digest,
            "plan_digest": self.plan_digest,
            "checkpoint_digest": self.checkpoint_digest,
            "epoch": self.epoch, "stage_index": self.stage_index,
            "host_id": self.host_id, "receipt_digest": self.receipt_digest,
            "value": self.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PublishedGroundEffect":
        """Rebuild a typed request from an untrusted external JSON envelope."""
        fields = {
            "resource", "generation", "manifest_digest", "plan_digest",
            "checkpoint_digest", "epoch", "stage_index", "host_id",
            "receipt_digest", "value",
        }
        if not isinstance(value, Mapping) or set(value) != fields:
            raise EffectFencingRefused("effect request schema is not exact")
        try:
            return cls(**dict(value))
        except (TypeError, ValueError) as exc:
            if isinstance(exc, EffectFencingRefused):
                raise
            raise EffectFencingRefused("invalid typed effect request") from exc


def published_effect(
    head: FencedGroundHead, resource: str,
) -> PublishedGroundEffect:
    """Project already checked Ground history into an inert, bound request.

    The receiver's install() performs its own independent replay and quorum
    check; merely constructing this description grants nothing.
    """
    _resource(resource)
    if not isinstance(head, FencedGroundHead):
        raise EffectFencingRefused("published effect needs a typed quorum head")
    state = head.state
    if state.get("event") != "publish" or state.get("assignment") is not None:
        raise EffectFencingRefused("only a published Ground stage can request a side effect")
    records = head.checkpoint["payload"]["stages"]
    if not isinstance(records, list) or not records:
        raise EffectFencingRefused("published Ground has no completed stage")
    record = records[-1]
    observation = record["stage_receipt"]
    return PublishedGroundEffect(
        resource=resource, generation=head.manifest.generation,
        manifest_digest=head.manifest.digest,
        plan_digest=state["plan_digest"],
        checkpoint_digest=head.checkpoint["digest"],
        epoch=state["epoch"],
        stage_index=len(records)-1,
        host_id=record["host"],
        receipt_digest=observation["receipt_digest"],
        value=observation["output"]["value"],
    )


class FencedGroundEffectReceiver:
    """One local durable register resource with atomic epoch and effect writes.

    The installed head is a *local* receiver admission barrier. It may lag a
    newly committed remote majority until that new head is installed. There
    is no cross-network atomic transaction between remote quorum and SQLite.
    """

    def __init__(
        self, database: str | Path, *, resource: str, plan_digest: str
    ) -> None:
        """Bind an immutable receiver resource policy to one generated Ground."""
        self.path = Path(database)
        self.resource = _resource(resource)
        self.plan_digest = _hex(plan_digest, "authorized Ground plan")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS receiver_policy (
                    resource TEXT PRIMARY KEY,
                    plan_digest TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS installed_authority (
                    resource TEXT PRIMARY KEY,
                    generation INTEGER NOT NULL,
                    root TEXT NOT NULL,
                    plan_digest TEXT NOT NULL,
                    checkpoint_digest TEXT NOT NULL,
                    epoch INTEGER NOT NULL,
                    stage INTEGER,
                    host TEXT,
                    receipt_digest TEXT,
                    expected_value INTEGER,
                    event TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS effect_handoffs (
                    resource TEXT PRIMARY KEY,
                    source_generation INTEGER NOT NULL,
                    source_root TEXT NOT NULL,
                    target_epoch INTEGER NOT NULL,
                    target_host TEXT NOT NULL,
                    barrier_digest TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS effect_log (
                    operation_id TEXT PRIMARY KEY,
                    resource TEXT NOT NULL,
                    generation INTEGER NOT NULL,
                    root TEXT NOT NULL,
                    stage INTEGER NOT NULL,
                    value INTEGER NOT NULL,
                    receipt_digest TEXT NOT NULL,
                    receipt_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS registers (
                    resource TEXT PRIMARY KEY,
                    value INTEGER NOT NULL,
                    operation_id TEXT NOT NULL
                );
            """)
            db.execute(
                "INSERT OR IGNORE INTO receiver_policy(resource,plan_digest) VALUES (?,?)",
                (self.resource, self.plan_digest),
            )
            accepted = db.execute(
                "SELECT plan_digest FROM receiver_policy WHERE resource=?",
                (self.resource,),
            ).fetchone()
            if accepted != (self.plan_digest,):
                raise EffectFencingRefused("receiver resource is pinned to another Ground plan")

    def _connect(self) -> sqlite3.Connection:
        """Open a new independent connection suitable for cross-process locking."""
        conn = sqlite3.connect(
            str(self.path), timeout=8, isolation_level=None,
        )
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("PRAGMA busy_timeout=8000")
        return conn

    def _validated_binding(
        self, publisher: FencedGroundLineage, head: FencedGroundHead
    ) -> dict[str, Any]:
        """Recheck original quorum high-water and every IPS-004 native stage."""
        if not isinstance(publisher, FencedGroundLineage):
            raise EffectFencingRefused("native quorum-fenced Ground verifier required")
        if not isinstance(head, FencedGroundHead):
            raise EffectFencingRefused("a quorum-sealed Ground head is required")
        publisher.restore(head)
        state = head.state
        if (state["plan_digest"] != self.plan_digest
                or publisher.plan.digest != self.plan_digest):
            raise EffectFencingRefused("receiver policy rejects a different Ground plan")
        record: PublishedGroundEffect | None = None
        if state["event"] == "publish":
            record = published_effect(head, self.resource)
            # Check the exact native DAG result as well as the original SAB-008
            # observation. This independent replay is required by restore().
            stage = f"ips003.stage.{record.stage_index:03d}"
            computed = publisher._session(head.checkpoint).dag.result(stage)
            if (computed["value"] != record.value
                    or computed["stage_receipt_digest"] != record.receipt_digest):
                raise EffectFencingRefused("published receiver observation disagrees with DAG")
        return {
            "resource": self.resource,
            "generation": head.manifest.generation,
            "root": head.manifest.digest,
            "plan_digest": state["plan_digest"],
            "checkpoint_digest": head.checkpoint["digest"],
            "epoch": state["epoch"],
            "stage": record.stage_index if record else None,
            "host": record.host_id if record else None,
            "receipt_digest": record.receipt_digest if record else None,
            "expected_value": record.value if record else None,
            "event": state["event"],
            "assignment_host": head.assignment["host_id"] if head.assignment else None,
            "predecessor_root": head.manifest.predecessor_digest,
        }

    def prepare_handoff(
        self, publisher: FencedGroundLineage, head: FencedGroundHead,
        *, next_host: str,
    ) -> dict[str, Any]:
        """Fsync a fail-closed receiver barrier BEFORE issuing a new quorum assignment.

        The barrier and every future effect are serialized by one SQLite
        writer lock. An acknowledged barrier cannot be removed by retrying
        the old head; a matching successor assignment must be quorum-sealed
        and verified before the new root can be installed.
        """
        if (type(next_host) is not str or not 1 <= len(next_host) <= 128
                or "\x00" in next_host):
            raise EffectFencingRefused("handoff target host identity is invalid")
        binding = self._validated_binding(publisher, head)
        if next_host == binding["assignment_host"]:
            raise EffectFencingRefused("handoff requires a distinct next host")
        proposed = {
            "resource": self.resource,
            "source_generation": binding["generation"],
            "source_root": binding["root"],
            "target_epoch": binding["epoch"] + 1,
            "target_host": next_host,
        }
        from .semantic_translation import canonical_value_digest
        proposed["barrier_digest"] = canonical_value_digest({
            "schema": "mailcpu.ips008.effect-handoff.v1", **proposed,
        })
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                installed = db.execute(
                    "SELECT generation,root FROM installed_authority WHERE resource=?",
                    (self.resource,),
                ).fetchone()
                if installed != (binding["generation"], binding["root"]):
                    raise EffectFencingRefused("handoff source is not the installed receiver head")
                old = db.execute(
                    """SELECT source_generation,source_root,target_epoch,target_host,
                              barrier_digest FROM effect_handoffs WHERE resource=?""",
                    (self.resource,),
                ).fetchone()
                expected = tuple(proposed[k] for k in (
                    "source_generation","source_root","target_epoch",
                    "target_host","barrier_digest",
                ))
                if old is not None and old != expected:
                    raise EffectFencingRefused("another durable receiver handoff is pending")
                if old is None:
                    db.execute(
                        """INSERT INTO effect_handoffs
                           (resource,source_generation,source_root,target_epoch,
                            target_host,barrier_digest) VALUES (?,?,?,?,?,?)""",
                        (self.resource, *expected),
                    )
                db.execute("COMMIT")
                return proposed
            except BaseException:
                if db.in_transaction:
                    db.execute("ROLLBACK")
                raise

    def install(
        self, publisher: FencedGroundLineage, head: FencedGroundHead,
    ) -> dict[str, Any]:
        """Monotonically install a quorum-verified root at the effect receiver.

        All new writes and installations serialize through the SAME local DB
        writer lock. An older verified proof cannot roll back a newer installed
        generation, even if the caller changes during its quorum preflight.
        """
        binding = self._validated_binding(publisher, head)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                current = db.execute(
                    """SELECT generation, root FROM installed_authority
                       WHERE resource=?""", (self.resource,),
                ).fetchone()
                if current:
                    generation, root = current
                    pending = db.execute(
                        """SELECT source_generation,source_root,target_epoch,target_host
                           FROM effect_handoffs WHERE resource=?""", (self.resource,),
                    ).fetchone()
                    if pending is not None and binding["generation"] > generation:
                        source_generation,source_root,target_epoch,target_host = pending
                        if (current != (source_generation,source_root)
                                or binding["generation"] != source_generation + 1
                                or binding["predecessor_root"] != source_root
                                or binding["epoch"] != target_epoch
                                or binding["assignment_host"] != target_host
                                or binding["event"] not in ("assign","reassign")):
                            raise EffectFencingRefused("new quorum head does not satisfy prepared receiver handoff")
                    if binding["generation"] < generation:
                        raise EffectFencingRefused("receiver rejects stale installed generation")
                    if binding["generation"] == generation:
                        if root != binding["root"]:
                            raise EffectFencingRefused("conflicting installed quorum root")
                        db.execute("COMMIT")
                        return dict(binding)
                db.execute(
                    """INSERT INTO installed_authority
                       (resource,generation,root,plan_digest,checkpoint_digest,
                        epoch,stage,host,receipt_digest,expected_value,event)
                       VALUES (:resource,:generation,:root,:plan_digest,
                               :checkpoint_digest,:epoch,:stage,:host,
                               :receipt_digest,:expected_value,:event)
                       ON CONFLICT(resource) DO UPDATE SET
                           generation=excluded.generation,root=excluded.root,
                           plan_digest=excluded.plan_digest,
                           checkpoint_digest=excluded.checkpoint_digest,
                           epoch=excluded.epoch,stage=excluded.stage,
                           host=excluded.host,receipt_digest=excluded.receipt_digest,
                           expected_value=excluded.expected_value,event=excluded.event
                    """, binding,
                )
                db.execute(
                    "DELETE FROM effect_handoffs WHERE resource=?",
                    (self.resource,),
                )
                db.execute("COMMIT")
            except BaseException:
                if db.in_transaction:
                    db.execute("ROLLBACK")
                raise
        return dict(binding)

    def apply(self, claim: PublishedGroundEffect) -> dict[str, Any]:
        """Atomically reject stale publishers and apply one authorized value.

        The persistent register write, exact installed authority comparison,
        and semantic effect deduplication share one SQLite write transaction.
        No network/quorum check is made *outside* this transaction and then
        relied upon inside it; only the receiver's installed root is authority.
        """
        if not isinstance(claim, PublishedGroundEffect) or claim.resource != self.resource:
            raise EffectFencingRefused("receiver policy rejects effect resource")
        if claim.plan_digest != self.plan_digest:
            raise EffectFencingRefused("receiver policy rejects a different Ground plan")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                if db.execute(
                    "SELECT 1 FROM effect_handoffs WHERE resource=?",
                    (self.resource,),
                ).fetchone() is not None:
                    raise EffectFencingRefused("receiver handoff barrier blocks old effects")
                row = db.execute(
                    """SELECT generation,root,plan_digest,checkpoint_digest,
                              epoch,stage,host,receipt_digest,expected_value,event
                       FROM installed_authority WHERE resource=?""",
                    (self.resource,),
                ).fetchone()
                expected = (
                    claim.generation, claim.manifest_digest,
                    claim.plan_digest, claim.checkpoint_digest,
                    claim.epoch, claim.stage_index,
                    claim.host_id, claim.receipt_digest,
                    claim.value, "publish",
                )
                if row != expected:
                    raise EffectFencingRefused(
                        "stale, unpublished or mismatched receiver-side fencing token"
                    )
                earlier = db.execute(
                    "SELECT receipt_json FROM effect_log WHERE operation_id=?",
                    (claim.operation_id,),
                ).fetchone()
                if earlier:
                    receipt = json.loads(earlier[0])
                    db.execute("COMMIT")
                    return receipt
                receipt: dict[str, Any] = {
                    "schema": _SCHEMA, "operation_id": claim.operation_id,
                    "resource": claim.resource, "generation": claim.generation,
                    "root": claim.manifest_digest,
                    "checkpoint_digest": claim.checkpoint_digest,
                    "epoch": claim.epoch, "stage": claim.stage_index,
                    "host": claim.host_id, "receipt_digest": claim.receipt_digest,
                    "value": claim.value, "committed": True,
                    "physical_host_attested": False,
                    "quorum_snapshot_is_bearer_authority": False,
                }
                receipt["digest"] = canonical_value_digest(receipt)
                db.execute(
                    """INSERT INTO effect_log
                       (operation_id,resource,generation,root,stage,value,
                        receipt_digest,receipt_json) VALUES (?,?,?,?,?,?,?,?)""",
                    (claim.operation_id,claim.resource,claim.generation,
                     claim.manifest_digest,claim.stage_index,claim.value,
                     claim.receipt_digest,
                     json.dumps(receipt,sort_keys=True,separators=(",", ":"))),
                )
                db.execute(
                    """INSERT INTO registers(resource,value,operation_id)
                       VALUES (?,?,?)
                       ON CONFLICT(resource) DO UPDATE SET
                           value=excluded.value,operation_id=excluded.operation_id""",
                    (self.resource,claim.value,claim.operation_id),
                )
                db.execute("COMMIT")
                return receipt
            except BaseException:
                if db.in_transaction:
                    db.execute("ROLLBACK")
                raise

    def snapshot(self) -> dict[str, Any]:
        """Observe current local fencing state and stored register, not regrant rights."""
        with self._connect() as db:
            installed = db.execute(
                """SELECT generation,root,epoch,event,stage FROM
                   installed_authority WHERE resource=?""",
                (self.resource,),
            ).fetchone()
            register = db.execute(
                "SELECT value,operation_id FROM registers WHERE resource=?",
                (self.resource,),
            ).fetchone()
            barrier = db.execute(
                "SELECT barrier_digest FROM effect_handoffs WHERE resource=?",
                (self.resource,),
            ).fetchone()
            count = db.execute(
                "SELECT COUNT(*) FROM effect_log WHERE resource=?",
                (self.resource,),
            ).fetchone()[0]
        return {
            "resource": self.resource, "authorized_plan_digest": self.plan_digest,
            "installed_generation": installed[0] if installed else None,
            "installed_root": installed[1] if installed else None,
            "installed_epoch": installed[2] if installed else None,
            "installed_event": installed[3] if installed else None,
            "installed_stage": installed[4] if installed else None,
            "register_value": register[0] if register else None,
            "register_operation_id": register[1] if register else None,
            "accepted_effects": count,
            "pending_handoff_digest": barrier[0] if barrier else None,
        }
