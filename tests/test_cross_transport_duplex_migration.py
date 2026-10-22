from __future__ import annotations

from dataclasses import replace

import pytest

from mailcpu import (
    CrossTransportDuplexRecoveryCoordinator,
    DEFAULT_CHECKPOINT_KIND,
    DuplexTransportMigrationCheckpoint,
    HeadlessOS,
    HypervisorArbitrationEvent,
    HypervisorDomain,
    HypervisorOperationDuplexRecoveryCoordinator,
    HypervisorOperationResultChannel,
    HypervisorRequest,
    InMemoryTransport,
    RecoveryPolicyOffer,
    RecoveryPolicyAgreement,
    ReliabilityPolicy,
    ReliableChannel,
    SocketTransport,
    TransportMigrationError,
    advertise_recovery_policy,
    negotiate_recovery_policy,
)


def _tcp_pair(local: str, peer: str) -> tuple[SocketTransport, SocketTransport]:
    """Mathematics: create reciprocal AF_INET streams `T_local↔T_peer` with typed endpoint identities."""

    listener = SocketTransport.listen("127.0.0.1", 0)
    port = listener.getsockname()[1]
    local_transport = SocketTransport.connect("127.0.0.1", port, local, peer)
    peer_transport = SocketTransport.accept(listener, peer, local)
    listener.close()
    return local_transport, peer_transport


def _agreement() -> RecoveryPolicyAgreement:
    """Mathematics: construct the bounded intersection `G=O∩A` for socket-to-memory duplex movement."""

    policy = ReliabilityPolicy(lease_ticks=1, max_attempts=3, window_size=4)
    advertisement = advertise_recovery_policy(
        checkpoint_kinds=(DEFAULT_CHECKPOINT_KIND,),
        transport_kinds=("memory", "socket"),
        max_window_size=4,
        min_lease_ticks=1,
        max_attempts=3,
        allow_cross_transport=True,
        supports_effect_ledger=True,
    )
    offer = RecoveryPolicyOffer(1, DEFAULT_CHECKPOINT_KIND, "socket", "memory", policy, True)
    return negotiate_recovery_policy(offer, advertisement)


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


def _channels(policy: ReliabilityPolicy):
    """Mathematics: compose independent request/result products `(R_q,R_r)` for both duplex roles."""

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


def test_duplex_socket_state_migrates_into_one_memory_host_without_replaying_effect() -> None:
    """Mathematics: `M(D_origin)∪M(D_executor)` preserves both ACK paths and `|native_effect|=1` on one target `Q`."""

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
        """Mathematics: apply one native process transition `P↦P∪{child}` and count executions."""

        calls["count"] += 1
        return executor.launch_file(
            "/bin/child.mca",
            parent_pid=executor.environment.init_pid,
            loader_pid=executor.environment.init_pid,
        )

    agreement = _agreement()
    try:
        assert origin_coordinator.send(_event()) == 1
        result = executor_coordinator.receive_and_reply(
            executor.environment.init_pid,
            {HypervisorDomain.PROCESS: launch_handler},
            encode_pid,
        )
        assert result is not None and result.effect == {"pid": 2} and result.executed is True
        first_result = origin_coordinator.receive_result()
        assert first_result is not None and first_result.replayed is False
        assert calls["count"] == 1

        origin_checkpoint = CrossTransportDuplexRecoveryCoordinator.checkpoint(
            request_origin_transport,
            origin_request,
            response_origin_transport,
            origin_response,
            origin,
            agreement,
            role="origin",
        )
        executor_checkpoint = CrossTransportDuplexRecoveryCoordinator.checkpoint(
            request_executor_transport,
            executor_request,
            response_executor_transport,
            executor_response,
            executor,
            agreement,
            role="executor",
        )
        assert DuplexTransportMigrationCheckpoint.from_snapshot(origin_checkpoint.snapshot()).snapshot() == origin_checkpoint.snapshot()
        assert DuplexTransportMigrationCheckpoint.from_snapshot(executor_checkpoint.snapshot()).snapshot() == executor_checkpoint.snapshot()
    finally:
        for transport in (
            request_origin_transport,
            request_executor_transport,
            response_executor_transport,
            response_origin_transport,
        ):
            if not transport.closed:
                transport.close()

    target = InMemoryTransport()
    migrated_origin = CrossTransportDuplexRecoveryCoordinator.migrate(origin_checkpoint, agreement, target)
    migrated_executor = CrossTransportDuplexRecoveryCoordinator.migrate(executor_checkpoint, agreement, target)
    assert migrated_origin.status().request_pending_sequences == (1,)
    assert migrated_executor.status().response_pending_sequences == (1,)

    assert migrated_executor.retry() == ()
    replay = migrated_origin.receive_result()
    assert replay is not None and replay.replayed is True and replay.effect == {"pid": 2}
    assert migrated_origin.service() == (1,)
    assert migrated_executor.service() == (1,)
    assert migrated_executor.receive_and_reply(2, {HypervisorDomain.PROCESS: launch_handler}, encode_pid) is None
    assert calls["count"] == 1
    assert len(migrated_executor.operating_system.environment.kernel.processes) == 2
    assert target.pending() == 0


def test_duplex_migration_rejects_invalid_response_ledger_before_target_import() -> None:
    """Mathematics: invalid `S_result` implies `Q_target'=Q_target` under joint shadow preflight."""

    policy = ReliabilityPolicy(window_size=2)
    transports = _channels(policy)
    (
        request_origin_transport,
        _request_executor_transport,
        _response_executor_transport,
        response_origin_transport,
        origin_request,
        _executor_request,
        _executor_response,
        origin_response,
    ) = transports
    agreement = _agreement()
    try:
        checkpoint = CrossTransportDuplexRecoveryCoordinator.checkpoint(
            request_origin_transport,
            origin_request,
            response_origin_transport,
            origin_response,
            HeadlessOS(),
            agreement,
            role="origin",
        )
    finally:
        for transport in transports[:4]:
            if not transport.closed:
                transport.close()

    invalid = replace(checkpoint, response_channel={"version": 999})
    target = InMemoryTransport()
    before = target.snapshot()
    with pytest.raises(TransportMigrationError, match="preflight"):
        CrossTransportDuplexRecoveryCoordinator.migrate(invalid, agreement, target)
    assert target.snapshot() == before
