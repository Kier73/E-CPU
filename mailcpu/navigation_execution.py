"""Crash-recoverable execution of hypervisor-admitted declarative navigation paths.

This adapter does not mutate arbitrary MailCPU subsystems directly. It replays
the authorized path against trusted live state, then delegates one atomic,
idempotent compare-and-swap commit to the host that owns that state.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Mapping

from .classifier import HypervisorAction, HypervisorDomain
from .navigation import (
    ProcessContext,
    ProcessDescriptor,
    SemanticAddress,
    evaluate_readiness,
)
from .navigation_admission import (
    NavigationAdmissionResult,
    NavigationAdmissionStatus,
    NavigationExecutionGrant,
)


class NavigationExecutionError(ValueError):
    """An execution adapter, grant, backend receipt, or callback contract is malformed."""


class NavigationExecutionStatus(str, Enum):
    """Terminal observation of one admitted declarative path execution."""

    EXECUTED = "executed"
    REPLAYED = "replayed"
    RECOVERED = "recovered"
    REFUSED_ADMISSION = "refused_admission"
    REFUSED_PROVENANCE = "refused_provenance"
    REFUSED_EXPIRED = "refused_expired"
    REFUSED_PROCESS = "refused_process"
    REFUSED_CAPABILITY = "refused_capability"
    REFUSED_CONTEXT = "refused_context"
    REFUSED_PATH = "refused_path"
    COMMIT_CONFLICT = "commit_conflict"
    COMMIT_UNVERIFIED = "commit_unverified"
    INDETERMINATE = "indeterminate"


def _canonical_bytes(value: Any) -> bytes:
    """Mathematics: encode finite JSON value x as unique compact sorted UTF-8 bytes J(x)."""
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise NavigationExecutionError(f"value is outside canonical JSON: {exc}") from exc


def _plain(value: Any) -> Any:
    """Mathematics: project nested immutable JSON mappings and sequences into canonical mutable JSON values."""
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_plain(item) for item in value)
    return value


def _digest(value: Any) -> str:
    """Mathematics: calculate H(x)=SHA256(J(x)) for a canonical JSON value."""
    return hashlib.sha256(_canonical_bytes(_plain(value))).hexdigest()


def _valid_digest(value: Any) -> bool:
    """Mathematics: test membership in the lowercase 256-bit hexadecimal identity domain."""
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _context_digest(context: ProcessContext) -> str:
    """Mathematics: reproduce the coordinator's full context identity, including state and temporal frame."""
    frame = None if context.temporal_frame is None else context.temporal_frame.to_dict()
    return _digest(
        {
            "process_id": context.process_id,
            "current_state": None if context.current_state is None else _plain(context.current_state),
            "bindings": _plain(context.bindings),
            "resolved_dependencies": sorted(context.resolved_dependencies),
            "resource_capacity": dict(context.resource_capacity),
            "capabilities": sorted(context.capabilities),
            "max_expansions": context.max_expansions,
            "max_depth": context.max_depth,
            "temporal_frame": frame,
        }
    )


def _state_digest(state: Mapping[str, Any]) -> str:
    """Mathematics: identify one concrete process state by its canonical JSON image."""
    return _digest(dict(state))


