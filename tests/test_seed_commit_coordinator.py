from __future__ import annotations

import threading
import time

import pytest

from mailcpu import (
    DurableSeedCommitJournal,
    DurableSeedCommitLedger,
    HeadlessOS,
    HypervisorSeedCommitChannel,
    HypervisorSeedCommitResultChannel,
    HypervisorSeedCommitRecoveryCoordinator,
    ReliabilityPolicy,
    ReliableChannel,
    RecoveryCoordinatorError,
    SeedCommitMembership,
    SeedCommitLedgerError,
    SeedCommitQuorumCoordinator,
    SeedCommitQuorumError,
    SeedCommitPeerLink,
    SeedCommitQuorumRecoveryCheckpoint,
    SeedCommitServiceRecoveryCheckpoint,
    SeedCommitRequest,
    SeedCommitQuorumParticipant,
    SystemIdentity,
    SystemSeed,
    SystemSeedEnvelope,
    TrajectoryReader,
    TrajectoryWriter,
    SEED_QUORUM_REQUEST_CHANNEL,
    SEED_QUORUM_RESPONSE_CHANNEL,
    SocketTransport,
)
from mailcpu.programs import wait_send_program


def _tcp_pair(peer: str = "B") -> tuple[SocketTransport, SocketTransport]:
    """Mathematics: construct reciprocal streams `A↔peer` whose framed mailbox projections preserve FIFO identities."""

    listener = SocketTransport.listen("127.0.0.1", 0)
    port = listener.getsockname()[1]
    owner_transport = SocketTransport.connect("127.0.0.1", port, "A", peer)
    peer_transport = SocketTransport.accept(listener, peer, "A")
    listener.close()
    return owner_transport, peer_transport


def _admitted_machine(system_id: str = "quorum-system") -> tuple[HeadlessOS, int]:
    """Mathematics: construct `OS₀` with one blocked input process and admitted seed digest `d₀` as its genesis coordinate."""

    machine = HeadlessOS()
    pid = machine.spawn(wait_send_program(), "quorum-input")
    seed = SystemSeed.from_system(machine)
    envelope = SystemSeedEnvelope(SystemIdentity(system_id, 1), "origin", "quorum", seed)
    assert machine.seed_admission.admit(envelope).accepted
    return machine, pid


def _live_pair(
    tmp_path,
    *,
    delayed_peer_seconds: float = 0.08,
    members: tuple[str, ...] = ("A", "B", "C"),
):
    """Mathematics: assemble a three-member fixed group with two TCP peer paths and independent durable participant state."""

    owner, pid = _admitted_machine()
    genesis = SystemSeed.from_system(owner).origin_digest
    membership = SeedCommitMembership("quorum-system", 1, members, "A", 1, genesis)
    owner_ledger = DurableSeedCommitLedger(tmp_path / "A.quorum", "A", membership)
    owner_journal = DurableSeedCommitJournal(tmp_path / "A.publication", "A")
    coordinator = SeedCommitQuorumCoordinator(membership, owner_ledger, owner, owner_journal, {}, retry_interval=0.02)
    policy = ReliabilityPolicy(lease_ticks=4, max_attempts=8, window_size=16)
    stopping = threading.Event()
    failures: list[Exception] = []
    peer_nodes = {}
    for member in ("B", "C"):
        replica = HeadlessOS.from_snapshot(owner.snapshot())
        replica_ledger = DurableSeedCommitLedger(tmp_path / f"{member}.quorum", member, membership)
        replica_journal = DurableSeedCommitJournal(tmp_path / f"{member}.publication", member)
        owner_transport, replica_transport = _tcp_pair(member)
        owner_requests = ReliableChannel(
            owner_transport, "A", member, SEED_QUORUM_REQUEST_CHANNEL, policy, peer=member
        )
        owner_responses = ReliableChannel(
            owner_transport, member, "A", SEED_QUORUM_RESPONSE_CHANNEL, policy, peer=member
        )
        replica_inbound = ReliableChannel(
            replica_transport, "A", member, SEED_QUORUM_REQUEST_CHANNEL, policy, peer="A"
        )
        replica_outbound = ReliableChannel(
            replica_transport, member, "A", SEED_QUORUM_RESPONSE_CHANNEL, policy, peer="A"
        )
        participant = SeedCommitQuorumParticipant(
            replica_ledger, replica_inbound, replica_outbound, replica, replica_journal
        )

        def service_peer(delay: float = 0.0, current_participant=participant) -> None:
            """Mathematics: repeatedly apply `P_{n+1}=service(P_n)` while preserving retryable failures and FIFO order."""

            if delay:
                time.sleep(delay)
            while not stopping.is_set():
                try:
                    if not current_participant.service_once():
                        time.sleep(0.001)
                except Exception as error:
                    failures.append(error)
                    time.sleep(0.001)

        worker = threading.Thread(
            target=service_peer,
            args=(delayed_peer_seconds if member == "C" else 0.0,),
            daemon=True,
        )
        worker.start()
        coordinator.peers[member] = SeedCommitPeerLink(member, owner_requests, owner_responses)
        peer_nodes[member] = {
            "operating_system": replica,
            "ledger": replica_ledger,
            "journal": replica_journal,
            "participant": participant,
            "owner_transport": owner_transport,
            "replica_transport": replica_transport,
            "worker": worker,
        }
    return {
        "owner": owner,
        "replica": peer_nodes["B"]["operating_system"],
        "peer_nodes": peer_nodes,
        "pid": pid,
        "membership": membership,
        "owner_ledger": owner_ledger,
        "replica_ledger": peer_nodes["B"]["ledger"],
        "owner_journal": owner_journal,
        "replica_journal": peer_nodes["B"]["journal"],
        "coordinator": coordinator,
        "participant": peer_nodes["B"]["participant"],
        "stopping": stopping,
        "failures": failures,
    }


