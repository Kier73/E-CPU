r"""Unit tests for chemical time, persistence horizons, and Wilczek-Zee holonomies.

Mathematics:
Verifies formal invariants across the tripartite temporal framework:
- Shannon entropy and Lempel-Ziv parsing difficulty metrics
- Difficulty-as-currency memory quota and delay-loop retention scaling
- Horizon guard enforcement ($t < t_{\text{horizon}} = \text{first\_bad}$)
- Tripartite SystemEpoch coordinate evolution $\langle \lambda, \tau_{\text{chronon}}, \tau_{\text{chem}} \rangle$
- SU(2) Wilczek-Zee geometric phase unitaries, solid angles, and multi-node consensus
"""

from __future__ import annotations

import math
import pytest

from mailcpu.chemical_time import (
    HorizonTracker,
    SystemEpoch,
    calculate_difficulty_quota,
    calculate_retention_delay,
    compute_chemical_difficulty,
    gzip_compressed_bits,
    shannon_entropy,
)
from mailcpu.holonomy_engine import (
    IDENTITY_2,
    HolonomyConsensus,
    compute_loop_solid_angle,
    make_su2_unitary,
    mat_adjoint2,
    mat_mul2,
    unitary_frobenius_distance,
)
from mailcpu.law_certifier import HorizonExceeded


def test_shannon_entropy_properties() -> None:
    r"""Test mathematical bounds and properties of Shannon entropy.

    Mathematics:
    \[
    H(X) = -\sum_x p(x) \log_2 p(x)
    \]
    """
    # Deterministic sequence: 0 entropy
    assert shannon_entropy([5, 5, 5, 5, 5]) == 0.0

    # Uniform binary distribution: 1.0 bit
    binary_seq = [0, 1] * 50
    assert math.isclose(shannon_entropy(binary_seq), 1.0, rel_tol=1e-5)

    # 4 uniform symbols: 2.0 bits
    quad_seq = [0, 1, 2, 3] * 25
    assert math.isclose(shannon_entropy(quad_seq), 2.0, rel_tol=1e-5)


def test_gzip_compression_bits() -> None:
    r"""Test Lempel-Ziv compression response to repetitive vs diverse sequences."""
    repetitive = [42] * 200
    diverse = list(range(200))

    bits_rep = gzip_compressed_bits(repetitive)
    bits_div = gzip_compressed_bits(diverse)

    assert bits_rep > 0
    assert bits_div > bits_rep


def test_chemical_difficulty_ranking() -> None:
    r"""Test that chemical parsing difficulty ranks streams by structural complexity."""
    constant_stream = [7] * 50
    linear_stream = list(range(50))
    chaotic_stream = [(16807 * i + 3) % 2147483647 for i in range(50)]

    diff_const = compute_chemical_difficulty(constant_stream)
    diff_linear = compute_chemical_difficulty(linear_stream)
    diff_chaotic = compute_chemical_difficulty(chaotic_stream)

    assert diff_const < diff_linear
    assert diff_linear < diff_chaotic


def test_difficulty_as_currency_and_retention() -> None:
    r"""Test difficulty-as-currency memory quota and retention delay scaling.

    Mathematics:
    \[
    Q = \lfloor Q_0 \cdot (1 + \alpha \log(1 + \tau)) \rfloor, \quad t_{\text{ret}} = t_0 \cdot (1 + \beta \tau)
    \]
    """
    base_quota = 65536
    base_delay = 100.0

    quota_low = calculate_difficulty_quota(0.5, base_quota=base_quota)
    quota_high = calculate_difficulty_quota(10.0, base_quota=base_quota)
    assert quota_high > quota_low >= base_quota

    delay_low = calculate_retention_delay(0.5, base_delay_ms=base_delay)
    delay_high = calculate_retention_delay(10.0, base_delay_ms=base_delay)
    assert delay_high > delay_low >= base_delay

    with pytest.raises(ValueError):
        calculate_difficulty_quota(-1.0)