@dataclass(frozen=True)
class NavigationCommitReceipt:
    """Backend-issued receipt for one atomic and idempotent state compare-and-swap."""

    execution_id: str
    committed: bool
    start_state_digest: str
    final_state_digest: str
    backend_revision: int
    replayed: bool = False
    reason: str | None = None

    def __post_init__(self) -> None:
        """Mathematics: bind the CAS outcome to one stable key, two state identities, and one backend version."""
        if not _valid_digest(self.execution_id):
            raise NavigationExecutionError("commit execution_id must be lowercase SHA-256 hex")
        for name in ("start_state_digest", "final_state_digest"):
            if not _valid_digest(getattr(self, name)):
                raise NavigationExecutionError(f"commit {name} must be lowercase SHA-256 hex")
        if not isinstance(self.committed, bool) or not isinstance(self.replayed, bool):
            raise NavigationExecutionError("commit flags must be Boolean")
        if not isinstance(self.backend_revision, int) or isinstance(self.backend_revision, bool) or self.backend_revision < 0:
            raise NavigationExecutionError("backend_revision must be a non-negative integer")
        if self.committed and self.backend_revision < 1:
            raise NavigationExecutionError("a committed state requires a positive backend revision")
        if self.reason is not None and (not isinstance(self.reason, str) or not self.reason):
            raise NavigationExecutionError("commit reason must be non-empty text or absent")

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize the backend CAS result without exposing mutable backend state."""
        return {
            "execution_id": self.execution_id,
            "committed": self.committed,
            "start_state_digest": self.start_state_digest,
            "final_state_digest": self.final_state_digest,
            "backend_revision": self.backend_revision,
            "replayed": self.replayed,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> NavigationCommitReceipt:
        """Mathematics: reconstruct a backend receipt only from its exact typed projection."""
        keys = {
            "execution_id",
            "committed",
            "start_state_digest",
            "final_state_digest",
            "backend_revision",
            "replayed",
            "reason",
        }
        if not isinstance(payload, Mapping) or set(payload) != keys:
            raise NavigationExecutionError("commit receipt fields are invalid")
        return cls(
            payload["execution_id"],
            payload["committed"],
            payload["start_state_digest"],
            payload["final_state_digest"],
            payload["backend_revision"],
            payload["replayed"],
            payload["reason"],
        )


@dataclass(frozen=True)
class NavigationExecutionResult:
    """Auditable execution outcome distinct from both an admission decision and a state commit."""

    status: NavigationExecutionStatus
    execution_id: str
    grant_digest: str
    start_state_digest: str
    target_state_digest: str
    transition_ids: tuple[str, ...]
    commit_receipt: NavigationCommitReceipt | None
    execution_receipt: str | None
    journal_receipt: str | None
    reason: str | None
    replayed: bool

    def __post_init__(self) -> None:
        """Mathematics: require complete identities and prohibit successful results without a committed backend receipt."""
        if not isinstance(self.status, NavigationExecutionStatus):
            raise NavigationExecutionError("execution status is invalid")
        for name in ("execution_id", "grant_digest", "start_state_digest", "target_state_digest"):
            if not _valid_digest(getattr(self, name)):
                raise NavigationExecutionError(f"{name} must be lowercase SHA-256 hex")
        if not isinstance(self.transition_ids, (tuple, list)) or any(
            not isinstance(item, str) or not item for item in self.transition_ids
        ):
            raise NavigationExecutionError("transition_ids must be a finite sequence of non-empty strings")
        object.__setattr__(self, "transition_ids", tuple(self.transition_ids))
        if self.commit_receipt is not None and not isinstance(self.commit_receipt, NavigationCommitReceipt):
            raise NavigationExecutionError("commit_receipt is malformed")
        if self.execution_receipt is not None and not _valid_digest(self.execution_receipt):
            raise NavigationExecutionError("execution_receipt must be lowercase SHA-256 hex")
        if self.journal_receipt is not None and not _valid_digest(self.journal_receipt):
            raise NavigationExecutionError("journal_receipt must be lowercase SHA-256 hex")
        if not isinstance(self.replayed, bool):
            raise NavigationExecutionError("replayed must be Boolean")
        successful = self.status in {
            NavigationExecutionStatus.EXECUTED,
            NavigationExecutionStatus.REPLAYED,
            NavigationExecutionStatus.RECOVERED,
        }
        if successful:
            if (
                self.commit_receipt is None
                or not self.commit_receipt.committed
                or self.execution_receipt is None
                or self.journal_receipt != self.execution_receipt
            ):
                raise NavigationExecutionError("successful execution requires a committed backend and journal receipt")
        if self.status is NavigationExecutionStatus.REPLAYED and not self.replayed:
            raise NavigationExecutionError("REPLAYED status requires replayed=true")
        if self.status is NavigationExecutionStatus.EXECUTED and self.replayed:
            raise NavigationExecutionError("EXECUTED status cannot describe a replay")

    @property
    def completed(self) -> bool:
        """Mathematics: project completion onto the successful execution equivalence classes."""
        return self.status in {
            NavigationExecutionStatus.EXECUTED,
            NavigationExecutionStatus.REPLAYED,
            NavigationExecutionStatus.RECOVERED,
        }

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize execution evidence without conflating a plan, grant, backend commit, or journal receipt."""
        return {
            "schema": "mailcpu.navigation-execution-result.v1",
            "status": self.status.value,
            "completed": self.completed,
            "execution_id": self.execution_id,
            "grant_digest": self.grant_digest,
            "start_state_digest": self.start_state_digest,
            "target_state_digest": self.target_state_digest,
            "transition_ids": list(self.transition_ids),
            "commit_receipt": None if self.commit_receipt is None else self.commit_receipt.to_dict(),
            "execution_receipt": self.execution_receipt,
            "journal_receipt": self.journal_receipt,
            "reason": self.reason,
            "replayed": self.replayed,
        }