def _close_pair(context) -> None:
    """Mathematics: transition worker `run→stop`, join it, and close both finite socket endpoints exactly once."""

    context["stopping"].set()
    for node in context["peer_nodes"].values():
        node["worker"].join(timeout=1)
        node["owner_transport"].close()
        node["replica_transport"].close()


def _request(machine: HeadlessOS, pid: int) -> SeedCommitRequest:
    """Mathematics: bind one mailbox input `q` to current admitted state digest `d₀` before deterministic preview."""

    current = machine.seed_admission.current("quorum-system")
    assert current is not None
    return SeedCommitRequest("quorum-system", "resolver", 1, pid, "inbox", (42,), current.state_digest)


def _client_seed_channels(context):
    """Mathematics: construct reciprocal TCP channels with request identity `(client,seed.input,n)` and typed result binding."""

    owner_transport, client_transport = _tcp_pair("client")
    policy = ReliabilityPolicy(lease_ticks=4, max_attempts=8, window_size=16)
    client_requests = ReliableChannel(client_transport, "client", "A", "seed.input", policy, peer="A")
    owner_requests = ReliableChannel(owner_transport, "A", "A", "seed.input", policy, peer="client")
    owner_results = ReliableChannel(owner_transport, "A", "client", "seed.result", policy, peer="client")
    client_results = ReliableChannel(client_transport, "A", "client", "seed.result", policy, peer="A")
    typed_requests = HypervisorSeedCommitChannel(owner_requests)
    typed_results = HypervisorSeedCommitResultChannel(owner_results, "client", "seed.input")
    recovery = HypervisorSeedCommitRecoveryCoordinator(
        owner_transport,
        typed_requests,
        typed_results,
        context["owner"],
        role="executor",
        quorum_coordinator=context["coordinator"],
    )
    return (
        owner_transport,
        client_transport,
        HypervisorSeedCommitChannel(client_requests),
        typed_requests,
        typed_results,
        HypervisorSeedCommitResultChannel(client_results, "client", "seed.input"),
        recovery,
    )


def test_quorum_seed_request_waits_for_decision_and_retries_same_fifo_head(tmp_path) -> None:
    """Mathematics: without quorum `r=1` and `OS=OS₀`; retry of the same `r` resumes its one prepared proposal."""

    context = _live_pair(tmp_path)
    owner_transport, client_transport, sender, receiver, result_channel, result_reader, recovery = _client_seed_channels(context)
    try:
        request = _request(context["owner"], context["pid"])
        assert sender.send(request) == 1
        before = context["owner"].snapshot()
        reachable = context["coordinator"].peers
        context["coordinator"].peers = {}
        with pytest.raises(SeedCommitQuorumError, match="prepare quorum unavailable"):
            recovery.receive_and_commit(timeout=0.05)
        assert receiver.channel.next_receive_sequence == 1
        assert receiver.channel.peek() is not None
        assert context["owner"].snapshot() == before
        assert context["owner_journal"].snapshot()["operations"] == 0
        prepared = context["owner_ledger"].proposal_for_request_identity(("client", "seed.input", 1))
        assert prepared is not None and prepared[1] is not None

        context["coordinator"].peers = reachable
        result = recovery.receive_and_commit()
        delivered = result_reader.receive()
        assert result is not None and result.accepted and not result.replayed
        assert delivered == result
        assert receiver.channel.next_receive_sequence == 2
        assert context["owner"].snapshot() == context["replica"].snapshot()
        assert context["owner"].vm.scheduler.tick == 1
        assert context["owner_ledger"].snapshot()["prepared"] == 1
    finally:
        _close_pair(context)
        owner_transport.close()
        client_transport.close()


def test_quorum_seed_request_lost_response_reuses_durable_result(tmp_path, monkeypatch) -> None:
    """Mathematics: response loss after publish preserves `effect_count(q)=1`; exact request retry reads its fsynced result."""

    context = _live_pair(tmp_path)
    owner_transport, client_transport, sender, receiver, result_channel, result_reader, recovery = _client_seed_channels(context)
    original_send = result_channel.send
    calls = {"count": 0}

    def fail_once(result):
        """Mathematics: erase one response projection while leaving quorum publication and request FIFO unacknowledged."""

        calls["count"] += 1
        if calls["count"] == 1:
            raise OSError("injected lost client response")
        return original_send(result)

    monkeypatch.setattr(result_channel, "send", fail_once)
    try:
        request = _request(context["owner"], context["pid"])
        sender.send(request)
        with pytest.raises(OSError, match="lost client response"):
            recovery.receive_and_commit()
        committed = context["owner"].snapshot()
        assert receiver.channel.next_receive_sequence == 1
        assert context["owner_journal"].lookup(("client", "seed.input", 1), request.fingerprint) is not None

        replay = recovery.receive_and_commit()
        delivered = result_reader.receive()
        assert replay is not None and replay.accepted and replay.replayed
        assert delivered is not None and delivered.accepted and delivered.replayed
        assert context["owner"].snapshot() == committed
        assert context["owner"].vm.scheduler.tick == 1
        assert context["owner_ledger"].snapshot()["prepared"] == 1
        assert calls["count"] == 2
    finally:
        _close_pair(context)
        owner_transport.close()
        client_transport.close()


