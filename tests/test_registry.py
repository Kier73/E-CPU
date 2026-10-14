from __future__ import annotations

from pathlib import Path

import pytest

from mailcpu import ImageRegistry, VirtualEnvironment
from mailcpu.cli import demo_image
from mailcpu.registry import RegistryError


def test_content_addressed_registry_publish_fetch_list_install(tmp_path: Path) -> None:
    """Mathematics: verify `fetch(publish(I).digest) = I` and installation preserves image file bytes."""

    registry = ImageRegistry(tmp_path / "registry")
    image = demo_image()
    record = registry.publish(image)
    assert registry.publish(image) == record
    assert registry.fetch(record.digest).digest() == record.digest
    assert registry.list() == (record,)
    environment = VirtualEnvironment.bootstrap()
    registry.install(record.digest, environment)
    assert environment.kernel.fs.read_file("/opt/mailcpu/README").startswith(b"This file")


def test_registry_rejects_unknown_or_tampered_digest(tmp_path: Path) -> None:
    """Mathematics: registry admission requires `path = digest` and `SHA256(image) = digest`; failures stay visible."""

    registry = ImageRegistry(tmp_path / "registry")
    with pytest.raises(RegistryError, match="not found"):
        registry.fetch("0" * 64)
    record = registry.publish(demo_image())
    path = Path(record.path)
    path.write_text(path.read_text(encoding="utf-8").replace("hello-mailcpu", "tampered"), encoding="utf-8")
    with pytest.raises(RegistryError, match="digest mismatch"):
        registry.fetch(record.digest)
