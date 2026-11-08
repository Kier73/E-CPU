from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from mailcpu import (
    Capability,
    HeadlessOS,
    HypervisorAction,
    HypervisorPolicy,
    LexicalDecisionModel,
    OperatorRegistry,
    SystemIdentity,
    SystemSeed,
    SystemSeedEnvelope,
    VirtualBudget,
    VirtualGroundRef,
    VirtualLayerRuntime,
    VirtualLayerWorkload,
    VirtualOperatorRef,
)
from mailcpu.computational_host import (
    ComputationalArtifactComponent,
    ComputationalArtifactError,
    ComputationalArtifactManifest,
    ComputationalBackendError,
    ComputationalBackendProfile,
    ComputationalHostReceipt,
    ComputationalHostRequest,
    LocalComputationalHost,
    admit_computational_artifact_directory,
    make_computational_host_operator,
    register_computational_host_operator,
    verify_computational_artifact_directory,
)
from mailcpu.computational_objects import ComputationalObjectStore


class MemoryPageBacking:
    """Fixed-size content-addressed page backing for artifact composition tests."""

    def __init__(self, page_size: int = 16) -> None:
        """Create one isolated page map with a declared fixed geometry."""
        self.page_size = page_size
        self.pages: dict[str, bytes] = {}

    def put_page(self, data: bytes) -> str:
        """Admit one page under its exact SHA-256 identity."""
        if not isinstance(data, bytes) or len(data) != self.page_size:
            raise ValueError("invalid page geometry")
        digest = hashlib.sha256(data).hexdigest()
        previous = self.pages.setdefault(digest, data)
        if previous != data:
            raise ValueError("content-address collision")
        return digest

    def get_page(self, digest: str) -> bytes:
        """Resolve a page by its content identity."""
        return self.pages[digest]


class EchoAdapter:
    """Small deterministic backend used to test the adapter contract without external runtimes."""

    def __init__(self, *, output: object | None = None) -> None:
        """Initialize adapter lifecycle observations and an optional fixed output."""
        self.load_count = 0
        self.unload_count = 0
        self.execute_count = 0
        self.output = output

    def load(self, manifest, artifact_root: Path, profile) -> None:
        """Record successful local artifact materialization."""
        assert artifact_root.is_dir()
        assert manifest.components
        assert profile.backend_id
        self.load_count += 1

    def execute(self, request: ComputationalHostRequest):
        """Return a deterministic operation projection."""
        self.execute_count += 1
        if self.output is not None:
            return self.output
        return {
            "operation": request.operation,
            "input": request.input_value,
            "logical_time": request.logical_time,
            "workload_id": request.workload_id,
        }

    def unload(self) -> None:
        """Record release of adapter-owned resources."""
        self.unload_count += 1


class FailingAdapter(EchoAdapter):
    """Adapter that fails only during the execution transition."""

    def execute(self, request: ComputationalHostRequest):
        """Raise a deterministic backend exception for error-path verification."""
        raise RuntimeError("backend failure")


def _artifact_directory(tmp_path: Path) -> Path:
    """Create a compact multi-component artifact fixture."""
    root = tmp_path / "artifact"
    (root / "parameters").mkdir(parents=True)
    (root / "config.json").write_text('{"width": 4, "layers": 2}', encoding="utf-8")
    (root / "parameters" / "weights.bin").write_bytes(bytes(range(47)))
    (root / "tokenizer.txt").write_text("alpha beta gamma", encoding="utf-8")
    return root


def _manifest(root: Path, *, object_store=None) -> ComputationalArtifactManifest:
    """Admit the deterministic fixture as a generic computational artifact."""
    return admit_computational_artifact_directory(
        root,
        artifact_id="test/runtime@1",
        artifact_kind="computational-runtime",
        object_store=object_store,
        metadata={"architecture": "test-ground", "revision": 1},
    )


def _profile(**overrides) -> ComputationalBackendProfile:
    """Construct a backend profile with explicit implementation and runtime identity."""
    values = {
        "backend_id": "test.backend",
        "implementation_id": "test.echo.v1",
        "implementation_digest": hashlib.sha256(b"test echo implementation").hexdigest(),
        "device": "cpu",
        "substrates": ("cpu",),
        "runtime_versions": {"python": "3.11"},
        "configuration": {"deterministic": True, "workers": 1},
        "max_input_bytes": 4096,
        "max_output_bytes": 8192,
    }
    values.update(overrides)
    return ComputationalBackendProfile(**values)


