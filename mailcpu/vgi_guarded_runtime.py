"""Source-pinned VGI guarded-process Grounds as real E-CPU M2 host operations.

The foreign Python code is *locally installed and admitted*, never supplied by
workloads. E-CPU retains operator authority and M2 execution receipts; VGI
checks mathematical reduction and replays transition traces. Caller-provided
migration probes are not an attested source-state observation.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import platform
from pathlib import Path
from typing import Any, Mapping

from .computational_host import (
    ComputationalArtifactManifest,
    ComputationalBackendError,
    ComputationalBackendProfile,
    ComputationalHostRequest,
    admit_computational_artifact_directory,
)

VGI_GUARDED_OPERATOR_ID = "vgi.guarded.execute"
VGI_GUARDED_PROTOCOL = "mailcpu.vgi-guarded-m2.v1"
VGI_SOURCE_COMMIT = "39a169b21513ffaaee85e40826c706c07a47215b"
VGI_MODULE_PINS = {
    "symbolic_reduction.py": "c61ef3647c7fa9f1a4e06729bb7b1359cb5aa9036d33a8595b66994c659fb58a",
    "guarded_reduction.py": "410cbfa824a53502c5d268e181c12fdf6bd783086a9c5561cec62f373e9dd0cd",
}
SOURCE_LIMIT = 2_097_152
_SUPPORTED = frozenset({"guarded.advance", "guarded.migrate", "guarded.jump"})


def _runtime_modules():
    try:
        vgi = importlib.import_module("vgi")
        guarded = importlib.import_module("vgi.guarded_reduction")
        symbolic = importlib.import_module("vgi.symbolic_reduction")
    except ImportError as exc:
        raise ComputationalBackendError("install VGI from the pinned source revision") from exc
    location = getattr(vgi, "__file__", None)
    if not isinstance(location, str):
        raise ComputationalBackendError("VGI source path unavailable")
    root = Path(location).parent
    if root.is_symlink() or not root.is_dir():
        raise ComputationalBackendError("VGI package root is not a regular directory")
    for filename, digest in VGI_MODULE_PINS.items():
        path = root / filename
        if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ComputationalBackendError(f"VGI source pin failed for {filename}")
    for module, name in ((guarded, "guarded_reduction.py"), (symbolic, "symbolic_reduction.py")):
        if Path(module.__file__).resolve() != (root / name).resolve():
            raise ComputationalBackendError("VGI module is outside admitted source tree")
    return guarded, symbolic, root


def admit_vgi_guarded_runtime(*, object_store=None) -> tuple[ComputationalArtifactManifest, Path]:
    """Admit installed VGI Python source under the original E-CPU M2 mechanism."""
    _, _, root = _runtime_modules()
    manifest = admit_computational_artifact_directory(
        root, artifact_id="vgi/guarded@002c", artifact_kind="python-runtime-source",
        object_store=object_store, exclude_paths=("__pycache__",),
        max_total_size=SOURCE_LIMIT,
        metadata={"protocol": VGI_GUARDED_PROTOCOL, "source_commit": VGI_SOURCE_COMMIT,
                  "module_pins": VGI_MODULE_PINS},
    )
    if not manifest.components or any(not x.path.endswith(".py") for x in manifest.components):
        raise ComputationalBackendError("VGI artifact contains unsupported files")
    return manifest, root


def vgi_guarded_backend_profile(manifest: ComputationalArtifactManifest) -> ComputationalBackendProfile:
    if not isinstance(manifest, ComputationalArtifactManifest):
        raise TypeError("expected M2 artifact manifest")
    if (manifest.metadata.get("protocol") != VGI_GUARDED_PROTOCOL or
        manifest.metadata.get("source_commit") != VGI_SOURCE_COMMIT or
        dict(manifest.metadata.get("module_pins", {})) != VGI_MODULE_PINS):
        raise ComputationalBackendError("VGI artifact metadata does not match pinned source")
    impl = hashlib.sha256((VGI_GUARDED_PROTOCOL + "\0" + manifest.manifest_digest).encode()).hexdigest()
    return ComputationalBackendProfile(
        backend_id="vgi.guarded", implementation_id="vgi.guarded.m2.python",
        implementation_digest=impl, device="cpu", substrates=("cpu",),
        runtime_versions={"python": platform.python_version(), "vgi_commit": VGI_SOURCE_COMMIT},
        configuration={"operations": sorted(_SUPPORTED), "source_limit": SOURCE_LIMIT},
        max_input_bytes=1_048_576, max_output_bytes=2_097_152,
        deterministic=True, effect_mode="pure",
    )


def _record(value: Any, fields: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ComputationalBackendError(f"{label}: exact fields required")
    try:
        obj = json.loads(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise ComputationalBackendError(f"{label}: non-JSON input") from exc
    if type(obj) is not dict:
        raise ComputationalBackendError(f"{label}: object required")
    return obj


def _source(raw: Any, guarded: Any, symbolic: Any):
    data = _record(raw, {"schema", "modulus", "dimension", "actions", "observations", "observation_bias"}, "source")
    if data["schema"] != guarded.SCHEMA or type(data["actions"]) is not list:
        raise ComputationalBackendError("unsupported VGI Ground format")
    actions = []
    for entry in data["actions"]:
        entry = _record(entry, {"symbol", "guard", "equals", "on_true", "on_false"}, "guarded action")
        branches = []
        for label in ("on_true", "on_false"):
            branch = _record(entry[label], {"matrix", "offset"}, label)
            if type(branch["matrix"]) is not list or type(branch["offset"]) is not list:
                raise ComputationalBackendError("branch matrix and offset must be arrays")
            branches.append(symbolic.AffineAction(entry["symbol"],
                tuple(tuple(row) for row in branch["matrix"]), tuple(branch["offset"])))
        actions.append(guarded.GuardedAction(entry["symbol"], tuple(entry["guard"]),
                            entry["equals"], *branches))
    if type(data["observations"]) is not list or type(data["observation_bias"]) is not list:
        raise ComputationalBackendError("observation matrix must be an array")
    result = guarded.GuardedGround(data["modulus"], data["dimension"], tuple(actions),
        tuple(tuple(row) for row in data["observations"]), tuple(data["observation_bias"]))
    if result.to_dict() != data:
        raise ComputationalBackendError("source Ground is not canonical")
    return result


class VGIGuardedBackendAdapter:
    """Finite, source-admitted operations; never interpret caller-provided Python."""

    def __init__(self) -> None:
        self._guarded: Any | None = None
        self._symbolic: Any | None = None
        self.executions = 0

    def load(self, manifest: ComputationalArtifactManifest, artifact_root: Path,
             profile: ComputationalBackendProfile) -> None:
        if profile != vgi_guarded_backend_profile(manifest):
            raise ComputationalBackendError("VGI backend profile differs")
        guarded, symbolic, root = _runtime_modules()
        if root.resolve() != Path(artifact_root).resolve():
            raise ComputationalBackendError("loaded VGI is not the admitted source directory")
        self._guarded, self._symbolic = guarded, symbolic

    def execute(self, request: ComputationalHostRequest) -> dict[str, Any]:
        if self._guarded is None or self._symbolic is None:
            raise ComputationalBackendError("VGI backend not loaded")
        if request.operation not in _SUPPORTED:
            raise ComputationalBackendError("VGI operation outside admitted catalogue")
        g, s = self._guarded, self._symbolic
        operation = request.operation
        if operation == "guarded.advance":
            data = _record(request.input_value, {"source", "certificate", "initial", "inputs"}, "advance")
            ground = _source(data["source"], g, s)
            q = g.admit_guarded_reduction(ground, data["certificate"])
            if type(data["inputs"]) is not list or len(data["inputs"]) > 512:
                raise ComputationalBackendError("advance quantum must contain at most 512 inputs")
            record = g.run_guarded(q, tuple(data["initial"]), tuple(data["inputs"]))
            verified = g.verify_guarded_receipt(q, record)
            output = {"status": verified["status"], "source_sha256": q.source_sha256,
                      "certificate_sha256": q.certificate_sha256, "quotient_dimension": q.dimension,
                      "original_dimensions": q.source_dimension, "steps": verified["steps"],
                      "final": list(verified["final"]), "observation": list(q.observe(verified["final"])),
                      "execution_receipt": record}
        elif operation == "guarded.migrate":
            data = _record(request.input_value, {"old_source", "old_certificate", "new_source",
                "new_certificate", "previous_receipt", "probe_values"}, "migration")
            old = g.admit_guarded_reduction(_source(data["old_source"], g, s), data["old_certificate"])
            new = g.admit_guarded_reduction(_source(data["new_source"], g, s), data["new_certificate"])
            previous = g.verify_guarded_receipt(old, data["previous_receipt"])
            plan = g.plan_migration(old, new)
            result = g.apply_migration(old, new, previous["final"], tuple(data["probe_values"]), plan)
            output = {"status": "MATHEMATICALLY_VERIFIED", "from_certificate": old.certificate_sha256,
                      "to_certificate": new.certificate_sha256, "prior_receipt_sha256": previous["receipt_sha256"],
                      "old_dimension": old.dimension, "new_dimension": new.dimension,
                      "required_probes": plan.probe_count, "probe_rows": [list(row) for row in plan.probe_rows],
                      "final": list(result), "observation": list(new.observe(result)),
                      "probe_authority": "CALLER_SUPPLIED_NOT_ATTESTED"}
        else:
            data = _record(request.input_value, {"source", "certificate", "initial", "symbol", "steps"}, "jump")
            ground = _source(data["source"], g, s)
            q = g.admit_guarded_reduction(ground, data["certificate"])
            raw_steps = data["steps"]
            if (type(raw_steps) is not str or not raw_steps or len(raw_steps) > 1234 or
                (raw_steps != "0" and raw_steps.startswith("0")) or not raw_steps.isascii() or
                not raw_steps.isdecimal()):
                raise ComputationalBackendError("steps must be canonical decimal string")
            steps = int(raw_steps)
            state = q.jump_invariant(tuple(data["initial"]), data["symbol"], steps)
            output = {"status": "MATHEMATICALLY_VERIFIED", "source_sha256": q.source_sha256,
                      "certificate_sha256": q.certificate_sha256, "final": list(state),
                      "observation": list(q.observe(state)), "steps": raw_steps,
                      "jump_method": "guard_invariant_affine_exponentiation"}
        self.executions += 1
        return {"schema": VGI_GUARDED_PROTOCOL, "operation": operation, "result": output}

    def unload(self) -> None:
        self._guarded = self._symbolic = None