class HypervisorNavigationExecutionAdapter:
    """Verify an admitted grant, replay its exact path, and perform one host-owned atomic commit."""

    def __init__(
        self,
        operating_system: Any,
        state_provider: Callable[[int, ProcessDescriptor, SemanticAddress], ProcessContext],
        commit_callback: Callable[
            [int, str, str, Mapping[str, Any], NavigationExecutionGrant],
            NavigationCommitReceipt,
        ],
        commit_lookup: Callable[[str], NavigationCommitReceipt | None],
    ) -> None:
        """Mathematics: bind execution to one OS journal, live state projection, idempotent backend CAS, and receipt lookup."""
        vm = getattr(operating_system, "vm", None)
        if vm is None or not hasattr(vm, "scheduler"):
            raise NavigationExecutionError("operating_system must expose the deterministic VM scheduler")
        if not callable(state_provider):
            raise NavigationExecutionError("a trusted live state_provider is required")
        if not callable(commit_callback):
            raise NavigationExecutionError("an atomic idempotent commit_callback is required")
        if not callable(commit_lookup):
            raise NavigationExecutionError("a durable commit_lookup by execution_id is required for crash recovery")
        self.operating_system = operating_system
        self.state_provider = state_provider
        self.commit_callback = commit_callback
        self.commit_lookup = commit_lookup

    def _journal(self):
        """Mathematics: resolve the single append-only journal shared by the kernel and hypervisor."""
        try:
            journal = self.operating_system.environment.kernel.journal
        except AttributeError as exc:
            raise NavigationExecutionError("operating system has no kernel journal") from exc
        if not callable(getattr(journal, "records", None)) or not callable(getattr(journal, "verify", None)):
            raise NavigationExecutionError("operating system journal lacks records/verify support")
        return journal

    @staticmethod
    def _execution_id(grant: NavigationExecutionGrant) -> str:
        """Mathematics: derive stable idempotency identity E=H(schema || grant_digest)."""
        return _digest(
            {
                "schema": "mailcpu.navigation-execution.v1",
                "grant_digest": grant.digest,
            }
        )

    def _verify_admission_provenance(
        self,
        admission: NavigationAdmissionResult,
        grant: NavigationExecutionGrant,
    ) -> tuple[bool, str | None]:
        """Mathematics: require a valid journal chain linking ALLOW, arbitration acceptance, and the exact grant."""
        if not isinstance(admission, NavigationAdmissionResult) or not admission.accepted:
            return False, "admission result is not successful"
        if admission.grant is None or admission.grant.digest != grant.digest:
            return False, "admission result does not carry this grant"
        if admission.action is not HypervisorAction.ALLOW or admission.domain is not HypervisorDomain.CPU:
            return False, "admission result is not an ALLOW decision in the CPU domain"
        if admission.decision_receipt != grant.decision_receipt:
            return False, "admission decision receipt does not match the grant"

        journal = self._journal()
        if not journal.verify():
            return False, "kernel/hypervisor journal hash chain is invalid"
        records = journal.records()
        admission_record = next(
            (
                item for item in records
                if item.digest == admission.admission_receipt
                and item.kind == "hypervisor.navigation.admit"
            ),
            None,
        )
        if admission_record is None:
            return False, "admission receipt is absent from the verified journal"
        payload = admission_record.payload
        if (
            payload.get("grant_digest") != grant.digest
            or payload.get("grant") != grant.to_dict()
            or payload.get("decision_receipt") != grant.decision_receipt
            or payload.get("coordination_digest") != grant.coordination_digest
            or payload.get("replayed") is not admission.replayed
        ):
            return False, "journal admission record does not bind this grant and result"

        decision_record = next(
            (
                item for item in records
                if item.digest == grant.decision_receipt and item.kind == "hypervisor.decision"
            ),
            None,
        )
        if decision_record is None:
            return False, "hypervisor decision receipt is absent from the verified journal"
        if (
            decision_record.payload.get("action") != HypervisorAction.ALLOW.value
            or decision_record.payload.get("domain") != HypervisorDomain.CPU.value
            or decision_record.payload.get("revision") != grant.decision_revision
        ):
            return False, "journal decision does not authorize this CPU grant"

        fingerprint = payload.get("arbitration_fingerprint")
        arbitration_record = next(
            (
                item for item in records
                if item.kind == "hypervisor.arbitration.accept"
                and item.payload.get("source") == grant.source
                and item.payload.get("channel") == grant.channel
                and item.payload.get("sequence") == grant.sequence
                and item.payload.get("fingerprint") == fingerprint
                and item.payload.get("decision_receipt") == grant.decision_receipt
                and item.payload.get("decision_revision") == grant.decision_revision
            ),
            None,
        )
        if arbitration_record is None:
            return False, "matching hypervisor arbitration acceptance is absent"
        if not decision_record.sequence < arbitration_record.sequence < admission_record.sequence:
            return False, "decision, arbitration, and admission receipts are not causally ordered"
        if arbitration_record.payload.get("logical_time") != grant.issued_at_tick:
            return False, "arbitration tick does not match grant issue tick"
        return True, None

    def _read_context(
        self,
        grant: NavigationExecutionGrant,
        descriptor: ProcessDescriptor,
        address: SemanticAddress,
    ) -> ProcessContext:
        """Mathematics: request one typed live state projection scoped to the grant PID and semantic process."""
        context = self.state_provider(grant.pid, descriptor, address)
        if not isinstance(context, ProcessContext):
            raise NavigationExecutionError("state_provider did not return ProcessContext")
        if context.process_id != grant.process_id:
            raise NavigationExecutionError("live context process identity does not match grant")
        return context

    def _refuse(
        self,
        status: NavigationExecutionStatus,
        execution_id: str,
        grant: NavigationExecutionGrant,
        reason: str,
        *,
        replayed: bool = False,
        start_state_digest: str | None = None,
    ) -> NavigationExecutionResult:
        """Mathematics: append one typed refusal to the shared journal without calling the backend commit."""
        actual_start = start_state_digest or grant.start_state_digest
        journal = self._journal()
        receipt = None
        if journal.verify():
            receipt = journal.append(
                "hypervisor.navigation.execute.refuse",
                {
                    "execution_id": execution_id,
                    "grant_digest": grant.digest,
                    "status": status.value,
                    "reason": reason,
                    "start_state_digest": actual_start,
                    "target_state_digest": grant.final_state_digest,
                    "replayed": replayed,
                },
            ).digest
        return NavigationExecutionResult(
            status,
            execution_id,
            grant.digest,
            actual_start,
            grant.final_state_digest,
            grant.transition_ids,
            None,
            None,
            receipt,
            reason,
            replayed,
        )

    def _completed_replay(
        self,
        execution_id: str,
        grant: NavigationExecutionGrant,
    ) -> NavigationExecutionResult | None:
        """Mathematics: recover a completed execution only from its exact prior journal commit record."""
        records = self._journal().records()
        matches = [
            item for item in records
            if item.kind == "hypervisor.navigation.execute.commit"
            and item.payload.get("execution_id") == execution_id
        ]
        if not matches:
            return None
        record = matches[-1]
        payload = record.payload
        if payload.get("grant_digest") != grant.digest:
            raise NavigationExecutionError("execution identity is already bound to a different grant")
        raw_receipt = payload.get("commit_receipt")
        if not isinstance(raw_receipt, Mapping):
            raise NavigationExecutionError("completed execution record has no backend receipt")
        receipt = NavigationCommitReceipt.from_dict(raw_receipt)
        if (
            not receipt.committed
            or receipt.execution_id != execution_id
            or receipt.start_state_digest != grant.start_state_digest
            or receipt.final_state_digest != grant.final_state_digest
            or payload.get("target_state_digest") != grant.final_state_digest
        ):
            raise NavigationExecutionError("completed execution receipt does not match the grant")
        return NavigationExecutionResult(
            NavigationExecutionStatus.REPLAYED,
            execution_id,
            grant.digest,
            grant.start_state_digest,
            grant.final_state_digest,
            grant.transition_ids,
            receipt,
            record.digest,
            record.digest,
            None,
            True,
        )

    def _recover_backend_commit(
        self,
        execution_id: str,
        grant: NavigationExecutionGrant,
        admission: NavigationAdmissionResult,
    ) -> NavigationExecutionResult | None:
        """Mathematics: reconcile a prior write-ahead intent through the backend's durable idempotency receipt."""
        begin = next(
            (
                item for item in self._journal().records()
                if item.kind == "hypervisor.navigation.execute.begin"
                and item.payload.get("execution_id") == execution_id
            ),
            None,
        )
        if begin is None:
            return None
        if begin.payload.get("grant_digest") != grant.digest:
            raise NavigationExecutionError("write-ahead execution identity is bound to another grant")
        try:
            receipt = self.commit_lookup(execution_id)
        except Exception as exc:
            record = self._journal().append(
                "hypervisor.navigation.execute.uncertain",
                {
                    "execution_id": execution_id,
                    "grant_digest": grant.digest,
                    "reason": f"backend receipt lookup failed: {type(exc).__name__}: {exc}",
                },
            )
            return NavigationExecutionResult(
                NavigationExecutionStatus.INDETERMINATE,
                execution_id,
                grant.digest,
                grant.start_state_digest,
                grant.final_state_digest,
                grant.transition_ids,
                None,
                None,
                record.digest,
                "backend commit status is unknown; retry receipt lookup using the same execution ID",
                True,
            )
        if receipt is None:
            return None
        if not isinstance(receipt, NavigationCommitReceipt):
            record = self._journal().append(
                "hypervisor.navigation.execute.uncertain",
                {
                    "execution_id": execution_id,
                    "grant_digest": grant.digest,
                    "reason": "backend receipt lookup returned an untyped value",
                },
            )
            return NavigationExecutionResult(
                NavigationExecutionStatus.INDETERMINATE,
                execution_id,
                grant.digest,
                grant.start_state_digest,
                grant.final_state_digest,
                grant.transition_ids,
                None,
                None,
                record.digest,
                "backend receipt lookup is untyped",
                True,
            )
        if (
            receipt.execution_id != execution_id
            or receipt.start_state_digest != grant.start_state_digest
        ):
            record = self._journal().append(
                "hypervisor.navigation.execute.uncertain",
                {
                    "execution_id": execution_id,
                    "grant_digest": grant.digest,
                    "reason": "backend's durable receipt does not identify the admitted state transition",
                    "commit_receipt": receipt.to_dict(),
                },
            )
            return NavigationExecutionResult(
                NavigationExecutionStatus.COMMIT_UNVERIFIED,
                execution_id,
                grant.digest,
                grant.start_state_digest,
                grant.final_state_digest,
                grant.transition_ids,
                receipt,
                None,
                record.digest,
                "backend's durable receipt does not match the grant",
                receipt.replayed,
            )
        if not receipt.committed:
            record = self._journal().append(
                "hypervisor.navigation.execute.refuse",
                {
                    "execution_id": execution_id,
                    "grant_digest": grant.digest,
                    "status": NavigationExecutionStatus.COMMIT_CONFLICT.value,
                    "reason": receipt.reason or "backend durably rejected the compare-and-swap",
                    "commit_receipt": receipt.to_dict(),
                    "recovered": True,
                },
            )
            return NavigationExecutionResult(
                NavigationExecutionStatus.COMMIT_CONFLICT,
                execution_id,
                grant.digest,
                grant.start_state_digest,
                grant.final_state_digest,
                grant.transition_ids,
                receipt,
                None,
                record.digest,
                receipt.reason or "backend durably rejected the compare-and-swap",
                True,
            )
        if receipt.final_state_digest != grant.final_state_digest:
            record = self._journal().append(
                "hypervisor.navigation.execute.uncertain",
                {
                    "execution_id": execution_id,
                    "grant_digest": grant.digest,
                    "reason": "backend committed a different final state",
                    "commit_receipt": receipt.to_dict(),
                },
            )
            return NavigationExecutionResult(
                NavigationExecutionStatus.COMMIT_UNVERIFIED,
                execution_id,
                grant.digest,
                grant.start_state_digest,
                grant.final_state_digest,
                grant.transition_ids,
                receipt,
                None,
                record.digest,
                "backend committed a final state different from the authorized target",
                receipt.replayed,
            )
        record = self._journal().append(
            "hypervisor.navigation.execute.commit",
            {
                "execution_id": execution_id,
                "grant_digest": grant.digest,
                "admission_receipt": begin.payload.get("admission_receipt"),
                "decision_receipt": grant.decision_receipt,
                "transition_ids": list(grant.transition_ids),
                "start_state_digest": grant.start_state_digest,
                "target_state_digest": grant.final_state_digest,
                "commit_receipt": receipt.to_dict(),
                "recovered_backend_commit": True,
            },
        )
        return NavigationExecutionResult(
            NavigationExecutionStatus.RECOVERED,
            execution_id,
            grant.digest,
            grant.start_state_digest,
            grant.final_state_digest,
            grant.transition_ids,
            receipt,
            record.digest,
            record.digest,
            None,
            True,
        )

    def _ensure_begin_record(
        self,
        execution_id: str,
        grant: NavigationExecutionGrant,
        admission: NavigationAdmissionResult,
    ) -> None:
        """Mathematics: append one write-ahead intent before backend mutation, preserving one idempotency key across recovery."""
        records = self._journal().records()
        existing = next(
            (
                item for item in records
                if item.kind == "hypervisor.navigation.execute.begin"
                and item.payload.get("execution_id") == execution_id
            ),
            None,
        )
        if existing is not None:
            if (
                existing.payload.get("grant_digest") != grant.digest
            ):
                raise NavigationExecutionError("execution begin identity is bound to different admission evidence")
            return
        self._journal().append(
            "hypervisor.navigation.execute.begin",
            {
                "execution_id": execution_id,
                "grant_digest": grant.digest,
                "admission_receipt": admission.admission_receipt,
                "pid": grant.pid,
                "issued_at_tick": grant.issued_at_tick,
                "expires_at_tick": grant.expires_at_tick,
                "maximum_steps": grant.maximum_steps,
                "transition_ids": list(grant.transition_ids),
                "start_state_digest": grant.start_state_digest,
                "target_state_digest": grant.final_state_digest,
            },
        )

    def execute(
        self,
        admission: NavigationAdmissionResult,
        descriptor: ProcessDescriptor,
        address: SemanticAddress,
    ) -> NavigationExecutionResult:
        """Mathematics: verify provenance, replay δ^path, CAS from the bound start, and journal the final state receipt."""
        if not isinstance(admission, NavigationAdmissionResult) or admission.grant is None:
            raise NavigationExecutionError("execution requires a successful NavigationAdmissionResult")
        if not isinstance(descriptor, ProcessDescriptor) or not isinstance(address, SemanticAddress):
            raise NavigationExecutionError("execution requires a ProcessDescriptor and SemanticAddress")
        grant = admission.grant
        execution_id = self._execution_id(grant)

        if (
            admission.status not in {NavigationAdmissionStatus.ADMITTED, NavigationAdmissionStatus.REPLAYED}
            or not admission.accepted
            or grant.authoritative is not True
            or grant.pid <= 0
            or grant.domain is not HypervisorDomain.CPU
        ):
            return self._refuse(
                NavigationExecutionStatus.REFUSED_ADMISSION,
                execution_id,
                grant,
                "admission result is not an authoritative CPU grant",
                replayed=admission.replayed,
            )
        if (
            descriptor.digest != grant.descriptor_digest
            or address.digest != grant.address_digest
            or descriptor.process_id != grant.process_id
            or address.process_id != grant.process_id
            or descriptor.version != address.version
        ):
            return self._refuse(
                NavigationExecutionStatus.REFUSED_PATH,
                execution_id,
                grant,
                "descriptor or semantic address differs from the admitted grant",
                replayed=admission.replayed,
            )

        try:
            provenance_ok, provenance_error = self._verify_admission_provenance(admission, grant)
        except Exception as exc:
            provenance_ok, provenance_error = False, f"{type(exc).__name__}: {exc}"
        if not provenance_ok:
            return self._refuse(
                NavigationExecutionStatus.REFUSED_PROVENANCE,
                execution_id,
                grant,
                provenance_error or "admission provenance is invalid",
                replayed=admission.replayed,
            )

        try:
            replay = self._completed_replay(execution_id, grant)
        except Exception as exc:
            return self._refuse(
                NavigationExecutionStatus.REFUSED_PROVENANCE,
                execution_id,
                grant,
                f"completed execution record is invalid: {type(exc).__name__}: {exc}",
                replayed=admission.replayed,
            )
        if replay is not None:
            return replay
        try:
            recovered = self._recover_backend_commit(execution_id, grant, admission)
        except Exception as exc:
            return self._refuse(
                NavigationExecutionStatus.REFUSED_PROVENANCE,
                execution_id,
                grant,
                f"backend recovery evidence is invalid: {type(exc).__name__}: {exc}",
                replayed=admission.replayed,
            )
        if recovered is not None:
            return recovered

        try:
            process = self.operating_system.environment.kernel._process(grant.pid)
        except Exception as exc:
            return self._refuse(
                NavigationExecutionStatus.REFUSED_PROCESS,
                execution_id,
                grant,
                f"target process is unavailable: {type(exc).__name__}: {exc}",
                replayed=admission.replayed,
            )
        if getattr(getattr(process, "status", None), "value", getattr(process, "status", None)) == "exited":
            return self._refuse(
                NavigationExecutionStatus.REFUSED_PROCESS,
                execution_id,
                grant,
                "exited process cannot execute a navigation grant",
                replayed=admission.replayed,
            )
        if any(
            not any(capability.allows(grant.resource, right) for capability in process.capabilities)
            for right in grant.required_rights
        ):
            return self._refuse(
                NavigationExecutionStatus.REFUSED_CAPABILITY,
                execution_id,
                grant,
                "one or more grant rights are no longer present on the live kernel process",
                replayed=admission.replayed,
            )

        try:
            scheduler_tick = self.operating_system.vm.scheduler.tick
        except Exception as exc:
            return self._refuse(
                NavigationExecutionStatus.REFUSED_EXPIRED,
                execution_id,
                grant,
                f"scheduler tick is unavailable: {type(exc).__name__}: {exc}",
                replayed=admission.replayed,
            )
        if not grant.valid_at(scheduler_tick):
            return self._refuse(
                NavigationExecutionStatus.REFUSED_EXPIRED,
                execution_id,
                grant,
                "grant is outside its half-open scheduler-tick validity interval",
                replayed=admission.replayed,
            )

        try:
            context = self._read_context(grant, descriptor, address)
        except Exception as exc:
            return self._refuse(
                NavigationExecutionStatus.REFUSED_CONTEXT,
                execution_id,
                grant,
                f"live process context is unavailable: {type(exc).__name__}: {exc}",
                replayed=admission.replayed,
            )
        if (
            _context_digest(context) != grant.context_digest
            or context.current_state is None and descriptor.initial_state is None
        ):
            return self._refuse(
                NavigationExecutionStatus.REFUSED_CONTEXT,
                execution_id,
                grant,
                "complete live context no longer matches the admitted context",
                replayed=admission.replayed,
            )
        start_state = (
            dict(context.current_state)
            if context.current_state is not None
            else dict(descriptor.initial_state or {})
        )
        actual_start_digest = _state_digest(start_state)
        if actual_start_digest != grant.start_state_digest:
            return self._refuse(
                NavigationExecutionStatus.REFUSED_CONTEXT,
                execution_id,
                grant,
                "live starting state differs from the grant's starting-state digest",
                replayed=admission.replayed,
                start_state_digest=actual_start_digest,
            )
        if not descriptor.admits(start_state, context.bindings):
            return self._refuse(
                NavigationExecutionStatus.REFUSED_CONTEXT,
                execution_id,
                grant,
                "starting state violates a declared process invariant",
                replayed=admission.replayed,
                start_state_digest=actual_start_digest,
            )
        readiness = evaluate_readiness(descriptor, context)
        if not readiness.ready:
            return self._refuse(
                NavigationExecutionStatus.REFUSED_CONTEXT,
                execution_id,
                grant,
                "process readiness no longer holds: " + ", ".join(readiness.blockers),
                replayed=admission.replayed,
                start_state_digest=actual_start_digest,
            )
        if len(grant.transition_ids) != grant.maximum_steps or grant.maximum_steps > context.max_depth:
            return self._refuse(
                NavigationExecutionStatus.REFUSED_PATH,
                execution_id,
                grant,
                "path length exceeds the grant or live context step bound",
                replayed=admission.replayed,
                start_state_digest=actual_start_digest,
            )

        rules = {rule.transition_id: rule for rule in descriptor.transitions}
        state: Mapping[str, Any] = start_state
        envelope: dict[str, int] = {}
        try:
            for transition_id in grant.transition_ids:
                rule = rules.get(transition_id)
                if rule is None or not rule.enabled(state, context.bindings):
                    raise NavigationExecutionError(f"transition is missing or disabled: {transition_id}")
                for name, required in rule.resource_requirements.items():
                    if context.resource_capacity.get(name, 0) < required:
                        raise NavigationExecutionError(f"resource capacity is insufficient: {name}")
                    envelope[name] = max(envelope.get(name, 0), required)
                state = rule.apply(state, context.bindings)
                if not descriptor.admits(state, context.bindings):
                    raise NavigationExecutionError(f"transition violates a process invariant: {transition_id}")
            if not address.goal.matches(state, context.bindings):
                raise NavigationExecutionError("replayed path does not satisfy the semantic goal")
            candidate_state = dict(state)
            target_digest = _state_digest(candidate_state)
            if target_digest != grant.final_state_digest:
                raise NavigationExecutionError("replayed final state differs from the admitted target digest")
            if tuple(sorted(envelope.items())) != grant.resource_envelope:
                raise NavigationExecutionError("replayed resource envelope differs from the grant")
        except Exception as exc:
            return self._refuse(
                NavigationExecutionStatus.REFUSED_PATH,
                execution_id,
                grant,
                f"path replay failed: {type(exc).__name__}: {exc}",
                replayed=admission.replayed,
                start_state_digest=actual_start_digest,
            )

        # Re-sample the scheduler immediately before the CAS to avoid committing after expiry.
        scheduler_tick = self.operating_system.vm.scheduler.tick
        if not grant.valid_at(scheduler_tick):
            return self._refuse(
                NavigationExecutionStatus.REFUSED_EXPIRED,
                execution_id,
                grant,
                "grant expired before the backend compare-and-swap",
                replayed=admission.replayed,
                start_state_digest=actual_start_digest,
            )

        try:
            self._ensure_begin_record(execution_id, grant, admission)
        except Exception as exc:
            return self._refuse(
                NavigationExecutionStatus.REFUSED_PROVENANCE,
                execution_id,
                grant,
                f"cannot establish execution write-ahead intent: {type(exc).__name__}: {exc}",
                replayed=admission.replayed,
                start_state_digest=actual_start_digest,
            )

        try:
            commit = self.commit_callback(
                grant.pid,
                execution_id,
                grant.start_state_digest,
                copy.deepcopy(candidate_state),
                grant,
            )
        except Exception as exc:
            record = self._journal().append(
                "hypervisor.navigation.execute.uncertain",
                {
                    "execution_id": execution_id,
                    "grant_digest": grant.digest,
                    "error": f"{type(exc).__name__}: {exc}",
                    "start_state_digest": grant.start_state_digest,
                    "target_state_digest": target_digest,
                },
            )
            return NavigationExecutionResult(
                NavigationExecutionStatus.INDETERMINATE,
                execution_id,
                grant.digest,
                grant.start_state_digest,
                target_digest,
                grant.transition_ids,
                None,
                None,
                record.digest,
                "backend outcome is indeterminate; retry with the same idempotency key: "
                + f"{type(exc).__name__}: {exc}",
                False,
            )
        if not isinstance(commit, NavigationCommitReceipt):
            record = self._journal().append(
                "hypervisor.navigation.execute.uncertain",
                {
                    "execution_id": execution_id,
                    "grant_digest": grant.digest,
                    "reason": "backend returned an untyped commit receipt",
                    "target_state_digest": target_digest,
                },
            )
            return NavigationExecutionResult(
                NavigationExecutionStatus.INDETERMINATE,
                execution_id,
                grant.digest,
                grant.start_state_digest,
                target_digest,
                grant.transition_ids,
                None,
                None,
                record.digest,
                "backend returned an untyped receipt; reconcile by retrying the same execution ID",
                False,
            )
        if (
            commit.execution_id != execution_id
            or commit.start_state_digest != grant.start_state_digest
            or (commit.committed and commit.final_state_digest != target_digest)
        ):
            record = self._journal().append(
                "hypervisor.navigation.execute.uncertain",
                {
                    "execution_id": execution_id,
                    "grant_digest": grant.digest,
                    "reason": "backend receipt does not match the requested CAS",
                    "commit_receipt": commit.to_dict(),
                    "target_state_digest": target_digest,
                },
            )
            return NavigationExecutionResult(
                NavigationExecutionStatus.COMMIT_UNVERIFIED,
                execution_id,
                grant.digest,
                grant.start_state_digest,
                target_digest,
                grant.transition_ids,
                commit,
                None,
                record.digest,
                "backend receipt does not match the requested state transition",
                commit.replayed,
            )
        if not commit.committed:
            record = self._journal().append(
                "hypervisor.navigation.execute.refuse",
                {
                    "execution_id": execution_id,
                    "grant_digest": grant.digest,
                    "status": NavigationExecutionStatus.COMMIT_CONFLICT.value,
                    "reason": commit.reason or "backend compare-and-swap rejected the starting-state version",
                    "commit_receipt": commit.to_dict(),
                },
            )
            return NavigationExecutionResult(
                NavigationExecutionStatus.COMMIT_CONFLICT,
                execution_id,
                grant.digest,
                grant.start_state_digest,
                target_digest,
                grant.transition_ids,
                commit,
                None,
                record.digest,
                commit.reason or "backend compare-and-swap rejected",
                commit.replayed,
            )

        try:
            observed_context = self._read_context(grant, descriptor, address)
            observed_state = observed_context.current_state
            observed_digest = None if observed_state is None else _state_digest(observed_state)
        except Exception as exc:
            observed_digest = None
            observation_error = f"{type(exc).__name__}: {exc}"
        else:
            observation_error = "backend state provider did not expose the committed state"
        if observed_digest != target_digest:
            record = self._journal().append(
                "hypervisor.navigation.execute.uncertain",
                {
                    "execution_id": execution_id,
                    "grant_digest": grant.digest,
                    "reason": observation_error,
                    "expected_target_state_digest": target_digest,
                    "observed_state_digest": observed_digest,
                    "commit_receipt": commit.to_dict(),
                },
            )
            return NavigationExecutionResult(
                NavigationExecutionStatus.COMMIT_UNVERIFIED,
                execution_id,
                grant.digest,
                grant.start_state_digest,
                target_digest,
                grant.transition_ids,
                commit,
                None,
                record.digest,
                observation_error,
                commit.replayed,
            )

        record = self._journal().append(
            "hypervisor.navigation.execute.commit",
            {
                "execution_id": execution_id,
                "grant_digest": grant.digest,
                "admission_receipt": admission.admission_receipt,
                "decision_receipt": grant.decision_receipt,
                "transition_ids": list(grant.transition_ids),
                "start_state_digest": grant.start_state_digest,
                "target_state_digest": target_digest,
                "commit_receipt": commit.to_dict(),
                "recovered_backend_commit": commit.replayed,
            },
        )
        status = (
            NavigationExecutionStatus.RECOVERED
            if commit.replayed
            else NavigationExecutionStatus.EXECUTED
        )
        return NavigationExecutionResult(
            status,
            execution_id,
            grant.digest,
            grant.start_state_digest,
            target_digest,
            grant.transition_ids,
            commit,
            record.digest,
            record.digest,
            None,
            commit.replayed,
        )
