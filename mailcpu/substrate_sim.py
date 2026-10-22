r"""Deterministic Wide-Area Network (WAN) substrate simulation harness.

Mathematics:
Simulates physical transmission media (delay loops, timing channels, DNS probes)
under controllable network impairments:
1. RTT Latency with Gaussian Jitter:
   \[
   \text{RTT}_k \sim \max\left(\frac{\mu_{\text{rtt}}}{4}, \; \mu_{\text{rtt}} + \mathcal{N}(0, \sigma^2_{\text{jitter}})\right)
   \]
2. Gilbert-Elliott 2-State Markov Burst Loss Model:
   State space $\mathcal{S} = \{G, B\}$ with transition matrix:
   \[
   P = \begin{pmatrix} 1 - p & p \\ q & 1 - q \end{pmatrix}
   \]
   where $p = P(G \to B)$ is the probability of entering a burst loss state,
   $q = P(B \to G)$ is the recovery probability, and packet loss probabilities
   satisfy $P(\text{loss} \mid G) = p_G \ll P(\text{loss} \mid B) = p_B$.
   Stationary probability of the bad state is $\pi_B = \frac{p}{p + q}$.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Sequence

from mailcpu.delay_loop import DelayGroup, DelaySlot
from mailcpu.rrns import recover_rrns
from mailcpu.timing_channel import CadenceDemodulator, CadenceModulator


@dataclass
class NetworkStats:
    r"""Empirical performance metrics captured during substrate simulation.

    Mathematics:
    Records transmitted packets $N_{\text{tx}}$, dropped packets $N_{\text{drop}}$,
    loss fraction $\frac{N_{\text{drop}}}{N_{\text{tx}}}$, and mean latency $\bar{\mu}$.
    """

    packets_sent: int = 0
    packets_delivered: int = 0
    packets_dropped: int = 0
    mean_latency_ms: float = 0.0
    jitter_std_ms: float = 0.0

    @property
    def loss_rate(self) -> float:
        r"""Mathematics: compute `packets_dropped / packets_sent`, or 0 when the denominator is zero."""
        if self.packets_sent == 0:
            return 0.0
        return self.packets_dropped / self.packets_sent


class GilbertElliottChannel:
    r"""Two-state Gilbert-Elliott Markov chain model for burst packet erasure.

    Mathematics:
    Models temporal correlations in network packet loss. State transitions occur
    per-packet evaluation:
    - Good state ($G$): low independent drop probability $p_G$.
    - Bad state ($B$): high burst drop probability $p_B$.
    """

    def __init__(
        self,
        p_g_to_b: float = 0.05,
        p_b_to_g: float = 0.30,
        loss_in_good: float = 0.005,
        loss_in_bad: float = 0.60,
        seed: int = 42,
    ) -> None:
        r"""Initialize the channel with transition and loss probabilities.

        Args:
            p_g_to_b: Probability of transitioning from Good to Bad ($p$).
            p_b_to_g: Probability of recovering from Bad to Good ($q$).
            loss_in_good: Loss probability in Good state ($p_G$).
            loss_in_bad: Loss probability in Bad state ($p_B$).
            seed: Deterministic random seed for reproducibility.
        """
        self.p = p_g_to_b
        self.q = p_b_to_g
        self.p_g = loss_in_good
        self.p_b = loss_in_bad
        self.state = "G"
        self._rng = random.Random(seed)

    def should_drop(self) -> bool:
        r"""Advance the Markov chain state by one packet and determine if it is dropped.

        Mathematics:
        Transitions state with probability $P(\text{next} \mid \text{current})$, then
        evaluates Bernoulli trial with parameter $p_{\text{state}}$.

        Returns:
            True if the packet is dropped, False if delivered.
        """
        # State transition
        if self.state == "G":
            if self._rng.random() < self.p:
                self.state = "B"
        else:
            if self._rng.random() < self.q:
                self.state = "G"

        # Packet drop evaluation
        drop_prob = self.p_b if self.state == "B" else self.p_g
        return self._rng.random() < drop_prob


class WanSubstrateSimulator:
    r"""Deterministic Wide-Area Network substrate simulation harness.

    Mathematics:
    Emulates physical delay line propagation, Gaussian jitter latency shifts,
    and Gilbert-Elliott burst erasures over simulated network substrates.
    """

    def __init__(
        self,
        mean_rtt_ms: float = 50.0,
        jitter_sigma_ms: float = 4.0,
        channel: GilbertElliottChannel | None = None,
        seed: int = 42,
    ) -> None:
        r"""Initialize the WAN simulator with latency distribution and loss channel.

        Args:
            mean_rtt_ms: Baseline round-trip propagation time $\mu_{\text{rtt}}$.
            jitter_sigma_ms: Standard deviation of latency jitter $\sigma_{\text{jitter}}$.
            channel: Optional custom Gilbert-Elliott channel instance.
            seed: Deterministic random seed.
        """
        self.mean_rtt_ms = mean_rtt_ms
        self.jitter_sigma_ms = jitter_sigma_ms
        self.channel = channel or GilbertElliottChannel(seed=seed)
        self._rng = random.Random(seed)
        self.stats = NetworkStats()
        self._latencies: list[float] = []

    def sample_rtt(self) -> float:
        r"""Mathematics: sample `R ~ Normal(mu, sigma^2)` and return `max(mu/4, R)`."""
        val = self._rng.gauss(self.mean_rtt_ms, self.jitter_sigma_ms)
        return max(self.mean_rtt_ms * 0.25, val)

    def transmit(self, payload: bytes, send_time_ms: float) -> tuple[bool, float]:
        r"""Simulate datagram transmission across the wide-area network.

        Mathematics:
        Evaluates burst erasure and calculates arrival timestamp:
        \[
        t_{\text{arrival}} = t_{\text{send}} + \text{RTT}
        \]

        Args:
            payload: Transmitted byte buffer.
            send_time_ms: Send timestamp in milliseconds.

        Returns:
            Tuple of (delivered: bool, arrival_time_ms: float).
        """
        self.stats.packets_sent += 1
        dropped = self.channel.should_drop()
        rtt = self.sample_rtt()
        arrival_time = send_time_ms + rtt

        if dropped:
            self.stats.packets_dropped += 1
            return False, arrival_time

        self.stats.packets_delivered += 1
        self._latencies.append(rtt)
        self.stats.mean_latency_ms = sum(self._latencies) / len(self._latencies)
        if len(self._latencies) > 1:
            mean = self.stats.mean_latency_ms
            self.stats.jitter_std_ms = math.sqrt(
                sum((latency - mean) ** 2 for latency in self._latencies)
                / (len(self._latencies) - 1)
            )
        return True, arrival_time

    def benchmark_delay_loop_circulation(
        self,
        group: DelayGroup,
        rounds: int = 10,
    ) -> dict[str, float]:
        r"""Benchmark in-flight delay loop scrubbing under simulated WAN burst erasure.

        Mathematics:
        Simulates $R$ round trips of a redundant group of $N$ packets. In each round,
        surviving packets are gathered, and if $k \le \text{surviving} < N$, the
        group is scrubbed to revive lost packets. A recovery is counted only when
        `recover_rrns` is consistent and reconstructs `group.initial_value` exactly.
        If surviving $< k$, loss is permanent.

        Args:
            group: Redundant `DelayGroup` instance.
            rounds: Number of circulation passes.

        Returns:
            Dict containing attempted and verified recovery counts, loss counts,
            and the empirical network loss rate.
        """
        erasure_events = 0
        attempted_recoveries = 0
        verified_recoveries = 0
        verification_failures = 0
        permanent_losses = 0

        k_req = group.k

        for _ in range(rounds):
            if group.is_lost:
                break
            surviving: list[DelaySlot] = []
            for slot in group.slots:
                payload = slot.encode_payload()
                delivered, _ = self.transmit(payload, send_time_ms=0.0)
                slot.alive = delivered
                if delivered:
                    surviving.append(slot)

            if len(surviving) < len(group.slots):
                erasure_events += 1
                if len(surviving) >= k_req:
                    attempted_recoveries += 1
                    pairs = [(slot.modulus, slot.residue) for slot in surviving]
                    recovered, consistent = recover_rrns(pairs, k_req, group.moduli)
                    if not consistent or recovered is None or recovered != group.initial_value:
                        verification_failures += 1
                        group.bad_recon_count += 1
                        group.is_lost = True
                        break

                    for slot in group.slots:
                        if not slot.alive:
                            slot.alive = True
                            slot.version += 1
                            slot.residue = recovered % slot.modulus

                    read_pairs = [(slot.modulus, slot.residue) for slot in group.slots]
                    verified_value, read_ok = recover_rrns(read_pairs, k_req, group.moduli)
                    if not read_ok or verified_value != group.initial_value:
                        verification_failures += 1
                        group.bad_recon_count += 1
                        group.is_lost = True
                        break

                    verified_recoveries += 1
                    group.scrub_count += 1
                else:
                    permanent_losses += 1
                    group.is_lost = True
                    break

        return {
            "rounds": float(rounds),
            "erasure_events": float(erasure_events),
            "attempted_recoveries": float(attempted_recoveries),
            "verified_recoveries": float(verified_recoveries),
            "scrub_recoveries": float(verified_recoveries),
            "verification_failures": float(verification_failures),
            "permanent_losses": float(permanent_losses),
            "network_loss_rate": self.stats.loss_rate,
        }

    def benchmark_timing_channel(
        self,
        modulator: CadenceModulator,
        demodulator: CadenceDemodulator,
        message: bytes,
    ) -> dict[str, float]:
        r"""Benchmark discrete cadence modulation over a jittery network link.

        Mathematics:
        Modulates message into discrete time intervals $\Delta t$, adds stochastic
        propagation jitter $\mathcal{N}(0, \sigma^2)$, demodulates symbols, and
        computes the empirical Bit Error Rate (BER):
        \[
        \text{BER} = \frac{\text{bit\_errors}}{8 \cdot |M|}
        \]

        Args:
            modulator: `CadenceModulator` instance.
            demodulator: `CadenceDemodulator` instance.
            message: Byte buffer to transmit.

        Returns:
            Dict containing `bytes_sent`, `bit_errors`, and `ber`.
        """
        delays = modulator.encode_bytes(message)
        demod_intervals: list[float] = []

        for d in delays:
            jitter = self._rng.gauss(0.0, self.jitter_sigma_ms)
            interval = max(0.0, d + jitter)
            demod_intervals.append(interval)

        recovered = demodulator.decode_intervals(demod_intervals)

        # Count bit differences
        bit_errors = 0
        min_len = min(len(message), len(recovered))
        for i in range(min_len):
            diff = message[i] ^ recovered[i]
            bit_errors += diff.bit_count()
        bit_errors += abs(len(message) - len(recovered)) * 8

        total_bits = len(message) * 8
        ber = (bit_errors / total_bits) if total_bits > 0 else 0.0

        return {
            "bytes_sent": float(len(message)),
            "recovered_bytes": float(len(recovered)),
            "bit_errors": float(bit_errors),
            "ber": ber,
        }
