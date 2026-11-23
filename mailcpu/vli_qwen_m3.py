"""SOI-011: M3 acceptance of original VL-I Qwen GDN/GQA M1 causal pages.

A worker can compute and put immutable causal pages, but only E-CPU M3
may publish the CURRENT original Qwen checkpoint/bundle. The original VL-I
QwenArchitectureCausalPrefix is always the sole numerical authority:
both a remote worker and an independent source-admitted controller execute
its actual step, checking exact output, causal head and all layer state.

The source factory is trusted, local, bound at admission; callers do not
submit code. M1 physical backing may live outside native HeadlessOS; the
versioned *pointer and original causal head* are inside the M3 OS state.
"""
from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path
import re
from typing import Any, Callable, Mapping

from .computational_host import (
    ComputationalArtifactManifest,
    admit_computational_artifact_directory,
)
from .computational_objects import ComputationalObjectStore
from .computational_transition import (
    ComputationalTransitionContext, ComputationalTransitionContract,
    ComputationalTransitionError,
)
from .stream_os_session import (
    OS_STATE_SCHEMA, restore_headless_state, serialize_headless_state,
)
from .vli_temporal_host import admit_vli_temporal_runtime
from .vli_qwen_pages import m1_qwen_causal_pages, check_original_qwen_checkpoint_pages

SCHEMA = "mailcpu.vli-qwen-causal-m3.v1"
INPUT_SCHEMA = "mailcpu.vli-qwen-token-input.v1"
TRANSITION = "vli.qwen-eight-layer-causal-step.v1"
INTERPRETATION = hashlib.sha256(b"mailcpu.original-qwen-eight-layer-M1-M3-v1").hexdigest()
PATH = "/vli/qwen/accepted-causal-state.json"
RESULT_ROOT = "/vli/qwen/accepted-results"
_SAFE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")


def _canonical(value: Any) -> bytes:
    """Make a bounded original-Qwen state descriptor reproducibly immutable."""
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ComputationalTransitionError("Qwen M3 state is not finite JSON") from exc


def _strict(raw: bytes, *, label: str, max_bytes: int = 2_097_152) -> dict:
    """Reject duplicate JSON keys, noncanonical encodings and oversized state."""
    if not isinstance(raw, bytes) or not 0 < len(raw) <= max_bytes:
        raise ComputationalTransitionError(label + " exceeds admitted bytes")
    def unique(pairs):
        """Refuse ambiguous duplicate-key state."""
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result
    try:
        value = json.loads(
            raw.decode("utf-8"), object_pairs_hook=unique,
            parse_constant=lambda item: (_ for _ in ()).throw(ValueError(item)),
        )
    except (UnicodeError, ValueError) as exc:
        raise ComputationalTransitionError(label + " is invalid JSON") from exc
    if not isinstance(value, dict) or _canonical(value) != raw:
        raise ComputationalTransitionError(label + " is not canonical source state")
    return value


def _digest(raw: bytes) -> str:
    """Bind immutable causal model bytes by SHA-256."""
    return hashlib.sha256(raw).hexdigest()


def admit_original_qwen_runtime_source() -> tuple[
    ComputationalArtifactManifest, ComputationalArtifactManifest,
]:
    """Admit all real VL-I modules and full original VL-64 model-fabric executor."""
    vli_manifest, _ = admit_vli_temporal_runtime()
    try:
        module = importlib.import_module("experiments.model_fabric.complete_native_layers")
    except ImportError as exc:
        raise ComputationalTransitionError("original VL-64 model-fabric runtime missing") from exc
    fabric_root = Path(module.__file__).parent
    fabric_manifest = admit_computational_artifact_directory(
        fabric_root,
        artifact_id="vl64/original-model-fabric@0.7",
        artifact_kind="python-qwen-causal-model-runtime",
        exclude_paths=("__pycache__",),
        max_total_size=8 * 1024 * 1024,
        metadata={"module": "experiments.model_fabric",
                  "protocol": SCHEMA},
    )
    return vli_manifest, fabric_manifest


def qwen_source_description(factory: Callable[[], Any]) -> dict[str, Any]:
    """Extract the original source-qualified model/plan identity at admission."""
    if not callable(factory):
        raise TypeError("Qwen model factory must be a trusted source callable")
    original = factory()
    plan = original.plan
    required = ("model", "revision", "index_ground_digest", "config_sha256", "plan_digest")
    if (not isinstance(plan, dict) or any(key not in plan for key in required)
        or type(original.stop_layer) is not int or original.stop_layer < 1
        or original.stop_layer > plan["layer_count"]):
        raise ComputationalTransitionError("original Qwen source plan is unadmitted")
    body = {key: plan[key] for key in required}
    for key in ("index_ground_digest", "config_sha256", "plan_digest"):
        if not isinstance(body[key], str) or _SHA.fullmatch(body[key]) is None:
            raise ComputationalTransitionError("original Qwen source digest malformed")
    return {
        "schema": "mailcpu.vli-qwen-source-identity.v1",
        **body,
        "stop_layer": original.stop_layer,
        "width": original.width,
        "max_positions": original.max_positions,
        "genesis": original.genesis,
    }


