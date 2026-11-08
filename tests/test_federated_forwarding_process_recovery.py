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
    ComputationalFabricAuthority,
    ComputationalFabricDirectory,
    ComputationalFabricDiscoveryService,
    ComputationalFabricForwardingClient,
    ComputationalFabricPeerListener,
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


def _start_peer_directory_listener(
    authority: ComputationalFabricAuthority,
    client_peer_id: str,
    certificates: dict[str, Path],
) -> tuple[ComputationalFabricPeerListener, threading.Event, threading.Thread, int]:
    """Serve one peer's real snapshot over a peer-pinned mutual-TLS discovery socket."""
    listener_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener_socket.bind(("127.0.0.1", 0))
    listener_socket.listen(8)
    port = int(listener_socket.getsockname()[1])
    listener = ComputationalFabricPeerListener(
        authority,
        listener_socket,
        client_peer_id,
        expected_client_dns=f"{client_peer_id}.fabric.test",
        tls_context=_server_context(certificates, authority.endpoint.peer_id),
        handshake_timeout=8.0,
    )
    stop = threading.Event()
    thread = threading.Thread(
        target=listener.serve_forever,
        args=(stop,),
        daemon=True,
        name=f"directory-{authority.endpoint.peer_id}-for-{client_peer_id}",
    )
    thread.start()
    return listener, stop, thread, port


def _stop_peer_directory_listener(
    item: tuple[ComputationalFabricPeerListener, threading.Event, threading.Thread, int],
) -> None:
    """Close one direct discovery endpoint and join its accept loop."""
    listener, stop, thread, _port = item
    stop.set()
    listener.close()
    thread.join(timeout=5.0)


