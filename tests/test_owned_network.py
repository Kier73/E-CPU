from __future__ import annotations

from pathlib import Path

import pytest

from mailcpu import HeadlessOS, NetworkAddress, NetworkError, OwnedNetworkError, OwnedNetworkFabric
from mailcpu.kernel import KernelError


def _fabric(queue_limit: int = 4) -> tuple[OwnedNetworkFabric, NetworkAddress, NetworkAddress]:
    """Mathematics: construct graph `G=(N,V,L)` with one direct edge `a↔b`."""

    fabric = OwnedNetworkFabric(queue_limit=queue_limit)
    fabric.create_namespace("alpha")
    fabric.create_namespace("beta")
    left = fabric.create_interface("alpha", "eth0", mtu=128)
    right = fabric.create_interface("beta", "eth0", mtu=128)
    fabric.connect("link0", left, right)
    return fabric, left, right


def test_owned_fabric_is_fifo_bounded_and_mtu_checked() -> None:
    """Mathematics: accepted frames preserve `Q := Q || f`, while invalid transitions preserve `Q` exactly."""

    fabric, left, right = _fabric(queue_limit=2)
    assert fabric.send(left, right, b"one", 1) == 1
    assert fabric.send(left, right, b"two", 2) == 2
    assert fabric.peek(right).payload == b"one"  # type: ignore[union-attr]
    assert fabric.receive(right).payload == b"one"  # type: ignore[union-attr]
    assert fabric.receive(right).payload == b"two"  # type: ignore[union-attr]
    assert fabric.receive(right) is None
    with pytest.raises(OwnedNetworkError, match="MTU"):
        fabric.send(left, right, b"x" * 129, 3)
    assert fabric.interfaces()[0]["queue_length"] == 0

    fabric.send(left, right, b"full", 4)
    fabric.send(left, right, b"full2", 5)
    with pytest.raises(OwnedNetworkError, match="queue is full"):
        fabric.send(left, right, b"overflow", 6)
    assert fabric.interfaces()[1]["queue_length"] == 2


def test_owned_fabric_checkpoint_restores_graph_and_queued_bytes() -> None:
    """Mathematics: `restore(snapshot(G,Q,k))` preserves topology, FIFO head, bytes, and frame identity."""

    fabric, left, right = _fabric()
    fabric.send(left, right, b"checkpointed bytes", 17)
    snapshot = fabric.snapshot()
    restored = OwnedNetworkFabric.from_snapshot(snapshot)
    assert restored.namespaces() == fabric.namespaces()
    assert restored.interfaces() == fabric.interfaces()
    assert restored.links() == fabric.links()
    frame = restored.receive(right)
    assert frame is not None
    assert frame.frame_id == 1
    assert frame.payload == b"checkpointed bytes"
    assert restored.journal.verify()


def test_owned_fabric_routes_across_namespace_forwarding_interfaces() -> None:
    """Mathematics: route `a0→b0→b1→c0` is the deterministic shortest path through link and namespace edges."""

    fabric = OwnedNetworkFabric()
    for namespace in ("alpha", "bridge", "omega"):
        fabric.create_namespace(namespace)
    alpha = fabric.create_interface("alpha", "eth0", mtu=256)
    bridge_left = fabric.create_interface("bridge", "eth0", mtu=128)
    bridge_right = fabric.create_interface("bridge", "eth1", mtu=128)
    omega = fabric.create_interface("omega", "eth0", mtu=256)
    fabric.connect("alpha-bridge", alpha, bridge_left)
    fabric.connect("bridge-omega", bridge_right, omega)
    with pytest.raises(OwnedNetworkError, match="directly linked"):
        fabric.send(alpha, omega, b"direct-only", 1)
    assert fabric.find_route(alpha, omega) == (alpha, bridge_left, bridge_right, omega)
    assert fabric.send_routed(alpha, omega, b"multi-hop", 2) == 1
    frame = fabric.receive(omega)
    assert frame is not None
    assert frame.payload == b"multi-hop"
    assert frame.route == (alpha, bridge_left, bridge_right, omega)
    with pytest.raises(OwnedNetworkError, match="route MTU"):
        fabric.send_routed(alpha, omega, b"x" * 129, 3)


