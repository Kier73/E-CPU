"""Content-addressed local image registry for native MailCPU deployment."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .environment import VirtualEnvironment
from .image import ExecutableImage


class RegistryError(ValueError):
    """An image registry operation failed integrity or lookup validation."""


@dataclass(frozen=True)
class ImageRecord:
    """Stable registry projection of one digest-addressed executable image."""

    digest: str
    name: str
    path: str


class ImageRegistry:
    """A local E0 content-addressed image store with immutable digest paths."""

    def __init__(self, root: str | Path) -> None:
        """Mathematics: initialize registry namespace `R = {digest ↦ image}` rooted at a host directory."""

        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def publish(self, image: ExecutableImage) -> ImageRecord:
        """Mathematics: store image at `R[SHA256(image)]` and reject any existing path with a different identity."""

        digest = image.digest()
        destination = self.root / f"{digest}.mcp.json"
        if destination.exists():
            existing = ExecutableImage.load(destination)
            if existing.digest() != digest:
                raise RegistryError(f"registry collision at digest: {digest}")
        else:
            image.save(destination)
        return ImageRecord(digest, image.name, str(destination))

    def fetch(self, digest: str) -> ExecutableImage:
        """Mathematics: resolve partial map `R[digest]`, then require `SHA256(loaded_image) = digest`."""

        if not digest or any(character not in "0123456789abcdef" for character in digest) or len(digest) != 64:
            raise RegistryError("digest must be a 64-character lowercase SHA-256 value")
        path = self.root / f"{digest}.mcp.json"
        if not path.exists():
            raise RegistryError(f"image not found: {digest}")
        try:
            image = ExecutableImage.load(path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise RegistryError(str(exc)) from exc
        if image.digest() != digest:
            raise RegistryError(f"image digest mismatch: {digest}")
        return image

    def list(self) -> tuple[ImageRecord, ...]:
        """Mathematics: enumerate finite registry domain `sort(dom(R))` after validating each stored image."""

        records: list[ImageRecord] = []
        for path in sorted(self.root.glob("*.mcp.json")):
            digest = path.name.removesuffix(".mcp.json")
            image = self.fetch(digest)
            records.append(ImageRecord(digest, image.name, str(path)))
        return tuple(records)

    def install(self, digest: str, environment: VirtualEnvironment) -> ExecutableImage:
        """Mathematics: apply deployment transition `E.F := E.F ∪ files(fetch(R[digest]))` after digest verification."""

        image = self.fetch(digest)
        image.require_supported()
        image.install(environment)
        return image
