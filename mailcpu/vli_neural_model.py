"""SOI-009: admit and execute VL-I's actual generated neural conversation runtime.

This intentionally exercises the original complete *described* neural model,
not a fabricated substitute for pretrained Qwen inference. Both VL-I's entire
source package and its VLD neural compiler/DAG dependency are admitted as
exact-byte E-CPU M2 artifacts. A host reconstructs and replays the complete
original model checkpoint before executing one new neural forward transition.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import platform
from pathlib import Path
from typing import Any, Mapping

from .computational_host import (
    ComputationalArtifactManifest, ComputationalBackendError,
    ComputationalBackendProfile, ComputationalHostRequest,
    admit_computational_artifact_directory,
)

MODEL_HOST_SCHEMA = "mailcpu.vli-neural-model-host.v1"
MODEL_OPERATOR_ID = "vli.generated-model.respond"
MODEL_SOURCE_BOUND = 2 * 1024 * 1024
DEPENDENCY_SOURCE_BOUND = 8 * 1024 * 1024
MAX_MODEL_INPUT = 1 * 1024 * 1024
MAX_MODEL_OUTPUT = 2 * 1024 * 1024
OPERATIONS = frozenset({"model.respond"})


def _runtime():
    """Resolve the original optional VL-I and full VLD generation dependencies."""
    try:
        vli = importlib.import_module("vli")
        vld = importlib.import_module("vld")
        generated = importlib.import_module("vli.generative_response")
        importlib.import_module("vld.models.procedural")
        importlib.import_module("vld.navigation.dag")
        importlib.import_module("vld.signal.transitions")
    except ImportError as exc:
        raise ComputationalBackendError(
            "Install exact original VL-I and full Virtual-Layer-Dynamics model runtime"
        ) from exc
    return vli, vld, generated


def _root(module) -> Path:
    """Identify the installed source tree of a required original runtime."""
    filename = getattr(module, "__file__", None)
    if not isinstance(filename, str):
        raise ComputationalBackendError("native model runtime has no source location")
    path = Path(filename).parent
    if path.is_symlink() or not path.is_dir() or not (path / "__init__.py").is_file():
        raise ComputationalBackendError("native model runtime source path invalid")
    return path


def admit_vli_neural_runtime(*, object_store=None) -> tuple[
    ComputationalArtifactManifest, ComputationalArtifactManifest, Path,
]:
    """Content-admit the whole original VL-I and its full real VLD dependency."""
    vli, vld, _ = _runtime()
    root = _root(vli)
    manifest = admit_computational_artifact_directory(
        root, artifact_id="vli/original-neural@0.1",
        artifact_kind="python-neural-model-runtime",
        object_store=object_store, exclude_paths=("__pycache__",),
        max_total_size=MODEL_SOURCE_BOUND,
        metadata={"runtime": "original-vli", "version": str(vli.__version__),
                  "protocol": MODEL_HOST_SCHEMA},
    )
    dependency = admit_computational_artifact_directory(
        _root(vld), artifact_id="vld/original-neural-compiler@0.7",
        artifact_kind="python-neural-compiler-runtime",
        object_store=object_store, exclude_paths=("__pycache__",),
        max_total_size=DEPENDENCY_SOURCE_BOUND,
        metadata={"runtime": "original-vld", "version": str(vld.__version__),
                  "protocol": MODEL_HOST_SCHEMA},
    )
    return manifest, dependency, root


def vli_neural_profile(
    manifest: ComputationalArtifactManifest,
    dependency: ComputationalArtifactManifest,
) -> ComputationalBackendProfile:
    """Fingerprint source model interpreter AND actual VLD neural compiler bytes."""
    if (not isinstance(manifest, ComputationalArtifactManifest)
        or not isinstance(dependency, ComputationalArtifactManifest)
        or manifest.metadata.get("protocol") != MODEL_HOST_SCHEMA
        or dependency.metadata.get("protocol") != MODEL_HOST_SCHEMA):
        raise ComputationalBackendError("model or dependency source declaration differs")
    combined = hashlib.sha256(
        MODEL_HOST_SCHEMA.encode() + b"\0"
        + bytes.fromhex(manifest.manifest_digest)
        + bytes.fromhex(dependency.manifest_digest)
    ).hexdigest()
    return ComputationalBackendProfile(
        backend_id="vli.generated-neural",
        implementation_id="vli.coord002.original-finite-neural-runtime",
        implementation_digest=combined,
        device="cpu", substrates=("cpu",),
        runtime_versions={"python": platform.python_version(),
                          "vli": str(manifest.metadata["version"]),
                          "vld": str(dependency.metadata["version"])},
        configuration={"operation": "model.respond",
                       "vld_source_digest": dependency.manifest_digest,
                       "model_source_limit": MODEL_SOURCE_BOUND,
                       "dependency_source_limit": DEPENDENCY_SOURCE_BOUND,
                       "model_class": "complete-described-neural-fsm"},
        deterministic=True, effect_mode="pure",
        max_input_bytes=MAX_MODEL_INPUT,
        max_output_bytes=MAX_MODEL_OUTPUT,
    )


def _safe_json(value: Any) -> Any:
    """Detach the E-CPU immutable JSON request and refuse untyped runtime objects."""
    try:
        return json.loads(json.dumps(
            value, ensure_ascii=False, separators=(",", ":"),
            sort_keys=True, allow_nan=False,
        ))
    except (ValueError, TypeError) as exc:
        raise ComputationalBackendError("neural model request is not finite JSON") from exc


def _model_source(value: str) -> bytes:
    """Reconstruct exact model-descriptive bytes instead of a caller-claimed model."""
    if not isinstance(value, str) or not value or len(value) > 2 * 65536 or len(value) % 2:
        raise ComputationalBackendError("model description hex outside source admission")
    try:
        raw = bytes.fromhex(value)
    except ValueError as exc:
        raise ComputationalBackendError("model description contains invalid hex") from exc
    if value != raw.hex():
        raise ComputationalBackendError("description hex must be canonical lowercase")
    return raw


def original_model_genesis(source: bytes, *, observer: str) -> dict[str, Any]:
    """Generate and checkpoint an actual original VL-I neural conversation."""
    if not isinstance(source, bytes) or len(source) > 65536:
        raise ComputationalBackendError("source description must fit the finite model host")
    _, _, generated = _runtime()
    ground = generated.GeneratedModelGround(source)
    conversation = generated.GenerativeConversation(ground, observer=observer)
    return conversation.checkpoint()


class VLIGenerativeModelAdapter:
    """Host the original VL-I neural transition, response DAG and causal replay."""

    def __init__(self, dependency: ComputationalArtifactManifest) -> None:
        """Retain exact second-runtime identity independently of M2's primary manifest."""
        if not isinstance(dependency, ComputationalArtifactManifest):
            raise TypeError("dependency must be a VLD computational artifact")
        self.dependency = dependency
        self._generated = None
        self.executions = 0

    def load(
        self,
        manifest: ComputationalArtifactManifest,
        artifact_root: Path,
        profile: ComputationalBackendProfile,
    ) -> None:
        """Verify both actual runtime package source identities before execution."""
        if profile != vli_neural_profile(manifest, self.dependency):
            raise ComputationalBackendError("model runtime profile differs from admitted source")
        vli, vld, generated = _runtime()
        if _root(vli).resolve() != Path(artifact_root).resolve():
            raise ComputationalBackendError("VL-I imported module location differs")
        if str(vli.__version__) != manifest.metadata["version"]:
            raise ComputationalBackendError("VL-I source version differs")
        if str(vld.__version__) != self.dependency.metadata["version"]:
            raise ComputationalBackendError("VLD compiler source version differs")
        # Verify full actual dependency byte inventory, not a mutable import name.
        from .computational_host import verify_computational_artifact_directory
        if not verify_computational_artifact_directory(self.dependency, _root(vld)):
            raise ComputationalBackendError("actual neural compiler dependency bytes changed")
        self._generated = generated

    def execute(self, request: ComputationalHostRequest) -> dict[str, Any]:
        """Reconstruct original neural weights and causal session; execute one full turn."""
        if self._generated is None:
            raise ComputationalBackendError("model host has not been loaded")
        if request.operation not in OPERATIONS:
            raise ComputationalBackendError("unadmitted neural execution operation")
        payload = _safe_json(request.input_value)
        if not isinstance(payload, dict) or set(payload) != {
            "description_hex", "checkpoint", "prompt", "action", "views",
        }:
            raise ComputationalBackendError("neural model input fields differ")
        source = _model_source(payload["description_hex"])
        checkpoint = payload["checkpoint"]
        if not isinstance(checkpoint, dict):
            raise ComputationalBackendError("neural model session checkpoint missing")
        ground = self._generated.GeneratedModelGround(source)
        restored = self._generated.GenerativeConversation.restore(
            ground, checkpoint, expected_head=checkpoint["checkpoint_digest"],
        )
        views = payload["views"]
        if (not isinstance(views, list) or not 1 <= len(views) <= 5
            or len(set(views)) != len(views)
            or any(v not in self._generated.ALLOWED_VIEWS for v in views)):
            raise ComputationalBackendError("model output view selection unadmitted")
        outcome = restored.respond(
            payload["prompt"], payload["action"], views=tuple(views),
        )
        completed = restored.checkpoint()
        self.executions += 1
        return _safe_json({
            "schema": MODEL_HOST_SCHEMA,
            "model_source_sha256": hashlib.sha256(source).hexdigest(),
            "model_ground_digest": ground.manifest["ground_digest"],
            "generated_weights_digest": ground.weights_digest,
            "vld_runtime_manifest_digest": self.dependency.manifest_digest,
            "checkpoint": completed,
            "output": outcome,
        })

    def unload(self) -> None:
        """Release the original neural interpreter binding."""
        self._generated = None
