"""Capability-gated lifecycle adapter for explicitly registered host services.

The event payload selects only a registered service and a typed lifecycle action.
Executable commands and process environments remain local configuration.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
import threading
from typing import Iterable

from .subprocess_service import (
    SubprocessServiceError,
    SubprocessServiceReport,
    SubprocessServiceSpec,
    SubprocessServiceSupervisor,
)


class HostServiceLifecycleError(RuntimeError):
    """A host-service lifecycle command is outside the configured local catalogue."""


class HostServiceAction(str, Enum):
    """Finite lifecycle vocabulary exposed through Hypervisor arbitration."""

    START = "start"
    STOP = "stop"
    INSPECT = "inspect"


@dataclass(frozen=True)
class HostServiceCommand:
    """A portable request naming one locally configured service and one supported action."""

    action: HostServiceAction
    service: str

    def __post_init__(self) -> None:
        if not isinstance(self.action, HostServiceAction):
            try:
                object.__setattr__(self, "action", HostServiceAction(self.action))
            except (TypeError, ValueError) as exc:
                raise HostServiceLifecycleError("action must be start, stop, or inspect") from exc
        if (
            not isinstance(self.service, str)
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", self.service) is None
        ):
            raise HostServiceLifecycleError("service must be a 1-128 character local service identifier")

    def to_dict(self) -> dict[str, str]:
        """Return the finite event projection without command, path, or environment details."""

        return {"action": self.action.value, "service": self.service}


class HostServiceLifecycleAdapter:
    """Bind Hypervisor-authorized requests to a finite local SubprocessServiceSupervisor catalogue.

    This adapter is a trusted host-side binding. It does not accept remote commands,
    executable paths, working directories, or arbitrary environment values.
    """

    def __init__(
        self,
        services: Iterable[SubprocessServiceSpec] = (),
        *,
        supervisor: SubprocessServiceSupervisor | None = None,
    ) -> None:
        if supervisor is not None and not isinstance(supervisor, SubprocessServiceSupervisor):
            raise HostServiceLifecycleError("supervisor must be a SubprocessServiceSupervisor")
        self.supervisor = supervisor or SubprocessServiceSupervisor()
        self._specs: dict[str, SubprocessServiceSpec] = {}
        self._lock = threading.RLock()
        for spec in services:
            self.register(spec)

    def register(self, spec: SubprocessServiceSpec) -> None:
        """Register one trusted local specification; duplicate names cannot replace commands."""

        if not isinstance(spec, SubprocessServiceSpec):
            raise HostServiceLifecycleError("register requires a SubprocessServiceSpec")
        with self._lock:
            if spec.name in self._specs:
                raise HostServiceLifecycleError(f"host service is already registered: {spec.name}")
            try:
                self.supervisor.register(spec)
            except (SubprocessServiceError, ValueError) as exc:
                raise HostServiceLifecycleError(str(exc)) from exc
            self._specs[spec.name] = spec

    def validate(self, command: HostServiceCommand) -> None:
        """Verify that a command targets a locally registered name before policy arbitration."""

        if not isinstance(command, HostServiceCommand):
            raise HostServiceLifecycleError("host service dispatch requires a HostServiceCommand")
        with self._lock:
            if command.service not in self._specs:
                raise HostServiceLifecycleError(f"host service is not registered: {command.service}")

    def execute(self, command: HostServiceCommand) -> dict[str, object]:
        """Apply one idempotent desired-state or observation operation to the local supervisor."""

        self.validate(command)
        with self._lock:
            try:
                if command.action is HostServiceAction.START:
                    report: SubprocessServiceReport = self.supervisor.start(command.service)
                elif command.action is HostServiceAction.STOP:
                    report = self.supervisor.stop(command.service)
                else:
                    report = self.supervisor.status(command.service)
            except (SubprocessServiceError, KeyError, OSError) as exc:
                raise HostServiceLifecycleError(str(exc)) from exc
            return report.to_dict()

    @property
    def registered_services(self) -> tuple[str, ...]:
        """Return deterministic service identifiers without exposing executable specifications."""

        with self._lock:
            return tuple(sorted(self._specs))

    def close(self) -> None:
        """Stop every child owned by this adapter's supervisor."""

        self.supervisor.close()
