from __future__ import annotations

import json

import pytest

from mailcpu import cli

_SOURCE = "set n 2\nset zero 0\nloop:\nadd n n zero\nhalt\n"


def test_declared_command_grammar_equals_registered_grammar() -> None:
    """Mathematics: the registered subparser domain equals the declared domain `_COMMANDS` exactly."""

    assert _registered_commands() == set(cli._COMMANDS)


@pytest.mark.parametrize("command", sorted(cli._COMMANDS))
def test_every_declared_command_is_reachable(command: str) -> None:
    """Mathematics: each `g ∈ dom(G)` resolves through argument parsing to a callable handler."""

    arguments = cli.build_parser().parse_args([command] + _operands(command))
    assert callable(arguments.handler)


def test_command_outside_the_declared_domain_is_refused() -> None:
    """Mathematics: a name outside `dom(G)` raises `SystemExit` rather than reaching any handler."""

    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["not-a-command"])


@pytest.mark.parametrize(
    ("command", "prerequisites"),
    [
        ("boot", ()),
        ("make-image", ()),
        ("run-image", ("make-image",)),
        ("demo", ()),
        ("run-source", ()),
        ("restore-run", ("run-source",)),
        ("os-demo", ()),
        ("memory-demo", ()),
        ("network-demo", ()),
        ("registry-publish", ("make-image",)),
        ("registry-list", ("make-image", "registry-publish")),
        ("lift", ()),
        ("bench", ()),
        ("substrate", ()),
        ("chronofold", ()),
    ],
)
def test_every_declared_command_returns_a_zero_exit_code(command, prerequisites, tmp_path, monkeypatch) -> None:
    """Mathematics: for each `g ∈ dom(G)`, a handler invoked with pre-satisfied operands returns exit code 0."""

    monkeypatch.chdir(tmp_path)
    _seed(tmp_path)
    for prerequisite in prerequisites:
        assert _invoke(prerequisite, tmp_path) == 0
    assert _invoke(command, tmp_path) == 0


@pytest.mark.parametrize("command", sorted(cli._COMMANDS))
def test_every_cli_report_declares_its_evidence_tier(command, tmp_path, monkeypatch, capsys) -> None:
    """Mathematics: every report `R` emitted by a declared command contains exactly one permitted tier `R.evidence_tier ∈ {E0,E1}`."""

    monkeypatch.chdir(tmp_path)
    _seed(tmp_path)
    for prerequisite in _prerequisites(command):
        assert _invoke(prerequisite, tmp_path) == 0
        capsys.readouterr()
    assert _invoke(command, tmp_path) == 0
    output = capsys.readouterr().out.strip()
    report = json.loads(output)
    assert isinstance(report, dict)
    assert report["evidence_tier"] == ("E1" if command == "network-demo" else "E0")


def _prerequisites(command: str) -> tuple[str, ...]:
    """Mathematics: return the minimal dependency path `P(command)` needed to materialize command operands."""

    return {
        "run-image": ("make-image",),
        "restore-run": ("run-source",),
        "registry-publish": ("make-image",),
        "registry-list": ("make-image", "registry-publish"),
    }.get(command, ())


def _invoke(command: str, root) -> int:
    """Mathematics: evaluate the unique handler bound to `g` under `dom(G)` and return its exit code."""

    arguments = cli.build_parser().parse_args([command] + _operands(command))
    return arguments.handler(arguments)


def _operands(command: str) -> list[str]:
    """Mathematics: supply the minimum operand sequence satisfying the arity declared by `g ∈ dom(G)`."""

    if command == "make-image":
        return ["image.mcp.json"]
    if command == "run-image":
        return ["image.mcp.json"]
    if command == "run-source":
        return ["source.mca", "--checkpoint-out", "state.mcpu.json", "--max-ticks", "50"]
    if command == "restore-run":
        return ["state.mcpu.json", "--max-ticks", "50"]
    if command == "registry-publish":
        return ["registry", "image.mcp.json"]
    if command == "registry-list":
        return ["registry"]
    if command == "lift":
        return ["1,2,3,4,5,6,7,8", "--horizon", "50"]
    if command == "bench":
        return ["--iterations", "5"]
    if command == "substrate":
        return ["--cycles", "3"]
    if command == "chronofold":
        return ["--ticks", "2"]
    return []


def _seed(root) -> None:
    """Mathematics: materialize every operand that `g ∈ dom(G)` reads but does not produce."""

    (root / "source.mca").write_text(_SOURCE, encoding="utf-8")


def _registered_commands() -> set[str]:
    """Mathematics: project the parser's subcommand domain as the value set of every registered choice group."""

    parser = cli.build_parser()
    return {
        name
        for action in parser._subparsers._group_actions
        for name in getattr(action, "choices", {})
    }
