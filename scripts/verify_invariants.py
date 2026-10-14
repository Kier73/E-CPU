#!/usr/bin/env python3
"""Invariant registry resolver.

Every entry in `docs/INVARIANTS.md` names a module, a symbol, and a test that
would fail if the invariant were violated. This script proves that each named
target still exists, so an invariant cannot silently lose its enforcement point
when code is renamed or removed.

It also checks docstrings across the package: every public
function, method, and class carries a docstring.

Usage:
    python scripts/verify_invariants.py
    python scripts/verify_invariants.py --registry docs/INVARIANTS.md
    python scripts/verify_invariants.py --quiet
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REGISTRY = ROOT / "docs" / "INVARIANTS.md"
PACKAGE = ROOT / "mailcpu"

# `| `ID` | statement | establishes | enforced by | required by |`
ROW = re.compile(
    r"^\|\s*`(?P<id>[A-Z]-\d+)`\s*\|"
    r"\s*(?P<statement>[^|]*)\|"
    r"\s*`(?P<establishes>[^`]+)`\s*\|"
    r"\s*`(?P<enforced>[^`]+(?:`\s*,\s*`[^`]+)*)`\s*\|"
    r"\s*(?P<required>[^|]*)\|",
    re.MULTILINE,
)

TEST_FUNCTION = re.compile(r"^def (test_[A-Za-z0-9_]+)", re.MULTILINE)


@dataclass(frozen=True)
class Problem:
    """Mathematics: a single unresolved registry entry, carrying the rule it violates and its location in the registry."""

    line: int
    rule: str
    message: str


def _test_functions(path: Path) -> set[str]:
    """Mathematics: project a test module onto the set of its top-level `test_*` definitions."""

    if not path.exists():
        return set()
    text = path.read_text(encoding="utf-8")
    return set(TEST_FUNCTION.findall(text))


def _defines_symbol(module: Path, symbol: str) -> bool:
    """Mathematics: decide whether `symbol` is bound at module scope in `module`."""

    if not module.exists():
        return False
    tree = ast.parse(module.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name == symbol:
                return True
        elif isinstance(node, ast.Assign):
            if any(isinstance(target, ast.Name) and target.id == symbol for target in node.targets):
                return True
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == symbol:
                return True
    return False


def _registry_line_offset(text: str, index: int) -> int:
    """Mathematics: map a character offset onto its 1-indexed line number."""

    return text.count("\n", 0, index) + 1


def verify(registry: Path = DEFAULT_REGISTRY) -> list[Problem]:
    """Mathematics: verify returns the list `P` of registry entries whose named target no longer resolves."""

    if not registry.exists():
        return [Problem(1, "registry missing", f"no registry at {registry}")]

    text = registry.read_text(encoding="utf-8")
    problems: list[Problem] = []
    seen: dict[str, int] = {}

    for match in ROW.finditer(text):
        identifier = match.group("id")
        establishes = match.group("establishes").strip()
        enforced = match.group("enforced").strip()
        line = _registry_line_offset(text, match.start())

        if identifier in seen:
            problems.append(
                Problem(line, "duplicate identifier", f"`{identifier}` also used at line {seen[identifier]}")
            )
        seen[identifier] = line

        module_path = ROOT / establishes
        if establishes != "mailcpu/":
            if not module_path.exists():
                problems.append(Problem(line, "module missing", f"`{identifier}` names missing module `{establishes}`"))
            elif not _defines_symbol(module_path, _last_segment(establishes)):
                symbol = _expected_symbol(establishes)
                if symbol and not _defines_symbol(module_path, symbol):
                    problems.append(
                        Problem(line, "module not relevant", f"`{identifier}` names `{establishes}`, which defines no relevant symbol")
                    )

        for target in enforced.replace("`", "").split(","):
            target = target.strip()
            if not target:
                continue
            module_part, _, function_name = target.partition("::")
            path = ROOT / module_part
            if not path.exists():
                problems.append(Problem(line, "test module missing", f"`{identifier}` names missing test module `{module_part}`"))
                continue
            functions = _test_functions(path)
            if function_name:
                if function_name not in functions:
                    problems.append(
                        Problem(
                            line,
                            "test missing",
                            f"`{identifier}` names `{target}`, but `{module_part}` defines no `{function_name}`",
                        )
                    )
                continue
            if functions and not any(
                any(marker in function for marker in (identifier.split("-")[0], _slug(identifier)))
                for function in functions
            ) and not _module_covers_module(path, establishes):
                problems.append(
                    Problem(line, "test not identifiable", f"`{identifier}` names `{target}`, which contains no test identifying this invariant")
                )

    problems.extend(_missing_docstrings())
    return problems


def _last_segment(text: str) -> str:
    return text.rstrip("/").rsplit("/", 1)[-1]


def _expected_symbol(establishes: str) -> str | None:
    stem = Path(establishes).stem
    mapping = {
        "mailcpu": "__init__",
        "interpreter": "ReferenceInterpreter",
        "model": "OPCODE_ARITY",
        "_codec": "encode_canonical_value",
        "journal": "EventJournal",
        "checkpoint": "save_checkpoint",
        "trajectory": "TrajectoryWriter",
        "kernel": "VirtualKernel",
        "classifier": "ClassifierHypervisor",
        "signals": "Signal",
        "memory": "VirtualMemory",
        "headless": "HeadlessOS",
        "reliability": "ReliableChannel",
        "durable_transport": "DurableMailboxTransport",
        "owned_network": "OwnedNetworkFabric",
        "network": "HeadlessNetworkDevice",
        "image": "ExecutableImage",
        "elf": "parse_elf",
        "cli": "build_parser",
        "vl_procedural_primitives": "feistel_seal",
        "virtual_memory": "VirtualMemory",
    }
    return mapping.get(stem)


def _slug(identifier: str) -> str:
    return identifier.lower().replace("-", "_")


def _module_covers_module(test_path: Path, establishes: str) -> bool:
    """Mathematics: decide whether a test module names the invariant's establishing module."""

    if establishes == "mailcpu/":
        return "mailcpu" in test_path.name or "surface" in test_path.name
    stem = Path(establishes).stem
    return stem in test_path.name or stem.replace("_", "") in test_path.name


def _missing_docstrings() -> list[Problem]:
    """Mathematics: project the definition set of the package onto the subset of public callables lacking a docstring."""

    problems: list[Problem] = []
    for module in sorted(PACKAGE.glob("*.py")):
        if module.name == "__main__.py":
            continue
        tree = ast.parse(module.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            if node.name.startswith("__") and node.name.endswith("__"):
                continue
            if ast.get_docstring(node):
                continue
            problems.append(
                Problem(
                    node.lineno,
                    "missing docstring",
                    f"{module.relative_to(ROOT).as_posix()}:{node.lineno}: `{node.name}` has no docstring",
                )
            )
    return problems


def main(argv: list[str] | None = None) -> int:
    """Mathematics: `main` returns 0 iff the unresolved-entry set is empty."""

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--quiet", action="store_true")
    arguments = parser.parse_args(argv)

    problems = verify(arguments.registry)
    for problem in problems:
        print(f"{problem.rule}: {problem.message}")
    if not arguments.quiet:
        print(f"\n{len(problems)} unresolved invariant entry(ies) or docstring gap(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
