"""NCB-006 — receiver-owned atomic reservations for constructed *pure* actions.

NCB-003 independently checks the mathematical possibility of each joint
controller operation and matches named, receiver-declared capacities. It does
not arbitrate TWO concurrent independently valid controllers. This optional
guard explicitly serializes actual shared capacity at ONE receiver-owned
SQLite database, reusing the same BEGIN IMMEDIATE/DURABLE receiver-local
transaction design used by IPS-007.

No NCP-002 packet imports authority, no sender can increase the installed
resource policy, no physical actuator is attested and no stateful external
effect can be committed through this pure-action wrapper. A process crash
retains its active reservation and FAILS CLOSED; no clock/lease timeout can
silently authorize a conflicting write. Manual reclamation requires an
additional owner/quorum protocol and is deliberately not implemented here.
"""
from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import secrets
import sqlite3
from typing import Any, Sequence

from .constructed_controller_admission import (
    CheckedCoupledController, ConstructedAction, CoupledControllerAdmissionError,
    NativeActionBinding, NativeResourceBinding, QualifiedConstructedStep,
    execute_constructed_action,
)
from .computational_resolver import ComputationalHostCatalogue
from .computational_execution import ComputationalExecutionAdmissionCoordinator


_SCHEMA = "mailcpu.ncb006.constructed-resource-reservations.v1"


class ConstructedResourceReservationRefused(CoupledControllerAdmissionError):
    """A real receiver-local capacity is unavailable or not qualified."""


def _canonical(value: Any) -> bytes:
    """Stable content identity for local observations, never an authority token."""
    return json.dumps(value, sort_keys=True, ensure_ascii=True,
                      separators=(",", ":"), allow_nan=False).encode("ascii")


def _digest(value: Any) -> str:
    return sha256(_canonical(value)).hexdigest()


@dataclass(frozen=True)
class _ReservationLease:
    """Private bearer for a LIVE local claim, not transported with its receipt."""

    token: str
    packet_digest: str
    action_digest: str
    reservation_receipt: dict[str,Any]


@dataclass(frozen=True)
class ReservedConstructedStep:
    """Verified native result with distinct non-authoritative capacity evidence."""

    execution: QualifiedConstructedStep
    reservation_receipt: dict[str,Any]
    release_receipt: dict[str,Any]
    digest: str

    def to_dict(self) -> dict[str,Any]:
        """Return a content receipt without exposing the active capability token."""
        return {
            "schema":"mailcpu.ncb006.reserved-pure-step.v1",
            "execution":self.execution.to_dict(),
            "reservation":dict(self.reservation_receipt),
            "release":dict(self.release_receipt),
            "digest":self.digest,
        }


