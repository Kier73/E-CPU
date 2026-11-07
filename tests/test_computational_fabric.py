from __future__ import annotations

from dataclasses import replace
import shutil
import socket
import ssl
import subprocess
import threading
import time
from pathlib import Path

import pytest

from mailcpu import (
    Capability,
    ComputationalAddress,
    ComputationalFabricAuthority,
    ComputationalFabricDirectory,
    ComputationalFabricPeerClient,
    ComputationalFabricPeerServer,
    ComputationalFabricResolver,
    ComputationalFabricStatus,
    ComputationalHostAdvertisement,
    ComputationalHostLocus,
    ComputationalNetworkLink,
    ComputationalPeerEndpoint,
    ComputationalPeerSnapshot,
    HeadlessOS,
    OperatorRegistry,
    OperatorSpec,
    RouteMetric,
    RouteMetricKey,
    SystemIdentity,
    SystemSeed,
    SystemSeedEnvelope,
    VirtualBudget,
    VirtualGroundRef,
    VirtualLayerRuntime,
    VirtualLayerWorkload,
    VirtualOperatorRef,
)
from mailcpu.computational_fabric import ComputationalFabricError
from mailcpu.mtls_transport import accept_mutual_tls
from mailcpu.socket_transport import SocketTransport

GROUND_FP = "a" * 64
PROGRAM_FP = "b" * 64
IMPLEMENTATION_FP = "c" * 64
METRICS = (
    RouteMetricKey("latency", "ticks"),
    RouteMetricKey("energy", "units"),
    RouteMetricKey("bytes", "bytes"),
    RouteMetricKey("risk", "score"),
)


