"""SOI-007: host the actual VL-I TIME-001/002 living interpreter through E-CPU M2.

The full installed vli source package is independently admitted as immutable
E-CPU computational bytes. Trusted bound operations reconstruct its original
TemporalIntelligenceGround and LiveTemporalObserver, not a reimplementation.

No arbitrary caller code, Python pickle or wall-clock uptime enters deterministic
M2 semantic outputs. The source_digest supplied by a sensor is provenance data:
authentication of that source remains an independent host obligation.
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

VLI_TEMPORAL_HOST_SCHEMA = "mailcpu.vli-temporal-host.v1"
VLI_TEMPORAL_ARTIFACT_ID = "vli/temporal@0.1"
VLI_TEMPORAL_OPERATOR_ID = "vli.temporal.execute"
VLI_MAX_SOURCE_BYTES = 2_097_152
VLI_M2_MAX_BYTES = 1_048_576
_OPERATIONS = ("temporal.ingest", "temporal.inquire", "temporal.compile", "temporal.navigate")


def _actual_vli() -> tuple[Any, Any, Any]:
    """Resolve the real optional VL-I source modules at this observer-host."""
    try:
        pkg = importlib.import_module("vli")
        temporal = importlib.import_module("vli.temporal_intelligence")
        living = importlib.import_module("vli.live_temporal_intelligence")
    except ImportError as exc:
        raise ComputationalBackendError(
            "Install a pinned virtual-layer-intelligence source runtime to use VL-I hosting"
        ) from exc
    return pkg, temporal, living


def _source_root(pkg: Any) -> Path:
    """Locate the exact installed source tree, not an advertised model identity."""
    file = getattr(pkg, "__file__", None)
    if not isinstance(file, str):
        raise ComputationalBackendError("VL-I runtime lacks a regular source location")
    root = Path(file).parent
    if root.is_symlink() or not root.is_dir() or not (root / "__init__.py").is_file():
        raise ComputationalBackendError("VL-I runtime source directory is invalid")
    return root


def admit_vli_temporal_runtime(*, object_store=None) -> tuple[ComputationalArtifactManifest, Path]:
    """Admit all original VL-I Python modules under M2's existing M1-capable manifest."""
    pkg, _, _ = _actual_vli()
    root = _source_root(pkg)
    manifest = admit_computational_artifact_directory(
        root,
        artifact_id=VLI_TEMPORAL_ARTIFACT_ID,
        artifact_kind="python-intelligence-runtime",
        object_store=object_store,
        metadata={
            "module": "vli.temporal_intelligence",
            "living_module": "vli.live_temporal_intelligence",
            "version": str(pkg.__version__),
            "protocol": VLI_TEMPORAL_HOST_SCHEMA,
        },
        exclude_paths=("__pycache__",),
        max_total_size=VLI_MAX_SOURCE_BYTES,
    )
    if any(not item.path.endswith(".py") for item in manifest.components):
        raise ComputationalBackendError("VL-I source admission includes unexpected artifacts")
    return manifest, root


def vli_temporal_backend_profile(manifest: ComputationalArtifactManifest) -> ComputationalBackendProfile:
    """Bind exact original source, runtime version and declared pure operation vocabulary."""
    if (not isinstance(manifest, ComputationalArtifactManifest)
        or manifest.metadata.get("protocol") != VLI_TEMPORAL_HOST_SCHEMA):
        raise ComputationalBackendError("VL-I runtime source protocol differs")
    fingerprint = hashlib.sha256(
        VLI_TEMPORAL_HOST_SCHEMA.encode("ascii") + b"\0"
        + bytes.fromhex(manifest.manifest_digest)
    ).hexdigest()
    return ComputationalBackendProfile(
        backend_id="vli.temporal",
        implementation_id="vli.time001-time002-native-python",
        implementation_digest=fingerprint,
        deterministic=True, effect_mode="pure",
        device="cpu", substrates=("cpu",),
        runtime_versions={"python": platform.python_version(), "vli": str(manifest.metadata["version"])},
        configuration={"operations": list(_OPERATIONS), "source_limit": VLI_MAX_SOURCE_BYTES},
        max_input_bytes=VLI_M2_MAX_BYTES,
        max_output_bytes=VLI_M2_MAX_BYTES,
    )


def _json(value: Any) -> Any:
    """Detach frozen M2 request mappings and keep only finite JSON values."""
    try:
        return json.loads(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False))
    except (ValueError, TypeError) as exc:
        raise ComputationalBackendError("VL-I input is outside the finite JSON domain") from exc


def _fields(value: Any, required: set[str]) -> dict[str, Any]:
    """Require exactly an admitted finite JSON object with no handler injection."""
    if not isinstance(value, Mapping) or set(value) != required:
        raise ComputationalBackendError("VL-I operation fields differ from declared contract")
    return _json(value)


