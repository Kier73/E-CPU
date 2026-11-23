"""SOI-007: E-CPU M3 continuity of original VL-I TIME-001/002 intelligence.

Each pure transition resumes a *real* TemporalIntelligenceGround from a
quorum-verified HeadlessOS checkpoint, invokes an admitted Python observer-host
process, independently reexecutes its native VL-I interpreter through E-CPU M2,
and publishes the successor Ground and native VM state with original M3 CAS.

The source_digest inside an observed sample is evidence claimed by its caller,
not a digital signature or independent attestation of physical observation.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Callable, Mapping

from .computational_host import (
    ComputationalHostReceipt, ComputationalHostRequest, LocalComputationalHost,
)
from .computational_transition import (
    ComputationalTransitionContext, ComputationalTransitionContract,
    ComputationalTransitionError,
)
from .stream_os_session import (
    OS_STATE_SCHEMA, restore_headless_state, serialize_headless_state,
)
from .vli_temporal_host import (
    VLI_TEMPORAL_HOST_SCHEMA, create_vli_temporal_genesis,
)
from .vli_signed_source import (
    verify_signed_history, verify_next_signed_packet, write_signed_packet,
)

VLI_TEMPORAL_SESSION_INPUT = "mailcpu.vli-observer-session-request.v1"
VLI_TEMPORAL_SESSION_INTERPRETATION = hashlib.sha256(
    b"mailcpu.original-vli-time001-002-in-headlessos-m3.v2-signed-source"
).hexdigest()
VLI_TEMPORAL_SESSION_TRANSITION = "vli.temporal.living-session.v2"
VLI_STATE_PATH = "/vli/temporal/state.json"
_VLI_OPS = frozenset({
    "temporal.ingest", "temporal.ingest_signed", "temporal.inquire", "temporal.compile", "temporal.navigate",
})
_SAFE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
_MAX_INPUT = 8192
_MAX_STATE = 4_194_304


def _canonical(value: Any) -> bytes:
    """Encode a finite JSON record with exactly one deterministic byte layout."""
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ComputationalTransitionError("VL-I semantic record is outside canonical JSON") from exc


def _decode(raw: bytes, *, max_bytes: int, kind: str) -> dict[str, Any]:
    """Decode bounded canonical UTF-8 JSON and refuse repeated keys."""
    if not isinstance(raw, bytes) or len(raw) > max_bytes:
        raise ComputationalTransitionError(kind + " exceeds its byte admission")
    def unique(pairs):
        """Forbid ambiguous duplicate-key source observations."""
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result
    try:
        record = json.loads(
            raw.decode("utf-8"), object_pairs_hook=unique,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
        )
    except (ValueError, UnicodeError) as exc:
        raise ComputationalTransitionError(kind + " is not valid UTF-8 JSON") from exc
    if not isinstance(record, dict) or _canonical(record) != raw:
        raise ComputationalTransitionError(kind + " must use canonical JSON object bytes")
    return record


def encode_vli_temporal_operation(operation: str, arguments: Mapping[str, Any]) -> bytes:
    """Select a bounded original VL-I operation and caller-provided source sample."""
    if operation not in _VLI_OPS or not isinstance(arguments, Mapping):
        raise ComputationalTransitionError("VL-I operation or typed arguments are not admitted")
    raw = _canonical({
        "schema": VLI_TEMPORAL_SESSION_INPUT,
        "operation": operation,
        "arguments": dict(arguments),
    })
    if len(raw) > _MAX_INPUT:
        raise ComputationalTransitionError("VL-I operation input exceeds its byte limit")
    return raw


def _operation(raw: bytes) -> tuple[str, dict[str, Any]]:
    """Interpret only the declared VL-I application operation vocabulary."""
    record = _decode(raw, max_bytes=_MAX_INPUT, kind="VL-I input")
    if (set(record) != {"schema", "operation", "arguments"}
        or record["schema"] != VLI_TEMPORAL_SESSION_INPUT
        or record["operation"] not in _VLI_OPS
        or not isinstance(record["arguments"], dict)):
        raise ComputationalTransitionError("VL-I request fields or operation differ")
    required = {
        "temporal.ingest": {"sample"},
        "temporal.ingest_signed": {"packet"},
        "temporal.inquire": {"strategy"},
        "temporal.compile": {"epoch_index"},
        "temporal.navigate": {"time", "epoch_index", "allow_projection"},
    }[record["operation"]]
    if set(record["arguments"]) != required:
        raise ComputationalTransitionError("VL-I operation argument fields differ")
    return record["operation"], record["arguments"]


def vli_temporal_session_backend_fingerprint(host: LocalComputationalHost) -> str:
    """Bind native VL-I version, exact source content and immutable backend profile."""
    if not isinstance(host, LocalComputationalHost):
        raise TypeError("VL-I M3 backend requires a real M2 reference host")
    return hashlib.sha256(
        b"mailcpu.vli-temporal-m3-backend.v1\0"
        + bytes.fromhex(host.manifest.manifest_digest)
        + bytes.fromhex(host.profile.fingerprint)
    ).hexdigest()


def vli_temporal_session_contract(host: LocalComputationalHost) -> ComputationalTransitionContract:
    """Declare pure original-VL-I state transition through E-CPU's existing M3."""
    return ComputationalTransitionContract(
        transition_id=VLI_TEMPORAL_SESSION_TRANSITION,
        state_schema_id=OS_STATE_SCHEMA,
        input_schema_id=VLI_TEMPORAL_SESSION_INPUT,
        interpretation_fingerprint=VLI_TEMPORAL_SESSION_INTERPRETATION,
        backend_fingerprint=vli_temporal_session_backend_fingerprint(host),
        max_input_bytes=_MAX_INPUT,
        max_state_bytes=_MAX_STATE,
        deterministic=True,
        effect_mode="pure",
    )


