from __future__ import annotations

import pytest

from mailcpu import (
    HeadlessOS,
    HypervisorArbitrationEvent,
    HypervisorDomain,
    HypervisorOperationRecoveryCoordinator,
    HypervisorRequest,
    OperationRecoveryCheckpoint,
    RecoveryCoordinatorError,
    ReliabilityPolicy,
    ReliableChannel,
    SocketTransport,
)


def _tcp_pair() -> tuple[SocketTransport, SocketTransport]:
    """Mathematics: create reciprocal AF_INET transports `T_origin↔T_replica` with bound peer identities."""

    listener = SocketTransport.listen("127.0.0.1", 0)
    port = listener.getsockname()[1]
    origin = SocketTransport.connect("127.0.0.1", port, "origin", "replica")
    replica = SocketTransport.accept(listener, "replica", "origin")
    listener.close()
    return origin, replica


def _event() -> HypervisorArbitrationEvent:
    """Mathematics: construct one sender event `e=(origin,ops,1,t,Q)` whose operation requires `execute`."""

    return HypervisorArbitrationEvent(
        "origin",
        "ops",
        1,
        100,
        HypervisorRequest(
            "spawn process executable file child image",
            "/bin/child.mca",
            {"path": "/bin/child.mca"},
            frozenset({"execute"}),
            frozenset({"execute"}),
        ),
    )


def test_operation_recovery_coordinator_rebinds_lost_ack_and_replays_effect() -> None:
    """Mathematics: `restore(C_op);retry;receive` preserves one child and one effect under lost `ACK(1)`."""

    origin_transport, replica_transport = _tcp_pair()
    policy = ReliabilityPolicy(lease_ticks=1, max_attempts=3, window_size=4)
    origin = HeadlessOS()
    replica = HeadlessOS()
    replica.install_source("/bin/child.mca", "HALT\n")
    origin_coordinator = HypervisorOperationRecoveryCoordinator(
        origin_transport,
        ReliableChannel(origin_transport, "origin", "replica", "ops", policy),
        origin,
        direction="outbound",
    )
    replica_coordinator = HypervisorOperationRecoveryCoordinator(
        replica_transport,
        ReliableChannel(replica_transport, "replica", "replica", "ops", policy, peer="origin"),
        replica,
        direction="inbound",
    )
    calls = {"count": 0}

    def encode_pid(child_pid: int) -> dict[str, int]:
        """Mathematics: encode child identity `p` as canonical replay effect `{"pid":p}`."""

        return {"pid": int(child_pid)}

    def launch_handler() -> int:
        """Mathematics: execute one replica process transition `P↦P∪{child}`."""

        calls["count"] += 1
        return replica_coordinator.operating_system.launch_file(
            "/bin/child.mca",
            parent_pid=replica_coordinator.operating_system.environment.init_pid,
            loader_pid=replica_coordinator.operating_system.environment.init_pid,
        )

    try:
        assert origin_coordinator.send(_event()) == 1
        first = replica_coordinator.receive_and_execute(
            replica_coordinator.operating_system.environment.init_pid,
            {HypervisorDomain.PROCESS: launch_handler},
            encode_pid,
        )
        assert first is not None and first.executed is True and first.effect == {"pid": 2}
        assert calls["count"] == 1
        assert origin_coordinator.status().pending_sequences == (1,)
        assert replica_coordinator.status().next_receive_sequence == 2

        origin_transport.close()
        replica_transport.close()
        origin_checkpoint = origin_coordinator.checkpoint(
            origin_transport,
            origin_coordinator.channel,
            origin,
            direction="outbound",
        )
        replica_checkpoint = replica_coordinator.checkpoint(
            replica_transport,
            replica_coordinator.channel,
            replica,
            direction="inbound",
        )
        assert OperationRecoveryCheckpoint.from_snapshot(origin_checkpoint.snapshot()).snapshot() == origin_checkpoint.snapshot()

        rebound_origin, rebound_replica = _tcp_pair()
        restored_origin = HypervisorOperationRecoveryCoordinator.rebind(
            origin_checkpoint,
            rebound_origin.socket,
            direction="outbound",
            peer="replica",
        )
        restored_replica = HypervisorOperationRecoveryCoordinator.rebind(
            replica_checkpoint,
            rebound_replica.socket,
            direction="inbound",
            peer="origin",
        )
        restored_calls = {"count": 0}

        def restored_handler() -> int:
            """Mathematics: a second call would increase `|P|`, so replay must keep this counter at zero."""

            restored_calls["count"] += 1
            return restored_replica.operating_system.launch_file(
                "/bin/child.mca",
                parent_pid=restored_replica.operating_system.environment.init_pid,
                loader_pid=restored_replica.operating_system.environment.init_pid,
            )

        assert restored_origin.retry() == ()
        replay = restored_replica.receive_and_execute(
            restored_replica.operating_system.environment.init_pid,
            {HypervisorDomain.PROCESS: restored_handler},
            encode_pid,
        )
        assert replay is not None and replay.replayed is True and replay.effect == first.effect
        assert restored_calls["count"] == 0
        assert len(restored_replica.operating_system.environment.kernel.processes) == 2
        assert restored_origin.service() == (1,)
        assert restored_origin.status().pending_sequences == ()
        assert restored_replica.operating_system.environment.kernel.journal.verify()
    finally:
        for transport in (origin_transport, replica_transport):
            if not transport.closed:
                transport.close()


def test_operation_recovery_coordinator_refuses_direction_before_rebind() -> None:
    """Mathematics: `direction'≠direction(C_op)` is rejected before `bind(rebind(T),...)` consumes the new socket."""

    origin_transport, replica_transport = _tcp_pair()
    policy = ReliabilityPolicy(lease_ticks=1, max_attempts=2, window_size=2)
    origin = HeadlessOS()
    coordinator = HypervisorOperationRecoveryCoordinator(
        origin_transport,
        ReliableChannel(origin_transport, "origin", "replica", "ops", policy),
        origin,
        direction="outbound",
    )
    checkpoint = coordinator.checkpoint(origin_transport, coordinator.channel, origin, direction="outbound")
    origin_transport.close()
    replica_transport.close()
    rebound_origin, rebound_replica = _tcp_pair()
    try:
        with pytest.raises(RecoveryCoordinatorError, match="direction"):
            HypervisorOperationRecoveryCoordinator.rebind(
                checkpoint,
                rebound_origin.socket,
                direction="inbound",
                peer="replica",
            )
    finally:
        rebound_origin.close()
        rebound_replica.close()
