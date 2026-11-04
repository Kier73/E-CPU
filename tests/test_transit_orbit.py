"""Deterministic scheduling tests for independent transit computation paths."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mailcpu import (
    Capability,
    HeadlessOS,
    HypervisorArbitrationEvent,
    HypervisorOperationChannel,
    HypervisorOperationResultChannel,
    HypervisorPolicy,
    HypervisorRequest,
    ReliabilityPolicy,
    ReliableChannel,
    SocketTransport,
    TransitComputeSession,
    TransitComputeWorker,
    TransitOrbitScheduler,
    TransitOrbitSchedulerError,
    verify_transit_orbit_receipts,
)


def _tcp_pair(local: str, peer: str) -> tuple[SocketTransport, SocketTransport]:
    """Create reciprocal loopback TCP transports with stable logical peer labels."""
    listener = SocketTransport.listen("127.0.0.1", 0)
    port = listener.getsockname()[1]
    local_transport = SocketTransport.connect("127.0.0.1", port, local, peer)
    peer_transport = SocketTransport.accept(listener, peer, local)
    listener.close()
    return local_transport, peer_transport


def _event(origin: str, sequence: int) -> HypervisorArbitrationEvent:
    """Build one bounded pure arithmetic request with stable semantic identity."""
    source = "\n".join(
        (
            "set left 19",
            "set right 23",
            "add total left right",
            "set offset 6",
            "add result total offset",
            "halt",
        )
    )
    return HypervisorArbitrationEvent(
        origin,
        "compute",
        sequence,
        500 + sequence,
        HypervisorRequest(
            "execute deterministic CPU arithmetic program",
            "/cpu/compute",
            {
                "source": source,
                "initial_registers": {"seed": 7},
                "max_ticks": 64,
            },
            frozenset({"execute"}),
            frozenset({"execute"}),
        ),
    )


def _transports(origin: str, worker: str) -> dict[str, SocketTransport]:
    """Build fresh request and response TCP pairs for a logical path."""
    request_origin, request_worker = _tcp_pair(origin, worker)
    response_worker, response_origin = _tcp_pair(worker, origin)
    return {
        "request_origin": request_origin,
        "request_worker": request_worker,
        "response_worker": response_worker,
        "response_origin": response_origin,
    }


def _harness(origin: str, worker: str) -> dict[str, object]:
    """Create an authenticated-by-local-identity loopback path with receiver-local authority."""
    transports = _transports(origin, worker)
    policy = ReliabilityPolicy(lease_ticks=1, max_attempts=3, window_size=8)
    request_origin = HypervisorOperationChannel(
        ReliableChannel(
            transports["request_origin"],
            origin,
            worker,
            "compute",
            policy,
        )
    )
    request_worker = HypervisorOperationChannel(
        ReliableChannel(
            transports["request_worker"],
            worker,
            worker,
            "compute",
            policy,
            peer=origin,
        )
    )
    response_worker = HypervisorOperationResultChannel(
        ReliableChannel(
            transports["response_worker"],
            worker,
            origin,
            "compute.result",
            policy,
        ),
        origin,
        "compute",
    )
    response_origin = HypervisorOperationResultChannel(
        ReliableChannel(
            transports["response_origin"],
            origin,
            origin,
            "compute.result",
            policy,
            peer=worker,
        ),
        origin,
        "compute",
    )

    receiver = HeadlessOS()
    worker_pid = receiver.environment.kernel.spawn(
        f"{worker}-compute-worker",
        capabilities=(Capability("/cpu/compute", frozenset({"execute"})),),
        parent_pid=receiver.environment.init_pid,
    )
    receiver.hypervisor.policy = HypervisorPolicy(
        review_confidence=0.0,
        automatic_confidence=0.0,
        destructive_confidence=0.0,
        danger_review_probability=1.0,
    )
    session = TransitComputeSession(
        TransitComputeWorker(receiver, worker_pid),
        request_worker,
        response_worker,
    )
    return {
        "session": session,
        "request_origin": request_origin,
        "response_origin": response_origin,
        "transports": transports,
        "origin": origin,
        "worker": worker,
    }


def _close(harnesses: list[dict[str, object]]) -> None:
    """Close every loopback transport created by the test harnesses."""
    for harness in harnesses:
        for transport in harness["transports"].values():
            if not transport.closed:
                transport.close()


def _receive_and_ack(harness: dict[str, object], count: int) -> list[object]:
    """Receive results, acknowledge requests, and release the worker result window."""
    results = []
    for _ in range(count):
        result = harness["response_origin"].receive()
        assert result is not None
        results.append(result)
    request_acks = harness["request_origin"].channel.process_ack()
    response_acks = harness["session"].response.channel.process_ack()
    assert request_acks == tuple(range(1, count + 1))
    assert response_acks == tuple(range(1, count + 1))
    return results


def test_orbit_scheduler_round_robins_ready_paths_without_global_lockstep() -> None:
    """Each ready path receives one transition per turn in stable logical-path order."""
    paths = [
        _harness("origin-a", "worker-a"),
        _harness("origin-b", "worker-b"),
    ]
    try:
        for harness in paths:
            sender = harness["request_origin"]
            for sequence in (1, 2):
                assert sender.send(_event(harness["origin"], sequence)) == sequence

        scheduler = TransitOrbitScheduler(
            {
                "path-b": paths[1]["session"],
                "path-a": paths[0]["session"],
            }
        )
        steps = scheduler.run(max_quanta=4)

        assert [step.receipt.path_id for step in steps] == [
            "path-a",
            "path-b",
            "path-a",
            "path-b",
        ]
        assert all(step.receipt.disposition == "processed" for step in steps)
        assert all(step.result is not None for step in steps)
        assert all(step.result.action.value == "allow" for step in steps)
        assert all(step.result.effect["registers"]["result"] == 48 for step in steps)
        assert scheduler.logical_tick == 4
        assert scheduler.cursor_path_id == "path-a"
        assert scheduler.state()["dispatch_counts"] == {
            "path-a": 2,
            "path-b": 2,
        }
        assert verify_transit_orbit_receipts(
            [step.receipt for step in steps]
        )

        for harness in paths:
            received = _receive_and_ack(harness, 2)
            assert all(item.effect["registers"]["result"] == 48 for item in received)
        assert all(
            harness["session"].worker.operating_system.environment.kernel.journal.verify()
            for harness in paths
        )
    finally:
        _close(paths)


def test_idle_orbit_quantum_is_receipted_and_does_not_rotate_cursor() -> None:
    """An empty ready set advances logical time without fabricating path work."""
    paths = [
        _harness("origin-a", "worker-a"),
        _harness("origin-b", "worker-b"),
    ]
    try:
        scheduler = TransitOrbitScheduler(
            {"path-a": paths[0]["session"], "path-b": paths[1]["session"]}
        )
        first = scheduler.step()
        second = scheduler.step()

        assert first.result is None
        assert first.receipt.disposition == "idle"
        assert first.receipt.path_id is None
        assert second.receipt.tick == 2
        assert second.receipt.previous_digest == first.receipt.digest
        assert scheduler.logical_tick == 2
        assert scheduler.cursor_path_id == "path-a"
        assert scheduler.state()["idle_ticks"] == 2
        assert verify_transit_orbit_receipts([first.receipt, second.receipt])
        assert not verify_transit_orbit_receipts(
            [first.receipt, second.receipt],
            initial_digest="f" * 64,
        )
    finally:
        _close(paths)


def test_orbit_checkpoint_restores_cursor_on_replacement_transports(
    tmp_path: Path,
) -> None:
    """Restored sessions retain logical path identity while their TCP connections are replaced."""
    paths = [
        _harness("origin-a", "worker-a"),
        _harness("origin-b", "worker-b"),
    ]
    replacement_transports: list[dict[str, SocketTransport]] = []
    try:
        paths[0]["request_origin"].send(_event("origin-a", 1))
        scheduler = TransitOrbitScheduler(
            {"path-a": paths[0]["session"], "path-b": paths[1]["session"]}
        )
        dispatched = scheduler.step()
        assert dispatched.receipt.path_id == "path-a"
        assert dispatched.result is not None
        assert dispatched.result.effect["registers"]["result"] == 48
        _receive_and_ack(paths[0], 1)

        session_snapshots = {
            path_id: harness["session"].snapshot()
            for path_id, harness in zip(("path-a", "path-b"), paths)
        }
        scheduler_path = tmp_path / "orbit.json"
        scheduler.save_checkpoint(scheduler_path)

        restored_sessions = {}
        for path_id, harness in zip(("path-a", "path-b"), paths):
            fresh = _transports(harness["origin"], harness["worker"])
            replacement_transports.append(fresh)
            restored_sessions[path_id] = TransitComputeSession.from_snapshot(
                session_snapshots[path_id],
                fresh["request_worker"],
                fresh["response_worker"],
            )
            assert (
                restored_sessions[path_id].snapshot()["digest"]
                == session_snapshots[path_id]["digest"]
            )

        restored = TransitOrbitScheduler.from_checkpoint(
            scheduler_path,
            restored_sessions,
        )
        assert restored.logical_tick == 1
        assert restored.cursor_path_id == "path-b"
        assert restored.receipt_head == scheduler.receipt_head

        # The new TCP transports are deliberately not part of the logical path
        # contract; the restored execution/checkpoint identity is.
        assert restored.step().receipt.disposition == "idle"
        assert restored.cursor_path_id == "path-b"
    finally:
        _close(paths)
        for transports in replacement_transports:
            for transport in transports.values():
                if not transport.closed:
                    transport.close()


def test_orbit_restore_rejects_changed_logical_path_membership() -> None:
    """The scheduler cannot silently attach a checkpoint to another path identity."""
    paths = [
        _harness("origin-a", "worker-a"),
        _harness("origin-b", "worker-b"),
    ]
    try:
        scheduler = TransitOrbitScheduler(
            {"path-a": paths[0]["session"], "path-b": paths[1]["session"]}
        )
        checkpoint = scheduler.snapshot()
        try:
            TransitOrbitScheduler.from_snapshot(
                checkpoint,
                {"path-a": paths[0]["session"]},
            )
        except TransitOrbitSchedulerError:
            pass
        else:
            raise AssertionError("orbit restore accepted incomplete logical path membership")
    finally:
        _close(paths)