def test_quorum_seed_gateway_durably_refuses_stale_precondition_without_host_mutation(tmp_path) -> None:
    """Mathematics: `d(request.base)≠d(host)` produces durable `accepted=0`, consumes the FIFO, and leaves `OS'=OS`."""

    context = _live_pair(tmp_path)
    owner_transport, client_transport, sender, receiver, result_channel, result_reader, recovery = _client_seed_channels(context)
    before = context["owner"].snapshot()
    try:
        current = context["owner"].seed_admission.current("quorum-system")
        assert current is not None
        stale = SeedCommitRequest(
            "quorum-system", "resolver", 1, context["pid"], "inbox", (42,), "f" * 64
        )
        sender.send(stale)
        result = recovery.receive_and_commit()
        delivered = result_reader.receive()
        assert result is not None and not result.accepted and "precondition" in (result.reason or "")
        assert delivered == result
        assert receiver.channel.next_receive_sequence == 2
        assert context["owner"].snapshot() == before
        assert context["owner_journal"].lookup(("client", "seed.input", 1), stale.fingerprint) == result
        assert context["owner_ledger"].snapshot()["prepared"] == 0
    finally:
        _close_pair(context)
        owner_transport.close()
        client_transport.close()


def test_quorum_seed_semantic_retransmission_after_later_slot_does_not_mutate_replicas(tmp_path) -> None:
    """Mathematics: reusing committed input `e₁` on fresh frame `r₃` returns replay while `OS_after=OS_before` at slot 2."""

    context = _live_pair(tmp_path)
    owner_transport, client_transport, sender, receiver, result_channel, result_reader, recovery = _client_seed_channels(context)
    try:
        first_request = _request(context["owner"], context["pid"])
        sender.send(first_request)
        first = recovery.receive_and_commit()
        assert first is not None and first.accepted
        assert result_reader.receive() == first
        sender.channel.process_ack()

        current = context["owner"].seed_admission.current("quorum-system")
        assert current is not None
        second_request = SeedCommitRequest(
            "quorum-system", "resolver", 2, context["pid"], "inbox", (43,), current.state_digest
        )
        sender.send(second_request)
        second = recovery.receive_and_commit()
        assert second is not None and second.accepted and not second.replayed
        assert result_reader.receive() == second
        sender.channel.process_ack()
        before_replay = context["owner"].snapshot()
        committed = context["owner_ledger"].committed_state()

        sender.send(first_request)
        replay = recovery.receive_and_commit()
        delivered = result_reader.receive()
        assert replay is not None and replay.accepted and replay.replayed
        assert replay.request_sequence == 3
        assert delivered == replay
        assert context["owner"].snapshot() == before_replay
        assert context["replica"].snapshot() == before_replay
        assert context["owner_ledger"].committed_state() == committed
        assert context["owner"].vm.scheduler.tick == 2
    finally:
        _close_pair(context)
        owner_transport.close()
        client_transport.close()


def test_seed_commit_quorum_checkpoint_rebinds_all_peer_channel_products(tmp_path) -> None:
    """Mathematics: rebind preserves `M,L,J,OS,{T_i,Q_i,R_i}` exactly across every captured member link."""

    context = _live_pair(tmp_path)
    rebound = None
    try:
        checkpoint = SeedCommitQuorumRecoveryCheckpoint.capture(context["coordinator"])
        restored_checkpoint = SeedCommitQuorumRecoveryCheckpoint.from_snapshot(checkpoint.snapshot())
        context["stopping"].set()
        for node in context["peer_nodes"].values():
            node["worker"].join(timeout=1)
        raw_sockets = {
            member: node["owner_transport"].socket
            for member, node in context["peer_nodes"].items()
        }
        rebound = restored_checkpoint.rebind(raw_sockets)
        assert rebound.membership.digest == context["membership"].digest
        assert rebound.operating_system.snapshot() == context["owner"].snapshot()
        assert rebound.ledger.snapshot() == context["owner_ledger"].snapshot()
        assert rebound.durable_journal.snapshot() == context["owner_journal"].snapshot()
        assert set(rebound.peers) == {"B", "C"}
        for member in rebound.peers:
            assert rebound.peers[member].requests.snapshot() == context["coordinator"].peers[member].requests.snapshot()
            assert rebound.peers[member].responses.snapshot() == context["coordinator"].peers[member].responses.snapshot()
    finally:
        if rebound is not None:
            for link in rebound.peers.values():
                link.requests.transport.close()
        _close_pair(context)


