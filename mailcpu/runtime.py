"""Atomic admission of linked ELF images into a verified execution backend."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence, Mapping

from .elf import (
    ElfError,
    ElfImage,
    ElfLoadResult,
    ElfStackLayout,
    ElfStartupState,
    materialize_startup_stack,
)
from .linker import DynamicLinkResult, DynamicLinker, LinkerError
from .memory import VirtualMemory, VirtualMemoryError


class ExecutionAdmissionError(RuntimeError):
    """A runtime image cannot be admitted to a verified execution backend."""


@dataclass(frozen=True)
class ElfExecutionCandidate:
    """The complete staged state presented to a backend validator."""

    name: str
    memory: VirtualMemory
    link: DynamicLinkResult
    load: ElfLoadResult
    startup: ElfStartupState
    stack: ElfStackLayout


@dataclass(frozen=True)
class ElfExecutionHandoff:
    """An accepted machine entry and startup stack bound to one backend identity."""

    name: str
    machine: str
    bits: int
    entry: int
    stack_pointer: int
    backend_id: str
    memory: VirtualMemory
    link: DynamicLinkResult
    startup: ElfStartupState
    stack: ElfStackLayout


class ElfExecutionBackend(Protocol):
    """Backend contract `validate(C)=∅` before an admitted handoff is published."""

    backend_id: str
    machine: str
    bits: int

    def validate(self, candidate: ElfExecutionCandidate) -> None:
        """Mathematics: reject candidate `C` unless the backend's execution invariants hold."""

        ...


class ExecutionBackendRegistry:
    """Finite, unambiguous relation from ELF identity `(machine,bits)` to validators."""

    def __init__(self, backends: Sequence[ElfExecutionBackend] = ()) -> None:
        """Mathematics: construct `B={(machine,bits)↦backend}` by registering every supplied backend."""

        self._by_key: dict[tuple[str, int], ElfExecutionBackend] = {}
        self._by_id: dict[str, ElfExecutionBackend] = {}
        for backend in backends:
            self.register(backend)

    def register(self, backend: ElfExecutionBackend) -> None:
        """Mathematics: extend `B` only when backend identity and key are both absent from their domains."""

        backend_id = str(getattr(backend, "backend_id", "")).strip()
        machine = str(getattr(backend, "machine", "")).strip()
        bits = getattr(backend, "bits", None)
        if not backend_id or not machine or bits not in {32, 64}:
            raise ExecutionAdmissionError("backend identity must include non-empty id, machine, and 32/64-bit width")
        if not callable(getattr(backend, "validate", None)):
            raise ExecutionAdmissionError("backend must provide a callable validate method")
        key = (machine, int(bits))
        if backend_id in self._by_id:
            raise ExecutionAdmissionError(f"duplicate execution backend id: {backend_id}")
        if key in self._by_key:
            raise ExecutionAdmissionError(f"duplicate execution backend identity: {machine}/{bits}")
        self._by_id[backend_id] = backend
        self._by_key[key] = backend

    def resolve(self, machine: str, bits: int) -> ElfExecutionBackend:
        """Mathematics: evaluate the partial relation `B[(machine,bits)]`, refusing keys outside its domain."""

        key = (str(machine), int(bits))
        try:
            return self._by_key[key]
        except KeyError as error:
            raise ExecutionAdmissionError(
                f"no verified execution backend for {key[0]}/{key[1]}"
            ) from error

    def admit(self, candidate: ElfExecutionCandidate) -> ElfExecutionBackend:
        """Mathematics: return `b∈B` only after `b.validate(candidate)=∅`; otherwise publish no admission."""

        backend = self.resolve(candidate.load.machine, candidate.load.bits)
        try:
            backend.validate(candidate)
        except ExecutionAdmissionError:
            raise
        except Exception as error:
            raise ExecutionAdmissionError(
                f"execution backend {backend.backend_id} rejected runtime handoff"
            ) from error
        return backend


