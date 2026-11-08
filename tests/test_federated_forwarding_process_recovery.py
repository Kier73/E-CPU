"""Hard-kill relay B at every forwarding transaction cut and recover it from disk."""

from __future__ import annotations

import hashlib
import json
import os
import socket
import ssl
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from mailcpu import (
    Capability,
    ComputationalAddress,
    ComputationalFabricDirectory,
    ComputationalFabricForwardingClient,
    ComputationalFabricForwardingEnvelope,
    ComputationalFabricForwardingServer,
    ComputationalFabricHopReceipt,
    ComputationalFabricResolver,
    ComputationalFabricStatus,
    ComputationalHostAdvertisement,
    ComputationalHostCatalogue,
    ComputationalHostLocus,
    ComputationalNetworkLink,
    ComputationalPeerEndpoint,
    ComputationalPeerSnapshot,
    HeadlessOS,
    HypervisorArbitrationEvent,
    HypervisorExecutionResult,
    HypervisorOperationResultChannel,
    HypervisorRequest,
    HypervisorPolicy,
    OperatorRegistry,
    OperatorSpec,
    RouteMetric,
    RouteMetricKey,
    SeedCommitMembership,
    SystemIdentity,
    SystemSeed,
    SystemSeedEnvelope,
    VirtualBudget,
    VirtualGroundRef,
    VirtualLayerRuntime,
    VirtualLayerWorkload,
    VirtualOperatorRef,
    SocketTransport,
)
from mailcpu.computational_fabric_forwarding import (
    COMPUTATIONAL_FABRIC_EXECUTE_RESOURCE,
    COMPUTATIONAL_FABRIC_FORWARD_OPERATION,
    COMPUTATIONAL_FABRIC_FORWARD_RESOURCE,
)
from mailcpu.mtls_transport import accept_mutual_tls, connect_mutual_tls


CUTS = (
    "before_execution",
    "after_execution_commit",
    "after_response_publish",
    "after_request_ack",
)
GENESIS = hashlib.sha256(b"mailcpu-federated-relay-b-process-recovery-v1").hexdigest()
GROUND_FP = "a" * 64
PROGRAM_FP = "b" * 64
IMPLEMENTATION_FP = "c" * 64
METRICS = (
    RouteMetricKey("latency", "ticks"),
    RouteMetricKey("energy", "units"),
    RouteMetricKey("bytes", "bytes"),
    RouteMetricKey("risk", "score"),
)


