from __future__ import annotations

import pytest

from mailcpu import (
    HeadlessOS,
    HypervisorSeedCommitChannel,
    HypervisorSeedCommitRecoveryCoordinator,
    HypervisorSeedCommitResultChannel,
    RecoveryCoordinatorError,
    ReliabilityPolicy,
    ReliableChannel,
    SeedCommitRequest,
    SeedCommitRecoveryCheckpoint,
    SystemIdentity,
    SystemSeed,
    SystemSeedEnvelope,
    SocketTransport,
)
from mailcpu.programs import wait_send_program


def _tcp_pair() -> tuple[SocketTransport, SocketTransport]:
    """Mathematics: create one reciprocal full-duplex stream `T_origin↔T_executor` with fixed endpoint identities."""

    listener = SocketTransport.listen("127.0.0.1", 0)
    port = listener.getsockname()[1]
    origin = SocketTransport.connect("127.0.0.1", port, "origin", "executor")
    executor = SocketTransport.accept(listener, "executor", "origin")
    listener.close()
    return origin, executor


def _machine(system_id: str) -> tuple[HeadlessOS, int]:
    """Mathematics: construct an admitted blocked orbit `S₀` and target process `p` for one seed transition."""

    machine = HeadlessOS()
    pid = machine.spawn(wait_send_program(), f"{system_id}-input")
    envelope = SystemSeedEnvelope(SystemIdentity(system_id, 1), "origin", "seed", SystemSeed.from_system(machine))
    assert machine.seed_admission.admit(envelope).accepted
    return machine, pid


def _channels(
    origin_transport: SocketTransport,
    executor_transport: SocketTransport,
) -> tuple[
    HypervisorSeedCommitChannel,
    HypervisorSeedCommitChannel,
    HypervisorSeedCommitResultChannel,
    HypervisorSeedCommitResultChannel,
]:
    """Mathematics: bind request/result reliable products to one physical duplex stream without duplicating transport state."""

    policy = ReliabilityPolicy(lease_ticks=1, max_attempts=4, window_size=8)
    request_origin = HypervisorSeedCommitChannel(
        ReliableChannel(origin_transport, "origin", "executor", "seed.commit.request", policy)
    )
    request_executor = HypervisorSeedCommitChannel(
        ReliableChannel(executor_transport, "executor", "executor", "seed.commit.request", policy, peer="origin")
    )
    result_executor = HypervisorSeedCommitResultChannel(
        ReliableChannel(executor_transport, "executor", "origin", "seed.commit.result", policy),
        operation_source="origin",
        operation_channel="seed.commit.request",
    )
    result_origin = HypervisorSeedCommitResultChannel(
        ReliableChannel(origin_transport, "origin", "origin", "seed.commit.result", policy, peer="executor"),
        operation_source="origin",
        operation_channel="seed.commit.request",
    )
    return request_origin, request_executor, result_executor, result_origin


def _request(machine: HeadlessOS, pid: int) -> SeedCommitRequest:
    """Mathematics: bind request precondition `d_before` to the executor's admitted seed before sending it."""

    envelope = machine.seed_admission.current("remote-system")
    assert envelope is not None
    return SeedCommitRequest("remote-system", "resolver", 1, pid, "inbox", (42,), envelope.state_digest)


