r"""Non-Abelian Wilczek-Zee holonomy engine and geometric consensus coordinator.

Mathematics:
Let $\mathcal{H}_0$ be a 4-fold degenerate ground subspace of a multi-level quantum
or topological system governed by parameter coordinates $\Omega \in S^2 \subset \mathbb{R}^3$.
For closed loops traced adiabatically on the parameter 2-sphere enclosing solid angle
$\Omega_{\text{solid}}$, the non-Abelian Wilczek-Zee connection generates an $\text{SU}(2)$
geometric phase unitary on the active dark subspace:
\[
U(\mathbf{n}, \chi) = \exp(-i \chi (\mathbf{n} \cdot \boldsymbol{\sigma})) = \cos(\chi) I_2 - i \sin(\chi) (n_x \sigma_x + n_y \sigma_y + n_z \sigma_z)
\]
where $\boldsymbol{\sigma} = (\sigma_x, \sigma_y, \sigma_z)$ are the Pauli spin matrices,
$\mathbf{n} \in S^2$ is the rotation axis, and $\chi = \frac{1}{2} \Omega_{\text{solid}}$.

In distributed execution, geometric holonomies are gauge-invariant under smooth
time-reparameterizations $t \mapsto f(t)$, isolating consensus coordinates from
packet latency jitter and transmission route variations:
\[
d(U_1, U_2) = \sqrt{\max\left(0, 2 - \text{Re}(\text{Tr}(U_1^\dagger U_2))\right)}
\]
Consensus holds across $N$ nodes iff $\max_{i < j} d(U_i, U_j) < \epsilon_{\text{consensus}}$.
"""

from __future__ import annotations

import math
from typing import Sequence

Matrix2x2 = tuple[tuple[complex, complex], tuple[complex, complex]]

# Standard Pauli matrices
SIGMA_X: Matrix2x2 = ((0.0 + 0.0j, 1.0 + 0.0j), (1.0 + 0.0j, 0.0 + 0.0j))
SIGMA_Y: Matrix2x2 = ((0.0 + 0.0j, 0.0 - 1.0j), (0.0 + 1.0j, 0.0 + 0.0j))
SIGMA_Z: Matrix2x2 = ((1.0 + 0.0j, 0.0 + 0.0j), (0.0 + 0.0j, -1.0 + 0.0j))
IDENTITY_2: Matrix2x2 = ((1.0 + 0.0j, 0.0 + 0.0j), (0.0 + 0.0j, 1.0 + 0.0j))


def mat_mul2(a: Matrix2x2, b: Matrix2x2) -> Matrix2x2:
    r"""Multiply two $2 \times 2$ complex matrices.

    Mathematics:
    \[
    C_{ij} = \sum_{k=0}^1 A_{ik} B_{kj}
    \]

    Args:
        a: First $2 \times 2$ matrix.
        b: Second $2 \times 2$ matrix.

    Returns:
        Product matrix $A B$.
    """
    return (
        (
            a[0][0] * b[0][0] + a[0][1] * b[1][0],
            a[0][0] * b[0][1] + a[0][1] * b[1][1],
        ),
        (
            a[1][0] * b[0][0] + a[1][1] * b[1][0],
            a[1][0] * b[0][1] + a[1][1] * b[1][1],
        ),
    )


def mat_adjoint2(a: Matrix2x2) -> Matrix2x2:
    r"""Compute the conjugate transpose $A^\dagger$ of a $2 \times 2$ matrix.

    Mathematics:
    \[
    (A^\dagger)_{ij} = \overline{A_{ji}}
    \]

    Args:
        a: Complex $2 \times 2$ matrix.

    Returns:
        Adjoint matrix $A^\dagger$.
    """
    return (
        (a[0][0].conjugate(), a[1][0].conjugate()),
        (a[0][1].conjugate(), a[1][1].conjugate()),
    )


def mat_trace2(a: Matrix2x2) -> complex:
    r"""Mathematics: compute `Tr(A) = A[0][0] + A[1][1]` for a 2-by-2 matrix."""
    return a[0][0] + a[1][1]


def make_su2_unitary(axis: tuple[float, float, float], chi: float) -> Matrix2x2:
    r"""Construct an $\text{SU}(2)$ Wilczek-Zee unitary $U(\mathbf{n}, \chi)$.

    Mathematics:
    \[
    U = \cos(\chi) I_2 - i \sin(\chi) (n_x \sigma_x + n_y \sigma_y + n_z \sigma_z)
    \]
    Normalizes rotation axis $\mathbf{n}$ such that $\|\mathbf{n}\|_2 = 1$.

    Args:
        axis: 3D rotation axis $(n_x, n_y, n_z) \in \mathbb{R}^3$.
        chi: Enclosed solid angle phase parameter $\chi \in \mathbb{R}$.

    Returns:
        Exact $2 \times 2$ unitary matrix with $\det(U) = 1$.
    """
    nx, ny, nz = axis
    norm = math.sqrt(nx * nx + ny * ny + nz * nz)
    if norm < 1e-15:
        # Default to z-axis on degenerate zero vector
        nx, ny, nz = 0.0, 0.0, 1.0
    else:
        nx, ny, nz = nx / norm, ny / norm, nz / norm

    cos_c = math.cos(chi)
    sin_c = math.sin(chi)

    # Matrix elements
    # u00 = cos(chi) - i sin(chi) nz
    # u01 = -i sin(chi) (nx - i ny) = -sin(chi) ny - i sin(chi) nx
    # u10 = -i sin(chi) (nx + i ny) = sin(chi) ny - i sin(chi) nx
    # u11 = cos(chi) + i sin(chi) nz
    u00 = complex(cos_c, -sin_c * nz)
    u01 = complex(-sin_c * ny, -sin_c * nx)
    u10 = complex(sin_c * ny, -sin_c * nx)
    u11 = complex(cos_c, sin_c * nz)

    return ((u00, u01), (u10, u11))


