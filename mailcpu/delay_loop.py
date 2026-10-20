"""Physical network delay-line memory loops with RRNS Chinese Remainder Theorem scrubbing."""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field
from typing import Sequence

from .rrns import crt, legit_range, primes_below, recover_rrns

FRAME_HEADER_FORMAT: str = "!HHIQ"  # group_id (H), slot_pos (H), version (I), residue (Q)
FRAME_HEADER_SIZE: int = struct.calcsize(FRAME_HEADER_FORMAT)


@dataclass
class DelaySlot:
    r"""Mathematics: state of a single circulating packet slot `\langle \text{id}, g, p, m, v, r \rangle`."""

    slot_id: int
    group_id: int
    pos: int
    modulus: int
    version: int = 0
    residue: int = 0
    alive: bool = True
    sent_time: float = 0.0
    arrival_times: list[float] = field(default_factory=list)
    received_count: int = 0

    def encode_payload(self, total_len: int = 64) -> bytes:
        """Mathematics: serialize slot coordinates and residue into network byte order datagram."""

        header = struct.pack(FRAME_HEADER_FORMAT, self.group_id, self.pos, self.version, self.residue)
        return header.ljust(total_len, b"\0")

    @classmethod
    def decode_payload(cls, data: bytes) -> tuple[int, int, int, int]:
        """Mathematics: unpack `(group_id, slot_pos, version, residue)` from datagram header."""

        if len(data) < FRAME_HEADER_SIZE:
            raise ValueError("datagram shorter than frame header size")
        return struct.unpack(FRAME_HEADER_FORMAT, data[:FRAME_HEADER_SIZE])


@dataclass
class DelayGroup:
    """Mathematics: state group of `n` parallel coprime residue slots with `k`-of-`n` CRT recovery."""

    group_id: int
    kind: str  # 'single', 'noscrub', 'scrub'
    k: int
    moduli: tuple[int, ...]
    initial_value: int
    slots: list[DelaySlot] = field(default_factory=list)
    is_lost: bool = False
    scrub_count: int = 0
    bad_recon_count: int = 0


class DelayLoopEngine:
    r"""Mathematics: circulating packet delay-line memory manager implementing Bandwidth-Delay scaling `C = \sum B_p \cdot \text{RTT}_p` and RRNS erasure regeneration."""

    def __init__(
        self,
        nominal_rtt_s: float = 0.05,
        slot_clamping_factor: float = 3.0,
        packet_len: int = 64,
    ) -> None:
        """Mathematics: initialize loop engine with nominal RTT, jitter clamping multiplier, and frame size."""

        self.nominal_rtt_s = nominal_rtt_s
        self.slot_clamping_factor = slot_clamping_factor
        self.packet_len = packet_len
        self.groups: dict[int, DelayGroup] = {}
        self.slots_by_id: dict[int, DelaySlot] = {}
        self._next_group_id: int = 0
        self._next_slot_id: int = 1000

        self.measured_rtts: list[float] = []
        self.jitter_s: float = 0.001

    @property
    def slot_interval_s(self) -> float:
        r"""Mathematics: compute dynamic slot spacing `\Delta_{\text{slot}} = \max(1\,\text{ms}, \gamma \cdot \sigma_{\text{jitter}})`."""

        return max(0.001, self.slot_clamping_factor * self.jitter_s)

    def add_group(
        self,
        value: int,
        k: int,
        moduli: Sequence[int],
        kind: str = "scrub",
    ) -> DelayGroup:
        r"""Mathematics: encode `V \in [0, \prod_{i=1}^k m_i)` across `n = |moduli|` slots with residues `r_i = V \bmod m_i`."""

        gid = self._next_group_id
        self._next_group_id += 1

        moduli_tuple = tuple(moduli)
        group = DelayGroup(
            group_id=gid,
            kind=kind,
            k=k,
            moduli=moduli_tuple,
            initial_value=value,
        )

        for pos, mod in enumerate(moduli_tuple):
            slot_id = self._next_slot_id
            self._next_slot_id += 1
            slot = DelaySlot(
                slot_id=slot_id,
                group_id=gid,
                pos=pos,
                modulus=mod,
                version=0,
                residue=value % mod,
            )
            group.slots.append(slot)
            self.slots_by_id[slot_id] = slot

        self.groups[gid] = group
        return group

    def record_rtt(self, rtt: float) -> None:
        r"""Mathematics: update empirical jitter `\sigma_{\text{jitter}}` using incremental standard deviation."""

        self.measured_rtts.append(rtt)
        if len(self.measured_rtts) > 100:
            self.measured_rtts.pop(0)
        if len(self.measured_rtts) >= 2:
            mean = sum(self.measured_rtts) / len(self.measured_rtts)
            variance = sum((x - mean) ** 2 for x in self.measured_rtts) / (len(self.measured_rtts) - 1)
            self.jitter_s = max(0.0005, math.sqrt(variance))

    def process_arrival(self, slot_id: int, payload: bytes, arrival_time: float) -> bool:
        """Mathematics: validate packet header `(gid, pos, ver, residue)` and update slot arrival sequence."""

        slot = self.slots_by_id.get(slot_id)
        if slot is None:
            return False

        gid, pos, ver, res = DelaySlot.decode_payload(payload)
        group = self.groups.get(gid)
        if group is None or group.is_lost:
            return False

        if ver != slot.version:
            return False

        slot.alive = True
        slot.arrival_times.append(arrival_time)
        slot.received_count += 1
        slot.residue = res
        return True

    def scrub_group(self, group_id: int) -> tuple[int | None, bool]:
        r"""Mathematics: reconstruct `V = \text{CRT}(k \text{ surviving residues})` and regenerate missing slots with incremented version."""

        group = self.groups.get(group_id)
        if group is None or group.is_lost:
            return (None, False)

        surviving = [(slot.modulus, slot.residue) for slot in group.slots if slot.alive]
        if len(surviving) < group.k:
            group.is_lost = True
            return (None, False)

        recovered_v, consistent = recover_rrns(surviving, group.k, group.moduli)
        if not consistent or recovered_v is None:
            group.bad_recon_count += 1
            return (None, False)

        group.scrub_count += 1
        for slot in group.slots:
            if not slot.alive:
                slot.alive = True
                slot.version += 1
                slot.residue = recovered_v % slot.modulus

        return (recovered_v, True)

    def read_group(self, group_id: int) -> tuple[int | None, bool]:
        """Mathematics: perform non-destructive read of circulating group state via CRT on active slots."""

        group = self.groups.get(group_id)
        if group is None or group.is_lost:
            return (None, False)

        surviving = [(slot.modulus, slot.residue) for slot in group.slots if slot.alive]
        if len(surviving) < group.k:
            return (None, False)

        return recover_rrns(surviving, group.k, group.moduli)
