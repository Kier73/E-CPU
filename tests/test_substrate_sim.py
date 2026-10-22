r"""Unit tests for deterministic WAN substrate simulation and benchmark harness.

Mathematics:
Verifies formal invariants across the network simulation harness:
- Gilbert-Elliott 2-state Markov burst erasure process
- Gaussian jitter latency sampling and minimum delay bounds
- Delay loop circulation, erasure detection, and slot revival
- Cadence timing channel modulation and bit error rate under network jitter
"""

from __future__ import annotations

import math
import pytest

from mailcpu.delay_loop import DelayGroup, DelayLoopEngine, DelaySlot
from mailcpu.substrate_sim import (
    GilbertElliottChannel,
    NetworkStats,
    WanSubstrateSimulator,
)
from mailcpu.timing_channel import (
    CadenceDemodulator,
    CadenceModulator,
    TimingChannelConfig,
)


def test_gilbert_elliott_channel_transitions() -> None:
    r"""Test 2-state Markov chain transitions and loss rate bounds.

    Mathematics:
    Stationary loss probability satisfies $\bar{P} = \pi_G p_G + \pi_B p_B$.
    """
    channel = GilbertElliottChannel(
        p_g_to_b=0.1,
        p_b_to_g=0.5,
        loss_in_good=0.0,
        loss_in_bad=1.0,
        seed=123,
    )

    drops = 0
    total = 500
    for _ in range(total):
        if channel.should_drop():
            drops += 1

    loss_rate = drops / total
    # Expected stationary bad state fraction is 0.1 / (0.1 + 0.5) = 1/6 ~= 0.166
    assert 0.05 < loss_rate < 0.35


def test_wan_simulator_rtt_and_jitter() -> None:
    r"""Test Gaussian RTT distribution and minimum latency clamping."""
    sim = WanSubstrateSimulator(mean_rtt_ms=40.0, jitter_sigma_ms=5.0, seed=42)

    rtts = [sim.sample_rtt() for _ in range(200)]
    mean_rtt = sum(rtts) / len(rtts)

    assert math.isclose(mean_rtt, 40.0, rel_tol=0.1)
    # Check lower clamp bound
    assert all(r >= 10.0 for r in rtts)


def test_wan_datagram_transmission() -> None:
    r"""Test packet delivery and drop tracking in the simulator."""
    sim = WanSubstrateSimulator(mean_rtt_ms=30.0, jitter_sigma_ms=2.0, seed=77)

    for i in range(100):
        delivered, arrival = sim.transmit(b"test-datagram", send_time_ms=i * 10.0)
        assert arrival > i * 10.0

    assert sim.stats.packets_sent == 100
    assert sim.stats.packets_delivered + sim.stats.packets_dropped == 100
    assert sim.stats.loss_rate >= 0.0
    assert sim.stats.mean_latency_ms > 0.0
    assert sim.stats.jitter_std_ms >= 0.0


def test_delay_loop_circulation_benchmark() -> None:
    r"""Test delay loop scrubbing under simulated WAN burst erasures.

    Mathematics:
    Every reported recovery must preserve the encoded value, so
    `verified_recoveries <= attempted_recoveries` and
    `read_group(group_id) = initial_value` after each successful scrub.
    """
    sim = WanSubstrateSimulator(mean_rtt_ms=20.0, jitter_sigma_ms=2.0, seed=99)
    engine = DelayLoopEngine()
    group = engine.add_group(value=12345, k=2, moduli=(257, 263, 269, 271))

    results = sim.benchmark_delay_loop_circulation(group, rounds=15)
    assert results["rounds"] == 15.0
    assert results["erasure_events"] >= 0.0
    assert results["verified_recoveries"] <= results["attempted_recoveries"]
    if not group.is_lost:
        recovered, ok = engine.read_group(group.group_id)
        assert ok is True
        assert recovered == group.initial_value


def test_delay_loop_benchmark_preserves_slot_identity_and_value() -> None:
    r"""Test deterministic erasures against exact RRNS reconstruction.

    Mathematics:
    For each round, three of five residues reconstruct
    `V = CRT({(m_i, V mod m_i)})`; every revived slot keeps its identity and
    receives `V mod m_i`, so the group remains equal to `V`.
    """
    sim = WanSubstrateSimulator(mean_rtt_ms=20.0, jitter_sigma_ms=0.0, seed=1)
    engine = DelayLoopEngine()
    group = engine.add_group(value=50000, k=3, moduli=(199, 197, 193, 191, 181))
    original_ids = tuple(slot.slot_id for slot in group.slots)
    drop_pattern = iter(([False, True, False, False, False] * 3))
    sim.channel.should_drop = drop_pattern.__next__

    results = sim.benchmark_delay_loop_circulation(group, rounds=3)

    assert results["attempted_recoveries"] == 3.0
    assert results["verified_recoveries"] == 3.0
    assert results["scrub_recoveries"] == 3.0
    assert results["verification_failures"] == 0.0
    assert tuple(slot.slot_id for slot in group.slots) == original_ids
    assert all(slot.residue == group.initial_value % slot.modulus for slot in group.slots)
    recovered, ok = engine.read_group(group.group_id)
    assert ok is True
    assert recovered == group.initial_value


def test_timing_channel_wan_benchmark() -> None:
    r"""Test cadence modulation and demodulation under simulated WAN jitter."""
    cfg = TimingChannelConfig(base_delay_ms=50.0, quantum_ms=25.0)
    modulator = CadenceModulator(config=cfg)
    demodulator = CadenceDemodulator(config=cfg)

    # Moderate jitter link: sigma = 2ms (< delta / 3 = 8.3ms)
    sim = WanSubstrateSimulator(mean_rtt_ms=30.0, jitter_sigma_ms=2.0, seed=101)

    message = b"WAN-Test"
    res = sim.benchmark_timing_channel(modulator, demodulator, message)

    assert res["bytes_sent"] == len(message)
    assert res["recovered_bytes"] == len(message)
    # Under low jitter, BER should be 0.0
    assert res["ber"] == 0.0