class ElfRuntimeLoader:
    """Compose dynamic linking, startup-stack construction, and backend admission atomically."""

    def __init__(self, linker: DynamicLinker, backends: ExecutionBackendRegistry) -> None:
        """Mathematics: bind loader relations `L=linker` and `B=backends` without changing any memory."""

        self.linker = linker
        self.backends = backends

    def admit(
        self,
        image: ElfImage,
        memory: VirtualMemory,
        *,
        name: str = "main",
        base: int = 0,
        argv: Sequence[str] = (),
        environment: Mapping[str, str] | None = None,
        stack_top: int = 0x7FFF_FFFF_F000,
    ) -> ElfExecutionHandoff:
        """Mathematics: commit `M'=commit(validate(B,stack(link(clone(M)))))` only after every admission predicate succeeds."""

        staged = memory.clone()
        try:
            link = self.linker.link_runtime(image, staged, name=name, base=base)
            if link.startup is None:
                raise ExecutionAdmissionError("runtime linker produced no startup state")
            if link.main.load.machine != "x86_64" or link.main.load.bits != 64:
                raise ExecutionAdmissionError(
                    "the startup-stack ABI is currently defined for x86_64/64 only"
                )
            stack = materialize_startup_stack(
                staged,
                link.startup,
                argv=argv,
                environment=environment,
                stack_top=stack_top,
            )
            candidate = ElfExecutionCandidate(
                name=name,
                memory=staged,
                link=link,
                load=link.main.load,
                startup=link.startup,
                stack=stack,
            )
            _validate_candidate(candidate)
            backend = self.backends.admit(candidate)
        except ExecutionAdmissionError:
            raise
        except (ElfError, LinkerError, VirtualMemoryError, ValueError) as error:
            raise ExecutionAdmissionError(str(error)) from error
        memory.commit_from(staged)
        return ElfExecutionHandoff(
            name=name,
            machine=candidate.load.machine,
            bits=candidate.load.bits,
            entry=candidate.startup.initial_entry,
            stack_pointer=candidate.stack.stack_pointer,
            backend_id=backend.backend_id,
            memory=memory,
            link=candidate.link,
            startup=candidate.startup,
            stack=candidate.stack,
        )


def _validate_candidate(candidate: ElfExecutionCandidate) -> None:
    """Mathematics: enforce entry consistency and `stack_pointer∈[mapping_start,mapping_end)` before backend dispatch."""

    load = candidate.load
    startup = candidate.startup
    stack = candidate.stack
    if candidate.link.main.load != load:
        raise ExecutionAdmissionError("runtime candidate load differs from link result")
    if startup.main_entry != load.entry:
        raise ExecutionAdmissionError("startup main entry differs from linked ELF entry")
    if startup.interpreter is None:
        if candidate.link.interpreter is not None or startup.interpreter_base is not None:
            raise ExecutionAdmissionError("static runtime handoff contains interpreter state")
        if startup.initial_entry != startup.main_entry:
            raise ExecutionAdmissionError("static runtime handoff initial entry is not the main entry")
    else:
        interpreter = candidate.link.interpreter
        if interpreter is None or interpreter.name != startup.interpreter:
            raise ExecutionAdmissionError("interpreter startup identity differs from link result")
        if startup.interpreter_base != interpreter.base:
            raise ExecutionAdmissionError("interpreter startup base differs from link result")
        if startup.initial_entry != interpreter.load.entry:
            raise ExecutionAdmissionError("initial entry differs from interpreter entry")
    if stack.mapping_start % candidate.memory.page_size or stack.mapping_length <= 0:
        raise ExecutionAdmissionError("startup stack mapping geometry is invalid")
    mapping_end = stack.mapping_start + stack.mapping_length
    if stack.stack_pointer % 16 or not (stack.mapping_start <= stack.stack_pointer < mapping_end):
        raise ExecutionAdmissionError("startup stack pointer is not aligned and mapped")
    if not (stack.mapping_start <= stack.argv_address < mapping_end):
        raise ExecutionAdmissionError("argv vector is outside the startup stack mapping")
    if not (stack.mapping_start <= stack.envp_address < mapping_end):
        raise ExecutionAdmissionError("environment vector is outside the startup stack mapping")
    if not (stack.mapping_start <= stack.auxiliary_address < mapping_end):
        raise ExecutionAdmissionError("auxiliary vector is outside the startup stack mapping")

