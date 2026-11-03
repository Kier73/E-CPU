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
    TransitSIMTError,
    TransitSIMTHost,
    TransitMemoryTransferError,
    TransitMemoryTransferHost,
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

        # Revoke the service capability after prior successful operations. The
        # persistent worker must recompute authority and deny the next request.
        receiver.environment.kernel._process(worker_pid).capabilities = ()
        revoked_event = _event(3)
        assert request_origin.send(revoked_event) == 3
        denied = worker.serve_once(request_worker, response_worker)
        assert denied is not None
        assert denied.action.value == "deny"
        assert denied.executed is False
        assert denied.effect is None
        denied_response = response_origin.receive()
        assert denied_response is not None
        assert denied_response.action.value == "deny"
        assert denied_response.executed is False
        assert request_origin.channel.process_ack() == (1, 2, 3)
        assert response_worker.channel.process_ack() == (1, 2, 3)
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
        corrupted = {
            **checkpoint,
            "state": {
                **checkpoint["state"],
                "authority_pid": checkpoint["state"]["authority_pid"] + 1,
            },
        }
        try:
            TransitComputeWorker.from_snapshot(
                corrupted,
                request_worker_transport,
                response_worker_transport,
            )
        except ValueError as exc:
            assert "digest mismatch" in str(exc)
        else:
            raise AssertionError("worker checkpoint accepted a corrupted authority field")

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


def test_transit_host_requires_exact_execute_right_and_non_destructive_request() -> None:
    """Mathematics: admit only request authority R={execute} and destructive flag d=0 at the compute capsule boundary."""

    event = _event()
    payload = dict(event.request.payload)
    wrong_right = HypervisorArbitrationEvent(
        event.source,
        event.channel,
        event.sequence,
        event.logical_time,
        HypervisorRequest(
            event.request.operation,
            event.request.resource,
            payload,
            frozenset({"read"}),
            frozenset({"read"}),
        ),
    )
    destructive = HypervisorArbitrationEvent(
        event.source,
        event.channel,
        event.sequence,
        event.logical_time,
        HypervisorRequest(
            event.request.operation,
            event.request.resource,
            payload,
            frozenset({"execute"}),
            frozenset({"execute"}),
            destructive=True,
        ),
    )
    host = TransitComputeHost()
    for invalid in (wrong_right, destructive):
        try:
            host.handle(invalid)
        except TransitComputeError as exc:
            assert "authority" in str(exc) or "destructive" in str(exc)
        else:
            raise AssertionError("transit compute accepted an out-of-contract authority request")


