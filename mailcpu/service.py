"""Deterministic service supervision for long-lived MailCPU processes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from .model import DEFAULT_MAX_TICKS
from .kernel import KernelError, ProcessStatus

if TYPE_CHECKING:
    from .headless import HeadlessOS, ProcessReport


class RestartPolicy(str, Enum):
    """Finite restart policies for a service's desired-state controller."""

    NEVER = "never"
    ON_FAILURE = "on_failure"
    ALWAYS = "always"


@dataclass(frozen=True)
class ServiceSpec:
    """Declarative service definition: virtual executable path, identity, and restart budget."""

    name: str
    source_path: str
    restart: RestartPolicy = RestartPolicy.NEVER
    max_restarts: int = 0
    environment: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        """Mathematics: require `name ≠ ε` and finite non-negative restart budget `0 ≤ max_restarts < ∞`."""

        if not self.name:
            raise ValueError("service name must be non-empty")
        if self.max_restarts < 0:
            raise ValueError("max_restarts must be non-negative")


@dataclass(frozen=True)
class ServiceReport:
    """Observable supervisor projection for one registered service."""

    name: str
    state: str
    pid: int | None
    restart_count: int
    exit_code: int | None
    process: ProcessReport | None

    def to_dict(self) -> dict[str, object]:
        """Mathematics: project service state `s` into a nested JSON-compatible record."""

        return {
            "name": self.name,
            "state": self.state,
            "pid": self.pid,
            "restart_count": self.restart_count,
            "exit_code": self.exit_code,
            "process": None if self.process is None else self.process.to_dict(),
        }


@dataclass
class _ServiceRecord:
    """Mutable controller state for one desired service."""

    spec: ServiceSpec
    desired: bool = False
    pid: int | None = None
    restart_count: int = 0
    exit_code: int | None = None
    state: str = "stopped"