def test_seed_commit_service_checkpoint_rebinds_ingress_and_quorum_on_one_host(tmp_path) -> None:
    """Mathematics: recovered ingress `I` and peer authority `Q` share `OS`, then process one client request through quorum."""

    context = _live_pair(tmp_path)
    ingress_transport, client_transport, sender, _typed_requests, _typed_results, result_reader, ingress = _client_seed_channels(context)
    rebound = None
    try:
        request = _request(context["owner"], context["pid"])
        sender.send(request)
        checkpoint = SeedCommitServiceRecoveryCheckpoint.capture(ingress)
        checkpoint = SeedCommitServiceRecoveryCheckpoint.from_snapshot(checkpoint.snapshot())
        assert checkpoint.ingress.role == "executor"
        assert checkpoint.quorum.operating_system == checkpoint.ingress.operating_system
        assert checkpoint.ingress.transport["queues"]
        assert checkpoint.ingress.request_channel["channel"]["next_receive_sequence"] == 1

        context["stopping"].set()
        for node in context["peer_nodes"].values():
            node["worker"].join(timeout=1)
        peer_sockets = {
            member: node["owner_transport"].socket
            for member, node in context["peer_nodes"].items()
        }
        rebound = checkpoint.rebind(peer_sockets, ingress_transport.socket, peer="client")
        assert rebound.quorum_coordinator is not None
        assert rebound.operating_system is rebound.quorum_coordinator.operating_system
        assert rebound.operating_system.snapshot() == checkpoint.ingress.operating_system
        assert rebound.checkpoint().snapshot() == checkpoint.ingress.snapshot()

        context["stopping"].clear()
        for node in context["peer_nodes"].values():
            participant = node["participant"]

            def serve(current_participant=participant) -> None:
                """Mathematics: iterate participant transition `Pₙ₊₁=service_once(Pₙ)` until the explicit stop event."""

                while not context["stopping"].is_set():
                    try:
                        if not current_participant.service_once():
                            time.sleep(0.001)
                    except Exception as error:
                        context["failures"].append(error)
                        time.sleep(0.001)

            worker = threading.Thread(target=serve, daemon=True)
            node["worker"] = worker
            worker.start()

        result = rebound.receive_and_commit(timeout=4.0)
        assert result is not None and result.accepted and not result.replayed
        assert result_reader.receive() == result
        sender.channel.process_ack()
        proposal = rebound.quorum_coordinator.ledger.proposal_at(1)
        assert proposal is not None
        expected_commit = (proposal.slot, proposal.result_state_digest)
        deadline = time.monotonic() + 2.0
        while any(
            node["ledger"].committed_state() != expected_commit
            for node in context["peer_nodes"].values()
        ) and time.monotonic() < deadline:
            time.sleep(0.002)
        assert all(
            node["ledger"].committed_state() == expected_commit
            for node in context["peer_nodes"].values()
        )
        assert all(
            node["operating_system"].snapshot() == rebound.operating_system.snapshot()
            for node in context["peer_nodes"].values()
        )
        assert not context["failures"]
        assert SystemSeed.from_system(rebound.operating_system).origin_digest == expected_commit[1]

        before_replay = rebound.operating_system.snapshot()
        sender.send(request)
        replay = rebound.receive_and_commit(timeout=4.0)
        assert replay is not None and replay.accepted and replay.replayed
        assert replay.request_sequence == 2
        assert result_reader.receive() == replay
        sender.channel.process_ack()
        assert rebound.operating_system.snapshot() == before_replay
        assert rebound.operating_system.vm.scheduler.tick == 1
    finally:
        context["stopping"].set()
        for node in context["peer_nodes"].values():
            node["worker"].join(timeout=1)
        if rebound is not None:
            rebound.transport.close()
            if rebound.quorum_coordinator is not None:
                for link in rebound.quorum_coordinator.peers.values():
                    link.requests.transport.close()
        else:
            ingress_transport.close()
        client_transport.close()
        _close_pair(context)


def test_seed_commit_service_checkpoint_rejects_mixed_host_cut(tmp_path) -> None:
    """Mathematics: reject composite `(Q, I)` whenever `OS_Q ≠ OS_I`, before any transport is rebound."""

    context = _live_pair(tmp_path)
    ingress_transport, client_transport, _sender, _typed_requests, _typed_results, _result_reader, ingress = _client_seed_channels(context)
    try:
        payload = SeedCommitServiceRecoveryCheckpoint.capture(ingress).snapshot()
        payload["ingress"]["operating_system"] = HeadlessOS().snapshot()
        with pytest.raises(RecoveryCoordinatorError, match="host snapshots differ"):
            SeedCommitServiceRecoveryCheckpoint.from_snapshot(payload)
    finally:
        ingress_transport.close()
        client_transport.close()
        _close_pair(context)


