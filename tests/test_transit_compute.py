"""Real TCP integration tests for bounded CPU work hosted inside MailCPU."""

from __future__ import annotations

from mailcpu import (
    Capability,
    HeadlessOS,
    HypervisorArbitrationEvent,
    HypervisorDomain,
    HypervisorOperationChannel,
    HypervisorOperationResultChannel,
    HypervisorPolicy,
    HypervisorRequest,
    ReliabilityPolicy,
    ReliableChannel,
    SocketTransport,
)
from mailcpu.transit_compute import TransitComputeError, TransitComputeHost


def _tcp_pair(local: str, peer: str) -> tuple[SocketTransport, SocketTransport]:
    """Mathematics: create reciprocal AF_INET transports T_local and T_peer over one loopback TCP connection."""

    listener = SocketTransport.listen("127.0.0.1", 0)
    port = listener.getsockname()[1]
    local_transport = SocketTransport.connect("127.0.0.1", port, local, peer)
    peer_transport = SocketTransport.accept(listener, peer, local)
    listener.close()
    return local_transport, peer_transport


def _event(sequence: int = 1, source: str | None = None) -> HypervisorArbitrationEvent:
    """Mathematics: construct a bounded compute request with semantic identity (origin, compute, sequence)."""

    program_source = "\n".join((
        "set left 19",
        "set right 23",
        "add total left right",
        "set offset 6",
        "add result total offset",
        "halt",
    ))
    return HypervisorArbitrationEvent(
        "origin",
        "compute",
        sequence,
        500 + sequence,
        HypervisorRequest(
            "execute deterministic CPU arithmetic program",
            "/cpu/compute",
            {
                "source": program_source,
                "initial_registers": {"seed": 7},
                "max_ticks": 64,
            },
            frozenset({"execute"}),
            frozenset({"execute"}) if source is None else frozenset(),
        ),
    )


def test_pure_compute_operation_executes_inside_mailcpu_over_real_tcp() -> None:
    """Mathematics: request -> receiver authority -> bounded VM orbit -> result frame -> ACK preserves the arithmetic effect once."""

    request_origin_transport, request_replica_transport = _tcp_pair("origin", "replica")
    response_replica_transport, response_origin_transport = _tcp_pair("replica", "origin")
    policy = ReliabilityPolicy(lease_ticks=1, max_attempts=3, window_size=4)
    request_origin = HypervisorOperationChannel(
        ReliableChannel(request_origin_transport, "origin", "replica", "compute", policy)
    )
    request_replica = HypervisorOperationChannel(
        ReliableChannel(request_replica_transport, "replica", "replica", "compute", policy, peer="origin")
    )
    response_replica = HypervisorOperationResultChannel(
        ReliableChannel(response_replica_transport, "replica", "origin", "compute.result", policy),
        "origin",
        "compute",
    )
    response_origin = HypervisorOperationResultChannel(
        ReliableChannel(response_origin_transport, "origin", "origin", "compute.result", policy, peer="replica"),
        "origin",
        "compute",
    )
    receiver = HeadlessOS()
    worker_pid = receiver.environment.kernel.spawn(
        "transit-compute-worker",
        capabilities=(Capability("/cpu/compute", frozenset({"execute"})),),
        parent_pid=receiver.environment.init_pid,
    )
    receiver.hypervisor.policy = HypervisorPolicy(
        review_confidence=0.0,
        automatic_confidence=0.0,
        destructive_confidence=0.0,
        danger_review_probability=1.0,
    )
    compute_host = TransitComputeHost()
    handler_calls = {"count": 0}

    def authorize(event: HypervisorArbitrationEvent) -> HypervisorArbitrationEvent:
        """Mathematics: derive granted rights from receiver-local capability state G(init, resource), ignoring the sender's claim."""

        return receiver.hypervisor_authorize_event(worker_pid, event)

    def execute(event: HypervisorArbitrationEvent) -> dict[str, object]:
        """Mathematics: map one authorized event to its isolated E-CPU execution result and increment the local invocation witness."""

        handler_calls["count"] += 1
        return compute_host.handle(event)

    try:
        event = _event()
        assert request_origin.send(event) == 1
        first = request_replica.receive_and_reply_event(
            receiver.hypervisor_arbitration,
            authorize,
            {HypervisorDomain.CPU: execute},
            response_replica,
        )
        assert first is not None
        assert first.executed is True
        assert first.domain is HypervisorDomain.CPU
        assert first.action.value == "allow"
        assert first.effect["registers"]["total"] == 42
        assert first.effect["registers"]["result"] == 48
        assert first.effect["status"] == "exited"
        assert len(first.effect["state_digest"]) == 64
        assert handler_calls["count"] == 1

        received = response_origin.receive()
        assert received is not None
        assert received.effect == first.effect
        assert received.replayed is False

        # A new reliable frame carrying the same semantic operation is replayed
        # from the hypervisor effect ledger; it must not start another VM job.
        assert request_origin.send(event) == 2
        replay = request_replica.receive_and_reply_event(
            receiver.hypervisor_arbitration,
            authorize,
            {HypervisorDomain.CPU: execute},
            response_replica,
        )
        assert replay is not None and replay.replayed is True
        assert replay.effect == first.effect
        assert handler_calls["count"] == 1

        replayed_response = response_origin.receive()
        assert replayed_response is not None
        assert replayed_response.replayed is True
        assert replayed_response.effect == first.effect
        assert request_origin.channel.process_ack() == (1, 2)
        assert response_replica.channel.process_ack() == (1, 2)
        assert receiver.environment.kernel.journal.verify()
    finally:
        for transport in (
            request_origin_transport,
            request_replica_transport,
            response_replica_transport,
            response_origin_transport,
        ):
            if not transport.closed:
                transport.close()