class ServiceSupervisor:
    """A deterministic desired-state controller over the HeadlessOS process API."""

    def __init__(self, operating_system: HeadlessOS) -> None:
        """Mathematics: initialize service map `S = ∅` and controller clock coupled to the OS scheduler."""

        self.operating_system = operating_system
        self._records: dict[str, _ServiceRecord] = {}

    def register(self, spec: ServiceSpec) -> None:
        """Mathematics: extend partial service map `S := S[name ↦ spec]` only when `name ∉ dom(S)`."""

        if spec.name in self._records:
            raise ValueError(f"service already registered: {spec.name}")
        self._records[spec.name] = _ServiceRecord(spec)

    def start(self, name: str) -> ServiceReport:
        """Mathematics: realize desired state by spawning `P := assemble(F[source_path])` when no live PID exists."""

        record = self._record(name)
        record.desired = True
        if record.pid is not None:
            try:
                current = self.operating_system.process(record.pid)
            except KernelError:
                record.pid = None
                current = None
            if current is not None and current.status != ProcessStatus.EXITED.value:
                record.state = current.status
                return self.status(name)
            if current is not None:
                # A direct caller may have terminated the process without
                # passing through supervisor reconciliation. Reap it before
                # realizing the desired state again.
                record.exit_code = current.exit_code
                self._collect(record)
        record.pid = self.operating_system.launch_file(
            record.spec.source_path,
            name=f"service:{name}",
            environment=dict(record.spec.environment),
        )
        record.state = ProcessStatus.RUNNABLE.value
        record.exit_code = None
        return self.status(name)

    def stop(self, name: str, exit_code: int = 0) -> ServiceReport:
        """Mathematics: set desired state false and apply `terminate(pid, exit_code)` to any live instance."""

        record = self._record(name)
        record.desired = False
        if record.pid is not None:
            try:
                current = self.operating_system.process(record.pid)
            except KernelError:
                record.pid = None
                current = None
            if current is not None:
                if current.status in {ProcessStatus.RUNNABLE.value, ProcessStatus.BLOCKED.value}:
                    current = self.operating_system.terminate(record.pid, exit_code)
                record.exit_code = current.exit_code
                if current.status == ProcessStatus.EXITED.value:
                    self._collect(record)
        record.state = "stopped"
        return self.status(name)

    def tick(self, max_ticks: int = DEFAULT_MAX_TICKS) -> tuple[ServiceReport, ...]:
        """Mathematics: advance OS orbit to absolute ceiling `max_ticks`, then apply restart policy transition `δ_service`."""

        self.operating_system.run(max_ticks)
        for name in tuple(sorted(self._records)):
            self._reconcile(self._records[name])
        return self.statuses()

    def status(self, name: str) -> ServiceReport:
        """Mathematics: project controller record `S[name]` and its current process report."""

        record = self._record(name)
        if record.pid is None:
            process = None
        else:
            try:
                process = self.operating_system.process(record.pid)
            except KernelError:
                process = None
        return ServiceReport(
            record.spec.name,
            record.state,
            record.pid,
            record.restart_count,
            record.exit_code if process is None else process.exit_code,
            process,
        )

    def statuses(self) -> tuple[ServiceReport, ...]:
        """Mathematics: enumerate `sort({project(S[name]) | name ∈ dom(S)})` in stable name order."""

        return tuple(self.status(name) for name in sorted(self._records))

    def snapshot(self) -> dict[str, object]:
        """Mathematics: serialize desired service relation `S` without duplicating process state held by the VM checkpoint."""

        return {
            name: {
                "spec": {
                    "name": record.spec.name,
                    "source_path": record.spec.source_path,
                    "restart": record.spec.restart.value,
                    "max_restarts": record.spec.max_restarts,
                    "environment": [list(item) for item in record.spec.environment],
                },
                "desired": record.desired,
                "pid": record.pid,
                "restart_count": record.restart_count,
                "exit_code": record.exit_code,
                "state": record.state,
            }
            for name, record in sorted(self._records.items())
        }

    @classmethod
    def from_snapshot(cls, operating_system: HeadlessOS, payload: dict[str, object]) -> "ServiceSupervisor":
        """Mathematics: reconstruct service controller map `S` over a restored process universe."""

        supervisor = cls(operating_system)
        for name, raw in sorted(payload.items()):
            specification = raw["spec"]
            spec = ServiceSpec(
                str(specification["name"]),
                str(specification["source_path"]),
                RestartPolicy(specification["restart"]),
                int(specification["max_restarts"]),
                tuple((str(item[0]), str(item[1])) for item in specification.get("environment", ())),
            )
            if spec.name != name:
                raise ValueError(f"service snapshot key mismatch: {name}")
            supervisor._records[name] = _ServiceRecord(
                spec,
                bool(raw["desired"]),
                None if raw.get("pid") is None else int(raw["pid"]),
                int(raw["restart_count"]),
                None if raw.get("exit_code") is None else int(raw["exit_code"]),
                str(raw["state"]),
            )
            if supervisor._records[name].pid is not None:
                operating_system.process(supervisor._records[name].pid)
        return supervisor

    def _reconcile(self, record: _ServiceRecord) -> None:
        """Mathematics: apply restart predicate `desired ∧ exited ∧ policy ∧ restart_count < budget`."""

        if record.pid is None:
            record.state = "stopped"
            return
        try:
            process = self.operating_system.process(record.pid)
        except KernelError:
            record.pid = None
            if record.desired:
                record.pid = self.operating_system.launch_file(
                    record.spec.source_path,
                    name=f"service:{record.spec.name}",
                    environment=dict(record.spec.environment),
                )
                record.state = ProcessStatus.RUNNABLE.value
                record.exit_code = None
            else:
                record.state = "stopped"
            return
        record.exit_code = process.exit_code
        if process.status != ProcessStatus.EXITED.value:
            record.state = process.status
            return
        should_restart = (
            record.desired
            and record.restart_count < record.spec.max_restarts
            and (
                record.spec.restart is RestartPolicy.ALWAYS
                or (record.spec.restart is RestartPolicy.ON_FAILURE and process.exit_code not in (None, 0))
            )
        )
        if should_restart:
            self._collect(record)
            record.restart_count += 1
            record.pid = self.operating_system.launch_file(
                record.spec.source_path,
                name=f"service:{record.spec.name}",
                environment=dict(record.spec.environment),
            )
            record.state = ProcessStatus.RUNNABLE.value
            record.exit_code = None
        else:
            self._collect(record)
            record.state = "exited" if record.desired else "stopped"

    def _collect(self, record: _ServiceRecord) -> None:
        """Mathematics: apply `waitpid(init,record.pid)` and remove the terminal service state, leaving `record.pid=⊥`."""

        if record.pid is None:
            return
        try:
            self.operating_system.reap_process(record.pid)
        except KernelError as exc:
            if "no child process" not in str(exc):
                raise
        record.pid = None

    def _record(self, name: str) -> _ServiceRecord:
        """Mathematics: look up service record `S[name]` by registered service name."""

        try:
            return self._records[name]
        except KeyError as exc:
            raise KeyError(f"unknown service: {name}") from exc