@pytest.mark.parametrize(
    "cut",
    ("owner_decision", "owner_publication", "response_send", "request_ack"),
)
def test_seed_commit_service_checkpoint_recovers_each_commit_response_ack_cut(tmp_path, monkeypatch, cut) -> None:
    """Mathematics: across four injected cuts, recover one durable state edge and preserve `effect_count(request)=1`."""

    context = _live_pair(tmp_path)
    ingress_transport, client_transport, sender, _typed_requests, _typed_results, result_reader, ingress = _client_seed_channels(context)
    rebound = None
    request = _request(context["owner"], context["pid"])
    sender.send(request)
    coordinator = context["coordinator"]

    if cut == "owner_decision":
        def crash_before_publish(_proposal, _result, _candidate):
            """Mathematics: terminate after durable decision quorum `q` but before owner journal publication `J_k`."""

            raise SystemExit(81)

        monkeypatch.setattr(coordinator, "_publish_owner", crash_before_publish)
    elif cut == "owner_publication":
        def crash_before_response(_result):
            """Mathematics: terminate after `fsync(J_k,OS_k)` but before any client result frame is emitted."""

            raise SystemExit(82)

        monkeypatch.setattr(ingress.response_channel, "send", crash_before_response)
    elif cut == "response_send":
        original_send = ingress.response_channel.send

        def crash_after_response(_result):
            """Mathematics: emit reliable result `R_s`, then cut execution before consuming and ACKing request `Q_r`."""

            original_send(_result)
            raise SystemExit(83)

        monkeypatch.setattr(ingress.response_channel, "send", crash_after_response)
    elif cut == "request_ack":
        original_receive = ingress.request_channel.channel.receive

        def crash_after_request_ack():
            """Mathematics: commit receive transition `r→r+1` and emit `ACK(r)`, then cut before service return."""

            received = original_receive()
            if received is not None:
                raise SystemExit(84)
            return received

        monkeypatch.setattr(ingress.request_channel.channel, "receive", crash_after_request_ack)
    else:
        raise AssertionError(f"unknown crash cut: {cut}")

    try:
        with pytest.raises(SystemExit):
            ingress.receive_and_commit(timeout=4.0)

        proposal = context["owner_ledger"].proposal_at(1)
        assert proposal is not None
        assert context["owner_ledger"].decision(proposal) is not None
        if cut == "owner_decision":
            assert context["owner_journal"].snapshot()["operations"] == 0
            assert SystemSeed.from_system(context["owner"]).origin_digest == proposal.predecessor_state_digest
            assert ingress.request_channel.channel.next_receive_sequence == 1
        else:
            assert context["owner_journal"].snapshot()["operations"] == 1
            assert SystemSeed.from_system(context["owner"]).origin_digest == proposal.result_state_digest
            expected_cursor = 2 if cut == "request_ack" else 1
            assert ingress.request_channel.channel.next_receive_sequence == expected_cursor

        first_delivery = None
        if cut == "response_send":
            first_delivery = result_reader.receive()
            assert first_delivery is not None and first_delivery.accepted and not first_delivery.replayed

        # Freeze remote participants so the two-cut checkpoint captures one exact distributed boundary.
        context["stopping"].set()
        for node in context["peer_nodes"].values():
            node["worker"].join(timeout=1)
        checkpoint = SeedCommitServiceRecoveryCheckpoint.from_snapshot(
            SeedCommitServiceRecoveryCheckpoint.capture(ingress).snapshot()
        )
        peer_sockets = {
            member: node["owner_transport"].socket
            for member, node in context["peer_nodes"].items()
        }
        rebound = checkpoint.rebind(peer_sockets, ingress_transport.socket, peer="client")

        context["stopping"].clear()
        for node in context["peer_nodes"].values():
            participant = node["participant"]

            def serve(current_participant=participant):
                """Mathematics: iterate peer transition `Pₙ₊₁=service_once(Pₙ)` until the test's recovery interval ends."""

                while not context["stopping"].is_set():
                    try:
                        if not current_participant.service_once():
                            time.sleep(0.001)
                    except Exception as error:
                        context["failures"].append(error)
                        time.sleep(0.001)

            worker = threading.Thread(target=serve, daemon=True)
            node["worker"] = worker
            worker.start()

        recovered_result = rebound.receive_and_commit(timeout=4.0)
        if cut == "request_ack":
            assert recovered_result is None
        else:
            assert recovered_result is not None and recovered_result.accepted

        if cut == "response_send":
            delivered = result_reader.receive()
            assert delivered is not None and delivered.accepted and delivered.replayed
            assert delivered.request_fingerprint == first_delivery.request_fingerprint
        else:
            deadline = time.monotonic() + 2.0
            delivered = None
            while delivered is None and time.monotonic() < deadline:
                delivered = result_reader.receive()
                if delivered is None:
                    time.sleep(0.002)
            assert delivered is not None and delivered.accepted
            assert delivered.replayed is (cut != "request_ack")

        deadline = time.monotonic() + 2.0
        expected_commit = (proposal.slot, proposal.result_state_digest)
        while any(
            node["ledger"].committed_state() != expected_commit
            for node in context["peer_nodes"].values()
        ) and time.monotonic() < deadline:
            time.sleep(0.002)
        assert all(
            node["ledger"].committed_state() == expected_commit
            for node in context["peer_nodes"].values()
        )
        assert all(
            node["operating_system"].snapshot() == rebound.operating_system.snapshot()
            for node in context["peer_nodes"].values()
        )
        assert SystemSeed.from_system(rebound.operating_system).origin_digest == proposal.result_state_digest
        assert rebound.operating_system.vm.scheduler.tick == 1
        assert not context["failures"]

        sender.channel.process_ack()
        rebound.service()
        assert sender.channel.pending_sequences() == ()
        assert rebound.response_channel.channel.pending_sequences() == ()
    finally:
        context["stopping"].set()
        for node in context["peer_nodes"].values():
            node["worker"].join(timeout=1)
        if rebound is not None:
            rebound.transport.close()
            if rebound.quorum_coordinator is not None:
                for link in rebound.quorum_coordinator.peers.values():
                    link.requests.transport.close()
        else:
            ingress_transport.close()
        client_transport.close()
        _close_pair(context)