def test_receiver_local_execute_capability_denies_compute_before_handler() -> None:
    """Mathematics: missing receiver right execute forces DENY and preserves the invariant handler_calls=0."""

    receiver = HeadlessOS()
    limited_pid = receiver.environment.kernel.spawn(
        "limited-compute-client",
        capabilities=(Capability("/safe", frozenset({"read"})),),
        parent_pid=receiver.environment.init_pid,
    )
    event = _event()
    authorized = receiver.hypervisor_authorize_event(limited_pid, event)
    handler_calls = {"count": 0}
    host = TransitComputeHost()

    def execute(request: HypervisorArbitrationEvent) -> dict[str, object]:
        """Mathematics: count any forbidden handler entry before delegating to the VM host."""

        handler_calls["count"] += 1
        return host.handle(request)

    result = receiver.hypervisor_arbitration.execute(
        authorized,
        {HypervisorDomain.CPU: lambda: execute(authorized)},
    )
    assert result.action.value == "deny"
    assert result.executed is False
    assert result.effect is None
    assert handler_calls["count"] == 0


def test_transit_host_rejects_syscall_and_message_side_effect_opcodes() -> None:
    """Mathematics: the admitted instruction set is a strict subset of the VM ISA excluding SYSCALL, SEND and WAIT."""

    host = TransitComputeHost()
    event = _event()
    unsafe = HypervisorArbitrationEvent(
        event.source,
        event.channel,
        event.sequence,
        event.logical_time,
        HypervisorRequest(
            event.request.operation,
            event.request.resource,
            {
                "source": "SYSCALL result clock\nHALT",
                "initial_registers": {},
                "max_ticks": 16,
            },
            event.request.required_rights,
            event.request.granted_rights,
        ),
    )
    try:
        host.handle(unsafe)
    except TransitComputeError as exc:
        assert "non-compute operations" in str(exc)
    else:
        raise AssertionError("unsafe syscall program was admitted")


def test_persistent_worker_serves_multiple_independent_requests() -> None:
    """Mathematics: one worker W processes distinct identities I_1 != I_2 while each job starts from an isolated VM state."""

    from mailcpu.transit_worker import TransitComputeWorker

    request_origin_transport, request_worker_transport = _tcp_pair("origin", "worker")
    response_worker_transport, response_origin_transport = _tcp_pair("worker", "origin")
    policy = ReliabilityPolicy(lease_ticks=1, max_attempts=3, window_size=4)
    request_origin = HypervisorOperationChannel(
        ReliableChannel(request_origin_transport, "origin", "worker", "compute", policy)
    )
    request_worker = HypervisorOperationChannel(
        ReliableChannel(request_worker_transport, "worker", "worker", "compute", policy, peer="origin")
    )
    response_worker = HypervisorOperationResultChannel(
        ReliableChannel(response_worker_transport, "worker", "origin", "compute.result", policy),
        "origin",
        "compute",
    )
    response_origin = HypervisorOperationResultChannel(
        ReliableChannel(response_origin_transport, "origin", "origin", "compute.result", policy, peer="worker"),
        "origin",
        "compute",
    )
    receiver = HeadlessOS()
    receiver.hypervisor.policy = HypervisorPolicy(
        review_confidence=0.0,
        automatic_confidence=0.0,
        destructive_confidence=0.0,
        danger_review_probability=1.0,
    )
    worker_pid = receiver.environment.kernel.spawn(
        "transit-compute-worker",
        capabilities=(Capability("/cpu/compute", frozenset({"execute"})),),
        parent_pid=receiver.environment.init_pid,
    )
    worker = TransitComputeWorker(receiver, worker_pid)

    try:
        outcomes = []
        for sequence in (1, 2):
            event = _event(sequence)
            assert request_origin.send(event) == sequence
            served = worker.serve_once(request_worker, response_worker)
            assert served is not None and served.executed is True
            assert served.action.value == "allow"
            returned = response_origin.receive()
            assert returned is not None
            assert returned.effect == served.effect
            assert returned.sequence == sequence
            outcomes.append(returned)

        assert len(outcomes) == 2
        assert all(item.effect["status"] == "exited" for item in outcomes)
        assert all(item.effect["registers"]["total"] == 42 for item in outcomes)
        assert request_origin.channel.process_ack() == (1, 2)
        assert response_worker.channel.process_ack() == (1, 2)
        assert receiver.environment.kernel.journal.verify()
    finally:
        for transport in (
            request_origin_transport,
            request_worker_transport,
            response_worker_transport,
            response_origin_transport,
        ):
            if not transport.closed:
                transport.close()


