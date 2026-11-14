"""A falsifiable 1/2-physical-port, E-CPU-only interior-network experiment."""
from __future__ import annotations

from copy import deepcopy

import pytest

from mailcpu.self_hosted_port_network import (
    MAX_COORDINATE, MODULUS, SelfHostedPortError, SelfHostedPortNetwork,
)


def _reference(t: int) -> int:
    """Independent literal recurrence for small coordinates only."""
    value = 7
    for _ in range(t):
        value = (5 * value + 1) % MODULUS
    return (3 * value + 11) % MODULUS


@pytest.mark.parametrize("physical_ports", [1, 2])
@pytest.mark.parametrize("coordinate", [0, 1, 2, 7, 100, 1024])
def test_virtual_host_outputs_match_iterated_reference(physical_ports, coordinate):
    chip = SelfHostedPortNetwork(physical_ports)
    chip.submit("sample", coordinate)
    report = chip.run()
    assert report["observed_value"] == _reference(coordinate)
    assert report["physical_boundary_ports"] == physical_ports
    assert report["logical_observer_hosts"] == 3
    assert report["internal_virtual_interfaces"] == 6
    assert report["interpreter_quanta"] == 3
    assert report["external_payload_bytes"] == 0
    assert report["materialized_orbit_intermediate_states"] == 0
    assert report["internal_payload_bytes"] > 0
    assert report["journal_verified"] is True
    assert len(report["observer_receipts"]) == 2
    assert not report["independent_physical_execution_claimed"]
    assert chip.fabric.namespaces() == ("dispatcher", "navigator", "projector")
    assert len(chip.fabric.links()) == 3


def test_one_or_two_physical_ports_do_not_change_internal_computation():
    a, b = SelfHostedPortNetwork(1), SelfHostedPortNetwork(2)
    for chip in (a, b):
        chip.submit("probe", 10**15 + 137)
        chip.run()
    ar, br = a.report(), b.report()
    assert ar["observed_value"] == br["observed_value"]
    assert ar["observer_receipts"] == br["observer_receipts"]
    assert ar["internal_payload_bytes"] == br["internal_payload_bytes"]
    assert ar["external_payload_bytes"] == br["external_payload_bytes"] == 0
    assert ar["interpreter_quanta"] == br["interpreter_quanta"] == 3


@pytest.mark.parametrize("restoration_phase", ["idle", "navigator", "projector", "dispatcher", "done"])
def test_restart_reconstructs_owned_network_and_pending_observation(restoration_phase):
    chip = SelfHostedPortNetwork(1)
    if restoration_phase != "idle":
        chip.submit("checkpoint", MAX_COORDINATE)
        while chip.phase != restoration_phase:
            chip.step()
    snapshot = deepcopy(chip.snapshot())
    restored = SelfHostedPortNetwork.from_snapshot(snapshot)
    assert restored.snapshot() == snapshot
    if restored.phase == "idle":
        restored.submit("checkpoint", MAX_COORDINATE)
    result = restored.run()
    assert result["observed_value"] == (3 * chip._navigated(MAX_COORDINATE) + 11) % MODULUS
    assert result["interpreter_quanta"] == 3


def test_bounded_physical_ports_and_input_coordinates_fail_closed():
    for count in (0, 3, -1, True, 1.5):
        with pytest.raises(SelfHostedPortError):
            SelfHostedPortNetwork(count)
    chip = SelfHostedPortNetwork(1)
    for bad in (True, -1, MAX_COORDINATE + 1, 2.5):
        with pytest.raises(SelfHostedPortError):
            chip.submit("sample", bad)
    with pytest.raises(SelfHostedPortError):
        chip.submit("bad id!", 1)
    assert chip.phase == "idle"
    assert all(item["queue_length"] == 0 for item in chip.fabric.interfaces())
    chip.submit("accepted", 3)
    with pytest.raises(SelfHostedPortError, match="one in-flight"):
        chip.submit("second", 5)


def test_mutated_queued_value_cannot_rebind_checkpoint():
    chip = SelfHostedPortNetwork(1)
    chip.submit("tamper", 777)
    chip.step()
    snapshot = deepcopy(chip.snapshot())
    queue = snapshot["fabric"]["queues"]
    assert len(queue) == 1
    body = bytes.fromhex(queue[0]["frames"][0]["payload_hex"])
    corrupted = body.replace(b'"navigated"', b'"projected"')
    assert corrupted != body
    queue[0]["frames"][0]["payload_hex"] = corrupted.hex()
    with pytest.raises((SelfHostedPortError, ValueError)):
        SelfHostedPortNetwork.from_snapshot(snapshot)


def test_modified_receipt_chain_and_resource_accounts_are_rejected():
    chip = SelfHostedPortNetwork(2)
    chip.submit("receipt", 501)
    chip.step()
    snap = chip.snapshot()
    for modify in (
        lambda s: s["history"].__setitem__(0, "f" * 64),
        lambda s: s.__setitem__("external_payload_bytes", 100),
        lambda s: s.__setitem__("internal_payload_bytes", 0),
        lambda s: s.__setitem__("interpreter_quanta", 7),
    ):
        damaged = deepcopy(snap)
        modify(damaged)
        with pytest.raises(SelfHostedPortError):
            SelfHostedPortNetwork.from_snapshot(damaged)


def test_queue_backpressure_and_mtu_are_not_ignorable():
    from mailcpu.owned_network import OwnedNetworkError
    chip = SelfHostedPortNetwork(1, queue_limit=1)
    chip.submit("queue", 4)
    before = chip.fabric.snapshot()
    with pytest.raises(OwnedNetworkError, match="full"):
        chip.fabric.send(chip.addresses[0], chip.addresses[1], b"overflow", 1)
    with pytest.raises(OwnedNetworkError, match="MTU"):
        chip.fabric.send(chip.addresses[0], chip.addresses[1], b"x" * 2_049, 1)
    assert chip.fabric.snapshot() == before
    assert chip.run()["observed_value"] == _reference(4)


def test_invalid_snapshot_topology_and_physical_port_limits():
    chip = SelfHostedPortNetwork(1)
    chip.submit("layout", 99)
    snap = chip.snapshot()
    bad = deepcopy(snap)
    bad["fabric"]["links"].pop()
    with pytest.raises((SelfHostedPortError, OwnedNetworkError, KeyError, ValueError)):
        from mailcpu.owned_network import OwnedNetworkError
        SelfHostedPortNetwork.from_snapshot(bad)
    bad = deepcopy(snap)
    bad["physical_ports"] = 3
    with pytest.raises(SelfHostedPortError):
        SelfHostedPortNetwork.from_snapshot(bad)