def create_vli_temporal_genesis(
    environment: str, *, dimensions: int = 1, observer: str = "vli-time",
) -> dict[str, Any]:
    """Create the real original VL-I empty Ground and its source-verified checkpoint."""
    _, t, _ = _actual_vli()
    initial = t.TemporalIntelligenceGround(environment, dimensions=dimensions, observer=observer)
    return initial.checkpoint()


class VLITemporalBackendAdapter:
    """M2 adapter executing real VL-I interpretation and active observation logic."""

    def __init__(self) -> None:
        """Initialize a lazy host-local VL-I interpreter binding."""
        self._runtime: tuple[Any, Any] | None = None
        self.executions = 0

    def load(
        self,
        manifest: ComputationalArtifactManifest,
        artifact_root: Path,
        profile: ComputationalBackendProfile,
    ) -> None:
        """Verify the running interpreter is exactly the separately admitted source."""
        if profile != vli_temporal_backend_profile(manifest):
            raise ComputationalBackendError("VL-I M2 backend fingerprint differs")
        pkg, temporal, living = _actual_vli()
        if _source_root(pkg).resolve() != Path(artifact_root).resolve():
            raise ComputationalBackendError("VL-I imported code is not the admitted source location")
        if str(pkg.__version__) != str(manifest.metadata["version"]):
            raise ComputationalBackendError("VL-I imported package version differs")
        self._runtime = temporal, living

    def execute(self, request: ComputationalHostRequest) -> dict[str, Any]:
        """Run one exact original TIME-001/002 operation on a reconstructed Ground."""
        if self._runtime is None:
            raise ComputationalBackendError("VL-I adapter has not loaded")
        if request.operation not in _OPERATIONS:
            raise ComputationalBackendError("VL-I operation is not in trusted catalogue")
        temporal, living = self._runtime
        raw = _json(request.input_value)
        if not isinstance(raw, dict):
            raise ComputationalBackendError("VL-I host requires an object input")
        base = {"snapshot"}
        extra = {
            "temporal.ingest": {"sample", "host"},
            "temporal.inquire": {"strategy"},
            "temporal.compile": {"epoch_index"},
            "temporal.navigate": {"time", "epoch_index", "allow_projection"},
        }[request.operation]
        args = _fields(raw, base | extra)
        snapshot = args["snapshot"]
        if not isinstance(snapshot, dict):
            raise ComputationalBackendError("VL-I requires exact checkpoint bytes")
        # Original source reconstructs every causal event, rather than trusting
        # only the snapshot's outer checkpoint_digest.
        ground = temporal.TemporalIntelligenceGround.restore(
            snapshot, expected_head=snapshot["head"], expected_identity=snapshot["identity"]
        )
        if request.operation == "temporal.ingest":
            saved: list[dict[str, Any]] = []
            living_observer = living.LiveTemporalObserver(
                ground, host=args["host"], checkpoint_sink=saved.append,
            )
            raw_decision = living_observer.ingest(args["sample"])
            if len(saved) != 1 or saved[0] != ground.checkpoint():
                raise ComputationalBackendError("living observer sink did not receive its verified checkpoint")
            # Host-specific uptime and number of observations in this Python
            # process are telemetry, NOT source semantics and not checkpointed.
            result = {
                key: value for key, value in raw_decision.items()
                if key not in {"measured_process_uptime_ns", "samples_in_one_live_process"}
            }
        elif request.operation == "temporal.inquire":
            living_observer = living.LiveTemporalObserver(ground, host="intention-observer")
            result = living_observer.intention(strategy=args["strategy"])
        elif request.operation == "temporal.compile":
            result = ground.compile_epoch(args["epoch_index"], expected_head=ground.head)
            if not temporal.verify_temporal_processor(
                ground.checkpoint(), result,
                expected_head=ground.head, expected_identity=ground.identity,
            ):
                raise ComputationalBackendError("VL-I source-derived temporal processor is invalid")
        else:
            result = ground.navigate(
                args["time"], epoch_index=args["epoch_index"],
                expected_head=ground.head, allow_projection=args["allow_projection"],
            )
            if not temporal.verify_temporal_navigation(
                ground.checkpoint(), result,
                expected_head=ground.head, expected_identity=ground.identity,
            ):
                raise ComputationalBackendError("VL-I navigation is not independently reconstructed")
        self.executions += 1
        return {
            "schema": VLI_TEMPORAL_HOST_SCHEMA,
            "operation": request.operation,
            "snapshot": ground.checkpoint(),
            "result": result,
        }

    def unload(self) -> None:
        """Release the observer-local Python interpretation binding."""
        self._runtime = None
