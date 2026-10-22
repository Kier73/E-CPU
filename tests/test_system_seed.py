from __future__ import annotations

import pytest

from mailcpu import HeadlessOS, SeedNavigationError, SystemSeed


PROGRAM = "set value 1\nset one 1\nadd value value one\nhalt\n"


def _machine() -> HeadlessOS:
    """Mathematics: construct one deterministic orbit seed `S_0` with a finite scheduler transition map `T`."""

    machine = HeadlessOS()
    machine.launch_source(PROGRAM, "seed-orbit")
    return machine


def test_system_seed_round_trips_exact_state_and_navigates_forward_and_backward() -> None:
    """Mathematics: `decode(encode(seed.at(k)))=seed.at(k)` and `T^(k-j)(S_j)=S_k` for reachable coordinates."""

    seed = SystemSeed.from_system(_machine())
    at_two = seed.at(2)
    restored = at_two.restore()
    independent = _machine()
    independent.run(2)
    assert at_two.state_digest == SystemSeed.from_system(independent).state_digest
    assert restored.snapshot() == independent.snapshot()
    assert SystemSeed.from_snapshot(at_two.snapshot()).snapshot() == at_two.snapshot()
    assert at_two.rewind(1).restore().snapshot() == seed.at(1).restore().snapshot()
    assert at_two.advance(1).coordinate == 3


def test_system_seed_rejects_tampered_origin_and_expected_state() -> None:
    """Mathematics: `digest(origin_state)≠origin_digest ∨ digest(T^k(origin))≠state_digest` refuses seed admission."""

    seed = SystemSeed.from_system(_machine()).at(2)
    tampered_origin = seed.snapshot()
    tampered_origin["origin_digest"] = "0" * 64
    with pytest.raises(SeedNavigationError, match="origin digest"):
        SystemSeed.from_snapshot(tampered_origin)

    tampered_state = seed.snapshot()
    tampered_state["state_digest"] = "0" * 64
    loaded = SystemSeed.from_snapshot(seed.snapshot())
    with pytest.raises(SeedNavigationError, match="state digest"):
        loaded.at(2, expected_digest=tampered_state["state_digest"])


def test_system_seed_refuses_unreachable_coordinate() -> None:
    """Mathematics: if `T^k(S_0)` cannot reach requested `k`, seed navigation raises instead of fabricating a state."""

    machine = HeadlessOS()
    machine.launch_source("halt\n", "terminal-orbit")
    seed = SystemSeed.from_system(machine)
    with pytest.raises(SeedNavigationError, match="cannot reach"):
        seed.at(2)
