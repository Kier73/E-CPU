from __future__ import annotations

import json
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time

import pytest

from mailcpu import (
    DurableSeedCommitJournal,
    DurableSeedCommitLedger,
    HeadlessOS,
    HypervisorSeedCommitChannel,
    HypervisorSeedCommitRecoveryCoordinator,
    HypervisorSeedCommitResultChannel,
    ReliabilityPolicy,
    ReliableChannel,
    SeedCommitMembership,
    SeedCommitQuorumParticipant,
    SeedCommitQuorumError,
    SeedCommitRequest,
    SeedCommitServiceRecoveryCheckpoint,
    SystemIdentity,
    SystemSeed,
    SystemSeedEnvelope,
    SEED_QUORUM_REQUEST_CHANNEL,
    SEED_QUORUM_RESPONSE_CHANNEL,
    SocketTransport,
)
from mailcpu._codec import decode_canonical_value, encode_canonical_value
from mailcpu.programs import wait_send_program


_OWNER_PROCESS = r'''# Mathematics: replay an exact owner service cut by preserving durable prefixes and reliable FIFO factors.
import json
import os
from pathlib import Path
import sys
import time
from mailcpu import (
    DurableSeedCommitJournal, DurableSeedCommitLedger, HeadlessOS,
    HypervisorSeedCommitChannel, HypervisorSeedCommitRecoveryCoordinator,
    HypervisorSeedCommitResultChannel, ReliabilityPolicy, ReliableChannel,
    SeedCommitMembership, SeedCommitPeerLink, SeedCommitQuorumCoordinator,
    SeedCommitServiceRecoveryCheckpoint, SocketTransport,
    SEED_QUORUM_REQUEST_CHANNEL, SEED_QUORUM_RESPONSE_CHANNEL,
)
from mailcpu._codec import decode_canonical_value, encode_canonical_value

config_path, checkpoint_path, mode = sys.argv[1:]
config = decode_canonical_value(json.loads(Path(config_path).read_text(encoding="utf-8")))
membership = config["membership"]
policy = ReliabilityPolicy(lease_ticks=4, max_attempts=8, window_size=16)

def persist(path, value):
    # Mathematics: persist canonical checkpoint bytes `B=JSON(encode(value))` before acknowledging the cut.
    data = json.dumps(encode_canonical_value(value), sort_keys=True, separators=(",", ":"))
    with Path(path).open("w", encoding="utf-8") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())

if mode != "recover":
    machine = HeadlessOS.from_snapshot(config["initial_os"])
    fixed_membership = __import__("mailcpu").SeedCommitMembership.from_snapshot(membership)
    owner_ledger = DurableSeedCommitLedger(config["ledger_paths"]["A"], "A", fixed_membership)
    owner_journal = DurableSeedCommitJournal(config["journal_paths"]["A"], "A")
    peer_links = {}
    peer_transports = []
    for member in ("B", "C"):
        transport = SocketTransport.connect("127.0.0.1", config["ports"][member], "A", member)
        peer_transports.append(transport)
        requests = ReliableChannel(transport, "A", member, SEED_QUORUM_REQUEST_CHANNEL, policy, peer=member)
        responses = ReliableChannel(transport, member, "A", SEED_QUORUM_RESPONSE_CHANNEL, policy, peer=member)
        peer_links[member] = SeedCommitPeerLink(member, requests, responses)
    quorum = SeedCommitQuorumCoordinator(
        fixed_membership, owner_ledger, machine, owner_journal, peer_links, retry_interval=0.02
    )
    ingress_transport = SocketTransport.connect("127.0.0.1", config["ports"]["client"], "A", "client")
    ingress_requests = HypervisorSeedCommitChannel(
        ReliableChannel(ingress_transport, "A", "A", "seed.input", policy, peer="client")
    )
    ingress_results = HypervisorSeedCommitResultChannel(
        ReliableChannel(ingress_transport, "A", "client", "seed.result", policy, peer="client"),
        "client", "seed.input",
    )
    ingress = HypervisorSeedCommitRecoveryCoordinator(
        ingress_transport, ingress_requests, ingress_results, machine, role="executor",
        quorum_coordinator=quorum,
    )
    print("READY", flush=True)

    def pause_at_cut():
        # Mathematics: serialize one stationary service state `C_k` before terminating the owner process.
        print("CUT " + mode, flush=True)
        if sys.stdin.readline().strip() != "capture":
            os._exit(92)
        checkpoint = SeedCommitServiceRecoveryCheckpoint.capture(ingress)
        persist(checkpoint_path, checkpoint.snapshot())
        print("CHECKPOINT", flush=True)
        os._exit(87)

    if mode == "owner_decision":
        def pause_before_publication(_proposal, _result, _candidate):
            # Mathematics: cut at `decision quorum=1, publication slot=0, OS=OS₀`.
            pause_at_cut()

        quorum._publish_owner = pause_before_publication
    elif mode == "owner_publication":
        def pause_before_response(result):
            # Mathematics: cut after `fsync(J₁,OS₁)` and before emitting response frame `R₁`.
            pause_at_cut()

        ingress.response_channel.send = pause_before_response
    elif mode == "response_send":
        original_send = ingress.response_channel.send

        def pause_after_response(result):
            # Mathematics: cut after emitting `R₁`, before request receive advances cursor `r:1→2`.
            original_send(result)
            pause_at_cut()

        ingress.response_channel.send = pause_after_response
    elif mode == "request_ack":
        original_receive = ingress.request_channel.channel.receive

        def pause_after_request_ack():
            # Mathematics: cut after `receive(q)` emits `ACK(q)` and advances cursor `r:1→2`.
            received = original_receive()
            if received is not None:
                pause_at_cut()
            return received

        ingress.request_channel.channel.receive = pause_after_request_ack
    else:
        raise AssertionError("unsupported owner process cut: " + mode)
    deadline = time.monotonic() + 30.0
    while ingress.request_channel.channel.peek() is None and time.monotonic() < deadline:
        time.sleep(0.002)
    assert ingress.request_channel.channel.peek() is not None
    ingress.receive_and_commit(timeout=30.0)
    os._exit(93)

checkpoint_payload = decode_canonical_value(json.loads(Path(checkpoint_path).read_text(encoding="utf-8")))
checkpoint = SeedCommitServiceRecoveryCheckpoint.from_snapshot(checkpoint_payload)
peer_sockets = {}
for member in ("B", "C"):
    raw_socket = SocketTransport.connect("127.0.0.1", config["ports"][member], "A", member).socket
    peer_sockets[member] = raw_socket
ingress_socket = SocketTransport.connect("127.0.0.1", config["ports"]["client"], "A", "client").socket
ingress = checkpoint.rebind(peer_sockets, ingress_socket, peer="client")
print("READY", flush=True)
if sys.stdin.readline().strip() != "resume":
    os._exit(94)
if ingress.request_channel.channel.peek() is not None:
    result = ingress.receive_and_commit(timeout=30.0)
    assert result is not None and result.accepted and result.replayed
else:
    # Mathematics: an ACKed request has `r=2`; recovery must not manufacture a second request effect.
    assert ingress.request_channel.channel.next_receive_sequence == 2
assert ingress.operating_system.vm.scheduler.tick == 1
deadline = time.monotonic() + 10.0
while ingress.response_channel.channel.pending_sequences() and time.monotonic() < deadline:
    ingress.service()
    ingress.retry()
    time.sleep(0.005)
assert ingress.response_channel.channel.pending_sequences() == ()
print("DONE", flush=True)
if sys.stdin.readline().strip() != "finish":
    os._exit(95)
ingress.close()
for link in ingress.quorum_coordinator.peers.values():
    link.requests.transport.close()
'''


