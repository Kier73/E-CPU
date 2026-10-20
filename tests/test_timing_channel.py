from __future__ import annotations

import random
import pytest

from mailcpu.timing_channel import (
    CadenceDemodulator,
    CadenceModulator,
    TimingChannelConfig,
)


def test_cadence_modulation_and_demodulation_exact() -> None:
    r"""Mathematics: in the noiseless channel `Y = X`, demodulation recovers exact byte vector `D(M(b)) = b`."""

    config = TimingChannelConfig(base_delay_ms=25.0, quantum_ms=5.0, bits_per_symbol=4)
    modulator = CadenceModulator(config)
    demodulator = CadenceDemodulator(config)

    payload = b"MailCPU_Substrate"
    delays = modulator.encode_bytes(payload)
    assert len(delays) == len(payload) * 2

    recovered = demodulator.decode_intervals(delays)
    assert recovered == payload


def test_timing_channel_resilience_to_gaussian_jitter() -> None:
    r"""Mathematics: for Gaussian jitter `\sigma < \frac{\delta}{3}`, symbol decision boundaries `\Delta t \pm \frac{\delta}{2}` maintain zero error rate."""

    random.seed(42)
    config = TimingChannelConfig(base_delay_ms=20.0, quantum_ms=6.0, bits_per_symbol=4)
    modulator = CadenceModulator(config)
    demodulator = CadenceDemodulator(config)

    payload = b"QuantumTiming123"
    ideal_delays = modulator.encode_bytes(payload)

    # Inject jitter with sigma = 1.0 ms (< quantum / 4)
    noisy_delays = [d + random.gauss(0.0, 1.0) for d in ideal_delays]

    recovered = demodulator.decode_intervals(noisy_delays)
    assert recovered == payload


def test_pll_baseline_drift_tracking() -> None:
    r"""Mathematics: Phase-Locked Loop steers `\hat{\Delta}_0` to follow slow network routing baseline shifts."""

    config = TimingChannelConfig(base_delay_ms=20.0, quantum_ms=8.0, bits_per_symbol=4, pll_alpha=0.1)
    modulator = CadenceModulator(config)
    demodulator = CadenceDemodulator(config)

    # Stream of 40 bytes with baseline shifting from 20ms to 30ms linearly
    payload = b"ABCDEFGHIJ" * 4
    delays = modulator.encode_bytes(payload)

    drifted_delays: list[float] = []
    total_samples = len(delays)
    for idx, d in enumerate(delays):
        drift = 10.0 * (idx / total_samples)
        drifted_delays.append(d + drift)

    recovered = demodulator.decode_intervals(drifted_delays)
    assert recovered == payload
    # Verify that tracked base has adjusted toward 30ms
    assert demodulator.tracked_base_ms > 25.0
