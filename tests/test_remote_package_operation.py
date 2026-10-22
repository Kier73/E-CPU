from __future__ import annotations

from mailcpu import (
    ExecutableImage,
    HeadlessOS,
    HypervisorArbitrationEvent,
    HypervisorDomain,
    HypervisorOperationRecoveryCoordinator,
    HypervisorPolicy,
    HypervisorRequest,
    ImageRegistry,
    Instruction,
    Op,
    Program,
    ReliabilityPolicy,
    ReliableChannel,
    SocketTransport,
)
from mailcpu.image import ImageFile


def _tcp_pair() -> tuple[SocketTransport, SocketTransport]:
    """Mathematics: create reciprocal AF_INET transports `T_origin↔T_replica` for one package operation stream."""

    listener = SocketTransport.listen("127.0.0.1", 0)
    port = listener.getsockname()[1]
    origin = SocketTransport.connect("127.0.0.1", port, "origin", "replica")
    replica = SocketTransport.accept(listener, "replica", "origin")
    listener.close()
    return origin, replica


def _package_event(digest: str) -> HypervisorArbitrationEvent:
    """Mathematics: construct `Q_package=(install,/package/h,{digest:h},write,destructive)` with a remote authority claim."""

    return HypervisorArbitrationEvent(
        "origin",
        "packages",
        1,
        200,
        HypervisorRequest(
            "install package registry image digest deployment",
            f"/package/{digest}",
            {"digest": digest},
            frozenset({"write"}),
            frozenset({"write"}),
            destructive=True,
        ),
    )


def test_remote_package_operation_installs_receiver_local_verified_image(tmp_path) -> None:
    """Mathematics: `ALLOW_PACKAGE∧write⇒F_after=install(fetch_verified(h),F_before)` and effect `e={digest:h}`."""

    registry = ImageRegistry(tmp_path / "replica-registry")
    image = ExecutableImage(
        "remote-package",
        Program((Instruction(Op.HALT, ()),)),
        files=(ImageFile("/opt/remote/data", b"receiver-local-package"),),
    )
    digest = registry.publish(image).digest
    origin_transport, replica_transport = _tcp_pair()
    policy = ReliabilityPolicy(lease_ticks=1, max_attempts=3, window_size=4)
    origin = HeadlessOS()
    replica = HeadlessOS()
    replica.hypervisor.policy = HypervisorPolicy(
        review_confidence=0.0,
        automatic_confidence=0.0,
        destructive_confidence=0.0,
        danger_review_probability=1.0,
    )
    origin_coordinator = HypervisorOperationRecoveryCoordinator(
        origin_transport,
        ReliableChannel(origin_transport, "origin", "replica", "packages", policy),
        origin,
        direction="outbound",
    )
    replica_coordinator = HypervisorOperationRecoveryCoordinator(
        replica_transport,
        ReliableChannel(replica_transport, "replica", "replica", "packages", policy, peer="origin"),
        replica,
        direction="inbound",
    )

    def install_handler() -> ExecutableImage:
        """Mathematics: perform receiver-local verified transition `F↦F∪files(fetch(R[h]))`."""

        return registry.install(digest, replica_coordinator.operating_system.environment)

    def encode_digest(installed: ExecutableImage) -> dict[str, str]:
        """Mathematics: expose verified image identity as canonical effect `{"digest":SHA256(I)}`."""

        return {"digest": installed.digest()}

    try:
        assert origin_coordinator.send(_package_event(digest)) == 1
        result = replica_coordinator.receive_and_execute(
            replica_coordinator.operating_system.environment.init_pid,
            {HypervisorDomain.PACKAGE: install_handler},
            encode_digest,
        )
        assert result is not None
        assert result.action.value == "allow"
        assert result.domain is HypervisorDomain.PACKAGE
        assert result.executed is True
        assert result.effect == {"digest": digest}
        assert replica_coordinator.operating_system.environment.kernel.fs.read_file("/opt/remote/data") == b"receiver-local-package"
        assert replica_coordinator.operating_system.environment.kernel.journal.verify()
    finally:
        origin_transport.close()
        replica_transport.close()