class ReceiverOwnedResourceReservations:
    """One durable local resource authority shared by independently running hosts.

    All resource quantities across one action are acquired under the same
    SQLite writer lock, so neither concurrency nor a mixed resource set can
    partially oversubscribe. The database is explicitly installed by a
    receiver-owned application, not selected or configured by a Ground packet.
    """

    def __init__(
        self, database: str | Path, *,
        resources: Sequence[NativeResourceBinding],
    ) -> None:
        if (not isinstance(resources, Sequence)
                or any(not isinstance(r,NativeResourceBinding) for r in resources)):
            raise ConstructedResourceReservationRefused(
                "an exact independently provisioned receiver resource palette is required"
            )
        values=tuple(resources)
        if (len(values)!=len({r.name for r in values})
                or len(values)>64):
            raise ConstructedResourceReservationRefused(
                "receiver resource names must be unique and bounded"
            )
        self.path=Path(database)
        self.resources=tuple(sorted(values,key=lambda r:r.name))
        policy=[
            {"name":r.name,"capacity":r.capacity,
             "claims":[list(claim) for claim in r.claims]}
            for r in self.resources
        ]
        self._policy_json=_canonical({"schema":_SCHEMA,"resources":policy}).decode("ascii")
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with closing(self._connect()) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS constructed_resource_policy (
                    policy_key INTEGER PRIMARY KEY CHECK(policy_key=1),
                    policy_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS constructed_resource_leases (
                    token TEXT PRIMARY KEY,
                    packet_digest TEXT NOT NULL,
                    action_digest TEXT NOT NULL,
                    resource_units_json TEXT NOT NULL
                );
            """)
            db.execute("BEGIN IMMEDIATE")
            try:
                current=db.execute(
                    "SELECT policy_json FROM constructed_resource_policy WHERE policy_key=1"
                ).fetchone()
                if current is None:
                    db.execute(
                        "INSERT INTO constructed_resource_policy VALUES (1,?)",
                        (self._policy_json,),
                    )
                elif current[0]!=self._policy_json:
                    raise ConstructedResourceReservationRefused(
                        "installed receiver-owned resource policy differs"
                    )
                db.execute("COMMIT")
            except BaseException:
                if db.in_transaction:
                    db.execute("ROLLBACK")
                raise

    def _connect(self) -> sqlite3.Connection:
        """Use the same durable SQLite writer-barrier pattern as IPS-007."""
        db=sqlite3.connect(str(self.path),timeout=8,isolation_level=None)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        db.execute("PRAGMA busy_timeout=8000")
        return db

    def _requested_units(
        self, controller: CheckedCoupledController,
        action: ConstructedAction,
    ) -> dict[str,int]:
        """Reconcile independent receiver policy with *exact* source claims."""
        declared=tuple(sorted(controller.resources))
        installed=tuple(sorted(
            (r.name,r.capacity,r.claims) for r in self.resources
        ))
        if declared!=installed:
            raise ConstructedResourceReservationRefused(
                "constructed resource description is not independently installed"
            )
        return {
            r.name:sum((factor,name) in r.claims
                       for factor,name in enumerate(action.names)
                       if name is not None)
            for r in self.resources
        }

    def reserve(
        self, controller: CheckedCoupledController, state: tuple[int,...],
    ) -> _ReservationLease:
        """Atomically reserve ALL claimed resources or none; no silent expiry."""
        if not isinstance(controller,CheckedCoupledController):
            raise ConstructedResourceReservationRefused(
                "checked mathematical controller required"
            )
        action=controller.next_action(state)
        requested=self._requested_units(controller,action)
        token=secrets.token_hex(32)
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                rows=db.execute(
                    "SELECT resource_units_json FROM constructed_resource_leases"
                ).fetchall()
                if len(rows)>=1024:
                    raise ConstructedResourceReservationRefused(
                        "too many outstanding local reservations"
                    )
                used={r.name:0 for r in self.resources}
                for row in rows:
                    quantities=json.loads(row[0])
                    if (type(quantities) is not dict
                            or set(quantities)!=set(used)
                            or any(type(value) is not int or value<0
                                   for value in quantities.values())):
                        raise ConstructedResourceReservationRefused(
                            "persisted reservation accounting is invalid"
                        )
                    for name,value in quantities.items():
                        used[name]+=value
                for resource in self.resources:
                    if used[resource.name]+requested[resource.name]>resource.capacity:
                        raise ConstructedResourceReservationRefused(
                            "receiver resource capacity already reserved by another controller"
                        )
                db.execute(
                    """INSERT INTO constructed_resource_leases
                       (token,packet_digest,action_digest,resource_units_json)
                       VALUES (?,?,?,?)""",
                    (token,controller.packet_digest,action.digest,
                     _canonical(requested).decode("ascii")),
                )
                db.execute("COMMIT")
            except BaseException:
                if db.in_transaction:
                    db.execute("ROLLBACK")
                raise
        evidence={
            "schema":"mailcpu.ncb006.reservation.v1",
            "controller_digest":controller.packet_digest,
            "source_action_digest":action.digest,
            "resource_policy_digest":_digest(json.loads(self._policy_json)),
            "claimed_units":requested,
            "local_durable_reservation":True,
            "external_resource_attested":False,
        }
        evidence["digest"]=_digest(evidence)
        return _ReservationLease(token,controller.packet_digest,action.digest,evidence)

    def release(self, lease: _ReservationLease) -> dict[str,Any]:
        """Release only an exact live local token after completion/refusal.

        Tokens lost on hard process death remain installed until a separately
        authorized recovery mechanism exists. This is intentional fail-closed
        behavior; callers must not unlink or silently reclaim a busy database.
        """
        if (not isinstance(lease,_ReservationLease) or type(lease.token) is not str):
            raise ConstructedResourceReservationRefused(
                "live local reservation proof required"
            )
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                row=db.execute(
                    "SELECT packet_digest,action_digest FROM constructed_resource_leases WHERE token=?",
                    (lease.token,),
                ).fetchone()
                if row!=(lease.packet_digest,lease.action_digest):
                    raise ConstructedResourceReservationRefused(
                        "missing, stale, or different live reservation"
                    )
                result=db.execute(
                    "DELETE FROM constructed_resource_leases WHERE token=?",
                    (lease.token,),
                )
                if result.rowcount!=1:
                    raise ConstructedResourceReservationRefused(
                        "reservation release was not atomic"
                    )
                db.execute("COMMIT")
            except BaseException:
                if db.in_transaction:
                    db.execute("ROLLBACK")
                raise
        record={
            "schema":"mailcpu.ncb006.release.v1",
            "reservation_digest":lease.reservation_receipt["digest"],
            "released":True,
        }
        record["digest"]=_digest(record)
        return record

    def snapshot(self) -> dict[str,Any]:
        """Expose only aggregate occupancy, not bearer reservation tokens."""
        with closing(self._connect()) as db:
            db.execute("BEGIN")
            try:
                quantities={r.name:0 for r in self.resources}
                rows=db.execute(
                    "SELECT resource_units_json FROM constructed_resource_leases"
                ).fetchall()
                for row in rows:
                    values=json.loads(row[0])
                    for name in quantities:
                        quantities[name]+=values[name]
                db.execute("COMMIT")
            except BaseException:
                if db.in_transaction:
                    db.execute("ROLLBACK")
                raise
        result={
            "schema":_SCHEMA,
            "resource_policy_digest":_digest(json.loads(self._policy_json)),
            "active_lease_count":len(rows),
            "occupied_units":quantities,
            "crash_reclamation_supported":False,
        }
        result["digest"]=_digest(result)
        return result


def execute_reserved_constructed_action(
    controller: CheckedCoupledController,
    state: tuple[int,...],
    bindings: Sequence[NativeActionBinding],
    catalogue: ComputationalHostCatalogue,
    coordinator: ComputationalExecutionAdmissionCoordinator,
    *,
    reservations: ReceiverOwnedResourceReservations,
    source: str="ncb006-constructed-controller",
    sequence: int=1,
) -> ReservedConstructedStep:
    """Execute pure native steps only while holding the receiver's real claim.

    This is a separate opted-in pathway; the historical NCB-003 helper still
    performs only STATIC per-controller capacity checks. A failed host
    resolution or Hypervisor admission releases the claim in finally.
    Because these operators are *pure*, releasing on regular failure is safe.
    The receiver never auto-releases an orphan after a hard crash.
    """
    if not isinstance(reservations,ReceiverOwnedResourceReservations):
        raise ConstructedResourceReservationRefused(
            "durable receiver-owned resource admission is required"
        )
    lease=reservations.reserve(controller,state)
    try:
        step=execute_constructed_action(
            controller,state,bindings,catalogue,coordinator,
            resources=reservations.resources,source=source,sequence=sequence,
        )
    finally:
        released=reservations.release(lease)
    body={
        "schema":"mailcpu.ncb006.reserved-pure-step.v1",
        "execution":step.to_dict(),
        "reservation":lease.reservation_receipt,
        "release":released,
    }
    return ReservedConstructedStep(
        execution=step,reservation_receipt=lease.reservation_receipt,
        release_receipt=released,digest=_digest(body),
    )
