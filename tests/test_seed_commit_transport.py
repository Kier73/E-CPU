from __future__ import annotations

import pytest

from mailcpu import (
    HeadlessOS,
    HypervisorSeedCommitChannel,
    HypervisorSeedCommitResultChannel,
    ReliabilityPolicy,
    ReliableChannel,
    SeedCommitRequest,
    SystemIdentity,
    SystemSeed,
    SystemSeedEnvelope,
    SocketTransport,
)
from mailcpu.programs import wait_send_program


def _tcp_pair() -> tuple[SocketTransport, SocketTransport]:
    """Mathematics: create reciprocal AF_INET transports `T_a↔T_b` with fixed endpoint identities."""

    listener = SocketTransport.listen("127.0.0.1", 0)
    port = listener.getsockname()[1]
    origin = SocketTransport.connect("127.0.0.1", port, "origin", "replica")
    replica = SocketTransport.accept(listener, "replica", "origin")
    listener.close()
    return origin, replica


def _machine() -> tuple[HeadlessOS, int]:
    """Mathematics: construct an admitted blocked orbit `S₀` with one deterministic input target `p`."""

    machine = HeadlessOS()
    pid = machine.spawn(wait_send_program(), "remote-input")
    origin = SystemSeed.from_system(machine)
    envelope = SystemSeedEnvelope(SystemIdentity("remote-system", 1), "origin", "seed", origin)
    assert machine.seed_admission.admit(envelope).accepted
    return machine, pid


def _channels(
    origin_transport: SocketTransport,
    replica_transport: SocketTransport,
) -> tuple[
    HypervisorSeedCommitChannel,
    HypervisorSeedCommitChannel,
    HypervisorSeedCommitResultChannel,
    HypervisorSeedCommitResultChannel,
]:
    """Mathematics: bind request `Q→R` and result `R→Q` FIFOs over one duplex transport pair."""

    policy = ReliabilityPolicy(lease_ticks=1, max_attempts=4, window_size=8)
    request_sender = HypervisorSeedCommitChannel(
        ReliableChannel(origin_transport, "origin", "replica", "seed.commit.request", policy)
    )
    request_receiver = HypervisorSeedCommitChannel(
        ReliableChannel(replica_transport, "replica", "replica", "seed.commit.request", policy, peer="origin")
    )
    result_sender = HypervisorSeedCommitResultChannel(
        ReliableChannel(replica_transport, "replica", "origin", "seed.commit.result", policy),
        operation_source="origin",
        operation_channel="seed.commit.request",
    )
    result_receiver = HypervisorSeedCommitResultChannel(
        ReliableChannel(origin_transport, "origin", "origin", "seed.commit.result", policy, peer="replica"),
        operation_source="origin",
        operation_channel="seed.commit.request",
    )
    return request_sender, request_receiver, result_sender, result_receiver


def _request(machine: HeadlessOS, pid: int, sequence: int = 1, values: tuple[int, ...] = (42,)) -> SeedCommitRequest:
    """Mathematics: bind an input request to the admitted pre-transition digest `d(S₀)` before transport."""

    current = machine.seed_admission.current("remote-system")
    assert current is not None
    return SeedCommitRequest(
        "remote-system",
        "resolver",
        sequence,
        pid,
        "inbox",
        values,
        current.state_digest,
    )


def test_remote_seed_commit_crosses_real_tcp_and_executes_once() -> None:
    """Mathematics: `decode(encode(r))=r`, and one request yields one live transition and one result."""

    origin_transport, replica_transport = _tcp_pair()
    machine, pid = _machine()
    request_sender, request_receiver, result_sender, result_receiver = _channels(origin_transport, replica_transport)
    try:
        request = _request(machine, pid)
        assert SeedCommitRequest.from_dict(request.to_dict()).to_dict() == request.to_dict()
        assert request_sender.send(request) == 1
        result = request_receiver.receive_and_commit(machine, result_sender)
        assert result is not None and result.accepted and not result.replayed
        response = result_receiver.receive()
        assert response is not None and response.accepted and not response.replayed
        assert response.envelope is not None
        assert response.envelope.seed.coordinate == 1
        assert machine.vm.scheduler.tick == 1
        assert machine.seed_admission.current("remote-system").snapshot() == response.envelope.snapshot()
    finally:
        origin_transport.close()
        replica_transport.close()


