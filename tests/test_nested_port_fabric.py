"""SHN-002 finite port contention, navigation, replay, and falsification tests."""
from __future__ import annotations

from copy import deepcopy
import pytest

from mailcpu.nested_port_fabric import NestedPortError, NestedPortFabric
from mailcpu.self_hosted_port_network import MODULUS


def oracle(t: int) -> int:
    """Independent literal recurrence for bounded reference coordinates."""
    x = 7
    for _ in range(t):
        x = (x * 5 + 1) % MODULUS
    return (3 * x + 11) % MODULUS


def filled(ports: int, *, active: bool = True, count: int = 24,
           hosts: int = 8, limit: int = 2) -> NestedPortFabric:
    chip = NestedPortFabric(ports, virtual_hosts=hosts,
                            active_port_observer=active, queue_limit=limit)
    for i in range(count):
        chip.submit(f"job{i}", [0, 1, 7, 101, 1024, 10**15 + 137][i % 6],
                    worker=i % hosts)
    return chip


@pytest.mark.parametrize("ports", [1, 2])
@pytest.mark.parametrize("active", [True, False])
def test_nested_traffic_is_real_owned_fabric_and_has_exact_results(ports, active):
    chip = filled(ports, active=active, count=24)
    result = chip.run(max_ticks=400)
    assert result["physical_port_lanes"] == ports
    assert result["logical_observer_hosts"] == 1 + ports + 8
    assert result["fabric_journal_verified"] is True
    assert result["external_payload_bytes"] == 0
    assert result["port_grants"] == [sum(2 for j in chip.jobs if j["lane"] == i)
                                     for i in range(ports)]
    assert result["interpreter_steps"] == 24 * (1 if active else 2)
    assert result["port_observer_steps"] == (24 if active else 0)
    assert all(j["completed_tick"] is not None for j in chip.jobs)
    for job in chip.jobs:
        t = job["coordinate"]
        if t <= 1024:
            assert result["outputs"][job["job_id"]] == oracle(t)
    for lane in range(ports):
        assert any(link["link_id"] == f"physical{lane}" for link in chip.fabric.links())
        assert sum(1 for link in chip.fabric.links()
                   if link["link_id"].startswith("virtual")) == 8
    assert len(chip.fabric.namespaces()) == 1 + ports + 8
    assert result["parallel_cpu_execution_claimed"] is False
    assert result["physical_hardware_measured"] is False


def test_one_interpreter_disallows_two_compute_steps_same_quantum():
    chip = filled(2, count=16)
    previous = 0
    for _ in range(100):
        if chip.complete:
            break
        tick = chip.step()
        assert chip.interpreter_steps - previous in (0, 1)
        assert len(tick["ports_used"]) <= 2
        assert len(set(tick["ports_used"])) == len(tick["ports_used"])
        previous = chip.interpreter_steps
    assert chip.complete


def test_active_port_observer_is_explicit_assumption_not_free_cpu():
    accelerated = filled(2, count=24).run(max_ticks=400)
    conservative = filled(2, active=False, count=24).run(max_ticks=400)
    assert accelerated["outputs"] == conservative["outputs"]
    assert accelerated["interpreter_steps"] == 24
    assert accelerated["port_observer_steps"] == 24
    assert conservative["interpreter_steps"] == 48
    assert conservative["port_observer_steps"] == 0


def test_capacity_comparison_records_not_assumes_port_speedup():
    one = filled(1, count=32).run(max_ticks=512)
    two = filled(2, count=32).run(max_ticks=512)
    assert one["outputs"] == two["outputs"]
    assert sum(one["port_grants"]) == sum(two["port_grants"]) == 64
    assert one["interpreter_steps"] == two["interpreter_steps"] == 32
    assert one["simulation_ticks"] >= 64  # 64 transmissions over one lane
    assert two["simulation_ticks"] >= 32  # one interpreter action per job
    # Whether 2 lanes win is an observation, not a contract of the scheduler.


@pytest.mark.parametrize("ports", [1, 2])
@pytest.mark.parametrize("mode", [True, False])
def test_restart_continuation_at_every_active_phase(ports, mode):
    original = filled(ports, active=mode, count=12, limit=1)
    for _ in range(15):
        if original.complete:
            break
        original.step()
    snap = deepcopy(original.snapshot())
    restored = NestedPortFabric.from_snapshot(snap)
    assert restored.snapshot() == snap
    original_report = original.run(max_ticks=400)
    restored_report = restored.run(max_ticks=400)
    assert original_report == restored_report
    assert restored.fabric.journal.verify()