def _request(manifest: ComputationalArtifactManifest, **overrides) -> ComputationalHostRequest:
    """Construct one deterministic operation request pinned to the admitted artifact."""
    values = {
        "request_id": "request-001",
        "artifact_manifest_digest": manifest.manifest_digest,
        "operation": "echo",
        "input_value": {"message": "hello", "values": [1, 2, 3]},
        "logical_time": 7,
        "workload_id": "workload-001",
    }
    values.update(overrides)
    return ComputationalHostRequest(**values)


def test_composite_artifact_manifest_roundtrip_and_m1_storage_verification(tmp_path) -> None:
    """A multi-file artifact binds exact local bytes and portable M1 page descriptors."""
    root = _artifact_directory(tmp_path)
    pages = MemoryPageBacking()
    objects = ComputationalObjectStore(pages, chunk_size=16)

    manifest = _manifest(root, object_store=objects)
    restored = ComputationalArtifactManifest.from_dict(manifest.to_dict())

    assert restored == manifest
    assert restored.manifest_digest == manifest.manifest_digest
    assert len(restored.components) == 3
    assert all(component.storage_manifest is not None for component in restored.components)
    assert verify_computational_artifact_directory(
        restored,
        root,
        object_store=objects,
        verify_storage=True,
    )


def test_artifact_identity_binds_component_bytes_paths_and_metadata(tmp_path) -> None:
    """Changing any file content, component name, or metadata changes the composite identity."""
    root = _artifact_directory(tmp_path)
    original = _manifest(root)

    changed_root = _artifact_directory(tmp_path / "second")
    (changed_root / "config.json").write_text('{"width": 8, "layers": 2}', encoding="utf-8")
    changed_content = _manifest(changed_root)
    changed_metadata = admit_computational_artifact_directory(
        root,
        artifact_id="test/runtime@1",
        artifact_kind="computational-runtime",
        metadata={"architecture": "other-ground", "revision": 1},
    )

    assert original.manifest_digest != changed_content.manifest_digest
    assert original.manifest_digest != changed_metadata.manifest_digest


def test_artifact_verification_detects_tampering_and_unmanifested_files(tmp_path) -> None:
    """Verification refuses modified component bytes and an unexpected extra file by default."""
    root = _artifact_directory(tmp_path)
    manifest = _manifest(root)
    assert verify_computational_artifact_directory(manifest, root)

    (root / "config.json").write_text('{"width": 99}', encoding="utf-8")
    assert not verify_computational_artifact_directory(manifest, root)

    (root / "config.json").write_text('{"width": 4, "layers": 2}', encoding="utf-8")
    (root / "extra.bin").write_bytes(b"not in manifest")
    assert not verify_computational_artifact_directory(manifest, root)
    assert verify_computational_artifact_directory(manifest, root, strict_inventory=False)


def test_artifact_admission_rejects_symlinks_and_path_traversal(tmp_path) -> None:
    """Artifact roots cannot smuggle external files through symlinked or noncanonical component paths."""
    root = _artifact_directory(tmp_path)
    external = tmp_path / "outside.bin"
    external.write_bytes(b"outside")
    link = root / "outside-link.bin"
    try:
        link.symlink_to(external)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable on this platform")

    with pytest.raises(ComputationalArtifactError, match="symlinks"):
        _manifest(root)

    with pytest.raises(ComputationalArtifactError, match="traversal"):
        ComputationalArtifactComponent(
            path="../outside.bin",
            size_bytes=6,
            content_digest=hashlib.sha256(b"outside").hexdigest(),
        )


def test_artifact_admission_enforces_file_and_size_bounds(tmp_path) -> None:
    """Admission checks the declared file count and aggregate size ceilings."""
    root = _artifact_directory(tmp_path)
    with pytest.raises(ComputationalArtifactError, match="max_total_size"):
        admit_computational_artifact_directory(
            root,
            artifact_id="test/runtime@1",
            artifact_kind="computational-runtime",
            max_total_size=16,
        )
    with pytest.raises(ComputationalArtifactError, match="too many files"):
        admit_computational_artifact_directory(
            root,
            artifact_id="test/runtime@1",
            artifact_kind="computational-runtime",
            max_files=2,
        )