def _admitted_machine() -> tuple[HeadlessOS, int]:
    """Mathematics: construct admitted genesis state `OS₀` and its blocked input process `p` deterministically."""

    machine = HeadlessOS()
    pid = machine.spawn(wait_send_program(), "process-recovery-input")
    seed = SystemSeed.from_system(machine)
    envelope = SystemSeedEnvelope(SystemIdentity("process-quorum", 1), "origin", "quorum", seed)
    assert machine.seed_admission.admit(envelope).accepted
    return machine, pid


def _accept_raw(listener) -> socket.socket:
    """Mathematics: project `listener.accept()` to the fresh raw stream while leaving identity binding to its recovery owner."""

    sock, _address = listener.accept()
    return sock


def _peer_runtime(raw_socket, member, membership, ledger_path, journal_path, initial_state, stopping, failures):
    """Mathematics: restore peer factor `(L,J,OS,T,R_in,R_out)` and apply service transitions only while `stopping=0`."""

    transport = SocketTransport(raw_socket, member, "A")
    inbound = ReliableChannel(
        transport, "A", member, SEED_QUORUM_REQUEST_CHANNEL,
        ReliabilityPolicy(lease_ticks=4, max_attempts=8, window_size=16), peer="A",
    )
    outbound = ReliableChannel(
        transport, member, "A", SEED_QUORUM_RESPONSE_CHANNEL,
        ReliabilityPolicy(lease_ticks=4, max_attempts=8, window_size=16), peer="A",
    )
    ledger = DurableSeedCommitLedger(ledger_path, member, membership)
    journal = DurableSeedCommitJournal(journal_path, member)
    operating_system = journal.restore_host() or HeadlessOS.from_snapshot(initial_state)
    participant = SeedCommitQuorumParticipant(ledger, inbound, outbound, operating_system, journal)

    def serve() -> None:
        """Mathematics: iterate peer transition `Pₙ₊₁=service_once(Pₙ)` until the explicit stop variable is set."""

        while not stopping.is_set():
            try:
                if not participant.service_once():
                    time.sleep(0.001)
            except Exception as error:
                failures.append(error)
                time.sleep(0.001)

    worker = threading.Thread(target=serve, daemon=True)
    worker.start()
    return {
        "transport": transport,
        "inbound": inbound,
        "outbound": outbound,
        "ledger": ledger,
        "journal": journal,
        "operating_system": operating_system,
        "participant": participant,
        "worker": worker,
        "ledger_path": ledger_path,
        "journal_path": journal_path,
    }