def test_seed_commit_quorum_checkpoint_rejects_durable_prefix_mismatch_before_rebind(tmp_path) -> None:
    """Mathematics: captured cut `(L₀,J₀)` cannot reconstruct from a later durable ledger `L₁≠L₀`."""

    context = _live_pair(tmp_path)
    rebound = None
    try:
        checkpoint = SeedCommitQuorumRecoveryCheckpoint.capture(context["coordinator"])
        request = _request(context["owner"], context["pid"])
        proposal, artifact = context["coordinator"].propose_seed_input(request, "client", "seed.input", 1)
        context["owner_ledger"].prepare(proposal, artifact)
        context["stopping"].set()
        for node in context["peer_nodes"].values():
            node["worker"].join(timeout=1)
        raw_sockets = {
            member: node["owner_transport"].socket
            for member, node in context["peer_nodes"].items()
        }
        with pytest.raises(SeedCommitQuorumError, match="durable owner ledgers differ"):
            rebound = checkpoint.rebind(raw_sockets)
    finally:
        if rebound is not None:
            for link in rebound.peers.values():
                link.requests.transport.close()
        _close_pair(context)


def test_seed_commit_quorum_checkpoint_recovers_owner_pending_publication(tmp_path, monkeypatch) -> None:
    """Mathematics: checkpoint state `(L_k,OS_{k-1})` resumes the pending certified edge and publishes only after decision quorum."""

    context = _live_pair(
        tmp_path,
        delayed_peer_seconds=0.08,
        members=("A", "B", "C", "D", "E"),
    )
    rebound = None
    try:
        request = _request(context["owner"], context["pid"])
        proposal, artifact = context["coordinator"].propose_seed_input(request, "client", "seed.input", 1)
        owner_before = context["owner"].snapshot()
        peer_c = context["peer_nodes"]["C"]["participant"]
        original_send = peer_c.outbound.send

        def withhold_c_decision(payload):
            """Mathematics: preserve C's durable local COMMIT while dropping only its decision response projection."""

            if payload.get("kind") == "mailcpu.hypervisor.seed.quorum.decision":
                raise OSError("injected C decision loss during checkpoint setup")
            return original_send(payload)

        monkeypatch.setattr(peer_c.outbound, "send", withhold_c_decision)
        with pytest.raises(SeedCommitQuorumError, match="commit quorum unavailable"):
            context["coordinator"].execute(proposal, artifact, timeout=0.8)
        assert context["owner_ledger"].decision(proposal) is not None
        assert context["owner"].snapshot() == owner_before
        assert context["owner_journal"].snapshot()["operations"] == 0

        context["stopping"].set()
        for node in context["peer_nodes"].values():
            node["worker"].join(timeout=1)
        checkpoint = SeedCommitQuorumRecoveryCheckpoint.capture(context["coordinator"])
        assert checkpoint.ledger_state["committed_state"]["slot"] == 1
        assert checkpoint.publication_state["operations"] == 0
        raw_sockets = {
            member: node["owner_transport"].socket
            for member, node in context["peer_nodes"].items()
        }
        rebound = SeedCommitQuorumRecoveryCheckpoint.from_snapshot(checkpoint.snapshot()).rebind(raw_sockets)
        assert rebound.operating_system.snapshot() == owner_before

        monkeypatch.setattr(peer_c.outbound, "send", original_send)
        context["stopping"].clear()
        for member, node in context["peer_nodes"].items():
            participant = node["participant"]

            def service(current_participant=participant):
                """Mathematics: continue each recovered participant service map until the test's explicit stop transition."""

                while not context["stopping"].is_set():
                    try:
                        if not current_participant.service_once():
                            time.sleep(0.001)
                    except Exception as error:
                        context["failures"].append(error)
                        time.sleep(0.001)

            worker = threading.Thread(target=service, daemon=True)
            node["worker"] = worker
            worker.start()

        recovered = rebound.resume(proposal, timeout=3)
        assert recovered.accepted
        assert rebound.operating_system.snapshot() == context["peer_nodes"]["B"]["operating_system"].snapshot()
        assert rebound.ledger.committed_state() == (1, proposal.result_state_digest)
        assert rebound.durable_journal.snapshot()["operations"] == 1
    finally:
        if rebound is not None:
            for link in rebound.peers.values():
                link.requests.transport.close()
        _close_pair(context)