def test_seed_commit_recovery_rebinds_lost_result_and_commits_once() -> None:
    """Mathematics: after `commit→lost result→rebind→retry`, the executor has one transition and the origin receives one result."""

    origin_transport, executor_transport = _tcp_pair()
    origin_machine = HeadlessOS()
    executor_machine, pid = _machine("remote-system")
    request_origin, request_executor, result_executor, result_origin = _channels(origin_transport, executor_transport)
    origin = HypervisorSeedCommitRecoveryCoordinator(
        origin_transport,
        request_origin,
        result_origin,
        origin_machine,
        role="origin",
    )
    executor = HypervisorSeedCommitRecoveryCoordinator(
        executor_transport,
        request_executor,
        result_executor,
        executor_machine,
        role="executor",
    )
    try:
        assert origin.send(_request(executor_machine, pid)) == 1
        committed = executor.receive_and_commit()
        assert committed is not None and committed.accepted
        assert executor_machine.vm.scheduler.tick == 1

        origin_checkpoint = origin.checkpoint()
        executor_checkpoint = executor.checkpoint()
        origin_transport.close()
        executor_transport.close()

        rebound_origin, rebound_executor = _tcp_pair()
        restored_origin = HypervisorSeedCommitRecoveryCoordinator.rebind(
            origin_checkpoint,
            rebound_origin.socket,
            role="origin",
            peer="executor",
        )
        restored_executor = HypervisorSeedCommitRecoveryCoordinator.rebind(
            executor_checkpoint,
            rebound_executor.socket,
            role="executor",
            peer="origin",
        )
        try:
            assert restored_origin.retry() == ()
            replay = restored_executor.receive_and_commit()
            assert replay is not None and replay.accepted and replay.replayed
            result = restored_origin.receive_result()
            assert result is not None and result.accepted and not result.replayed
            assert restored_executor.service() == (1,)
            assert restored_origin.service() == (1,)
            assert restored_executor.operating_system.vm.scheduler.tick == 1
            assert restored_executor.operating_system.seed_admission.current("remote-system").seed.coordinate == 1
            assert restored_origin.status().request_pending_sequences == ()
            assert restored_origin.status().response_pending_sequences == ()
            assert restored_executor.status().request_pending_sequences == ()
            assert restored_executor.status().response_pending_sequences == ()
        finally:
            restored_origin.close()
            restored_executor.close()
    finally:
        if not origin_transport.closed:
            origin_transport.close()
        if not executor_transport.closed:
            executor_transport.close()


def test_seed_commit_recovery_checkpoint_round_trip_preserves_both_ledgers() -> None:
    """Mathematics: `decode(encode(C))=C` for one shared transport and both request/result semantic ledgers."""

    origin_transport, executor_transport = _tcp_pair()
    origin_machine = HeadlessOS()
    executor_machine, pid = _machine("remote-system")
    request_origin, request_executor, result_executor, result_origin = _channels(origin_transport, executor_transport)
    executor = HypervisorSeedCommitRecoveryCoordinator(
        executor_transport,
        request_executor,
        result_executor,
        executor_machine,
        role="executor",
    )
    try:
        request_origin.send(_request(executor_machine, pid))
        executor.receive_and_commit()
        checkpoint = executor.checkpoint()
        assert SeedCommitRecoveryCheckpoint.from_snapshot(checkpoint.snapshot()).snapshot() == checkpoint.snapshot()
    finally:
        origin_transport.close()
        executor_transport.close()


def test_seed_commit_recovery_rejects_role_or_peer_mismatch() -> None:
    """Mathematics: `role'≠role(C)` or `peer'≠peer(C)` is rejected before the new socket is bound."""

    origin_transport, executor_transport = _tcp_pair()
    executor_machine, _pid = _machine("remote-system")
    _request_origin, request_executor, result_executor, _result_origin = _channels(origin_transport, executor_transport)
    executor = HypervisorSeedCommitRecoveryCoordinator(
        executor_transport,
        request_executor,
        result_executor,
        executor_machine,
        role="executor",
    )
    checkpoint = executor.checkpoint()
    origin_transport.close()
    executor_transport.close()
    rebound_origin, rebound_executor = _tcp_pair()
    try:
        with pytest.raises(RecoveryCoordinatorError, match="role"):
            HypervisorSeedCommitRecoveryCoordinator.rebind(
                checkpoint,
                rebound_executor.socket,
                role="origin",
                peer="origin",
            )
        with pytest.raises(RecoveryCoordinatorError, match="peer"):
            HypervisorSeedCommitRecoveryCoordinator.rebind(
                checkpoint,
                rebound_executor.socket,
                role="executor",
                peer="wrong-peer",
            )
    finally:
        rebound_origin.close()
        rebound_executor.close()
