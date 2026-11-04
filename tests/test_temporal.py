"""Adversarial conformance tests for process-scoped temporal clock domains."""

from __future__ import annotations

import pytest

from mailcpu.chemical_time import SystemEpoch
from mailcpu.temporal import (
    CausalClockError,
    CausalRelation,
    CausalStamp,
    ClockDomain,
    ClockRegressionError,
    ClockUnavailableError,
    MonotonicReading,
    TemporalContext,
    TemporalError,
    TemporalProfile,
)


class ManualClock:
    """Deterministic integer clock source for clock-domain boundary tests."""

    def __init__(self, *values: int) -> None:
        self.values = list(values)
        self.index = 0

    def __call__(self) -> int:
        """Mathematics: return the next scripted clock value, then hold the last value."""
        if not self.values:
            return 0
        value = self.values[min(self.index, len(self.values) - 1)]
        self.index += 1
        return value

    def set(self, value: int) -> None:
        """Mathematics: replace the source's current value with one integer sample."""
        self.values = [value]
        self.index = 0


def _profile(*domains: ClockDomain) -> TemporalProfile:
    """Mathematics: construct a profile D from the supplied finite clock-domain set."""
    return TemporalProfile(frozenset(domains))


def test_process_profile_exposes_only_declared_clock_domains() -> None:
    """A requester process may use monotonic and causal time without receiving other domains."""
    monotonic = ManualClock(100, 110)
    context = TemporalContext(
        "requester:1",
        _profile(ClockDomain.MONOTONIC, ClockDomain.CAUSAL),
        monotonic_ns=monotonic,
        wall_time_ns=ManualClock(1_000),
    )

    frame = context.observe()
    assert frame.monotonic is not None
    assert frame.monotonic.elapsed_ns == 10
    assert frame.causal is not None
    assert frame.wall is None
    assert frame.scheduler is None
    with pytest.raises(ClockUnavailableError):
        context.wall_reading()


def test_wall_clock_rollback_does_not_regress_monotonic_duration() -> None:
    """Calendar corrections remain visible as wall samples and do not alter elapsed time."""
    monotonic = ManualClock(100, 110, 120)
    wall = ManualClock(5_000, 4_000)
    context = TemporalContext(
        "receiver:2",
        _profile(ClockDomain.MONOTONIC, ClockDomain.WALL),
        monotonic_ns=monotonic,
        wall_time_ns=wall,
    )

    first = context.observe()
    second = context.observe()

    assert first.wall is not None and second.wall is not None
    assert first.wall.utc_ns == 5_000
    assert second.wall.utc_ns == 4_000
    assert first.wall.sample_index == 1
    assert second.wall.sample_index == 2
    assert first.monotonic is not None and second.monotonic is not None
    assert first.monotonic.elapsed_ns == 10
    assert second.monotonic.elapsed_ns == 20


def test_monotonic_clock_regression_is_rejected() -> None:
    """A local monotonic source must never move behind its previous sample."""
    clock = ManualClock(1_000, 1_010, 1_005)
    context = TemporalContext(
        "worker:3",
        _profile(ClockDomain.MONOTONIC),
        monotonic_ns=clock,
    )
    first = context.monotonic_reading()
    assert first.elapsed_ns == 10
    with pytest.raises(ClockRegressionError):
        context.monotonic_reading()


def test_monotonic_duration_requires_same_actor_and_segment() -> None:
    """Elapsed-time subtraction refuses cross-process or cross-restore comparisons."""
    start = MonotonicReading("node-a:proc-1", 0, 100)
    finish = MonotonicReading("node-a:proc-1", 0, 175)
    other_process = MonotonicReading("node-a:proc-2", 0, 200)
    restored = MonotonicReading("node-a:proc-1", 1, 250)

    assert start.elapsed_until(finish) == 75
    with pytest.raises(TemporalError):
        start.elapsed_until(other_process)
    with pytest.raises(TemporalError):
        start.elapsed_until(restored)


def test_restore_preserves_accumulated_elapsed_and_opens_new_segment() -> None:
    """Checkpoint restore preserves observed duration but does not count offline time."""
    first_clock = ManualClock(100, 100)
    context = TemporalContext(
        "logical-worker-4",
        _profile(ClockDomain.MONOTONIC, ClockDomain.CAUSAL),
        monotonic_ns=first_clock,
    )
    before = context.monotonic_reading()
    assert before.elapsed_ns == 0
    first_clock.set(140)
    checkpoint = context.snapshot()

    restored_clock = ManualClock(9_000, 9_000)
    restored = TemporalContext.from_snapshot(
        checkpoint,
        monotonic_ns=restored_clock,
        wall_time_ns=ManualClock(100),
    )
    after_restore = restored.monotonic_reading()

    assert after_restore.segment == before.segment + 1
    assert after_restore.elapsed_ns == 40
    assert restored_clock.index == 2
    with pytest.raises(TemporalError):
        before.elapsed_until(after_restore)
    restored_clock.set(9_050)
    assert restored.monotonic_reading().elapsed_ns == 90


