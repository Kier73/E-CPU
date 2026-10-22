from __future__ import annotations

from mailcpu import (
    Capability,
    HeadlessOS,
    HypervisorArbitrationEvent,
    HypervisorDomain,
    HypervisorOperationChannel,
    HypervisorRequest,
    ReliabilityPolicy,
    ReliableChannel,
    SocketTransport,
)


def _tcp_pair() -> tuple[SocketTransport, SocketTransport]:
    """Mathematics: create one AF_INET stream `S_origin↔S_replica` with reciprocal endpoint identities."""

    listener = SocketTransport.listen("127.0.0.1", 0)
    port = listener.getsockname()[1]
    origin = SocketTransport.connect("127.0.0.1", port, "origin", "replica")
    replica = SocketTransport.accept(listener, "replica", "origin")
    listener.close()
    return origin, replica


def _event(sequence: int) -> HypervisorArbitrationEvent:
    """Mathematics: construct operation event `e=(origin,ops,sequence,t,Q)` with a sender-side authority claim."""

    return HypervisorArbitrationEvent(
        "origin",
        "ops",
        sequence,
        100 + sequence,
        HypervisorRequest(
            "spawn process executable file child image",
            "/bin/child.mca",
            {"path": "/bin/child.mca"},
            frozenset({"execute"}),
            frozenset({"execute"}),
        ),
    )


def test_operation_event_round_trips_over_real_tcp_and_receiver_rebuilds_authority() -> None:
    """Mathematics: `decode(encode(e))=e`, while receiver-local `G(pid)` overrides forged remote grants before `E[I]`."""

    origin_transport, replica_transport = _tcp_pair()
    policy = ReliabilityPolicy(lease_ticks=1, max_attempts=3, window_size=4)
    origin_channel = HypervisorOperationChannel(
        ReliableChannel(origin_transport, "origin", "replica", "ops", policy)
    )
    replica_channel = HypervisorOperationChannel(
        ReliableChannel(replica_transport, "replica", "replica", "ops", policy, peer="origin")
    )
    origin = HeadlessOS()
    replica = HeadlessOS()
    replica.install_source("/bin/child.mca", "HALT\n")
    calls = {"count": 0}

    def encode_pid(child_pid: int) -> dict[str, int]:
        """Mathematics: encode child identity `p` as canonical effect `{"pid":p}`."""

        return {"pid": int(child_pid)}

    def launch_handler() -> int:
        """Mathematics: perform one replica-local process transition `P↦P∪{child}`."""

        calls["count"] += 1
        return replica.launch_file(
            "/bin/child.mca",
            parent_pid=replica.environment.init_pid,
            loader_pid=replica.environment.init_pid,
        )

    def authorize_init(event: HypervisorArbitrationEvent) -> HypervisorArbitrationEvent:
        """Mathematics: bind remote request `e` to replica init capability relation `G(init,resource)`."""

        return replica.hypervisor_authorize_event(replica.environment.init_pid, event)

    try:
        event = _event(1)
        sequence = origin_channel.send(event)
        assert sequence == 1
        origin_transport.service()
        first = replica_channel.receive_and_execute(
            replica.hypervisor_arbitration,
            authorize_init,
            {HypervisorDomain.PROCESS: launch_handler},
            encode_pid,
        )
        assert first is not None and first.executed is True and first.effect == {"pid": 2}
        assert calls["count"] == 1
        assert len(replica.environment.kernel.processes) == 2

        origin_transport.close()
        replica_transport.close()
        origin_transport_snapshot = origin_transport.snapshot()
        replica_transport_snapshot = replica_transport.snapshot()
        origin_channel_snapshot = origin_channel.channel.snapshot()
        replica_channel_snapshot = replica_channel.channel.snapshot()
        replica_os_snapshot = replica.snapshot()

        rebound_origin, rebound_replica = _tcp_pair()
        restored_origin_transport = SocketTransport.from_snapshot(rebound_origin.socket, origin_transport_snapshot)
        restored_replica_transport = SocketTransport.from_snapshot(rebound_replica.socket, replica_transport_snapshot)
        restored_origin_channel = HypervisorOperationChannel(
            ReliableChannel.from_snapshot(origin_channel_snapshot, restored_origin_transport)
        )
        restored_replica = HeadlessOS.from_snapshot(replica_os_snapshot)
        restored_calls = {"count": 0}

        def restored_handler() -> int:
            """Mathematics: this would mutate `P`, so zero calls proves effect replay rather than duplicate launch."""

            restored_calls["count"] += 1
            return restored_replica.launch_file(
                "/bin/child.mca",
                parent_pid=restored_replica.environment.init_pid,
                loader_pid=restored_replica.environment.init_pid,
            )

        def authorize_restored(event: HypervisorArbitrationEvent) -> HypervisorArbitrationEvent:
            """Mathematics: reconstruct grants from restored replica capabilities, ignoring remote `granted_rights`."""

            return restored_replica.hypervisor_authorize_event(restored_replica.environment.init_pid, event)

        restored_replica_channel = HypervisorOperationChannel(
            ReliableChannel.from_snapshot(replica_channel_snapshot, restored_replica_transport)
        )
        assert restored_origin_channel.channel.tick() == ()
        assert restored_replica_transport.service() == 1
        replay = restored_replica_channel.receive_and_execute(
            restored_replica.hypervisor_arbitration,
            authorize_restored,
            {HypervisorDomain.PROCESS: restored_handler},
            encode_pid,
        )
        assert replay is not None and replay.replayed is True and replay.effect == first.effect
        assert restored_calls["count"] == 0
        assert len(restored_replica.environment.kernel.processes) == 2

        restored_origin_transport.service()
        assert restored_origin_channel.channel.process_ack() == (1,)

        limited_pid = restored_replica.environment.kernel.spawn(
            "limited-remote-launcher",
            capabilities=(Capability("/safe", frozenset({"read"})),),
            parent_pid=restored_replica.environment.init_pid,
        )
        forged_calls = {"count": 0}

        def forged_handler() -> dict[str, str]:
            """Mathematics: any call would violate receiver-local `¬execute⇒ΔP=0`, so the counter must remain zero."""

            forged_calls["count"] += 1
            return {"unexpected": "launch"}

        def authorize_limited(event: HypervisorArbitrationEvent) -> HypervisorArbitrationEvent:
            """Mathematics: apply the limited receiver relation `G(limited,resource)=∅` to the forged event."""

            return restored_replica.hypervisor_authorize_event(limited_pid, event)

        origin_channel_2 = HypervisorOperationChannel(restored_origin_channel.channel)
        assert origin_channel_2.send(_event(2)) == 2
        restored_replica_transport.service()
        denied = restored_replica_channel.receive_and_execute(
            restored_replica.hypervisor_arbitration,
            authorize_limited,
            {HypervisorDomain.PROCESS: forged_handler},
        )
        assert denied is not None and denied.executed is False and denied.effect is None
        assert forged_calls["count"] == 0
        restored_origin_transport.service()
        assert restored_origin_channel.channel.process_ack() == (2,)
        assert restored_replica.environment.kernel.journal.verify()
    finally:
        for transport in (origin_transport, replica_transport):
            if not transport.closed:
                transport.close()