def test_horizon_tracker() -> None:
    r"""Test that HorizonTracker guards validity and raises HorizonExceeded on breach."""
    tracker = HorizonTracker(task_id=1, t_horizon=25, family="lcg")

    assert tracker.is_valid_coordinate(0)
    assert tracker.is_valid_coordinate(24)
    assert not tracker.is_valid_coordinate(25)
    assert not tracker.is_valid_coordinate(30)

    # Valid step
    tracker.assert_valid(20)

    # Exceeded horizon
    with pytest.raises(HorizonExceeded) as exc_info:
        tracker.assert_valid(25)
    assert "exceeding certified horizon" in str(exc_info.value)

    # Unbounded horizon
    unbounded = HorizonTracker(task_id=2, t_horizon=None)
    assert unbounded.is_valid_coordinate(10000)
    unbounded.assert_valid(10000)


def test_system_epoch_advancement() -> None:
    r"""Test tripartite SystemEpoch progression across event, chronon, and chemical dimensions."""
    epoch0 = SystemEpoch(event_lambda=0, chronon_phase=1 + 0j, chemical_tau=0.0)

    # Event advance
    epoch1 = epoch0.advance_event()
    assert epoch1.event_lambda == 1
    assert epoch1.chronon_phase == 1 + 0j

    # Chronon advance with 1 active bit: factor is (-i)^1 = -1j
    epoch2 = epoch1.advance_chronon(1)
    assert epoch2.chronon_phase == -1j

    # Chronon advance with 2 active bits: factor is (-i)^2 = -1
    epoch3 = epoch2.advance_chronon(2)
    assert epoch3.chronon_phase == 1j

    # Chemical difficulty accumulation
    epoch4 = epoch3.add_chemical_difficulty(2.5)
    assert epoch4.chemical_tau == 2.5
    assert epoch4.event_lambda == 1


def test_su2_wilczek_zee_unitary_group() -> None:
    r"""Test that make_su2_unitary constructs exact SU(2) matrices with U^dag U = I and det(U) = 1."""
    axis = (1.0, 2.0, -1.0)
    chi = 0.785398  # pi / 4

    u = make_su2_unitary(axis, chi)

    # Determinant = u00 * u11 - u01 * u10
    det = u[0][0] * u[1][1] - u[0][1] * u[1][0]
    assert math.isclose(det.real, 1.0, rel_tol=1e-5)
    assert math.isclose(det.imag, 0.0, abs_tol=1e-5)

    # Unitary: U^dag U = I
    u_dag = mat_adjoint2(u)
    prod = mat_mul2(u_dag, u)
    assert math.isclose(prod[0][0].real, 1.0, rel_tol=1e-5)
    assert math.isclose(prod[1][1].real, 1.0, rel_tol=1e-5)
    assert math.isclose(abs(prod[0][1]), 0.0, abs_tol=1e-5)
    assert math.isclose(abs(prod[1][0]), 0.0, abs_tol=1e-5)


def test_spherical_loop_solid_angle() -> None:
    r"""Test solid angle calculation for a circular trajectory around the north pole."""
    # Circle at theta = pi/3 (60 degrees) spanning full 2*pi in phi
    # Enclosed solid angle is 2*pi*(1 - cos(theta)) = 2*pi*(1 - 0.5) = pi
    n_points = 100
    traj = [
        (math.pi / 3.0, (2.0 * math.pi * k) / n_points)
        for k in range(n_points)
    ]
    omega = compute_loop_solid_angle(traj)
    assert math.isclose(omega, math.pi, rel_tol=1e-2)