def test_temporal_checkpoint_rejects_tampering() -> None:
    """A changed temporal profile or clock counter invalidates its digest."""
    context = TemporalContext(
        "checkpoint-worker",
        _profile(ClockDomain.CAUSAL),
    )
    context.emit_causal_stamp()
    checkpoint = context.snapshot()
    tampered = {
        **checkpoint,
        "state": {
            **checkpoint["state"],
            "lamport": checkpoint["state"]["lamport"] + 1,
        },
    }
    with pytest.raises(TemporalError):
        TemporalContext.from_snapshot(tampered)


def test_lamport_and_vector_clocks_preserve_received_causality() -> None:
    """A receiving process merges remote vector state before producing its next local event."""
    origin = TemporalContext("origin", _profile(ClockDomain.CAUSAL))
    receiver = TemporalContext("receiver", _profile(ClockDomain.CAUSAL))

    request = origin.emit_causal_stamp()
    served = receiver.receive_causal_stamp(request)
    result = receiver.emit_causal_stamp()
    acknowledged = origin.receive_causal_stamp(result)

    assert request.lamport == 1
    assert served.lamport == 2
    assert result.lamport == 3
    assert acknowledged.lamport == 4
    assert request.relation(served) is CausalRelation.BEFORE
    assert served.relation(result) is CausalRelation.BEFORE
    assert result.relation(acknowledged) is CausalRelation.BEFORE
    assert acknowledged.vector_map() == {"origin": 2, "receiver": 2}


def test_vector_clocks_detect_concurrent_events() -> None:
    """Independent events from disconnected processes remain concurrent until a merge."""
    left = TemporalContext("left", _profile(ClockDomain.CAUSAL))
    right = TemporalContext("right", _profile(ClockDomain.CAUSAL))

    left_event = left.emit_causal_stamp()
    right_event = right.emit_causal_stamp()

    assert left_event.relation(right_event) is CausalRelation.CONCURRENT
    assert right_event.relation(left_event) is CausalRelation.CONCURRENT
    assert left_event.relation(left_event) is CausalRelation.EQUAL


def test_causal_receive_rejects_self_stamp_and_invalid_vector() -> None:
    """Causal merge refuses a self-delivery and malformed vector-clock states."""
    context = TemporalContext("worker", _profile(ClockDomain.CAUSAL))
    own = context.emit_causal_stamp()
    with pytest.raises(CausalClockError):
        context.receive_causal_stamp(own)
    with pytest.raises((CausalClockError, TemporalError)):
        CausalStamp.create("worker", 1, {"worker": 2})
    with pytest.raises((CausalClockError, TemporalError)):
        CausalStamp.create("worker", 1, {"other": 1})


def test_scheduler_and_system_epoch_domains_remain_independent() -> None:
    """A process may observe scheduler ticks and all SystemEpoch coordinates without conflating them."""
    from mailcpu.assembler import assemble
    from mailcpu.scheduler import DeterministicScheduler

    scheduler = DeterministicScheduler()
    scheduler.add(assemble("SET R1, 5\nHALT"), name="clocked-task", chemical_cost=0.75)
    scheduler.run(max_ticks=1)

    context = TemporalContext(
        "cpu-process:1",
        _profile(
            ClockDomain.SCHEDULER,
            ClockDomain.EVENT,
            ClockDomain.CHRONON,
            ClockDomain.CHEMICAL,
        ),
    )
    frame = context.observe(
        scheduler_id="cpu-main",
        scheduler_tick=scheduler.tick,
        system_epoch=scheduler.system_epoch,
    )

    assert frame.scheduler is not None and frame.scheduler.scheduler_id == "cpu-main"
    assert frame.scheduler.tick == 1
    assert frame.event_lambda == 1
    assert frame.chronon_phase == (0.0, -1.0)
    assert frame.chemical_tau == 0.75
    assert frame.monotonic is None
    assert frame.wall is None


def test_scheduler_domain_requires_named_scheduler_and_tick() -> None:
    """Virtual ticks are scoped to a named scheduler and cannot silently default to wall time."""
    context = TemporalContext(
        "vm-task",
        _profile(ClockDomain.SCHEDULER),
    )
    with pytest.raises(ClockUnavailableError):
        context.observe()
    with pytest.raises(TemporalError):
        context.observe(scheduler_id="vm-main", scheduler_tick=True)


