r"""TCP sequence ring arithmetic over $\mathbb{Z}_{2^{32}}$ and AIMD backpressure flow controller."""

from __future__ import annotations

from dataclasses import dataclass

MOD32: int = 1 << 32
HALF32: int = 1 << 31


def seq_diff(a: int, b: int) -> int:
    r"""Mathematics: compute signed cyclic distance `(a - b) \pmod{2^{32}}` projected onto `[-2^{31}, 2^{31} - 1]`."""

    diff = (a - b) % MOD32
    if diff >= HALF32:
        diff -= MOD32
    return diff


def seq_less_than(a: int, b: int) -> bool:
    r"""Mathematics: evaluate strict circular precedence `a <_{\mathbb{Z}_{2^{32}}} b \iff \text{seq\_diff}(b, a) > 0`."""

    return seq_diff(b, a) > 0


def seq_in_window(seq: int, base: int, window_size: int) -> bool:
    r"""Mathematics: evaluate window containment predicate `0 \le (seq - base) \pmod{2^{32}} < window\_size`."""

    offset = (seq - base) % MOD32
    return 0 <= offset < window_size


@dataclass
class AimdController:
    r"""Mathematics: autonomous Additive-Increase Multiplicative-Decrease feedback operator `W_{t+1} = f_{\text{AIMD}}(W_t)` regulating task concurrency without centralized mutexes."""

    window: float = 1.0
    min_window: float = 1.0
    max_window: float = 64.0
    alpha: float = 1.0
    beta: float = 0.5

    def on_ack(self) -> float:
        r"""Mathematics: linear accumulation phase `W \leftarrow \min(W_{\max}, W + \frac{\alpha}{W})`."""

        self.window = min(self.max_window, self.window + self.alpha / max(1.0, self.window))
        return self.window

    def on_loss(self) -> float:
        r"""Mathematics: multiplicative descent phase `W \leftarrow \max(W_{\min}, W \cdot \beta)`."""

        self.window = max(self.min_window, self.window * self.beta)
        return self.window

    def can_dispatch(self, in_flight: int) -> bool:
        r"""Mathematics: evaluate backpressure predicate `in\_flight < W`."""

        return in_flight < self.window

    def snapshot(self) -> dict[str, float]:
        """Mathematics: serialize controller state coordinates for checkpoint persistence."""

        return {
            "window": float(self.window),
            "min_window": float(self.min_window),
            "max_window": float(self.max_window),
            "alpha": float(self.alpha),
            "beta": float(self.beta),
        }

    @classmethod
    def from_snapshot(cls, data: dict[str, float]) -> AimdController:
        """Mathematics: reconstruct `AimdController` from serialized state mapping."""

        return cls(
            window=float(data.get("window", 1.0)),
            min_window=float(data.get("min_window", 1.0)),
            max_window=float(data.get("max_window", 64.0)),
            alpha=float(data.get("alpha", 1.0)),
            beta=float(data.get("beta", 0.5)),
        )