def test_headless_route_send_uses_owned_forwarding_and_preserves_evidence() -> None:
    """Mathematics: `net_route_send` exposes `δ_route` and records the chosen path in the received frame."""

    os = HeadlessOS()
    pid = os.environment.init_pid
    for namespace in ("bridge", "omega"):
        os.syscall(pid, "net_namespace_create", name=namespace)
    os.syscall(pid, "net_interface_create", namespace="root", interface="eth0")
    os.syscall(pid, "net_interface_create", namespace="bridge", interface="eth0")
    os.syscall(pid, "net_interface_create", namespace="bridge", interface="eth1")
    os.syscall(pid, "net_interface_create", namespace="omega", interface="eth0")
    os.syscall(
        pid,
        "net_connect",
        link="root-bridge",
        left_namespace="root",
        left_interface="eth0",
        right_namespace="bridge",
        right_interface="eth0",
    )
    os.syscall(
        pid,
        "net_connect",
        link="bridge-omega",
        left_namespace="bridge",
        left_interface="eth1",
        right_namespace="omega",
        right_interface="eth0",
    )
    assert os.syscall(
        pid,
        "net_route_send",
        source_namespace="root",
        source_interface="eth0",
        destination_namespace="omega",
        destination_interface="eth0",
        payload=b"routed-mail",
        logical_time=11,
    ) == 1
    frame = os.environment.network_receive(pid, NetworkAddress("omega", "eth0"))
    assert frame is not None
    assert tuple(address.interface for address in frame.route) == ("eth0", "eth0", "eth1", "eth0")
    assert any(record.kind == "network.route.forward" for record in os.environment.kernel.journal.records())


def test_headless_os_exposes_owned_network_syscalls_and_checkpoint(tmp_path: Path) -> None:
    """Mathematics: OS transition `δ_net` preserves bytes across send/receive and checkpoint continuation."""

    os = HeadlessOS()
    pid = os.environment.init_pid
    os.syscall(pid, "net_namespace_create", name="guest")
    os.syscall(pid, "net_interface_create", namespace="root", interface="eth0", mtu=256)
    os.syscall(pid, "net_interface_create", namespace="guest", interface="eth0", mtu=256)
    os.syscall(
        pid,
        "net_connect",
        link="guest-link",
        left_namespace="root",
        left_interface="eth0",
        right_namespace="guest",
        right_interface="eth0",
    )
    assert os.syscall(
        pid,
        "net_send",
        source_namespace="root",
        source_interface="eth0",
        destination_namespace="guest",
        destination_interface="eth0",
        payload=b"mailcpu fabric",
        logical_time=9,
    ) == 1
    checkpoint = tmp_path / "owned-network.mcpu.json"
    os.save_checkpoint(checkpoint)
    restored = HeadlessOS.restore_checkpoint(checkpoint)
    frame = restored.syscall(
        restored.environment.init_pid,
        "net_receive",
        destination_namespace="guest",
        destination_interface="eth0",
    )
    assert frame is not None
    assert frame.payload == b"mailcpu fabric"
    assert restored.environment.kernel.journal.verify()


def test_scheduled_program_moves_bytes_through_owned_link() -> None:
    """Mathematics: `net_send_from` and `net_receive_into` implement `Q_d := Q_d || memory[a:a+n]` and its inverse."""

    os = HeadlessOS()
    pid = os.environment.init_pid
    os.syscall(pid, "net_namespace_create", name="guest")
    os.syscall(pid, "net_interface_create", namespace="root", interface="eth0")
    os.syscall(pid, "net_interface_create", namespace="guest", interface="eth0")
    os.syscall(
        pid,
        "net_connect",
        link="guest-link",
        left_namespace="root",
        left_interface="eth0",
        right_namespace="guest",
        right_interface="eth0",
    )
    sender = os.run_source(
        "\n".join(
            (
                "SYSCALL r0 mmap length=4 writable=true",
                "SYSCALL r1 mem_write address=$r0 data=hex:6d61696c",
                "SYSCALL r2 net_send_from source_namespace=root source_interface=eth0 destination_namespace=guest destination_interface=eth0 address=$r0 size=4 logical_time=12",
                "SYSCALL r3 exit code=0",
            )
        ),
        name="network-sender",
    )
    assert sender.exit_code == 0
    receiver = os.launch_source(
        "\n".join(
            (
                "SYSCALL r0 mmap length=4 writable=true",
                "SYSCALL r1 net_receive_into destination_namespace=guest destination_interface=eth0 address=$r0 size=4",
                "SYSCALL r2 exit code=0",
            )
        ),
        name="network-receiver",
    )
    os.run()
    address = os.process(receiver).registers["r0"]
    assert os.vm.memories[receiver].read(address, 4) == b"mail"


