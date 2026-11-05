"""Hypervisor-owned admission for replayable navigation proposals.

The coordinator is deliberately an admission boundary, not a transition
executor. It replays the navigation evidence against a trusted live-context
provider, derives kernel rights from the target PID, and delegates policy and
replay identity to the existing HeadlessOS hypervisor.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Mapping

from .classifier import HypervisorAction, HypervisorDomain
from .fs import normalize_path
from .navigation import ProcessContext, ProcessDescriptor, SemanticAddress
from .navigation_coordinator import (
    NavigationCoordinationResult,
    verify_navigation_coordination,
)


class NavigationAdmissionError(ValueError):
    """An admission request or its trusted host integration is malformed."""


class NavigationAdmissionStatus(str, Enum):
    """Terminal result of one hypervisor navigation-admission attempt."""

    ADMITTED = "admitted"
    REPLAYED = "replayed"
    REFUSED_PLAN = "refused_plan"
    REFUSED_CONTEXT = "refused_context"
    REFUSED_CAPABILITY = "refused_capability"
    REFUSED_POLICY = "refused_policy"
    REFUSED_DOMAIN = "refused_domain"
    REFUSED_ARBITRATION = "refused_arbitration"


def _canonical_bytes(value: Any) -> bytes:
    """Mathematics: map a finite JSON value to unique sorted compact UTF-8 bytes."""
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise NavigationAdmissionError(
            f"admission value is not canonical JSON: {exc}"
        ) from exc


def _digest(value: Any) -> str:
    """Mathematics: compute H(x)=SHA256(J(x)) over canonical JSON bytes."""
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _sha256(value: Any, label: str) -> None:
    """Mathematics: require an identity in the finite lowercase SHA-256 domain."""
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise NavigationAdmissionError(f"{label} must be lowercase SHA-256 hex")


@dataclass(frozen=True)
class NavigationExecutionGrant:
    """A process-bound, path-bounded, expiring authorization issued by the hypervisor."""

    pid: int
    source: str
    channel: str
    sequence: int
    process_id: str
    descriptor_digest: str
    address_digest: str
    context_digest: str
    coordination_digest: str
    proposal_digest: str
    witness_digest: str
    final_state_digest: str
    transition_ids: tuple[str, ...]
    resource: str
    required_rights: tuple[str, ...]
    resource_envelope: tuple[tuple[str, int], ...]
    decision_receipt: str
    decision_revision: int
    issued_at_tick: int
    expires_at_tick: int
    maximum_steps: int
    domain: HypervisorDomain = HypervisorDomain.CPU

    def __post_init__(self) -> None:
        """Mathematics: validate identity, evidence, path, rights, and finite lifetime."""
        if not isinstance(self.pid, int) or isinstance(self.pid, bool) or self.pid <= 0:
            raise NavigationAdmissionError("grant pid must be a positive integer")
        if not all(isinstance(value, str) and value for value in (
            self.source, self.channel, self.process_id, self.resource
        )):
            raise NavigationAdmissionError("grant identity and resource fields must be non-empty")
        if not isinstance(self.sequence, int) or isinstance(self.sequence, bool) or self.sequence <= 0:
            raise NavigationAdmissionError("grant sequence must be positive")
        if not isinstance(self.domain, HypervisorDomain) or self.domain is not HypervisorDomain.CPU:
            raise NavigationAdmissionError("navigation grants are restricted to the CPU domain")
        for name in (
            "descriptor_digest", "address_digest", "context_digest",
            "coordination_digest", "proposal_digest", "witness_digest",
            "final_state_digest", "decision_receipt",
        ):
            _sha256(getattr(self, name), name)
        if not isinstance(self.transition_ids, (tuple, list)) or not self.transition_ids:
            raise NavigationAdmissionError("grant must bind a non-empty transition path")
        if any(not isinstance(item, str) or not item for item in self.transition_ids):
            raise NavigationAdmissionError("grant transition IDs must be non-empty strings")
        object.__setattr__(self, "transition_ids", tuple(self.transition_ids))
        if not isinstance(self.required_rights, (tuple, list)):
            raise NavigationAdmissionError("grant required_rights must be a finite sequence")
        if any(not isinstance(item, str) or not item for item in self.required_rights):
            raise NavigationAdmissionError("grant rights must contain non-empty strings")
        rights = tuple(sorted(set(self.required_rights)))
        if not rights or "execute" not in rights:
            raise NavigationAdmissionError("grant rights must include execute")
        object.__setattr__(self, "required_rights", rights)
        if not isinstance(self.resource_envelope, (tuple, list)):
            raise NavigationAdmissionError("grant resource envelope must be a finite sequence")
        envelope: dict[str, int] = {}
        for item in self.resource_envelope:
            if not isinstance(item, (tuple, list)) or len(item) != 2:
                raise NavigationAdmissionError("grant resource envelope entries must be pairs")
            name, amount = item
            if not isinstance(name, str) or not name:
                raise NavigationAdmissionError("grant resource names must be non-empty")
            if not isinstance(amount, int) or isinstance(amount, bool) or amount < 0 or name in envelope:
                raise NavigationAdmissionError("grant resource amounts or names are invalid")
            envelope[name] = amount
        object.__setattr__(self, "resource_envelope", tuple(sorted(envelope.items())))
        for name in ("decision_revision", "issued_at_tick", "expires_at_tick", "maximum_steps"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise NavigationAdmissionError(f"{name} must be a non-negative integer")
        if self.expires_at_tick <= self.issued_at_tick:
            raise NavigationAdmissionError("grant expiry must be after issue tick")
        if self.maximum_steps != len(self.transition_ids) or self.maximum_steps < 1:
            raise NavigationAdmissionError("grant step bound must equal its finite transition path length")
        try:
            canonical_resource = normalize_path(self.resource)
        except Exception as exc:
            raise NavigationAdmissionError(f"grant resource path is invalid: {exc}") from exc
        if canonical_resource != self.resource:
            raise NavigationAdmissionError("grant resource must already be canonical")

    @property
    def authoritative(self) -> bool:
        """Mathematics: distinguish a hypervisor-issued bounded grant from a navigation proposal."""
        return True

    @property
    def digest(self) -> str:
        """Mathematics: identify the complete grant scope and lifetime by canonical SHA-256."""
        return _digest(self.to_dict())

    def valid_at(self, scheduler_tick: int) -> bool:
        """Mathematics: accept only during the half-open logical-time interval [issued, expiry)."""
        return (
            isinstance(scheduler_tick, int)
            and not isinstance(scheduler_tick, bool)
            and self.issued_at_tick <= scheduler_tick < self.expires_at_tick
        )

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize an explicitly authoritative, finite, non-transferable grant."""
        return {
            "schema": "mailcpu.navigation-execution-grant.v1",
            "authoritative": True,
            "scope": "one-process-one-path-one-resource-one-expiry",
            "pid": self.pid,
            "source": self.source,
            "channel": self.channel,
            "sequence": self.sequence,
            "process_id": self.process_id,
            "descriptor_digest": self.descriptor_digest,
            "address_digest": self.address_digest,
            "context_digest": self.context_digest,
            "coordination_digest": self.coordination_digest,
            "proposal_digest": self.proposal_digest,
            "witness_digest": self.witness_digest,
            "final_state_digest": self.final_state_digest,
            "transition_ids": list(self.transition_ids),
            "resource": self.resource,
            "required_rights": list(self.required_rights),
            "resource_envelope": {name: amount for name, amount in self.resource_envelope},
            "decision_receipt": self.decision_receipt,
            "decision_revision": self.decision_revision,
            "issued_at_tick": self.issued_at_tick,
            "expires_at_tick": self.expires_at_tick,
            "maximum_steps": self.maximum_steps,
            "domain": self.domain.value,
        }