def compute_loop_solid_angle(trajectory: Sequence[tuple[float, float]]) -> float:
    r"""Compute the solid angle $\Omega_{\text{solid}}$ enclosed by a closed spherical path.

    Mathematics:
    Given closed path $(\theta_k, \phi_k)_{k=0}^{M-1}$ on $S^2$:
    \[
    \Omega_{\text{solid}} = \sum_{k=0}^{M-1} (1 - \cos\theta_k) \cdot \Delta \phi_k \pmod{4\pi}
    \]
    where $\Delta \phi_k \in [-\pi, \pi)$ is the shortest angular difference.

    Args:
        trajectory: Sequence of spherical coordinates $(\theta, \phi)$ with $\theta \in [0, \pi], \phi \in [0, 2\pi)$.

    Returns:
        Enclosed solid angle in radians.
    """
    n = len(trajectory)
    if n < 3:
        return 0.0
    total_omega = 0.0
    for k in range(n):
        th_k, ph_k = trajectory[k]
        _, ph_next = trajectory[(k + 1) % n]
        d_phi = (ph_next - ph_k + math.pi) % (2.0 * math.pi) - math.pi
        total_omega += (1.0 - math.cos(th_k)) * d_phi
    return total_omega


def unitary_frobenius_distance(u1: Matrix2x2, u2: Matrix2x2) -> float:
    r"""Compute the gauge-invariant distance between two $\text{SU}(2)$ unitaries.

    Mathematics:
    \[
    d(U_1, U_2) = \sqrt{\max\left(0.0, \; 2 - \text{Re}(\text{Tr}(U_1^\dagger U_2))\right)}
    \]
    Returns $0.0$ when $U_1 = U_2$ and reaches maximum $2.0$ for orthogonal antipodal unitaries.

    Args:
        u1: First unitary matrix.
        u2: Second unitary matrix.

    Returns:
        Distance metric in $[0.0, 2.0]$.
    """
    prod = mat_mul2(mat_adjoint2(u1), u2)
    tr = mat_trace2(prod)
    val = max(0.0, 2.0 - tr.real)
    return math.sqrt(val)


class HolonomyConsensus:
    r"""Multi-node geometric consensus coordinator based on Wilczek-Zee holonomies.

    Mathematics:
    Aggregates geometric phase unitaries $\{U_i\}_{i=1}^N$ submitted by distributed
    nodes executing independent trajectory traversals. Nodes achieve consensus iff
    all pairwise distances satisfy:
    \[
    \max_{i < j} d(U_i, U_j) < \epsilon_{\text{consensus}}
    \]
    """

    def __init__(self, tolerance: float = 1e-4) -> None:
        r"""Initialize the consensus coordinator with an allowable distance tolerance.

        Args:
            tolerance: Maximum allowable Frobenius distance $\epsilon_{\text{consensus}}$.
        """
        self.tolerance = tolerance
        self._nodes: dict[str, Matrix2x2] = {}

    def register_node_unitary(self, node_id: str, u: Matrix2x2) -> None:
        r"""Register a geometric phase unitary for a distributed node.

        Mathematics: update the node map as `N' = N union {node_id -> u}`.

        Args:
            node_id: Unique node identifier.
            u: Submitted $2 \times 2$ $\text{SU}(2)$ unitary matrix.
        """
        self._nodes[node_id] = u

    def node_count(self) -> int:
        r"""Mathematics: return `|dom(N)|`, the cardinality of the node map."""
        return len(self._nodes)

    def max_pairwise_distance(self) -> float:
        r"""Mathematics: calculate `max_{i<j} d(U_i, U_j)`, or 0 for fewer than two nodes."""
        items = list(self._nodes.values())
        if len(items) < 2:
            return 0.0
        max_d = 0.0
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                d = unitary_frobenius_distance(items[i], items[j])
                if d > max_d:
                    max_d = d
        return max_d

    def is_in_consensus(self) -> bool:
        r"""Mathematics: return 1 exactly when `max_{i<j} d(U_i, U_j) <= tolerance`."""
        if len(self._nodes) < 2:
            return True
        return self.max_pairwise_distance() <= self.tolerance

    def consensus_centroid(self) -> Matrix2x2:
        r"""Calculate the normalized Fréchet mean unitary on $\text{SU}(2)$.

        Mathematics:
        Averages elements $M = \frac{1}{N} \sum_{i=1}^N U_i$ and projects $M$
        back onto $\text{SU}(2)$ via determinant normalization:
        \[
        U^* = \frac{M}{\sqrt{\det(M)}}
        \]

        Returns:
            Mean consensus unitary matrix in $\text{SU}(2)$.
        """
        if not self._nodes:
            return IDENTITY_2
        n = len(self._nodes)
        s00 = sum(u[0][0] for u in self._nodes.values()) / n
        s01 = sum(u[0][1] for u in self._nodes.values()) / n
        s10 = sum(u[1][0] for u in self._nodes.values()) / n
        s11 = sum(u[1][1] for u in self._nodes.values()) / n

        det = s00 * s11 - s01 * s10
        norm = math.sqrt(abs(det)) if abs(det) > 1e-15 else 1.0
        scale = complex(1.0 / norm, 0.0)

        return (
            (s00 * scale, s01 * scale),
            (s10 * scale, s11 * scale),
        )