def test_unitary_frobenius_distance() -> None:
    r"""Test Frobenius gauge-invariant distance between unitaries."""
    u1 = make_su2_unitary((0, 0, 1), 0.5)
    u2 = make_su2_unitary((0, 0, 1), 0.5)
    u3 = make_su2_unitary((0, 0, 1), 1.5)

    # Identical unitaries: distance is 0.0
    assert math.isclose(unitary_frobenius_distance(u1, u2), 0.0, abs_tol=1e-6)

    # Different unitaries: distance > 0
    d13 = unitary_frobenius_distance(u1, u3)
    assert d13 > 0.0

    # Symmetry
    assert math.isclose(unitary_frobenius_distance(u1, u3), unitary_frobenius_distance(u3, u1), rel_tol=1e-6)


def test_holonomy_consensus_agreement_and_divergence() -> None:
    r"""Test multi-node consensus tracking and divergence detection."""
    consensus = HolonomyConsensus(tolerance=1e-3)

    # Three nodes agreeing on trajectory parameter chi = 0.5 along z-axis
    u_agree1 = make_su2_unitary((0, 0, 1), 0.5)
    u_agree2 = make_su2_unitary((0, 0, 1), 0.50001)
    u_agree3 = make_su2_unitary((0, 0, 1), 0.49999)

    consensus.register_node_unitary("node-1", u_agree1)
    consensus.register_node_unitary("node-2", u_agree2)
    consensus.register_node_unitary("node-3", u_agree3)

    assert consensus.node_count() == 3
    assert consensus.is_in_consensus()

    # Register divergent Byzantine node
    u_divergent = make_su2_unitary((1, 0, 0), 1.2)
    consensus.register_node_unitary("node-4", u_divergent)

    assert not consensus.is_in_consensus()
    assert consensus.max_pairwise_distance() > 0.5

    # Fréchet mean centroid
    centroid = consensus.consensus_centroid()
    det_c = centroid[0][0] * centroid[1][1] - centroid[0][1] * centroid[1][0]
    assert math.isclose(abs(det_c), 1.0, rel_tol=1e-4)


def test_scheduler_chemical_time_and_horizon_integration() -> None:
    r"""Test DeterministicScheduler evolution of SystemEpoch and HorizonTracker enforcement."""
    from mailcpu.assembler import assemble
    from mailcpu.bus import MailboxBus
    from mailcpu.journal import EventJournal
    from mailcpu.scheduler import DeterministicScheduler

    source = """
    SET R1, 10
    SET R2, 20
    ADD R1, R1, R2
    HALT
    """
    program = assemble(source)
    scheduler = DeterministicScheduler()

    # Add task with chemical cost, chronofold, and horizon at step 2
    pid = scheduler.add(
        program,
        name="test_worker",
        enable_chronofold=True,
        chemical_cost=1.5,
        t_horizon=2,
    )

    # Step 0 (LOAD R1, 10)
    scheduler.run(max_ticks=1)
    assert scheduler.system_epoch.event_lambda == 1
    assert scheduler.system_epoch.chemical_tau == 1.5
    assert scheduler.tasks[pid].state.steps == 1

    # Step 1 (LOAD R2, 20)
    scheduler.run(max_ticks=2)
    assert scheduler.system_epoch.event_lambda == 2
    assert scheduler.system_epoch.chemical_tau == 3.0
    assert scheduler.tasks[pid].state.steps == 2

    # Step 2 attempts to exceed t_horizon = 2
    with pytest.raises(HorizonExceeded):
        scheduler.run(max_ticks=3)

    # Test snapshot serialization and restoration of SystemEpoch and task horizon
    snap = scheduler.snapshot()
    assert "system_epoch" in snap
    assert snap["system_epoch"]["chemical_tau"] == 3.0

    restored = DeterministicScheduler.from_snapshot(
        snap,
        bus=MailboxBus(),
        journal=EventJournal(),
    )
    assert restored.system_epoch.event_lambda == 2
    assert restored.system_epoch.chemical_tau == 3.0
    assert restored.tasks[pid].chemical_cost == 1.5
    assert restored.tasks[pid].horizon_tracker is not None
    assert restored.tasks[pid].horizon_tracker.t_horizon == 2

