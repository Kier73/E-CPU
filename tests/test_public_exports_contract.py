"""Audit exported symbols against their actual implementation module objects.

This is a structural surface test, not semantic proof of every exported API.
"""
from __future__ import annotations

import ast
import importlib
from pathlib import Path


def test_all_public_exports_bind_to_their_declaring_module():
    package = importlib.import_module("mailcpu")
    path = Path(package.__file__)
    source = ast.parse(path.read_text(encoding="utf8"))
    imported = {}
    for node in source.body:
        if not isinstance(node, ast.ImportFrom) or node.level != 1 or not node.module:
            continue
        for alias in node.names:
            published_name = alias.asname or alias.name
            imported.setdefault(published_name, (node.module, alias.name))
    names = package.__all__
    assert isinstance(names, list)
    assert len(names) == len(set(names)), "duplicate entries in __all__"
    assert set(names) == set(imported), (
        "export registry is not aligned with the module import surface: "
        f"missing={sorted(set(imported) - set(names))}, "
        f"undeclared={sorted(set(names) - set(imported))}"
    )
    for name in names:
        module_name, implementation_name = imported[name]
        implementation = importlib.import_module(f"mailcpu.{module_name}")
        assert hasattr(implementation, implementation_name), (
            f"implementation absent for {module_name}.{implementation_name}"
        )
        assert getattr(package, name) is getattr(implementation, implementation_name), (
            f"public symbol {name} does not resolve to {module_name}.{implementation_name}"
        )
