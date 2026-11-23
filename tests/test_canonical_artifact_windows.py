"""Artifact-order regression: identical M2 source identity across Windows and POSIX.

Windows pathlib ordering can be case-folded while original E-CPU manifests
require exact POSIX-relative lexicographic strings. The runtime now sorts on
canonical artifact paths rather than host-dependent Path comparisons.
"""
from __future__ import annotations

from mailcpu.computational_host import (
    admit_computational_artifact_directory,
    verify_computational_artifact_directory,
)


def test_original_model_source_artifact_inventory_is_cross_platform_canonical(tmp_path):
    """Mixed-case nested paths must have one exact source digest on every OS."""
    source = tmp_path / "model-runtime"
    (source / "engine").mkdir(parents=True)
    (source / "Model").mkdir()
    for path, raw in {
        "Zeta.py": b"zeta=0\n",
        "alpha.py": b"alpha=1\n",
        "beta.py": b"beta=2\n",
        "engine/Zeta.py": b"zeta='runtime'\n",
        "engine/alpha.py": b"alpha='runtime'\n",
        "Model/Delegate.py": b"delegate=1\n",
    }.items():
        (source / path).write_bytes(raw)
    expected_paths = [
        "Model/Delegate.py", "Zeta.py", "alpha.py",
        "beta.py", "engine/Zeta.py", "engine/alpha.py",
    ]
    first = admit_computational_artifact_directory(
        source,
        artifact_id="model/canonical@1",
        artifact_kind="python-runtime-source",
        max_total_size=1 << 20,
    )
    assert [component.path for component in first.components] == expected_paths
    assert verify_computational_artifact_directory(first, source)
    second = admit_computational_artifact_directory(
        source,
        artifact_id="model/canonical@1",
        artifact_kind="python-runtime-source",
        max_total_size=1 << 20,
    )
    assert first.canonical_bytes() == second.canonical_bytes()
    assert first.manifest_digest == second.manifest_digest
