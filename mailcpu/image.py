"""Portable MailCPU executable images and filesystem payloads."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from .bytecode import BytecodeError, BytecodeExecutable
from .environment import VirtualEnvironment
from .fs import FsError
from .model import Instruction, Op, Program


class UnsupportedRegimeError(ValueError):
    """An image requests an execution regime without a verified MailCPU backend."""


class ExecutionRegime(str, Enum):
    """Regime tags reserved for proof-gated polymorphic execution."""

    MAILCPU = "MAILCPU"
    SENSE = "SENSE"
    LEAP = "LEAP"
    HDC = "HDC"
    MDL = "MDL"


@dataclass(frozen=True)
class ImageFile:
    """One path/data pair embedded in a portable executable image."""

    path: str
    data: bytes
    mode: int = 0o644


def encode_program(program: Program) -> list[dict[str, Any]]:
    """Mathematics: serialize program function `P : pc ↦ (op, args)` without changing its finite graph."""

    return [
        {"op": instruction.op.value, "args": list(instruction.args)}
        for instruction in program.instructions
    ]


def decode_program(payload: list[dict[str, Any]]) -> Program:
    """Mathematics: reconstruct `P` from its opcode/operand graph and reapply static domain validation."""

    return Program(
        tuple(Instruction(Op(item["op"]), tuple(item.get("args", ()))) for item in payload)
    )


@dataclass(frozen=True)
class ExecutableImage:
    """A self-contained MailCPU program, environment payload, and reproducible metadata."""

    name: str
    program: Program
    files: tuple[ImageFile, ...] = ()
    environment: tuple[tuple[str, str], ...] = ()
    regime: ExecutionRegime = ExecutionRegime.MAILCPU
    bytecode: bytes | None = None

    def __post_init__(self) -> None:
        """Mathematics: establish compiled identity `B=encode(P)` or require supplied `B` to decode exactly to `P`."""

        compiled = BytecodeExecutable(self.program).to_bytes() if self.bytecode is None else bytes(self.bytecode)
        try:
            decoded = BytecodeExecutable.from_bytes(compiled).program
        except BytecodeError as exc:
            raise ValueError(f"invalid image bytecode: {exc}") from exc
        if decoded != self.program:
            raise ValueError("image program and bytecode disagree")
        object.__setattr__(self, "bytecode", compiled)

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: project image state `I = (name, P, files, env)` into canonical JSON-compatible data."""

        return {
            "format": "mailcpu-image-v2",
            "name": self.name,
            "regime": self.regime.value,
            "program": encode_program(self.program),
            "bytecode_hex": bytes(self.bytecode or b"").hex(),
            "files": [
                {"path": item.path, "data_hex": item.data.hex(), "mode": item.mode}
                for item in sorted(self.files, key=lambda file: file.path)
            ],
            "environment": [list(item) for item in sorted(self.environment)],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ExecutableImage":
        """Mathematics: invert image formats v1/v2, requiring v2 binary `B` and readable graph `P` to decode identically."""

        image_format = payload.get("format")
        if image_format not in {"mailcpu-image-v1", "mailcpu-image-v2"}:
            raise ValueError("unsupported MailCPU image format")
        bytecode: bytes | None = None
        if image_format == "mailcpu-image-v2":
            try:
                bytecode = bytes.fromhex(str(payload["bytecode_hex"]))
                binary_program = BytecodeExecutable.from_bytes(bytecode).program
            except (KeyError, ValueError, BytecodeError) as exc:
                raise ValueError(f"invalid image bytecode: {exc}") from exc
            graph_program = decode_program(payload["program"])
            if graph_program != binary_program:
                raise ValueError("image program graph disagrees with binary bytecode")
            program = binary_program
        else:
            program = decode_program(payload["program"])
        files = tuple(
            ImageFile(item["path"], bytes.fromhex(item["data_hex"]), int(item.get("mode", 0o644)))
            for item in payload.get("files", [])
        )
        environment = tuple((str(key), str(value)) for key, value in payload.get("environment", []))
        return cls(
            str(payload["name"]),
            program,
            files,
            environment,
            ExecutionRegime(payload.get("regime", ExecutionRegime.MAILCPU.value)),
            bytecode,
        )

    def require_supported(self) -> None:
        """Mathematics: validate execution regime `r = MAILCPU` before admitting program execution."""

        if self.regime is not ExecutionRegime.MAILCPU:
            raise UnsupportedRegimeError(
                f"execution regime {self.regime.value} has no verified MailCPU backend"
            )

    def digest(self) -> str:
        """Mathematics: identify the image by `h = SHA256(canonical_json(I))`, independent of file ordering."""

        canonical = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    def save(self, path: str | Path) -> None:
        """Mathematics: publish canonical image `I` by durable sibling write and atomic replacement `replace(I_tmp, I)`."""

        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"
        temporary_path: Path | None = None
        try:
            descriptor, raw_temporary_path = tempfile.mkstemp(
                prefix=f".{destination.name}.",
                suffix=".tmp",
                dir=str(destination.parent),
                text=True,
            )
            temporary_path = Path(raw_temporary_path)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, destination)
            temporary_path = None
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink()
                except FileNotFoundError:
                    pass

    @classmethod
    def load(cls, path: str | Path) -> "ExecutableImage":
        """Mathematics: parse `JSON(path)` and reconstruct the validated executable image `I`."""

        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.from_dict(payload)

    def install(self, environment: VirtualEnvironment) -> None:
        """Mathematics: extend filesystem graph `F` with every image file, creating each missing parent directory."""

        for item in sorted(self.files, key=lambda file: (file.path.count("/"), file.path)):
            _ensure_parent_directories(environment, item.path)
            try:
                environment.kernel.fs.stat(item.path)
                environment.kernel.fs.write_file(item.path, item.data, offset=0, truncate=True)
            except FsError:
                environment.kernel.fs.create_file(item.path, item.data, item.mode)


def _ensure_parent_directories(environment: VirtualEnvironment, path: str) -> None:
    """Mathematics: recursively ensure every prefix in `parent(path)` exists in the directory graph."""

    parts = path.strip("/").split("/")[:-1]
    current = ""
    for component in parts:
        current += "/" + component
        try:
            environment.kernel.fs.stat(current)
        except FsError:
            environment.kernel.fs.mkdir(current)
