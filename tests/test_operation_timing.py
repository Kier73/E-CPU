from __future__ import annotations

import itertools

import pytest

from mailcpu import OperationTimingError, OperationTimingProbe


def _clock(start: int = 1_000):
    values = itertools.count(start, 10)
    return lambda: next(values)


def test_timing_probe_records_endpoint_local_monotonic_and_causal_provenance() -> None:
    probe = OperationTimingProbe("peer-a/origin", monotonic_ns=_clock())
    token = probe.start("fabric_route_resolution", correlation_id="request-1")
    sample = probe.finish(token)

    assert sample.actor_id == "peer-a/origin"
    assert sample.segment == 0
    assert sample.correlation_id == "request-1"
    assert sample.elapsed_ns == 10
    assert sample.causal_start.actor_id == sample.causal_end.actor_id == "peer-a/origin"
    assert sample.causal_end.lamport > sample.causal_start.lamport

    payload = probe.to_dict()
    assert payload["schema"] == "mailcpu.operation-timing-probe.v1"
    assert payload["clock_domain"] == "process-local-monotonic-nanoseconds"
    assert payload["samples"][0]["elapsed_ns"] == 10
    assert payload["summary"]["fabric_route_resolution"] == {
        "count": 1,
        "min_ns": 10,
        "median_ns": 10,
        "p95_ns": 10,
        "max_ns": 10,
        "total_ns": 10,
        "mean_ns": 10,
    }


def test_timing_probe_records_phase_when_measured_operation_raises() -> None:
    probe = OperationTimingProbe("peer-b/receiver", monotonic_ns=_clock())

    with pytest.raises(RuntimeError, match="backend refused"):
        with probe.measure("backend_compute", correlation_id="frontier-2"):
            raise RuntimeError("backend refused")

    assert len(probe.samples) == 1
    assert probe.samples[0].phase == "backend_compute"
    assert probe.samples[0].correlation_id == "frontier-2"
    assert probe.samples[0].elapsed_ns == 10


def test_timing_probe_refuses_invalid_phase_and_correlation_id() -> None:
    probe = OperationTimingProbe("peer-a", monotonic_ns=_clock())

    with pytest.raises(OperationTimingError, match="phase name"):
        probe.start("Not A Phase")

    with pytest.raises(OperationTimingError, match="correlation_id"):
        probe.start("backend_compute", correlation_id="bad correlation id")


def test_monotonic_samples_from_distinct_timing_probes_are_not_subtractable() -> None:
    first = OperationTimingProbe("peer-a", monotonic_ns=_clock())
    second = OperationTimingProbe("peer-b", monotonic_ns=_clock(9_000))

    first_sample = first.finish(first.start("origin_round_trip"))
    second_sample = second.finish(second.start("receiver_admission"))

    with pytest.raises(ValueError, match="different actors or segments"):
        first_sample.started.elapsed_until(second_sample.ended)


def test_clear_removes_samples_without_resetting_causal_or_monotonic_state() -> None:
    probe = OperationTimingProbe("peer-a", monotonic_ns=_clock())
    first = probe.finish(probe.start("local_compute"))
    probe.clear()
    second = probe.finish(probe.start("local_compute"))

    assert probe.samples == (second,)
    assert second.causal_start.lamport > first.causal_end.lamport
    assert second.started.elapsed_ns > first.ended.elapsed_ns
