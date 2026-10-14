from __future__ import annotations

import json
from pathlib import Path

import pytest

from mailcpu.cli import demo_image, main
from mailcpu.environment import VirtualEnvironment
from mailcpu.bytecode import BytecodeError, BytecodeExecutable
from mailcpu.image import ExecutableImage
from mailcpu.image import ExecutionRegime, UnsupportedRegimeError
from mailcpu.model import Instruction, Op, Program


def test_executable_image_round_trip_and_install(tmp_path: Path) -> None:
    """Mathematics: verify `decode(encode(I)) = I` and image installation preserves file bytes."""

    image = demo_image()
    path = tmp_path / "demo.mcp.json"
    image.save(path)
    loaded = ExecutableImage.load(path)
    assert loaded.digest() == image.digest()
    environment = VirtualEnvironment.bootstrap()
    loaded.install(environment)
    assert environment.kernel.fs.read_file("/opt/mailcpu/README").startswith(b"This file")


def test_binary_bytecode_round_trip_is_deterministic_and_validated() -> None:
    """Mathematics: `decode(encode(P))=P`, `encode(P)` is deterministic, and malformed/trailing bytes are rejected."""

    program = Program(
        (
            Instruction(Op.SET, ("value", 7)),
            Instruction(Op.SYSCALL, ("pid", "getpid")),
            Instruction(Op.HALT),
        )
    )
    executable = BytecodeExecutable(program)
    encoded = executable.to_bytes()
    assert BytecodeExecutable.from_bytes(encoded).program == program
    assert encoded == BytecodeExecutable(program).to_bytes()
    assert executable.digest() == BytecodeExecutable.from_bytes(encoded).digest()
    with pytest.raises(BytecodeError):
        BytecodeExecutable.from_bytes(encoded[:-1])
    with pytest.raises(BytecodeError, match="trailing"):
        BytecodeExecutable.from_bytes(encoded + b"x")


def test_image_v2_requires_graph_and_binary_program_identity_and_reads_v1() -> None:
    """Mathematics: v2 admission requires `decode(B)=P`, while v1 graph-only images remain migration-readable."""

    image = demo_image()
    payload = image.to_dict()
    assert payload["format"] == "mailcpu-image-v2"
    assert ExecutableImage.from_dict(payload).digest() == image.digest()

    mismatched = dict(payload)
    mismatched["program"] = [{"op": "HALT", "args": []}]
    with pytest.raises(ValueError, match="disagrees"):
        ExecutableImage.from_dict(mismatched)

    legacy = dict(payload)
    legacy["format"] = "mailcpu-image-v1"
    legacy.pop("bytecode_hex")
    assert ExecutableImage.from_dict(legacy).program == image.program


def test_native_cli_demo(capsys) -> None:
    """Mathematics: verify the native command path returns `result = 42` without a WSL dependency."""

    assert main(["demo"]) == 0
    output = capsys.readouterr().out
    assert '"result": 42' in output
    assert '"status": "halted"' in output


def test_native_cli_memory_demo(capsys) -> None:
    """Mathematics: verify checkpoint projection preserves shared value `x_before = x_after` and journal validity."""

    assert main(["memory-demo"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["shared_before_checkpoint"] == "mailcpu-memory"
    assert result["shared_after_checkpoint"] == "mailcpu-memory"
    assert result["journal_valid"] is True


def test_native_cli_network_demo(capsys) -> None:
    """Mathematics: the CLI witness preserves datagram bytes across a four-vertex route and validates its journal."""

    assert main(["network-demo"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["payload"] == "mailcpu-datagram"
    assert len(result["route"]) == 4
    assert result["journal_valid"] is True


def test_unsupported_execution_regime_refuses_without_fake_fallback() -> None:
    """Mathematics: image admission is partial `admit(I) ⇔ regime(I) = MAILCPU`, not an unproved coercion."""

    image = ExecutableImage(
        "sense-experiment",
        Program((Instruction(Op.HALT),)),
        regime=ExecutionRegime.SENSE,
    )
    with pytest.raises(UnsupportedRegimeError, match="no verified MailCPU backend"):
        image.require_supported()