@dataclass(frozen=True)
class NavigationAdmissionResult:
    """Auditable outcome of a navigation admission attempt."""

    status: NavigationAdmissionStatus
    reason: str | None
    grant: NavigationExecutionGrant | None
    action: HypervisorAction | None
    domain: HypervisorDomain | None
    decision_receipt: str | None
    admission_receipt: str
    replayed: bool

    def __post_init__(self) -> None:
        """Mathematics: enforce the result invariant that only ADMITTED/REPLAYED carry grants."""
        if not isinstance(self.status, NavigationAdmissionStatus):
            raise NavigationAdmissionError("admission status is invalid")
        _sha256(self.admission_receipt, "admission_receipt")
        if self.decision_receipt is not None:
            _sha256(self.decision_receipt, "decision_receipt")
        if self.grant is not None and not isinstance(self.grant, NavigationExecutionGrant):
            raise NavigationAdmissionError("admission grant is malformed")
        if self.action is not None and not isinstance(self.action, HypervisorAction):
            raise NavigationAdmissionError("admission action is malformed")
        if self.domain is not None and not isinstance(self.domain, HypervisorDomain):
            raise NavigationAdmissionError("admission domain is malformed")
        if self.status in {NavigationAdmissionStatus.ADMITTED, NavigationAdmissionStatus.REPLAYED}:
            if self.grant is None or self.action is not HypervisorAction.ALLOW or self.domain is not HypervisorDomain.CPU:
                raise NavigationAdmissionError("successful admission requires a CPU grant and ALLOW decision")
        elif self.grant is not None:
            raise NavigationAdmissionError("refused admission cannot carry a grant")
        if not isinstance(self.replayed, bool):
            raise NavigationAdmissionError("replayed must be Boolean")
        if self.status is NavigationAdmissionStatus.REPLAYED and not self.replayed:
            raise NavigationAdmissionError("REPLAYED status requires the replayed flag")
        if self.status is NavigationAdmissionStatus.ADMITTED and self.replayed:
            raise NavigationAdmissionError("ADMITTED status cannot describe a replay")

    @property
    def accepted(self) -> bool:
        """Mathematics: project admission success as membership in {ADMITTED, REPLAYED}."""
        return self.status in {NavigationAdmissionStatus.ADMITTED, NavigationAdmissionStatus.REPLAYED}

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize the outcome without conflating a proposal, decision, grant, or receipt."""
        return {
            "schema": "mailcpu.navigation-admission-result.v1",
            "status": self.status.value,
            "accepted": self.accepted,
            "reason": self.reason,
            "grant": None if self.grant is None else self.grant.to_dict(),
            "grant_digest": None if self.grant is None else self.grant.digest,
            "action": None if self.action is None else self.action.value,
            "domain": None if self.domain is None else self.domain.value,
            "decision_receipt": self.decision_receipt,
            "admission_receipt": self.admission_receipt,
            "replayed": self.replayed,
        }


class HypervisorNavigationAdmissionCoordinator:
    """Revalidate navigation at the live OS boundary, then request a hypervisor grant."""

    def __init__(
        self,
        operating_system: Any,
        context_provider: Callable[[int, ProcessDescriptor, SemanticAddress], ProcessContext],
    ) -> None:
        """Mathematics: bind admission to one HeadlessOS authority and trusted live-context projection."""
        if not callable(getattr(operating_system, "hypervisor_arbitrate_event", None)):
            raise NavigationAdmissionError("operating_system must expose hypervisor_arbitrate_event")
        if not callable(context_provider):
            raise NavigationAdmissionError("a trusted live-context provider is required")
        self.operating_system = operating_system
        self.context_provider = context_provider

    def _journal(self):
        """Mathematics: resolve the single journal shared by kernel and hypervisor."""
        try:
            journal = self.operating_system.environment.kernel.journal
        except AttributeError as exc:
            raise NavigationAdmissionError("operating system has no kernel journal") from exc
        if not callable(getattr(journal, "append", None)):
            raise NavigationAdmissionError("operating system journal is invalid")
        return journal

    def _refuse(
        self,
        *,
        source: str,
        sequence: int,
        pid: int,
        status: NavigationAdmissionStatus,
        reason: str,
        coordination_digest: str | None,
        action: HypervisorAction | None = None,
        domain: HypervisorDomain | None = None,
        decision_receipt: str | None = None,
        replayed: bool = False,
    ) -> NavigationAdmissionResult:
        """Mathematics: journal one fail-closed refusal before returning a result without authority."""
        payload = {
            "source": source,
            "sequence": sequence,
            "pid": pid,
            "status": status.value,
            "reason": reason,
            "coordination_digest": coordination_digest,
            "action": None if action is None else action.value,
            "domain": None if domain is None else domain.value,
            "decision_receipt": decision_receipt,
            "replayed": replayed,
        }
        receipt = self._journal().append("hypervisor.navigation.refuse", payload).digest
        return NavigationAdmissionResult(
            status, reason, None, action, domain, decision_receipt, receipt, replayed
        )

    def admit(
        self,
        *,
        pid: int,
        source: str,
        sequence: int,
        descriptor: ProcessDescriptor,
        address: SemanticAddress,
        coordination: NavigationCoordinationResult,
        resource: str,
        required_rights: frozenset[str] | set[str] | tuple[str, ...] = frozenset({"execute"}),
        grant_ttl_ticks: int = 64,
    ) -> NavigationAdmissionResult:
        """Mathematics: verify current context, derive kernel rights, arbitrate policy, and issue a bounded CPU grant."""
        if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
            raise NavigationAdmissionError("pid must be a positive integer")
        if not isinstance(source, str) or not source:
            raise NavigationAdmissionError("source must be non-empty")
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence <= 0:
            raise NavigationAdmissionError("sequence must be a positive integer")
        if not isinstance(descriptor, ProcessDescriptor) or not isinstance(address, SemanticAddress):
            raise NavigationAdmissionError("descriptor and semantic address must be typed")
        if not isinstance(coordination, NavigationCoordinationResult):
            raise NavigationAdmissionError("coordination must be a NavigationCoordinationResult")
        if not isinstance(resource, str) or not resource:
            raise NavigationAdmissionError("resource must be non-empty")
        if not isinstance(grant_ttl_ticks, int) or isinstance(grant_ttl_ticks, bool) or grant_ttl_ticks < 1:
            raise NavigationAdmissionError("grant_ttl_ticks must be a positive integer")
        if not isinstance(required_rights, (tuple, list, set, frozenset)):
            raise NavigationAdmissionError("required_rights must be a finite set or sequence")
        if any(not isinstance(item, str) or not item for item in required_rights):
            raise NavigationAdmissionError("required_rights must contain non-empty strings")
        rights = frozenset(required_rights)
        if not rights or "execute" not in rights:
            raise NavigationAdmissionError("required_rights must contain execute")
        try:
            canonical_resource = normalize_path(resource)
        except Exception as exc:
            raise NavigationAdmissionError(f"resource is invalid: {exc}") from exc

        request = coordination.admission_request
        coordination_digest = coordination.digest
        if request is None:
            return self._refuse(
                source=source, sequence=sequence, pid=pid,
                status=NavigationAdmissionStatus.REFUSED_PLAN,
                reason="coordination result has no ready admission proposal",
                coordination_digest=coordination_digest,
            )
        if descriptor.process_id != address.process_id or descriptor.version != address.version:
            return self._refuse(
                source=source, sequence=sequence, pid=pid,
                status=NavigationAdmissionStatus.REFUSED_PLAN,
                reason="semantic address does not identify the supplied descriptor",
                coordination_digest=coordination_digest,
            )

        try:
            live_context = self.context_provider(pid, descriptor, address)
        except Exception as exc:
            return self._refuse(
                source=source, sequence=sequence, pid=pid,
                status=NavigationAdmissionStatus.REFUSED_CONTEXT,
                reason=f"live context unavailable: {type(exc).__name__}: {exc}",
                coordination_digest=coordination_digest,
            )
        if not isinstance(live_context, ProcessContext) or not verify_navigation_coordination(
            descriptor, address, live_context, coordination
        ):
            return self._refuse(
                source=source, sequence=sequence, pid=pid,
                status=NavigationAdmissionStatus.REFUSED_CONTEXT,
                reason="live context does not reproduce the complete coordinated plan",
                coordination_digest=coordination_digest,
            )

        try:
            scheduler_tick = self.operating_system.vm.scheduler.tick
        except AttributeError as exc:
            raise NavigationAdmissionError("operating system has no deterministic scheduler tick") from exc
        if not isinstance(scheduler_tick, int) or isinstance(scheduler_tick, bool) or scheduler_tick < 0:
            raise NavigationAdmissionError("scheduler tick is invalid")
        expires_at_tick = scheduler_tick + grant_ttl_ticks

        payload = {
            "operation_kind": "navigation.execution",
            "pid": pid,
            "process_id": descriptor.process_id,
            "descriptor_version": descriptor.version,
            "descriptor_digest": descriptor.digest,
            "address_digest": address.digest,
            "context_digest": coordination.context_digest,
            "coordination_digest": coordination_digest,
            "proposal_digest": request.digest,
            "witness_digest": request.concrete_witness_digest,
            "final_state_digest": request.final_state_digest,
            "transition_ids": list(request.transition_ids),
            "resource_envelope": {name: amount for name, amount in request.resource_envelope},
            "resource": canonical_resource,
            "required_rights": sorted(rights),
            "grant_ttl_ticks": grant_ttl_ticks,
            "issued_at_tick": scheduler_tick,
            "expires_at_tick": expires_at_tick,
            "maximum_steps": len(request.transition_ids),
            "domain": HypervisorDomain.CPU.value,
        }
        try:
            arbitration = self.operating_system.hypervisor_arbitrate_event(
                pid=pid,
                source=source,
                channel="navigation.admission",
                sequence=sequence,
                operation="execute CPU navigation transition path",
                resource=canonical_resource,
                payload=payload,
                required_rights=rights,
                destructive=False,
            )
        except Exception as exc:
            return self._refuse(
                source=source, sequence=sequence, pid=pid,
                status=NavigationAdmissionStatus.REFUSED_ARBITRATION,
                reason=f"hypervisor arbitration refused: {type(exc).__name__}: {exc}",
                coordination_digest=coordination_digest,
            )

        decision = arbitration.decision
        replayed = arbitration.replayed
        if decision is not None:
            action, domain = decision.action, decision.domain
            decision_receipt = decision.receipt
            decision_revision = decision.revision
        else:
            projection = self.operating_system.hypervisor_arbitration.decision_projection_for(
                (source, "navigation.admission", sequence)
            )
            if projection is None:
                return self._refuse(
                    source=source, sequence=sequence, pid=pid,
                    status=NavigationAdmissionStatus.REFUSED_POLICY,
                    reason="replayed arbitration has no recoverable decision projection",
                    coordination_digest=coordination_digest,
                    replayed=True,
                )
            action, domain, decision_receipt, decision_revision = projection

        if action is HypervisorAction.DENY:
            return self._refuse(
                source=source, sequence=sequence, pid=pid,
                status=NavigationAdmissionStatus.REFUSED_CAPABILITY,
                reason="kernel capability check denied one or more required rights",
                coordination_digest=coordination_digest,
                action=action, domain=domain, decision_receipt=decision_receipt,
                replayed=replayed,
            )
        if action is not HypervisorAction.ALLOW:
            return self._refuse(
                source=source, sequence=sequence, pid=pid,
                status=NavigationAdmissionStatus.REFUSED_POLICY,
                reason="hypervisor policy requires review or refused automatic admission",
                coordination_digest=coordination_digest,
                action=action, domain=domain, decision_receipt=decision_receipt,
                replayed=replayed,
            )
        if domain is not HypervisorDomain.CPU:
            return self._refuse(
                source=source, sequence=sequence, pid=pid,
                status=NavigationAdmissionStatus.REFUSED_DOMAIN,
                reason=f"navigation execution requires CPU domain, not {domain.value}",
                coordination_digest=coordination_digest,
                action=action, domain=domain, decision_receipt=decision_receipt,
                replayed=replayed,
            )

        grant = NavigationExecutionGrant(
            pid=pid,
            source=source,
            channel="navigation.admission",
            sequence=sequence,
            process_id=descriptor.process_id,
            descriptor_digest=descriptor.digest,
            address_digest=address.digest,
            context_digest=coordination.context_digest,
            coordination_digest=coordination_digest,
            proposal_digest=request.digest,
            witness_digest=request.concrete_witness_digest,
            final_state_digest=request.final_state_digest,
            transition_ids=request.transition_ids,
            resource=canonical_resource,
            required_rights=tuple(sorted(rights)),
            resource_envelope=request.resource_envelope,
            decision_receipt=decision_receipt,
            decision_revision=decision_revision,
            issued_at_tick=scheduler_tick,
            expires_at_tick=expires_at_tick,
            maximum_steps=len(request.transition_ids),
        )
        receipt = self._journal().append(
            "hypervisor.navigation.admit",
            {
                "grant_digest": grant.digest,
                "grant": grant.to_dict(),
                "decision_receipt": decision_receipt,
                "coordination_digest": coordination_digest,
                "arbitration_fingerprint": arbitration.fingerprint,
                "replayed": replayed,
            },
        ).digest
        return NavigationAdmissionResult(
            NavigationAdmissionStatus.REPLAYED if replayed else NavigationAdmissionStatus.ADMITTED,
            None,
            grant,
            action,
            domain,
            decision_receipt,
            receipt,
            replayed,
        )
