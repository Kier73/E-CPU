from __future__ import annotations

import pytest

from mailcpu.environment import VirtualEnvironment
from mailcpu.fs import FsError, VirtualFileSystem
from mailcpu.providers import ProceduralProvider, ProviderKind
from mailcpu.vl_procedural_primitives import feistel_stream_byte


def test_procedural_provider_is_bounded_deterministic_and_read_only() -> None:
    """Mathematics: verify `P(o,n)` is deterministic, bounded by `size`, and cannot be mutated as a blob."""

    filesystem = VirtualFileSystem()
    filesystem.mkdir("/data")
    filesystem.register_procedural_file(
        "/data/feistel-like",
        ProceduralProvider(ProviderKind.FEISTEL, size=128, seed=17),
    )
    first = filesystem.read_file("/data/feistel-like", 7, 32)
    second = filesystem.read_file("/data/feistel-like", 7, 32)
    assert first == second
    assert len(filesystem.read_file("/data/feistel-like", 120, 32)) == 8
    with pytest.raises(FsError, match="read-only"):
        filesystem.write_file("/data/feistel-like", b"x")


def test_boot_namespace_contains_procedural_devices() -> None:
    """Mathematics: verify `/dev/zero` is synthesized as `0^n` and entropy is repeatable for a fixed seed."""

    environment = VirtualEnvironment.bootstrap()
    assert environment.kernel.fs.read_file("/dev/zero", 0, 64) == bytes(64)
    entropy_a = environment.kernel.fs.read_file("/dev/entropy", 0, 64)
    entropy_b = environment.kernel.fs.read_file("/dev/entropy", 0, 64)
    assert entropy_a == entropy_b
    assert any(byte != 0 for byte in entropy_a)


def test_feistel_provider_is_connected_to_vendored_virtual_layer_primitive() -> None:
    """Mathematics: verify provider slice `P[o:n]` equals the connected Feistel stream byte function."""

    provider = ProceduralProvider(ProviderKind.FEISTEL, size=64, seed=17, tau=0xB16B00B5CAFE)
    assert provider.read(5, 20) == bytes(
        feistel_stream_byte(index, 0xB16B00B5CAFE, 17) for index in range(5, 25)
    )
