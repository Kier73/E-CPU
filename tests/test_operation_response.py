from __future__ import annotations

from mailcpu import (
    HeadlessOS,
    HypervisorArbitrationEvent,
    HypervisorDomain,
    HypervisorOperationChannel,
    HypervisorOperationResultChannel,
    HypervisorRequest,
    ReliabilityPolicy,
    ReliableChannel,
    SocketTransport,
)


def _tcp_pair(local: str, peer: str) -> tuple[SocketTransport, SocketTransport]:
    """Mathematics: create reciprocal AF_INET transports `T_local↔T_peer` with the requested endpoint identities."""

    listener = SocketTransport.listen("127.0.0.1", 0)
    port = listener.getsockname()[1]
    local_transport = SocketTransport.connect("127.0.0.1", port, local, peer)
    peer_transport = SocketTransport.accept(listener, peer, local)
    listener.close()
    return local_transport, peer_transport


def _event() -> HypervisorArbitrationEvent:
    """Mathematics: construct one operation `e=(origin,ops,1,t,Q)` requiring receiver-local `execute`."""

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


def test_operation_response_returns_effect_and_deduplicates_after_lost_response_ack() -> None:
    """Mathematics: `request→effect→response` returns one `e`, while a repeated response frame preserves `S[I]=e`."""

    request_origin_transport, request_replica_transport = _tcp_pair("origin", "replica")
    response_replica_transport, response_origin_transport = _tcp_pair("replica", "origin")
    policy = ReliabilityPolicy(lease_ticks=1, max_attempts=3, window_size=4)
    request_origin = HypervisorOperationChannel(
        ReliableChannel(request_origin_transport, "origin", "replica", "ops", policy)
    )
    request_replica = HypervisorOperationChannel(
        ReliableChannel(request_replica_transport, "replica", "replica", "ops", policy, peer="origin")
    )
    response_replica = HypervisorOperationResultChannel(
        ReliableChannel(response_replica_transport, "replica", "origin", "ops.result", policy),
        "origin",
        "ops",
    )
    response_origin = HypervisorOperationResultChannel(
        ReliableChannel(response_origin_transport, "origin", "origin", "ops.result", policy, peer="replica"),
        "origin",
        "ops",
    )
    replica = HeadlessOS()
    replica.install_source("/bin/child.mca", "HALT\n")
    calls = {"count": 0}

    def encode_pid(child_pid: int) -> dict[str, int]:
        """Mathematics: encode native child identity `p` as canonical response effect `{"pid":p}`."""

        return {"pid": int(child_pid)}

    def authorize(event: HypervisorArbitrationEvent) -> HypervisorArbitrationEvent:
        """Mathematics: derive receiver-local grants `G(init,resource)` before policy and effect evaluation."""

        return replica.hypervisor_authorize_event(replica.environment.init_pid, event)

    def launch_handler() -> int:
        """Mathematics: perform one native process transition `P↦P∪{child}` on the replica."""

        calls["count"] += 1
        return replica.launch_file(
            "/bin/child.mca",
            parent_pid=replica.environment.init_pid,
            loader_pid=replica.environment.init_pid,
        )

    try:
        assert request_origin.send(_event()) == 1
        execution = request_replica.receive_and_reply(
            replica.hypervisor_arbitration,
            authorize,
            {HypervisorDomain.PROCESS: launch_handler},
            response_replica,
            encode_pid,
        )
        assert execution is not None and execution.effect == {"pid": 2}
        received = response_origin.receive()
        assert received is not None
        assert received.replayed is False
        assert received.effect == execution.effect
        assert calls["count"] == 1
        assert request_origin.channel.process_ack() == (1,)
        assert len(replica.environment.kernel.processes) == 2

        response_replica_transport.close()
        response_origin_transport.close()
        response_sender_snapshot = response_replica.channel.snapshot()
        response_receiver_snapshot = response_origin.snapshot()

        rebound_response_replica, rebound_response_origin = _tcp_pair("replica", "origin")
        restored_response_sender = ReliableChannel.from_snapshot(
            response_sender_snapshot,
            SocketTransport.from_snapshot(rebound_response_replica.socket, response_replica_transport.snapshot()),
        )
        restored_response_receiver_transport = SocketTransport.from_snapshot(
            rebound_response_origin.socket,
            response_origin_transport.snapshot(),
        )
        restored_response_receiver = HypervisorOperationResultChannel.from_snapshot(
            response_receiver_snapshot,
            restored_response_receiver_transport,
        )
        assert restored_response_sender.tick() == ()
        replay = restored_response_receiver.receive()
        assert replay is not None
        assert replay.replayed is True
        assert replay.effect == received.effect
        assert restored_response_sender.process_ack() == (1,)
        assert restored_response_receiver.snapshot()["seen"]
        assert replica.environment.kernel.journal.verify()
    finally:
        for transport in (
            request_origin_transport,
            request_replica_transport,
            response_replica_transport,
            response_origin_transport,
        ):
            if not transport.closed:
                transport.close()
