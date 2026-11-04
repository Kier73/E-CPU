"""Capability-gated hypervisor control for deterministic transit-orbit scheduling.

The controller authorizes one scheduler quantum through the coordinator OS.
The selected TransitComputeSession still performs receiver-local authorization
before its operation handler is invoked.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

from .classifier import HypervisorAction, HypervisorDecision, HypervisorDomain
from .headless import HeadlessOS
from .transit_orbit import (
    TransitOrbitScheduler,
    TransitOrbitSchedulerError,
    TransitOrbitStep,
)
from .transit_session import TransitComputeSession


_FORMAT = "mailcpu-hypervisor-transit-orbit-v1"
_RESOURCE = "/system/transit/orbit"
_RIGHT = "schedule"
_STATE_FIELDS = frozenset({"version", "authority_pid", "scheduler"})


class HypervisorTransitOrbitError(ValueError):
    """A hypervisor-owned transit-orbit controller or checkpoint is invalid."""


def _canonical_bytes(value: Any) -> bytes:
    """Mathematics: map finite JSON-compatible state x to canonical bytes J(x), refusing values outside the finite JSON domain."""
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise HypervisorTransitOrbitError(
            f"hypervisor transit-orbit state is not canonical JSON: {exc}"
        ) from exc


def _digest(value: Any) -> str:
    """Mathematics: compute H(x)=SHA-256(J(x)) over canonical JSON bytes."""
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _nonnegative_int(value: Any, label: str) -> int:
    """Mathematics: enforce x∈Z≥0 and x∉{bool}; reject values outside that domain."""
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise HypervisorTransitOrbitError(f"{label} must be a non-negative integer")
    return value


@dataclass(frozen=True)
class HypervisorTransitOrbitStep:
    """One policy decision and its optional scheduler transition."""

    decision: HypervisorDecision
    orbit_step: TransitOrbitStep | None

    def __post_init__(self) -> None:
        """Keep policy denial and scheduler execution mutually exclusive."""
        if not isinstance(self.decision, HypervisorDecision):
            raise HypervisorTransitOrbitError("step requires a HypervisorDecision")
        if self.decision.action is HypervisorAction.ALLOW:
            if not isinstance(self.orbit_step, TransitOrbitStep):
                raise HypervisorTransitOrbitError(
                    "an allowed scheduling decision must contain one orbit step"
                )
        elif self.orbit_step is not None:
            raise HypervisorTransitOrbitError(
                "a non-allow decision cannot contain an orbit step"
            )

    @property
    def authorized(self) -> bool:
        """Mathematics: authorized=1 iff decision.action=ALLOW; an orbit transition exists exactly in that case."""
        return self.decision.action is HypervisorAction.ALLOW


class HypervisorTransitOrbitController:
    """Run a deterministic transit scheduler as a capability-gated hypervisor subroutine.

    The controller is an event-loop adapter, not a background thread. A host
    calls pump() after transport readiness or acknowledgement progress. Each
    scheduling quantum passes through the coordinator's HeadlessOS policy and
    capability boundary; the selected receiver session then applies its own
    local hypervisor authorization to the semantic operation.
    """

    resource = _RESOURCE
    required_right = _RIGHT

    def __init__(
        self,
        operating_system: HeadlessOS,
        authority_pid: int,
        scheduler: TransitOrbitScheduler,
    ) -> None:
        """Bind one live OS authority process to an existing transit scheduler."""
        if not isinstance(operating_system, HeadlessOS):
            raise HypervisorTransitOrbitError(
                "controller requires a coordinator HeadlessOS"
            )
        if not isinstance(scheduler, TransitOrbitScheduler):
            raise HypervisorTransitOrbitError(
                "controller requires a TransitOrbitScheduler"
            )
        _nonnegative_int(authority_pid, "authority_pid")
        try:
            operating_system.environment.kernel._process(authority_pid)
        except Exception as exc:
            raise HypervisorTransitOrbitError(
                "authority_pid does not identify a live coordinator process"
            ) from exc
        self.operating_system = operating_system
        self.authority_pid = authority_pid
        self.scheduler = scheduler

    def state(self) -> dict[str, object]:
        """Mathematics: project C=(authority_pid,resource,right,orbit_state) without copying authoritative path ledgers."""
        return {
            "authority_pid": self.authority_pid,
            "resource": self.resource,
            "required_right": self.required_right,
            "scheduler": self.scheduler.state(),
        }

    def step(self) -> HypervisorTransitOrbitStep:
        """Mathematics: evaluate one guarded transition T_C; when action≠ALLOW, the scheduler state is unchanged."""
        request_payload = {
            "control": "advance one ready transit compute scheduling quantum",
            "scheduler": self.scheduler.state(),
        }

        # This is one fixed internal control primitive, not a domain-routed job.
        # The classifier's domain is advisory; any non-REVIEW label reaches the
        # same scheduler subroutine. The exact resource capability and policy
        # action remain the authority gate. REVIEW is never given a handler.
        handlers = {
            domain: self.scheduler.step
            for domain in HypervisorDomain
            if domain is not HypervisorDomain.REVIEW
        }
        decision, result = self.operating_system.hypervisor_dispatch(
            self.authority_pid,
            operation="execute CPU transit orbit scheduling quantum",
            resource=self.resource,
            payload=request_payload,
            handlers=handlers,
            required_rights=frozenset({self.required_right}),
            destructive=False,
        )

        if decision.action is HypervisorAction.ALLOW:
            if not isinstance(result, TransitOrbitStep):
                raise HypervisorTransitOrbitError(
                    "allowed hypervisor dispatch did not return a scheduler step"
                )
        elif result is not None:
            raise HypervisorTransitOrbitError(
                "hypervisor returned a scheduler result for a non-allow decision"
            )
        return HypervisorTransitOrbitStep(decision, result)

    def pump(self, max_quanta: int) -> tuple[HypervisorTransitOrbitStep, ...]:
        """Mathematics: execute at most N>0 guarded quanta and stop at non-ALLOW, idle, or backpressure."""
        if (
            not isinstance(max_quanta, int)
            or isinstance(max_quanta, bool)
            or max_quanta <= 0
        ):
            raise HypervisorTransitOrbitError("max_quanta must be a positive integer")

        steps: list[HypervisorTransitOrbitStep] = []
        for _ in range(max_quanta):
            current = self.step()
            steps.append(current)
            if current.orbit_step is None:
                break
            if current.orbit_step.receipt.disposition in {"idle", "backpressured"}:
                break
        return tuple(steps)

    def snapshot(self) -> dict[str, object]:
        """Mathematics: serialize K=(version,authority_pid,scheduler_snapshot) with digest H(K), leaving OS and sessions authoritative."""
        state = {
            "version": 1,
            "authority_pid": self.authority_pid,
            "scheduler": self.scheduler.snapshot(),
        }
        return {
            "format": _FORMAT,
            "digest": _digest(state),
            "state": state,
        }

    @classmethod
    def from_snapshot(
        cls,
        payload: Mapping[str, Any],
        operating_system: HeadlessOS,
        sessions: Mapping[str, TransitComputeSession],
    ) -> "HypervisorTransitOrbitController":
        """Mathematics: reconstruct C only when format, schema, digest, authority process, and restored session contracts verify."""
        if not isinstance(payload, Mapping) or set(payload) != {
            "format",
            "digest",
            "state",
        }:
            raise HypervisorTransitOrbitError(
                "hypervisor transit-orbit checkpoint envelope fields are invalid"
            )
        if payload.get("format") != _FORMAT:
            raise HypervisorTransitOrbitError(
                "unsupported hypervisor transit-orbit checkpoint format"
            )
        state = payload.get("state")
        if not isinstance(state, Mapping) or set(state) != _STATE_FIELDS:
            raise HypervisorTransitOrbitError(
                "hypervisor transit-orbit checkpoint state fields are invalid"
            )
        if state.get("version") != 1 or isinstance(state.get("version"), bool):
            raise HypervisorTransitOrbitError(
                "unsupported hypervisor transit-orbit checkpoint version"
            )
        if _digest(dict(state)) != payload.get("digest"):
            raise HypervisorTransitOrbitError(
                "hypervisor transit-orbit checkpoint digest mismatch"
            )
        authority_pid = _nonnegative_int(
            state.get("authority_pid"), "authority_pid"
        )
        scheduler = TransitOrbitScheduler.from_snapshot(
            state.get("scheduler"),
            sessions,
        )
        return cls(operating_system, authority_pid, scheduler)
