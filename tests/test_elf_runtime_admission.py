from __future__ import annotations

from dataclasses import replace

import pytest

from mailcpu import (
    ElfExecutionCandidate,
    ElfRuntimeLoader,
    ExecutionAdmissionError,
    ExecutionBackendRegistry,
    VirtualMemory,
)
from mailcpu.linker import DynamicLinker

from test_linker import _static_provider


class _RecordingBackend:
    """Test backend whose admission relation records one complete candidate."""

    backend_id = "test-x86-64"
    machine = "x86_64"
    bits = 64

    def __init__(self, reject: bool = False) -> None:
        """Mathematics: initialize validator state `R=∅` and rejection predicate `q` without touching VM state."""

        self.reject = reject
        self.candidates: list[ElfExecutionCandidate] = []

    def validate(self, candidate: ElfExecutionCandidate) -> None:
        """Mathematics: accept iff `q=false` and append exactly one candidate to `R` after validation."""

        if self.reject:
            raise ValueError("backend admission predicate failed")
        self.candidates.append(candidate)


def _runtime_image():
    """Mathematics: construct a static x86-64 image `I` with no unresolved provider relation."""

    return _static_provider()


def test_runtime_loader_commits_only_after_backend_admission() -> None:
    """Mathematics: `M'=commit(stack(link(clone(M))))` and returned entry/stack bind to the accepted backend."""

    backend = _RecordingBackend()
    loader = ElfRuntimeLoader(
        DynamicLinker({}),
        ExecutionBackendRegistry((backend,)),
    )
    memory = VirtualMemory()
    handoff = loader.admit(
        _runtime_image(),
        memory,
        name="app",
        base=0x400000,
        argv=("app", "argument"),
        environment={"MODE": "test"},
        stack_top=0x9000,
    )

    assert handoff.backend_id == "test-x86-64"
    assert handoff.machine == "x86_64"
    assert handoff.bits == 64
    assert handoff.entry == handoff.startup.main_entry
    assert handoff.stack_pointer == handoff.stack.stack_pointer
    assert handoff.memory is memory
    assert len(backend.candidates) == 1
    assert memory.read(handoff.stack_pointer, 8) == (2).to_bytes(8, "little")


def test_runtime_loader_missing_backend_preserves_memory() -> None:
    """Mathematics: `B[(machine,bits)]∉dom(B)` implies `M_after=M_before` after all staged work is discarded."""

    loader = ElfRuntimeLoader(DynamicLinker({}), ExecutionBackendRegistry())
    memory = VirtualMemory()
    memory.map(0, 4096)
    before = memory.snapshot()
    with pytest.raises(ExecutionAdmissionError, match="no verified execution backend"):
        loader.admit(_runtime_image(), memory, base=0x400000, stack_top=0x9000)
    assert memory.snapshot() == before


def test_runtime_loader_backend_rejection_preserves_memory() -> None:
    """Mathematics: `validate(C)≠∅` implies no commit, so `M_after=M_before` even after link and stack staging."""

    backend = _RecordingBackend(reject=True)
    loader = ElfRuntimeLoader(DynamicLinker({}), ExecutionBackendRegistry((backend,)))
    memory = VirtualMemory()
    before = memory.snapshot()
    with pytest.raises(ExecutionAdmissionError, match="rejected runtime handoff"):
        loader.admit(_runtime_image(), memory, base=0x400000, stack_top=0x9000)
    assert memory.snapshot() == before


def test_runtime_loader_link_failure_preserves_memory() -> None:
    """Mathematics: unresolved runtime provider `p∉dom(D)` prevents any candidate and preserves `M` exactly."""

    image = replace(_runtime_image(), interpreter="/lib/missing.so")
    loader = ElfRuntimeLoader(DynamicLinker({}), ExecutionBackendRegistry((_RecordingBackend(),)))
    memory = VirtualMemory()
    before = memory.snapshot()
    with pytest.raises(ExecutionAdmissionError, match="missing ELF dependency provider"):
        loader.admit(image, memory, base=0x400000, stack_top=0x9000)
    assert memory.snapshot() == before
