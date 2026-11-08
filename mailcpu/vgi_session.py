"""Mathematics: Persistent, bounded, migratable VGI Signal8 computations over M1/M3/M4.

The VGI Ground and typed task compile into an immutable interpretation
descriptor. Mutable machine snapshots are canonical state bytes in M1 and
become current only through the M3 quorum checkpoint and M4 transition CAS.
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .computational_host import (
    ComputationalArtifactComponent,
    ComputationalArtifactManifest,
)
from .computational_session import (
    BackendCompatibility,
    ComputationalSessionCheckpoint,
    ComputationalSessionError,
    ComputationalSessionIntegrityError,
    ComputationalSessionSnapshot,
    ComputationalSessionStore,
)
from .computational_transition import (
    ComputationalSessionTransitionAdapter,
    ComputationalTransitionBackend,
    ComputationalTransitionContext,
    ComputationalTransitionContract,
    ComputationalTransitionError,
)
from .vgi_host import (
    VGICompiledTaskPlan,
    VGIHostError,
    compile_vgi_signal8_task,
    vgi_signal8_implementation_fingerprint,
)

VGI_SESSION_STATE_SCHEMA = "vgi.signal8.machine-session-state.v1"
VGI_SESSION_MEDIA_TYPE = "application/vnd.mailcpu.vgi-session+json"
VGI_SESSION_STATE_ENVELOPE_SCHEMA = "mailcpu.vgi.signal8.session-state.v1"
VGI_SESSION_DESCRIPTOR_SCHEMA = "mailcpu.vgi.signal8.compiled-session-descriptor.v1"
VGI_SESSION_TRANSFER_SCHEMA = "mailcpu.vgi.signal8.session-transfer.v1"
VGI_QUANTUM_INPUT_SCHEMA = "mailcpu.vgi.signal8.quantum-request.v1"
VGI_QUANTUM_TRANSITION_ID = "vgi.signal8.execute-quantum"
VGI_QUANTUM_OPERATION_ID = "vgi.signal8.initialize"
DEFAULT_MAX_QUANTUM_STEPS = 128
DEFAULT_MAX_TOTAL_STEPS = 100_000
DEFAULT_MAX_STATE_BYTES = 64 * 1024 * 1024
MAX_VGI_SESSION_STEPS = 10_000_000
MAX_VGI_SESSION_TRANSFER_BYTES = 64 * 1024 * 1024

ImplementationCompatibility = Callable[[str, str], bool]


class VGISessionError(ComputationalTransitionError):
    """Mathematics: VGI session identity, snapshot, quantum, or migration admission failed."""


def _canonical_bytes(value: object, label: str) -> bytes:
    """Mathematics: Encode one finite JSON value as sorted compact UTF-8 bytes."""
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise VGISessionError(f"{label} is outside canonical JSON") from exc


def _sha256(data: bytes) -> str:
    """Mathematics: Return the lowercase SHA-256 identity of an exact byte sequence."""
    return hashlib.sha256(data).hexdigest()


def _vgi_program_bytes(value: object) -> bytes:
    """Mathematics: Reproduce VGI Program fingerprint encoding, including its default ASCII escaping."""
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise VGISessionError("VGI Program is outside canonical JSON") from exc


def _require_digest(value: object, name: str) -> str:
    """Mathematics: Require one exact lowercase 64-character hexadecimal SHA-256 digest."""
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise VGISessionError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _positive_integer(value: object, name: str, maximum: int) -> int:
    """Mathematics: Require a positive built-in integer within its declared finite upper bound."""
    if type(value) is not int or value < 1 or value > maximum:
        raise VGISessionError(f"{name} must be an integer in [1, {maximum}]")
    return value


def _interpretation_fingerprint(
    ground_fingerprint: str,
    task_digest: str,
    program_fingerprint: str,
) -> str:
    """Mathematics: Identify semantic interpretation independently from compiler and host implementation identity."""
    return _sha256(_canonical_bytes({
        "schema": "vgi.signal8.semantic-interpretation.v1",
        "ground_fingerprint": ground_fingerprint,
        "task_digest": task_digest,
        "program_fingerprint": program_fingerprint,
    }, "VGI semantic interpretation"))


def _compiled_plan_digest(
    ground_fingerprint: str,
    implementation_fingerprint: str,
    task_digest: str,
    program_fingerprint: str,
) -> str:
    """Mathematics: Bind the compiled VGI plan to its Ground, compiler implementation, typed task, and immutable Program."""
    return _sha256(_canonical_bytes({
        "schema": "vgi.signal8.compiled-task-plan.v1",
        "ground_fingerprint": ground_fingerprint,
        "implementation_fingerprint": implementation_fingerprint,
        "task_digest": task_digest,
        "program_fingerprint": program_fingerprint,
    }, "VGI compiled plan"))


def _artifact_manifest(
    task_bytes: bytes,
    program_bytes: bytes,
    *,
    ground_fingerprint: str,
    task_digest: str,
    program_fingerprint: str,
) -> ComputationalArtifactManifest:
    """Mathematics: Represent the declared Ground, typed task, and compiled Program as one immutable M2 artifact identity."""
    components = tuple(sorted((
        ComputationalArtifactComponent(
            path="program.json",
            size_bytes=len(program_bytes),
            content_digest=_sha256(program_bytes),
            media_type="application/json",
        ),
        ComputationalArtifactComponent(
            path="task.json",
            size_bytes=len(task_bytes),
            content_digest=_sha256(task_bytes),
            media_type="application/json",
        ),
    ), key=lambda component: component.path))
    return ComputationalArtifactManifest(
        artifact_id="vgi.signal8.compiled-program",
        artifact_kind="vgi.signal8.compiled-task",
        components=components,
        total_size_bytes=len(task_bytes) + len(program_bytes),
        metadata={
            "ground_fingerprint": ground_fingerprint,
            "task_digest": task_digest,
            "program_fingerprint": program_fingerprint,
            "representation": "typed-task-and-vgi-program-ir",
        },
    )


@dataclass(frozen=True, slots=True)
class VGICompiledSessionDescriptor:
    """Mathematics: Immutable semantic artifact and interpretation identity required to reconstruct one VGI session."""

    ground_fingerprint: str
    implementation_fingerprint: str
    task_json: str
    program_json: str
    task_digest: str
    program_fingerprint: str
    compiled_plan_digest: str
    interpretation_fingerprint: str
    artifact_manifest: ComputationalArtifactManifest
    descriptor_digest: str

    def __post_init__(self) -> None:
        """Mathematics: Validate all descriptor fingerprints, canonical task/program bytes, and M2 artifact identity."""
        for name in (
            "ground_fingerprint",
            "implementation_fingerprint",
            "task_digest",
            "program_fingerprint",
            "compiled_plan_digest",
            "interpretation_fingerprint",
            "descriptor_digest",
        ):
            _require_digest(getattr(self, name), name)
        if not isinstance(self.task_json, str) or not isinstance(self.program_json, str):
            raise VGISessionError("descriptor task_json and program_json must be strings")
        if not isinstance(self.artifact_manifest, ComputationalArtifactManifest):
            raise TypeError("artifact_manifest must be a ComputationalArtifactManifest")
        try:
            task_data = json.loads(self.task_json)
            program_data = json.loads(self.program_json)
        except json.JSONDecodeError as exc:
            raise VGISessionError("descriptor task or program JSON is malformed") from exc
        if _canonical_bytes(task_data, "descriptor task") != self.task_json.encode("utf-8"):
            raise VGISessionError("descriptor task JSON is not canonical")
        if _vgi_program_bytes(program_data) != self.program_json.encode("utf-8"):
            raise VGISessionError("descriptor program JSON is not canonical under the VGI fingerprint encoding")
        if _sha256(self.task_json.encode("utf-8")) != self.task_digest:
            raise VGISessionError("descriptor task digest does not match its canonical bytes")
        if _sha256(self.program_json.encode("utf-8")) != self.program_fingerprint:
            raise VGISessionError("descriptor program fingerprint does not match its canonical bytes")
        if self.interpretation_fingerprint != _interpretation_fingerprint(
            self.ground_fingerprint,
            self.task_digest,
            self.program_fingerprint,
        ):
            raise VGISessionError("descriptor semantic interpretation fingerprint is invalid")
        if self.compiled_plan_digest != _compiled_plan_digest(
            self.ground_fingerprint,
            self.implementation_fingerprint,
            self.task_digest,
            self.program_fingerprint,
        ):
            raise VGISessionError("descriptor compiled plan digest is invalid")
        expected_artifact = _artifact_manifest(
            self.task_json.encode("utf-8"),
            self.program_json.encode("utf-8"),
            ground_fingerprint=self.ground_fingerprint,
            task_digest=self.task_digest,
            program_fingerprint=self.program_fingerprint,
        )
        if expected_artifact.manifest_digest != self.artifact_manifest.manifest_digest:
            raise VGISessionError("descriptor artifact manifest does not bind its task and Program bytes")
        payload = self._payload_dict()
        if self.descriptor_digest != _sha256(_canonical_bytes(payload, "VGI session descriptor")):
            raise VGISessionError("VGI session descriptor digest mismatch")

    @classmethod
    def from_task(
        cls,
        task_data: Mapping[str, Any],
        ground_fingerprint: str,
    ) -> VGICompiledSessionDescriptor:
        """Mathematics: Compile a typed VGI task and derive its semantic artifact and immutable session descriptor."""
        try:
            plan = compile_vgi_signal8_task(task_data, ground_fingerprint)
        except VGIHostError as exc:
            raise VGISessionError(f"cannot compile the VGI session task: {exc}") from exc
        task_bytes = _canonical_bytes(plan.task.to_dict(), "VGI TaskSpec")
        program_bytes = _vgi_program_bytes(plan.program.to_dict())
        artifact = _artifact_manifest(
            task_bytes,
            program_bytes,
            ground_fingerprint=plan.ground_fingerprint,
            task_digest=plan.task_digest,
            program_fingerprint=plan.program_fingerprint,
        )
        semantic_fingerprint = _interpretation_fingerprint(
            plan.ground_fingerprint,
            plan.task_digest,
            plan.program_fingerprint,
        )
        payload = {
            "schema": VGI_SESSION_DESCRIPTOR_SCHEMA,
            "ground_fingerprint": plan.ground_fingerprint,
            "implementation_fingerprint": plan.implementation_fingerprint,
            "task_json": task_bytes.decode("utf-8"),
            "program_json": program_bytes.decode("utf-8"),
            "task_digest": plan.task_digest,
            "program_fingerprint": plan.program_fingerprint,
            "compiled_plan_digest": plan.plan_digest,
            "interpretation_fingerprint": semantic_fingerprint,
            "artifact_manifest": artifact.to_dict(),
        }
        descriptor = cls(
            ground_fingerprint=plan.ground_fingerprint,
            implementation_fingerprint=plan.implementation_fingerprint,
            task_json=payload["task_json"],
            program_json=payload["program_json"],
            task_digest=plan.task_digest,
            program_fingerprint=plan.program_fingerprint,
            compiled_plan_digest=plan.plan_digest,
            interpretation_fingerprint=semantic_fingerprint,
            artifact_manifest=artifact,
            descriptor_digest=_sha256(_canonical_bytes(payload, "VGI session descriptor")),
        )
        return descriptor

    @property
    def artifact_manifest_digest(self) -> str:
        """Mathematics: Expose the exact M2 artifact manifest identity used by the M3 session checkpoint."""
        return self.artifact_manifest.manifest_digest

    @property
    def task_data(self) -> dict[str, Any]:
        """Mathematics: Decode a detached typed task declaration from its canonical descriptor bytes."""
        return json.loads(self.task_json)

    @property
    def program_data(self) -> dict[str, Any]:
        """Mathematics: Decode a detached immutable VGI Program representation from its canonical descriptor bytes."""
        return json.loads(self.program_json)

    def _payload_dict(self) -> dict[str, object]:
        """Mathematics: Project all descriptor identities except the self-referential descriptor digest."""
        return {
            "schema": VGI_SESSION_DESCRIPTOR_SCHEMA,
            "ground_fingerprint": self.ground_fingerprint,
            "implementation_fingerprint": self.implementation_fingerprint,
            "task_json": self.task_json,
            "program_json": self.program_json,
            "task_digest": self.task_digest,
            "program_fingerprint": self.program_fingerprint,
            "compiled_plan_digest": self.compiled_plan_digest,
            "interpretation_fingerprint": self.interpretation_fingerprint,
            "artifact_manifest": self.artifact_manifest.to_dict(),
        }

    def to_dict(self) -> dict[str, object]:
        """Mathematics: Export the complete semantic descriptor with its verified self-digest."""
        return self._payload_dict() | {"descriptor_digest": self.descriptor_digest}

    def resolve_local_plan(
        self,
        *,
        implementation_compatibility: ImplementationCompatibility | None = None,
    ) -> VGICompiledTaskPlan:
        """Mathematics: Recompile the declared task locally and require exact Ground/task/Program semantics before restoring state."""
        try:
            plan = compile_vgi_signal8_task(self.task_data, self.ground_fingerprint)
        except VGIHostError as exc:
            raise VGISessionError(f"target cannot compile the VGI session descriptor: {exc}") from exc
        if (
            plan.task_digest != self.task_digest
            or plan.program_fingerprint != self.program_fingerprint
            or plan.ground_fingerprint != self.ground_fingerprint
        ):
            raise VGISessionError("target VGI compiler produced a different Ground, task, or Program identity")
        if plan.implementation_fingerprint != self.implementation_fingerprint:
            if implementation_compatibility is None:
                raise VGISessionError(
                    "VGI implementation changed; an explicit implementation compatibility predicate is required"
                )
            try:
                compatible = implementation_compatibility(
                    self.implementation_fingerprint,
                    plan.implementation_fingerprint,
                )
            except Exception as exc:
                raise VGISessionError("VGI implementation compatibility predicate failed") from exc
            if compatible is not True:
                raise VGISessionError("target VGI implementation refused the source descriptor")
        elif plan.plan_digest != self.compiled_plan_digest:
            raise VGISessionError("local VGI compiled-plan identity differs from the session descriptor")
        return plan

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
        *,
        implementation_compatibility: ImplementationCompatibility | None = None,
    ) -> VGICompiledSessionDescriptor:
        """Mathematics: Decode a portable descriptor, verify every digest, and prove local semantic recompilation or explicit implementation compatibility."""
        expected = {
            "schema",
            "ground_fingerprint",
            "implementation_fingerprint",
            "task_json",
            "program_json",
            "task_digest",
            "program_fingerprint",
            "compiled_plan_digest",
            "interpretation_fingerprint",
            "artifact_manifest",
            "descriptor_digest",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise VGISessionError("VGI session descriptor fields are invalid")
        if payload["schema"] != VGI_SESSION_DESCRIPTOR_SCHEMA:
            raise VGISessionError("unsupported VGI session descriptor schema")
        try:
            artifact = ComputationalArtifactManifest.from_dict(payload["artifact_manifest"])
            descriptor = cls(
                ground_fingerprint=payload["ground_fingerprint"],
                implementation_fingerprint=payload["implementation_fingerprint"],
                task_json=payload["task_json"],
                program_json=payload["program_json"],
                task_digest=payload["task_digest"],
                program_fingerprint=payload["program_fingerprint"],
                compiled_plan_digest=payload["compiled_plan_digest"],
                interpretation_fingerprint=payload["interpretation_fingerprint"],
                artifact_manifest=artifact,
                descriptor_digest=payload["descriptor_digest"],
            )
        except (TypeError, ValueError, KeyError) as exc:
            if isinstance(exc, VGISessionError):
                raise
            raise VGISessionError("VGI session descriptor is malformed") from exc
        descriptor.resolve_local_plan(implementation_compatibility=implementation_compatibility)
        return descriptor


def _session_state_bytes(
    descriptor: VGICompiledSessionDescriptor,
    machine_snapshot: Mapping[str, Any],
    *,
    status: str,
    last_quantum_steps: int,
) -> bytes:
    """Mathematics: Encode one resumable VGI machine snapshot together with its immutable interpretation and bounded quantum status."""
    return _canonical_bytes({
        "schema": VGI_SESSION_STATE_ENVELOPE_SCHEMA,
        "descriptor_digest": descriptor.descriptor_digest,
        "machine_snapshot": dict(machine_snapshot),
        "status": status,
        "last_quantum_steps": last_quantum_steps,
    }, "VGI session state")


def _decode_session_state(
    state_bytes: bytes,
    descriptor: VGICompiledSessionDescriptor,
    plan: VGICompiledTaskPlan,
    *,
    max_quantum_steps: int,
    max_total_steps: int,
) -> tuple[Any, str, int]:
    """Mathematics: Verify the canonical session envelope and restore its machine only under the exact descriptor Ground and Program."""
    try:
        payload = json.loads(state_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VGISessionError("VGI session state is not valid UTF-8 JSON") from exc
    expected = {"schema", "descriptor_digest", "machine_snapshot", "status", "last_quantum_steps"}
    if (
        not isinstance(payload, Mapping)
        or set(payload) != expected
        or payload["schema"] != VGI_SESSION_STATE_ENVELOPE_SCHEMA
        or _canonical_bytes(payload, "VGI session state") != state_bytes
    ):
        raise VGISessionError("VGI session state envelope fields or canonical representation are invalid")
    if payload["descriptor_digest"] != descriptor.descriptor_digest:
        raise VGISessionError("VGI machine state belongs to another compiled session descriptor")
    status = payload["status"]
    if status not in {"ready", "running", "halted", "step_limit"}:
        raise VGISessionError("VGI session status is invalid")
    last_steps = payload["last_quantum_steps"]
    if type(last_steps) is not int or last_steps < 0 or last_steps > max_quantum_steps:
        raise VGISessionError("VGI session last_quantum_steps is outside its declared bound")
    try:
        from vgi import SIGNAL8_GROUND, SignalStateMachine, VirtualGroundInterpreter
    except ImportError as exc:
        raise VGISessionError("the VGI optional dependency is required to restore a session") from exc
    if descriptor.ground_fingerprint != SIGNAL8_GROUND.fingerprint:
        raise VGISessionError("the VGI session Ground is not installed on this host")
    interpreter = VirtualGroundInterpreter(ground=SIGNAL8_GROUND)
    try:
        machine = SignalStateMachine.restore(interpreter, plan.program, payload["machine_snapshot"])
    except Exception as exc:
        raise VGISessionError(f"VGI machine checkpoint failed restoration: {exc}") from exc
    total_steps = len(machine.trace)
    if total_steps > max_total_steps:
        raise VGISessionError("VGI machine checkpoint exceeds max_total_steps")
    if last_steps > total_steps:
        raise VGISessionError("VGI session last_quantum_steps exceeds its cumulative instruction trace")
    if status == "ready" and (total_steps != 0 or last_steps != 0):
        raise VGISessionError("ready VGI session must have an untouched machine checkpoint")
    if status == "running" and (machine.halted or total_steps == 0):
        raise VGISessionError("running VGI session must have executed instructions and remain non-terminal")
    if machine.halted and status != "halted":
        raise VGISessionError("halted VGI machine is not marked halted in its session envelope")
    if not machine.halted and status == "halted":
        raise VGISessionError("VGI session is marked halted but its machine is not halted")
    if not machine.halted and status == "step_limit" and total_steps < max_total_steps:
        raise VGISessionError("VGI step_limit status is inconsistent with the cumulative step count")
    if not machine.halted and total_steps >= max_total_steps and status != "step_limit":
        raise VGISessionError("VGI session reached max_total_steps without recording step_limit")
    return machine, status, last_steps


class _VGISessionTransitionBackend(ComputationalTransitionBackend):
    """Mathematics: Pure backend that restores, advances, and snapshots one bounded VGI SignalStateMachine quantum."""

    def __init__(
        self,
        descriptor: VGICompiledSessionDescriptor,
        plan: VGICompiledTaskPlan,
        backend_fingerprint: str,
        *,
        max_quantum_steps: int,
        max_total_steps: int,
    ) -> None:
        """Mathematics: Bind one compiled VGI Program and exact host execution profile to a bounded state transition."""
        self.descriptor = descriptor
        self.plan = plan
        self.backend_fingerprint = backend_fingerprint
        self.max_quantum_steps = max_quantum_steps
        self.max_total_steps = max_total_steps

    def transition(
        self,
        state_bytes: bytes,
        input_bytes: bytes,
        context: ComputationalTransitionContext,
    ) -> bytes:
        """Mathematics: Apply at most quantum_steps VGI instructions and return the exact canonical successor machine state."""
        if context.interpretation_fingerprint != self.descriptor.interpretation_fingerprint:
            raise VGISessionError("transition context interpretation differs from the compiled VGI descriptor")
        if context.execution_backend_fingerprint != self.backend_fingerprint:
            raise VGISessionError("transition context execution backend differs from the admitted VGI quantum backend")
        try:
            request = json.loads(input_bytes)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise VGISessionError("VGI quantum request is not valid UTF-8 JSON") from exc
        if (
            not isinstance(request, Mapping)
            or set(request) != {"schema", "quantum_steps"}
            or request["schema"] != VGI_QUANTUM_INPUT_SCHEMA
            or _canonical_bytes(request, "VGI quantum request") != input_bytes
        ):
            raise VGISessionError("VGI quantum request fields or canonical representation are invalid")
        quantum_steps = _positive_integer(
            request["quantum_steps"],
            "quantum_steps",
            self.max_quantum_steps,
        )
        machine, status, _last_steps = _decode_session_state(
            state_bytes,
            self.descriptor,
            self.plan,
            max_quantum_steps=self.max_quantum_steps,
            max_total_steps=self.max_total_steps,
        )
        if status in {"halted", "step_limit"}:
            raise VGISessionError(f"cannot advance a VGI session in {status} status")
        total_steps = len(machine.trace)
        remaining = self.max_total_steps - total_steps
        if remaining <= 0:
            raise VGISessionError("VGI session exhausted max_total_steps")
        actual_steps = min(quantum_steps, remaining)
        executed = 0
        while executed < actual_steps and not machine.halted:
            machine.step()
            executed += 1
        if machine.halted:
            next_status = "halted"
        elif len(machine.trace) >= self.max_total_steps:
            next_status = "step_limit"
        else:
            next_status = "running"
        return _session_state_bytes(
            self.descriptor,
            machine.snapshot(),
            status=next_status,
            last_quantum_steps=executed,
        )


def vgi_signal8_session_backend_fingerprint(
    *,
    max_quantum_steps: int = DEFAULT_MAX_QUANTUM_STEPS,
    max_total_steps: int = DEFAULT_MAX_TOTAL_STEPS,
    max_state_bytes: int = DEFAULT_MAX_STATE_BYTES,
) -> str:
    """Mathematics: Fingerprint the VGI session transition implementation together with its quantum, total-step, and state-size execution profile."""
    quantum_limit = _positive_integer(max_quantum_steps, "max_quantum_steps", MAX_VGI_SESSION_STEPS)
    total_limit = _positive_integer(max_total_steps, "max_total_steps", MAX_VGI_SESSION_STEPS)
    state_limit = _positive_integer(max_state_bytes, "max_state_bytes", MAX_VGI_SESSION_TRANSFER_BYTES)
    if quantum_limit > total_limit:
        raise VGISessionError("max_quantum_steps cannot exceed max_total_steps")
    try:
        source_fingerprint = vgi_signal8_implementation_fingerprint(
            _VGISessionTransitionBackend,
            max_configured_steps=quantum_limit,
        )
    except VGIHostError as exc:
        raise VGISessionError(f"cannot fingerprint the VGI session backend: {exc}") from exc
    return _sha256(_canonical_bytes({
        "schema": "vgi.signal8.session-backend-profile.v1",
        "source_fingerprint": source_fingerprint,
        "max_quantum_steps": quantum_limit,
        "max_total_steps": total_limit,
        "max_state_bytes": state_limit,
        "state_schema_id": VGI_SESSION_STATE_SCHEMA,
        "transition_id": VGI_QUANTUM_TRANSITION_ID,
    }, "VGI session backend profile"))


@dataclass(frozen=True, slots=True)
class VGISessionExecution:
    """Mathematics: One verified session revision projected into its restored VGI execution result and continuation status."""

    session: ComputationalSessionSnapshot
    execution: Any
    status: str
    last_quantum_steps: int
    descriptor_digest: str

    @property
    def revision(self) -> int:
        """Mathematics: Expose the committed M3 revision carrying this VGI machine state."""
        return self.session.revision

    @property
    def checkpoint_digest(self) -> str:
        """Mathematics: Expose the exact quorum-anchored checkpoint identity for the next CAS transition."""
        return self.session.checkpoint_digest

    @property
    def replayed(self) -> bool:
        """Mathematics: Expose whether the M3/M4 path returned an exact immediate operation replay."""
        return self.session.replayed

    @property
    def halted(self) -> bool:
        """Mathematics: Expose the VGI machine terminal condition independently from session persistence status."""
        return bool(self.execution.halted)

    @property
    def total_steps(self) -> int:
        """Mathematics: Return the cumulative number of committed VGI instruction events retained in the machine trace."""
        return len(self.execution.trace)


class VGISessionTransferBundle:
    """Mathematics: Portable VGI session package containing semantic descriptor, M3 proof, M1 manifest, and exact state bytes."""

    def __init__(
        self,
        descriptor: Mapping[str, Any],
        session_export: Mapping[str, Any],
        state_manifest: Mapping[str, Any],
        state_bytes: bytes,
        bundle_digest: str,
    ) -> None:
        """Mathematics: Validate one in-memory transfer package before it is admitted by a target host."""
        if not isinstance(descriptor, Mapping) or not isinstance(session_export, Mapping):
            raise TypeError("transfer descriptor and session_export must be mappings")
        if not isinstance(state_manifest, Mapping) or not isinstance(state_bytes, bytes):
            raise TypeError("transfer state_manifest must be a mapping and state_bytes must be bytes")
        self.descriptor = dict(descriptor)
        self.session_export = dict(session_export)
        self.state_manifest = dict(state_manifest)
        self.state_bytes = state_bytes
        self.bundle_digest = _require_digest(bundle_digest, "bundle_digest")
        if self.bundle_digest != _sha256(_canonical_bytes(self._payload_dict(), "VGI transfer bundle")):
            raise VGISessionError("VGI session transfer bundle digest mismatch")

    @classmethod
    def create(
        cls,
        descriptor: VGICompiledSessionDescriptor,
        session_export: Mapping[str, Any],
        state_manifest: Mapping[str, Any],
        state_bytes: bytes,
    ) -> VGISessionTransferBundle:
        """Mathematics: Bind a verified VGI session descriptor and M3 export to exact M1 state-object bytes."""
        if not isinstance(descriptor, VGICompiledSessionDescriptor):
            raise TypeError("descriptor must be a VGICompiledSessionDescriptor")
        if not isinstance(session_export, Mapping) or not isinstance(state_manifest, Mapping):
            raise TypeError("session_export and state_manifest must be mappings")
        if not isinstance(state_bytes, bytes):
            raise TypeError("state_bytes must be bytes")
        if len(state_bytes) > MAX_VGI_SESSION_TRANSFER_BYTES:
            raise VGISessionError("VGI session transfer state exceeds the maximum bundle extent")
        try:
            checkpoint = ComputationalSessionCheckpoint.from_dict(session_export["checkpoint"])
        except (KeyError, TypeError, ValueError) as exc:
            raise VGISessionError("VGI session transfer requires a typed M3 checkpoint export") from exc
        if state_manifest != checkpoint.state_manifest.to_dict():
            raise VGISessionError("transfer M1 manifest differs from the M3 checkpoint manifest")
        if (
            len(state_bytes) != checkpoint.state_manifest.size_bytes
            or _sha256(state_bytes) != checkpoint.state_manifest.content_digest
        ):
            raise VGISessionError("transfer state bytes do not match the M3 checkpoint M1 manifest")
        if checkpoint.artifact_manifest_digest != descriptor.artifact_manifest_digest:
            raise VGISessionError("M3 checkpoint artifact differs from the VGI descriptor")
        if checkpoint.state_schema_id != VGI_SESSION_STATE_SCHEMA:
            raise VGISessionError("M3 checkpoint state schema differs from the VGI session schema")
        payload = {
            "schema": VGI_SESSION_TRANSFER_SCHEMA,
            "descriptor": descriptor.to_dict(),
            "session_export": dict(session_export),
            "state_manifest": dict(state_manifest),
            "state_bytes_digest": _sha256(state_bytes),
            "state_size_bytes": len(state_bytes),
        }
        digest = _sha256(_canonical_bytes(payload, "VGI transfer bundle"))
        return cls(
            descriptor.to_dict(),
            dict(session_export),
            dict(state_manifest),
            state_bytes,
            digest,
        )

    def _payload_dict(self) -> dict[str, object]:
        """Mathematics: Project transfer identities while replacing the raw state bytes by their digest and exact extent."""
        return {
            "schema": VGI_SESSION_TRANSFER_SCHEMA,
            "descriptor": self.descriptor,
            "session_export": self.session_export,
            "state_manifest": self.state_manifest,
            "state_bytes_digest": _sha256(self.state_bytes),
            "state_size_bytes": len(self.state_bytes),
        }

    def to_dict(self) -> dict[str, object]:
        """Mathematics: Encode the portable transfer package with base64 state bytes and its verified bundle digest."""
        payload = self._payload_dict()
        payload["state_bytes_base64"] = base64.b64encode(self.state_bytes).decode("ascii")
        payload["bundle_digest"] = self.bundle_digest
        return payload

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
        *,
        max_state_bytes: int = DEFAULT_MAX_STATE_BYTES,
    ) -> VGISessionTransferBundle:
        """Mathematics: Decode a bounded base64 VGI session transfer and verify its bundle, state extent, and content digest."""
        maximum = _positive_integer(max_state_bytes, "max_state_bytes", MAX_VGI_SESSION_TRANSFER_BYTES)
        expected = {
            "schema",
            "descriptor",
            "session_export",
            "state_manifest",
            "state_bytes_digest",
            "state_size_bytes",
            "state_bytes_base64",
            "bundle_digest",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise VGISessionError("VGI transfer bundle fields are invalid")
        if payload["schema"] != VGI_SESSION_TRANSFER_SCHEMA:
            raise VGISessionError("unsupported VGI transfer bundle schema")
        size = payload["state_size_bytes"]
        if type(size) is not int or size < 0 or size > maximum:
            raise VGISessionError("VGI transfer state extent exceeds its declared bound")
        try:
            state_bytes = base64.b64decode(payload["state_bytes_base64"], validate=True)
        except (TypeError, ValueError) as exc:
            raise VGISessionError("VGI transfer state bytes are not valid base64") from exc
        if len(state_bytes) != size or _sha256(state_bytes) != payload["state_bytes_digest"]:
            raise VGISessionError("VGI transfer state length or digest mismatch")
        try:
            bundle = cls(
                payload["descriptor"],
                payload["session_export"],
                payload["state_manifest"],
                state_bytes,
                payload["bundle_digest"],
            )
        except (TypeError, ValueError) as exc:
            if isinstance(exc, VGISessionError):
                raise
            raise VGISessionError("VGI transfer bundle is malformed") from exc
        return bundle


class VGIPersistentSession:
    """Mathematics: M5-M7 VGI session host joining compiled semantics, bounded execution, quorum state, and host transfer."""

    def __init__(
        self,
        session_store: ComputationalSessionStore,
        descriptor: VGICompiledSessionDescriptor,
        *,
        max_quantum_steps: int = DEFAULT_MAX_QUANTUM_STEPS,
        max_total_steps: int = DEFAULT_MAX_TOTAL_STEPS,
        max_state_bytes: int = DEFAULT_MAX_STATE_BYTES,
        backend_compatibility: BackendCompatibility | None = None,
        implementation_compatibility: ImplementationCompatibility | None = None,
    ) -> None:
        """Mathematics: Bind one compiled VGI descriptor to an M3 store and a receiver-local bounded transition backend."""
        if not isinstance(session_store, ComputationalSessionStore):
            raise TypeError("session_store must be a ComputationalSessionStore")
        if not isinstance(descriptor, VGICompiledSessionDescriptor):
            raise TypeError("descriptor must be a VGICompiledSessionDescriptor")
        self.max_quantum_steps = _positive_integer(
            max_quantum_steps,
            "max_quantum_steps",
            MAX_VGI_SESSION_STEPS,
        )
        self.max_total_steps = _positive_integer(
            max_total_steps,
            "max_total_steps",
            MAX_VGI_SESSION_STEPS,
        )
        self.max_state_bytes = _positive_integer(
            max_state_bytes,
            "max_state_bytes",
            MAX_VGI_SESSION_TRANSFER_BYTES,
        )
        if self.max_quantum_steps > self.max_total_steps:
            raise VGISessionError("max_quantum_steps cannot exceed max_total_steps")
        if self.max_state_bytes > session_store.object_store.max_object_bytes:
            raise VGISessionError("max_state_bytes exceeds the M1 object-store limit")
        if session_store.state_schema_id != VGI_SESSION_STATE_SCHEMA:
            raise VGISessionError("M3 session state_schema_id does not match the VGI machine-state schema")
        if session_store.state_media_type != VGI_SESSION_MEDIA_TYPE:
            raise VGISessionError("M3 session state_media_type does not match the VGI machine-state media type")
        if session_store.artifact_manifest_digest != descriptor.artifact_manifest_digest:
            raise VGISessionError("M3 session artifact manifest differs from the compiled VGI descriptor")
        if backend_compatibility is not None and not callable(backend_compatibility):
            raise TypeError("backend_compatibility must be callable")
        if implementation_compatibility is not None and not callable(implementation_compatibility):
            raise TypeError("implementation_compatibility must be callable")
        plan = descriptor.resolve_local_plan(
            implementation_compatibility=implementation_compatibility,
        )
        self.session_store = session_store
        self.descriptor = descriptor
        self.plan = plan
        self.backend_compatibility = backend_compatibility
        self.implementation_compatibility = implementation_compatibility
        self.backend_fingerprint = vgi_signal8_session_backend_fingerprint(
            max_quantum_steps=self.max_quantum_steps,
            max_total_steps=self.max_total_steps,
            max_state_bytes=self.max_state_bytes,
        )
        if session_store.backend_fingerprint != self.backend_fingerprint:
            raise VGISessionError("M3 session backend fingerprint does not match the VGI session execution profile")
        backend = _VGISessionTransitionBackend(
            descriptor,
            plan,
            self.backend_fingerprint,
            max_quantum_steps=self.max_quantum_steps,
            max_total_steps=self.max_total_steps,
        )
        contract = ComputationalTransitionContract(
            transition_id=VGI_QUANTUM_TRANSITION_ID,
            state_schema_id=VGI_SESSION_STATE_SCHEMA,
            input_schema_id=VGI_QUANTUM_INPUT_SCHEMA,
            interpretation_fingerprint=descriptor.interpretation_fingerprint,
            backend_fingerprint=self.backend_fingerprint,
            max_input_bytes=1024,
            max_state_bytes=self.max_state_bytes,
            deterministic=True,
            effect_mode="pure",
        )
        self.transition_adapter = ComputationalSessionTransitionAdapter(
            session_store,
            contract,
            backend,
            backend_compatibility=backend_compatibility,
        )

    def initialize(self, initial_memory: Mapping[str, Any]) -> VGISessionExecution:
        """Mathematics: Admit typed initial signal memory as revision one under the compiled VGI artifact and Ground."""
        if not isinstance(initial_memory, Mapping):
            raise VGISessionError("initial_memory must be a mapping of declared task addresses to SignalValue data")
        try:
            from vgi import SIGNAL8_GROUND, SignalValue, VirtualGroundInterpreter
        except ImportError as exc:
            raise VGISessionError("the VGI optional dependency is required to initialize a session") from exc
        if set(initial_memory) != set(self.plan.task.inputs):
            raise VGISessionError("initial memory addresses must exactly match the VGI TaskSpec inputs")
        normalized: dict[str, Any] = {}
        for address, value in initial_memory.items():
            try:
                signal = value if isinstance(value, SignalValue) else SignalValue.from_dict(value)
            except Exception as exc:
                raise VGISessionError(f"initial memory cell {address!r} is not a valid VGI SignalValue") from exc
            normalized[address] = signal
        interpreter = VirtualGroundInterpreter(ground=SIGNAL8_GROUND)
        try:
            machine = interpreter.instantiate(self.plan.program, normalized)
        except Exception as exc:
            raise VGISessionError(f"VGI initial machine admission failed: {exc}") from exc
        memory_dict = {address: value.to_dict() for address, value in sorted(normalized.items())}
        input_digest = _sha256(_canonical_bytes({
            "schema": "vgi.signal8.initial-memory.v1",
            "descriptor_digest": self.descriptor.descriptor_digest,
            "memory": memory_dict,
        }, "VGI initial memory"))
        state_bytes = _session_state_bytes(
            self.descriptor,
            machine.snapshot(),
            status="ready",
            last_quantum_steps=0,
        )
        if len(state_bytes) > self.max_state_bytes:
            raise VGISessionError("initial VGI machine checkpoint exceeds max_state_bytes")
        try:
            snapshot = self.session_store.create_session(
                state_bytes,
                transition_id="vgi.signal8.initialize",
                operation_id="vgi.signal8.initialize",
                input_digest=input_digest,
                logical_time=0,
            )
        except ComputationalSessionError as exc:
            raise VGISessionError(f"cannot initialize the VGI computational session: {exc}") from exc
        return self._view(snapshot)

    def load(self) -> VGISessionExecution:
        """Mathematics: Restore the machine only from the current M1-verified and quorum-anchored session revision."""
        try:
            snapshot = self.session_store.load_latest(
                backend_compatibility=self.backend_compatibility,
            )
        except ComputationalSessionError as exc:
            raise VGISessionError(f"cannot load the latest VGI session state: {exc}") from exc
        return self._view(snapshot)

    def advance(
        self,
        quantum_steps: int,
        *,
        operation_id: str,
        logical_time: int | None = None,
        expected_revision: int | None = None,
        expected_checkpoint_digest: str | None = None,
    ) -> VGISessionExecution:
        """Mathematics: Execute one bounded VGI instruction quantum and quorum-commit its resumable machine checkpoint."""
        quantum = _positive_integer(quantum_steps, "quantum_steps", self.max_quantum_steps)
        current = self.load()
        if current.status in {"halted", "step_limit"}:
            if current.session.checkpoint.operation_id == operation_id:
                pass
            else:
                if current.status == "halted":
                    return current
                raise VGISessionError("VGI session has exhausted max_total_steps")
        input_bytes = _canonical_bytes({
            "schema": VGI_QUANTUM_INPUT_SCHEMA,
            "quantum_steps": quantum,
        }, "VGI quantum request")
        try:
            committed = self.transition_adapter.apply(
                input_bytes,
                operation_id=operation_id,
                logical_time=logical_time,
                expected_revision=expected_revision,
                expected_checkpoint_digest=expected_checkpoint_digest,
            )
        except ComputationalSessionError as exc:
            raise VGISessionError(f"VGI quantum transition was not committed: {exc}") from exc
        return self._view(committed)

    def export_transfer(self) -> VGISessionTransferBundle:
        """Mathematics: Package the current semantic descriptor, M3 quorum evidence, M1 manifest, and exact state bytes for transit."""
        current = self.load()
        export = current.session.export_dict()
        manifest = current.session.checkpoint.state_manifest.to_dict()
        return VGISessionTransferBundle.create(
            self.descriptor,
            export,
            manifest,
            current.session.state_bytes,
        )

    def restore_transfer(
        self,
        transfer: VGISessionTransferBundle | Mapping[str, Any],
    ) -> VGISessionExecution:
        """Mathematics: Re-admit transferred M1 pages, verify source descriptor and quorum proof, then restore the same VGI machine on this host."""
        bundle = (
            transfer
            if isinstance(transfer, VGISessionTransferBundle)
            else VGISessionTransferBundle.from_dict(
                transfer,
                max_state_bytes=self.max_state_bytes,
            )
        )
        if bundle.descriptor.get("descriptor_digest") != self.descriptor.descriptor_digest:
            raise VGISessionError("transfer bundle belongs to another compiled VGI session descriptor")
        if bundle.descriptor != self.descriptor.to_dict():
            raise VGISessionError("transfer descriptor differs from the locally admitted VGI session descriptor")
        try:
            checkpoint = ComputationalSessionCheckpoint.from_dict(
                bundle.session_export["checkpoint"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise VGISessionError("transfer bundle contains an invalid M3 checkpoint") from exc
        if bundle.state_manifest != checkpoint.state_manifest.to_dict():
            raise VGISessionError("transferred M1 manifest differs from the quorum-anchored checkpoint manifest")
        if (
            len(bundle.state_bytes) != checkpoint.state_manifest.size_bytes
            or _sha256(bundle.state_bytes) != checkpoint.state_manifest.content_digest
        ):
            raise VGISessionError("transferred VGI state bytes do not match the M1 manifest")
        if len(bundle.state_bytes) > self.max_state_bytes:
            raise VGISessionError("transferred VGI state bytes exceed the target max_state_bytes")
        try:
            admitted_manifest = self.session_store.object_store.put_bytes(
                bundle.state_bytes,
                media_type=self.session_store.state_media_type,
            )
        except Exception as exc:
            raise VGISessionError("target M1 page store refused transferred VGI state bytes") from exc
        if admitted_manifest.to_dict() != checkpoint.state_manifest.to_dict():
            raise VGISessionError(
                "target M1 page geometry differs from the anchored manifest; transfer requires matching chunk geometry"
            )
        try:
            restored = self.session_store.restore_export(
                bundle.session_export,
                backend_compatibility=self.backend_compatibility,
            )
        except ComputationalSessionError as exc:
            raise VGISessionError(f"target could not verify the source quorum lineage: {exc}") from exc
        return self._view(restored)

    def _view(self, snapshot: ComputationalSessionSnapshot) -> VGISessionExecution:
        """Mathematics: Project one verified byte snapshot into an exact restored machine and its cumulative execution result."""
        if (
            snapshot.checkpoint.artifact_manifest_digest != self.descriptor.artifact_manifest_digest
            or snapshot.checkpoint.state_schema_id != VGI_SESSION_STATE_SCHEMA
        ):
            raise VGISessionError("M3 session checkpoint does not match the admitted VGI artifact or state schema")
        machine, status, last_steps = _decode_session_state(
            snapshot.state_bytes,
            self.descriptor,
            self.plan,
            max_quantum_steps=self.max_quantum_steps,
            max_total_steps=self.max_total_steps,
        )
        return VGISessionExecution(
            session=snapshot,
            execution=machine.result(),
            status=status,
            last_quantum_steps=last_steps,
            descriptor_digest=self.descriptor.descriptor_digest,
        )