def _openssl(tmp_path: Path, *arguments: str) -> None:
    """Mathematics: Run one bounded certificate-generation command and require successful exit."""
    result = subprocess.run(
        ["openssl", *arguments],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise AssertionError(f"openssl failed: {result.stderr}")


def _make_test_certificates(tmp_path: Path) -> dict[str, Path]:
    """Mathematics: Create one CA and two mutually trusted leaf certificates with distinct DNS SANs."""
    ca_key = tmp_path / "ca.key"
    ca_cert = tmp_path / "ca.pem"
    _openssl(
        tmp_path,
        "req", "-x509", "-newkey", "rsa:2048", "-nodes",
        "-keyout", str(ca_key), "-out", str(ca_cert),
        "-days", "30", "-sha256", "-subj", "/CN=Computational Fabric Test CA",
        "-addext", "basicConstraints=critical,CA:TRUE",
        "-addext", "keyUsage=critical,keyCertSign,cRLSign",
    )
    files: dict[str, Path] = {"ca": ca_cert}
    for role, dns_name in (("server", "peer-b.fabric.test"), ("client", "peer-a.fabric.test")):
        key = tmp_path / f"{role}.key"
        csr = tmp_path / f"{role}.csr"
        certificate = tmp_path / f"{role}.pem"
        extensions = tmp_path / f"{role}.ext"
        _openssl(
            tmp_path,
            "req", "-new", "-newkey", "rsa:2048", "-nodes",
            "-keyout", str(key), "-out", str(csr),
            "-subj", f"/CN={dns_name}",
        )
        extensions.write_text(
            "\n".join((
                f"subjectAltName=DNS:{dns_name}",
                "extendedKeyUsage=clientAuth,serverAuth",
                "basicConstraints=critical,CA:FALSE",
                "keyUsage=critical,digitalSignature,keyEncipherment",
            )) + "\n",
            encoding="utf-8",
        )
        _openssl(
            tmp_path,
            "x509", "-req", "-in", str(csr),
            "-CA", str(ca_cert), "-CAkey", str(ca_key), "-CAcreateserial",
            "-out", str(certificate), "-days", "30", "-sha256",
            "-extfile", str(extensions),
        )
        files[f"{role}_cert"] = certificate
        files[f"{role}_key"] = key
    return files


def _server_context(certificates: dict[str, Path]) -> ssl.SSLContext:
    """Mathematics: Build a TLS server context that requires a CA-verified client certificate."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(str(certificates["server_cert"]), str(certificates["server_key"]))
    context.load_verify_locations(cafile=str(certificates["ca"]))
    context.verify_mode = ssl.CERT_REQUIRED
    return context


def _client_context(certificates: dict[str, Path]) -> ssl.SSLContext:
    """Mathematics: Build a TLS client context with CA validation, hostname checking and a client certificate."""
    context = ssl.create_default_context(
        ssl.Purpose.SERVER_AUTH,
        cafile=str(certificates["ca"]),
    )
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(str(certificates["client_cert"]), str(certificates["client_key"]))
    return context


def _spec() -> OperatorSpec:
    """Mathematics: Declare one deterministic pure object-to-integer operator contract for the fabric tests."""
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


def _runtime(node_id: str = "node-b") -> VirtualLayerRuntime:
    """Mathematics: Build a local deterministic pure handler with a fixed resource profile."""
    registry = OperatorRegistry()
    registry.register(_spec(), lambda value, workload: value["left"] + value["right"])
    return VirtualLayerRuntime(registry, node_id, frozenset({"cpu"}))


def _locus(peer_id: str = "peer-b", host_id: str = "logical-host-b") -> ComputationalHostLocus:
    """Mathematics: Construct a receiver-local locus whose private process binding is omitted from advertisement."""
    return ComputationalHostLocus.from_runtime(
        host_id=host_id,
        runtime=_runtime(),
        authority_pid=17,
        operator_id="core.sum_pair",
        computational_ground_fingerprints=(GROUND_FP,),
        program_fingerprints=(PROGRAM_FP,),
        costs=_host_costs(3),
        implementation_fingerprint=IMPLEMENTATION_FP,
    )


def _host_costs(latency: int, energy: int = 20, bytes_: int = 128, risk: int = 0):
    """Mathematics: Return the host cost vector in the common fabric objective basis."""
    return (
        RouteMetric("latency", "ticks", latency),
        RouteMetric("energy", "units", energy),
        RouteMetric("bytes", "bytes", bytes_),
        RouteMetric("risk", "score", risk),
    )


def _link(source: str, target: str, latency: int, *, max_frame_bytes: int = 1_048_576):
    """Mathematics: Construct a directed peer adjacency in the shared metric basis."""
    return ComputationalNetworkLink(
        source,
        target,
        (
            RouteMetric("latency", "ticks", latency),
            RouteMetric("energy", "units", 1),
            RouteMetric("bytes", "bytes", 64),
            RouteMetric("risk", "score", 0),
        ),
        max_frame_bytes=max_frame_bytes,
    )


def _endpoint(peer_id: str, *, dns: str | None = None, host: str = "127.0.0.1", port: int = 443):
    """Mathematics: Construct one logical peer endpoint with a distinct TLS DNS identity."""
    return ComputationalPeerEndpoint(
        peer_id,
        dns or f"{peer_id}.fabric.test",
        host,
        port,
    )


def _snapshot(peer_id: str, *, hosts=(), links=(), revision: int = 1, lease: int = 60):
    """Mathematics: Build one peer-owned directory snapshot."""
    return ComputationalPeerSnapshot(
        _endpoint(peer_id),
        revision,
        lease,
        tuple(hosts),
        tuple(links),
    )


def _address() -> ComputationalAddress:
    """Mathematics: Bind a typed workload to the exact Ground, program, operator and route objective."""
    operating_system = HeadlessOS()
    identity = SystemIdentity(f"fabric-system-{id(operating_system)}", 1)
    seed = SystemSeed.from_system(operating_system)
    envelope = SystemSeedEnvelope(identity, "fabric-tests", "fabric-tests", seed)
    assert operating_system.seed_admission.admit(envelope).accepted
    workload = VirtualLayerWorkload(
        workload_id="fabric-route-workload",
        system=identity,
        ground=VirtualGroundRef.from_envelope(envelope),
        intention={"goal": {"kind": "sum"}},
        operators=(VirtualOperatorRef("core.sum_pair", 1, "cpu"),),
        input_value={"left": 4, "right": 5},
        budget=VirtualBudget(10_000, 10_000, 10_000),
        logical_time=7,
        eligible_nodes=("node-b",),
        max_hops=4,
    )
    return ComputationalAddress.from_workload(
        workload,
        "core.sum_pair",
        _spec(),
        GROUND_FP,
        program_fingerprint=PROGRAM_FP,
        metric_order=METRICS,
    )


def _directory(*snapshots: ComputationalPeerSnapshot, local_peer_id: str = "peer-a"):
    """Mathematics: Admit one local snapshot and direct authenticated test observations for all remote peer revisions."""
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
            directory.merge_authenticated_snapshot(
                snapshot,
                authenticated_peer_id=snapshot.peer_id,
                authenticated_server_name=snapshot.endpoint.tls_server_name,
            )
    return directory


def test_host_advertisement_is_portable_and_strips_receiver_authority() -> None:
    locus = _locus()
    advertisement = ComputationalHostAdvertisement.from_locus(locus, "peer-b")

    restored = ComputationalHostAdvertisement.from_dict(advertisement.to_dict())

    assert restored == advertisement
    assert restored.digest == advertisement.digest
    assert restored.peer_id == "peer-b"
    assert restored.host_id == "logical-host-b"
    assert "authority_pid" not in restored.to_dict()
    assert "runtime_binding" not in restored.to_dict()
    assert "handler_binding" not in restored.to_dict()


def test_peer_snapshot_round_trip_binds_only_peer_owned_hosts_and_outgoing_links() -> None:
    ad = ComputationalHostAdvertisement.from_locus(_locus(), "peer-b")
    snapshot = _snapshot("peer-b", hosts=(ad,), links=(_link("peer-b", "peer-a", 2),))

    restored = ComputationalPeerSnapshot.from_dict(snapshot.to_dict())

    assert restored == snapshot
    assert restored.digest == snapshot.digest
    with pytest.raises(ComputationalFabricError, match="another peer"):
        ComputationalPeerSnapshot(
            _endpoint("peer-c"),
            1,
            60,
            (ad,),
            (),
        )
    with pytest.raises(ComputationalFabricError, match="outgoing"):
        ComputationalPeerSnapshot(
            _endpoint("peer-b"),
            1,
            60,
            (),
            (_link("peer-c", "peer-b", 2),),
        )


def test_peer_authority_snapshot_restores_revisioned_advertisements() -> None:
    endpoint = _endpoint("peer-b")
    authority = ComputationalFabricAuthority(endpoint, lease_seconds=45)
    advertisement = ComputationalHostAdvertisement.from_locus(_locus(), "peer-b")
    authority.register_host(advertisement)
    authority.register_link(_link("peer-b", "peer-c", 7))
    original = authority.snapshot()

    restored = ComputationalFabricAuthority.from_snapshot(
        ComputationalPeerSnapshot.from_dict(original.to_dict())
    )

    assert restored.snapshot() == original
    assert restored.snapshot().digest == original.digest
    assert restored.revision == original.revision
    assert restored.register_host(advertisement) == advertisement.digest
    assert restored.revision == original.revision


def test_directory_requires_direct_peer_identity_and_monotonic_revisions() -> None:
    first = _snapshot("peer-b")
    directory = ComputationalFabricDirectory(
        "peer-a",
        {"peer-b": "peer-b.fabric.test"},
    )
    with pytest.raises(ComputationalFabricError, match="not an explicitly trusted"):
        directory.merge_authenticated_snapshot(
            first,
            authenticated_peer_id="peer-c",
            authenticated_server_name="peer-c.fabric.test",
        )
    with pytest.raises(ComputationalFabricError, match="DNS identity"):
        directory.merge_authenticated_snapshot(
            first,
            authenticated_peer_id="peer-b",
            authenticated_server_name="impostor.fabric.test",
        )

    assert directory.merge_authenticated_snapshot(
        first,
        authenticated_peer_id="peer-b",
        authenticated_server_name="peer-b.fabric.test",
    )
    assert not directory.merge_authenticated_snapshot(
        first,
        authenticated_peer_id="peer-b",
        authenticated_server_name="peer-b.fabric.test",
    )
    with pytest.raises(ComputationalFabricError, match="rollback"):
        directory.merge_authenticated_snapshot(
            _snapshot("peer-b", revision=0),
            authenticated_peer_id="peer-b",
            authenticated_server_name="peer-b.fabric.test",
        )
    with pytest.raises(ComputationalFabricError, match="equivocated"):
        directory.merge_authenticated_snapshot(
            _snapshot("peer-b", revision=1, lease=45),
            authenticated_peer_id="peer-b",
            authenticated_server_name="peer-b.fabric.test",
        )


def test_directory_leases_expire_on_receiver_monotonic_time() -> None:
    clock = [100.0]
    snapshot = _snapshot("peer-b", lease=5)
    directory = ComputationalFabricDirectory(
        "peer-a",
        {"peer-b": "peer-b.fabric.test"},
        monotonic=lambda: clock[0],
    )
    directory.merge_authenticated_snapshot(
        snapshot,
        authenticated_peer_id="peer-b",
        authenticated_server_name="peer-b.fabric.test",
    )
    assert tuple(item.peer_id for item in directory.active_snapshots) == ("peer-b",)

    clock[0] = 104.999
    assert directory.expired_peer_ids == ()
    clock[0] = 105.0
    assert directory.expired_peer_ids == ("peer-b",)
    assert directory.active_snapshots == ()
    assert directory.purge_expired() == ("peer-b",)
    assert directory.peer_snapshots == ()


def test_fabric_resolver_selects_lowest_cost_multi_hop_peer_path() -> None:
    ad = ComputationalHostAdvertisement.from_locus(_locus(), "peer-b")
    peer_a = _snapshot(
        "peer-a",
        links=(
            _link("peer-a", "peer-b", 6),
            _link("peer-a", "peer-c", 1),
        ),
    )
    peer_b = _snapshot("peer-b", hosts=(ad,))
    peer_c = _snapshot(
        "peer-c",
        links=(_link("peer-c", "peer-b", 1),),
    )
    directory = _directory(peer_a, peer_b, peer_c)

    result = ComputationalFabricResolver().resolve(
        _address(),
        directory,
        origin_peer_id="peer-a",
        max_hops=4,
    )

    assert result.status is ComputationalFabricStatus.FOUND
    assert result.authoritative is False
    assert result.witness is not None
    assert result.witness.authoritative is False
    assert result.witness.peer_path == ("peer-a", "peer-c", "peer-b")
    assert len(result.witness.link_ids) == 2
    assert result.witness.target_host.host_id == "logical-host-b"
    assert tuple(item.amount for item in result.witness.network_costs if item.name == "latency") == (2,)
    assert tuple(item.amount for item in result.witness.host_costs if item.name == "latency") == (3,)
    assert tuple(item.amount for item in result.witness.total_costs if item.name == "latency") == (5,)
    assert tuple(item.peer_id for item in result.witness.peer_endpoints) == result.witness.peer_path
    assert result.witness.to_dict()["authoritative"] is False
    restored_witness = type(result.witness).from_dict(result.witness.to_dict())
    restored_result = type(result).from_dict(result.to_dict())
    assert restored_witness == result.witness
    assert restored_witness.digest == result.witness.digest
    assert restored_result.digest == result.digest


def test_fabric_route_uses_stable_path_tie_break_and_never_invents_reverse_edges() -> None:
    ad = ComputationalHostAdvertisement.from_locus(_locus(), "peer-d")
    snapshots = (
        _snapshot("peer-a", links=(_link("peer-a", "peer-c", 1), _link("peer-a", "peer-b", 1))),
        _snapshot("peer-b", links=(_link("peer-b", "peer-d", 1),)),
        _snapshot("peer-c", links=(_link("peer-c", "peer-d", 1),)),
        _snapshot("peer-d", hosts=(ad,)),
    )
    directory = _directory(*snapshots)

    result = ComputationalFabricResolver().resolve(
        _address(),
        directory,
        origin_peer_id="peer-a",
    )

    assert result.status is ComputationalFabricStatus.FOUND
    assert result.witness is not None
    assert result.witness.peer_path == ("peer-a", "peer-b", "peer-d")

    reverse_only = _directory(
        _snapshot("peer-a"),
        _snapshot("peer-d", hosts=(ad,), links=(_link("peer-d", "peer-a", 1),)),
    )
    unreachable = ComputationalFabricResolver().resolve(
        _address(),
        reverse_only,
        origin_peer_id="peer-a",
    )
    assert unreachable.status is ComputationalFabricStatus.UNREACHABLE
    assert unreachable.witness is None


def test_fabric_resolver_enforces_hop_frame_budget_and_implementation_pins() -> None:
    ad = ComputationalHostAdvertisement.from_locus(_locus(), "peer-c")
    snapshots = (
        _snapshot("peer-a", links=(_link("peer-a", "peer-b", 1),)),
        _snapshot("peer-b", links=(_link("peer-b", "peer-c", 1),)),
        _snapshot("peer-c", hosts=(ad,)),
    )
    directory = _directory(*snapshots)
    resolver = ComputationalFabricResolver()

    hop_limited = resolver.resolve(
        _address(),
        directory,
        origin_peer_id="peer-a",
        max_hops=1,
    )
    assert hop_limited.status is ComputationalFabricStatus.BUDGET_EXHAUSTED
    assert any(item.code.value == "hop_limit" for item in hop_limited.blockers)

    ad_unpinned = ComputationalHostAdvertisement(
        ad.host_id, ad.node_id, ad.peer_id, ad.operator_spec, ad.substrates,
        ad.computational_ground_fingerprints, ad.program_fingerprints,
        ad.supports_ground_program_compilation, ad.supports_structural_memory,
        None, ad.costs, ad.virtual_capacity, ad.max_energy, ad.max_bytes,
        ad.max_virtual_ticks,
    )
    unpinned_directory = _directory(
        snapshots[0],
        snapshots[1],
        _snapshot("peer-c", hosts=(ad_unpinned,)),
    )
    unpinned = resolver.resolve(
        _address(),
        unpinned_directory,
        origin_peer_id="peer-a",
    )
    assert unpinned.status is ComputationalFabricStatus.BLOCKED
    assert any(item.code.value == "implementation_missing" for item in unpinned.blockers)

    tiny_link_directory = _directory(
        _snapshot("peer-a", links=(_link("peer-a", "peer-b", 1, max_frame_bytes=8),)),
        snapshots[1],
        snapshots[2],
    )
    tiny = resolver.resolve(
        _address(),
        tiny_link_directory,
        origin_peer_id="peer-a",
    )
    assert tiny.status is ComputationalFabricStatus.UNREACHABLE
    assert any(item.code.value == "resource_limit" for item in tiny.blockers)


def test_fabric_resolver_fails_closed_on_incompatible_computational_ground() -> None:
    good = ComputationalHostAdvertisement.from_locus(_locus(), "peer-b")
    wrong_ground = ComputationalHostAdvertisement(
        good.host_id, good.node_id, good.peer_id, good.operator_spec, good.substrates,
        ("d" * 64,), good.program_fingerprints, good.supports_ground_program_compilation,
        good.supports_structural_memory, good.implementation_fingerprint, good.costs,
        good.virtual_capacity, good.max_energy, good.max_bytes, good.max_virtual_ticks,
    )
    directory = _directory(
        _snapshot("peer-a", links=(_link("peer-a", "peer-b", 1),)),
        _snapshot("peer-b", hosts=(wrong_ground,)),
    )
    blocked = ComputationalFabricResolver().resolve(
        _address(), directory, origin_peer_id="peer-a"
    )
    assert blocked.status is ComputationalFabricStatus.BLOCKED
    assert any(item.code.value == "ground_mismatch" for item in blocked.blockers)


def test_fabric_resolver_applies_aggregate_network_cost_ceilings() -> None:
    advertisement = ComputationalHostAdvertisement.from_locus(_locus(), "peer-b")
    directory = _directory(
        _snapshot("peer-a", links=(_link("peer-a", "peer-b", 4),)),
        _snapshot("peer-b", hosts=(advertisement,)),
    )
    address = replace(
        _address(),
        resource_ceilings=(RouteMetric("latency", "ticks", 3),),
    )

    result = ComputationalFabricResolver().resolve(
        address,
        directory,
        origin_peer_id="peer-a",
    )

    assert result.status is ComputationalFabricStatus.BUDGET_EXHAUSTED
    assert result.witness is None
    assert any(item.code.value == "resource_limit" for item in result.blockers)


def test_fabric_resolver_preserves_shorter_paths_when_the_cheapest_prefix_exceeds_hop_budget() -> None:
    advertisement = ComputationalHostAdvertisement.from_locus(_locus(), "peer-d")
    directory = _directory(
        _snapshot(
            "peer-a",
            links=(
                _link("peer-a", "peer-b", 1),
                _link("peer-a", "peer-c", 5),
            ),
        ),
        _snapshot("peer-b", links=(_link("peer-b", "peer-c", 1),)),
        _snapshot("peer-c", links=(_link("peer-c", "peer-d", 1),)),
        _snapshot("peer-d", hosts=(advertisement,)),
    )

    result = ComputationalFabricResolver().resolve(
        _address(),
        directory,
        origin_peer_id="peer-a",
        max_hops=2,
    )

    assert result.status is ComputationalFabricStatus.FOUND
    assert result.witness is not None
    assert result.witness.peer_path == ("peer-a", "peer-c", "peer-d")
    assert tuple(
        item.amount for item in result.witness.network_costs if item.name == "latency"
    ) == (6,)


def test_fabric_resolver_rejects_program_and_operator_contract_mismatches() -> None:
    advertisement = ComputationalHostAdvertisement.from_locus(_locus(), "peer-b")
    program_mismatch = replace(advertisement, program_fingerprints=("d" * 64,))
    contract_mismatch = replace(
        advertisement,
        operator_spec=replace(
            advertisement.operator_spec,
            description="A different operator contract with the same operator name",
        ),
    )
    for candidate, code in (
        (program_mismatch, "program_mismatch"),
        (contract_mismatch, "contract_mismatch"),
    ):
        directory = _directory(
            _snapshot("peer-a", links=(_link("peer-a", "peer-b", 1),)),
            _snapshot("peer-b", hosts=(candidate,)),
        )
        result = ComputationalFabricResolver().resolve(
            _address(),
            directory,
            origin_peer_id="peer-a",
        )
        assert result.status is ComputationalFabricStatus.BLOCKED
        assert result.witness is None
        assert any(item.code.value == code for item in result.blockers)


@pytest.mark.skipif(shutil.which("openssl") is None, reason="OpenSSL CLI is required for ephemeral mutual-TLS certificates")
def test_mutual_tls_peer_client_discovers_and_merges_remote_host_snapshot(tmp_path) -> None:
    certificates = _make_test_certificates(tmp_path)
    server_context = _server_context(certificates)
    client_context = _client_context(certificates)
    listener = SocketTransport.listen("127.0.0.1", 0)
    endpoint = ComputationalPeerEndpoint(
        "peer-b",
        "peer-b.fabric.test",
        "127.0.0.1",
        listener.getsockname()[1],
    )
    authority = ComputationalFabricAuthority(endpoint, lease_seconds=30)
    authority.register_host(ComputationalHostAdvertisement.from_locus(_locus(), "peer-b"))

    server_result: dict[str, object] = {}
    server_errors: list[BaseException] = []
    stop = threading.Event()

    def serve() -> None:
        """Mathematics: Accept the one expected peer certificate and service its reliable directory request loop."""
        try:
            transport = accept_mutual_tls(
                listener,
                "peer-b",
                "peer-a",
                server_context,
                expected_peer_dns="peer-a.fabric.test",
            )
            server = ComputationalFabricPeerServer(
                authority,
                transport,
                "peer-a",
                expected_client_dns="peer-a.fabric.test",
            )
            server_result["server"] = server
            server.serve_forever(stop)
        except BaseException as exc:
            server_errors.append(exc)

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    client: ComputationalFabricPeerClient | None = None
    try:
        directory = ComputationalFabricDirectory(
            "peer-a",
            {"peer-b": "peer-b.fabric.test"},
        )
        directory.register_local_snapshot(
            _snapshot("peer-a", links=(_link("peer-a", "peer-b", 2),))
        )
        client = ComputationalFabricPeerClient.connect_mutual_tls(
            "peer-a",
            endpoint,
            client_context,
            timeout=3.0,
        )
        assert client.refresh(directory)
        assert tuple(item.peer_id for item in directory.active_snapshots) == ("peer-b",)
        assert directory.hosts[0].host_id == "logical-host-b"
        assert directory.hosts[0].implementation_fingerprint == IMPLEMENTATION_FP
        routed = ComputationalFabricResolver().resolve(
            _address(),
            directory,
            origin_peer_id="peer-a",
        )
        assert routed.status is ComputationalFabricStatus.FOUND
        assert routed.witness is not None
        assert routed.witness.peer_path == ("peer-a", "peer-b")
        assert routed.witness.target_host.host_id == "logical-host-b"
        assert server_result.get("server") is not None
        assert not server_errors
    finally:
        if client is not None:
            client.close()
        stop.set()
        listener.close()
        thread.join(timeout=3.0)
    assert not thread.is_alive()
    assert not server_errors, repr(server_errors)
