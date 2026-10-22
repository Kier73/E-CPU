"""Deterministic provider resolution and transactional dynamic ELF linking."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol

from .elf import ELF_PAGE_SIZE, DynamicLinkPlan, ElfError, ElfImage, ElfLoadResult, ElfStartupState
from .memory import VirtualMemory


class LinkerError(RuntimeError):
    """A dependency, base assignment, symbol map, or relocation transaction failed."""


class ElfDependencyProvider(Protocol):
    """Provider relation from a DT_NEEDED name to a validated `ElfImage`."""

    def resolve(self, name: str) -> ElfImage:
        """Mathematics: resolve `provider[name]=ElfImage` or raise `LinkerError` without fabricating a dependency."""

        ...


@dataclass(frozen=True)
class MappingElfProvider:
    """Immutable dependency provider backed by a name-to-image mapping."""

    images: Mapping[str, ElfImage]

    def resolve(self, name: str) -> ElfImage:
        """Mathematics: evaluate the finite partial map `I[name]`, refusing `name∉dom(I)`."""

        try:
            return self.images[name]
        except KeyError as error:
            raise LinkerError(f"missing ELF dependency provider: {name}") from error


@dataclass(frozen=True)
class LoadedElf:
    """One dependency graph node with its deterministic base and staged projection."""

    name: str
    image: ElfImage
    base: int
    load: ElfLoadResult


@dataclass(frozen=True)
class DynamicLinkResult:
    """The committed link map and immutable relocation plans for one link operation."""

    main: LoadedElf
    dependencies: tuple[LoadedElf, ...]
    plans: tuple[tuple[str, DynamicLinkPlan], ...]
    interpreter: LoadedElf | None = None
    startup: ElfStartupState | None = None


class DynamicLinker:
    """Provider-backed ELF linker with deterministic layout and clone-then-commit memory semantics."""

    def __init__(self, provider: ElfDependencyProvider | Mapping[str, ElfImage]) -> None:
        """Mathematics: bind linker dependency relation `D=name↦ElfImage` without changing any virtual memory."""

        self.provider = provider if hasattr(provider, "resolve") else MappingElfProvider(provider)

    def link(
        self,
        image: ElfImage,
        memory: VirtualMemory,
        *,
        name: str = "main",
        base: int = 0,
    ) -> DynamicLinkResult:
        """Mathematics: construct and validate `M'=apply(stage(resolve(graph(I))),plans)` on a clone, then atomically commit `M'` to `M`."""

        if not name:
            raise LinkerError("main ELF name must be non-empty")
        if base < 0 or base % ELF_PAGE_SIZE:
            raise LinkerError("main ELF base must be non-negative and page-aligned")
        try:
            graph = self._resolve_graph(image, name)
            loaded, plans, staged = self._stage_graph(graph, memory, base)
        except (ElfError, LinkerError, ValueError) as error:
            raise LinkerError(str(error)) from error
        startup = None if image.interpreter is not None else image.startup_state(loaded[0].load)
        memory.commit_from(staged)
        main = loaded[0]
        return DynamicLinkResult(main, tuple(loaded[1:]), plans, startup=startup)

    def link_runtime(
        self,
        image: ElfImage,
        memory: VirtualMemory,
        *,
        name: str = "main",
        base: int = 0,
    ) -> DynamicLinkResult:
        """Mathematics: resolve and commit one combined graph `G(main) ∪ G(interpreter)` and construct its typed startup handoff."""

        if image.interpreter is None:
            return self.link(image, memory, name=name, base=base)
        try:
            interpreter_image = self.provider.resolve(image.interpreter)
            main_graph = self._resolve_graph(image, name)
            interpreter_graph = self._resolve_graph(interpreter_image, image.interpreter)
            graph: list[tuple[str, ElfImage]] = list(main_graph)
            seen = {graph_name for graph_name, _image in graph}
            for graph_name, graph_image in interpreter_graph:
                if graph_name not in seen:
                    graph.append((graph_name, graph_image))
                    seen.add(graph_name)
            loaded, plans, staged = self._stage_graph(tuple(graph), memory, base)
            loaded_by_name = {item.name: item for item in loaded}
            main = loaded_by_name[name]
            interpreter = loaded_by_name[image.interpreter]
            dependencies = tuple(
                item for item in loaded if item.name not in {name, image.interpreter}
            )
            startup = image.startup_state(
                main.load,
                interpreter_entry=interpreter.load.entry,
                interpreter_base=interpreter.base,
            )
        except (ElfError, LinkerError, ValueError, KeyError) as error:
            raise LinkerError(str(error)) from error
        memory.commit_from(staged)
        return DynamicLinkResult(main, dependencies, plans, interpreter, startup)

    def _stage_graph(
        self,
        graph: tuple[tuple[str, ElfImage], ...],
        memory: VirtualMemory,
        base: int,
    ) -> tuple[tuple[LoadedElf, ...], tuple[tuple[str, DynamicLinkPlan], ...], VirtualMemory]:
        """Mathematics: evaluate `M' = apply(relocate(stage(assign(graph))))` on a clone, returning it before one caller-controlled commit."""

        loaded_images = self._assign_bases(graph, base)
        bindings = self._bindings(loaded_images)
        plans = tuple(
            (loaded_name, loaded_image.plan_relocations(loaded_base, bindings))
            for loaded_name, loaded_image, loaded_base in loaded_images
        )
        staged = memory.clone()
        loaded: list[LoadedElf] = []
        for loaded_name, loaded_image, loaded_base in loaded_images:
            load = loaded_image.load_into(staged, loaded_base)
            loaded.append(LoadedElf(loaded_name, loaded_image, loaded_base, load))
        for loaded_name, plan in plans:
            loaded_image = next(item.image for item in loaded if item.name == loaded_name)
            loaded_image.apply_relocations(staged, plan)
        return tuple(loaded), plans, staged

    def _resolve_graph(self, main: ElfImage, main_name: str) -> tuple[tuple[str, ElfImage], ...]:
        """Mathematics: depth-first fold `G=(main,DT_NEEDED...)` with visited-name deduplication and cycle termination."""

        result: list[tuple[str, ElfImage]] = [(main_name, main)]
        visited: set[str] = {main_name}

        def visit(owner: str, image: ElfImage) -> None:
            """Mathematics: append each `needed∉visited` once, then recurse on its dependency relation."""

            del owner
            if image.dynamic is None:
                return
            for dependency in image.dynamic.needed:
                if dependency in visited:
                    continue
                try:
                    resolved = self.provider.resolve(dependency)
                except Exception as error:
                    raise LinkerError(f"cannot resolve dependency {dependency}") from error
                if resolved.dynamic is not None and resolved.dynamic.soname not in {None, dependency}:
                    raise LinkerError(f"dependency soname mismatch: requested {dependency}, got {resolved.dynamic.soname}")
                visited.add(dependency)
                result.append((dependency, resolved))
                visit(dependency, resolved)

        visit(main_name, main)
        return tuple(result)

    @staticmethod
    def _assign_bases(
        graph: tuple[tuple[str, ElfImage], ...],
        main_base: int,
    ) -> tuple[tuple[str, ElfImage, int], ...]:
        """Mathematics: assign `b_0=main_base`, `b_{i+1}=align_up(max_end_i,P)` with `P=4096`."""

        assigned: list[tuple[str, ElfImage, int]] = []
        cursor = main_base
        for index, (name, image) in enumerate(graph):
            selected_base = main_base if index == 0 else _align_up(cursor, ELF_PAGE_SIZE)
            if image.elf_type == 2 and selected_base != 0:
                raise LinkerError(f"ET_EXEC dependency cannot be relocated: {name}")
            if image.elf_type == 2 and index == 0 and selected_base != 0:
                raise LinkerError("ET_EXEC main image requires base zero")
            assigned.append((name, image, selected_base))
            cursor = max(cursor, selected_base + _image_span(image))
        return tuple(assigned)

    @staticmethod
    def _bindings(loaded: tuple[tuple[str, ElfImage, int], ...]) -> dict[str, int]:
        """Mathematics: construct first-definition global map `B[name]=base+st_value` in deterministic graph order."""

        bindings: dict[str, int] = {}
        for _name, image, base in loaded:
            if image.dynamic is None:
                continue
            for symbol in image.dynamic.symbols:
                if symbol.name and symbol.defined and symbol.name not in bindings:
                    bindings[symbol.name] = base + symbol.value
        return bindings


def _image_span(image: ElfImage) -> int:
    """Mathematics: calculate `span(I)=align_up(max(v_i+m_i),P)` over all PT_LOAD segments."""

    return _align_up(max(segment.virtual_address + segment.memory_size for segment in image.segments), ELF_PAGE_SIZE)


def _align_up(value: int, alignment: int) -> int:
    """Mathematics: calculate least multiple `ceil(value/alignment)*alignment` for positive `alignment`."""

    return ((value + alignment - 1) // alignment) * alignment