def qwen_backend_fingerprint(
    source: Mapping[str, Any],
    vli_manifest: ComputationalArtifactManifest,
    model_fabric_manifest: ComputationalArtifactManifest,
) -> str:
    """Bind entire VL-I and VL-64 model source trees plus exact original model plan."""
    if (not isinstance(source, Mapping) or not isinstance(vli_manifest, ComputationalArtifactManifest)
        or not isinstance(model_fabric_manifest, ComputationalArtifactManifest)):
        raise TypeError("Qwen backend must bind admitted source manifests and plan")
    return _digest(
        b"mailcpu.vli-qwen-causal-M3-backend.v1\0"
        + bytes.fromhex(vli_manifest.manifest_digest)
        + bytes.fromhex(model_fabric_manifest.manifest_digest)
        + _canonical(source)
    )


def qwen_m3_contract(backend_fingerprint: str) -> ComputationalTransitionContract:
    """Re-use existing pure M3 session CAS and its current-state interpretation."""
    if not isinstance(backend_fingerprint, str) or _SHA.fullmatch(backend_fingerprint) is None:
        raise ComputationalTransitionError("Qwen M3 backend digest invalid")
    return ComputationalTransitionContract(
        transition_id=TRANSITION,
        state_schema_id=OS_STATE_SCHEMA,
        input_schema_id=INPUT_SCHEMA,
        interpretation_fingerprint=INTERPRETATION,
        backend_fingerprint=backend_fingerprint,
        max_input_bytes=4096,
        max_state_bytes=4_194_304,
        deterministic=True,
        effect_mode="pure",
    )


def encode_qwen_causal_input(hidden: list[float], token_id: int) -> bytes:
    """Admit one exact finite hidden-state input and original token coordinate."""
    import math
    if (not isinstance(hidden, list) or not 1 <= len(hidden) <= 8192
        or any(type(value) not in (int, float) or not math.isfinite(value) for value in hidden)
        or type(token_id) is not int or not 0 <= token_id < 2**31):
        raise ComputationalTransitionError("Qwen token ID or numerical input is not admitted")
    raw = _canonical({"schema": INPUT_SCHEMA, "hidden": hidden, "token_id": token_id})
    if len(raw) > 4096:
        raise ComputationalTransitionError("Qwen native model input exceeds 4096 bytes")
    return raw


def _next_lineage(previous: str, command: dict) -> str:
    """Bind source token sequence digest to previous accepted M3 history."""
    if not isinstance(previous, str) or _SHA.fullmatch(previous) is None:
        raise ComputationalTransitionError("original causal sequence digest malformed")
    return _digest(b"mailcpu.qwen-causal-sequence.v1\0"
                   + bytes.fromhex(previous) + _canonical(command))


def bootstrap_qwen_causal_m3(
    original_factory: Callable[[], Any],
    vli_manifest: ComputationalArtifactManifest,
    fabric_manifest: ComputationalArtifactManifest,
    *,
    original_os_state: bytes | None = None,
) -> bytes:
    """Admit original Qwen source into native OS before first M3 session revision."""
    from .headless import HeadlessOS
    machine = HeadlessOS() if original_os_state is None else restore_headless_state(original_os_state)
    source = qwen_source_description(original_factory)
    descriptor = {
        "schema": SCHEMA, "source": source,
        "source_manifest_digest": vli_manifest.manifest_digest,
        "fabric_manifest_digest": fabric_manifest.manifest_digest,
        "position": 0, "causal_head": source["genesis"],
        "input_sequence_digest": "0" * 64,
        "checkpoint": None, "bundle": None,
    }
    machine.install_source(PATH, _canonical(descriptor).decode("utf-8"))
    return serialize_headless_state(machine)