def test_seed_commit_quorum_installs_identical_host_state_over_real_peer_channel(tmp_path) -> None:
    """Mathematics: `q=2` durable prepare votes and commit decisions precede equal owner/replica publication `OS_A=OS_B=OS'`."""

    context = _live_pair(tmp_path)
    try:
        request = _request(context["owner"], context["pid"])
        proposal, artifact = context["coordinator"].propose_seed_input(request, "client", "seed.input", 1)
        with TrajectoryWriter(tmp_path / "owner.mtrj", tmp_path / "owner.mtrj.idx") as writer:
            context["owner"].vm.trajectory = writer
            result = context["coordinator"].execute(proposal, artifact, timeout=3)

            deadline = time.monotonic() + 2
            while context["peer_nodes"]["C"]["ledger"].decision(proposal) is None and time.monotonic() < deadline:
                time.sleep(0.002)
            assert context["peer_nodes"]["C"]["ledger"].decision(proposal) is not None

            current = context["owner"].seed_admission.current("quorum-system")
            assert current is not None
            second_request = SeedCommitRequest(
                "quorum-system", "resolver", 2, context["pid"], "inbox", (43,), current.state_digest
            )
            second_proposal, second_artifact = context["coordinator"].propose_seed_input(
                second_request, "client", "seed.input", 2
            )
            second_result = context["coordinator"].execute(second_proposal, second_artifact, timeout=3)
            writer.flush()
            with TrajectoryReader(tmp_path / "owner.mtrj", tmp_path / "owner.mtrj.idx") as reader:
                assert reader.verify() > 0

        assert result.accepted and result.state_digest == proposal.result_state_digest
        assert second_result.accepted and second_result.state_digest == second_proposal.result_state_digest
        assert context["owner"].snapshot() == context["replica"].snapshot()
        assert context["owner"].vm.scheduler.tick == 2
        assert context["owner_ledger"].decision(proposal) is not None
        assert context["replica_ledger"].decision(proposal) is not None
        assert context["owner_ledger"].committed_state() == (2, second_proposal.result_state_digest)
        assert context["replica_ledger"].committed_state() == (2, second_proposal.result_state_digest)
        deadline = time.monotonic() + 2
        while context["peer_nodes"]["C"]["ledger"].committed_state() != (2, second_proposal.result_state_digest) and time.monotonic() < deadline:
            time.sleep(0.002)
        assert context["peer_nodes"]["C"]["ledger"].committed_state() == (2, second_proposal.result_state_digest)
        assert context["owner"].snapshot() == context["peer_nodes"]["C"]["operating_system"].snapshot()
        assert context["owner_ledger"].certificate(proposal) is not None
        assert context["owner_ledger"].verify() and all(
            node["ledger"].verify() for node in context["peer_nodes"].values()
        )
        assert context["owner_journal"].lookup(("client", "seed.input", 1), request.fingerprint) == result
        assert context["replica_journal"].lookup(("client", "seed.input", 1), request.fingerprint) == result
        assert context["owner_journal"].lookup(("client", "seed.input", 2), second_request.fingerprint) == second_result
        assert not context["failures"]
    finally:
        _close_pair(context)


def test_owner_does_not_publish_after_local_decision_until_peer_decision_is_recovered(tmp_path, monkeypatch) -> None:
    """Mathematics: absent decision quorum `|D|<q` implies `OS_owner=OS_before` and no owner publication record."""

    context = _live_pair(tmp_path)
    try:
        request = _request(context["owner"], context["pid"])
        proposal, artifact = context["coordinator"].propose_seed_input(request, "client", "seed.input", 1)
        before = context["owner"].snapshot()
        delivery = {"blocked": True}
        originals = {
            member: node["participant"].outbound.send
            for member, node in context["peer_nodes"].items()
        }

        def drop_each_decision(member):
            """Mathematics: bind response-loss injection to one peer while leaving its other response values unchanged."""

            original_send = originals[member]

            def send(payload):
                """Mathematics: preserve every response unless the test's decision-delivery gate is closed."""

                if payload.get("kind") == "mailcpu.hypervisor.seed.quorum.decision" and delivery["blocked"]:
                    raise OSError(f"injected lost commit acknowledgement from {member}")
                return original_send(payload)

            return send

        for member, node in context["peer_nodes"].items():
            monkeypatch.setattr(node["participant"].outbound, "send", drop_each_decision(member))
        with pytest.raises(SeedCommitQuorumError, match="commit quorum unavailable"):
            context["coordinator"].execute(proposal, artifact, timeout=1.0)

        assert context["owner_ledger"].decision(proposal) is not None
        assert all(node["ledger"].decision(proposal) is not None for node in context["peer_nodes"].values())
        assert all(
            node["journal"].lookup(("client", "seed.input", 1), request.fingerprint) is not None
            for node in context["peer_nodes"].values()
        )
        assert context["owner"].snapshot() == before
        assert context["owner_journal"].snapshot()["operations"] == 0

        delivery["blocked"] = False
        for member, node in context["peer_nodes"].items():
            monkeypatch.setattr(node["participant"].outbound, "send", originals[member])
        restarted_ledger = DurableSeedCommitLedger(tmp_path / "A.quorum", "A", context["membership"])
        restarted_journal = DurableSeedCommitJournal(tmp_path / "A.publication", "A")
        context["owner_ledger"] = restarted_ledger
        context["owner_journal"] = restarted_journal
        context["coordinator"] = SeedCommitQuorumCoordinator(
            context["membership"],
            restarted_ledger,
            context["owner"],
            restarted_journal,
            context["coordinator"].peers,
            retry_interval=0.02,
        )
        assert restarted_ledger.certificate(proposal) is not None
        assert restarted_ledger.transition_artifact(proposal) is not None
        recovered = context["coordinator"].resume(proposal, timeout=3)
        assert recovered.accepted
        assert context["owner"].snapshot() == context["replica"].snapshot()
        assert context["owner"].snapshot() == context["peer_nodes"]["C"]["operating_system"].snapshot()
        assert context["owner_journal"].snapshot()["operations"] == 1
        assert context["owner_ledger"].verify() and all(
            node["ledger"].verify() for node in context["peer_nodes"].values()
        )
    finally:
        _close_pair(context)


