from __future__ import annotations

import ast
import builtins
import inspect
from pathlib import Path

import pytest

import mailcpu
from mailcpu import vl_procedural_primitives


def _exports() -> dict[str, object]:
    """Mathematics: project `mailcpu.__all__` onto the map `name -> attribute` for every declared export."""

    return {name: getattr(mailcpu, name, None) for name in mailcpu.__all__}


def test_every_public_callable_carries_a_docstring() -> None:
    """Mathematics: every non-dunder function, method, and class defined in the package binds a docstring, so the undocumented-callable set is empty."""

    package = Path(mailcpu.__file__).resolve().parent
    undocumented: list[str] = []
    for module_path in sorted(package.glob("*.py")):
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            if node.name.startswith("__") and node.name.endswith("__"):
                continue
            if not ast.get_docstring(node):
                undocumented.append(f"{module_path.name}:{node.lineno}:{node.name}")
    assert undocumented == []


def test_all_is_duplicate_free() -> None:
    """Mathematics: `|dom(__all__)| = |set(__all__)|`, so no name is declared twice."""

    assert len(mailcpu.__all__) == len(set(mailcpu.__all__))


def test_every_declared_export_resolves() -> None:
    """Mathematics: for every `n ∈ __all__`, the attribute `n` is bound in the package namespace."""

    unresolved = [name for name, value in _exports().items() if value is None]
    assert unresolved == []


def test_every_public_name_is_declared() -> None:
    """Mathematics: the set of non-underscore names bound in the package namespace equals `dom(__all__)`."""

    public = {
        name
        for name, value in vars(mailcpu).items()
        if not name.startswith("_") and not inspect.ismodule(value)
    }
    assert public - set(mailcpu.__all__) == set()


def test_no_export_shadows_a_builtin() -> None:
    """Mathematics: `dom(__all__) ∩ dom(builtins) = ∅`, so `from mailcpu import *` cannot rebind a builtin."""

    shadowed = sorted(set(mailcpu.__all__) & set(dir(builtins)))
    assert shadowed == []


def test_vendored_primitive_is_not_exported_from_the_package_root() -> None:
    """Mathematics: the vendored address permutation lies outside `dom(__all__)`, so it cannot be reached by a wildcard import."""

    vendored = {
        "feistel_open",
        "feistel_seal",
        "feistel_stream_byte",
    }
    assert vendored & set(mailcpu.__all__) == set()
    assert not vendored & {
        name
        for name, value in vars(mailcpu).items()
        if not inspect.ismodule(value)
    }


def test_vendored_primitive_remains_importable_from_its_module() -> None:
    """Mathematics: the vendored primitive remains reachable by explicit submodule import."""

    assert callable(vl_procedural_primitives.feistel_seal)
    assert callable(vl_procedural_primitives.feistel_open)


def test_error_types_are_exported_so_callers_can_catch_them() -> None:
    """Mathematics: each frequently raised domain error is a member of `dom(__all__)`, so a caller can catch it without reaching into a submodule."""

    required = {"KernelError", "FsError", "VirtualMemoryError", "CheckpointError", "ClassifierError"}
    assert required <= set(mailcpu.__all__)


def test_memory_error_uses_a_non_shadowing_name() -> None:
    """Mathematics: the virtual-memory domain error is named `VirtualMemoryError`, which is distinct from the builtin `MemoryError`."""

    assert issubclass(mailcpu.VirtualMemoryError, Exception)
    assert not issubclass(mailcpu.VirtualMemoryError, builtins.MemoryError)


def test_signal_vocabulary_is_the_single_source_of_default_exit_codes() -> None:
    """Mathematics: `default_exit_code` is a property of the signal enum, so no subsystem carries a competing literal table."""

    assert mailcpu.Signal.TERM.default_exit_code == 143
    assert mailcpu.Signal.HUP.default_exit_code == 129
    assert mailcpu.Signal.CONT.is_fatal is False


@pytest.mark.parametrize("module_name", sorted(
    name for name, value in vars(mailcpu).items()
    if inspect.ismodule(value) and getattr(value, "__name__", "").startswith("mailcpu.")
))
def test_every_submodule_declares_its_responsibility(module_name: str) -> None:
    """Mathematics: every package submodule carries a module docstring stating its responsibility."""

    module = getattr(mailcpu, module_name)
    assert module.__doc__, f"{module_name} has no module docstring"
    assert len(module.__doc__.strip()) > 0