def _state(state_bytes: bytes, backend, *, check_original_state: bool) -> dict:
    """Verify source/OS and every original causal page before allowing a new host."""
    machine = restore_headless_state(state_bytes)
    try:
        raw = machine.environment.kernel.fs.read_file(PATH)
    except Exception as exc:
        raise ComputationalTransitionError("original Qwen OS state is missing") from exc
    state = _strict(raw, label="original Qwen model state")
    expected = {
        "schema", "source", "source_manifest_digest",
        "fabric_manifest_digest", "position", "causal_head",
        "input_sequence_digest", "checkpoint", "bundle",
    }
    if (set(state) != expected
        or state["schema"] != SCHEMA
        or state["source"] != backend.source
        or state["source_manifest_digest"] != backend.vli_manifest.manifest_digest
        or state["fabric_manifest_digest"] != backend.fabric_manifest.manifest_digest
        or type(state["position"]) is not int
        or not 0 <= state["position"] < backend.source["max_positions"]
        or _SHA.fullmatch(state["causal_head"]) is None
        or _SHA.fullmatch(state["input_sequence_digest"]) is None):
        raise ComputationalTransitionError("original Qwen source state or model identity differs")
    if state["position"] == 0:
        if (state["causal_head"] != backend.source["genesis"]
            or state["checkpoint"] is not None or state["bundle"] is not None):
            raise ComputationalTransitionError("original Qwen genesis altered")
    elif check_original_state:
        restored, pages = _rehydrate(state, backend)
        if (restored.position != state["position"]
            or restored.head != state["causal_head"]
            or pages.verify_bundle() is not True):
            raise ComputationalTransitionError("original Qwen causal M1 state differs")
    return state


def _rehydrate(state: dict, backend):
    """Run original VL-I restore directly over E-CPU's immutable M1 page store."""
    from vli.qwen_architecture_navigator import QwenArchitectureCausalPrefix
    original = backend.original_factory()
    if state["position"] == 0:
        return original, m1_qwen_causal_pages(backend.object_store)
    cp, bundle = state["checkpoint"], state["bundle"]
    if (not isinstance(cp, dict) or not isinstance(bundle, dict)
        or cp.get("causal_head") != state["causal_head"]
        or cp.get("position") != state["position"]
        or cp.get("input_sequence_digest") != state["input_sequence_digest"]
        or cp.get("plan_digest") != backend.source["plan_digest"]):
        raise ComputationalTransitionError("original Qwen causal checkpoint differs from M3 source")
    try:
        pages = m1_qwen_causal_pages(backend.object_store, bundle=bundle)
        prefix = QwenArchitectureCausalPrefix.restore(
            original.nav, original.plan, pages, cp,
            expected_digest=cp["checkpoint_digest"],
            expected_input_sequence_digest=state["input_sequence_digest"],
            expected_plan_digest=backend.source["plan_digest"],
            max_positions=backend.source["max_positions"],
        )
        check_original_qwen_checkpoint_pages(cp, pages)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        raise ComputationalTransitionError("original Qwen causal pages cannot be reconstructed") from exc
    return prefix, pages


def evaluate_original_qwen_step(
    state: dict, command: dict, *, model_factory, object_store,
    source: dict, model_fabric_digest: str,
) -> dict:
    """Execute one real original eight-layer token step and checkpoint all its M1 pages."""
    import math
    if (not isinstance(command, dict)
        or set(command) != {"schema", "hidden", "token_id"}
        or command["schema"] != INPUT_SCHEMA
        or type(command["token_id"]) is not int
        or not 0 <= command["token_id"] < 2**31
        or not isinstance(command["hidden"], list)
        or len(command["hidden"]) != source["width"]
        or any(type(v) not in (int, float) or not math.isfinite(v) for v in command["hidden"])):
        raise ComputationalTransitionError("Qwen input is not the admitted model shape")
    if not isinstance(model_factory, type(lambda: None)) and not callable(model_factory):
        raise TypeError("original Qwen source factory missing")
    proxy = type("_TrustedModelSource", (), {
        "original_factory": staticmethod(model_factory),
        "object_store": object_store,
        "source": source,
    })()
    original, pages = _rehydrate(state, proxy)
    new_input_lineage = _next_lineage(state["input_sequence_digest"], command)
    result, receipt = original.step(command["hidden"], token_id=command["token_id"])
    checkpoint = original.checkpoint(pages, input_sequence_digest=new_input_lineage)
    bundle = pages.export_bundle()
    stats = check_original_qwen_checkpoint_pages(checkpoint, pages)
    if (original.position != state["position"] + 1
        or original.head != checkpoint["causal_head"]
        or len(receipt["layer_witnesses"]) != source["stop_layer"]
        or checkpoint["position"] != original.position):
        raise ComputationalTransitionError("original Qwen numerical state transition did not complete")
    next_state = {
        **state, "position": original.position,
        "causal_head": original.head,
        "input_sequence_digest": new_input_lineage,
        "checkpoint": checkpoint, "bundle": bundle,
    }
    return {
        "state": next_state,
        "output": result,
        "receipt": receipt,
        "causal_stats": stats,
        "source_fabric_manifest_digest": model_fabric_digest,
    }