def _refresh_peer_directory(
    directory: ComputationalFabricDirectory,
    local_peer_id: str,
    control_ports: dict[str, int],
    certificates: dict[str, Path],
) -> tuple[Any, ...]:
    """Reacquire each configured peer's snapshot and local monotonic lease over fresh direct TLS."""
    endpoints = {
        peer_id: ComputationalPeerEndpoint(
            peer_id,
            f"{peer_id}.fabric.test",
            "127.0.0.1",
            port,
        )
        for peer_id, port in sorted(control_ports.items())
    }
    discovery = ComputationalFabricDiscoveryService(
        directory,
        endpoints,
        _client_context(certificates, local_peer_id),
        timeout=8.0,
        refresh_interval=10.0,
    )
    try:
        reports = discovery.refresh_all()
    finally:
        discovery.close()
    assert all(report.connected and report.refreshed and report.active for report in reports), reports
    return reports


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
    operating_system.hypervisor.policy = HypervisorPolicy(
        review_confidence=0.0,
        automatic_confidence=0.0,
        destructive_confidence=0.0,
        danger_review_probability=1.0,
    )
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
@pytest.mark.parametrize("cut", CUTS)
def test_relay_b_hard_process_kill_restarts_from_quorum_and_replays_same_operation(
    cut: str,
    tmp_path: Path,
) -> None:
    """A restarted relay reacquires its direct A/C directory leases over fresh TLS before forwarding resumes."""
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
    advertisement = ComputationalHostAdvertisement.from_locus(catalogue.loci[0], "peer-c")

    # Each peer contributes its own local authority snapshot. Remote snapshots
    # are deliberately absent until a live TLS discovery exchange completes.
    lease_clock = [1_000.0]
    snapshot_a = ComputationalPeerSnapshot(endpoint_a, 1, 2, (), (link_ab,))
    snapshot_b = ComputationalPeerSnapshot(endpoint_b, 1, 2, (), (link_bc,))
    snapshot_c = ComputationalPeerSnapshot(endpoint_c, 1, 2, (advertisement,), ())
    directory_a = ComputationalFabricDirectory(
        "peer-a",
        {
            "peer-b": endpoint_b.tls_server_name,
            "peer-c": endpoint_c.tls_server_name,
        },
        monotonic=lambda: lease_clock[0],
    )
    directory_a.register_local_snapshot(snapshot_a)
    directory_c = ComputationalFabricDirectory(
        "peer-c",
        {"peer-b": endpoint_b.tls_server_name},
        monotonic=lambda: lease_clock[0],
    )
    directory_c.register_local_snapshot(snapshot_c)

    # A serves its own local snapshot to B. C serves its local snapshot on
    # two peer-pinned discovery sockets, one for A and one for B.
    authority_a = ComputationalFabricAuthority.from_snapshot(snapshot_a)
    authority_c = ComputationalFabricAuthority.from_snapshot(snapshot_c)
    discovery_a_for_b = _start_peer_directory_listener(
        authority_a, "peer-b", certificates
    )
    discovery_c_for_a = _start_peer_directory_listener(
        authority_c, "peer-a", certificates
    )
    discovery_c_for_b = _start_peer_directory_listener(
        authority_c, "peer-b", certificates
    )

    config = {
        "membership_path": str(membership_path),
        "lineage_root": str(lineage_root),
        "peer_b_port": peer_b_port,
        "peer_b_cert": str(certificates["peer-b_cert"]),
        "peer_b_key": str(certificates["peer-b_key"]),
        "ca_cert": str(certificates["ca"]),
        "peer_snapshots": {
            item.peer_id: item.to_dict()
            for item in (snapshot_a, snapshot_b, snapshot_c)
        },
        "peer_a_discovery_port_b": discovery_a_for_b[3],
        "peer_c_discovery_port_b": discovery_c_for_b[3],
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
        relay_ready = _wait_ready(relay)
        assert relay_ready["peer"] == "peer-b"
        assert relay_ready["directory_peers"] == ["peer-a", "peer-b", "peer-c"]
        assert relay_ready["discovery_port_a"] != endpoint_b.port
        assert relay_ready["discovery_port_c"] != endpoint_b.port

        # A and C independently discover B from their own pinned control
        # endpoints. The snapshots they receive advertise B's forwarding port.
        _refresh_peer_directory(
            directory_c,
            "peer-c",
            {"peer-b": int(relay_ready["discovery_port_c"])},
            certificates,
        )
        _refresh_peer_directory(
            directory_a,
            "peer-a",
            {
                "peer-b": int(relay_ready["discovery_port_a"]),
                "peer-c": discovery_c_for_a[3],
            },
            certificates,
        )
        active_a = {item.peer_id: item for item in directory_a.active_snapshots}
        assert active_a["peer-b"].endpoint == endpoint_b
        assert active_a["peer-c"].endpoint == endpoint_c
        assert any(item.peer_id == "peer-b" for item in directory_c.active_snapshots)

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

        _kill(relay)
        assert len(calls) == expected_pre_kill_executions
        client_a.close()
        client_a = None

        # Advance only the directory's monotonic lease clock. Both origin A
        # and terminal C must now treat B as unavailable until a new TLS
        # observation refreshes its local lease.
        lease_clock[0] += 3.0
        expired_a = directory_a.purge_expired()
        expired_c = directory_c.purge_expired()
        assert "peer-b" in expired_a
        assert "peer-b" in expired_c
        assert "peer-b" not in {item.peer_id for item in directory_a.active_snapshots}
        assert "peer-b" not in {item.peer_id for item in directory_c.active_snapshots}

        # Reopen C's forwarding server from its own image while retaining its
        # separate direct-discovery listeners. B must reacquire C again too.
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
        restored_ready = _wait_ready(relay_restored)
        assert restored_ready["peer"] == "peer-b"
        assert restored_ready["pid"] != relay.pid
        assert restored_ready["discovery_port_a"] != relay_ready["discovery_port_a"]
        assert restored_ready["discovery_port_c"] != relay_ready["discovery_port_c"]

        # New B sockets mean new discovery handshakes. Reacquisition renews
        # the expired local B lease at A and C without changing B's advertised
        # forwarding endpoint or the route's semantic peer identity.
        _refresh_peer_directory(
            directory_c,
            "peer-c",
            {"peer-b": int(restored_ready["discovery_port_c"])},
            certificates,
        )
        _refresh_peer_directory(
            directory_a,
            "peer-a",
            {
                "peer-b": int(restored_ready["discovery_port_a"]),
                "peer-c": discovery_c_for_a[3],
            },
            certificates,
        )
        assert {
            item.peer_id for item in directory_a.active_snapshots
        } >= {"peer-a", "peer-b", "peer-c"}
        assert {
            item.peer_id for item in directory_c.active_snapshots
        } >= {"peer-b", "peer-c"}

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
        for discovery_listener in (
            discovery_a_for_b,
            discovery_c_for_a,
            discovery_c_for_b,
        ):
            _stop_peer_directory_listener(discovery_listener)

def _send_federated_operation(
    client: ComputationalFabricForwardingClient,
    envelope: ComputationalFabricForwardingEnvelope,
) -> int:
    """Send one origin operation through A's reliable request channel."""
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
    return client.request.send(event)


def _rebind_live_relay(
    control_port: int,
    *,
    peer_id: str = "peer-c",
) -> dict[str, Any]:
    """Ask a surviving relay process to reconnect one downstream peer over fresh mutual TLS."""
    with socket.create_connection(("127.0.0.1", control_port), timeout=25.0) as connection:
        connection.settimeout(25.0)
        connection.sendall(
            json.dumps(
                {"command": "rebind_next_hop", "peer_id": peer_id},
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8") + b"\\n"
        )
        chunks = bytearray()
        while b"\\n" not in chunks and len(chunks) <= 4096:
            part = connection.recv(1024)
            if not part:
                break
            chunks.extend(part)
    assert b"\\n" in chunks, "relay control endpoint closed without a response"
    return json.loads(bytes(chunks).split(b"\\n", 1)[0].decode("utf-8"))


@pytest.mark.parametrize("cut", CUTS)
def test_terminal_peer_c_hard_process_kill_recovers_while_relay_b_survives(
    cut: str,
    tmp_path: Path,
) -> None:
    """C dies at each terminal transaction cut; B preserves the pending route and rebinds C without restarting."""
    root = Path(__file__).resolve().parents[1]
    relay_worker = root / "tests" / "helpers" / "federated_forwarding_relay_worker.py"
    terminal_worker = root / "tests" / "helpers" / "federated_forwarding_terminal_worker.py"
    certificates = _certificates(tmp_path)

    lineage_c = tmp_path / "lineage-c"
    authorities_c = lineage_c / "authorities"
    authorities_c.mkdir(parents=True, exist_ok=True)

    membership_c_path = tmp_path / "membership-c.json"
    membership_c = SeedCommitMembership(
        "federated-terminal-peer-c",
        1,
        ("peer-c", "anchor-e", "anchor-f"),
        "peer-c",
        1,
        hashlib.sha256(b"mailcpu-federated-terminal-peer-c-process-recovery-v1").hexdigest(),
    )
    membership_c_path.write_text(
        json.dumps(membership_c.snapshot(), sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )

    anchor_e, anchor_e_port = _start_anchor(root, "anchor-e", membership_c_path, authorities_c)
    anchor_f, anchor_f_port = _start_anchor(root, "anchor-f", membership_c_path, authorities_c)

    peer_a_port = _free_port()
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

    # Build the portable semantic address and advertisement exactly as the
    # terminal worker will. The PID-bearing local runtime binding stays inside C.
    address_os = HeadlessOS()
    address, catalogue, _calls, _execute_pid = _make_workload(address_os)
    advertisement = ComputationalHostAdvertisement.from_locus(catalogue.loci[0], "peer-c")
    snapshots = (
        ComputationalPeerSnapshot(endpoint_a, 1, 60, (), (link_ab,)),
        ComputationalPeerSnapshot(endpoint_b, 1, 60, (), (link_bc,)),
        ComputationalPeerSnapshot(endpoint_c, 1, 60, (advertisement,), ()),
    )
    directory_a = _directory(snapshots, "peer-a")
    resolved = ComputationalFabricResolver().resolve(
        address,
        directory_a,
        origin_peer_id="peer-a",
    )
    assert resolved.status is ComputationalFabricStatus.FOUND
    assert resolved.witness is not None
    assert resolved.witness.peer_path == ("peer-a", "peer-b", "peer-c")

    calls_path = tmp_path / "terminal-operator-calls.jsonl"
    runtime_path = tmp_path / "terminal-runtime.json"
    config = {
        "membership_path_c": str(membership_c_path),
        "lineage_root_c": str(lineage_c),
        "anchor_e_port": anchor_e_port,
        "anchor_f_port": anchor_f_port,
        "peer_b_port": peer_b_port,
        "peer_c_port": peer_c_port,
        "peer_b_cert": str(certificates["peer-b_cert"]),
        "peer_b_key": str(certificates["peer-b_key"]),
        "peer_c_cert": str(certificates["peer-c_cert"]),
        "peer_c_key": str(certificates["peer-c_key"]),
        "ca_cert": str(certificates["ca"]),
        "peer_snapshots": {item.peer_id: item.to_dict() for item in snapshots},
        "calls_path": str(calls_path),
        "runtime_path": str(runtime_path),
    }
    config_path = tmp_path / "terminal-recovery-config.json"
    config_path.write_text(
        json.dumps(config, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )

    terminal_checkpoint_dir = tmp_path / "peer-c-checkpoints"
    relay_checkpoint_dir = tmp_path / "peer-b-unused-checkpoints"
    cut_marker = tmp_path / "peer-c-cut.json"
    terminal_result = tmp_path / "peer-c-result.json"
    relay_result = tmp_path / "peer-b-result.json"
    processes: list[subprocess.Popen[str]] = [anchor_e, anchor_f]
    client_a: ComputationalFabricForwardingClient | None = None
    terminal_initial: subprocess.Popen[str] | None = None
    terminal_restored: subprocess.Popen[str] | None = None
    relay: subprocess.Popen[str] | None = None

    try:
        terminal_initial = subprocess.Popen(
            [
                sys.executable, str(terminal_worker), "prepare", str(config_path),
                cut, str(cut_marker), str(terminal_checkpoint_dir),
            ],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        processes.append(terminal_initial)
        terminal_ready = _wait_ready(terminal_initial)
        assert terminal_ready["peer"] == "peer-c"

        relay = subprocess.Popen(
            [
                sys.executable, str(relay_worker), "live", str(config_path),
                "live", str(relay_result), str(relay_checkpoint_dir),
            ],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        processes.append(relay)
        relay_ready = _wait_ready(relay)
        assert relay_ready["peer"] == "peer-b"
        assert isinstance(relay_ready["control_port"], int)

        client_a = ComputationalFabricForwardingClient.connect_mutual_tls(
            "peer-a",
            endpoint_b,
            _client_context(certificates, "peer-a"),
            origin_peer_id="peer-a",
            origin_channel="application.batch",
            timeout=8.0,
        )
        first_envelope = ComputationalFabricForwardingEnvelope.begin(
            address,
            resolved.witness,
            origin_channel="application.batch",
            origin_sequence=7,
        )
        assert _send_federated_operation(client_a, first_envelope) == 1

        cut_state = _wait_json(cut_marker, terminal_initial)
        assert cut_state["stage"] == "cut"
        assert cut_state["pid"] == terminal_initial.pid
        assert cut_state["cut"] == cut
        assert cut_state["generation"] == 1
        assert cut_state["request_receive_cursor"] == (
            2 if cut == "after_request_ack" else 1
        )
        assert cut_state["response_pending"] == (
            [1] if cut in {"after_response_publish", "after_request_ack"} else []
        )
        assert cut_state["execution_count"] == (0 if cut == "before_execution" else 1)
        assert cut_state["journal_valid"] is True

        _kill(terminal_initial)
        assert relay.poll() is None, "relay B must remain alive while terminal C is absent"
        calls_before_restart = (
            len(calls_path.read_text(encoding="utf-8").splitlines())
            if calls_path.exists()
            else 0
        )
        assert calls_before_restart == (0 if cut == "before_execution" else 1)

        terminal_restored = subprocess.Popen(
            [
                sys.executable, str(terminal_worker), "restore", str(config_path),
                cut, str(terminal_result), str(terminal_checkpoint_dir),
            ],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        processes.append(terminal_restored)
        restored_ready = _wait_ready(terminal_restored)
        assert restored_ready["peer"] == "peer-c"
        assert restored_ready["pid"] != terminal_initial.pid

        rebound = _rebind_live_relay(int(relay_ready["control_port"]))
        assert rebound["ok"] is True, rebound
        assert rebound["pid"] == relay.pid
        assert rebound["peer_id"] == "peer-c"

        # Receive the original result before issuing fresh work. This may
        # complete before or after the C restart for publication/ACK cuts.
        first_result = _read_forward_results(client_a, 1, relay)[0]
        assert first_result.action.value == "allow"
        assert first_result.executed is True
        first_receipt = ComputationalFabricHopReceipt.from_dict(
            first_result.effect["receipt"]
        )
        assert first_receipt.peer_id == "peer-b"
        assert first_receipt.downstream is not None
        assert first_receipt.downstream.peer_id == "peer-c"
        assert first_receipt.downstream.terminal_execution is not None
        assert first_receipt.downstream.terminal_execution["execution"]["effect"]["result"] == 9

        # A second, new operation forces B to drain any old duplicate C result
        # before accepting the current result; it proves the rebinding path
        # remains useful rather than merely replaying one completed receipt.
        second_envelope = ComputationalFabricForwardingEnvelope.begin(
            address,
            resolved.witness,
            origin_channel="application.batch",
            origin_sequence=8,
        )
        assert _send_federated_operation(client_a, second_envelope) == 2
        second_result = _read_forward_results(client_a, 1, relay)[0]
        assert second_result.action.value == "allow"
        assert second_result.executed is True
        second_receipt = ComputationalFabricHopReceipt.from_dict(
            second_result.effect["receipt"]
        )
        assert second_receipt.downstream is not None
        assert second_receipt.downstream.terminal_execution is not None
        assert second_receipt.downstream.terminal_execution["execution"]["effect"]["result"] == 9

        b_state = _wait_json(relay_result, relay)
        c_state = _wait_json(terminal_result, terminal_restored)
        assert b_state["stage"] == "live_complete"
        assert b_state["pid"] == relay.pid
        assert b_state["execution_count"] == 2
        assert b_state["request_receive_cursor"] == 3
        assert b_state["response_pending"] == []
        assert b_state["downstream_request_pending"] == []
        assert b_state["downstream_response_seen"] == 2
        assert b_state["journal_valid"] is True

        assert c_state["stage"] == "restored_complete"
        assert c_state["pid"] == terminal_restored.pid
        assert c_state["cut"] == cut
        assert c_state["execution_count"] == 2
        assert c_state["request_receive_cursor"] == 3
        assert c_state["response_pending"] == []
        assert c_state["call_count"] == 2
        assert c_state["journal_valid"] is True
        assert len(calls_path.read_text(encoding="utf-8").splitlines()) == 2

        relay_stdout, relay_stderr = relay.communicate(timeout=15)
        assert relay.returncode == 0, (
            f"live relay failed with exit={relay.returncode}\\n"
            f"stdout:\\n{relay_stdout}\\nstderr:\\n{relay_stderr}"
        )
        terminal_stdout, terminal_stderr = terminal_restored.communicate(timeout=15)
        assert terminal_restored.returncode == 0, (
            f"restored terminal failed with exit={terminal_restored.returncode}\\n"
            f"stdout:\\n{terminal_stdout}\\nstderr:\\n{terminal_stderr}"
        )
    finally:
        if client_a is not None:
            client_a.close()
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=10)



def test_relay_then_terminal_hard_kills_preserve_one_federated_operation_history(
    tmp_path: Path,
) -> None:
    """B and then C die in separate generations while A retains one semantic operation history."""
    root = Path(__file__).resolve().parents[1]
    relay_worker = root / "tests" / "helpers" / "federated_forwarding_relay_worker.py"
    terminal_worker = root / "tests" / "helpers" / "federated_forwarding_terminal_worker.py"
    certificates = _certificates(tmp_path)

    # B and C deliberately use distinct owner journals and fixed-membership
    # quorums. Their authority processes remain alive across both peer kills.
    lineage_b = tmp_path / "lineage-b"
    authorities_b = lineage_b / "authorities"
    authorities_b.mkdir(parents=True, exist_ok=True)
    membership_b_path = tmp_path / "membership-b.json"
    membership_b = SeedCommitMembership(
        "federated-reverse-relay-peer-b",
        1,
        ("peer-b", "anchor-c", "anchor-d"),
        "peer-b",
        1,
        hashlib.sha256(b"mailcpu-federated-reverse-peer-b-v1").hexdigest(),
    )
    membership_b_path.write_text(
        json.dumps(membership_b.snapshot(), sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    anchor_c, anchor_c_port = _start_anchor(root, "anchor-c", membership_b_path, authorities_b)
    anchor_d, anchor_d_port = _start_anchor(root, "anchor-d", membership_b_path, authorities_b)

    lineage_c = tmp_path / "lineage-c"
    authorities_c = lineage_c / "authorities"
    authorities_c.mkdir(parents=True, exist_ok=True)
    membership_c_path = tmp_path / "membership-c.json"
    membership_c = SeedCommitMembership(
        "federated-reverse-terminal-peer-c",
        1,
        ("peer-c", "anchor-e", "anchor-f"),
        "peer-c",
        1,
        hashlib.sha256(b"mailcpu-federated-reverse-peer-c-v1").hexdigest(),
    )
    membership_c_path.write_text(
        json.dumps(membership_c.snapshot(), sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    anchor_e, anchor_e_port = _start_anchor(root, "anchor-e", membership_c_path, authorities_c)
    anchor_f, anchor_f_port = _start_anchor(root, "anchor-f", membership_c_path, authorities_c)

    peer_a_port = _free_port()
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

    address_os = HeadlessOS()
    address, catalogue, _calls, _execute_pid = _make_workload(address_os)
    advertisement = ComputationalHostAdvertisement.from_locus(catalogue.loci[0], "peer-c")
    snapshots = (
        ComputationalPeerSnapshot(endpoint_a, 1, 60, (), (link_ab,)),
        ComputationalPeerSnapshot(endpoint_b, 1, 60, (), (link_bc,)),
        ComputationalPeerSnapshot(endpoint_c, 1, 60, (advertisement,), ()),
    )
    directory_a = _directory(snapshots, "peer-a")
    resolved = ComputationalFabricResolver().resolve(
        address,
        directory_a,
        origin_peer_id="peer-a",
    )
    assert resolved.status is ComputationalFabricStatus.FOUND
    assert resolved.witness is not None
    assert resolved.witness.peer_path == ("peer-a", "peer-b", "peer-c")

    calls_path = tmp_path / "terminal-operator-calls.jsonl"
    runtime_path = tmp_path / "terminal-runtime.json"
    terminal_checkpoint_dir = tmp_path / "peer-c-checkpoints"
    relay_checkpoint_dir = tmp_path / "peer-b-checkpoints"
    terminal_idle_marker = tmp_path / "peer-c-idle-checkpoint.json"
    terminal_result = tmp_path / "peer-c-result.json"
    relay_cut_marker = tmp_path / "peer-b-cut.json"
    relay_result = tmp_path / "peer-b-result.json"

    config = {
        "membership_path": str(membership_b_path),
        "lineage_root": str(lineage_b),
        "anchor_c_port": anchor_c_port,
        "anchor_d_port": anchor_d_port,
        "membership_path_c": str(membership_c_path),
        "lineage_root_c": str(lineage_c),
        "anchor_e_port": anchor_e_port,
        "anchor_f_port": anchor_f_port,
        "peer_b_port": peer_b_port,
        "peer_c_port": peer_c_port,
        "peer_b_cert": str(certificates["peer-b_cert"]),
        "peer_b_key": str(certificates["peer-b_key"]),
        "peer_c_cert": str(certificates["peer-c_cert"]),
        "peer_c_key": str(certificates["peer-c_key"]),
        "ca_cert": str(certificates["ca"]),
        "peer_snapshots": {item.peer_id: item.to_dict() for item in snapshots},
        "calls_path": str(calls_path),
        "runtime_path": str(runtime_path),
        "enable_live_checkpoint": True,
        "live_cut": "after_execution_commit",
        "restore_operations": 2,
    }
    config_path = tmp_path / "sequential-recovery-config.json"
    config_path.write_text(
        json.dumps(config, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )

    processes: list[subprocess.Popen[str]] = [
        anchor_c, anchor_d, anchor_e, anchor_f
    ]
    client_a: ComputationalFabricForwardingClient | None = None
    terminal_initial: subprocess.Popen[str] | None = None
    terminal_final: subprocess.Popen[str] | None = None
    relay_live: subprocess.Popen[str] | None = None
    relay_final: subprocess.Popen[str] | None = None

    try:
        # C remains alive after the first operation and seals a quiescent
        # generation only after B has acknowledged its terminal response.
        terminal_initial = subprocess.Popen(
            [
                sys.executable, str(terminal_worker), "live_idle", str(config_path),
                "idle", str(terminal_idle_marker), str(terminal_checkpoint_dir),
            ],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        processes.append(terminal_initial)
        terminal_ready = _wait_ready(terminal_initial)
        assert terminal_ready["peer"] == "peer-c"

        relay_live = subprocess.Popen(
            [
                sys.executable, str(relay_worker), "live", str(config_path),
                "live", str(relay_cut_marker), str(relay_checkpoint_dir),
            ],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        processes.append(relay_live)
        relay_ready = _wait_ready(relay_live)
        assert relay_ready["peer"] == "peer-b"
        assert isinstance(relay_ready["control_port"], int)

        client_a = ComputationalFabricForwardingClient.connect_mutual_tls(
            "peer-a",
            endpoint_b,
            _client_context(certificates, "peer-a"),
            origin_peer_id="peer-a",
            origin_channel="application.batch",
            timeout=8.0,
        )
        first_envelope = ComputationalFabricForwardingEnvelope.begin(
            address,
            resolved.witness,
            origin_channel="application.batch",
            origin_sequence=7,
        )
        assert _send_federated_operation(client_a, first_envelope) == 1
        requester_snapshot = client_a.snapshot()

        # B dies first, after it has durably committed C's terminal receipt.
        # Its own response to A is still unpublished and A retains exact frame 1.
        b_first_cut = _wait_json(relay_cut_marker, relay_live)
        assert b_first_cut["stage"] == "cut"
        assert b_first_cut["pid"] == relay_live.pid
        assert b_first_cut["cut"] == "after_execution_commit"
        assert b_first_cut["generation"] == 1
        assert b_first_cut["execution_count"] == 1
        assert b_first_cut["request_receive_cursor"] == 1
        assert b_first_cut["response_pending"] == []
        assert b_first_cut["downstream_seen"] == 1
        assert b_first_cut["journal_valid"] is True
        assert requester_snapshot["request_channel"]["pending"]["1"]

        # C has consumed B's downstream request and its response has been
        # acknowledged. Seal C's independent idle image before killing it.
        c_idle = _wait_json(terminal_idle_marker, terminal_initial)
        assert c_idle["stage"] == "idle_checkpoint"
        assert c_idle["pid"] == terminal_initial.pid
        assert c_idle["cut"] == "idle"
        assert c_idle["generation"] == 1
        assert c_idle["request_receive_cursor"] == 2
        assert c_idle["response_pending"] == []
        assert c_idle["execution_count"] == 1
        assert c_idle["journal_valid"] is True

        # Preserve the requested order: terminate relay B, then terminal C.
        _kill(relay_live)
        client_a.close()
        client_a = None
        _kill(terminal_initial)

        # Restore C first so the replacement B can establish a fresh mutual-TLS
        # adjacency without inheriting the prior socket or transport object.
        terminal_final = subprocess.Popen(
            [
                sys.executable, str(terminal_worker), "restore_latest", str(config_path),
                "idle", str(terminal_result), str(terminal_checkpoint_dir),
            ],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        processes.append(terminal_final)
        c_final_ready = _wait_ready(terminal_final)
        assert c_final_ready["peer"] == "peer-c"
        assert c_final_ready["pid"] != terminal_initial.pid

        relay_final = subprocess.Popen(
            [
                sys.executable, str(relay_worker), "restore", str(config_path),
                "after_execution_commit", str(relay_result), str(relay_checkpoint_dir),
            ],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        processes.append(relay_final)
        b_final_ready = _wait_ready(relay_final)
        assert b_final_ready["peer"] == "peer-b"
        assert b_final_ready["pid"] != relay_live.pid

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

        first_result = _read_forward_results(client_a, 1, relay_final)[0]
        assert first_result.action.value == "allow"
        assert first_result.executed is True
        assert first_result.replayed is True
        first_receipt = ComputationalFabricHopReceipt.from_dict(
            first_result.effect["receipt"]
        )
        assert first_receipt.peer_id == "peer-b"
        assert first_receipt.downstream is not None
        assert first_receipt.downstream.peer_id == "peer-c"
        assert first_receipt.downstream.terminal_execution is not None
        assert first_receipt.downstream.terminal_execution["execution"]["effect"]["result"] == 9

        # A new operation after both process deaths proves the restored channel
        # cursors and semantic ledgers can advance together, not merely replay.
        second_envelope = ComputationalFabricForwardingEnvelope.begin(
            address,
            resolved.witness,
            origin_channel="application.batch",
            origin_sequence=8,
        )
        assert _send_federated_operation(client_a, second_envelope) == 2
        second_result = _read_forward_results(client_a, 1, relay_final)[0]
        assert second_result.action.value == "allow"
        assert second_result.executed is True
        assert second_result.replayed is False
        second_receipt = ComputationalFabricHopReceipt.from_dict(
            second_result.effect["receipt"]
        )
        assert second_receipt.downstream is not None
        assert second_receipt.downstream.peer_id == "peer-c"
        assert second_receipt.downstream.terminal_execution is not None
        assert second_receipt.downstream.terminal_execution["execution"]["effect"]["result"] == 9

        b_final_state = _wait_json(relay_result, relay_final)
        c_final_state = _wait_json(terminal_result, terminal_final)
        assert b_final_state["stage"] == "recovered"
        assert b_final_state["pid"] == relay_final.pid
        assert b_final_state["execution_count"] == 2
        assert b_final_state["request_receive_cursor"] == 3
        assert b_final_state["response_pending"] == []
        assert b_final_state["downstream_seen"] == 2
        assert b_final_state["journal_valid"] is True

        assert c_final_state["stage"] == "restored_complete"
        assert c_final_state["pid"] == terminal_final.pid
        assert c_final_state["cut"] == "idle"
        assert c_final_state["execution_count"] == 2
        assert c_final_state["request_receive_cursor"] == 3
        assert c_final_state["response_pending"] == []
        assert c_final_state["call_count"] == 2
        assert c_final_state["journal_valid"] is True
        assert len(calls_path.read_text(encoding="utf-8").splitlines()) == 2

        relay_stdout, relay_stderr = relay_final.communicate(timeout=20)
        assert relay_final.returncode == 0, (
            f"restored B exited with {relay_final.returncode}\n"
            f"stdout:\n{relay_stdout}\nstderr:\n{relay_stderr}"
        )
        terminal_stdout, terminal_stderr = terminal_final.communicate(timeout=20)
        assert terminal_final.returncode == 0, (
            f"restored C exited with {terminal_final.returncode}\n"
            f"stdout:\n{terminal_stdout}\nstderr:\n{terminal_stderr}"
        )
    finally:
        if client_a is not None:
            client_a.close()
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=10)