def test_remote_seed_commit_reuses_cached_result_when_response_send_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mathematics: if `commit(r)` precedes `reply(r)`, retry satisfies `effect_count(r)=1` and returns cached `R(r)`."""

    origin_transport, replica_transport = _tcp_pair()
    machine, pid = _machine()
    request_sender, request_receiver, result_sender, result_receiver = _channels(origin_transport, replica_transport)
    original_send = result_sender.send
    calls = {"send": 0}

    def fail_once(result: object) -> int:
        """Mathematics: model one lost response `reply₁(r)=⊥` while leaving the committed receiver state intact."""

        calls["send"] += 1
        if calls["send"] == 1:
            raise OSError("simulated lost response")
        return original_send(result)

    monkeypatch.setattr(result_sender, "send", fail_once)
    try:
        request_sender.send(_request(machine, pid))
        with pytest.raises(OSError, match="lost response"):
            request_receiver.receive_and_commit(machine, result_sender)
        assert machine.vm.scheduler.tick == 1
        replay = request_receiver.receive_and_commit(machine, result_sender)
        assert replay is not None and replay.accepted and replay.replayed
        response = result_receiver.receive()
        assert response is not None and response.accepted
        assert machine.vm.scheduler.tick == 1
        assert machine.seed_admission.current("remote-system").seed.coordinate == 1
    finally:
        origin_transport.close()
        replica_transport.close()


def test_remote_seed_commit_result_duplicate_is_semantic_replay() -> None:
    """Mathematics: a retransmitted result with the same request identity satisfies `R[I]=R[I]` without reapplying input."""

    origin_transport, replica_transport = _tcp_pair()
    machine, pid = _machine()
    request_sender, request_receiver, result_sender, result_receiver = _channels(origin_transport, replica_transport)
    try:
        request_sender.send(_request(machine, pid))
        first = request_receiver.receive_and_commit(machine, result_sender)
        assert first is not None
        delivered = result_receiver.receive()
        assert delivered is not None and not delivered.replayed
        result_sender.channel.tick()
        replay = result_receiver.receive()
        assert replay is not None and replay.replayed
        assert replay.request_fingerprint == delivered.request_fingerprint
        assert machine.vm.scheduler.tick == 1
    finally:
        origin_transport.close()
        replica_transport.close()


def test_remote_seed_commit_same_input_identity_on_new_frame_is_replayed() -> None:
    """Mathematics: a new transport frame carrying the same input identity returns `replayed=1` without advancing virtual time."""

    origin_transport, replica_transport = _tcp_pair()
    machine, pid = _machine()
    request_sender, request_receiver, result_sender, result_receiver = _channels(origin_transport, replica_transport)
    try:
        request = _request(machine, pid)
        request_sender.send(request)
        first = request_receiver.receive_and_commit(machine, result_sender)
        assert first is not None and first.accepted and not first.replayed
        assert result_receiver.receive() is not None
        request_sender.send(request)
        replay = request_receiver.receive_and_commit(machine, result_sender)
        assert replay is not None and replay.accepted and replay.replayed
        assert result_receiver.receive() is not None
        assert machine.vm.scheduler.tick == 1
    finally:
        origin_transport.close()
        replica_transport.close()


def test_remote_seed_commit_refuses_stale_precondition_without_mutation() -> None:
    """Mathematics: `d(request.base)≠d(host)` implies refusal and `host_after=host_before`."""

    origin_transport, replica_transport = _tcp_pair()
    machine, pid = _machine()
    request_sender, request_receiver, result_sender, result_receiver = _channels(origin_transport, replica_transport)
    before = machine.snapshot()
    try:
        stale = _request(machine, pid)
        stale = SeedCommitRequest(
            stale.system_id,
            stale.source,
            stale.sequence,
            stale.pid,
            stale.mailbox,
            stale.values,
            "f" * 64,
        )
        request_sender.send(stale)
        result = request_receiver.receive_and_commit(machine, result_sender)
        assert result is not None and not result.accepted
        assert "precondition" in (result.reason or "")
        assert result_receiver.receive() == result
        assert machine.snapshot() == before
    finally:
        origin_transport.close()
        replica_transport.close()


def test_remote_seed_commit_refuses_conflicting_input_sequence() -> None:
    """Mathematics: an equal input identity with unequal payload `f(e')≠f(e)` is refused without a second transition."""

    origin_transport, replica_transport = _tcp_pair()
    machine, pid = _machine()
    request_sender, request_receiver, result_sender, result_receiver = _channels(origin_transport, replica_transport)
    try:
        request_sender.send(_request(machine, pid, sequence=1, values=(42,)))
        first = request_receiver.receive_and_commit(machine, result_sender)
        assert first is not None and first.accepted
        assert result_receiver.receive() is not None
        request_sender.send(_request(machine, pid, sequence=1, values=(99,)))
        conflict = request_receiver.receive_and_commit(machine, result_sender)
        assert conflict is not None and not conflict.accepted
        assert "conflicting" in (conflict.reason or "")
        assert result_receiver.receive() == conflict
        assert machine.vm.scheduler.tick == 1
    finally:
        origin_transport.close()
        replica_transport.close()


def test_remote_seed_commit_ledgers_round_trip_after_execution() -> None:
    """Mathematics: `decode(encode(Q,L,S))=(Q,L,S)` preserves reliable cursors and both semantic ledgers."""

    origin_transport, replica_transport = _tcp_pair()
    machine, pid = _machine()
    request_sender, request_receiver, result_sender, result_receiver = _channels(origin_transport, replica_transport)
    try:
        request_sender.send(_request(machine, pid))
        assert request_receiver.receive_and_commit(machine, result_sender) is not None
        assert result_receiver.receive() is not None
        request_snapshot = request_receiver.snapshot()
        result_snapshot = result_receiver.snapshot()
        restored_request = HypervisorSeedCommitChannel.from_snapshot(request_snapshot, replica_transport)
        restored_result = HypervisorSeedCommitResultChannel.from_snapshot(result_snapshot, origin_transport)
        assert restored_request.snapshot() == request_snapshot
        assert restored_result.snapshot() == result_snapshot
    finally:
        origin_transport.close()
        replica_transport.close()
