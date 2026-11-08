"""Hard-killable relay-B process for federated forwarding recovery tests."""

from __future__ import annotations

import json
import os
import socket
import ssl
import sys
import threading
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from mailcpu import (  # noqa: E402
    Capability,
    ComputationalFabricDirectory,
    ComputationalFabricForwardingClient,
    ComputationalFabricForwardingRecoveryStore,
    ComputationalFabricForwardingServer,
    ComputationalPeerSnapshot,
    DistributedRecoveryLineageCoordinator,
    HeadlessOS,
    HypervisorPolicy,
    RecoveryLineageAuthority,
    RecoveryLineagePeerClient,
    SeedCommitMembership,
    SocketTransport,
)
from mailcpu.mtls_transport import accept_mutual_tls, connect_mutual_tls  # noqa: E402


def _write_json_durable(path: Path, value: dict[str, Any]) -> None:
    """Mathematics: fsync a complete marker before atomically exposing one process recovery cut."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, sort_keys=True, separators=(",", ":"))
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _membership(path: Path) -> SeedCommitMembership:
    """Mathematics: reconstruct the immutable fixed-membership quorum used by this relay incarnation."""
    return SeedCommitMembership.from_snapshot(
        json.loads(path.read_text(encoding="utf-8"))
    )


def _open_store(config: dict[str, Any]) -> tuple[ComputationalFabricForwardingRecoveryStore, Any]:
    """Mathematics: combine B's durable local owner journal with two independent process-backed authorities."""
    membership = _membership(Path(config["membership_path"]))
    lineage_root = Path(config["lineage_root"])
    anchors = lineage_root / "authorities"
    owner = RecoveryLineageAuthority(
        membership,
        membership.owner_id,
        anchors / f"{membership.owner_id}.jsonl",
    )
    peer_c = RecoveryLineagePeerClient.connect(
        membership,
        "anchor-c",
        "127.0.0.1",
        int(config["anchor_c_port"]),
        timeout=5.0,
    )
    peer_d = RecoveryLineagePeerClient.connect(
        membership,
        "anchor-d",
        "127.0.0.1",
        int(config["anchor_d_port"]),
        timeout=5.0,
    )
    coordinator = DistributedRecoveryLineageCoordinator(
        membership,
        {membership.owner_id: owner, "anchor-c": peer_c, "anchor-d": peer_d},
    )
    store = ComputationalFabricForwardingRecoveryStore(
        config["checkpoint_directory"],
        coordinator,
    )
    return store, coordinator


def _directory(config: dict[str, Any]) -> ComputationalFabricDirectory:
    """Mathematics: rebuild B's directly authenticated receiver view without restoring expired remote leases."""
    snapshots = {
        peer_id: ComputationalPeerSnapshot.from_dict(raw)
        for peer_id, raw in config["peer_snapshots"].items()
    }
    trusted = {
        peer_id: snapshot.endpoint.tls_server_name
        for peer_id, snapshot in snapshots.items()
        if peer_id != "peer-b"
    }
    directory = ComputationalFabricDirectory("peer-b", trusted)
    directory.register_local_snapshot(snapshots["peer-b"])
    for peer_id in ("peer-a", "peer-c"):
        snapshot = snapshots[peer_id]
        directory._merge_verified_peer_snapshot(
            snapshot,
            authenticated_peer_id=peer_id,
            authenticated_server_name=snapshot.endpoint.tls_server_name,
        )
    return directory


def _tls_contexts(config: dict[str, Any]) -> tuple[ssl.SSLContext, ssl.SSLContext]:
    """Mathematics: create B's server and client TLS contexts with independent peer DNS identities."""
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.minimum_version = ssl.TLSVersion.TLSv1_2
    server_context.load_cert_chain(config["peer_b_cert"], config["peer_b_key"])
    server_context.load_verify_locations(cafile=config["ca_cert"])
    server_context.verify_mode = ssl.CERT_REQUIRED

    client_context = ssl.create_default_context(
        ssl.Purpose.SERVER_AUTH,
        cafile=config["ca_cert"],
    )
    client_context.minimum_version = ssl.TLSVersion.TLSv1_2
    client_context.load_cert_chain(config["peer_b_cert"], config["peer_b_key"])
    return server_context, client_context


