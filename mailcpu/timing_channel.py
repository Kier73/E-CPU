"""Discrete Cadence Modulation (DCM) and Anantharam-Verdú timing channel coder."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass
class TimingChannelConfig:
    r"""Mathematics: parameter configuration `\langle \Delta_0, \delta, B, \alpha \rangle` for discrete cadence modulation."""

    base_delay_ms: float = 20.0
    quantum_ms: float = 5.0
    bits_per_symbol: int = 4
    pll_alpha: float = 0.05

    @property
    def max_symbol(self) -> int:
        """Mathematics: compute upper symbol boundary `2^B - 1`."""

        return (1 << self.bits_per_symbol) - 1


class CadenceModulator:
    r"""Mathematics: map discrete symbol stream `d_k \in [0, 2^B - 1]` to physical inter-transmission delays `\Delta t_k = \Delta_0 + d_k \cdot \delta`."""

    def __init__(self, config: TimingChannelConfig | None = None) -> None:
        """Mathematics: initialize cadence modulator with specified timing parameters."""

        self.config = config or TimingChannelConfig()

    def encode_symbol(self, symbol: int) -> float:
        r"""Mathematics: compute interval `\Delta t(d) = \Delta_0 + (d \bmod 2^B) \cdot \delta` in milliseconds."""

        clamped = symbol & self.config.max_symbol
        return self.config.base_delay_ms + clamped * self.config.quantum_ms

    def encode_bytes(self, data: bytes) -> list[float]:
        r"""Mathematics: decompose byte stream into `2 \times |data|` nibble delays (big-endian)."""

        delays: list[float] = []
        for byte_val in data:
            high_nibble = (byte_val >> 4) & 0x0F
            low_nibble = byte_val & 0x0F
            delays.append(self.encode_symbol(high_nibble))
            delays.append(self.encode_symbol(low_nibble))
        return delays


class CadenceDemodulator:
    r"""Mathematics: maximum-likelihood symbol estimator `\hat{d} = \operatorname{round}((\Delta t' - \Delta_0) / \delta)` with Phase-Locked Loop (PLL) baseline steering."""

    def __init__(self, config: TimingChannelConfig | None = None) -> None:
        r"""Mathematics: initialize demodulator state with tracking base interval `\hat{\Delta}_0 = \Delta_0`."""

        self.config = config or TimingChannelConfig()
        self.tracked_base_ms = self.config.base_delay_ms

    def decode_interval(self, observed_delay_ms: float) -> int:
        r"""Mathematics: decode symbol `\hat{d}` from `observed_delay_ms` and steer baseline via `\Delta_0 \leftarrow \Delta_0 + \alpha \cdot \text{error}`."""

        raw_symbol = (observed_delay_ms - self.tracked_base_ms) / self.config.quantum_ms
        symbol = round(raw_symbol)
        clamped_symbol = max(0, min(self.config.max_symbol, symbol))

        ideal_delay = self.tracked_base_ms + clamped_symbol * self.config.quantum_ms
        phase_error = observed_delay_ms - ideal_delay
        self.tracked_base_ms += self.config.pll_alpha * phase_error

        return clamped_symbol

    def decode_intervals(self, intervals_ms: Sequence[float]) -> bytes:
        """Mathematics: assemble decoded nibble stream into byte vector."""

        nibbles = [self.decode_interval(delta) for delta in intervals_ms]
        output = bytearray()
        for i in range(0, len(nibbles) - 1, 2):
            byte_val = (nibbles[i] << 4) | nibbles[i + 1]
            output.append(byte_val)
        return bytes(output)
