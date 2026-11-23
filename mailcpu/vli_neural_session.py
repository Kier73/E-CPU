"""SOI-009: original complete VL-I generated neural conversation under E-CPU M3.

State includes exact described model bytes, original generated neural model
checkpoint, complete native HeadlessOS and committed response receipts. A new
observer-host replays real original neural turns from the M3 predecessor,
computes one new step, and may only publish through original M3 quorum CAS.
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
from .vli_neural_model import (
    MODEL_HOST_SCHEMA, original_model_genesis,
)

MODEL_SOURCE_PATH = "/vli/neural/source.json"
MODEL_CHECKPOINT_PATH = "/vli/neural/conversation.json"
MODEL_RESULT_ROOT = "/vli/neural/results"
MODEL_INPUT_SCHEMA = "mailcpu.vli-neural-model-request.v1"
MODEL_TRANSITION_ID = "vli.generated-neural.conversation-step.v1"
MODEL_INTERPRETATION_DIGEST = hashlib.sha256(
    b"mailcpu.original-VLI-full-neural-model-M3-v1"
).hexdigest()
_ALLOWED_VIEWS = frozenset(("text", "page", "code", "tokens", "tool_call"))
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")


def _canonical(value: Any) -> bytes:
    """Encode a self-contained finite model/session record."""
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ComputationalTransitionError("model record cannot be canonicalized") from exc


def _decode(raw: bytes, bound: int, label: str) -> dict:
    """Admit only exact canonical JSON and reject repeated fields."""
    if not isinstance(raw, bytes) or len(raw) > bound:
        raise ComputationalTransitionError(label + " exceeds byte admission")
    def unique(pairs):
        """Refuse ambiguous duplicate-key state."""
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result
    try:
        obj = json.loads(raw.decode("utf-8"), object_pairs_hook=unique,
                         parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    except (ValueError, UnicodeError) as exc:
        raise ComputationalTransitionError(label + " is invalid JSON") from exc
    if not isinstance(obj, dict) or _canonical(obj) != raw:
        raise ComputationalTransitionError(label + " is not an exact canonical JSON object")
    return obj


def encode_vli_model_turn(prompt: str, action: str,
                          views: tuple[str, ...] = ("text", "page", "code", "tokens")) -> bytes:
    """Encode one authorized model intention without accepting new Python code."""
    if (not isinstance(prompt, str) or not 0 < len(prompt.encode("utf-8")) <= 8192
        or not isinstance(action, str) or not 1 <= len(action) <= 80
        or not isinstance(views, tuple) or not 1 <= len(views) <= 5
        or len(set(views)) != len(views)
        or not set(views) <= _ALLOWED_VIEWS):
        raise ComputationalTransitionError("model prompt, action or output views differ")
    result = _canonical({"schema": MODEL_INPUT_SCHEMA, "prompt": prompt,
                         "action": action, "views": list(views)})
    if len(result) > 8192 + 512:
        raise ComputationalTransitionError("model intention exceeds finite input")
    return result


def _turn(raw: bytes) -> dict:
    """Validate the only semantic operation allowed by this M3 backend."""
    row = _decode(raw, 8192 + 512, "neural model input")
    if set(row) != {"schema", "prompt", "action", "views"} or row["schema"] != MODEL_INPUT_SCHEMA:
        raise ComputationalTransitionError("model intention schema differs")
    # Roundtrip through typed constructor to prevent permissive decode.
    encoded = encode_vli_model_turn(row["prompt"], row["action"], tuple(row["views"]))
    if raw != encoded:
        raise ComputationalTransitionError("model input not in typed operation domain")
    return row


def bootstrap_vli_neural_model(
    model_description: bytes, *, observer: str = "ecpu-vli-model",
    include_living_ground: bool = True,
) -> bytes:
    """Initialize original neural-model and optionally living temporal state in one OS."""
    if not isinstance(model_description, bytes) or not 0 < len(model_description) <= 65536:
        raise ComputationalTransitionError("model source bytes exceed the finite model admission")
    if include_living_ground:
        from .vli_temporal_session import bootstrap_vli_temporal_state
        machine = restore_headless_state(bootstrap_vli_temporal_state(
            "vli:model-execution-environment", observer="vli-model-observer",
        ))
    else:
        from .headless import HeadlessOS
        machine = HeadlessOS()
    checkpoint = original_model_genesis(model_description, observer=observer)
    machine.install_source(MODEL_SOURCE_PATH, model_description.decode("utf-8"))
    machine.install_source(MODEL_CHECKPOINT_PATH, _canonical(checkpoint).decode("utf-8"))
    return serialize_headless_state(machine)


def read_vli_model_checkpoint(state_bytes: bytes) -> tuple[bytes, dict]:
    """Reconstruct and replay entire original neural conversation from native OS VFS."""
    machine = restore_headless_state(state_bytes)
    try:
        source = machine.environment.kernel.fs.read_file(MODEL_SOURCE_PATH)
        checkpoint_bytes = machine.environment.kernel.fs.read_file(MODEL_CHECKPOINT_PATH)
    except Exception as exc:
        raise ComputationalTransitionError("OS missing current source model or causal checkpoint") from exc
    if not 0 < len(source) <= 65536:
        raise ComputationalTransitionError("model source is outside the admitted geometry")
    saved = _decode(checkpoint_bytes, 2_097_152, "original VL-I neural checkpoint")
    from vli.generative_response import GeneratedModelGround, GenerativeConversation
    try:
        model = GeneratedModelGround(source)
        restored = GenerativeConversation.restore(
            model, saved, expected_head=saved["checkpoint_digest"],
        )
        if restored.checkpoint() != saved:
            raise ValueError("replayed model source differs from accepted checkpoint")
    except (ValueError, KeyError, TypeError) as exc:
        raise ComputationalTransitionError("original neural model checkpoint cannot be reconstructed") from exc
    return source, saved


def vli_model_session_fingerprint(reference_host: LocalComputationalHost) -> str:
    """Identify native VL-I and VLD source/compiler in one M3 semantic backend."""
    if not isinstance(reference_host, LocalComputationalHost):
        raise TypeError("real neural reference host is required")
    return hashlib.sha256(
        b"mailcpu.vli-original-neural-M3-v1\0"
        + bytes.fromhex(reference_host.manifest.manifest_digest)
        + bytes.fromhex(reference_host.profile.fingerprint)
    ).hexdigest()


def vli_model_session_contract(reference_host: LocalComputationalHost) -> ComputationalTransitionContract:
    """Bind complete OS, original neural model interpretation and M3 source identity."""
    return ComputationalTransitionContract(
        transition_id=MODEL_TRANSITION_ID,
        state_schema_id=OS_STATE_SCHEMA,
        input_schema_id=MODEL_INPUT_SCHEMA,
        interpretation_fingerprint=MODEL_INTERPRETATION_DIGEST,
        backend_fingerprint=vli_model_session_fingerprint(reference_host),
        max_input_bytes=8192 + 512,
        max_state_bytes=4_194_304,
        deterministic=True, effect_mode="pure",
    )


class VLINeuralModelSessionBackend:
    """Verify real neural execution before publishing complete E-CPU OS model state."""

    def __init__(
        self,
        reference_host: LocalComputationalHost,
        execute_remote: Callable[[str, str, dict, ComputationalTransitionContext], dict],
        *,
        active_host: str,
        allowed_remote_hosts: frozenset[str],
    ) -> None:
        """Bind an exact M2 neural source, one allowed worker and M3 backend identity."""
        if not isinstance(reference_host, LocalComputationalHost) or not callable(execute_remote):
            raise TypeError("M3 original neural model requires a real M2 host and remote callable")
        if (not isinstance(active_host, str) or _ID.fullmatch(active_host) is None
            or active_host not in allowed_remote_hosts):
            raise ComputationalTransitionError("neural model worker is not an admitted host")
        if not reference_host.profile.deterministic or reference_host.profile.effect_mode != "pure":
            raise ComputationalTransitionError("neural continuation must be a pure model transition")
        self.reference_host = reference_host
        self.execute_remote = execute_remote
        self.active_host = active_host
        self.allowed_remote_hosts = allowed_remote_hosts
        self.backend_fingerprint = vli_model_session_fingerprint(reference_host)
        self.remote_calls = 0
        self.accepted_turn_heads: list[str] = []

    def transition(self, state_bytes: bytes, input_bytes: bytes,
                   context: ComputationalTransitionContext) -> bytes:
        """Replay source model, reexecute remote neural work and quorum-stage successor."""
        if not isinstance(context, ComputationalTransitionContext):
            raise ComputationalTransitionError("model transition requires exact M3 context")
        if (context.backend_fingerprint != self.backend_fingerprint
            or context.execution_backend_fingerprint != self.backend_fingerprint
            or context.state_schema_id != OS_STATE_SCHEMA
            or context.artifact_manifest_digest != self.reference_host.manifest.manifest_digest
            or context.interpretation_fingerprint != MODEL_INTERPRETATION_DIGEST
            or context.transition_contract_digest != vli_model_session_contract(self.reference_host).digest
            or hashlib.sha256(state_bytes).hexdigest() != context.state_digest):
            raise ComputationalTransitionError("neural model backend or state binding differs")
        if _ID.fullmatch(context.operation_id) is None:
            raise ComputationalTransitionError("model operation identity cannot be represented safely")
        command = _turn(input_bytes)
        source, previous = read_vli_model_checkpoint(state_bytes)
        original_turns = len(previous["events"])
        machine = restore_headless_state(state_bytes)
        model_input = {
            "description_hex": source.hex(),
            "checkpoint": previous,
            "prompt": command["prompt"],
            "action": command["action"],
            "views": command["views"],
        }
        request = ComputationalHostRequest(
            request_id=context.operation_id,
            artifact_manifest_digest=self.reference_host.manifest.manifest_digest,
            operation="model.respond",
            input_value=model_input,
            logical_time=context.logical_time,
            workload_id=context.session_id,
        )
        self.remote_calls += 1
        remote = self.execute_remote("model.respond", context.operation_id, model_input, context)
        if (not isinstance(remote, dict)
            or set(remote) != {"context_binding_digest", "receipt", "output"}
            or remote["context_binding_digest"] != context.binding_digest):
            raise ComputationalTransitionError("remote neural model result lacks M3 binding")
        try:
            receipt = ComputationalHostReceipt.from_dict(remote["receipt"])
        except (ValueError, TypeError, KeyError) as exc:
            raise ComputationalTransitionError("remote neural model M2 receipt invalid") from exc
        if (receipt.host_id != self.active_host
            or receipt.host_id not in self.allowed_remote_hosts
            or receipt.artifact_manifest_digest != self.reference_host.manifest.manifest_digest
            or receipt.backend_fingerprint != self.reference_host.profile.fingerprint
            or receipt.request_id != context.operation_id
            or receipt.workload_id != context.session_id
            or receipt.logical_time != context.logical_time
            or receipt.input_digest != request.input_digest):
            raise ComputationalTransitionError("remote model source/operation identity differs")
        raw_output = _canonical(remote["output"])
        if (receipt.output_digest != hashlib.sha256(raw_output).hexdigest()
            or receipt.output_size_bytes != len(raw_output)):
            raise ComputationalTransitionError("remote model output/receipt digest differs")
        # Deliberate independent execution of original VL-I neural forward:
        # it proves exact equivalence rather than promising an acceleration.
        authoritative = self.reference_host.execute(request)
        if authoritative.output != remote["output"]:
            raise ComputationalTransitionError("remote neural computation differs from independently executed model")
        output = authoritative.output
        if (not isinstance(output, dict)
            or set(output) != {
                "schema", "model_source_sha256", "model_ground_digest",
                "generated_weights_digest", "vld_runtime_manifest_digest",
                "checkpoint", "output",
            }
            or output["schema"] != MODEL_HOST_SCHEMA
            or output["model_source_sha256"] != hashlib.sha256(source).hexdigest()
            or output["vld_runtime_manifest_digest"] != self.reference_host.profile.configuration["vld_source_digest"]):
            raise ComputationalTransitionError("completed neural model source record invalid")
        updated = output["checkpoint"]
        turn_output = output["output"]
        if (not isinstance(updated, dict)
            or updated.get("model_ground_digest") != previous["model_ground_digest"]
            or updated.get("observer") != previous["observer"]
            or len(updated.get("events", ())) != original_turns + 1
            or updated["events"][:-1] != previous["events"]
            or updated["events"][-1]["previous"] != previous["head"]
            or updated["events"][-1]["neural_forward_steps"] != 1
            or updated["head"] != updated["events"][-1]["turn_digest"]
            or turn_output["turn"] != updated["events"][-1]
            or turn_output["response"]["step_receipt"]["generated_weights_digest"] != output["generated_weights_digest"]
            or turn_output["response"]["phase"] != "RENDERED"):
            raise ComputationalTransitionError("original neural model successor failed complete-turn semantics")
        # Do not commit host-specific M2 receipt; another host may reexecute
        # semantically identical model work with a different host identity.
        machine.install_source(MODEL_CHECKPOINT_PATH, _canonical(updated).decode("utf-8"))
        machine.install_source(
            f"{MODEL_RESULT_ROOT}/{context.logical_time:08d}_{context.operation_id}.json",
            _canonical({
                "schema": "mailcpu.vli-neural-inference-result.v1",
                "model_source_sha256": output["model_source_sha256"],
                "model_ground_digest": output["model_ground_digest"],
                "generated_weights_digest": output["generated_weights_digest"],
                "vld_runtime_manifest_digest": output["vld_runtime_manifest_digest"],
                "turn": turn_output["turn"], "response": turn_output["response"],
            }).decode("utf-8"),
        )
        machine.run(max_ticks=machine.vm.scheduler.tick + 1)
        candidate = serialize_headless_state(machine)
        self.accepted_turn_heads.append(updated["head"])
        return candidate