def _connect_c(
    config: dict[str, Any],
    client_context: ssl.SSLContext,
) -> SocketTransport:
    """Mathematics: establish a fresh B→C mutual-TLS stream using the stable logical endpoint."""
    endpoint = ComputationalPeerSnapshot.from_dict(
        config["peer_snapshots"]["peer-c"]
    ).endpoint
    return connect_mutual_tls(
        endpoint.endpoint_host,
        endpoint.port,
        "peer-b",
        "peer-c",
        client_context,
        server_hostname=endpoint.tls_server_name,
        timeout=5.0,
        handshake_timeout=5.0,
    )


def _accept_a(
    listener: SocketTransport,
    config: dict[str, Any],
    server_context: ssl.SSLContext,
    directory: ComputationalFabricDirectory,
) -> SocketTransport:
    """Mathematics: accept only A's certificate chain and exact configured DNS SAN."""
    return accept_mutual_tls(
        listener,
        "peer-b",
        "peer-a",
        server_context,
        expected_peer_dns=directory.trusted_peers["peer-a"],
        handshake_timeout=5.0,
    )


def _new_server(
    config: dict[str, Any],
    directory: ComputationalFabricDirectory,
    operating_system: HeadlessOS,
    authority_pid: int,
    inbound: SocketTransport,
    downstream: SocketTransport,
) -> ComputationalFabricForwardingServer:
    """Mathematics: bind a newly created relay OS and two live mutual-TLS adjacencies to one operation namespace."""
    endpoint_c = ComputationalPeerSnapshot.from_dict(
        config["peer_snapshots"]["peer-c"]
    ).endpoint
    client = ComputationalFabricForwardingClient(
        "peer-b",
        endpoint_c,
        downstream,
        origin_peer_id="peer-a",
        origin_channel="application.batch",
        timeout=8.0,
    )
    return ComputationalFabricForwardingServer(
        "peer-b",
        "peer-a",
        inbound,
        directory,
        operating_system,
        authority_pid,
        origin_peer_id="peer-a",
        origin_channel="application.batch",
        next_hop_clients={"peer-c": client},
        timeout=8.0,
    )


def _wait_for_recovery_completion(
    server: ComputationalFabricForwardingServer,
    result_path: Path,
    cut: str,
    timeout: float = 35.0,
) -> None:
    """Mathematics: keep servicing B until its original request is consumed and every response frame is ACKed."""
    deadline = time.monotonic() + timeout
    results: list[dict[str, Any]] = []
    while time.monotonic() < deadline:
        result = server.serve_once()
        if result is not None:
            results.append({
                "replayed": bool(result.replayed),
                "action": result.action.value,
                "domain": result.domain.value,
                "executed": bool(result.executed),
                "effect": dict(result.effect),
            })
        if (
            server.inbound.channel.next_receive_sequence >= 2
            and not server.outbound.channel.pending_sequences()
        ):
            break
        time.sleep(0.002)
    else:
        raise TimeoutError(
            "relay B did not finish the recovered operation: "
            f"receive_cursor={server.inbound.channel.next_receive_sequence}, "
            f"pending_results={server.outbound.channel.pending_sequences()}"
        )

    hypervisor_state = server.operating_system.hypervisor_arbitration.snapshot()
    executions = hypervisor_state["executions"]
    downstream_client = server.next_hop_clients["peer-c"]
    _write_json_durable(result_path, {
        "stage": "recovered",
        "pid": os.getpid(),
        "cut": cut,
        "results": results,
        "execution_count": len(executions),
        "request_receive_cursor": server.inbound.channel.next_receive_sequence,
        "response_pending": list(server.outbound.channel.pending_sequences()),
        "downstream_seen": len(downstream_client.response.snapshot()["seen"]),
        "journal_valid": server.operating_system.environment.kernel.journal.verify(),
    })