def test_network_handle_is_released_once_on_reap_of_its_accepting_process() -> None:
    """Mathematics: `reap` applies `Owner^{-1}(pid) := ∅` once, so the accepting process's native handles vanish with it while another owner's handle survives and a second reap is impossible."""

    os = HeadlessOS()
    init = os.environment.init_pid
    os.syscall(init, "net_namespace_create", name="guest")
    os.syscall(init, "net_interface_create", namespace="root", interface="eth0")
    os.syscall(init, "net_interface_create", namespace="guest", interface="eth0")
    os.syscall(
        init,
        "net_connect",
        link="guest-link",
        left_namespace="root",
        left_interface="eth0",
        right_namespace="guest",
        right_interface="eth0",
    )
    listener_fd = os.syscall(init, "net_stream_listen_fd", namespace="guest", interface="eth0", port=8900)
    listener_handle = os.environment.kernel.processes[init].fds[listener_fd].network_handle
    report = os.run_source(
        "\n".join(
            (
                "SYSCALL l0 net_stream_listen_fd namespace=guest interface=eth0 port=8901",
                "SYSCALL r0 net_stream_connect_fd source_namespace=root source_interface=eth0 source_port=9900 destination_namespace=guest destination_interface=eth0 destination_port=8901",
                "SYSCALL r1 net_stream_accept_fd fd=$l0",
                "SYSCALL r2 exit code=0",
            )
        ),
        name="accepting-process",
        parent_pid=init,
    )
    assert report.registers["r1"] >= 3
    owned_handles = tuple(item["handle"] for item in os.environment.streams.connections())
    assert len(owned_handles) == 2
    assert all(os.environment.streams.has_connection(handle) for handle in owned_handles)

    os.reap_process(report.pid)
    assert not any(os.environment.streams.has_connection(handle) for handle in owned_handles)
    assert os.environment.streams.listener_binding(int(listener_handle))[1] == 8900
    with pytest.raises(KernelError):
        os.reap_process(report.pid)
    assert not any(os.environment.streams.has_connection(handle) for handle in owned_handles)


def test_owned_link_driver_commits_only_after_e0_accepts() -> None:
    """Mathematics: driver transition is `peek→D.ingest→dequeue`; `D` failure leaves queue head unchanged."""

    def packet(payload: bytes) -> bytes:
        """Mathematics: construct a fixed IPv4/TCP frame with `total_length=40+|payload|`."""

        total_length = 40 + len(payload)
        frame = bytearray(total_length)
        frame[0] = 0x45
        frame[2:4] = total_length.to_bytes(2, "big")
        frame[9] = 6
        frame[12:16] = bytes((10, 0, 0, 1))
        frame[16:20] = bytes((10, 0, 0, 2))
        frame[20:22] = (4000).to_bytes(2, "big")
        frame[22:24] = (80).to_bytes(2, "big")
        frame[32] = 0x50
        frame[33] = 0x02
        frame[34:36] = (4096).to_bytes(2, "big")
        frame[40:] = payload
        return bytes(frame)

    os = HeadlessOS()
    pid = os.environment.init_pid
    os.syscall(pid, "net_namespace_create", name="guest")
    os.syscall(pid, "net_interface_create", namespace="root", interface="eth0")
    os.syscall(pid, "net_interface_create", namespace="guest", interface="eth0")
    os.syscall(
        pid,
        "net_connect",
        link="guest-link",
        left_namespace="root",
        left_interface="eth0",
        right_namespace="guest",
        right_interface="eth0",
    )
    source = NetworkAddress("root", "eth0")
    destination = NetworkAddress("guest", "eth0")
    os.environment.network_send(pid, source, destination, packet(b""), 1)
    accepted = os.drain_owned_network_to_e0(pid, "guest", "eth0")
    assert accepted and accepted[0][0].kind == "connection.state"
    malformed = b"not-an-ipv4-frame"
    os.environment.network_send(pid, source, destination, malformed, 2)
    with pytest.raises(NetworkError):
        os.drain_owned_network_to_e0(pid, "guest", "eth0")
    queued = os.environment.owned_network.peek(destination)
    assert queued is not None and queued.payload == malformed
