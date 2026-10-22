"""One validated admission boundary for MailCPU source, bytecode, and ELF artifacts."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import tempfile
from typing import Any

from .assembler import AssemblyError, assemble
from .bytecode import BytecodeError, BytecodeExecutable
from .elf import ElfError, ElfImage, parse_elf
from .image import ExecutableImage


class ArtifactIngestionError(ValueError):
    """An artifact cannot enter any admitted compiler/output domain."""


class ArtifactKind(str, Enum):
    """The finite input/output domains recognized by the general ingestion boundary."""

    ASSEMBLY = "assembly"
    BYTECODE = "bytecode"
    ELF = "elf"


@dataclass(frozen=True)
class IngestedArtifact:
    """A digest-preserving artifact projection with exactly one validated payload interpretation."""

    name: str
    kind: ArtifactKind
    source_digest: str
    content_digest: str
    payload: bytes
    image: ExecutableImage | None = None
    elf: ElfImage | None = None

    def require_image(self) -> ExecutableImage:
        """Mathematics: project `I` only when `kind∈{ASSEMBLY,BYTECODE}` and `image≠∅`; ELF remains a loader artifact."""

        if self.image is None:
            raise ArtifactIngestionError("artifact has no MailCPU executable image")
        return self.image

    def save(self, path: str | Path) -> None:
        """Mathematics: publish the validated artifact projection by atomic replacement, with image JSON or exact ELF bytes according to `kind`."""

        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if self.image is not None:
            self.image.save(destination)
            return
        _atomic_write(destination, self.payload)

    def report(self) -> dict[str, object]:
        """Mathematics: project artifact evidence `R=(kind,name,source_digest,content_digest,loader_metadata)` without changing state."""

        result: dict[str, object] = {
            "name": self.name,
            "kind": self.kind.value,
            "source_digest": self.source_digest,
            "content_digest": self.content_digest,
        }
        if self.image is not None:
            result.update({"image_name": self.image.name, "instruction_count": len(self.image.program.instructions)})
        if self.elf is not None:
            result.update(
                {
                    "bits": self.elf.bits,
                    "machine": self.elf.machine_name,
                    "interpreter": self.elf.interpreter,
                    "dynamic": self.elf.has_dynamic_segment,
                    "load_segments": len(self.elf.segments),
                }
            )
        return result


class ArtifactIngestor:
    """Format-detecting compiler/artifact adapter that delegates admission to existing validators."""

    @classmethod
    def ingest_bytes(
        cls,
        payload: bytes,
        name: str = "artifact",
        format_hint: str | None = None,
    ) -> IngestedArtifact:
        """Mathematics: apply `detect(x)` by magic, then evaluate the matching validated relation without fallback after a recognized magic failure."""

        data = bytes(payload)
        if not name:
            raise ArtifactIngestionError("artifact name must be non-empty")
        kind = cls._detect_kind(data, name, format_hint)
        source_digest = hashlib.sha256(data).hexdigest()
        try:
            if kind is ArtifactKind.ASSEMBLY:
                source = data.decode("utf-8")
                program = assemble(source)
                image = ExecutableImage(Path(name).stem or "artifact", program)
                content_digest = hashlib.sha256(bytes(image.bytecode or b"")).hexdigest()
                return IngestedArtifact(name, kind, source_digest, content_digest, data, image=image)
            if kind is ArtifactKind.BYTECODE:
                executable = BytecodeExecutable.from_bytes(data)
                image = ExecutableImage(Path(name).stem or "artifact", executable.program, bytecode=data)
                return IngestedArtifact(name, kind, source_digest, executable.digest(), data, image=image)
            elf = parse_elf(data)
            return IngestedArtifact(name, kind, source_digest, elf.digest, data, elf=elf)
        except (UnicodeDecodeError, AssemblyError, BytecodeError, ElfError, ValueError) as error:
            raise ArtifactIngestionError(f"cannot ingest {name!r} as {kind.value}: {error}") from error

    @classmethod
    def ingest_path(cls, path: str | Path, format_hint: str | None = None) -> IngestedArtifact:
        """Mathematics: read finite host artifact `x=bytes(path)` once, then apply `ingest_bytes(x,path.name,hint)`."""

        source_path = Path(path)
        try:
            payload = source_path.read_bytes()
        except OSError as error:
            raise ArtifactIngestionError(f"cannot read artifact {source_path}: {error}") from error
        return cls.ingest_bytes(payload, source_path.name, format_hint)

    @staticmethod
    def _detect_kind(payload: bytes, name: str, format_hint: str | None) -> ArtifactKind:
        """Mathematics: choose `K` by explicit hint or disjoint magic domains `MCPB`, `ELF`, and UTF-8 assembly text."""

        if format_hint is not None:
            normalized = format_hint.lower().lstrip(".")
            aliases = {
                "mca": ArtifactKind.ASSEMBLY,
                "asm": ArtifactKind.ASSEMBLY,
                "assembly": ArtifactKind.ASSEMBLY,
                "mcpb": ArtifactKind.BYTECODE,
                "bytecode": ArtifactKind.BYTECODE,
                "elf": ArtifactKind.ELF,
            }
            try:
                return aliases[normalized]
            except KeyError as error:
                raise ArtifactIngestionError(f"unsupported artifact format hint: {format_hint}") from error
        if payload.startswith(b"MCPB"):
            return ArtifactKind.BYTECODE
        if payload.startswith(b"\x7fELF"):
            return ArtifactKind.ELF
        suffix = Path(name).suffix.lower()
        if suffix in {".mcpb", ".bytecode"}:
            return ArtifactKind.BYTECODE
        if suffix in {".elf", ".so", ".bin"}:
            return ArtifactKind.ELF
        try:
            payload.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ArtifactIngestionError("artifact has no recognized magic and is not UTF-8 assembly") from error
        return ArtifactKind.ASSEMBLY


def ingest_bytes(payload: bytes, name: str = "artifact", format_hint: str | None = None) -> IngestedArtifact:
    """Mathematics: expose the total public ingestion relation `x↦ArtifactIngestor.ingest_bytes(x)`."""

    return ArtifactIngestor.ingest_bytes(payload, name, format_hint)


def ingest_path(path: str | Path, format_hint: str | None = None) -> IngestedArtifact:
    """Mathematics: expose path ingestion `path↦ingest_bytes(read(path))` with one read and one validated output."""

    return ArtifactIngestor.ingest_path(path, format_hint)


def _atomic_write(path: Path, payload: bytes) -> None:
    """Mathematics: publish bytes by `fsync(write(tmp))` followed by atomic `replace(tmp,path)` and no partial destination."""

    temporary_path: Path | None = None
    try:
        descriptor, raw_temporary_path = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=str(path.parent),
        )
        temporary_path = Path(raw_temporary_path)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    except OSError as error:
        raise ArtifactIngestionError(f"cannot publish artifact {path}: {error}") from error
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass
