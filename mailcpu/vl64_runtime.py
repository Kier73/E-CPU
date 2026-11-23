"""VL-64 64-KiB runtime as a content-admitted E-CPU observer-host service.

This is an M2 ComputationalBackendAdapter around the actual installed vld
package, not an emulation of its Python runtime by MailCPU instructions.
The *whole* compact vld source tree is admitted as an artifact; the service
exports a finite set of typed, pure operations through M2 / Virtual Layer.
Each E-CPU VM can independently own its scheduler, kernel, hypervisor, process
identity and locally bound VL-64 host with the existing capability protocol.
"""

from __future__ import annotations

import hashlib
import importlib
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

VL64_OPERATOR_ID = "vl64.core.run"
VL64_SOURCE_LIMIT = 65_536
VL64_PROTOCOL = "mailcpu.vl64-runtime-host.v1"
_SUPPORTED = frozenset({"affine.navigate", "intention.realize", "ground.cycle", "page.cow"})


def _installed_vld():
    """Load the optional actual VL-64 core without adding it to E-CPU requirements."""
    try:
        return importlib.import_module("vld")
    except ImportError as exc:
        raise ComputationalBackendError(
            "VL-64 is optional; install a pinned virtual-layer-dynamics-64 runtime"
        ) from exc


def _path_for(runtime: Any) -> Path:
    """Identify the full compact core directory containing the imported runtime."""
    location = getattr(runtime, "__file__", None)
    if not isinstance(location, str):
        raise ComputationalBackendError("VL-64 runtime has no regular source location")
    root = Path(location).parent
    if root.is_symlink() or not (root / "__init__.py").is_file():
        raise ComputationalBackendError("VL-64 source root must be a regular directory")
    return root


def admit_vl64_runtime(*, object_store=None) -> tuple[ComputationalArtifactManifest, Path]:
    """Admit the real installed 64-KiB source core via E-CPU's original M2 manifest."""
    vld = _installed_vld()
    root = _path_for(vld)
    manifest = admit_computational_artifact_directory(
        root,
        artifact_id="vl64/core@0.7",
        artifact_kind="python-runtime-source",
        object_store=object_store,
        exclude_paths=("__pycache__",),
        max_total_size=VL64_SOURCE_LIMIT,
        metadata={
            "runtime": "vld",
            "version": str(vld.__version__),
            "protocol": VL64_PROTOCOL,
        },
    )
    if any(not component.path.endswith(".py") for component in manifest.components):
        raise ComputationalBackendError("VL-64 core includes unexpected source artifact kinds")
    if not manifest.components or manifest.total_size_bytes > VL64_SOURCE_LIMIT:
        raise ComputationalBackendError("VL-64 source exceeds 64-KiB admission")
    return manifest, root


def vl64_backend_profile(manifest: ComputationalArtifactManifest) -> ComputationalBackendProfile:
    """Bind the exact vld artifact version, Python implementation and admission budgets."""
    if not isinstance(manifest, ComputationalArtifactManifest):
        raise TypeError("manifest must be a ComputationalArtifactManifest")
    if manifest.metadata.get("protocol") != VL64_PROTOCOL:
        raise ComputationalBackendError("VL-64 artifact protocol differs")
    implementation = hashlib.sha256(
        VL64_PROTOCOL.encode("ascii") + b"\0" + bytes.fromhex(manifest.manifest_digest)
    ).hexdigest()
    return ComputationalBackendProfile(
        backend_id="vl64.core",
        implementation_id="vl64.m2-native-python",
        implementation_digest=implementation,
        device="cpu",
        substrates=("cpu",),
        runtime_versions={
            "python": platform.python_version(),
            "vl64": str(manifest.metadata["version"]),
        },
        configuration={"ops": sorted(_SUPPORTED), "source_limit": VL64_SOURCE_LIMIT},
        max_input_bytes=4096,
        max_output_bytes=4096,
        deterministic=True,
        effect_mode="pure",
    )


def _fields(value: object, required: set[str]) -> dict[str, object]:
    """Admit only exact named JSON parameters, excluding extras and type coercion."""
    if not isinstance(value, Mapping) or set(value) != required:
        raise ComputationalBackendError("VL-64 operation argument fields differ")
    return dict(value)


def _integer(value: object, name: str, minimum: int, maximum: int) -> int:
    """Require a bounded arithmetic coordinate with no bool-to-int conversion."""
    if type(value) is not int or not minimum <= value <= maximum:
        raise ComputationalBackendError(f"{name} must be an integer in [{minimum},{maximum}]")
    return value


def _affine_args(raw: object) -> tuple[int, int, int, int, int]:
    """Validate the complete modular affine computation envelope."""
    value = _fields(raw, {"a", "b", "x0", "steps", "modulus"})
    modulus = _integer(value["modulus"], "modulus", 2, (1 << 31) - 1)
    a = _integer(value["a"], "a", 0, modulus - 1)
    b = _integer(value["b"], "b", 0, modulus - 1)
    x0 = _integer(value["x0"], "x0", 0, modulus - 1)
    steps = _integer(value["steps"], "steps", 0, 10**12)
    return a, b, x0, steps, modulus


