r"""Vantage-point transformations for execution sequence re-parameterization.

Mathematics:
Let $x = (x_0, x_1, \dots, x_{N-1}) \in \mathbb{Z}^N$ be an observed sequence of
events (e.g. packet arrival delays, memory trace intervals, DNS latch states).
A vantage transform is a map $V: \mathbb{Z}^N \to \mathbb{Z}^{N'}$ that projects
the sequence into an alternative coordinate frame where hidden algebraic laws
become apparent:
1. Stride decimation: $\sigma_k(x)_j = x_{k \cdot j}$
2. Difference operator: $\Delta x_j = x_{j+1} - x_j$
3. Prefix integration: $\Sigma x_j = \sum_{i=0}^j x_i$
4. Origin centering: $\Omega(x)_j = x_j - x_0$
5. Modular projection: $\mu_M(x)_j = x_j \pmod M$
6. Range quantization: $\phi_K(x)_j = \lfloor \frac{(x_j - \min(x)) \cdot K}{\max(x) - \min(x)} \rfloor$
"""

from __future__ import annotations

from typing import Sequence


def vp_stride(lane: Sequence[int], k: int = 2) -> list[int]:
    r"""Decimate an observation sequence by stride step k.

    Mathematics:
    Given sequence $x = (x_0, x_1, \dots, x_{N-1})$, the decimated sequence is:
    \[
    \sigma_k(x)_j = x_{k \cdot j}, \quad 0 \le j < \lceil N / k \rceil
    \]
    Stride decimation isolates single threads in interleaved cyclic round-robin
    execution traces.

    Args:
        lane: Sequence of integer samples.
        k: Positive integer decimation step ($k \ge 1$).

    Returns:
        Decimated list of integers.
    """
    if k <= 0:
        raise ValueError(f"stride step k must be positive, got {k}")
    return list(lane[::k])


def vp_difference(lane: Sequence[int]) -> list[int]:
    r"""Compute discrete first differences of an observation sequence.

    Mathematics:
    Given sequence $x = (x_0, x_1, \dots, x_{N-1})$, the difference sequence is:
    \[
    \Delta x_j = x_{j+1} - x_j, \quad 0 \le j < N - 1
    \]
    Affine recurrences $x_{t+1} \equiv a x_t + c \pmod M$ with $a = 1$ project to
    constants $\Delta x_j = c$, collapsing arithmetic progressions to order-0.

    Args:
        lane: Sequence of integer samples.

    Returns:
        List of first differences of length $N - 1$.
    """
    if len(lane) < 2:
        return []
    return [lane[i + 1] - lane[i] for i in range(len(lane) - 1)]


def vp_integrate(lane: Sequence[int], seed: int = 0) -> list[int]:
    r"""Compute cumulative prefix sum of an observation sequence.

    Mathematics:
    Given sequence $x = (x_0, x_1, \dots, x_{N-1})$, the prefix sum sequence is:
    \[
    \Sigma x_j = \text{seed} + \sum_{i=0}^j x_i, \quad 0 \le j < N
    \]
    This is the discrete inverse operator of $\Delta$.

    Args:
        lane: Sequence of integer samples.
        seed: Initial cumulative offset.

    Returns:
        List of integrated cumulative sums of length $N$.
    """
    out: list[int] = []
    acc = seed
    for v in lane:
        acc += v
        out.append(acc)
    return out


def vp_origin(lane: Sequence[int]) -> list[int]:
    r"""Zero-center a sequence relative to its initial coordinate $x_0$.

    Mathematics:
    Given sequence $x = (x_0, x_1, \dots, x_{N-1})$, the origin-centered sequence is:
    \[
    \Omega(x)_j = x_j - x_0, \quad 0 \le j < N
    \]
    Preserves exact dynamics while eliminating arbitrary translation offsets.

    Args:
        lane: Sequence of integer samples.

    Returns:
        List of centered integer samples where the first element is 0.
    """
    if not lane:
        return []
    o = lane[0]
    return [v - o for v in lane]


def vp_modulus(lane: Sequence[int], m: int | None = None) -> list[int]:
    r"""Project sequence elements into integer ring $\mathbb{Z}_M$.

    Mathematics:
    Given sequence $x = (x_0, x_1, \dots, x_{N-1})$, modular projection is:
    \[
    \mu_M(x)_j = x_j \pmod M
    \]
    If $M$ is unspecified, the smallest power-of-two modulus or prime covering
    $\max(|x|)$ is selected from standard candidate rings.

    Args:
        lane: Sequence of integer samples.
        m: Optional modulus ring.

    Returns:
        List of modular residues in $[0, M - 1]$.
    """
    if not lane:
        return []
    if m is not None:
        if m <= 0:
            raise ValueError(f"modulus m must be positive, got {m}")
        return [v % m for v in lane]

    hi = max(abs(v) for v in lane)
    candidates = (256, 4096, 65536, 16777216, 2147483647, 4294967296)
    chosen = candidates[-1]
    for cand in candidates:
        if cand > hi:
            chosen = cand
            break
    return [v % chosen for v in lane]


def vp_fold(lane: Sequence[int], k_bins: int = 64) -> list[int]:
    r"""Quantize a sequence linearly into $K$ discrete bins.

    Mathematics:
    Let $x_{\min} = \min(x)$ and $x_{\max} = \max(x)$. The folded sequence is:
    \[
    \phi_K(x)_j = \begin{cases}
    0 & \text{if } x_{\max} = x_{\min} \\
    \lfloor \frac{(x_j - x_{\min}) \cdot K}{x_{\max} - x_{\min}} \rfloor & \text{otherwise}
    \end{cases}
    \]

    Args:
        lane: Sequence of integer samples.
        k_bins: Target discrete quantization bin resolution.

    Returns:
        List of quantized values bounded in $[0, K]$.
    """
    if not lane:
        return []
    if k_bins <= 0:
        raise ValueError(f"k_bins must be positive, got {k_bins}")
    lo = min(lane)
    hi = max(lane)
    span = hi - lo
    if span <= 0:
        return [0 for _ in lane]
    return [((v - lo) * k_bins) // span for v in lane]


def apply_vantage(name: str, lane: Sequence[int], **kwargs: int) -> list[int]:
    r"""Apply a named vantage transformation to a sequence.

    Mathematics:
    Computes $y = V_{\text{name}}(x)$ under parameterized configuration $\theta$.

    Supported names:
    - `"stride"`: Stride decimation with parameter `k` (default 2).
    - `"difference"`: First difference operator.
    - `"integrate"`: Cumulative prefix sum with parameter `seed` (default 0).
    - `"origin"`: Zero-centering by initial element.
    - `"modulus"`: Ring projection with parameter `m`.
    - `"fold"`: Quantization with parameter `k_bins` (default 64).

    Args:
        name: Name of the transform.
        lane: Input sequence of integers.
        **kwargs: Optional keyword parameters for transforms (`k`, `seed`, `m`, `k_bins`).

    Returns:
        Transformed list of integers.
    """
    if name == "stride":
        k = kwargs.get("k", 2)
        return vp_stride(lane, k=k)
    if name == "difference":
        return vp_difference(lane)
    if name == "integrate":
        seed = kwargs.get("seed", 0)
        return vp_integrate(lane, seed=seed)
    if name == "origin":
        return vp_origin(lane)
    if name == "modulus":
        m = kwargs.get("m")
        return vp_modulus(lane, m=m)
    if name == "fold":
        k_bins = kwargs.get("k_bins", 64)
        return vp_fold(lane, k_bins=k_bins)
    raise ValueError(f"unknown vantage transform {name!r}")
