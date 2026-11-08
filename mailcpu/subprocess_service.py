"""Bounded supervision for real operating-system service processes."""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from typing import Any, Mapping, Sequence
import uuid

from .service import RestartPolicy


_READINESS_SCHEMA = "mailcpu.subprocess-service-readiness.v1"
_READY_FILE_ENV = "MAILCPU_SERVICE_READY_FILE"
_START_TOKEN_ENV = "MAILCPU_SERVICE_START_TOKEN"
_SERVICE_NAME_ENV = "MAILCPU_SERVICE_NAME"


class SubprocessServiceError(RuntimeError):
    """A child process failed to satisfy its service lifecycle contract."""


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    try:
        return json.dumps(
            dict(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise SubprocessServiceError(f"service lifecycle value is not canonical JSON: {exc}") from exc


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    descriptor: int | None = None
    try:
        descriptor = os.open(
            str(temporary),
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o600,
        )
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = None
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        try:
            directory_fd = os.open(str(path.parent), os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            # Directory fsync is not available on every supported platform.
            pass
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def publish_service_ready(details: Mapping[str, Any]) -> None:
    """Publish one startup-token-bound readiness record for a supervised child."""

    if not isinstance(details, Mapping):
        raise SubprocessServiceError("readiness details must be a mapping")
    ready_file = os.environ.get(_READY_FILE_ENV)
    start_token = os.environ.get(_START_TOKEN_ENV)
    service_name = os.environ.get(_SERVICE_NAME_ENV)
    if not ready_file or not start_token or not service_name:
        raise SubprocessServiceError("child is missing its supervisor readiness environment")
    payload = {
        "schema": _READINESS_SCHEMA,
        "service_name": service_name,
        "start_token": start_token,
        "pid": os.getpid(),
        "details": dict(details),
    }
    _atomic_write(Path(ready_file), _canonical_bytes(payload) + b"\n")


@dataclass(frozen=True)
class SubprocessServiceSpec:
    """Declarative child-process command, readiness contract, and finite restart policy."""

    name: str
    command: tuple[str, ...]
    readiness_directory: Path
    restart: RestartPolicy = RestartPolicy.ON_FAILURE
    max_restarts: int = 3
    readiness_timeout: float = 10.0
    restart_delay: float = 0.25
    shutdown_timeout: float = 3.0
    environment: tuple[tuple[str, str], ...] = ()
    cwd: Path | None = None
    log_path: Path | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name or self.name.strip() != self.name:
            raise SubprocessServiceError("service name must be non-empty trimmed text")
        command = tuple(self.command)
        if not command or any(not isinstance(item, str) or not item for item in command):
            raise SubprocessServiceError("service command must contain non-empty text arguments")
        object.__setattr__(self, "command", command)
        if not isinstance(self.readiness_directory, Path):
            object.__setattr__(self, "readiness_directory", Path(self.readiness_directory))
        if self.cwd is not None and not isinstance(self.cwd, Path):
            object.__setattr__(self, "cwd", Path(self.cwd))
        if self.log_path is not None and not isinstance(self.log_path, Path):
            object.__setattr__(self, "log_path", Path(self.log_path))
        if not isinstance(self.restart, RestartPolicy):
            try:
                object.__setattr__(self, "restart", RestartPolicy(self.restart))
            except ValueError as exc:
                raise SubprocessServiceError("restart must be never, on_failure, or always") from exc
        if type(self.max_restarts) is not int or not 0 <= self.max_restarts <= 1000:
            raise SubprocessServiceError("max_restarts must be an integer between zero and 1000")
        for name, value in (
            ("readiness_timeout", self.readiness_timeout),
            ("shutdown_timeout", self.shutdown_timeout),
        ):
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(float(value))
                or value <= 0
                or value > 3600
            ):
                raise SubprocessServiceError(f"{name} must be positive and at most 3600 seconds")
        if (
            not isinstance(self.restart_delay, (int, float))
            or isinstance(self.restart_delay, bool)
            or not math.isfinite(float(self.restart_delay))
            or self.restart_delay < 0
            or self.restart_delay > 3600
        ):
            raise SubprocessServiceError("restart_delay must be between zero and 3600 seconds")
        pairs = tuple((str(key), str(value)) for key, value in self.environment)
        if len({key for key, _value in pairs}) != len(pairs):
            raise SubprocessServiceError("service environment keys must be unique")
        reserved = {_READY_FILE_ENV, _START_TOKEN_ENV, _SERVICE_NAME_ENV}
        if reserved.intersection(key for key, _value in pairs):
            raise SubprocessServiceError("service environment cannot override supervisor readiness keys")
        object.__setattr__(self, "environment", pairs)


@dataclass(frozen=True)
class SubprocessServiceReport:
    """Read-only lifecycle projection for one supervised child."""

    name: str
    state: str
    pid: int | None
    restart_count: int
    exit_code: int | None
    ready: Mapping[str, Any] | None
    last_error: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "state": self.state,
            "pid": self.pid,
            "restart_count": self.restart_count,
            "exit_code": self.exit_code,
            "ready": None if self.ready is None else dict(self.ready),
            "last_error": self.last_error,
        }


@dataclass
class _ProcessRecord:
    spec: SubprocessServiceSpec
    desired: bool = False
    process: subprocess.Popen[bytes] | None = None
    restart_count: int = 0
    exit_code: int | None = None
    state: str = "stopped"
    ready: Mapping[str, Any] | None = None
    last_error: str | None = None
    log_stream: Any | None = None


class SubprocessServiceSupervisor:
    """Own child lifetimes, verify startup readiness, and restart only within declared bounds."""

    def __init__(self) -> None:
        self._records: dict[str, _ProcessRecord] = {}
        self._lock = threading.RLock()
        self._closed = False

    def register(self, spec: SubprocessServiceSpec) -> None:
        if not isinstance(spec, SubprocessServiceSpec):
            raise SubprocessServiceError("register requires a SubprocessServiceSpec")
        with self._lock:
            if self._closed:
                raise SubprocessServiceError("supervisor is closed")
            if spec.name in self._records:
                raise SubprocessServiceError(f"service already registered: {spec.name}")
            self._records[spec.name] = _ProcessRecord(spec)

    def start(self, name: str) -> SubprocessServiceReport:
        with self._lock:
            record = self._record(name)
            if self._closed:
                raise SubprocessServiceError("supervisor is closed")
            if record.process is not None and record.process.poll() is None:
                record.desired = True
                return self._report(record)
            if record.process is not None:
                record.exit_code = record.process.returncode
                self._release_process(record)
            record.desired = True
            self._spawn(record)
            return self._report(record)

    def stop(self, name: str) -> SubprocessServiceReport:
        with self._lock:
            record = self._record(name)
            record.desired = False
            process = record.process
            if process is not None:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=record.spec.shutdown_timeout)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=record.spec.shutdown_timeout)
                record.exit_code = process.returncode
                self._release_process(record)
            record.ready = None
            record.state = "stopped"
            record.last_error = None
            return self._report(record)

    def kill(self, name: str) -> SubprocessServiceReport:
        """Hard-kill a child while preserving desired state so reconcile can exercise crash recovery."""

        with self._lock:
            record = self._record(name)
            if record.process is None:
                raise SubprocessServiceError(f"service has no child process: {name}")
            if record.process.poll() is None:
                record.process.kill()
                record.process.wait(timeout=record.spec.shutdown_timeout)
            record.exit_code = record.process.returncode
            return self._report(record)

    def reconcile(self) -> tuple[SubprocessServiceReport, ...]:
        """Observe child termination and apply each service's bounded restart transition."""

        with self._lock:
            if self._closed:
                return self.statuses()
            for name in sorted(self._records):
                self._reconcile_record(self._records[name])
            return self.statuses()

    def run_forever(
        self,
        stop_event: threading.Event,
        *,
        poll_interval: float = 0.1,
    ) -> None:
        if not isinstance(stop_event, threading.Event):
            raise SubprocessServiceError("stop_event must be a threading.Event")
        if (
            not isinstance(poll_interval, (int, float))
            or isinstance(poll_interval, bool)
            or not math.isfinite(float(poll_interval))
            or poll_interval <= 0
            or poll_interval > 60
        ):
            raise SubprocessServiceError("poll_interval must be positive and at most 60 seconds")
        while not stop_event.is_set():
            self.reconcile()
            if stop_event.wait(float(poll_interval)):
                return

    def status(self, name: str) -> SubprocessServiceReport:
        with self._lock:
            return self._report(self._record(name))

    def statuses(self) -> tuple[SubprocessServiceReport, ...]:
        with self._lock:
            return tuple(self._report(self._records[name]) for name in sorted(self._records))

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            names = tuple(sorted(self._records))
        for name in names:
            self.stop(name)

    def _reconcile_record(self, record: _ProcessRecord) -> None:
        process = record.process
        if process is None:
            if record.desired and record.state == "failed":
                self._restart(record)
            return
        code = process.poll()
        if code is None:
            return
        record.exit_code = code
        self._release_process(record)
        record.ready = None
        record.state = "exited"
        if not record.desired:
            record.state = "stopped"
            return
        should_restart = (
            record.spec.restart is RestartPolicy.ALWAYS
            or (
                record.spec.restart is RestartPolicy.ON_FAILURE
                and code != 0
            )
        )
        if not should_restart:
            return
        self._restart(record)

    def _restart(self, record: _ProcessRecord) -> None:
        if record.restart_count >= record.spec.max_restarts:
            record.state = "restart_exhausted"
            return
        record.restart_count += 1
        if record.spec.restart_delay:
            time.sleep(float(record.spec.restart_delay))
        try:
            self._spawn(record)
        except SubprocessServiceError:
            # The next reconcile cycle may consume another bounded restart slot.
            return

    def _spawn(self, record: _ProcessRecord) -> None:
        spec = record.spec
        token = uuid.uuid4().hex
        name_key = hashlib.sha256(spec.name.encode("utf-8")).hexdigest()[:16]
        ready_path = spec.readiness_directory / f"{name_key}.{token}.ready.json"
        ready_path.parent.mkdir(parents=True, exist_ok=True)
        environment = os.environ.copy()
        environment.update(dict(spec.environment))
        environment[_READY_FILE_ENV] = str(ready_path)
        environment[_START_TOKEN_ENV] = token
        environment[_SERVICE_NAME_ENV] = spec.name

        log_stream = None
        process: subprocess.Popen[bytes] | None = None
        try:
            if spec.log_path is not None:
                spec.log_path.parent.mkdir(parents=True, exist_ok=True)
                log_stream = spec.log_path.open("ab")
            output = log_stream if log_stream is not None else subprocess.DEVNULL
            process = subprocess.Popen(
                list(spec.command),
                cwd=None if spec.cwd is None else str(spec.cwd),
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT if log_stream is not None else subprocess.DEVNULL,
            )
            record.process = process
            record.log_stream = log_stream
            record.ready = None
            record.state = "starting"
            record.last_error = None
            deadline = time.monotonic() + float(spec.readiness_timeout)
            while time.monotonic() < deadline:
                code = process.poll()
                if code is not None:
                    raise SubprocessServiceError(
                        f"service {spec.name} exited before readiness with status {code}"
                    )
                if ready_path.is_file():
                    try:
                        payload = json.loads(ready_path.read_text(encoding="utf-8"))
                    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                        raise SubprocessServiceError(
                            f"service {spec.name} published malformed readiness: {exc}"
                        ) from exc
                    expected = {"schema", "service_name", "start_token", "pid", "details"}
                    if not isinstance(payload, dict) or set(payload) != expected:
                        raise SubprocessServiceError(
                            f"service {spec.name} readiness fields are malformed"
                        )
                    if (
                        payload["schema"] != _READINESS_SCHEMA
                        or payload["service_name"] != spec.name
                        or payload["start_token"] != token
                        or type(payload["pid"]) is not int
                        or payload["pid"] != process.pid
                        or not isinstance(payload["details"], dict)
                    ):
                        raise SubprocessServiceError(
                            f"service {spec.name} readiness identity does not match its child process"
                        )
                    record.ready = dict(payload["details"])
                    record.state = "running"
                    record.exit_code = None
                    record.last_error = None
                    return
                time.sleep(0.01)
            raise SubprocessServiceError(
                f"service {spec.name} did not publish readiness within {spec.readiness_timeout:g} seconds"
            )
        except Exception as exc:
            if process is not None:
                if process.poll() is None:
                    process.kill()
                try:
                    process.wait(timeout=spec.shutdown_timeout)
                except subprocess.TimeoutExpired:
                    pass
            record.exit_code = None if process is None else process.returncode
            record.process = None
            record.ready = None
            record.state = "failed"
            record.last_error = f"{type(exc).__name__}: {exc}"[:1024]
            if log_stream is not None:
                log_stream.close()
            record.log_stream = None
            raise SubprocessServiceError(record.last_error) from exc
        finally:
            try:
                ready_path.unlink()
            except FileNotFoundError:
                pass

    def _release_process(self, record: _ProcessRecord) -> None:
        if record.log_stream is not None:
            try:
                record.log_stream.close()
            finally:
                record.log_stream = None
        record.process = None

    def _report(self, record: _ProcessRecord) -> SubprocessServiceReport:
        process = record.process
        return SubprocessServiceReport(
            record.spec.name,
            record.state,
            None if process is None else process.pid,
            record.restart_count,
            record.exit_code,
            None if record.ready is None else dict(record.ready),
            record.last_error,
        )

    def _record(self, name: str) -> _ProcessRecord:
        try:
            return self._records[name]
        except KeyError as exc:
            raise KeyError(f"unknown service: {name}") from exc