def test_manifest_metadata_is_detached_and_immutable(tmp_path) -> None:
    """Caller mutations cannot silently alter metadata already included in a manifest digest."""
    root = _artifact_directory(tmp_path)
    metadata = {"nested": {"items": [1, 2]}}
    manifest = admit_computational_artifact_directory(
        root,
        artifact_id="test/runtime@1",
        artifact_kind="computational-runtime",
        metadata=metadata,
    )
    digest = manifest.manifest_digest
    metadata["nested"]["items"].append(3)

    assert manifest.manifest_digest == digest
    with pytest.raises(TypeError):
        manifest.metadata["new"] = "value"


def test_backend_fingerprint_binds_implementation_runtime_and_configuration() -> None:
    """Backend implementation, runtime and configuration changes create distinct identities."""
    first = _profile()
    changed_runtime = _profile(runtime_versions={"python": "3.12"})
    changed_config = _profile(configuration={"deterministic": True, "workers": 2})
    changed_implementation = _profile(
        implementation_digest=hashlib.sha256(b"other implementation").hexdigest()
    )

    assert len(first.fingerprint) == 64
    assert len({
        first.fingerprint,
        changed_runtime.fingerprint,
        changed_config.fingerprint,
        changed_implementation.fingerprint,
    }) == 4


def test_local_host_lazily_loads_and_emits_deterministic_receipts(tmp_path) -> None:
    """Repeated equal requests produce equal receipt identity while timing remains an external observation."""
    root = _artifact_directory(tmp_path)
    manifest = _manifest(root)
    adapter = EchoAdapter()
    host = LocalComputationalHost(
        host_id="host-local-1",
        manifest=manifest,
        artifact_root=root,
        profile=_profile(),
        adapter=adapter,
    )
    request = _request(manifest)

    assert not host.is_loaded
    first = host.execute(request)
    second = host.execute(request)

    assert host.is_loaded
    assert adapter.load_count == 1
    assert adapter.execute_count == 2
    assert first.output == second.output
    assert first.receipt == second.receipt
    assert first.elapsed_ns >= 0
    assert first.receipt.status == "EXECUTED"
    assert first.receipt.to_dict()["receipt_digest"] == first.receipt.receipt_digest
    assert ComputationalHostReceipt.from_dict(first.receipt.to_dict()) == first.receipt
    host.unload()
    assert not host.is_loaded
    assert adapter.unload_count == 1


def test_host_receipt_rejects_tampering_and_execution_output_mismatch(tmp_path) -> None:
    """Receipt and output digests are independently checked instead of trusting caller fields."""
    root = _artifact_directory(tmp_path)
    manifest = _manifest(root)
    host = LocalComputationalHost(
        host_id="host-local-1",
        manifest=manifest,
        artifact_root=root,
        profile=_profile(),
        adapter=EchoAdapter(),
    )
    result = host.execute(_request(manifest))
    tampered = result.receipt.to_dict()
    tampered["output_digest"] = hashlib.sha256(b"forged").hexdigest()

    with pytest.raises(ComputationalBackendError, match="digest"):
        ComputationalHostReceipt.from_dict(tampered)

    with pytest.raises(ComputationalBackendError, match="does not match its receipt"):
        type(result)(
            output_json=json.dumps({"forged": True}, sort_keys=True, separators=(",", ":")),
            receipt=result.receipt,
            elapsed_ns=result.elapsed_ns,
        )


def test_host_rechecks_artifact_bytes_before_first_load(tmp_path) -> None:
    """A local artifact modified after admission is refused before backend initialization."""
    root = _artifact_directory(tmp_path)
    manifest = _manifest(root)
    adapter = EchoAdapter()
    host = LocalComputationalHost(
        host_id="host-local-1",
        manifest=manifest,
        artifact_root=root,
        profile=_profile(),
        adapter=adapter,
    )
    (root / "parameters" / "weights.bin").write_bytes(b"tampered")

    with pytest.raises(ComputationalArtifactError, match="differ"):
        host.execute(_request(manifest))
    assert adapter.load_count == 0
    assert not host.is_loaded