def _openssl(cwd: Path, *arguments: str) -> None:
    """Mathematics: run one bounded certificate-generation command and require successful exit."""
    result = subprocess.run(
        ["openssl", *arguments],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise AssertionError(f"openssl failed: {result.stderr}")


def _certificates(root: Path) -> dict[str, Path]:
    """Mathematics: create one test CA and three distinct leaf identities for A, B and C."""
    ca_key = root / "ca.key"
    ca_cert = root / "ca.pem"
    _openssl(
        root,
        "req", "-x509", "-newkey", "rsa:2048", "-nodes",
        "-keyout", str(ca_key), "-out", str(ca_cert),
        "-days", "30", "-sha256", "-subj", "/CN=Federated Recovery Test CA",
        "-addext", "basicConstraints=critical,CA:TRUE",
        "-addext", "keyUsage=critical,keyCertSign,cRLSign",
    )
    result: dict[str, Path] = {"ca": ca_cert}
    for peer_id in ("peer-a", "peer-b", "peer-c"):
        key = root / f"{peer_id}.key"
        csr = root / f"{peer_id}.csr"
        cert = root / f"{peer_id}.pem"
        ext = root / f"{peer_id}.ext"
        _openssl(
            root,
            "req", "-new", "-newkey", "rsa:2048", "-nodes",
            "-keyout", str(key), "-out", str(csr),
            "-subj", f"/CN={peer_id}.fabric.test",
        )
        ext.write_text(
            "\n".join((
                f"subjectAltName=DNS:{peer_id}.fabric.test",
                "extendedKeyUsage=clientAuth,serverAuth",
                "basicConstraints=critical,CA:FALSE",
                "keyUsage=critical,digitalSignature,keyEncipherment",
            )) + "\n",
            encoding="utf-8",
        )
        _openssl(
            root,
            "x509", "-req", "-in", str(csr),
            "-CA", str(ca_cert), "-CAkey", str(ca_key), "-CAcreateserial",
            "-out", str(cert), "-days", "30", "-sha256",
            "-extfile", str(ext),
        )
        result[f"{peer_id}_cert"] = cert
        result[f"{peer_id}_key"] = key
    return result


def _server_context(certificates: dict[str, Path], peer_id: str) -> ssl.SSLContext:
    """Mathematics: require a CA-verified client certificate for one exact server peer identity."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(
        str(certificates[f"{peer_id}_cert"]),
        str(certificates[f"{peer_id}_key"]),
    )
    context.load_verify_locations(cafile=str(certificates["ca"]))
    context.verify_mode = ssl.CERT_REQUIRED
    return context


def _client_context(certificates: dict[str, Path], peer_id: str) -> ssl.SSLContext:
    """Mathematics: verify server DNS identity and present the selected peer's CA-signed client certificate."""
    context = ssl.create_default_context(
        ssl.Purpose.SERVER_AUTH,
        cafile=str(certificates["ca"]),
    )
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(
        str(certificates[f"{peer_id}_cert"]),
        str(certificates[f"{peer_id}_key"]),
    )
    return context


def _link(source: str, target: str, latency: int) -> ComputationalNetworkLink:
    """Mathematics: create one directed fabric edge in the common four-dimensional cost basis."""
    return ComputationalNetworkLink(
        source,
        target,
        (
            RouteMetric("latency", "ticks", latency),
            RouteMetric("energy", "units", 1),
            RouteMetric("bytes", "bytes", 64),
            RouteMetric("risk", "score", 0),
        ),
        max_frame_bytes=1_048_576,
    )


def _costs(latency: int) -> tuple[RouteMetric, ...]:
    """Mathematics: return a host cost vector compatible with the fabric route objective."""
    return (
        RouteMetric("latency", "ticks", latency),
        RouteMetric("energy", "units", 20),
        RouteMetric("bytes", "bytes", 128),
        RouteMetric("risk", "score", 0),
    )


def _spec() -> OperatorSpec:
    """Mathematics: declare one deterministic pure CPU/GPU addition operator for terminal execution."""
    return OperatorSpec(
        operator_id="core.sum_pair",
        version=1,
        description="Add two integers from a JSON object",
        input_kind="object",
        output_kind="integer",
        substrates=("cpu", "gpu"),
        required_rights=frozenset({"compute"}),
        base_energy=8,
        energy_per_byte=1,
        max_input_bytes=4096,
        max_output_bytes=64,
        deterministic=True,
        effect_mode="pure",
    )


def _wait_ready(process: subprocess.Popen[str]) -> dict[str, Any]:
    """Read the relay's one-line listener advertisement or report its startup traceback."""
    assert process.stdout is not None
    line = process.stdout.readline()
    assert line, (
        "relay process exited before publishing its listener: "
        f"returncode={process.poll()}, stderr={process.stderr.read() if process.stderr else None!r}"
    )
    value = json.loads(line)
    assert value["pid"] == process.pid
    return value


def _read_json(path: Path) -> dict[str, Any] | None:
    """Read a complete durable marker while tolerating transient replacement and sharing errors."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (FileNotFoundError, PermissionError, json.JSONDecodeError):
        return None


def _wait_json(path: Path, process: subprocess.Popen[str], timeout: float = 40.0) -> dict[str, Any]:
    """Wait for a child marker without mistaking process liveness for a completed recovery cut."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and process.poll() is None:
        value = _read_json(path)
        if value is not None:
            return value
        time.sleep(0.01)
    value = _read_json(path)
    assert value is not None, (
        f"relay did not publish {path.name}: returncode={process.poll()}, "
        f"stderr={process.stderr.read() if process.stderr else None!r}"
    )
    return value


def _kill(process: subprocess.Popen[str]) -> None:
    """Hard-kill one child interpreter and require its process handle to become terminal."""
    if process.poll() is None:
        process.kill()
    process.communicate(timeout=10)
    assert process.returncode is not None and process.returncode != 0


def _free_port() -> int:
    """Choose an available loopback TCP port for a stable peer endpoint across B restart."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    port = int(listener.getsockname()[1])
    listener.close()
    return port


def _start_anchor(
    root: Path,
    member_id: str,
    membership_path: Path,
    journal_root: Path,
) -> tuple[subprocess.Popen[str], int]:
    """Launch an independent durable authority process with reconnectable owner streams."""
    worker = root / "tests" / "helpers" / "federated_forwarding_anchor_worker.py"
    process = subprocess.Popen(
        [
            sys.executable,
            str(worker),
            member_id,
            str(membership_path),
            str(journal_root / f"{member_id}.jsonl"),
        ],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    ready = _wait_ready(process)
    assert ready["member_id"] == member_id
    return process, int(ready["port"])


def _directory(
    snapshots: tuple[ComputationalPeerSnapshot, ...],
    local_peer_id: str,
) -> ComputationalFabricDirectory:
    """Admit a local snapshot and direct authenticated test observations for each remote peer."""
    trusted = {
        snapshot.peer_id: snapshot.endpoint.tls_server_name
        for snapshot in snapshots
        if snapshot.peer_id != local_peer_id
    }
    directory = ComputationalFabricDirectory(local_peer_id, trusted)
    for snapshot in snapshots:
        if snapshot.peer_id == local_peer_id:
            directory.register_local_snapshot(snapshot)
        else:
            directory._merge_verified_peer_snapshot(
                snapshot,
                authenticated_peer_id=snapshot.peer_id,
                authenticated_server_name=snapshot.endpoint.tls_server_name,
            )
    return directory


def _start_terminal_service(
    listener: socket.socket,
    directory: ComputationalFabricDirectory,
    operating_system: HeadlessOS,
    execute_pid: int,
    catalogue: ComputationalHostCatalogue,
    certificates: dict[str, Path],
    *,
    snapshot: dict[str, Any] | None = None,
) -> tuple[threading.Thread, threading.Event, dict[str, Any], list[BaseException]]:
    """Accept B over mutual TLS, optionally restore C, then service its local terminal execution boundary."""
    holder: dict[str, Any] = {}
    failures: list[BaseException] = []
    stop = threading.Event()

    def run() -> None:
        """Mathematics: own C's accepted TLS stream and serialized serving transitions until the supervisor stops the peer."""
        try:
            transport = accept_mutual_tls(
                listener,
                "peer-c",
                "peer-b",
                _server_context(certificates, "peer-c"),
                expected_peer_dns="peer-b.fabric.test",
                handshake_timeout=8.0,
            )
            if snapshot is None:
                server = ComputationalFabricForwardingServer(
                    "peer-c",
                    "peer-b",
                    transport,
                    directory,
                    operating_system,
                    execute_pid,
                    origin_peer_id="peer-a",
                    origin_channel="application.batch",
                    catalogue=catalogue,
                    timeout=8.0,
                )
            else:
                restored_os = HeadlessOS.from_snapshot(snapshot["operating_system"])
                server = ComputationalFabricForwardingServer.from_snapshot(
                    snapshot,
                    transport,
                    directory,
                    catalogue=catalogue,
                    operating_system=restored_os,
                )
            holder["server"] = server
            listener.close()
            while not stop.is_set():
                try:
                    server.serve_once()
                except Exception as exc:
                    if not stop.is_set():
                        failures.append(exc)
                    return
                time.sleep(0.001)
        except BaseException as exc:
            failures.append(exc)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread, stop, holder, failures


def _wait_terminal_response_ack(server: ComputationalFabricForwardingServer, timeout: float = 8.0) -> None:
    """Wait until C's result sender has processed the ACK emitted by B's downstream client."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and server.outbound.channel.pending_sequences():
        time.sleep(0.005)
    assert server.outbound.channel.pending_sequences() == ()


def _make_workload(operating_system: HeadlessOS) -> tuple[ComputationalAddress, ComputationalHostCatalogue, list[str], int]:
    """Create C's deterministic terminal operator and return its distinct network receive authority PID."""
    system_identity = SystemIdentity("federated-process-recovery-system", 1)
    seed = SystemSeed.from_system(operating_system)
    seed_envelope = SystemSeedEnvelope(
        system_identity,
        "federated-process-recovery",
        "federated-process-recovery",
        seed,
    )
    assert operating_system.seed_admission.admit(seed_envelope).accepted
    ground = VirtualGroundRef.from_envelope(seed_envelope)
    calls: list[str] = []
    registry = OperatorRegistry()
    spec = _spec()

    def execute(value, workload):
        """Mathematics: enter the terminal pure operator once for the semantic federated workload."""
        calls.append(workload.workload_id)
        return value["left"] + value["right"]

    registry.register(spec, execute)
    runtime = VirtualLayerRuntime(registry, "node-c", frozenset({"cpu"}))
    compute_pid = operating_system.environment.kernel.spawn(
        "federated-terminal-compute",
        capabilities=(Capability("/virtual-layer/operators", frozenset({"compute"})),),
        parent_pid=operating_system.environment.init_pid,
    )
    locus = ComputationalHostLocus.from_runtime(
        host_id="logical-host-c",
        runtime=runtime,
        authority_pid=compute_pid,
        operator_id="core.sum_pair",
        computational_ground_fingerprints=(GROUND_FP,),
        program_fingerprints=(PROGRAM_FP,),
        costs=_costs(3),
        implementation_fingerprint=IMPLEMENTATION_FP,
    )
    catalogue = ComputationalHostCatalogue((locus,))
    # The terminal NETWORK-domain gate is distinct from the host process's
    # Virtual Layer compute right; the selected host still receives its own
    # independently checked CPU/compute admission at the destination.
    forwarding_pid = operating_system.environment.kernel.spawn(
        "federated-terminal-network-gate",
        capabilities=(Capability(
            COMPUTATIONAL_FABRIC_EXECUTE_RESOURCE,
            frozenset({"execute"}),
        ),),
        parent_pid=operating_system.environment.init_pid,
    )
    address_workload = VirtualLayerWorkload(
        workload_id="federated-process-recovery-sum",
        system=system_identity,
        ground=ground,
        intention={"goal": {"kind": "sum", "expected": 9}},
        operators=(VirtualOperatorRef("core.sum_pair", 1, "cpu"),),
        input_value={"left": 4, "right": 5},
        budget=VirtualBudget(10_000, 10_000, 10_000),
        logical_time=23,
        eligible_nodes=("node-c",),
        max_hops=2,
    )
    address = ComputationalAddress.from_workload(
        address_workload,
        "core.sum_pair",
        spec,
        GROUND_FP,
        program_fingerprint=PROGRAM_FP,
        metric_order=METRICS,
    )
    return address, catalogue, calls, forwarding_pid


def _read_forward_results(
    client: ComputationalFabricForwardingClient,
    count: int,
    process: subprocess.Popen[str],
    timeout: float = 30.0,
) -> list[HypervisorExecutionResult]:
    """Consume exactly the expected transport result frames while draining the original operation ACK."""
    results: list[HypervisorExecutionResult] = []
    deadline = time.monotonic() + timeout
    while len(results) < count and time.monotonic() < deadline:
        client.request.channel.process_ack()
        result = client.response.receive()
        if result is not None:
            results.append(result)
            continue
        if process.poll() is not None:
            stdout, stderr = process.communicate(timeout=5)
            raise AssertionError(
                "relay B exited before returning the recovered receipt: "
                f"returncode={process.returncode}, stdout={stdout!r}, stderr={stderr!r}"
            )
        time.sleep(0.002)
    assert len(results) == count, (
        f"expected {count} forwarding results, received {len(results)}; "
        f"relay_returncode={process.poll()}"
    )
    return results


@pytest.mark.parametrize("cut", CUTS)
def test_relay_b_hard_process_kill_restarts_from_quorum_and_replays_same_operation(
    cut: str,
    tmp_path: Path,
) -> None:
    """A real B interpreter dies at every request/commit/publish/ACK cut and resumes over fresh TLS streams."""
    root = Path(__file__).resolve().parents[1]
    worker = root / "tests" / "helpers" / "federated_forwarding_relay_worker.py"
    certificates = _certificates(tmp_path)
    lineage_root = tmp_path / "lineage"
    anchors_dir = lineage_root / "authorities"
    anchors_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_dir = tmp_path / "peer-b-checkpoints"
    membership_path = tmp_path / "membership.json"
    membership = SeedCommitMembership(
        "federated-relay-peer-b",
        1,
        ("peer-b", "anchor-c", "anchor-d"),
        "peer-b",
        1,
        GENESIS,
    )
    membership_path.write_text(
        json.dumps(membership.snapshot(), sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    anchor_c, anchor_c_port = _start_anchor(root, "anchor-c", membership_path, anchors_dir)
    anchor_d, anchor_d_port = _start_anchor(root, "anchor-d", membership_path, anchors_dir)

    peer_a_port = 44001
    peer_b_port = _free_port()
    peer_c_port = _free_port()
    endpoint_a = ComputationalPeerEndpoint(
        "peer-a", "peer-a.fabric.test", "127.0.0.1", peer_a_port
    )
    endpoint_b = ComputationalPeerEndpoint(
        "peer-b", "peer-b.fabric.test", "127.0.0.1", peer_b_port
    )
    endpoint_c = ComputationalPeerEndpoint(
        "peer-c", "peer-c.fabric.test", "127.0.0.1", peer_c_port
    )
    link_ab = _link("peer-a", "peer-b", 2)
    link_bc = _link("peer-b", "peer-c", 3)
    operating_system = HeadlessOS()
    address, catalogue, calls, execute_pid = _make_workload(operating_system)
    locus = catalogue.loci[0]
    advertisement = ComputationalHostAdvertisement.from_locus(locus, "peer-c")
    snapshot_a = ComputationalPeerSnapshot(endpoint_a, 1, 60, (), (link_ab,))
    snapshot_b = ComputationalPeerSnapshot(endpoint_b, 1, 60, (), (link_bc,))
    snapshot_c = ComputationalPeerSnapshot(endpoint_c, 1, 60, (advertisement,), ())
    snapshots = (snapshot_a, snapshot_b, snapshot_c)
    directory_a = _directory(snapshots, "peer-a")
    directory_b = _directory(snapshots, "peer-b")
    directory_c = _directory((snapshot_b, snapshot_c), "peer-c")
    resolved = ComputationalFabricResolver().resolve(
        address,
        directory_a,
        origin_peer_id="peer-a",
    )
    assert resolved.status is ComputationalFabricStatus.FOUND
    assert resolved.witness is not None
    assert resolved.witness.peer_path == ("peer-a", "peer-b", "peer-c")
    envelope = ComputationalFabricForwardingEnvelope.begin(
        address,
        resolved.witness,
        origin_channel="application.batch",
        origin_sequence=7,
    )

    config = {
        "membership_path": str(membership_path),
        "lineage_root": str(lineage_root),
        "anchor_c_port": anchor_c_port,
        "anchor_d_port": anchor_d_port,
        "peer_b_port": peer_b_port,
        "peer_b_cert": str(certificates["peer-b_cert"]),
        "peer_b_key": str(certificates["peer-b_key"]),
        "ca_cert": str(certificates["ca"]),
        "peer_snapshots": {item.peer_id: item.to_dict() for item in snapshots},
    }
    config_path = tmp_path / "relay-config.json"
    config_path.write_text(
        json.dumps(config, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    marker_path = tmp_path / "relay-cut.json"
    result_path = tmp_path / "relay-result.json"
    processes: list[subprocess.Popen[str]] = [anchor_c, anchor_d]
    client_a: ComputationalFabricForwardingClient | None = None
    transport_a: SocketTransport | None = None
    terminal_listener = SocketTransport.listen("127.0.0.1", peer_c_port)
    terminal_thread: threading.Thread | None = None
    terminal_stop: threading.Event | None = None
    terminal_holder: dict[str, Any] = {}
    terminal_failures: list[BaseException] = []
    terminal_snapshot: dict[str, Any] | None = None
    relay: subprocess.Popen[str] | None = None
    relay_restored: subprocess.Popen[str] | None = None
    terminal_listener_rebound: socket.socket | None = None
    terminal_thread_rebound: threading.Thread | None = None
    terminal_stop_rebound: threading.Event | None = None
    terminal_holder_rebound: dict[str, Any] = {}
    terminal_failures_rebound: list[BaseException] = []
    try:
        terminal_thread, terminal_stop, terminal_holder, terminal_failures = _start_terminal_service(
            terminal_listener,
            directory_c,
            operating_system,
            execute_pid,
            catalogue,
            certificates,
        )
        relay = subprocess.Popen(
            [sys.executable, str(worker), "prepare", str(config_path), cut, str(marker_path), str(checkpoint_dir)],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        processes.append(relay)
        _wait_ready(relay)
        client_a = ComputationalFabricForwardingClient.connect_mutual_tls(
            "peer-a",
            endpoint_b,
            _client_context(certificates, "peer-a"),
            origin_peer_id="peer-a",
            origin_channel="application.batch",
            timeout=8.0,
        )
        request = HypervisorRequest(
            COMPUTATIONAL_FABRIC_FORWARD_OPERATION,
            COMPUTATIONAL_FABRIC_FORWARD_RESOURCE,
            {"envelope": envelope.advance().to_dict()},
            frozenset({"forward"}),
            frozenset(),
            False,
        )
        event = HypervisorArbitrationEvent(
            "peer-a",
            envelope.channel_id,
            envelope.origin_sequence,
            envelope.logical_time,
            request,
        )
        assert client_a.request.send(event) == 1
        requester_snapshot = client_a.snapshot()

        cut_marker = _wait_json(marker_path, relay)
        assert cut_marker["stage"] == "cut"
        assert cut_marker["pid"] == relay.pid
        assert cut_marker["cut"] == cut
        assert cut_marker["generation"] == 1
        assert cut_marker["request_receive_cursor"] == (
            2 if cut == "after_request_ack" else 1
        )
        assert cut_marker["response_pending"] == (
            [1] if cut in {"after_response_publish", "after_request_ack"} else []
        )
        expected_pre_kill_executions = 0 if cut == "before_execution" else 1
        assert cut_marker["execution_count"] == expected_pre_kill_executions
        assert cut_marker["journal_valid"] is True
        assert requester_snapshot["request_channel"]["pending"]["1"]

        terminal_server = terminal_holder["server"]
        if cut != "before_execution":
            _wait_terminal_response_ack(terminal_server)
        terminal_stop.set()
        terminal_thread.join(timeout=5.0)
        assert not terminal_thread.is_alive()
        assert not terminal_failures
        terminal_snapshot = terminal_server.snapshot(capture_cut="idle")
        terminal_server.close()
        terminal_listener.close()

        # B is the only computational peer process destroyed here. A's sender
        # snapshot and C's terminal execution/reliable-channel image are held
        # by the independent supervising process.
        _kill(relay)
        assert len(calls) == expected_pre_kill_executions
        client_a.close()
        client_a = None

        # Reopen C's server from its own state before B reconnects.
        terminal_listener_rebound = SocketTransport.listen("127.0.0.1", peer_c_port)
        terminal_thread_rebound, terminal_stop_rebound, terminal_holder_rebound, terminal_failures_rebound = (
            _start_terminal_service(
                terminal_listener_rebound,
                directory_c,
                operating_system,
                execute_pid,
                catalogue,
                certificates,
                snapshot=terminal_snapshot,
            )
        )

        relay_restored = subprocess.Popen(
            [sys.executable, str(worker), "restore", str(config_path), cut, str(result_path), str(checkpoint_dir)],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        processes.append(relay_restored)
        _wait_ready(relay_restored)
        client_a = ComputationalFabricForwardingClient.from_snapshot(
            requester_snapshot,
            connect_mutual_tls(
                endpoint_b.endpoint_host,
                endpoint_b.port,
                "peer-a",
                "peer-b",
                _client_context(certificates, "peer-a"),
                server_hostname=endpoint_b.tls_server_name,
                timeout=8.0,
                handshake_timeout=8.0,
            ),
        )
        assert client_a.request.channel.pending_sequences() == (1,)
        assert client_a.request.channel.retransmit(1) is True

        expected_frames = 2 if cut == "after_response_publish" else 1
        recovered_results = _read_forward_results(client_a, expected_frames, relay_restored)
        assert recovered_results[0].action.value == "allow"
        assert recovered_results[0].executed is True
        assert recovered_results[0].domain.value == "network"
        receipts = [
            ComputationalFabricHopReceipt.from_dict(item.effect["receipt"])
            for item in recovered_results
        ]
        assert all(item.succeeded for item in receipts)
        assert all(item.peer_id == "peer-b" for item in receipts)
        assert all(item.downstream is not None for item in receipts)
        assert all(item.downstream.peer_id == "peer-c" for item in receipts)
        assert all(item.downstream.terminal_execution is not None for item in receipts)
        assert all(
            item.downstream.terminal_execution["execution"]["effect"]["result"] == 9
            for item in receipts
        )
        assert len({item.digest for item in receipts}) == 1
        assert recovered_results[0].replayed is False
        if cut == "after_response_publish":
            assert recovered_results[1].replayed is True

        # The live terminal process retains its exact local replay ledger.
        # B's post-commit replay must reuse C's receipt instead of executing C
        # again; before_execution is the only cut that executes C after B dies.
        expected_final_calls = 1
        assert calls == ["federated-process-recovery-sum"]
        terminal_restored = terminal_holder_rebound["server"]
        assert len(
            terminal_restored.operating_system.hypervisor_arbitration.snapshot()["executions"]
        ) == 1
        assert not terminal_failures_rebound

        relay_result = _wait_json(result_path, relay_restored)
        assert relay_result["stage"] == "recovered"
        assert relay_result["pid"] == relay_restored.pid
        assert relay_result["cut"] == cut
        assert relay_result["execution_count"] == 1
        assert relay_result["request_receive_cursor"] == 2
        assert relay_result["response_pending"] == []
        assert relay_result["downstream_seen"] == 1
        assert relay_result["journal_valid"] is True
        if cut == "after_request_ack":
            assert relay_result["results"] == []
        else:
            assert len(relay_result["results"]) == 1
            assert relay_result["results"][0]["replayed"] is (
                cut in {"after_execution_commit", "after_response_publish"}
            )
        assert len(calls) == expected_final_calls

        relay_stdout, relay_stderr = relay_restored.communicate(timeout=20)
        assert relay_restored.returncode == 0, (
            f"restored B exited with {relay_restored.returncode}\n"
            f"stdout:\n{relay_stdout}\nstderr:\n{relay_stderr}"
        )
    finally:
        if client_a is not None:
            client_a.close()
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=10)
        if terminal_stop is not None:
            terminal_stop.set()
        if terminal_stop_rebound is not None:
            terminal_stop_rebound.set()
        for thread in (terminal_thread, terminal_thread_rebound):
            if thread is not None:
                thread.join(timeout=5.0)
        for holder in (terminal_holder, terminal_holder_rebound):
            for server in holder.values():
                server.close()
        terminal_listener.close()
        if terminal_listener_rebound is not None:
            terminal_listener_rebound.close()