class QwenCausalM3Backend:
    """Original Qwen numerical execution + E-CPU M1 bytes + M3 session publication."""

    def __init__(
        self,
        object_store: ComputationalObjectStore,
        original_factory: Callable[[], Any],
        vli_manifest: ComputationalArtifactManifest,
        fabric_manifest: ComputationalArtifactManifest,
        execute_remote: Callable[[dict, ComputationalTransitionContext], dict],
        *,
        active_host: str,
        allowed_remote_hosts: frozenset[str],
    ):
        """Bind original source, exact model profile and allowed remote worker identity."""
        if not isinstance(object_store, ComputationalObjectStore):
            raise TypeError("native Qwen M3 backend requires E-CPU ComputationalObjectStore")
        if (not callable(original_factory) or not callable(execute_remote)
            or not isinstance(active_host, str) or _SAFE.fullmatch(active_host) is None
            or active_host not in allowed_remote_hosts):
            raise ComputationalTransitionError("Qwen trusted model source or worker admission differs")
        self.original_factory = original_factory
        self.object_store = object_store
        self.vli_manifest = vli_manifest
        self.fabric_manifest = fabric_manifest
        self.source = qwen_source_description(original_factory)
        self.backend_fingerprint = qwen_backend_fingerprint(self.source, vli_manifest, fabric_manifest)
        self.execute_remote = execute_remote
        self.active_host = active_host
        self.allowed_remote_hosts = allowed_remote_hosts
        self.remote_calls = 0

    def transition(
        self, state_bytes: bytes, input_bytes: bytes, context: ComputationalTransitionContext,
    ) -> bytes:
        """Reconstruct source, compare real original math and quorum-stage full native OS."""
        if not isinstance(context, ComputationalTransitionContext):
            raise ComputationalTransitionError("Qwen M3 context is missing")
        if (context.backend_fingerprint != self.backend_fingerprint
            or context.execution_backend_fingerprint != self.backend_fingerprint
            or context.artifact_manifest_digest != self.vli_manifest.manifest_digest
            or context.state_schema_id != OS_STATE_SCHEMA
            or context.interpretation_fingerprint != INTERPRETATION
            or context.transition_contract_digest != qwen_m3_contract(self.backend_fingerprint).digest
            or _digest(state_bytes) != context.state_digest):
            raise ComputationalTransitionError("Qwen model M3 state is not source-qualified")
        if _SAFE.fullmatch(context.operation_id) is None:
            raise ComputationalTransitionError("Qwen M3 operation ID is not a safe native OS path")
        command = _strict(input_bytes, label="Qwen token input", max_bytes=4096)
        if input_bytes != encode_qwen_causal_input(command.get("hidden"), command.get("token_id")):
            raise ComputationalTransitionError("Qwen token input is not canonical and typed")
        state = _state(state_bytes, self, check_original_state=True)
        if state["position"] + 1 > self.source["max_positions"]:
            raise ComputationalTransitionError("Qwen model has exhausted its causal token budget")
        # Remote worker may write immutable pages, never the accepted M3 head.
        self.remote_calls += 1
        remote = self.execute_remote({
            "schema": "mailcpu.vli-qwen-remote-step.v1",
            "context_binding_digest": context.binding_digest,
            "active_host": self.active_host,
            "source": self.source,
            "vli_manifest_digest": self.vli_manifest.manifest_digest,
            "fabric_manifest_digest": self.fabric_manifest.manifest_digest,
            "state": state,
            "command": command,
        }, context)
        if (not isinstance(remote, dict)
            or set(remote) != {"context_binding_digest", "host_id", "candidate"}
            or remote["context_binding_digest"] != context.binding_digest
            or remote["host_id"] != self.active_host
            or not isinstance(remote["candidate"], dict)):
            raise ComputationalTransitionError("remote original Qwen result identity differs")
        # Independently execute all 8 original Qwen layers on the controller.
        reference = evaluate_original_qwen_step(
            state, command, model_factory=self.original_factory,
            object_store=self.object_store, source=self.source,
            model_fabric_digest=self.fabric_manifest.manifest_digest,
        )
        if _canonical(reference) != _canonical(remote["candidate"]):
            raise ComputationalTransitionError("remote original Qwen causal output differs from independent full-layer execution")
        # A rejected M3 predecessor may leave extra immutable M1 pages,
        # but cannot publish any of them as current causal session state.
        machine = restore_headless_state(state_bytes)
        machine.install_source(PATH, _canonical(reference["state"]).decode("utf-8"))
        machine.install_source(
            f"{RESULT_ROOT}/{context.logical_time:08d}_{context.operation_id}.json",
            _canonical({
                "schema": "mailcpu.vli-qwen-accepted-causal-step.v1",
                "causal_head": reference["state"]["causal_head"],
                "position": reference["state"]["position"],
                "output": reference["output"],
                "receipt": reference["receipt"],
                "causal_stats": reference["causal_stats"],
            }).decode("utf-8"),
        )
        machine.run(max_ticks=machine.vm.scheduler.tick + 1)
        return serialize_headless_state(machine)