def test_observed_vote_is_fsynced_before_ack_and_reused_after_owner_restart(tmp_path) -> None:
    """Mathematics: an ACKed peer vote remains in the owner journal, so `restart + new vote` is unnecessary for quorum recovery."""

    context = _live_pair(tmp_path, delayed_peer_seconds=0.8, members=("A", "B", "C", "D", "E"))
    try:
        request = _request(context["owner"], context["pid"])
        proposal, artifact = context["coordinator"].propose_seed_input(request, "client", "seed.input", 1)
        with pytest.raises(SeedCommitQuorumError, match="prepare quorum unavailable"):
            context["coordinator"].execute(proposal, artifact, timeout=0.5)

        observed = context["owner_ledger"].observed_votes(proposal)
        assert tuple(vote.member_id for vote in observed) == ("B",)
        assert context["owner"].snapshot() == context["peer_nodes"]["B"]["operating_system"].snapshot()
        assert context["owner_journal"].snapshot()["operations"] == 0

        restarted_ledger = DurableSeedCommitLedger(tmp_path / "A.quorum", "A", context["membership"])
        restarted_journal = DurableSeedCommitJournal(tmp_path / "A.publication", "A")
        context["coordinator"] = SeedCommitQuorumCoordinator(
            context["membership"],
            restarted_ledger,
            context["owner"],
            restarted_journal,
            context["coordinator"].peers,
            retry_interval=0.02,
        )
        result = context["coordinator"].execute(proposal, artifact, timeout=3)
        assert result.accepted
        assert restarted_ledger.certificate(proposal) is not None
        assert context["owner"].snapshot() == context["replica"].snapshot()
        assert context["peer_nodes"]["B"]["participant"].outbound.snapshot()["next_sequence"] == 3
        assert restarted_ledger.verify()
    finally:
        _close_pair(context)


def test_observed_decision_is_fsynced_before_ack_and_reused_after_owner_restart(tmp_path, monkeypatch) -> None:
    """Mathematics: persist each remote `COMMIT` receipt before ACK so a partial decision set survives owner-coordinator restart."""

    context = _live_pair(
        tmp_path,
        delayed_peer_seconds=0.08,
        members=("A", "B", "C", "D", "E"),
    )
    try:
        request = _request(context["owner"], context["pid"])
        proposal, artifact = context["coordinator"].propose_seed_input(request, "client", "seed.input", 1)
        before = context["owner"].snapshot()
        delivery = {"blocked": True}
        peer_c = context["peer_nodes"]["C"]["participant"]
        original_send = peer_c.outbound.send

        def withhold_c_decision(payload):
            """Mathematics: remove only C's decision response while leaving its durable commit and all other traffic intact."""

            if payload.get("kind") == "mailcpu.hypervisor.seed.quorum.decision" and delivery["blocked"]:
                raise OSError("injected C decision-response loss")
            return original_send(payload)

        monkeypatch.setattr(peer_c.outbound, "send", withhold_c_decision)
        with pytest.raises(SeedCommitQuorumError, match="commit quorum unavailable"):
            context["coordinator"].execute(proposal, artifact, timeout=1.0)

        observed = context["owner_ledger"].observed_decisions(proposal)
        assert tuple(item.member_id for item in observed) == ("B",)
        assert context["owner"].snapshot() == before
        assert context["owner_journal"].snapshot()["operations"] == 0

        restarted_ledger = DurableSeedCommitLedger(tmp_path / "A.quorum", "A", context["membership"])
        restarted_journal = DurableSeedCommitJournal(tmp_path / "A.publication", "A")
        assert tuple(item.member_id for item in restarted_ledger.observed_decisions(proposal)) == ("B",)
        context["coordinator"] = SeedCommitQuorumCoordinator(
            context["membership"],
            restarted_ledger,
            context["owner"],
            restarted_journal,
            context["coordinator"].peers,
            retry_interval=0.02,
        )
        delivery["blocked"] = False
        monkeypatch.setattr(peer_c.outbound, "send", original_send)
        result = context["coordinator"].resume(proposal, timeout=3)
        assert result.accepted
        assert context["owner"].snapshot() == context["peer_nodes"]["B"]["operating_system"].snapshot()
        assert restarted_journal.snapshot()["operations"] == 1
        assert restarted_ledger.verify()
    finally:
        _close_pair(context)


def test_bound_transition_artifact_survives_ledger_restart_and_rejects_substitution(tmp_path) -> None:
    """Mathematics: replay restores exact `A` for its proposal digest and rejects any artifact `A'` with `d(A')≠d(A)`."""

    context = _live_pair(tmp_path)
    try:
        request = _request(context["owner"], context["pid"])
        proposal, artifact = context["coordinator"].propose_seed_input(request, "client", "seed.input", 1)
        vote = context["owner_ledger"].prepare(proposal, artifact)
        reopened = DurableSeedCommitLedger(tmp_path / "A.quorum", "A", context["membership"])
        restored = reopened.transition_artifact(proposal)
        assert restored is not None and restored.digest == artifact.digest
        assert reopened.prepare(proposal, restored) == vote

        altered_host = dict(artifact.operating_system)
        altered_host["environment"] = {"changed": True}
        from mailcpu import SeedCommitTransitionArtifact

        substituted = SeedCommitTransitionArtifact(artifact.result, altered_host)
        with pytest.raises(SeedCommitLedgerError, match="artifact digest"):
            reopened.prepare(proposal, substituted)
        assert reopened.verify()
    finally:
        _close_pair(context)