def bootstrap_vli_temporal_state(
    environment: str, *, dimensions: int = 1, observer: str = "vli-time",
) -> bytes:
    """Boot HeadlessOS with the original VL-I Ground inside its portable native VFS."""
    from .headless import HeadlessOS
    machine = HeadlessOS()
    snapshot = create_vli_temporal_genesis(
        environment, dimensions=dimensions, observer=observer,
    )
    machine.install_source(VLI_STATE_PATH, _canonical(snapshot).decode("utf-8"))
    return serialize_headless_state(machine)


def read_vli_temporal_checkpoint(state_bytes: bytes) -> dict[str, Any]:
    """Project and source-verify VL-I's causally complete checkpoint from E-CPU OS."""
    machine = restore_headless_state(state_bytes)
    try:
        raw = machine.environment.kernel.fs.read_file(VLI_STATE_PATH)
    except Exception as exc:
        raise ComputationalTransitionError("native OS lacks its VL-I Ground") from exc
    snapshot = _decode(raw, max_bytes=_MAX_STATE, kind="VL-I Ground")
    if not {"head", "identity"} <= set(snapshot):
        raise ComputationalTransitionError("VL-I Ground lacks its causal identity")
    from vli.temporal_intelligence import verify_temporal_snapshot
    try:
        verify_temporal_snapshot(
            snapshot, expected_head=snapshot["head"],
            expected_identity=snapshot["identity"],
        )
    except (ValueError, KeyError, TypeError) as exc:
        raise ComputationalTransitionError("source-verification of VL-I Ground failed") from exc
    verify_signed_history(machine, snapshot)
    return snapshot


