from __future__ import annotations

import pytest

from mailcpu import (
    HeadlessOS,
    SeedAdmissionError,
    SeedNavigationError,
    SeedInputEvent,
    SystemIdentity,
    SystemSeed,
    SystemSeedEnvelope,
)
from mailcpu.programs import wait_send_program


def _machine() -> tuple[HeadlessOS, int]:
    """Mathematics: construct one blocked input orbit `S_0` with a known process target `pid`."""

    machine = HeadlessOS()
    pid = machine.spawn(wait_send_program(), "input-orbit")
    return machine, pid


def test_system_seed_replays_external_input_and_rewinds_its_event_prefix() -> None:
    """Mathematics: `Σ' = advance_input(e)` restores the same input transition and `Σ'.rewind(1)` removes `e`."""

    machine, pid = _machine()
    origin = SystemSeed.from_system(machine)
    advanced = origin.advance_input("resolver", 1, pid, "inbox", [42])
    restored = advanced.restore()
    assert restored.vm.scheduler.tick == 1
    assert advanced.input_events[0].receipt == advanced.input_receipts()[0]
    machine.inject(pid, "inbox", (42,))
    machine.run(1)
    assert machine.snapshot() == restored.snapshot()

    completed = advanced.advance(1).restore()
    machine.run(2)
    assert completed.vm.scheduler.tasks[pid].backend.outputs == [("outbox", 42)]
    assert machine.snapshot() == completed.snapshot()
    assert advanced.rewind(1).snapshot() == origin.snapshot()
    assert SystemSeed.from_snapshot(advanced.snapshot()).snapshot() == advanced.snapshot()


def test_system_seed_rejects_input_event_digest_tampering() -> None:
    """Mathematics: `digest(payload')≠digest(payload)` refuses an altered input event before replay."""

    machine, pid = _machine()
    event = SeedInputEvent("resolver", 1, pid, "inbox", (42,), 1)
    assert event.receipt.digest == event.digest
    seed = SystemSeed.from_system(machine).advance_input("resolver", 1, pid, "inbox", [42])
    tampered = seed.snapshot()
    tampered["input_events"][0]["values"] = [99]
    with pytest.raises(SeedNavigationError, match="digest"):
        SystemSeed.from_snapshot(tampered)


def test_system_seed_rejects_future_input_events() -> None:
    """Mathematics: a present seed coordinate `k` cannot contain an event with `coordinate(e)>k`."""

    machine, pid = _machine()
    origin = SystemSeed.from_system(machine)
    tampered = origin.advance_input("resolver", 1, pid, "inbox", [42]).snapshot()
    tampered["coordinate"] = 0
    tampered["state_digest"] = origin.state_digest
    with pytest.raises(SeedNavigationError, match="exceeds seed coordinate"):
        SystemSeed.from_snapshot(tampered)


def test_hypervisor_seed_admission_advances_and_replays_live_input() -> None:
    """Mathematics: `admit(E')` accepts one new receipt and exact retransmission returns the original receipt."""

    machine, pid = _machine()
    seed = SystemSeed.from_system(machine)
    initial = SystemSeedEnvelope(SystemIdentity("live-system", 1), "origin", "ops", seed)
    assert machine.seed_admission.admit(initial).accepted

    result, advanced = machine.seed_admission.advance_input("live-system", "resolver", 1, pid, "inbox", [42])
    assert result.accepted and not result.replayed
    assert advanced.input_frontier == advanced.seed.input_receipts()
    assert advanced.restore().vm.scheduler.tick == 1

    replay, replayed_envelope = machine.seed_admission.advance_input(
        "live-system",
        "resolver",
        1,
        pid,
        "inbox",
        [42],
    )
    assert replay.accepted and replay.replayed
    assert replay.admission_receipt == result.admission_receipt
    assert replayed_envelope.snapshot() == advanced.snapshot()
    with pytest.raises(SeedAdmissionError, match="conflicting"):
        machine.seed_admission.advance_input("live-system", "resolver", 1, pid, "inbox", [99])


def test_hypervisor_seed_admission_retransmission_preserves_a_later_fifo_frontier() -> None:
    """Mathematics: an old duplicate returns its original receipt while the authoritative frontier remains `F₂`, not `F₁`."""

    machine, pid = _machine()
    coordinator = machine.seed_admission
    initial = SystemSeedEnvelope(
        SystemIdentity("fifo-system", 1),
        "origin",
        "ops",
        SystemSeed.from_system(machine),
    )
    assert coordinator.admit(initial).accepted
    first, after_first = coordinator.advance_input("fifo-system", "resolver", 1, pid, "inbox", [41])
    second, after_second = coordinator.advance_input("fifo-system", "resolver", 2, pid, "inbox", [42])
    duplicate, returned = coordinator.advance_input("fifo-system", "resolver", 1, pid, "inbox", [41])

    assert first.accepted and second.accepted
    assert after_first.seed.coordinate == 1
    assert after_second.seed.coordinate == 2
    assert duplicate.accepted and duplicate.replayed
    assert duplicate.admission_receipt == first.admission_receipt
    assert returned.snapshot() == after_second.snapshot()
    assert coordinator.current("fifo-system").snapshot() == after_second.snapshot()
