"""Selective, exact SEND-stream observation over the affine MailCPU loop fragment.

This is an observer-side semantic query, not a transport send or host execution.
It preserves the ordered SEND output projection while omitting the other
semantic transitions. A pure-counter loop supports bounded O(log i) queries for
the output at index i, even when the program never halts. No WAIT, SYSCALL,
MUL or secondary branch is silently interpreted as a transparent effect.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any, Mapping, Sequence

from .affine_orbit import (
    AffineOrbitRefused,
    _apply,
    _initial_identity,
    _matrix_multiply,
    _matrix_power,
    _names_of,
    _program_identity,
    _symbolic,
)
from .model import Instruction, Op, Program

_FRAGMENT = frozenset((Op.SET, Op.COPY, Op.ADD, Op.SEND))


@dataclass(frozen=True)
class StreamObservation:
    """An exact indexed (mailbox, value) event from the program's output log."""

    index: int
    mailbox: str
    value: int


@dataclass(frozen=True)
class StreamObservationReceipt:
    """Digest-bound query evidence that can be independently recomputed."""

    program_digest: str
    initial_digest: str
    index: int
    mailbox: str
    value: int

    def _payload(self) -> dict[str, Any]:
        """Mathematics: project an indexed observation into strict typed JSON."""

        return {
            "schema": "mailcpu.affine-send-observation.v1",
            "program_digest": self.program_digest,
            "initial_digest": self.initial_digest,
            "index": hex(self.index),
            "mailbox": self.mailbox,
            "value": hex(self.value),
        }

    @property
    def digest(self) -> str:
        """Mathematics: hash canonical bytes of an exact claimed observation."""

        encoded = json.dumps(
            self._payload(), sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        return sha256(encoded).hexdigest()

    def snapshot(self) -> dict[str, Any]:
        """Mathematics: emit a portable, versioned, content-addressed receipt."""

        return {**self._payload(), "digest": self.digest}

    @classmethod
    def from_snapshot(cls, raw: Mapping[str, Any]) -> "StreamObservationReceipt":
        """Mathematics: reject unknown fields, noncanonical integers and tampered receipts."""

        if not isinstance(raw, Mapping) or set(raw) != {
            "schema", "program_digest", "initial_digest", "index", "mailbox", "value", "digest"
        } or raw["schema"] != "mailcpu.affine-send-observation.v1":
            raise AffineOrbitRefused("stream receipt envelope is malformed")
        for name in ("program_digest", "initial_digest", "digest"):
            item = raw[name]
            if (
                not isinstance(item, str) or len(item) != 64
                or any(ch not in "0123456789abcdef" for ch in item)
            ):
                raise AffineOrbitRefused("stream receipt requires lower-case SHA256 identity")
        if not isinstance(raw["mailbox"], str) or not raw["mailbox"]:
            raise AffineOrbitRefused("stream receipt mailbox is malformed")
        def decode(value: Any) -> int:
            """Mathematics: invert the unique canonical lowercase hexadecimal representation."""

            if not isinstance(value, str):
                raise AffineOrbitRefused("stream receipt integer must be a hexadecimal string")
            try:
                parsed = int(value, 16)
            except ValueError as exc:
                raise AffineOrbitRefused("stream receipt integer is malformed") from exc
            if hex(parsed) != value:
                raise AffineOrbitRefused("stream receipt integer is noncanonical")
            return parsed
        index = decode(raw["index"])
        value = decode(raw["value"])
        if index < 0:
            raise AffineOrbitRefused("stream receipt index must be nonnegative")
        receipt = cls(raw["program_digest"], raw["initial_digest"], index, raw["mailbox"], value)
        if receipt.snapshot() != dict(raw):
            raise AffineOrbitRefused("stream receipt digest is invalid")
        return receipt


def _identity(size: int) -> list[list[int]]:
    """Mathematics: return the homogeneous identity linear map."""

    return [[int(i == j) for j in range(size)] for i in range(size)]


def _compile_segment(
    instructions: Sequence[Instruction],
    names: tuple[str, ...],
    *,
    max_bits: int,
) -> tuple[list[list[int]], tuple[tuple[str, tuple[int, ...]], ...]]:
    """Mathematics: compile affine updates plus their position-specific SEND readouts."""

    index = {name: i for i, name in enumerate(names)}
    transform = _identity(len(names) + 1)
    pending: list[Instruction] = []
    emitted: list[tuple[str, tuple[int, ...]]] = []
    for ins in instructions:
        if ins.op not in _FRAGMENT:
            raise AffineOrbitRefused(
                f"{ins.op.value} requires a different semantic Ground than SET/COPY/ADD/SEND"
            )
        if ins.op is Op.SEND:
            if pending:
                transform = _matrix_multiply(
                    _symbolic(pending, names, max_bits=max_bits),
                    transform, max_bits=max_bits,
                )
                pending = []
            emitted.append((ins.args[0], tuple(transform[index[ins.args[1]]])))
        else:
            pending.append(ins)
    if pending:
        transform = _matrix_multiply(
            _symbolic(pending, names, max_bits=max_bits),
            transform, max_bits=max_bits,
        )
    return transform, tuple(emitted)


class AffineSendStream:
    """Select one exact SEND event without constructing the complete output log."""

    def __init__(
        self,
        program: Program,
        initial_registers: Mapping[str, int] | None = None,
        *,
        max_registers: int = 32,
        max_bits: int = 65536,
    ) -> None:
        """Mathematics: compile affine readouts, then prove the pure-counter first exit."""

        if not isinstance(program, Program):
            raise AffineOrbitRefused("stream compilation requires a validated Program")
        if initial_registers is None:
            initial_registers = {}
        if not isinstance(initial_registers, Mapping) or any(
            not isinstance(name, str) or not name
            or not isinstance(value, int) or isinstance(value, bool)
            for name, value in initial_registers.items()
        ):
            raise AffineOrbitRefused("stream valuation must map register names to integers")
        if not isinstance(max_bits, int) or isinstance(max_bits, bool) or max_bits < 4:
            raise AffineOrbitRefused("max_bits must be an integer of at least four")
        if not isinstance(max_registers, int) or isinstance(max_registers, bool) or max_registers < 1:
            raise AffineOrbitRefused("max_registers must be a positive integer")
        if any(abs(value).bit_length() > max_bits for value in initial_registers.values()):
            raise AffineOrbitRefused("stream initial state exceeds integer-bit admission")
        instructions = program.instructions
        branches = [pc for pc, instruction in enumerate(instructions) if instruction.op is Op.BRANCH]
        if len(branches) != 1:
            raise AffineOrbitRefused("stream requires exactly one BRANCH")
        end = branches[0]
        start = instructions[end].args[1]
        if start > end:
            raise AffineOrbitRefused("forward BRANCH is not a supported loop")
        if not instructions[end + 1:] or instructions[-1].op is not Op.HALT:
            raise AffineOrbitRefused("stream loop must have a terminal HALT suffix")
        names_set = _names_of(instructions) | set(initial_registers)
        names_set.update(
            ins.args[1] for ins in instructions if ins.op is Op.SEND
        )
        names = tuple(sorted(names_set))
        if len(names) > max_registers:
            raise AffineOrbitRefused("stream register dimension exceeds admission")
        prefix, body, suffix = instructions[:start], instructions[start:end], instructions[end + 1:-1]
        self._P, self._prefix_sends = _compile_segment(prefix, names, max_bits=max_bits)
        self._B, self._body_sends = _compile_segment(body, names, max_bits=max_bits)
        self._S, self._suffix_sends = _compile_segment(suffix, names, max_bits=max_bits)
        self._initial = dict(initial_registers)
        self._program = program
        self._max_bits = max_bits
        self._vp = _apply(
            self._P, [self._initial.get(name, 0) for name in names] + [1],
            max_bits=max_bits,
        )
        self._v0 = [self._initial.get(name, 0) for name in names] + [1]
        self._final_body: list[int] | None = None
        self._names = names
        count = len(names)
        ci = names.index(instructions[end].args[0])
        row = self._B[ci]
        unchanged = {
            i for i in range(count)
            if self._B[i] == [int(j == i) for j in range(count + 1)]
        }
        if row[ci] != 1 or any(
            row[i] != 0 for i in range(count) if i != ci and i not in unchanged
        ):
            raise AffineOrbitRefused("stream counter is not an independently pure affine counter")
        counter_step = row[count] + sum(
            row[i] * self._vp[i] for i in unchanged if i != ci
        )
        counter_initial = self._vp[ci]
        if abs(counter_step).bit_length() > max_bits:
            raise AffineOrbitRefused("stream counter increment exceeds integer-bit admission")
        if counter_step == 0:
            iterations = 1 if counter_initial == 0 else None
        else:
            quotient, remainder = divmod(-counter_initial, counter_step)
            iterations = quotient if remainder == 0 and quotient >= 1 else None
        self.iterations: int | None = iterations
        self.termination: str = "HALTS" if iterations is not None else "DIVERGES"
        self.counter_initial = counter_initial
        self.counter_delta = counter_step

    def length(self) -> int | None:
        """Mathematics: return the finite output count or None for an infinite stream."""

        if self.iterations is None:
            return None if self._body_sends else len(self._prefix_sends)
        return (
            len(self._prefix_sends)
            + self.iterations * len(self._body_sends)
            + len(self._suffix_sends)
        )

    def _read(
        self, emission: tuple[str, tuple[int, ...]], vector: list[int],
    ) -> tuple[str, int]:
        """Mathematics: evaluate one emitted row against its exact initial orbit coordinate."""

        name, row = emission
        return name, _apply([list(row)], vector, max_bits=self._max_bits)[0]

    def out(self, index: int) -> tuple[str, int]:
        """Mathematics: evaluate the given zero-based emitted output in O(log iteration) matrix products."""

        if not isinstance(index, int) or isinstance(index, bool) or index < 0:
            raise IndexError("stream output index must be a nonnegative integer")
        if index < len(self._prefix_sends):
            return self._read(self._prefix_sends[index], self._v0)
        offset = index - len(self._prefix_sends)
        body_count = len(self._body_sends)
        if body_count and (self.iterations is None or offset < self.iterations * body_count):
            iteration, emission_index = divmod(offset, body_count)
            state = _apply(
                _matrix_power(self._B, iteration, max_bits=self._max_bits),
                self._vp, max_bits=self._max_bits,
            )
            return self._read(self._body_sends[emission_index], state)
        if self.iterations is None:
            raise IndexError("stream index exceeds the available prefix")
        suffix_offset = offset - self.iterations * body_count
        if 0 <= suffix_offset < len(self._suffix_sends):
            if self._final_body is None:
                self._final_body = _apply(
                    _matrix_power(self._B, self.iterations, max_bits=self._max_bits),
                    self._vp, max_bits=self._max_bits,
                )
            return self._read(self._suffix_sends[suffix_offset], self._final_body)
        raise IndexError("stream output index is outside the finite log")

    def observe(self, index: int) -> StreamObservation:
        """Mathematics: return one typed observation, not a physical SEND operation."""

        mailbox, value = self.out(index)
        return StreamObservation(index, mailbox, value)

    def issue_receipt(self, index: int) -> StreamObservationReceipt:
        """Mathematics: bind an exact output query to program, valuation, and output identity."""

        mailbox, value = self.out(index)
        return StreamObservationReceipt(
            _program_identity(self._program),
            _initial_identity(self._initial),
            index, mailbox, value,
        )


def verify_stream_receipt(
    receipt: StreamObservationReceipt,
    program: Program,
    initial_registers: Mapping[str, int] | None = None,
    *,
    max_registers: int = 32,
    max_bits: int = 65536,
) -> bool:
    """Mathematics: independent exact reconstruction without replaying intermediate SENDs."""

    if not isinstance(receipt, StreamObservationReceipt):
        return False
    try:
        oracle = AffineSendStream(
            program, initial_registers,
            max_registers=max_registers, max_bits=max_bits,
        )
        return oracle.issue_receipt(receipt.index) == receipt
    except (AffineOrbitRefused, IndexError, TypeError, ValueError):
        return False