def test_system_epoch_domains_require_epoch_and_validate_phase() -> None:
    """Event, chronon, and chemical coordinates require a valid SystemEpoch projection."""
    context = TemporalContext(
        "analysis-worker",
        _profile(ClockDomain.EVENT, ClockDomain.CHRONON, ClockDomain.CHEMICAL),
    )
    with pytest.raises(ClockUnavailableError):
        context.observe()
    with pytest.raises(TemporalError):
        context.observe(system_epoch=SystemEpoch(1, 2 + 0j, 0.0))
    with pytest.raises(TemporalError):
        context.observe(system_epoch=SystemEpoch(1, 1 + 0j, float("nan")))


def test_wall_clock_offset_does_not_override_vector_causality() -> None:
    """Arbitrary host wall-clock offsets cannot change the vector-clock partial order."""
    left_clock = ManualClock(900_000)
    right_clock = ManualClock(100_000)
    left = TemporalContext(
        "left-host:proc",
        _profile(ClockDomain.WALL, ClockDomain.CAUSAL),
        wall_time_ns=left_clock,
    )
    right = TemporalContext(
        "right-host:proc",
        _profile(ClockDomain.WALL, ClockDomain.CAUSAL),
        wall_time_ns=right_clock,
    )

    left_frame = left.observe()
    right_frame = right.observe()
    left_event = left.emit_causal_stamp()
    right_event = right.emit_causal_stamp()

    assert left_frame.wall is not None and right_frame.wall is not None
    assert left_frame.wall.utc_ns > right_frame.wall.utc_ns
    assert left_event.relation(right_event) is CausalRelation.CONCURRENT


def test_temporal_frame_serializes_selected_domains_without_conversion() -> None:
    """The temporal frame preserves each selected coordinate in its own typed field."""
    epoch = SystemEpoch(7, 0 - 1j, 2.25)
    context = TemporalContext(
        "mixed-worker",
        _profile(
            ClockDomain.WALL,
            ClockDomain.CAUSAL,
            ClockDomain.SCHEDULER,
            ClockDomain.EVENT,
            ClockDomain.CHRONON,
            ClockDomain.CHEMICAL,
        ),
        wall_time_ns=ManualClock(123_456),
    )
    causal = context.emit_causal_stamp()
    frame = context.observe(
        scheduler_id="scheduler-x",
        scheduler_tick=11,
        system_epoch=epoch,
    )
    data = frame.to_dict()

    assert data["wall"]["utc_ns"] == 123_456
    assert data["causal"]["lamport"] == causal.lamport
    assert data["scheduler"] == {"scheduler_id": "scheduler-x", "tick": 11}
    assert data["event_lambda"] == 7
    assert data["chronon_phase"] == [0.0, -1.0]
    assert data["chemical_tau"] == 2.25
    assert "seconds" not in data


def test_profile_serialization_is_canonical_and_duplicate_domains_are_refused() -> None:
    """Clock profiles round-trip as sorted domains and reject repeated or unknown labels."""
    profile = _profile(ClockDomain.WALL, ClockDomain.MONOTONIC)
    assert profile.to_dict() == {"domains": ["monotonic", "wall"]}
    assert TemporalProfile.from_dict(profile.to_dict()) == profile
    with pytest.raises(TemporalError):
        TemporalProfile.from_dict({"domains": ["wall", "wall"]})
    with pytest.raises(TemporalError):
        TemporalProfile.from_dict({"domains": ["universal-time"]})


def test_invalid_clock_source_values_are_rejected() -> None:
    """Clock providers must return integer nanoseconds and cannot use Boolean values."""
    context = TemporalContext(
        "bad-clock",
        _profile(ClockDomain.MONOTONIC),
        monotonic_ns=lambda: True,
    )
    with pytest.raises(TemporalError):
        context.monotonic_reading()


def test_scheduler_and_event_counters_do_not_mutate_causal_clock() -> None:
    """Observing virtual scheduler coordinates does not advance a process's causal event counter."""
    epoch = SystemEpoch(99, 1 + 0j, 0.0)
    context = TemporalContext(
        "independent",
        _profile(ClockDomain.CAUSAL, ClockDomain.SCHEDULER, ClockDomain.EVENT),
    )
    before = context.current_causal_stamp()
    frame = context.observe(
        scheduler_id="independent-scheduler",
        scheduler_tick=1_000_000,
        system_epoch=epoch,
    )
    after = context.current_causal_stamp()

    assert frame.scheduler is not None and frame.scheduler.tick == 1_000_000
    assert frame.event_lambda == 99
    assert before == after
