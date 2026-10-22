r"""Canonical seeds for deterministic MailCPU system-state navigation.

Mathematics:
Let `S_0` be a complete `HeadlessOS` snapshot and `T` the deterministic
scheduler transition operator. A seed is

\[
  \Sigma = (S_0, d_0, k, d_k),
  \qquad d_i = SHA256(JSON_{canonical}(T^i(S_0))).
\]

Navigation evaluates `T^k(S_0)` from the immutable origin. Rewind is therefore
exact replay from `S_0`, not an invented inverse for effects such as filesystem
writes or process creation. A requested coordinate is admitted only when the
restored scheduler reaches its target tick and its canonical digest matches.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

from .headless import HeadlessOS


class SeedNavigationError(ValueError):
    """A seed is malformed, tampered with, unreachable, or inconsistent with its expected digest."""


def _canonical_state(state: Mapping[str, Any]) -> bytes:
    """Mathematics: encode state as `c=JSON(sort_keys,state)` so equal state products have equal bytes."""

    try:
        return json.dumps(dict(state), sort_keys=True, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise SeedNavigationError("seed state is outside the canonical JSON algebra") from exc


def _state_digest(state: Mapping[str, Any]) -> str:
    """Mathematics: compute the content identity `d(S)=SHA256(c(S))` for one complete system state."""

    return hashlib.sha256(_canonical_state(state)).hexdigest()


def _scheduler_tick(state: Mapping[str, Any]) -> int:
    """Mathematics: project logical coordinate `τ(S)=S.vm.scheduler.tick` from the checkpoint graph."""

    try:
        raw_vm = state["vm"]
        raw_scheduler = dict(raw_vm)["scheduler"]
        tick = int(dict(raw_scheduler)["tick"])
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise SeedNavigationError("seed origin has no valid scheduler coordinate") from exc
    if tick < 0:
        raise SeedNavigationError("seed scheduler coordinate must be non-negative")
    return tick


def _validate_digest(value: Any, label: str) -> str:
    """Mathematics: restrict a content identity to the hexadecimal image of `SHA256`, `D={0,…,f}^{64}`."""

    digest = str(value)
    if len(digest) != 64:
        raise SeedNavigationError(f"{label} must be a 64-character SHA-256 digest")
    try:
        int(digest, 16)
    except ValueError as exc:
        raise SeedNavigationError(f"{label} must be hexadecimal") from exc
    return digest


@dataclass(frozen=True)
class SystemSeed:
    """An immutable origin-and-coordinate seed for predictable system-state replay."""

    origin_state: dict[str, Any]
    origin_digest: str
    coordinate: int
    state_digest: str

    @classmethod
    def from_system(cls, operating_system: HeadlessOS) -> "SystemSeed":
        """Mathematics: construct `Σ=(S_0,d_0,0,d_0)` from one complete running system state."""

        if not isinstance(operating_system, HeadlessOS):
            raise SeedNavigationError("system seed requires a HeadlessOS")
        state = deepcopy(operating_system.snapshot())
        digest = _state_digest(state)
        return cls(state, digest, 0, digest)

    @classmethod
    def from_snapshot(cls, payload: Mapping[str, Any]) -> "SystemSeed":
        """Mathematics: admit a seed only when `d(origin_state)=origin_digest` and its coordinate is finite and non-negative."""

        if not isinstance(payload, Mapping) or payload.get("format") != "mailcpu-system-seed/1":
            raise SeedNavigationError("unsupported system seed format")
        origin_state = payload.get("origin_state")
        if not isinstance(origin_state, Mapping):
            raise SeedNavigationError("system seed origin_state must be a mapping")
        origin = deepcopy(dict(origin_state))
        origin_digest = _validate_digest(payload.get("origin_digest"), "origin digest")
        if _state_digest(origin) != origin_digest:
            raise SeedNavigationError("origin digest does not match origin state")
        raw_coordinate = payload.get("coordinate")
        if isinstance(raw_coordinate, bool):
            raise SeedNavigationError("system seed coordinate is invalid")
        try:
            coordinate = int(raw_coordinate)
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise SeedNavigationError("system seed coordinate is invalid") from exc
        if coordinate < 0:
            raise SeedNavigationError("system seed coordinate must be non-negative")
        state_digest = _validate_digest(payload.get("state_digest"), "state digest")
        return cls(origin, origin_digest, coordinate, state_digest)

    def snapshot(self) -> dict[str, object]:
        """Mathematics: serialize `Σ` with copied origin state so seed storage cannot alias live execution state."""

        return {
            "format": "mailcpu-system-seed/1",
            "origin_state": deepcopy(self.origin_state),
            "origin_digest": self.origin_digest,
            "coordinate": self.coordinate,
            "state_digest": self.state_digest,
        }

    def restore(self) -> HeadlessOS:
        """Mathematics: evaluate `restore(Σ)=T^k(S_0)` and verify the seed's recorded digest at coordinate `k`."""

        operating_system = self._replay(self.coordinate)
        digest = _state_digest(operating_system.snapshot())
        if digest != _validate_digest(self.state_digest, "state digest"):
            raise SeedNavigationError("state digest does not match replayed state")
        return operating_system

    def at(self, coordinate: int, *, expected_digest: str | None = None) -> "SystemSeed":
        """Mathematics: compute `Σ.at(k)=(S_0,d_0,k,d(T^k(S_0)))` by deterministic replay from the origin."""

        if not isinstance(coordinate, int) or isinstance(coordinate, bool) or coordinate < 0:
            raise SeedNavigationError("seed coordinate must be a non-negative integer")
        operating_system = self._replay(coordinate)
        state = deepcopy(operating_system.snapshot())
        digest = _state_digest(state)
        if expected_digest is not None and digest != _validate_digest(expected_digest, "state digest"):
            raise SeedNavigationError("state digest does not match replayed state")
        return type(self)(deepcopy(self.origin_state), self.origin_digest, coordinate, digest)

    def advance(self, distance: int = 1) -> "SystemSeed":
        """Mathematics: move forward on the seed orbit `k↦k+distance` for non-negative integer distance."""

        if not isinstance(distance, int) or isinstance(distance, bool) or distance < 0:
            raise SeedNavigationError("seed advance distance must be a non-negative integer")
        return self.at(self.coordinate + distance)

    def rewind(self, distance: int = 1) -> "SystemSeed":
        """Mathematics: move backward by replaying the origin at `k-distance`, requiring `distance≤k`."""

        if not isinstance(distance, int) or isinstance(distance, bool) or distance < 0:
            raise SeedNavigationError("seed rewind distance must be a non-negative integer")
        if distance > self.coordinate:
            raise SeedNavigationError("seed rewind exceeds origin coordinate")
        return self.at(self.coordinate - distance)

    def _replay(self, coordinate: int) -> HeadlessOS:
        """Mathematics: evaluate `T^(τ(S_0)+k)(S_0)` and refuse if the scheduler cannot reach the requested coordinate."""

        target_tick = _scheduler_tick(self.origin_state) + coordinate
        try:
            operating_system = HeadlessOS.from_snapshot(deepcopy(self.origin_state))
            operating_system.run(target_tick)
        except (KeyError, TypeError, ValueError, OSError, OverflowError) as exc:
            raise SeedNavigationError("seed origin cannot be replayed") from exc
        actual_tick = operating_system.vm.scheduler.tick
        if actual_tick != target_tick:
            raise SeedNavigationError(
                f"seed cannot reach coordinate {coordinate}: scheduler stopped at tick {actual_tick}"
            )
        return operating_system