def _write_canonical(path: Path, value: object) -> None:
    """Mathematics: persist a lossless tagged serialization `decode(encode(x))=x` for the test's finite checkpoint algebra."""

    path.write_text(
        json.dumps(encode_canonical_value(value), sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )


def _read_canonical(path: Path) -> object:
    """Mathematics: invert `_write_canonical` through the tagged value algebra before validating typed recovery factors."""

    return decode_canonical_value(json.loads(path.read_text(encoding="utf-8")))


@pytest.mark.parametrize("cut", ("owner_decision", "owner_publication", "response_send", "request_ack"))
def test_quorum_owner_process_restart_rebinds_new_tcp_and_replays_one_operation(tmp_path, cut) -> None:
    """Mathematics: across each owner death cut, preserve one quorum slot, one publication, and the expected FIFO cursor."""

    initial, pid = _admitted_machine()
    genesis = SystemSeed.from_system(initial).origin_digest
    membership = SeedCommitMembership("process-quorum", 1, ("A", "B", "C"), "A", 1, genesis)
    listeners = {member: SocketTransport.listen("127.0.0.1", 0) for member in ("B", "C", "client")}
    for listener in listeners.values():
        listener.settimeout(10)
    paths = {
        "ledger_paths": {member: str(tmp_path / f"{member}.quorum") for member in ("A", "B", "C")},
        "journal_paths": {member: str(tmp_path / f"{member}.publication") for member in ("A", "B", "C")},
    }
    config_path = tmp_path / "process-recovery-config.json"
    checkpoint_path = tmp_path / "owner-service-checkpoint.json"
    config = {
        "membership": membership.snapshot(),
        "initial_os": initial.snapshot(),
        **paths,
        "ports": {member: listener.getsockname()[1] for member, listener in listeners.items()},
    }
    _write_canonical(config_path, config)
    first = subprocess.Popen(
        [sys.executable, "-c", _OWNER_PROCESS, str(config_path), str(checkpoint_path), cut],
        cwd=Path(__file__).resolve().parents[1],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    peer_stops: list[threading.Event] = []
    peer_nodes: dict[str, dict[str, object]] = {}
    transports_to_close: list[SocketTransport] = []
    processes = [first]
    origin = None
    recovered_origin = None
    failures: list[Exception] = []
    try:
        first_peer_sockets = {member: _accept_raw(listeners[member]) for member in ("B", "C")}
        first_client_socket = _accept_raw(listeners["client"])
        assert first.stdout.readline().strip() == "READY"
        stop = threading.Event()
        peer_stops.append(stop)
        for member in ("B", "C"):
            peer_nodes[member] = _peer_runtime(
                first_peer_sockets[member], member, membership,
                paths["ledger_paths"][member], paths["journal_paths"][member],
                initial.snapshot(), stop, failures,
            )
            transports_to_close.append(peer_nodes[member]["transport"])

        client_transport = SocketTransport(first_client_socket, "client", "A")
        transports_to_close.append(client_transport)
        policy = ReliabilityPolicy(lease_ticks=4, max_attempts=8, window_size=16)
        requester = HypervisorSeedCommitChannel(
            ReliableChannel(client_transport, "client", "A", "seed.input", policy, peer="A")
        )
        result_reader = HypervisorSeedCommitResultChannel(
            ReliableChannel(client_transport, "client", "client", "seed.result", policy, peer="A"),
            "client", "seed.input",
        )
        origin = HypervisorSeedCommitRecoveryCoordinator(
            client_transport, requester, result_reader, HeadlessOS(), role="origin"
        )
        admitted = initial.seed_admission.current("process-quorum")
        assert admitted is not None
        request = SeedCommitRequest(
            "process-quorum", "resolver", 1, pid, "inbox", (42,), admitted.state_digest
        )
        assert origin.send(request) == 1
        assert first.stdout.readline().strip() == "CUT " + cut
        first_result = None
        if cut in ("response_send", "request_ack"):
            deadline = time.monotonic() + 10.0
            while first_result is None and time.monotonic() < deadline:
                first_result = origin.receive_result()
                if first_result is None:
                    time.sleep(0.002)
            assert first_result is not None and first_result.accepted and not first_result.replayed
        if cut == "request_ack":
            # Mathematics: observe the already emitted `ACK(q)` before saving the requester cut.
            deadline = time.monotonic() + 5.0
            while origin.status().request_pending_sequences and time.monotonic() < deadline:
                origin.service()
                time.sleep(0.002)
            assert origin.status().request_pending_sequences == ()
        requester_checkpoint = origin.checkpoint()
        requester_checkpoint = type(requester_checkpoint).from_snapshot(requester_checkpoint.snapshot())

        # Mathematics: stop all participant transition functions before taking the distributed cut.
        stop.set()
        for node in peer_nodes.values():
            node["worker"].join(timeout=2)
            assert not node["worker"].is_alive()
        peer_cuts = {
            member: {
                "transport": node["transport"].snapshot(),
                "inbound": node["inbound"].snapshot(),
                "outbound": node["outbound"].snapshot(),
            }
            for member, node in peer_nodes.items()
        }
        expected_digest = next(iter(peer_nodes.values()))["ledger"].committed_state()[1]
        assert all(node["ledger"].committed_state() == (1, expected_digest) for node in peer_nodes.values())
        assert all(node["journal"].snapshot()["operations"] == 1 for node in peer_nodes.values())

        assert first.stdin is not None
        first.stdin.write("capture\n")
        first.stdin.flush()
        assert first.stdout.readline().strip() == "CHECKPOINT"
        first_output, first_error = first.communicate(timeout=20)
        assert first.returncode == 87, (first_output, first_error)
        owner_checkpoint_payload = _read_canonical(checkpoint_path)
        owner_checkpoint = SeedCommitServiceRecoveryCheckpoint.from_snapshot(owner_checkpoint_payload)
        assert owner_checkpoint.quorum.ledger_state["committed_state"]["slot"] == 1
        expected_publications = 0 if cut == "owner_decision" else 1
        expected_request_cursor = 2 if cut == "request_ack" else 1
        expected_result_cursor = 2 if cut in ("response_send", "request_ack") else 1
        assert owner_checkpoint.quorum.publication_state["operations"] == expected_publications
        assert owner_checkpoint.ingress.request_channel["channel"]["next_receive_sequence"] == expected_request_cursor
        assert requester_checkpoint.request_channel["channel"]["next_sequence"] == 2
        assert requester_checkpoint.response_channel["channel"]["next_receive_sequence"] == expected_result_cursor
        assert bool(requester_checkpoint.request_channel["channel"]["pending"]) is (cut != "request_ack")
        assert SystemSeed.from_system(HeadlessOS.from_snapshot(owner_checkpoint.quorum.operating_system)).origin_digest == (
            membership.genesis_state_digest if cut == "owner_decision" else expected_digest
        )

        # Mathematics: mutate one durable-head coordinate; checkpoint validation must reject the known-bad cut.
        corrupted = json.loads(json.dumps(encode_canonical_value(owner_checkpoint_payload)))
        decoded_corrupt = decode_canonical_value(corrupted)
        decoded_corrupt["quorum"]["ledger_state"]["membership_digest"] = "0" * 64
        with pytest.raises(SeedCommitQuorumError):
            SeedCommitServiceRecoveryCheckpoint.from_snapshot(decoded_corrupt)

        for node in peer_nodes.values():
            node["transport"].close()
        client_transport.close()

        second = subprocess.Popen(
            [sys.executable, "-c", _OWNER_PROCESS, str(config_path), str(checkpoint_path), "recover"],
            cwd=Path(__file__).resolve().parents[1],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        processes.append(second)
        rebound_peer_sockets = {member: _accept_raw(listeners[member]) for member in ("B", "C")}
        rebound_client_socket = _accept_raw(listeners["client"])
        recovered_stop = threading.Event()
        peer_stops.append(recovered_stop)
        restored_nodes: dict[str, dict[str, object]] = {}
        for member in ("B", "C"):
            raw_transport = SocketTransport.from_snapshot(
                rebound_peer_sockets[member], peer_cuts[member]["transport"]
            )
            inbound = ReliableChannel.from_snapshot(peer_cuts[member]["inbound"], raw_transport)
            outbound = ReliableChannel.from_snapshot(peer_cuts[member]["outbound"], raw_transport)
            ledger = DurableSeedCommitLedger(paths["ledger_paths"][member], member, membership)
            journal = DurableSeedCommitJournal(paths["journal_paths"][member], member)
            restored_host = journal.restore_host()
            assert restored_host is not None
            assert SystemSeed.from_system(restored_host).origin_digest == expected_digest
            participant = SeedCommitQuorumParticipant(ledger, inbound, outbound, restored_host, journal)

            def serve_restored(current=participant, current_stop=recovered_stop):
                """Mathematics: resume `Pₙ₊₁=service_once(Pₙ)` from durable peer state and saved FIFO cursor."""

                while not current_stop.is_set():
                    try:
                        if not current.service_once():
                            time.sleep(0.001)
                    except Exception as error:
                        failures.append(error)
                        time.sleep(0.001)

            worker = threading.Thread(target=serve_restored, daemon=True)
            worker.start()
            restored_nodes[member] = {
                "transport": raw_transport, "ledger": ledger, "journal": journal,
                "operating_system": restored_host, "worker": worker,
            }
            transports_to_close.append(raw_transport)
        assert second.stdout.readline().strip() == "READY"
        recovered_origin = HypervisorSeedCommitRecoveryCoordinator.rebind(
            requester_checkpoint, rebound_client_socket, role="origin", peer="A"
        )
        assert second.stdin is not None
        second.stdin.write("resume\n")
        second.stdin.flush()
        duplicate_result = None
        if cut != "request_ack":
            deadline = time.monotonic() + 10.0
            while duplicate_result is None and time.monotonic() < deadline:
                duplicate_result = recovered_origin.receive_result()
                recovered_origin.service()
                if duplicate_result is None:
                    time.sleep(0.002)
            assert duplicate_result is not None and duplicate_result.accepted and duplicate_result.replayed
            assert duplicate_result.request_fingerprint == request.fingerprint
            assert duplicate_result.state_digest == expected_digest
        assert second.stdout.readline().strip() == "DONE"
        if cut == "request_ack":
            assert recovered_origin.status().request_pending_sequences == ()
            assert recovered_origin.response_channel.channel.next_receive_sequence == 2
        # Mathematics: quiesce all peer transition functions before releasing the owner's close transition.
        recovered_stop.set()
        for node in restored_nodes.values():
            node["worker"].join(timeout=2)
            assert not node["worker"].is_alive()
        assert second.stdin is not None
        second.stdin.write("finish\n")
        second.stdin.flush()
        second_output, second_error = second.communicate(timeout=20)
        assert second.returncode == 0, (second_output, second_error)
        deadline = time.monotonic() + 5.0
        while recovered_origin.status().request_pending_sequences and time.monotonic() < deadline:
            recovered_origin.service()
            time.sleep(0.002)
        assert recovered_origin.status().request_pending_sequences == ()
        assert not failures, [str(error) for error in failures]
        owner_journal = DurableSeedCommitJournal(paths["journal_paths"]["A"], "A")
        owner_ledger = DurableSeedCommitLedger(paths["ledger_paths"]["A"], "A", membership)
        assert owner_journal.verify()
        assert owner_journal.snapshot()["operations"] == 1
        assert owner_ledger.committed_state() == (1, expected_digest)
        for node in restored_nodes.values():
            assert node["ledger"].committed_state() == (1, expected_digest)
            assert node["journal"].snapshot()["operations"] == 1
            assert SystemSeed.from_system(node["operating_system"]).origin_digest == expected_digest
            assert node["operating_system"].vm.scheduler.tick == 1
    finally:
        for stop in peer_stops:
            stop.set()
        for node in peer_nodes.values():
            node["worker"].join(timeout=1)
        if "restored_nodes" in locals():
            for node in restored_nodes.values():
                node["worker"].join(timeout=1)
        if recovered_origin is not None:
            recovered_origin.close()
        elif origin is not None and not origin.transport.closed:
            origin.close()
        for transport in transports_to_close:
            if not transport.closed:
                transport.close()
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)
        for listener in listeners.values():
            listener.close()