def test_reconstructed_worker_restores_execution_ledger_and_replays_without_reexecution() -> None:
    """Mathematics: restore receiver and channel snapshots, then require E[I] replay without a second compute invocation."""

    from mailcpu import TransitComputeWorker

    class CountingHost(TransitComputeHost):
        """A test host that exposes the number of first-time VM executions."""

        def __init__(self) -> None:
            """Mathematics: initialize invocation count c=0 for the test execution witness."""
            super().__init__()
            self.calls = 0

        def handle(self, event: HypervisorArbitrationEvent) -> dict[str, object]:
            """Mathematics: increment c exactly when the arithmetic host is entered for a first-seen operation."""
            self.calls += 1
            return super().handle(event)

    request_origin_transport, request_worker_transport = _tcp_pair("origin", "worker")
    response_worker_transport, response_origin_transport = _tcp_pair("worker", "origin")
    policy = ReliabilityPolicy(lease_ticks=1, max_attempts=3, window_size=4)
    request_origin = HypervisorOperationChannel(
        ReliableChannel(request_origin_transport, "origin", "worker", "compute", policy)
    )
    request_worker = HypervisorOperationChannel(
        ReliableChannel(request_worker_transport, "worker", "worker", "compute", policy, peer="origin")
    )
    response_worker = HypervisorOperationResultChannel(
        ReliableChannel(response_worker_transport, "worker", "origin", "compute.result", policy),
        "origin",
        "compute",
    )
    response_origin = HypervisorOperationResultChannel(
        ReliableChannel(response_origin_transport, "origin", "origin", "compute.result", policy, peer="worker"),
        "origin",
        "compute",
    )
    receiver = HeadlessOS()
    receiver.hypervisor.policy = HypervisorPolicy(
        review_confidence=0.0,
        automatic_confidence=0.0,
        destructive_confidence=0.0,
        danger_review_probability=1.0,
    )
    worker_pid = receiver.environment.kernel.spawn(
        "transit-compute-worker",
        capabilities=(Capability("/cpu/compute", frozenset({"execute"})),),
        parent_pid=receiver.environment.init_pid,
    )
    first_host = CountingHost()
    worker = TransitComputeWorker(receiver, worker_pid, first_host)
    event = _event(source="untrusted")

    try:
        assert request_origin.send(event) == 1
        first = worker.serve_once(request_worker, response_worker)
        assert first is not None and first.executed is True and first.replayed is False
        try:
            worker.snapshot(request_worker, response_worker)
        except ValueError as exc:
            assert "unacknowledged response" in str(exc)
        else:
            raise AssertionError("worker checkpoint accepted an unacknowledged result")
        first_response = response_origin.receive()
        assert first_response is not None and first_response.effect == first.effect
        assert request_origin.channel.process_ack() == (1,)
        assert response_worker.channel.process_ack() == (1,)
        assert first_host.calls == 1

        # Reconstruct worker, receiver ledger, reliable cursors, and result replay ledger.
        checkpoint = worker.snapshot(request_worker, response_worker)
        restarted_worker, restored_request, restored_response = TransitComputeWorker.from_snapshot(
            checkpoint,
            request_worker_transport,
            response_worker_transport,
        )
        restarted_host = CountingHost()
        restarted_worker.compute_host = restarted_host

        # A fresh reliable frame carries the same semantic operation identity and payload.
        assert request_origin.send(event) == 2
        replay = restarted_worker.serve_once(restored_request, restored_response)
        assert replay is not None
        assert replay.executed is True
        assert replay.replayed is True
        assert replay.effect == first.effect
        assert restarted_host.calls == 0

        replay_response = response_origin.receive()
        assert replay_response is not None
        assert replay_response.replayed is True
        assert replay_response.effect == first.effect
        assert request_origin.channel.process_ack() == (2,)
        assert restored_response.channel.process_ack() == (2,)
        assert restarted_worker.operating_system.environment.kernel.journal.verify()
    finally:
        for transport in (
            request_origin_transport,
            request_worker_transport,
            response_worker_transport,
            response_origin_transport,
        ):
            if not transport.closed:
                transport.close()
