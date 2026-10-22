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
    TrajectoryReader,
    TrajectoryWriter,
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


def test_headless_seed_input_commit_matches_shadow_and_replays_duplicate() -> None:
    """Mathematics: commit requires `π(live_after)=π(shadow_after)=Σ'.state`, while duplicate input leaves the frontier unchanged."""

    machine, pid = _machine()
    origin = SystemSeed.from_system(machine)
    initial = SystemSeedEnvelope(SystemIdentity("commit-system", 1), "origin", "ops", origin)
    assert machine.seed_admission.admit(initial).accepted

    result, committed = machine.commit_seed_input("commit-system", "resolver", 1, pid, "inbox", iter((42,)))
    assert result.accepted and not result.replayed
    assert machine.vm.scheduler.tick == 1
    assert machine.seed_admission.current("commit-system").snapshot() == committed.snapshot()
    assert SystemSeed.from_system(machine).origin_digest == committed.seed.state_digest

    replay, current = machine.commit_seed_input("commit-system", "resolver", 1, pid, "inbox", [42])
    assert replay.accepted and replay.replayed
    assert replay.admission_receipt == result.admission_receipt
    assert current.snapshot() == committed.snapshot()
    assert machine.vm.scheduler.tick == 1

    second_result, second = machine.commit_seed_input("commit-system", "resolver", 2, pid, "inbox", [43])
    old_replay, current_after_old_replay = machine.commit_seed_input(
        "commit-system",
        "resolver",
        1,
        pid,
        "inbox",
        [42],
    )
    assert second_result.accepted and not second_result.replayed
    assert second.seed.coordinate == 2
    assert old_replay.accepted and old_replay.replayed
    assert old_replay.admission_receipt == result.admission_receipt
    assert current_after_old_replay.snapshot() == second.snapshot()
    assert machine.vm.scheduler.tick == 2


def test_headless_seed_input_commit_refuses_live_drift_without_mutation() -> None:
    """Mathematics: if `digest(π(live))≠digest(Σ.current)`, commit is refused before `live := live'`."""

    machine, pid = _machine()
    initial = SystemSeedEnvelope(
        SystemIdentity("drift-system", 1),
        "origin",
        "ops",
        SystemSeed.from_system(machine),
    )
    assert machine.seed_admission.admit(initial).accepted
    machine.run(1)
    before = machine.snapshot()
    with pytest.raises(SeedAdmissionError, match="diverged"):
        machine.commit_seed_input("drift-system", "resolver", 1, pid, "inbox", [42])
    assert machine.snapshot() == before


def test_headless_seed_input_commit_rolls_back_when_live_transition_diverges(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mathematics: a post-transition mismatch restores `live := snapshot_before` and preserves the admitted registry."""

    machine, pid = _machine()
    initial = SystemSeedEnvelope(
        SystemIdentity("rollback-system", 1),
        "origin",
        "ops",
        SystemSeed.from_system(machine),
    )
    assert machine.seed_admission.admit(initial).accepted
    before = machine.snapshot()
    original_run = machine.run

    def corrupt_run(max_ticks: int = 0) -> tuple[object, ...]:
        """Mathematics: model an invalid live transition `T'(S)=corrupt(T(S))` after the scheduler step."""

        events = original_run(max_ticks)
        machine.environment.kernel.journal.append("test.corruption", {"tick": machine.vm.scheduler.tick})
        return events

    monkeypatch.setattr(machine, "run", corrupt_run)
    with pytest.raises(SeedAdmissionError, match="diverged"):
        machine.commit_seed_input("rollback-system", "resolver", 1, pid, "inbox", [42])
    assert machine.snapshot() == before
    assert machine.seed_admission.current("rollback-system").seed.coordinate == 0


def test_headless_seed_input_commit_rolls_back_trajectory_suffix(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Mathematics: rollback restores both virtual state `S` and trace prefix `W[:n_before]` after a failed live step."""

    data_path = tmp_path / "commit.mtrj"
    index_path = tmp_path / "commit.mtrj.idx"
    with TrajectoryWriter(data_path, index_path) as writer:
        machine = HeadlessOS(trajectory=writer)
        pid = machine.spawn(wait_send_program(), "trajectory-input")
        initial = SystemSeedEnvelope(
            SystemIdentity("trajectory-system", 1),
            "origin",
            "ops",
            SystemSeed.from_system(machine),
        )
        assert machine.seed_admission.admit(initial).accepted
        before = machine.snapshot()
        original_run = machine.run

        def corrupt_run(max_ticks: int = 0) -> tuple[object, ...]:
            """Mathematics: append one invalid live trace suffix after the ordinary scheduler transition."""

            events = original_run(max_ticks)
            machine.environment.kernel.journal.append("test.corruption", {"tick": machine.vm.scheduler.tick})
            return events

        monkeypatch.setattr(machine, "run", corrupt_run)
        with pytest.raises(SeedAdmissionError, match="diverged"):
            machine.commit_seed_input("trajectory-system", "resolver", 1, pid, "inbox", [42])
        assert machine.snapshot() == before
        monkeypatch.undo()
        result, committed = machine.commit_seed_input("trajectory-system", "resolver", 1, pid, "inbox", [42])
        assert result.accepted and committed.seed.coordinate == 1
        writer.flush()
        with TrajectoryReader(data_path, index_path) as reader:
            assert reader.verify() == 1
