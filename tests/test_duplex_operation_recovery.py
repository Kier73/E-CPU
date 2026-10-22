from __future__ import annotations

import pytest

from mailcpu import (
    DuplexOperationRecoveryCheckpoint,
    HeadlessOS,
    HypervisorArbitrationEvent,
    HypervisorDomain,
    HypervisorIntentRevisionWitness,
    HypervisorOperationDuplexRecoveryCoordinator,
    HypervisorOperationResultChannel,
    HypervisorRequest,
    HypervisorRevisionProposal,
    IntentExample,
    IntentPrototypeModel,
    ReliabilityPolicy,
    ReliableChannel,
    RecoveryCoordinatorError,
    SocketTransport,
)


def _tcp_pair(local: str, peer: str) -> tuple[SocketTransport, SocketTransport]:
    """Mathematics: create reciprocal AF_INET streams `T_local↔T_peer` with the requested endpoint identities."""

    listener = SocketTransport.listen("127.0.0.1", 0)
    port = listener.getsockname()[1]
    local_transport = SocketTransport.connect("127.0.0.1", port, local, peer)
    peer_transport = SocketTransport.accept(listener, peer, local)
    listener.close()
    return local_transport, peer_transport


def _event() -> HypervisorArbitrationEvent:
    """Mathematics: form one request identity `I=(origin,ops,1)` with an executable process effect."""

    return HypervisorArbitrationEvent(
        "origin",
        "ops",
        1,
        300,
        HypervisorRequest(
            "spawn process executable file child image",
            "/bin/child.mca",
            {"path": "/bin/child.mca"},
            frozenset({"execute"}),
            frozenset({"execute"}),
        ),
    )


def _package_request() -> HypervisorRequest:
    """Mathematics: form a destructive package state `x_package` for advisory corpus training only."""

    return HypervisorRequest(
        "install package registry image digest deployment",
        "/package/child",
        {"digest": "verified-child"},
        frozenset({"write"}),
        frozenset({"write"}),
        True,
    )


def _channels(policy: ReliabilityPolicy):
    """Mathematics: compose independent request and response products `R_q` and `R_r` for origin and executor."""

    request_origin, request_executor = _tcp_pair("origin", "executor")
    response_executor, response_origin = _tcp_pair("executor", "origin")
    origin_request = ReliableChannel(request_origin, "origin", "executor", "ops", policy)
    executor_request = ReliableChannel(request_executor, "executor", "executor", "ops", policy, peer="origin")
    executor_response = HypervisorOperationResultChannel(
        ReliableChannel(response_executor, "executor", "origin", "ops.result", policy),
        "origin",
        "ops",
    )
    origin_response = HypervisorOperationResultChannel(
        ReliableChannel(response_origin, "origin", "origin", "ops.result", policy, peer="executor"),
        "origin",
        "ops",
    )
    return (
        request_origin,
        request_executor,
        response_executor,
        response_origin,
        origin_request,
        executor_request,
        executor_response,
        origin_response,
    )