def test_host_enforces_artifact_input_and_output_bounds(tmp_path) -> None:
    """Request and result sizes are bounded by the selected backend profile."""
    root = _artifact_directory(tmp_path)
    manifest = _manifest(root)
    input_limited = LocalComputationalHost(
        host_id="host-input-limit",
        manifest=manifest,
        artifact_root=root,
        profile=_profile(max_input_bytes=12),
        adapter=EchoAdapter(),
    )
    with pytest.raises(ComputationalBackendError, match="max_input_bytes"):
        input_limited.execute(_request(manifest))

    output_limited = LocalComputationalHost(
        host_id="host-output-limit",
        manifest=manifest,
        artifact_root=root,
        profile=_profile(max_output_bytes=12),
        adapter=EchoAdapter(output={"result": "this is too large"}),
    )
    with pytest.raises(ComputationalBackendError, match="max_output_bytes"):
        output_limited.execute(_request(manifest))


def test_host_refuses_a_request_for_another_artifact(tmp_path) -> None:
    """A backend cannot reinterpret a request pinned to a different immutable artifact."""
    root = _artifact_directory(tmp_path)
    manifest = _manifest(root)
    host = LocalComputationalHost(
        host_id="host-local-1",
        manifest=manifest,
        artifact_root=root,
        profile=_profile(),
        adapter=EchoAdapter(),
    )
    with pytest.raises(ComputationalBackendError, match="differs"):
        host.execute(_request(
            manifest,
            artifact_manifest_digest=hashlib.sha256(b"other artifact").hexdigest(),
        ))


def test_backend_failure_does_not_produce_a_receipt(tmp_path) -> None:
    """A failed adapter transition raises and never manufactures successful output evidence."""
    root = _artifact_directory(tmp_path)
    manifest = _manifest(root)
    host = LocalComputationalHost(
        host_id="host-local-1",
        manifest=manifest,
        artifact_root=root,
        profile=_profile(),
        adapter=FailingAdapter(),
    )
    with pytest.raises(ComputationalBackendError, match="execution failed"):
        host.execute(_request(manifest))


def test_generic_host_operator_executes_through_hypervisor_virtual_layer(tmp_path) -> None:
    """The generic adapter runs as a typed node-local operator under receiver-local capability authority."""
    root = _artifact_directory(tmp_path)
    manifest = _manifest(root)
    host = LocalComputationalHost(
        host_id="host-local-1",
        manifest=manifest,
        artifact_root=root,
        profile=_profile(),
        adapter=EchoAdapter(),
    )
    registry = OperatorRegistry()
    spec = register_computational_host_operator(
        registry,
        host,
        operator_id="artifact.echo",
        version=1,
    )
    assert spec.operator_id == "artifact.echo"
    runtime = VirtualLayerRuntime(registry, "node-test", frozenset({"cpu"}))

    operating_system = HeadlessOS()
    operating_system.hypervisor.classifier = LexicalDecisionModel()
    operating_system.hypervisor.policy = HypervisorPolicy(embedding_review_confidence=1.0)
    identity = SystemIdentity("computational-host-test", 1)
    seed = SystemSeed.from_system(operating_system)
    envelope = SystemSeedEnvelope(identity, "executor", "computational-host-test", seed)
    admission = operating_system.seed_admission.admit(envelope)
    assert admission.accepted
    system_ground = VirtualGroundRef.from_envelope(envelope)

    workload = VirtualLayerWorkload(
        workload_id="host-workload-001",
        system=identity,
        ground=system_ground,
        intention={"goal": {"kind": "execute-typed-operation"}},
        operators=(VirtualOperatorRef("artifact.echo", 1, "cpu"),),
        input_value={"operation": "echo", "input": {"message": "through-virtual-layer"}},
        budget=VirtualBudget(
            max_energy=100_000,
            max_bytes=4096,
            max_virtual_ticks=1000,
        ),
        logical_time=7,
        eligible_nodes=("node-test",),
        max_hops=2,
    )
    pid = operating_system.environment.kernel.spawn(
        "computational-host-worker",
        capabilities=(Capability("/virtual-layer/operators", frozenset({"compute"})),),
        parent_pid=operating_system.environment.init_pid,
    )

    result = runtime.execute_operator(
        operating_system,
        pid,
        "origin",
        "computational-host",
        1,
        workload.logical_time,
        workload,
        "artifact.echo",
    )

    assert result.action is HypervisorAction.ALLOW
    assert result.executed is True
    assert result.effect["kind"] == "virtual_layer.operator_result"
    host_result = result.effect["result"]
    assert host_result["output"]["operation"] == "echo"
    assert host_result["receipt"]["status"] == "EXECUTED"
    assert host_result["receipt"]["artifact_manifest_digest"] == manifest.manifest_digest
