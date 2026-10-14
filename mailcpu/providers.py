"""Deterministic procedural file providers inspired by the GV VFS reference."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum
from typing import Any

from .vl_procedural_primitives import feistel_stream_byte


class ProviderKind(str, Enum):
    """Finite provider families available to procedural inodes."""

    ZERO = "zero"
    ENTROPY = "entropy"
    FEISTEL = "feistel"
    PROC_TEXT = "proc_text"


@dataclass(frozen=True)
class ProceduralProvider:
    """A bounded, read-only function from `(offset, count)` to deterministic bytes."""

    kind: ProviderKind
    size: int
    seed: int = 0
    text: str = ""
    tau: int = 0xB16B00B5CAFE

    def __post_init__(self) -> None:
        """Mathematics: enforce `0≤offset,count`, `size≥0`, and 64-bit procedural seed/salt domains."""

        if self.size < 0:
            raise ValueError("provider size must be non-negative")
        if not 0 <= self.seed < 2**64 or not 0 <= self.tau < 2**64:
            raise ValueError("provider seed and tau must be unsigned 64-bit values")

    def read(self, offset: int, count: int) -> bytes:
        """Mathematics: return bounded slice `P[offset : min(offset + count, size)]` from the provider function `P`."""

        if offset < 0 or count < 0:
            raise ValueError("offset and count must be non-negative")
        if offset >= self.size or count == 0:
            return b""
        length = min(count, self.size - offset)
        if self.kind is ProviderKind.ZERO:
            return bytes(length)
        if self.kind is ProviderKind.PROC_TEXT:
            return self.text.encode("utf-8")[offset : offset + length]
        if self.kind is ProviderKind.FEISTEL:
            return bytes(feistel_stream_byte(offset + index, self.tau, self.seed) for index in range(length))
        data = bytearray(length)
        domain = self.kind.value.encode("ascii")
        for index in range(length):
            position = offset + index
            block = position // 32
            lane = position % 32
            digest = hashlib.sha256(
                domain + self.seed.to_bytes(16, "little", signed=False) + block.to_bytes(8, "little")
            ).digest()
            data[index] = digest[lane]
        return bytes(data)

    def snapshot(self) -> dict[str, Any]:
        """Mathematics: serialize provider identity `P = (kind, size, seed, text)` without materializing its bytes."""

        return {
            "kind": self.kind.value,
            "size": self.size,
            "seed": self.seed,
            "text": self.text,
            "tau": self.tau,
        }


class ProviderRegistry:
    """Named provider map shared by procedural filesystem inodes."""

    def __init__(self) -> None:
        """Mathematics: initialize partial provider function `P : key ⇀ ProceduralProvider` as empty."""

        self._providers: dict[str, ProceduralProvider] = {}

    def register(self, key: str, provider: ProceduralProvider) -> None:
        """Mathematics: extend `P := P[key ↦ provider]` only when `key ∉ dom(P)`."""

        if not key or key in self._providers:
            raise ValueError(f"provider key unavailable: {key}")
        self._providers[key] = provider

    def get(self, key: str) -> ProceduralProvider:
        """Mathematics: perform partial lookup `P[key]`, failing on an unregistered provider."""

        try:
            return self._providers[key]
        except KeyError as exc:
            raise KeyError(f"unknown provider: {key}") from exc

    def snapshot(self) -> dict[str, dict[str, Any]]:
        """Mathematics: expose the finite provider graph `dom(P)` and its symbolic specifications."""

        return {key: provider.snapshot() for key, provider in sorted(self._providers.items())}

    @classmethod
    def from_snapshot(cls, payload: dict[str, dict[str, Any]]) -> "ProviderRegistry":
        """Mathematics: reconstruct provider function `P` from its finite symbolic graph and validate every domain entry."""

        registry = cls()
        for key, specification in sorted(payload.items()):
            registry.register(
                key,
                ProceduralProvider(
                    ProviderKind(specification["kind"]),
                    int(specification["size"]),
                    int(specification.get("seed", 0)),
                    str(specification.get("text", "")),
                    int(specification.get("tau", 0xB16B00B5CAFE)),
                ),
            )
        return registry