def test_duplex_recovery_rebinds_both_loss_paths_and_trains_from_live_operations() -> None:
    """Mathematics: `restore(D);retry_q,retry_r` preserves one effect `|P|=1` through lost request and response ACKs."""

    policy = ReliabilityPolicy(lease_ticks=1, max_attempts=3, window_size=4)
    (
        request_origin_transport,
        request_executor_transport,
        response_executor_transport,
        response_origin_transport,
        origin_request,
        executor_request,
        executor_response,
        origin_response,
    ) = _channels(policy)
    origin = HeadlessOS()
    executor = HeadlessOS()
    executor.install_source("/bin/child.mca", "HALT\n")
    origin_coordinator = HypervisorOperationDuplexRecoveryCoordinator(
        request_origin_transport,
        origin_request,
        response_origin_transport,
        origin_response,
        origin,
        role="origin",
    )
    executor_coordinator = HypervisorOperationDuplexRecoveryCoordinator(
        request_executor_transport,
        executor_request,
        response_executor_transport,
        executor_response,
        executor,
        role="executor",
    )
    calls = {"count": 0}

    def encode_pid(child_pid: int) -> dict[str, int]:
        """Mathematics: encode native child identity `p` as canonical effect `E={pid:p}`."""

        return {"pid": int(child_pid)}

    def launch_handler() -> int:
        """Mathematics: apply one native process transition `P↦P∪{child}` and count handler executions."""

        calls["count"] += 1
        return executor.launch_file(
            "/bin/child.mca",
            parent_pid=executor.environment.init_pid,
            loader_pid=executor.environment.init_pid,
        )

    event = _event()
    try:
        assert origin_coordinator.send(event) == 1
        first = executor_coordinator.receive_and_reply(
            executor.environment.init_pid,
            {HypervisorDomain.PROCESS: launch_handler},
            encode_pid,
        )
        assert first is not None and first.executed is True and first.effect == {"pid": 2}
        received = origin_coordinator.receive_result()
        assert received is not None and received.replayed is False and received.effect == first.effect
        assert calls["count"] == 1
        assert origin_coordinator.status().request_pending_sequences == (1,)
        assert executor_coordinator.status().response_pending_sequences == (1,)

        package = _package_request()
        candidate = IntentPrototypeModel.fit(
            (
                IntentExample("process", event.request.state()),
                IntentExample("package", package.state()),
            )
        )
        held_out_process = HypervisorRequest(
            "retransmit process executable child image operation",
            "/bin/worker.mca",
            {"path": "/bin/worker.mca"},
            frozenset({"execute"}),
            frozenset({"execute"}),
        )
        held_out_package = HypervisorRequest(
            "stage package registry verified image deployment",
            "/package/worker",
            {"digest": "verified-worker"},
            frozenset({"write"}),
            frozenset({"write"}),
            True,
        )
        assert candidate.predict(held_out_process.state()).domain == "process"
        assert candidate.predict(held_out_package.state()).domain == "package"
        witnesses = tuple(
            HypervisorIntentRevisionWitness.from_prediction(
                request,
                candidate.predict(request.state()),
                origin.hypervisor_decide(request),
            )
            for request in (event.request, package)
        )
        admission = origin.hypervisor_propose_revision(
            HypervisorRevisionProposal.from_candidate(
                "origin",
                "duplex-intent-training",
                1,
                301,
                candidate,
                witnesses,
                target="intent",
            )
        )
        assert admission.admission.accepted is True
        assert origin.hypervisor.intent_model.snapshot() == candidate.snapshot()

        for transport in (
            request_origin_transport,
            request_executor_transport,
            response_executor_transport,
            response_origin_transport,
        ):
            transport.close()
        origin_checkpoint = origin_coordinator.checkpoint()
        executor_checkpoint = executor_coordinator.checkpoint()
        assert DuplexOperationRecoveryCheckpoint.from_snapshot(origin_checkpoint.snapshot()).snapshot() == origin_checkpoint.snapshot()
        assert DuplexOperationRecoveryCheckpoint.from_snapshot(executor_checkpoint.snapshot()).snapshot() == executor_checkpoint.snapshot()

        rebound_request_origin, rebound_request_executor = _tcp_pair("origin", "executor")
        rebound_response_executor, rebound_response_origin = _tcp_pair("executor", "origin")
        restored_origin = HypervisorOperationDuplexRecoveryCoordinator.rebind(
            origin_checkpoint,
            rebound_request_origin.socket,
            rebound_response_origin.socket,
            role="origin",
            peer="executor",
        )
        restored_executor = HypervisorOperationDuplexRecoveryCoordinator.rebind(
            executor_checkpoint,
            rebound_request_executor.socket,
            rebound_response_executor.socket,
            role="executor",
            peer="origin",
        )
        restored_calls = {"count": 0}

        def restored_handler() -> int:
            """Mathematics: a second native transition would violate `|P_effect|=1`, so replay must not call this handler."""

            restored_calls["count"] += 1
            return restored_executor.operating_system.launch_file(
                "/bin/child.mca",
                parent_pid=restored_executor.operating_system.environment.init_pid,
                loader_pid=restored_executor.operating_system.environment.init_pid,
            )

        assert restored_origin.retry() == ()
        assert restored_executor.retry() == ()
        response_replay = restored_origin.receive_result()
        assert response_replay is not None and response_replay.replayed is True and response_replay.effect == {"pid": 2}
        assert restored_executor.service() == (1,)
        request_replay = restored_executor.receive_and_reply(
            restored_executor.operating_system.environment.init_pid,
            {HypervisorDomain.PROCESS: restored_handler},
            encode_pid,
        )
        assert request_replay is not None and request_replay.replayed is True and request_replay.effect == {"pid": 2}
        response_replay_again = restored_origin.receive_result()
        assert response_replay_again is not None and response_replay_again.replayed is True
        assert restored_executor.service() == (2,)
        assert restored_origin.service() == (1,)
        assert restored_calls["count"] == 0
        assert len(restored_executor.operating_system.environment.kernel.processes) == 2
        assert restored_origin.status().request_pending_sequences == ()
        assert restored_executor.status().response_pending_sequences == ()
        assert restored_origin.operating_system.hypervisor.intent_model.snapshot() == candidate.snapshot()
        assert restored_executor.operating_system.environment.kernel.journal.verify()
        assert restored_origin.operating_system.environment.kernel.journal.verify()
    finally:
        for transport in (
            request_origin_transport,
            request_executor_transport,
            response_executor_transport,
            response_origin_transport,
        ):
            if not transport.closed:
                transport.close()
        for name in (
            "rebound_request_origin",
            "rebound_request_executor",
            "rebound_response_executor",
            "rebound_response_origin",
        ):
            transport = locals().get(name)
            if transport is not None and not transport.closed:
                transport.close()


def test_duplex_recovery_rejects_role_mismatch_before_socket_rebind() -> None:
    """Mathematics: `role_new≠role_checkpoint` refuses `bind(rebind(D))` before consuming replacement sockets."""

    policy = ReliabilityPolicy(window_size=2)
    (
        request_origin_transport,
        request_executor_transport,
        response_executor_transport,
        response_origin_transport,
        origin_request,
        _executor_request,
        _executor_response,
        origin_response,
    ) = _channels(policy)
    try:
        checkpoint = HypervisorOperationDuplexRecoveryCoordinator.capture(
            request_origin_transport,
            origin_request,
            response_origin_transport,
            origin_response,
            HeadlessOS(),
            role="origin",
        )
        rebound_request_origin, rebound_request_executor = _tcp_pair("origin", "executor")
        rebound_response_executor, rebound_response_origin = _tcp_pair("executor", "origin")
        with pytest.raises(RecoveryCoordinatorError, match="role"):
            HypervisorOperationDuplexRecoveryCoordinator.rebind(
                checkpoint,
                rebound_request_origin.socket,
                rebound_response_origin.socket,
                role="executor",
                peer="executor",
            )
        for transport in (
            rebound_request_origin,
            rebound_request_executor,
            rebound_response_executor,
            rebound_response_origin,
        ):
            transport.close()
    finally:
        for transport in (
            request_origin_transport,
            request_executor_transport,
            response_executor_transport,
            response_origin_transport,
        ):
            if not transport.closed:
                transport.close()