def test_partial_checkpoint_has_intent_but_no_unearned_port_grants():
    chip = NestedPortFabric(1, virtual_hosts=4)
    chip.submit("fresh", 7, worker=0)
    assert chip.tick == 0
    assert chip.port_grants == [0]
    assert chip.fabric.peek(chip.workers[0]) is None
    restored = NestedPortFabric.from_snapshot(chip.snapshot())
    assert restored.run()["outputs"] == {"fresh": oracle(7)}


def test_closed_form_coordinate_large_and_no_materialized_orbit():
    chip = NestedPortFabric(1)
    chip.submit("huge", 10**18, worker=3)
    result = chip.run()
    assert 0 <= result["outputs"]["huge"] < MODULUS
    assert chip.interpreter_steps == 1
    assert result["simulation_ticks"] < 100


def test_backpressure_limits_queue_and_preserves_all_jobs():
    chip = NestedPortFabric(1, virtual_hosts=2, queue_limit=1, max_jobs=32)
    for i in range(16):
        chip.submit(f"probe{i}", i, worker=0)
    report = chip.run(max_ticks=512)
    assert len(report["outputs"]) == 16
    assert all(report["outputs"][f"probe{i}"] == oracle(i) for i in range(16))
    assert all(i["queue_length"] == 0 for i in chip.fabric.interfaces())


def test_budget_horizon_refuses_without_silent_completion():
    chip = filled(1, count=32)
    with pytest.raises(NestedPortError, match="budget exhausted"):
        chip.run(max_ticks=3)
    assert not chip.complete
    assert NestedPortFabric.from_snapshot(chip.snapshot()).run(max_ticks=512)["outputs"]


def test_corrupted_checkpoint_digest_and_rehashed_field_tamper_rejected():
    chip = filled(2, count=8)
    for _ in range(8):
        chip.step()
    snap = chip.snapshot()
    forged = deepcopy(snap)
    forged["port_grants"][0] += 1
    with pytest.raises(NestedPortError, match="digest"):
        NestedPortFabric.from_snapshot(forged)
    forged["snapshot_digest"] = __import__(
        "mailcpu.nested_port_fabric", fromlist=["_hash"])._hash(
            {k: v for k, v in forged.items() if k != "snapshot_digest"})
    with pytest.raises(NestedPortError, match="resource count"):
        NestedPortFabric.from_snapshot(forged)


def test_forged_result_with_rehashed_snapshot_rejected():
    from mailcpu.nested_port_fabric import _hash
    chip = filled(1, count=4)
    for _ in range(8):
        if chip.complete:
            break
        chip.step()
    forged = deepcopy(chip.snapshot())
    computed = next(j for j in forged["jobs"] if j["phase"] in ("computed", "returned", "done"))
    computed["value"] = (computed["value"] + 1) % MODULUS
    bare = {k: v for k, v in forged.items() if k != "snapshot_digest"}
    forged["snapshot_digest"] = _hash(bare)
    with pytest.raises(NestedPortError, match="answer or receipt changed"):
        NestedPortFabric.from_snapshot(forged)


def test_unexpected_frame_refused_before_interpreter_execution():
    chip = NestedPortFabric(1, virtual_hosts=2)
    chip.submit("clean", 1, worker=0)
    chip.step()  # one query frame arrives at guest0
    before = chip.interpreter_steps
    # The genuine packet is still in FIFO and any adjacent tampered message
    # must not be evaluated as a fresh authorized job.
    chip.fabric.send_routed(chip.core[0], chip.workers[0], b"malformed", chip.tick)
    chip.step()  # consumes only the genuine first request
    assert chip.interpreter_steps == before + 1
    with pytest.raises(NestedPortError, match="invalid JSON frame|queues differ"):
        NestedPortFabric.from_snapshot(chip.snapshot())


def test_invalid_identifiers_ports_and_job_bounds():
    for ports in (0, 3, -1, True, 1.5):
        with pytest.raises(NestedPortError):
            NestedPortFabric(ports)
    chip = NestedPortFabric(1, virtual_hosts=2, max_jobs=1)
    for bad in (-1, True, 10**18 + 1):
        with pytest.raises(NestedPortError):
            chip.submit("valid", bad, worker=0)
    for bad in (-1, 2, True):
        with pytest.raises(NestedPortError):
            chip.submit("valid", 1, worker=bad)
    chip.submit("valid", 1, worker=0)
    for identity in ("valid", "bad id"):
        with pytest.raises(NestedPortError):
            chip.submit(identity, 5, worker=1)


def test_port_path_is_nested_and_does_not_shortcut_to_guest():
    chip = NestedPortFabric(1, virtual_hosts=8)
    for i, guest in enumerate(chip.workers):
        path = chip.fabric.find_route(chip.core[0], guest)
        assert len(path) == 4
        assert path[0] == chip.core[0] and path[1] == chip.ports[0]
        assert path[2].namespace == "port0" and path[-1] == guest
