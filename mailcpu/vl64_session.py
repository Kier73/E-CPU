"""SOI-004: M3 quorum-committed VL-64 application operations inside HeadlessOS VFS.

The controller validates a remote real-VL64 computation against a separately
loaded local M2 runtime before writing its semantic output into the native
HeadlessOS virtual filesystem. The entire OS checkpoint is then published by
the *existing* M3 ComputationalSessionTransitionAdapter and majority lineage
CAS. Host-local EXECUTED receipts are evidence, not a replacement for quorum.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Callable, Mapping

from .fs import FsError
from .computational_host import (
    ComputationalBackendError,
    ComputationalHostReceipt,
    ComputationalHostRequest,
    LocalComputationalHost,
)
from .computational_transition import (
    ComputationalTransitionContext,
    ComputationalTransitionContract,
    ComputationalTransitionError,
)
from .stream_os_session import (
    OS_STATE_SCHEMA,
    restore_headless_state,
    serialize_headless_state,
)
from .vl64_runtime import VL64_OPERATOR_ID, VL64_PROTOCOL

VL64_SESSION_INPUT_SCHEMA = "mailcpu.vl64-quorum-intention.v1"
VL64_SESSION_TRANSITION_ID = "vl64.application.state-commit.v1"
VL64_SESSION_INTERPRETATION = hashlib.sha256(
    b"mailcpu.vl64-native-headless-vfs-semantic-result.v1"
).hexdigest()
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")


def _canonical(value: object) -> bytes:
    """Project a finite typed VL-64 session record to canonical JSON bytes."""
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ComputationalTransitionError("VL-64 session record is outside canonical JSON") from exc


def _decode(raw: bytes, label: str) -> dict[str, Any]:
    """Require exact canonical JSON without duplicate fields or NaN inputs."""
    if not isinstance(raw, bytes) or len(raw) > 4096:
        raise ComputationalTransitionError(label + " exceeds admitted byte size")
    def unique(pairs):
        """Refuse duplicate JSON keys rather than silently choosing a value."""
        mapping = {}
        for key, value in pairs:
            if key in mapping:
                raise ValueError("duplicate JSON key")
            mapping[key] = value
        return mapping
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique,
                           parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    except (UnicodeError, ValueError) as exc:
        raise ComputationalTransitionError(label + " cannot be decoded") from exc
    if not isinstance(value, dict) or _canonical(value) != raw:
        raise ComputationalTransitionError(label + " is not a canonical JSON mapping")
    return value


def encode_vl64_session_operation(operation: str, arguments: Mapping[str, Any]) -> bytes:
    """Bind a known host operation and finite JSON arguments without caller code."""
    if operation not in {"affine.navigate", "intention.realize", "ground.cycle", "page.cow", "core.verify", "vm.nested", "page.session"}:
        raise ComputationalTransitionError("unknown VL-64 session operation")
    if not isinstance(arguments, Mapping):
        raise ComputationalTransitionError("VL-64 arguments must be a mapping")
    encoded = _canonical({
        "schema": VL64_SESSION_INPUT_SCHEMA, "operation": operation,
        "arguments": dict(arguments),
    })
    if len(encoded) > 4096:
        raise ComputationalTransitionError("VL-64 input exceeds 4KiB")
    return encoded


def _input(raw: bytes) -> tuple[str, dict[str, Any]]:
    """Decode one exact typed VL-64 application operation."""
    record = _decode(raw, "VL-64 session input")
    if set(record) != {"schema", "operation", "arguments"} or record["schema"] != VL64_SESSION_INPUT_SCHEMA:
        raise ComputationalTransitionError("VL-64 session input fields or schema differ")
    if record["operation"] not in {"affine.navigate", "intention.realize", "ground.cycle", "page.cow", "core.verify", "vm.nested", "page.session"}:
        raise ComputationalTransitionError("VL-64 operation is unadmitted")
    if not isinstance(record["arguments"], dict):
        raise ComputationalTransitionError("VL-64 arguments are not a JSON mapping")
    return record["operation"], record["arguments"]


def vl64_session_backend_fingerprint(host: LocalComputationalHost) -> str:
    """Bind stable state semantics to this exact VL-64 backend and artifact."""
    if not isinstance(host, LocalComputationalHost):
        raise TypeError("reference host must be LocalComputationalHost")
    return hashlib.sha256(
        b"mailcpu.vl64-quorum-session-backend.v1\0"
        + bytes.fromhex(host.manifest.manifest_digest)
        + bytes.fromhex(host.profile.fingerprint)
    ).hexdigest()


def vl64_session_contract(host: LocalComputationalHost) -> ComputationalTransitionContract:
    """Declare pure M3 session revision advancement through actual VL-64."""
    return ComputationalTransitionContract(
        transition_id=VL64_SESSION_TRANSITION_ID,
        state_schema_id=OS_STATE_SCHEMA,
        input_schema_id=VL64_SESSION_INPUT_SCHEMA,
        interpretation_fingerprint=VL64_SESSION_INTERPRETATION,
        backend_fingerprint=vl64_session_backend_fingerprint(host),
        max_input_bytes=4096,
        max_state_bytes=4_194_304,
        deterministic=True,
        effect_mode="pure",
    )


class VL64QuorumSessionBackend:
    """Verify a remote real VL-64 M2 receipt, then advance a native OS checkpoint."""

    def __init__(
        self,
        reference_host: LocalComputationalHost,
        execute_remote: Callable[[str, str, dict[str, Any], ComputationalTransitionContext], dict[str, Any]],
        *,
        allowed_remote_hosts: frozenset[str],
    ) -> None:
        """Bind receiver-local source admission and an explicit remote host catalogue."""
        if not isinstance(reference_host, LocalComputationalHost):
            raise TypeError("reference_host must be LocalComputationalHost")
        if not callable(execute_remote):
            raise TypeError("execute_remote must be callable")
        if not allowed_remote_hosts or any(not isinstance(x, str) or _ID.fullmatch(x) is None for x in allowed_remote_hosts):
            raise ComputationalTransitionError("allowed_remote_hosts must contain safe host labels")
        if not reference_host.profile.deterministic or reference_host.profile.effect_mode != "pure":
            raise ComputationalTransitionError("VL-64 quorum session requires a pure M2 reference backend")
        self.reference_host = reference_host
        self.execute_remote = execute_remote
        self.allowed_remote_hosts = allowed_remote_hosts
        self.backend_fingerprint = vl64_session_backend_fingerprint(reference_host)
        self.remote_calls = 0
        self.accepted_outputs: list[str] = []

    def transition(
        self, state_bytes: bytes, input_bytes: bytes, context: ComputationalTransitionContext
    ) -> bytes:
        """Verify current M3 state, actual VL-64 output and virtual OS successor."""
        if not isinstance(context, ComputationalTransitionContext):
            raise ComputationalTransitionError("VL-64 session requires an admitted M3 context")
        if (context.backend_fingerprint != self.backend_fingerprint
            or context.execution_backend_fingerprint != self.backend_fingerprint
            or context.state_schema_id != OS_STATE_SCHEMA
            or context.interpretation_fingerprint != VL64_SESSION_INTERPRETATION
            or hashlib.sha256(state_bytes).hexdigest() != context.state_digest):
            raise ComputationalTransitionError("VL-64 session M3 binding differs from current state")
        if _ID.fullmatch(context.operation_id) is None:
            raise ComputationalTransitionError("VL-64 operation_id cannot be represented as a VFS result path")
        machine = restore_headless_state(state_bytes)
        operation, arguments = _input(input_bytes)
        if operation == "page.session":
            if set(arguments) != {"offset", "write_hex"}:
                raise ComputationalTransitionError("page.session input requires offset and write_hex")
            try:
                current_page_bytes = machine.environment.kernel.fs.read_file("/vl64/session/page-state.json")
            except FsError as exc:
                if "not found" not in str(exc):
                    raise ComputationalTransitionError("VL-64 saved application state is unreadable") from exc
                previous_hex = ""
            else:
                try:
                    current_page = json.loads(current_page_bytes)
                except (UnicodeError, ValueError) as exc:
                    raise ComputationalTransitionError("VL-64 saved application state is corrupt") from exc
                if not isinstance(current_page, dict) or set(current_page) != {
                    "schema", "state_hex", "state_digest", "logical_time",
                } or current_page["schema"] != "mailcpu.vl64-persistent-page.v1":
                    raise ComputationalTransitionError("VL-64 saved application schema differs")
                previous_hex = current_page["state_hex"]
                if not isinstance(previous_hex, str) or len(previous_hex) != 512:
                    raise ComputationalTransitionError("VL-64 saved application state has wrong length")
                try:
                    decoded_page = bytes.fromhex(previous_hex)
                except ValueError as exc:
                    raise ComputationalTransitionError("VL-64 saved application state has invalid bytes") from exc
                if (previous_hex != decoded_page.hex()
                    or hashlib.sha256(decoded_page + bytes(4096 - 256)).hexdigest() != current_page["state_digest"]
                    or type(current_page["logical_time"]) is not int
                    or current_page["logical_time"] >= context.logical_time):
                    raise ComputationalTransitionError("VL-64 saved application state fails integrity or time check")
            arguments = {"state_hex": previous_hex, **arguments}
        self.remote_calls += 1
        remote = self.execute_remote(operation, context.operation_id, arguments, context)
        if not isinstance(remote, dict) or set(remote) != {"context_binding_digest", "output", "receipt"}:
            raise ComputationalTransitionError("remote VL-64 result lacks required evidence fields")
        if remote["context_binding_digest"] != context.binding_digest:
            raise ComputationalTransitionError("remote VL-64 M3 context receipt differs")
        try:
            receipt = ComputationalHostReceipt.from_dict(remote["receipt"])
        except (ValueError, TypeError, KeyError) as exc:
            raise ComputationalTransitionError("remote VL-64 M2 receipt invalid") from exc
        if (receipt.host_id not in self.allowed_remote_hosts
            or receipt.artifact_manifest_digest != self.reference_host.manifest.manifest_digest
            or receipt.backend_fingerprint != self.reference_host.profile.fingerprint
            or receipt.request_id != context.operation_id
            or receipt.workload_id != context.session_id
            or receipt.logical_time != context.logical_time):
            raise ComputationalTransitionError("remote VL-64 host or session identity differs")
        request = ComputationalHostRequest(
            request_id=context.operation_id,
            artifact_manifest_digest=self.reference_host.manifest.manifest_digest,
            operation=operation,
            input_value=arguments,
            workload_id=context.session_id,
            logical_time=context.logical_time,
        )
        if receipt.input_digest != request.input_digest:
            raise ComputationalTransitionError("remote VL-64 M2 input digest differs")
        if hashlib.sha256(_canonical(remote["output"])).hexdigest() != receipt.output_digest:
            raise ComputationalTransitionError("remote VL-64 output differs from M2 receipt digest")
        # Independently reexecute through another fully admitted M2 runtime.
        reference = self.reference_host.execute(request)
        if remote["output"] != reference.output:
            raise ComputationalTransitionError("remote VL-64 result differs from independent reference")
        if operation == "page.session":
            page_result = remote["output"]["result"]
            if not isinstance(page_result, dict) or set(page_result) != {
                "state_hex", "state_digest", "manifest_digest", "page_bytes",
            }:
                raise ComputationalTransitionError("VL-64 persistent page result has invalid fields")
            page_hex = page_result["state_hex"]
            if not isinstance(page_hex, str) or len(page_hex) != 512:
                raise ComputationalTransitionError("VL-64 persistent page result has wrong length")
            try:
                page_raw = bytes.fromhex(page_hex)
            except ValueError as exc:
                raise ComputationalTransitionError("VL-64 persistent page result has invalid bytes") from exc
            if (page_hex != page_raw.hex()
                or page_result["page_bytes"] != 4096
                or hashlib.sha256(page_raw + bytes(4096 - 256)).hexdigest() != page_result["state_digest"]):
                raise ComputationalTransitionError("VL-64 persistent page result digest differs")
            machine.install_source(
                "/vl64/session/page-state.json",
                _canonical({
                    "schema": "mailcpu.vl64-persistent-page.v1",
                    "state_hex": page_hex,
                    "state_digest": page_result["state_digest"],
                    "logical_time": context.logical_time,
                }).decode("utf-8"),
            )
        # Host-local M2 receipt remains outside the state: a replacement host
        # may produce an equivalent semantic output and a different host receipt.
        state_record = {
            "schema": VL64_PROTOCOL,
            "operation": operation,
            "operation_id": context.operation_id,
            "logical_time": context.logical_time,
            "result": remote["output"]["result"],
        }
        machine.install_source(
            f"/vl64/results/{context.logical_time:08d}_{context.operation_id}.json",
            _canonical(state_record).decode("utf-8"),
        )
        machine.run(max_ticks=machine.vm.scheduler.tick + 1)
        candidate = serialize_headless_state(machine)
        self.accepted_outputs.append(hashlib.sha256(_canonical(state_record)).hexdigest())
        return candidate
