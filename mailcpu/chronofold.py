"""Structural trajectory ledger with periodicity metadata and Bennett replay."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

from .reversible_gates import (
    ReversibleGate,
    ReversibleProgram,
    apply_gate,
    execute_gates,
    phase_factor,
    reverse_gates,
)


@dataclass(frozen=True)
class AllocatorSnapshot:
    """Mathematics: immutable snapshot of bit allocation state `(nbits, peak, free_counts)`."""

    nbits: int
    peak: int
    free_sizes: tuple[tuple[int, int], ...]

    @classmethod
    def capture(cls, program: ReversibleProgram) -> AllocatorSnapshot:
        """Mathematics: project `program` allocator onto discrete state coordinate."""

        free_tuple = tuple(sorted((size, len(buckets)) for size, buckets in program._free.items() if buckets))
        return cls(nbits=program.nbits, peak=program.peak_bits, free_sizes=free_tuple)


@dataclass
class ChronoFold:
    r"""Mathematics: trajectory representation `\mathcal{F} = \langle s_0, \mathcal{T}, \mathcal{A}, D \rangle` with optional period metadata."""

    initial_tape: int
    trace: list[int] = field(default_factory=list)
    period_header: int = 0
    period_length: int = 1
    period_stride: int = 0
    active_chronons: int = 0
    sector_reads: int = 0

    @property
    def phase(self) -> complex:
        r"""Mathematics: evaluate trajectory geometric phase `D = (-i)^{n_{active}}`."""

        return phase_factor(self.active_chronons)

    def record_step(self, step_code: int, active_delta: int = 0, read_delta: int = 0) -> None:
        """Mathematics: append step code to trace ledger and accumulate chronon count."""

        self.trace.append(step_code)
        self.active_chronons += active_delta
        self.sector_reads += read_delta

    def detect_periodicity(self, min_period: int = 1, max_period: int = 64) -> bool:
        r"""Mathematics: detect shift-periodic recurrence `\exists P, S : t_{i+P} = t_i + S` and store metadata without deleting samples."""

        trace_len = len(self.trace)
        if trace_len < min_period * 2:
            return False
        for period in range(min_period, min(max_period + 1, trace_len // 2)):
            candidate_stride = self.trace[-1] - self.trace[-1 - period]
            is_periodic = True
            for index in range(1, period + 1):
                if self.trace[-index] - self.trace[-index - period] != candidate_stride:
                    is_periodic = False
                    break
            if is_periodic:
                self.period_length = period
                self.period_stride = candidate_stride
                self.period_header = trace_len - 2 * period
                return True
        return False

    def recompute_final_tape(
        self,
        gate_generator: Callable[[int], Sequence[ReversibleGate | tuple[int, int, int, int, int]]],
    ) -> tuple[int, int]:
        r"""Mathematics: Bennett constant-space forward replay `T^N(s_0)` in `\mathcal{O}(N)` time and `\mathcal{O}(1)` memory."""

        current_tape = self.initial_tape
        accumulated_active = 0
        for step_code in self.trace:
            gates = gate_generator(step_code)
            current_tape, step_active = execute_gates(current_tape, gates)
            accumulated_active += step_active
        return (current_tape, accumulated_active)

    def reverse_tape(
        self,
        final_tape: int,
        gate_generator: Callable[[int], Sequence[ReversibleGate | tuple[int, int, int, int, int]]],
    ) -> tuple[int, int]:
        r"""Mathematics: reverse replay `(T^N)^{-1}(s_N) = s_0` asserting zero thermodynamic dissipation."""

        current_tape = final_tape
        accumulated_active = 0
        for step_code in reversed(self.trace):
            gates = gate_generator(step_code)
            current_tape, step_active = execute_gates(current_tape, reverse_gates(gates))
            accumulated_active += step_active
        return (current_tape, accumulated_active)

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize chronofold descriptor into JSON-serializable mapping."""

        return {
            "format": "mailcpu-chronofold/1",
            "initial_tape": hex(self.initial_tape),
            "trace": self.trace,
            "period_header": self.period_header,
            "period_length": self.period_length,
            "period_stride": self.period_stride,
            "active_chronons": self.active_chronons,
            "sector_reads": self.sector_reads,
            "phase": [self.phase.real, self.phase.imag],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ChronoFold:
        """Mathematics: deserialize mapping into validated `ChronoFold` instance."""

        if data.get("format") != "mailcpu-chronofold/1":
            raise ValueError(f"unsupported chronofold format: {data.get('format')}")
        raw_tape = data["initial_tape"]
        initial_tape = int(raw_tape, 16) if isinstance(raw_tape, str) else int(raw_tape)
        trace = [int(step_code) for step_code in data.get("trace", [])]
        period_header = int(data.get("period_header", 0))
        period_length = int(data.get("period_length", 1))
        period_stride = int(data.get("period_stride", 0))
        active_chronons = int(data.get("active_chronons", 0))
        sector_reads = int(data.get("sector_reads", 0))
        if initial_tape < 0:
            raise ValueError("chronofold initial_tape must be non-negative")
        if any(step_code < 0 for step_code in trace):
            raise ValueError("chronofold trace codes must be non-negative")
        if period_header < 0 or period_length <= 0:
            raise ValueError("chronofold period metadata has invalid bounds")
        if active_chronons < 0 or sector_reads < 0:
            raise ValueError("chronofold counters must be non-negative")
        if period_header and period_header + 2 * period_length > len(trace):
            raise ValueError("chronofold period metadata exceeds the retained trace")
        fold = cls(
            initial_tape=initial_tape,
            trace=trace,
            period_header=period_header,
            period_length=period_length,
            period_stride=period_stride,
            active_chronons=active_chronons,
            sector_reads=sector_reads,
        )
        return fold

    def to_json(self) -> str:
        """Mathematics: serialize chronofold to UTF-8 JSON string."""

        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_json(cls, payload: str) -> ChronoFold:
        """Mathematics: deserialize chronofold from UTF-8 JSON string."""

        return cls.from_dict(json.loads(payload))