class VL64BackendAdapter:
    """Trust-bound E-CPU host bridge to real VL-64 methods with no user-supplied code."""

    def __init__(self) -> None:
        """Create a lazy M2 adapter with isolated load and unload lifecycle."""
        self._runtime: Any | None = None
        self.executions = 0

    def load(
        self,
        manifest: ComputationalArtifactManifest,
        artifact_root: Path,
        profile: ComputationalBackendProfile,
    ) -> None:
        """Require imported vld bytes to be exactly those admitted by E-CPU M2."""
        if profile != vl64_backend_profile(manifest):
            raise ComputationalBackendError("VL-64 profile differs from admitted implementation")
        runtime = _installed_vld()
        if _path_for(runtime).resolve() != Path(artifact_root).resolve():
            raise ComputationalBackendError("loaded VL-64 module is not the admitted source tree")
        if str(runtime.__version__) != str(manifest.metadata["version"]):
            raise ComputationalBackendError("VL-64 runtime version differs from artifact")
        self._runtime = runtime

    def execute(self, request: ComputationalHostRequest) -> dict[str, object]:
        """Dispatch one finite VL-64 operation using its real implementation."""
        if self._runtime is None:
            raise ComputationalBackendError("VL-64 backend is not loaded")
        operation = request.operation
        if operation not in _SUPPORTED:
            raise ComputationalBackendError("VL-64 operation is not in the host admission catalogue")
        vld = self._runtime
        if operation == "affine.navigate":
            a, b, x0, steps, modulus = _affine_args(request.input_value)
            result = vld.affine_navigate(a, b, x0, steps, modulus)
            output = {"value": result, "modulus": modulus, "steps": steps}
        elif operation == "intention.realize":
            a, b, x0, steps, modulus = _affine_args(request.input_value)
            expr = vld.IntentExpr.iterate_affine("x", a, b, steps, modulus)
            specification = vld.IntentionSpec(
                intention_id=request.request_id,
                target_expr=expr,
                contract_kind="int_vector",
                lineage_id=request.workload_id,
            )
            compiler = vld.IntentionCompiler()
            plan = compiler.compile(specification)
            receipt = compiler.realize(plan, {"x": [x0]})
            if receipt["status"] != "ADMITTED":
                raise ComputationalBackendError("VL-64 compiler refused the intention")
            output = {
                "value": receipt["admitted_observation"][0],
                "selected_plan": receipt["plan"],
                "expression_digest": expr.expr_digest,
            }
        elif operation == "ground.cycle":
            fields = _fields(request.input_value, {"initial", "steps"})
            initial = _integer(fields["initial"], "initial", 0, 3)
            steps = _integer(fields["steps"], "steps", 0, 10**12)
            # Witnessed full 4-state cycle; all transitions actually supplied.
            ground = vld.ObservedGround({"counter": (0,)})
            training = tuple(
                (bytes((index, 10 + index)), bytes(((index + 1) % 4, 10 + index)))
                for index in range(4)
            )
            ground.fit(training)
            observed = ground.navigate(bytes((initial, 10 + initial)), steps, "counter")
            output = {
                "terminal_state": observed["terminal_state"],
                "skipped_steps": observed["skipped_steps"],
                "evaluated_steps": observed["evaluated_steps"],
                "steps": steps,
            }
        else:
            fields = _fields(request.input_value, {"payload_hex"})
            raw = fields["payload_hex"]
            if not isinstance(raw, str) or len(raw) > 1024 or len(raw) % 2:
                raise ComputationalBackendError("VL-64 page payload must be bounded hex bytes")
            try:
                data = bytes.fromhex(raw)
            except ValueError as exc:
                raise ComputationalBackendError("VL-64 page payload is invalid hex") from exc
            parent = vld.PageSpace()
            parent.write_page(0, 0, data)
            child = parent.fork()
            child.write_page(0, 0, data[::-1])
            parent_bytes = parent.read_page(0)
            child_bytes = child.read_page(0)
            output = {
                "parent_digest": hashlib.sha256(parent_bytes).hexdigest(),
                "child_digest": hashlib.sha256(child_bytes).hexdigest(),
                "parent_manifest": parent.commit_manifest()["digest"],
                "child_manifest": child.commit_manifest()["digest"],
                "isolated": parent_bytes[: len(data)] == data
                and child_bytes[: len(data)] == data[::-1],
            }
        self.executions += 1
        return {"schema": VL64_PROTOCOL, "operation": operation, "result": output}

    def unload(self) -> None:
        """Detach the VL-64 runtime after the E-CPU host lifecycle closes."""
        self._runtime = None
