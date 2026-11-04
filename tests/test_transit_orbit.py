"""Deterministic scheduling tests for independent transit computation paths."""

from __future__ import annotations
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
    TransitOrbitReceipt,
    TransitOrbitScheduler,
    TransitOrbitSchedulerError,
    HypervisorTransitOrbitController,
    HypervisorTransitOrbitError,
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


def _harness(
    origin: str,
    worker: str,
    *,
    response_window_size: int = 8,
) -> dict[str, object]:
    """Create a loopback path whose receiver enforces local execution authority."""
    transports = _transports(origin, worker)
    request_policy = ReliabilityPolicy(lease_ticks=1, max_attempts=3, window_size=8)
    response_policy = ReliabilityPolicy(
        lease_ticks=1,
        max_attempts=3,
        window_size=response_window_size,
    )
    request_origin = HypervisorOperationChannel(
        ReliableChannel(
            transports["request_origin"],
            origin,
            worker,
            "compute",
            request_policy,
        )
    )
    request_worker = HypervisorOperationChannel(
        ReliableChannel(
            transports["request_worker"],
            worker,
            worker,
            "compute",
            request_policy,
            peer=origin,
        )
    )
    response_worker = HypervisorOperationResultChannel(
        ReliableChannel(
            transports["response_worker"],
            worker,
            origin,
            "compute.result",
            response_policy,
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
            response_policy,
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
        portable_receipts = [
            TransitOrbitReceipt.from_dict(step.receipt.to_dict())
            for step in steps
        ]
        assert [receipt.to_dict() for receipt in portable_receipts] == [
            step.receipt.to_dict() for step in steps
        ]
        assert verify_transit_orbit_receipts(portable_receipts)
        tampered_receipt = steps[0].receipt.to_dict()
        tampered_receipt["action"] = "deny"
        try:
            TransitOrbitReceipt.from_dict(tampered_receipt)
        except TransitOrbitSchedulerError:
            pass
        else:
            raise AssertionError("receipt reconstruction accepted a changed payload")

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
        assert not verify_transit_orbit_receipts(
            [first.receipt, second.receipt],
            initial_tick=1,
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
        client_snapshots = {
            path_id: {
                "request": harness["request_origin"].channel.snapshot(),
                "response": harness["response_origin"].snapshot(),
            }
            for path_id, harness in zip(("path-a", "path-b"), paths)
        }
        scheduler_path = tmp_path / "orbit.json"
        scheduler.save_checkpoint(scheduler_path)

        restored_sessions = {}
        restored_clients = {}
        for path_id, harness in zip(("path-a", "path-b"), paths):
            fresh = _transports(harness["origin"], harness["worker"])
            replacement_transports.append(fresh)
            restored_sessions[path_id] = TransitComputeSession.from_snapshot(
                session_snapshots[path_id],
                fresh["request_worker"],
                fresh["response_worker"],
            )
            restored_clients[path_id] = {
                "request": HypervisorOperationChannel(
                    ReliableChannel.from_snapshot(
                        client_snapshots[path_id]["request"],
                        fresh["request_origin"],
                    )
                ),
                "response": HypervisorOperationResultChannel.from_snapshot(
                    client_snapshots[path_id]["response"],
                    fresh["response_origin"],
                ),
            }
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

        # Replacement transports carry the same logical path. The cursor is
        # retained, and a new request traverses the restored path on the new TCP
        # connection without reconstructing its previous execution from scratch.
        path_b = restored_clients["path-b"]
        assert path_b["request"].send(_event("origin-b", 1)) == 1
        resumed = restored.step()
        assert resumed.receipt.path_id == "path-b"
        assert resumed.receipt.disposition == "processed"
        assert resumed.result is not None
        assert resumed.result.action.value == "allow"
        assert resumed.result.effect["registers"]["result"] == 48

        resumed_result = path_b["response"].receive()
        assert resumed_result is not None
        assert resumed_result.effect["registers"]["result"] == 48
        assert path_b["request"].channel.process_ack() == (1,)
        assert restored_sessions["path-b"].response.channel.process_ack() == (1,)
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


def test_orbit_scheduler_waits_for_response_window_before_dispatch() -> None:
    """A full result window blocks another request before its receiver transition executes."""
    harness = _harness(
        "origin-a",
        "worker-a",
        response_window_size=1,
    )
    try:
        sender = harness["request_origin"]
        assert sender.send(_event("origin-a", 1)) == 1
        assert sender.send(_event("origin-a", 2)) == 2

        session = harness["session"]
        scheduler = TransitOrbitScheduler({"path-a": session})
        first = scheduler.step()
        assert first.receipt.disposition == "processed"
        assert first.result is not None
        assert first.result.effect["registers"]["result"] == 48
        assert session.request.channel.next_receive_sequence == 2
        assert session.response.channel.available_window == 0

        blocked = scheduler.step()
        assert blocked.result is None
        assert blocked.receipt.disposition == "backpressured"
        assert blocked.receipt.path_id == "path-a"
        assert session.request.channel.next_receive_sequence == 2
        assert scheduler.state()["dispatch_counts"] == {"path-a": 1}
        assert scheduler.state()["backpressure_ticks"] == 1

        first_reply = harness["response_origin"].receive()
        assert first_reply is not None
        assert first_reply.effect["registers"]["result"] == 48
        assert sender.channel.process_ack() == (1,)
        assert session.response.channel.process_ack() == (1,)
        assert session.response.channel.available_window == 1

        second = scheduler.step()
        assert second.receipt.disposition == "processed"
        assert second.result is not None
        assert second.result.effect["registers"]["result"] == 48
        second_reply = harness["response_origin"].receive()
        assert second_reply is not None
        assert second_reply.effect["registers"]["result"] == 48
        assert sender.channel.process_ack() == (2,)
        assert session.response.channel.process_ack() == (2,)

        assert scheduler.state()["dispatch_counts"] == {"path-a": 2}
        assert scheduler.state()["backpressure_ticks"] == 1
        assert verify_transit_orbit_receipts(
            [first.receipt, blocked.receipt, second.receipt]
        )
        restored = TransitOrbitScheduler.from_snapshot(
            scheduler.snapshot(),
            {"path-a": session},
        )
        assert restored.logical_tick == 3
        assert restored.state()["backpressure_ticks"] == 1
        assert restored.receipt_head == scheduler.receipt_head
        assert session.worker.operating_system.environment.kernel.journal.verify()
    finally:
        _close([harness])



def _orbit_control_plane(*, authorized: bool = True) -> tuple[HeadlessOS, int]:
    """Create a coordinator whose process may or may not schedule transit paths."""
    coordinator = HeadlessOS()
    capabilities = (
        (Capability("/system/transit/orbit", frozenset({"schedule"})),)
        if authorized
        else ()
    )
    authority_pid = coordinator.environment.kernel.spawn(
        "transit-orbit-control",
        capabilities=capabilities,
        parent_pid=coordinator.environment.init_pid,
    )
    coordinator.hypervisor.policy = HypervisorPolicy(
        review_confidence=0.0,
        automatic_confidence=0.0,
        destructive_confidence=0.0,
        danger_review_probability=1.0,
        embedding_review_confidence=1.0,
    )
    return coordinator, authority_pid


def test_hypervisor_capability_denial_does_not_consume_a_ready_transit_request() -> None:
    """The control-plane right gates the scheduler before a receiver path is entered."""
    harness = _harness("origin-a", "worker-a")
    try:
        harness["request_origin"].send(_event("origin-a", 1))
        session = harness["session"]
        scheduler = TransitOrbitScheduler({"path-a": session})
        coordinator, authority_pid = _orbit_control_plane(authorized=False)
        controller = HypervisorTransitOrbitController(
            coordinator, authority_pid, scheduler
        )

        controlled = controller.step()

        assert controlled.decision.action.value == "deny"
        assert controlled.orbit_step is None
        assert scheduler.logical_tick == 0
        assert session.request.channel.next_receive_sequence == 1
        assert session.request.channel.peek() is not None
        assert scheduler.state()["dispatch_counts"] == {"path-a": 0}
    finally:
        _close([harness])


def test_hypervisor_pump_fairly_interleaves_four_ready_paths_under_sustained_load() -> None:
    """The hypervisor admits each quantum while round-robin prevents path starvation."""
    paths = [
        _harness("origin-a", "worker-a"),
        _harness("origin-b", "worker-b"),
        _harness("origin-c", "worker-c"),
        _harness("origin-d", "worker-d"),
    ]
    try:
        for harness in paths:
            sender = harness["request_origin"]
            for sequence in (1, 2):
                assert sender.send(_event(harness["origin"], sequence)) == sequence

        sessions = {
            "path-a": paths[0]["session"],
            "path-b": paths[1]["session"],
            "path-c": paths[2]["session"],
            "path-d": paths[3]["session"],
        }
        scheduler = TransitOrbitScheduler(sessions)
        coordinator, authority_pid = _orbit_control_plane()
        controller = HypervisorTransitOrbitController(
            coordinator, authority_pid, scheduler
        )

        controlled_steps = controller.pump(max_quanta=12)
        orbit_steps = [item.orbit_step for item in controlled_steps]

        assert all(item.decision.action.value == "allow" for item in controlled_steps)
        assert all(item.orbit_step is not None for item in controlled_steps)
        assert [item.receipt.path_id for item in orbit_steps[:-1]] == [
            "path-a", "path-b", "path-c", "path-d",
            "path-a", "path-b", "path-c", "path-d",
        ]
        assert orbit_steps[-1].receipt.disposition == "idle"
        assert orbit_steps[-1].receipt.path_id is None
        assert scheduler.logical_tick == 9
        assert scheduler.state()["dispatch_counts"] == {
            "path-a": 2,
            "path-b": 2,
            "path-c": 2,
            "path-d": 2,
        }
        receipts = [item.receipt for item in orbit_steps]
        assert verify_transit_orbit_receipts(receipts)

        for harness in paths:
            replies = _receive_and_ack(harness, 2)
            assert [item.effect["registers"]["result"] for item in replies] == [48, 48]
            assert harness["session"].worker.operating_system.environment.kernel.journal.verify()
    finally:
        _close(paths)


def test_hypervisor_pump_stops_at_backpressure_and_resumes_after_acknowledgement() -> None:
    """A full response window blocks only that path and a later event-loop pump resumes it."""
    harness = _harness(
        "origin-a",
        "worker-a",
        response_window_size=1,
    )
    try:
        sender = harness["request_origin"]
        assert sender.send(_event("origin-a", 1)) == 1
        assert sender.send(_event("origin-a", 2)) == 2
        session = harness["session"]
        scheduler = TransitOrbitScheduler({"path-a": session})
        coordinator, authority_pid = _orbit_control_plane()
        controller = HypervisorTransitOrbitController(
            coordinator, authority_pid, scheduler
        )

        first_burst = controller.pump(max_quanta=8)
        assert [item.orbit_step.receipt.disposition for item in first_burst] == [
            "processed",
            "backpressured",
        ]
        assert session.request.channel.next_receive_sequence == 2
        assert scheduler.state()["dispatch_counts"] == {"path-a": 1}

        first_reply = harness["response_origin"].receive()
        assert first_reply is not None
        assert first_reply.effect["registers"]["result"] == 48
        assert sender.channel.process_ack() == (1,)
        assert session.response.channel.process_ack() == (1,)

        second_burst = controller.pump(max_quanta=8)
        assert [item.orbit_step.receipt.disposition for item in second_burst] == [
            "processed",
            "idle",
        ]
        second_reply = harness["response_origin"].receive()
        assert second_reply is not None
        assert second_reply.effect["registers"]["result"] == 48
        assert sender.channel.process_ack() == (2,)
        assert session.response.channel.process_ack() == (2,)
        assert scheduler.state()["dispatch_counts"] == {"path-a": 2}
        assert scheduler.logical_tick == 4
    finally:
        _close([harness])


def test_hypervisor_orbit_controller_checkpoint_binds_authority_and_scheduler_state() -> None:
    """Controller restore preserves the scheduler cursor and requires the same authority identity."""
    paths = [
        _harness("origin-a", "worker-a"),
        _harness("origin-b", "worker-b"),
    ]
    try:
        sessions = {
            "path-a": paths[0]["session"],
            "path-b": paths[1]["session"],
        }
        scheduler = TransitOrbitScheduler(sessions)
        coordinator, authority_pid = _orbit_control_plane()
        controller = HypervisorTransitOrbitController(
            coordinator, authority_pid, scheduler
        )
        first = controller.step()
        assert first.decision.action.value == "allow"
        assert first.orbit_step is not None
        assert first.orbit_step.receipt.disposition == "idle"

        checkpoint = controller.snapshot()
        restored = HypervisorTransitOrbitController.from_snapshot(
            checkpoint,
            coordinator,
            sessions,
        )
        assert restored.authority_pid == authority_pid
        assert restored.scheduler.logical_tick == scheduler.logical_tick
        assert restored.scheduler.cursor_path_id == scheduler.cursor_path_id
        assert restored.scheduler.receipt_head == scheduler.receipt_head

        tampered = {
            **checkpoint,
            "state": {
                **checkpoint["state"],
                "authority_pid": authority_pid + 1,
            },
        }
        try:
            HypervisorTransitOrbitController.from_snapshot(
                tampered,
                coordinator,
                sessions,
            )
        except HypervisorTransitOrbitError:
            pass
        else:
            raise AssertionError("controller restore accepted a tampered authority identity")
    finally:
        _close(paths)


def test_hypervisor_orbit_controller_rejects_invalid_pump_budget_and_boolean_pid() -> None:
    """Bounded event-loop pumping and authority identities reject ambiguous integer values."""
    coordinator, authority_pid = _orbit_control_plane()
    harness = _harness("origin-a", "worker-a")
    try:
        scheduler = TransitOrbitScheduler({"path-a": harness["session"]})
        try:
            HypervisorTransitOrbitController(coordinator, True, scheduler)
        except HypervisorTransitOrbitError:
            pass
        else:
            raise AssertionError("controller accepted a Boolean authority PID")

        controller = HypervisorTransitOrbitController(
            coordinator, authority_pid, scheduler
        )
        for invalid in (0, -1, True, 1.5, "4"):
            try:
                controller.pump(invalid)
            except HypervisorTransitOrbitError:
                pass
            else:
                raise AssertionError(f"controller accepted invalid pump budget: {invalid!r}")
    finally:
        _close([harness])



def test_hypervisor_rechecks_scheduler_capability_before_every_quantum() -> None:
    """Revoking coordinator authority stops the next turn without consuming its queued operation."""
    harness = _harness("origin-a", "worker-a")
    try:
        sender = harness["request_origin"]
        assert sender.send(_event("origin-a", 1)) == 1
        assert sender.send(_event("origin-a", 2)) == 2
        session = harness["session"]
        scheduler = TransitOrbitScheduler({"path-a": session})
        coordinator, authority_pid = _orbit_control_plane()
        controller = HypervisorTransitOrbitController(
            coordinator, authority_pid, scheduler
        )

        first = controller.step()
        assert first.authorized is True
        assert first.orbit_step is not None
        assert first.orbit_step.receipt.disposition == "processed"
        assert scheduler.logical_tick == 1

        coordinator.environment.kernel._process(authority_pid).capabilities = ()
        denied = controller.step()

        assert denied.decision.action.value == "deny"
        assert denied.orbit_step is None
        assert scheduler.logical_tick == 1
        assert session.request.channel.next_receive_sequence == 2
        assert session.request.channel.peek() is not None
    finally:
        _close([harness])


def test_coordinator_scheduler_permission_does_not_grant_receiver_job_permission() -> None:
    """An allowed control quantum can still produce a receiver-local DENY without running the job."""
    harness = _harness("origin-a", "worker-a")
    try:
        assert harness["request_origin"].send(_event("origin-a", 1)) == 1
        session = harness["session"]
        receiver_os = session.worker.operating_system
        receiver_os.environment.kernel._process(
            session.worker.authority_pid
        ).capabilities = ()

        scheduler = TransitOrbitScheduler({"path-a": session})
        coordinator, authority_pid = _orbit_control_plane()
        controller = HypervisorTransitOrbitController(
            coordinator, authority_pid, scheduler
        )

        controlled = controller.step()

        assert controlled.decision.action.value == "allow"
        assert controlled.orbit_step is not None
        assert controlled.orbit_step.receipt.disposition == "processed"
        assert controlled.orbit_step.result is not None
        assert controlled.orbit_step.result.action.value == "deny"
        assert controlled.orbit_step.result.executed is False
        assert controlled.orbit_step.result.effect is None
        replies = _receive_and_ack(harness, 1)
        assert replies[0].action.value == "deny"
        assert session.worker.operating_system.environment.kernel.journal.verify()
    finally:
        _close([harness])