def main(arguments: list[str]) -> int:
    """Mathematics: run relay B until a named fault cut or recover its latest quorum-anchored peer generation."""
    if len(arguments) != 5:
        raise ValueError("relay worker requires mode, config, cut, marker/result path, and checkpoint directory")
    mode, config_path, cut, marker_or_result, checkpoint_directory = arguments
    if mode not in {"prepare", "restore", "live"}:
        raise ValueError(f"unsupported relay mode {mode!r}")
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    config["checkpoint_directory"] = checkpoint_directory
    directory = _directory(config)
    store, coordinator = _open_store(config)
    verified = store.load_latest() if mode == "restore" else None
    if verified is not None and verified.manifest.capture_cut != cut:
        raise ValueError("relay restart cut differs from the quorum-anchored capture cut")

    server_context, client_context = _tls_contexts(config)
    listener = SocketTransport.listen("127.0.0.1", int(config["peer_b_port"]))
    control_listener: socket.socket | None = None
    if mode == "live":
        control_listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        control_listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        control_listener.bind(("127.0.0.1", 0))
        control_listener.listen(4)
        control_listener.settimeout(0.25)
    downstream: SocketTransport | None = None
    inbound: SocketTransport | None = None
    server: ComputationalFabricForwardingServer | None = None
    print(json.dumps({
        "pid": os.getpid(),
        "peer": "peer-b",
        "port": int(config["peer_b_port"]),
        "control_port": None if control_listener is None else control_listener.getsockname()[1],
        "mode": mode,
    }, sort_keys=True), flush=True)

    try:
        downstream = _connect_c(config, client_context)
        inbound = _accept_a(listener, config, server_context, directory)
        if mode == "live":
            operating_system = HeadlessOS()
            operating_system.hypervisor.policy = HypervisorPolicy(
                review_confidence=0.0,
                automatic_confidence=0.0,
                destructive_confidence=0.0,
                danger_review_probability=1.0,
            )
            authority_pid = operating_system.environment.kernel.spawn(
                "federated-process-relay-b-live",
                capabilities=(Capability(
                    "/network/computational-fabric/forward",
                    frozenset({"forward"}),
                ),),
                parent_pid=operating_system.environment.init_pid,
            )
            server = _new_server(
                config,
                directory,
                operating_system,
                authority_pid,
                inbound,
                downstream,
            )
            assert control_listener is not None

            def serve_control() -> None:
                """Accept loopback-only supervisor commands to replace a failed downstream stream."""
                while True:
                    try:
                        connection, _address = control_listener.accept()
                    except socket.timeout:
                        continue
                    except OSError:
                        return
                    with connection:
                        try:
                            connection.settimeout(20.0)
                            chunks = bytearray()
                            while b"\\n" not in chunks and len(chunks) <= 4096:
                                part = connection.recv(1024)
                                if not part:
                                    break
                                chunks.extend(part)
                            command = json.loads(bytes(chunks).split(b"\\n", 1)[0].decode("utf-8"))
                            if command.get("command") != "rebind_next_hop":
                                raise ValueError("unsupported relay control command")
                            peer_id = str(command.get("peer_id", ""))
                            replacement_transport = _connect_c(config, client_context)
                            replacement = server.rebind_next_hop_transport(
                                peer_id,
                                replacement_transport,
                            )
                            reply = {
                                "ok": True,
                                "peer_id": peer_id,
                                "remote": replacement.remote_endpoint.peer_id,
                                "pid": os.getpid(),
                            }
                        except Exception as exc:
                            reply = {
                                "ok": False,
                                "error": f"{type(exc).__name__}: {exc}",
                                "pid": os.getpid(),
                            }
                        connection.sendall(
                            json.dumps(reply, sort_keys=True, separators=(",", ":")).encode("utf-8")
                            + b"\\n"
                        )

            control_thread = threading.Thread(target=serve_control, daemon=True)
            control_thread.start()
            completed: list[dict[str, Any]] = []
            deadline = time.monotonic() + 90.0
            while time.monotonic() < deadline:
                try:
                    result = server.serve_once()
                except Exception as exc:
                    # A downstream process may be absent during its restart
                    # window. Preserve B's unacknowledged inbound operation and
                    # its pending downstream frame; the supervisor can rebind
                    # the transport and this loop will retry the same identity.
                    server.last_error = f"{type(exc).__name__}: {exc}"
                    time.sleep(0.01)
                    continue
                if result is not None:
                    completed.append({
                        "sequence": result.sequence,
                        "replayed": bool(result.replayed),
                        "action": result.action.value,
                        "domain": result.domain.value,
                        "executed": bool(result.executed),
                    })
                downstream_client = server.next_hop_clients["peer-c"]
                if (
                    server.inbound.channel.next_receive_sequence >= 3
                    and not server.outbound.channel.pending_sequences()
                    and not downstream_client.request.channel.pending_sequences()
                    and not downstream_client.response.channel.pending_sequences()
                    and len(completed) >= 2
                ):
                    _write_json_durable(Path(marker_or_result), {
                        "stage": "live_complete",
                        "pid": os.getpid(),
                        "results": completed,
                        "execution_count": len(
                            server.operating_system.hypervisor_arbitration.snapshot()["executions"]
                        ),
                        "request_receive_cursor": server.inbound.channel.next_receive_sequence,
                        "response_pending": list(server.outbound.channel.pending_sequences()),
                        "downstream_request_pending": list(
                            downstream_client.request.channel.pending_sequences()
                        ),
                        "downstream_response_seen": len(
                            downstream_client.response.snapshot()["seen"]
                        ),
                        "journal_valid": server.operating_system.environment.kernel.journal.verify(),
                    })
                    return 0
                time.sleep(0.002)
            raise TimeoutError("live relay did not settle two terminal operations")

        if mode == "prepare":
            operating_system = HeadlessOS()
            operating_system.hypervisor.policy = HypervisorPolicy(
                review_confidence=0.0,
                automatic_confidence=0.0,
                destructive_confidence=0.0,
                danger_review_probability=1.0,
            )
            authority_pid = operating_system.environment.kernel.spawn(
                "federated-process-relay-b",
                capabilities=(Capability(
                    "/network/computational-fabric/forward",
                    frozenset({"forward"}),
                ),),
                parent_pid=operating_system.environment.init_pid,
            )
            server = _new_server(
                config,
                directory,
                operating_system,
                authority_pid,
                inbound,
                downstream,
            )

            def stop_at_cut(stage: str) -> None:
                """Mathematics: hold B at the selected committed protocol boundary only after its peer image is quorum-anchored."""
                if stage != cut:
                    return
                checkpoint = store.seal(server, stage)
                _write_json_durable(Path(marker_or_result), {
                    "stage": "cut",
                    "pid": os.getpid(),
                    "cut": stage,
                    "generation": checkpoint.generation,
                    "manifest_digest": checkpoint.manifest.digest,
                    "execution_count": len(
                        server.operating_system.hypervisor_arbitration.snapshot()["executions"]
                    ),
                    "request_receive_cursor": server.inbound.channel.next_receive_sequence,
                    "response_pending": list(server.outbound.channel.pending_sequences()),
                    "downstream_seen": len(
                        server.next_hop_clients["peer-c"].response.snapshot()["seen"]
                    ),
                    "journal_valid": server.operating_system.environment.kernel.journal.verify(),
                })
                while True:
                    time.sleep(60)

            deadline = time.monotonic() + 40.0
            while time.monotonic() < deadline:
                result = server.serve_once(fault_hook=stop_at_cut)
                if result is not None:
                    raise AssertionError(f"relay B crossed its selected crash cut {cut!r}")
                time.sleep(0.002)
            raise TimeoutError(f"relay B did not reach crash cut {cut!r}")

        assert verified is not None
        server = verified.restore_server(
            inbound,
            directory,
            next_hop_transports={"peer-c": downstream},
        )
        _wait_for_recovery_completion(server, Path(marker_or_result), cut)
        inbound.close()
        for client in server.next_hop_clients.values():
            client.close()
        return 0
    finally:
        if server is not None:
            try:
                server.close()
            except Exception:
                pass
        elif inbound is not None and not inbound.closed:
            inbound.close()
        if downstream is not None and not downstream.closed:
            downstream.close()
        listener.close()
        if control_listener is not None:
            control_listener.close()
        coordinator.close()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
