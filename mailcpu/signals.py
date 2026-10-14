"""Typed process-signal vocabulary for the MailCPU control plane."""

from __future__ import annotations

from enum import Enum


class SignalError(ValueError):
    """A signal name or delivery target is invalid."""


class Signal(str, Enum):
    """Signals supported by the deterministic native process ABI."""

    TERM = "TERM"
    KILL = "KILL"
    STOP = "STOP"
    CONT = "CONT"
    INT = "INT"
    QUIT = "QUIT"
    HUP = "HUP"

    @classmethod
    def parse(cls, value: str | "Signal") -> "Signal":
        """Mathematics: resolve `σ = enum(uppercase(strip(SIG-prefix(value))))` in the finite signal set."""

        if isinstance(value, cls):
            return value
        normalized = str(value).upper()
        if normalized.startswith("SIG"):
            normalized = normalized[3:]
        try:
            return cls(normalized)
        except ValueError as exc:
            raise SignalError(f"unknown signal: {value}") from exc

    @property
    def default_exit_code(self) -> int:
        """Mathematics: a fatal `σ` terminates its target with `128 + n` where `n` is the signal's ordinal position in the ascending signal vocabulary."""

        return _EXIT_CODES[self]

    @property
    def is_fatal(self) -> bool:
        """Mathematics: `σ` is fatal when its default exit code is defined, that is, when termination is a total transition with no resumption."""

        return self in _EXIT_CODES


_EXIT_CODES = {
    Signal.HUP: 129,
    Signal.INT: 130,
    Signal.QUIT: 131,
    Signal.KILL: 137,
    Signal.TERM: 143,
}

DEFAULT_TERMINATION_EXIT_CODE = Signal.TERM.default_exit_code