class VLITemporalSessionBackend:
    """M3-coordinated genuine living-VL-I interpreter with independent M2 verification."""

    def __init__(
        self,
        reference_host: LocalComputationalHost,
        execute_remote: Callable[[str, str, dict[str, Any], ComputationalTransitionContext], dict[str, Any]],
        *,
        active_host: str,
        allowed_remote_hosts: frozenset[str],
    ) -> None:
        """Bind assignment context, permitted host names and independent M2 execution."""
        if not isinstance(reference_host, LocalComputationalHost):
            raise TypeError("reference_host must be an admitted M2 computational host")
        if not callable(execute_remote):
            raise TypeError("remote VL-I interpreter executor must be callable")
        if (not isinstance(active_host, str) or _SAFE.fullmatch(active_host) is None
            or active_host not in allowed_remote_hosts):
            raise ComputationalTransitionError("active VL-I host must be explicitly admitted")
        if not reference_host.profile.deterministic or reference_host.profile.effect_mode != "pure":
            raise ComputationalTransitionError("VL-I pure M3 transition needs deterministic reference")
        self.reference_host = reference_host
        self.execute_remote = execute_remote
        self.active_host = active_host
        self.allowed_remote_hosts = allowed_remote_hosts
        self.backend_fingerprint = vli_temporal_session_backend_fingerprint(reference_host)
        self.remote_calls = 0
        self.accepted_source_heads: list[str] = []

    def transition(
        self, state_bytes: bytes, input_bytes: bytes, context: ComputationalTransitionContext,
    ) -> bytes:
        """Commit only the independently reexecuted real VL-I successor Ground."""
        if not isinstance(context, ComputationalTransitionContext):
            raise ComputationalTransitionError("VL-I transition requires M3 session coordinates")
        if (context.backend_fingerprint != self.backend_fingerprint
            or context.execution_backend_fingerprint != self.backend_fingerprint
            or context.artifact_manifest_digest != self.reference_host.manifest.manifest_digest
            or context.state_schema_id != OS_STATE_SCHEMA
            or context.interpretation_fingerprint != VLI_TEMPORAL_SESSION_INTERPRETATION
            or context.transition_contract_digest != vli_temporal_session_contract(self.reference_host).digest
            or hashlib.sha256(state_bytes).hexdigest() != context.state_digest):
            raise ComputationalTransitionError("VL-I transition is not bound to current M3 head")
        if not isinstance(context.operation_id, str) or _SAFE.fullmatch(context.operation_id) is None:
            raise ComputationalTransitionError("VL-I operation ID must be VFS-safe")
        operation, args = _operation(input_bytes)
        previous = read_vli_temporal_checkpoint(state_bytes)
        machine = restore_headless_state(state_bytes)
        source_root = verify_signed_history(machine, previous)
        signed_packet = None
        packet_digest = None
        native_operation = operation
        if operation == "temporal.ingest_signed":
            if source_root is None:
                raise ComputationalTransitionError("signed VL-I sample lacks M3-pinned source trust root")
            signed_packet = args["packet"]
            sample, packet_digest = verify_next_signed_packet(machine, previous, signed_packet)
            host_args = {"snapshot": previous, "sample": sample}
            native_operation = "temporal.ingest"
        else:
            if operation == "temporal.ingest" and source_root is not None:
                raise ComputationalTransitionError("unsigned VL-I observation refused by signed-source policy")
            host_args = {"snapshot": previous, **args}
        if native_operation == "temporal.ingest":
            host_args["host"] = self.active_host
        request = ComputationalHostRequest(
            request_id=context.operation_id,
            artifact_manifest_digest=self.reference_host.manifest.manifest_digest,
            operation=native_operation,
            input_value=host_args,
            workload_id=context.session_id,
            logical_time=context.logical_time,
        )

        self.remote_calls += 1
        result = self.execute_remote(native_operation, context.operation_id, host_args, context)
        if not isinstance(result, dict) or set(result) != {
            "context_binding_digest", "receipt", "output",
        } or result["context_binding_digest"] != context.binding_digest:
            raise ComputationalTransitionError("remote VL-I result lacks valid M3 context evidence")
        try:
            receipt = ComputationalHostReceipt.from_dict(result["receipt"])
        except (TypeError, KeyError, ValueError) as exc:
            raise ComputationalTransitionError("remote VL-I M2 receipt invalid") from exc
        if (receipt.host_id not in self.allowed_remote_hosts
            or receipt.host_id != self.active_host
            or receipt.artifact_manifest_digest != self.reference_host.manifest.manifest_digest
            or receipt.backend_fingerprint != self.reference_host.profile.fingerprint
            or receipt.request_id != context.operation_id
            or receipt.workload_id != context.session_id
            or receipt.logical_time != context.logical_time
            or receipt.input_digest != request.input_digest):
            raise ComputationalTransitionError("remote VL-I execution identity differs")
        raw_output = _canonical(result["output"])
        if (hashlib.sha256(raw_output).hexdigest() != receipt.output_digest
            or len(raw_output) != receipt.output_size_bytes):
            raise ComputationalTransitionError("remote VL-I semantic value differs from M2 receipt")
        reference = self.reference_host.execute(request)
        if reference.output != result["output"]:
            raise ComputationalTransitionError("VL-I remote semantic result differs from source-executed reference")
        output = reference.output
        if (not isinstance(output, dict) or set(output) != {
            "schema", "operation", "snapshot", "result",
        } or output["schema"] != VLI_TEMPORAL_HOST_SCHEMA or output["operation"] != native_operation):
            raise ComputationalTransitionError("VL-I result is outside its host output schema")
        candidate = output["snapshot"]
        if (not isinstance(candidate, dict)
            or candidate.get("identity") != previous["identity"]):
            raise ComputationalTransitionError("VL-I Ground identity changed during session")
        # The original VL-I source independently reconstructs every historical event.
        from vli.temporal_intelligence import verify_temporal_snapshot
        try:
            verify_temporal_snapshot(
                candidate, expected_head=candidate["head"],
                expected_identity=previous["identity"],
            )
        except (KeyError, ValueError, TypeError) as exc:
            raise ComputationalTransitionError("VL-I proposed source chain cannot be reconstructed") from exc
        if native_operation == "temporal.ingest":
            if (len(candidate["events"]) != len(previous["events"]) + 1
                or candidate["events"][:-1] != previous["events"]
                or candidate["events"][-1]["host"] != self.active_host
                or candidate["events"][-1]["time"] != host_args["sample"]["time"]
                or candidate["events"][-1]["source_digest"] != host_args["sample"]["source_digest"]
                or candidate["head"] == previous["head"]):
                raise ComputationalTransitionError("VL-I proposed observation did not extend exact M3 source head")
        elif candidate != previous:
            raise ComputationalTransitionError("read-only VL-I intention changed the observed Ground")
        machine.install_source(VLI_STATE_PATH, _canonical(candidate).decode("utf-8"))
        if signed_packet is not None:
            write_signed_packet(machine, signed_packet)
            verify_signed_history(machine, candidate)
        machine.install_source(
            f"/vli/results/{context.logical_time:08d}_{context.operation_id}.json",
            _canonical({
                "schema": "mailcpu.vli-session-semantic-result.v1",
                "operation": operation, "time": context.logical_time,
                "previous_head": previous["head"], "head": candidate["head"],
                "identity": candidate["identity"], "result": output["result"],
                "source_authentication": (
                    {"kind": "VL-I-TIME005-ED25519", "packet_digest": packet_digest,
                     "publisher": source_root["source"]} if signed_packet is not None else None
                ),
            }).decode("utf-8"),
        )
        machine.run(max_ticks=machine.vm.scheduler.tick + 1)
        successor = serialize_headless_state(machine)
        self.accepted_source_heads.append(candidate["head"])
        return successor