def test_durable_mailbox_worker_restart_replays_committed_job(tmp_path) -> None:
    """Mathematics: persist channels and worker state, reconstruct all objects, then replay E[I] without a second VM execution."""

    import json

    from mailcpu import DurableMailboxTransport, TransitComputeWorker

    class CountingHost(TransitComputeHost):
        """Count first-seen arithmetic executions across the simulated worker restart."""

        def __init__(self) -> None:
            """Mathematics: initialize execution counter c=0."""
            super().__init__()
            self.calls = 0

        def handle(self, event: HypervisorArbitrationEvent) -> dict[str, object]:
            """Mathematics: increment c for each actual compute VM entry."""
            self.calls += 1
            return super().handle(event)

    request_path = tmp_path / "request.mailbox"
    response_path = tmp_path / "response.mailbox"
    request_transport = DurableMailboxTransport(request_path)
    response_transport = DurableMailboxTransport(response_path)
    policy = ReliabilityPolicy(lease_ticks=1, max_attempts=3, window_size=4)

    request_sender = HypervisorOperationChannel(
        ReliableChannel(request_transport, "origin", "worker", "compute", policy)
    )
    request_worker = HypervisorOperationChannel(
        ReliableChannel(request_transport, "worker", "worker", "compute", policy, peer="origin")
    )
    response_worker = HypervisorOperationResultChannel(
        ReliableChannel(response_transport, "worker", "origin", "compute.result", policy),
        "origin",
        "compute",
    )
    response_origin = HypervisorOperationResultChannel(
        ReliableChannel(response_transport, "origin", "origin", "compute.result", policy, peer="worker"),
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
    event = _event()

    assert request_sender.send(event) == 1
    first = worker.serve_once(request_worker, response_worker)
    assert first is not None and first.executed is True and first.replayed is False
    first_result = response_origin.receive()
    assert first_result is not None and first_result.effect == first.effect
    assert request_sender.channel.process_ack() == (1,)
    assert response_worker.channel.process_ack() == (1,)
    assert first_host.calls == 1

    # Persist the quiescent worker checkpoint independently of the durable mailboxes.
    checkpoint_path = tmp_path / "worker.json"
    checkpoint = worker.snapshot(request_worker, response_worker)
    checkpoint_path.write_text(
        json.dumps(checkpoint, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    client_request_state = request_sender.channel.snapshot()
    client_response_state = response_origin.snapshot()

    assert request_transport.verify()
    assert response_transport.verify()

    # Reopen both append-only logs and rebuild every channel/worker object.
    reopened_request_transport = DurableMailboxTransport(request_path, repair_torn=False)
    reopened_response_transport = DurableMailboxTransport(response_path, repair_torn=False)
    restored_checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    restored_worker, restored_request, restored_response = TransitComputeWorker.from_snapshot(
        restored_checkpoint,
        reopened_request_transport,
        reopened_response_transport,
    )
    restored_worker_host = CountingHost()
    restored_worker.compute_host = restored_worker_host
    restored_client_request = HypervisorOperationChannel(
        ReliableChannel.from_snapshot(client_request_state, reopened_request_transport)
    )
    restored_client_response = HypervisorOperationResultChannel.from_snapshot(
        client_response_state,
        reopened_response_transport,
    )

    # A fresh transport frame carries the exact same semantic event identity.
    assert restored_client_request.send(event) == 2
    replay = restored_worker.serve_once(restored_request, restored_response)
    assert replay is not None and replay.replayed is True
    assert replay.effect == first.effect
    assert restored_worker_host.calls == 0

    replay_result = restored_client_response.receive()
    assert replay_result is not None
    assert replay_result.replayed is True
    assert replay_result.effect == first.effect
    assert restored_client_request.channel.process_ack() == (2,)
    assert restored_response.channel.process_ack() == (2,)
    assert reopened_request_transport.verify()
    assert reopened_response_transport.verify()
    assert restored_worker.operating_system.environment.kernel.journal.verify()


def test_simt_reference_backend_matches_scalar_mailcpu_and_models_divergence_barriers() -> None:
    """Mathematics: SIMT lane-map output equals scalar MailCPU output, and barrier epochs occur only after lane-mask reconvergence."""

    values = (-4, -1, 0, 3, 8)
    simt_event = HypervisorArbitrationEvent(
        "client",
        "simt",
        1,
        100,
        HypervisorRequest(
            "execute deterministic CPU SIMT reference program",
            "/gpu/simt",
            {
                "lanes": len(values),
                "inputs": {"x": list(values)},
                "program": [
                    ["load", "value", "x"],
                    ["lane_id", "lane"],
                    ["const", "one", 1],
                    ["add", "tagged_lane", "lane", "one"],
                    ["mul", "square", "value", "value"],
                    ["const", "zero", 0],
                    ["lt", "negative", "value", "zero"],
                    ["if", "negative"],
                    ["sub", "result", "zero", "value"],
                    ["else"],
                    ["copy", "result", "value"],
                    ["endif"],
                    ["barrier"],
                    ["store", "absolute", "result"],
                    ["store", "lane_ids", "lane"],
                    ["store", "tagged_lanes", "tagged_lane"],
                    ["store", "squares", "square"],
                    ["halt"],
                ],
                "max_steps": 32,
            },
            frozenset({"execute"}),
            frozenset({"execute"}),
        ),
    )
    simt_result = TransitSIMTHost().handle(simt_event)
    assert simt_result["outputs"]["absolute"] == [4, 1, 0, 3, 8]
    assert simt_result["outputs"]["lane_ids"] == [0, 1, 2, 3, 4]
    assert simt_result["outputs"]["tagged_lanes"] == [1, 2, 3, 4, 5]
    assert simt_result["outputs"]["squares"] == [16, 1, 0, 9, 64]
    assert simt_result["mask_trace"] == [
        {"pc": 7, "opcode": "if", "active_lanes": [0, 1]},
        {"pc": 9, "opcode": "else", "active_lanes": [2, 3, 4]},
        {"pc": 11, "opcode": "endif", "active_lanes": [0, 1, 2, 3, 4]},
    ]
    assert simt_result["barriers"] == [
        {"epoch": 1, "pc": 12, "arrivals": len(values)}
    ]
    assert len(simt_result["state_digest"]) == 64

    scalar_host = TransitComputeHost()
    scalar_results: list[int] = []
    for sequence, value in enumerate(values, start=1):
        scalar_source = "\n".join((
            f"SET value {value}",
            f"SET neg_value {-value}",
            "SET zero 0",
            "SET minus_one -1",
            "SET one 1",
            "COMPARE sign value zero",
            "BRANCH sign sign_nonzero",
            "SET result 0",
            "BRANCH one done",
            "sign_nonzero:",
            "COMPARE positive sign minus_one",
            "BRANCH positive nonnegative",
            "COPY result neg_value",
            "BRANCH one done",
            "nonnegative:",
            "COPY result value",
            "done:",
            "HALT",
        ))
        scalar_event = HypervisorArbitrationEvent(
            "client",
            "compute",
            sequence,
            200 + sequence,
            HypervisorRequest(
                "execute deterministic CPU arithmetic program",
                "/cpu/compute",
                {
                    "source": scalar_source,
                    "initial_registers": {},
                    "max_ticks": 64,
                },
                frozenset({"execute"}),
                frozenset({"execute"}),
            ),
        )
        scalar_result = scalar_host.handle(scalar_event)
        scalar_results.append(scalar_result["registers"]["result"])
    assert scalar_results == simt_result["outputs"]["absolute"]

    divergent_barrier = HypervisorArbitrationEvent(
        "client",
        "simt",
        2,
        101,
        HypervisorRequest(
            "execute deterministic CPU SIMT reference program",
            "/gpu/simt",
            {
                "lanes": 2,
                "inputs": {"x": [-1, 1]},
                "program": [
                    ["load", "value", "x"],
                    ["const", "zero", 0],
                    ["lt", "negative", "value", "zero"],
                    ["if", "negative"],
                    ["barrier"],
                    ["endif"],
                    ["store", "copy", "value"],
                    ["halt"],
                ],
                "max_steps": 16,
            },
            frozenset({"execute"}),
            frozenset({"execute"}),
        ),
    )
    try:
        TransitSIMTHost().handle(divergent_barrier)
    except TransitSIMTError as exc:
        assert "BARRIER must appear after explicit reconvergence" in str(exc)
    else:
        raise AssertionError("SIMT reference backend accepted a barrier in a divergent region")


def test_simt_reference_kernel_executes_as_a_receiver_authorized_transit_operation() -> None:
    """Mathematics: transport a portable SIMT query, rederive execute authority at the receiver, and return the reference backend effect."""

    import time

    from mailcpu import TransitSIMTHost

    client_transport, worker_transport = _tcp_pair("client", "worker")
    policy = ReliabilityPolicy(lease_ticks=1, max_attempts=3, window_size=4)
    request_sender = HypervisorOperationChannel(
        ReliableChannel(client_transport, "client", "worker", "compute", policy)
    )
    request_receiver = HypervisorOperationChannel(
        ReliableChannel(worker_transport, "worker", "worker", "compute", policy, peer="client")
    )
    response_sender = HypervisorOperationResultChannel(
        ReliableChannel(worker_transport, "worker", "client", "compute.result", policy),
        "client",
        "compute",
    )
    response_receiver = HypervisorOperationResultChannel(
        ReliableChannel(client_transport, "client", "client", "compute.result", policy, peer="worker"),
        "client",
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
        "simt-transit-worker",
        capabilities=(Capability("/gpu/simt", frozenset({"execute"})),),
        parent_pid=receiver.environment.init_pid,
    )
    host = TransitSIMTHost()
    values = [-4, -1, 0, 3, 8]
    event = HypervisorArbitrationEvent(
        "client",
        "compute",
        1,
        300,
        HypervisorRequest(
            "execute deterministic CPU SIMT reference program",
            "/gpu/simt",
            {
                "lanes": len(values),
                "inputs": {"x": values},
                "program": [
                    ["load", "value", "x"],
                    ["const", "zero", 0],
                    ["lt", "negative", "value", "zero"],
                    ["if", "negative"],
                    ["sub", "result", "zero", "value"],
                    ["else"],
                    ["copy", "result", "value"],
                    ["endif"],
                    ["barrier"],
                    ["store", "absolute", "result"],
                    ["halt"],
                ],
                "max_steps": 16,
            },
            frozenset({"execute"}),
            frozenset(),
        ),
    )

    def authorize(request: HypervisorArbitrationEvent) -> HypervisorArbitrationEvent:
        """Mathematics: discard peer-supplied grants and derive execute rights from worker PID capabilities."""

        return receiver.hypervisor_authorize_event(worker_pid, request)

    try:
        assert request_sender.send(event) == 1
        deadline = time.monotonic() + 3.0
        served = None
        while time.monotonic() < deadline and served is None:
            served = request_receiver.receive_and_reply_event(
                receiver.hypervisor_arbitration,
                authorize,
                {HypervisorDomain.CPU: host.handle},
                response_sender,
            )
            if served is None:
                time.sleep(0.005)
        assert served is not None
        assert served.action.value == "allow"
        assert served.executed is True
        assert served.effect["outputs"]["absolute"] == [4, 1, 0, 3, 8]

        deadline = time.monotonic() + 3.0
        returned = None
        while time.monotonic() < deadline and returned is None:
            returned = response_receiver.receive()
            if returned is None:
                time.sleep(0.005)
        assert returned is not None
        assert returned.effect == served.effect
        assert returned.replayed is False

        deadline = time.monotonic() + 3.0
        request_acks = ()
        response_acks = ()
        while time.monotonic() < deadline and (request_acks != (1,) or response_acks != (1,)):
            request_acks = request_sender.channel.process_ack()
            response_acks = response_sender.channel.process_ack()
            if request_acks != (1,) or response_acks != (1,):
                time.sleep(0.005)
        assert request_acks == (1,)
        assert response_acks == (1,)
        assert receiver.environment.kernel.journal.verify()
    finally:
        for transport in (client_transport, worker_transport):
            if not transport.closed:
                transport.close()


def test_private_process_memory_transfer_runs_as_a_causally_receipted_transit_operation() -> None:
    """Mathematics: copy a bounded private address interval only under receiver read/write capabilities, then replay its semantic result without a second write."""

    import time

    from mailcpu import (
        ChoiceAnswer,
        DecisionBatch,
        IntentEmbedding,
        IntentPrototypeModel,
        NoulAnswer,
        assemble,
    )

    source_bytes = bytes((index * 17 + 3) % 256 for index in range(80))
    source_address = 4088
    destination_address = 4050

    client_transport, worker_transport = _tcp_pair("client", "worker")
    policy = ReliabilityPolicy(lease_ticks=1, max_attempts=3, window_size=4)
    request_sender = HypervisorOperationChannel(
        ReliableChannel(client_transport, "client", "worker", "memory", policy)
    )
    request_receiver = HypervisorOperationChannel(
        ReliableChannel(worker_transport, "worker", "worker", "memory", policy, peer="client")
    )
    response_sender = HypervisorOperationResultChannel(
        ReliableChannel(worker_transport, "worker", "client", "memory.result", policy),
        "client",
        "memory",
    )
    response_receiver = HypervisorOperationResultChannel(
        ReliableChannel(client_transport, "client", "client", "memory.result", policy, peer="worker"),
        "client",
        "memory",
    )

    receiver = HeadlessOS()
    source_pid = receiver.spawn(assemble("HALT"), "memory-source")
    destination_pid = receiver.spawn(assemble("HALT"), "memory-destination")
    source_memory = receiver.vm.memories[source_pid]
    destination_memory = receiver.vm.memories[destination_pid]
    source_memory.write(source_address, source_bytes)
    destination_memory.write(destination_address, b"\\xA5" * len(source_bytes))
    before_destination = destination_memory.read(destination_address, len(source_bytes))

    authority_pid = receiver.environment.kernel.spawn(
        "memory-transfer-worker",
        capabilities=(
            Capability("/memory/transfer", frozenset({"execute"})),
            Capability(f"/memory/{source_pid}", frozenset({"read"})),
            Capability(f"/memory/{destination_pid}", frozenset({"write"})),
        ),
        parent_pid=receiver.environment.init_pid,
    )
    receiver.hypervisor.policy = HypervisorPolicy(
        review_confidence=0.0,
        automatic_confidence=0.0,
        destructive_confidence=0.0,
        danger_review_probability=1.0,
        embedding_review_confidence=1.0,
    )

    event = HypervisorArbitrationEvent(
        "client",
        "memory",
        1,
        400,
        HypervisorRequest(
            "execute CPU instruction memory transfer",
            "/memory/transfer",
            {
                "source_pid": source_pid,
                "source_address": source_address,
                "destination_pid": destination_pid,
                "destination_address": destination_address,
                "length": len(source_bytes),
            },
            frozenset({"execute"}),
            frozenset(),
        ),
    )

    class CPUOnlyClassifier:
        """A deterministic test classifier that routes this reference transfer to the CPU execution domain."""

        model = "test-cpu-memory-transfer"

        def evaluate(self, state, questions):
            """Mathematics: return the normalized point mass P(domain=CPU)=1 and danger probability 0."""

            options = questions["domain"].criteria
            probabilities = {
                option: 1.0 if option == "cpu" else 0.0
                for option, _description in options
            }
            return DecisionBatch(
                {
                    "domain": ChoiceAnswer("cpu", probabilities, 1.0),
                    "danger": NoulAnswer(0.0),
                },
                self.model,
            )

    receiver.hypervisor.classifier = CPUOnlyClassifier()
    encoder = IntentEmbedding()
    receiver.hypervisor.intent_model = IntentPrototypeModel(
        encoder,
        {"cpu": encoder.encode(event.request.state()).vector},
    )

    transfer_host = TransitMemoryTransferHost(receiver, authority_pid)
    handler_calls = {"count": 0}

    def handle_transfer(request: HypervisorArbitrationEvent):
        """Mathematics: count actual host invocations so semantic replays can prove effect suppression."""

        handler_calls["count"] += 1
        return transfer_host.handle(request)

    def serve_one():
        """Mathematics: consume one event-aware request transition and publish its result before the request acknowledgement."""

        return request_receiver.receive_and_reply_event(
            receiver.hypervisor_arbitration,
            lambda request: receiver.hypervisor_authorize_event(authority_pid, request),
            {HypervisorDomain.CPU: handle_transfer},
            response_sender,
        )

    def wait_for_result():
        """Mathematics: observe typed result channel until one result arrives or finite wall-time budget expires."""

        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            result = response_receiver.receive()
            if result is not None:
                return result
            time.sleep(0.005)
        raise AssertionError("timed out waiting for memory transfer result")

    def wait_for_server_effect():
        """Mathematics: poll the nonblocking reliable request channel until its first effect result is committed."""

        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            result = serve_one()
            if result is not None:
                return result
            time.sleep(0.005)
        raise AssertionError("timed out waiting for memory transfer request")

    try:
        assert request_sender.send(event) == 1
        first = wait_for_server_effect()
        assert first.action.value == "allow"
        assert first.executed is True
        assert first.effect["bytes_transferred"] == len(source_bytes)
        assert destination_memory.read(destination_address, len(source_bytes)) == source_bytes
        assert source_memory.read(source_address, len(source_bytes)) == source_bytes
        assert first.effect["data_digest"] == __import__("hashlib").sha256(source_bytes).hexdigest()
        assert len(first.effect["completion_receipt"]) == 64
        returned = wait_for_result()
        assert returned.effect == first.effect
        assert returned.replayed is False
        assert handler_calls["count"] == 1

        # The memory operation is an explicit write; destination state must
        # remain unchanged when the receiver authority lacks destination write.
        restricted_pid = receiver.environment.kernel.spawn(
            "restricted-memory-worker",
            capabilities=(
                Capability("/memory/transfer", frozenset({"execute"})),
                Capability(f"/memory/{source_pid}", frozenset({"read"})),
            ),
            parent_pid=receiver.environment.init_pid,
        )
        restricted = TransitMemoryTransferHost(receiver, restricted_pid)
        try:
            restricted.handle(receiver.hypervisor_authorize_event(restricted_pid, event))
        except TransitMemoryTransferError as exc:
            assert "lacks 'write' permission" in str(exc)
        else:
            raise AssertionError("memory transfer succeeded without receiver destination-write authority")
        assert destination_memory.read(destination_address, len(source_bytes)) == source_bytes

        # A fresh reliable frame with the original semantic identity must replay
        # the same completion result without entering the transfer host again.
        assert request_sender.send(event) == 2
        replay = wait_for_server_effect()
        assert replay.replayed is True
        assert replay.effect == first.effect
        replay_result = wait_for_result()
        assert replay_result.replayed is True
        assert replay_result.effect == first.effect
        assert handler_calls["count"] == 1
        assert request_sender.channel.process_ack() == (1, 2)
        assert response_sender.channel.process_ack() == (1, 2)
        assert receiver.environment.kernel.journal.verify()
    finally:
        for transport in (client_transport, worker_transport):
            if not transport.closed:
                transport.close()


def test_private_memory_transfer_refuses_out_of_bounds_and_shared_pages() -> None:
    """Mathematics: reject nonresident or shared endpoint pages before committing any destination byte."""

    from mailcpu import assemble

    receiver = HeadlessOS()
    source_pid = receiver.spawn(assemble("HALT"), "private-source")
    destination_pid = receiver.spawn(assemble("HALT"), "private-destination")
    authority_pid = receiver.environment.kernel.spawn(
        "private-memory-worker",
        capabilities=(
            Capability("/memory/transfer", frozenset({"execute"})),
            Capability(f"/memory/{source_pid}", frozenset({"read"})),
            Capability(f"/memory/{destination_pid}", frozenset({"write"})),
        ),
        parent_pid=receiver.environment.init_pid,
    )
    source_memory = receiver.vm.memories[source_pid]
    destination_memory = receiver.vm.memories[destination_pid]
    source_memory.write(0, b"bounded")
    destination_memory.write(0, b"untouched")
    host = TransitMemoryTransferHost(receiver, authority_pid)

    def request(source_address: int, length: int) -> HypervisorArbitrationEvent:
        """Mathematics: bind one transfer proposal to private source and destination process identities."""

        return HypervisorArbitrationEvent(
            "client",
            "memory",
            1,
            1,
            HypervisorRequest(
                "execute CPU instruction memory transfer",
                "/memory/transfer",
                {
                    "source_pid": source_pid,
                    "source_address": source_address,
                    "destination_pid": destination_pid,
                    "destination_address": 0,
                    "length": length,
                },
                frozenset({"execute"}),
                frozenset({"execute"}),
            ),
        )

    before = destination_memory.read(0, len(b"untouched"))
    try:
        host.handle(request(8190, 16))
    except TransitMemoryTransferError:
        pass
    else:
        raise AssertionError("out-of-bounds memory transfer was accepted")
    assert destination_memory.read(0, len(b"untouched")) == before
