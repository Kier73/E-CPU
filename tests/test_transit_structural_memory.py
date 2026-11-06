"""Transit integration tests for receiver-side structural-memory reads."""

from __future__ import annotations

import time

import pytest

from mailcpu import (
    Capability,
    HeadlessOS,
    HypervisorArbitrationEvent,
    HypervisorDomain,
    HypervisorOperationChannel,
    HypervisorOperationResultChannel,
    HypervisorPolicy,
    HypervisorRequest,
    ReliabilityPolicy,
    ReliableChannel,
    SocketTransport,
    TransitBackendRouter,
    TransitComputeSession,
    TransitComputeWorker,
    TransitStructuralMemoryError,
    TransitStructuralMemoryHost,
    TransitTranslationEvidence,
    TransitOracleEvidence,
    TRANSIT_STRUCTURAL_MEMORY_OPERATION,
    TRANSIT_STRUCTURAL_MEMORY_RESOURCE,
)
from mailcpu.law_certifier import Law
from mailcpu.semantic_translation import canonical_value_digest


def _tcp_pair(local: str, peer: str) -> tuple[SocketTransport, SocketTransport]:
    """Mathematics: create reciprocal AF_INET transports T_local and T_peer over one loopback TCP connection."""

    listener = SocketTransport.listen("127.0.0.1", 0)
    port = listener.getsockname()[1]
    local_transport = SocketTransport.connect("127.0.0.1", port, local, peer)
    peer_transport = SocketTransport.accept(listener, peer, local)
    listener.close()
    return local_transport, peer_transport


def _prepare_receiver():
    """Mathematics: construct receiver state S with one admitted memory revision and a read-only transit authority."""

    operating_system = HeadlessOS(
        structural_memory_admission_policy=lambda proposal: proposal.spec.domain == "integer-orbit"
    )
    law = Law(
        family="int",
        params={"x0": 7, "step": 5, "mod": 97},
        order=1,
        verdict="GROUND",
    )
    proposal = operating_system.structural_memory.propose(
        "orbit-alpha",
        law,
        {0: 7, 1: 12, 2: 17, 3: 22},
        domain="integer-orbit",
        context={"tenant": "alpha", "partition": 4},
    )
    version = operating_system.structural_memory.admit(
        proposal.proposal_id,
        expected_revision=0,
    )
    authority_pid = operating_system.environment.kernel.spawn(
        "structural-memory-transit-authority",
        capabilities=(
            Capability(TRANSIT_STRUCTURAL_MEMORY_RESOURCE, frozenset({"read"})),
        ),
        parent_pid=operating_system.environment.init_pid,
    )
    operating_system.hypervisor.policy = HypervisorPolicy(
        review_confidence=0.0,
        automatic_confidence=0.0,
        destructive_confidence=0.0,
        danger_review_probability=1.0,
        embedding_review_confidence=1.0,
    )
    return operating_system, authority_pid, version


def _event(
    *,
    sequence: int = 1,
    memory_id: str = "orbit-alpha",
    revision: int = 1,
    context: dict[str, object] | None = None,
    coordinate: int = 100,
    granted: frozenset[str] = frozenset(),
) -> HypervisorArbitrationEvent:
    """Mathematics: construct semantic request q=(memory_id,revision,context,coordinate) under operation identity (client,structural.read,sequence)."""

    return HypervisorArbitrationEvent(
        "client",
        "structural.read",
        sequence,
        900 + sequence,
        HypervisorRequest(
            TRANSIT_STRUCTURAL_MEMORY_OPERATION,
            TRANSIT_STRUCTURAL_MEMORY_RESOURCE,
            {
                "memory_id": memory_id,
                "revision": revision,
                "context": {"tenant": "alpha", "partition": 4} if context is None else context,
                "coordinate": coordinate,
            },
            frozenset({"read"}),
            granted,
        ),
    )


def _build_router(operating_system, authority_pid, host_type=TransitStructuralMemoryHost):
    """Mathematics: build receiver handler relation R with scalar CPU and exact structural-read operation/resource keys."""

    router = TransitBackendRouter()
    router.register_backend(host_type(operating_system, authority_pid))
    return router


def _wait_for_response(channel: HypervisorOperationResultChannel):
    """Mathematics: poll until one typed response is available or a finite three-second test deadline expires."""

    deadline = time.monotonic() + 3.0
    result = None
    while result is None and time.monotonic() < deadline:
        result = channel.receive()
        if result is None:
            time.sleep(0.005)
    assert result is not None, "transit structural-memory response did not arrive"
    return result


def _wait_for_ack(channel: ReliableChannel, expected: tuple[int, ...]) -> None:
    """Mathematics: require the reliable channel ACK projection A(t) to equal the expected sequence tuple before deadline."""

    deadline = time.monotonic() + 3.0
    actual: tuple[int, ...] = ()
    while actual != expected and time.monotonic() < deadline:
        actual = channel.process_ack()
        if actual != expected:
            time.sleep(0.005)
    assert actual == expected


def test_structural_memory_coordinate_read_runs_inside_receiver_transit_path() -> None:
    """Mathematics: execute q=(m,r,c,t) at the receiver and return the exact structural receipt before acknowledging request delivery."""

    request_client_transport, request_worker_transport = _tcp_pair("client", "worker")
    response_worker_transport, response_client_transport = _tcp_pair("worker", "client")
    policy = ReliabilityPolicy(lease_ticks=1, max_attempts=3, window_size=4)
    request_client = HypervisorOperationChannel(
        ReliableChannel(request_client_transport, "client", "worker", "structural.read", policy)
    )
    request_worker = HypervisorOperationChannel(
        ReliableChannel(request_worker_transport, "worker", "worker", "structural.read", policy, peer="client")
    )
    response_worker = HypervisorOperationResultChannel(
        ReliableChannel(response_worker_transport, "worker", "client", "structural.result", policy),
        "client",
        "structural.read",
    )
    response_client = HypervisorOperationResultChannel(
        ReliableChannel(response_client_transport, "client", "client", "structural.result", policy, peer="worker"),
        "client",
        "structural.read",
    )
    receiver, authority_pid, version = _prepare_receiver()
    calls = {"count": 0}

    class CountingStructuralHost(TransitStructuralMemoryHost):
        """Expose first-time host invocation count for semantic replay assertions."""

        def handle(self, event: HypervisorArbitrationEvent) -> dict[str, object]:
            """Mathematics: increment c only when the arbitration loop actually enters the structural-read handler."""
            calls["count"] += 1
            return super().handle(event)

    router = _build_router(receiver, authority_pid, CountingStructuralHost)
    worker = TransitComputeWorker(receiver, authority_pid, router)
    session = TransitComputeSession(worker, request_worker, response_worker)
    event = _event()
    try:
        assert set(router.registered_backends()) == {
            ("execute deterministic CPU arithmetic program", "/cpu/compute"),
            (TRANSIT_STRUCTURAL_MEMORY_OPERATION, TRANSIT_STRUCTURAL_MEMORY_RESOURCE),
        }
        assert session.phase == "idle"
        assert request_client.send(event) == 1

        deadline = time.monotonic() + 3.0
        served = None
        while served is None and time.monotonic() < deadline:
            served = session.serve_once()
            if served is None:
                time.sleep(0.005)
        assert served is not None
        assert served.action.value == "allow"
        assert served.domain is HypervisorDomain.FILESYSTEM
        assert served.executed is True
        assert served.replayed is False
        assert served.effect["memory_id"] == "orbit-alpha"
        assert served.effect["revision"] == version.spec.revision
        assert served.effect["coordinate"] == 100
        assert served.effect["value"] == (7 + 5 * 100) % 97
        assert served.effect["spec_digest"] == version.spec.digest
        assert served.effect["certificate_digest"] == version.certificate.digest
        assert served.effect["context_digest"] == version.spec.context_digest
        assert served.effect["witness_digest"] == version.certificate.witness_digest
        assert len(served.effect["receipt_id"]) == 64
        evidence = TransitTranslationEvidence.from_dict(served.effect["_semantic_translation"])
        oracle = TransitOracleEvidence.from_dict(served.effect["_semantic_oracle"])
        assert oracle.oracle.type_id == "mailcpu.transit.semantic-oracle.structural-memory-coordinate"
        assert oracle.equivalent is True
        assert oracle.work_units <= oracle.work_limit
        assert evidence.identity == event.identity
        assert evidence.request_fingerprint == served.fingerprint
        assert evidence.decision_receipt == served.decision_receipt
        assert evidence.backend_manifest == tuple(sorted(router.registered_backends()))
        assert evidence.contract.source.type_id == "mailcpu.transit.authorized-event"
        assert evidence.contract.target.type_id == "mailcpu.transit.handler-effect"
        assert evidence.contract.mapping.type_id == "mailcpu.transit.backend-dispatch"
        assert evidence.contract.authority_requirements[0].resource == TRANSIT_STRUCTURAL_MEMORY_RESOURCE
        assert evidence.contract.authority_requirements[0].rights == ("read",)
        assert evidence.comparison.equivalent is True
        raw_effect = {
            key: value for key, value in served.effect.items()
            if key not in {"_semantic_translation", "_semantic_oracle"}
        }
        assert canonical_value_digest(raw_effect) == evidence.effect_digest
        assert evidence.contract.target.content_digest == evidence.effect_digest
        assert evidence.digest == TransitTranslationEvidence.from_dict(evidence.to_dict()).digest
        evidence.validate_execution_result(served, require_oracle=True)
        forged_payload = evidence.to_dict()
        forged_payload["decision_receipt"] = "0" * 64
        forged_evidence = TransitTranslationEvidence.from_dict(forged_payload)
        with pytest.raises(ValueError, match="decision receipt"):
            forged_evidence.validate_execution_result(served, require_oracle=True)
        with pytest.raises(ValueError):
            TransitTranslationEvidence.from_dict({**evidence.to_dict(), "unknown": True})
        assert calls["count"] == 1
        assert session.phase == "response-unacknowledged"

        returned = _wait_for_response(response_client)
        assert returned.effect == served.effect
        assert returned.replayed is False
        _wait_for_ack(request_client.channel, (1,))
        _wait_for_ack(response_worker.channel, (1,))
        assert receiver.environment.kernel.journal.verify()
        assert [
            record.kind for record in receiver.environment.kernel.journal.records()
            if record.kind.startswith("structural_memory.read")
        ] == ["structural_memory.read_revision"]

        # A new transport frame with the same semantic identity and exact payload
        # must replay the committed receipt without entering the structural host.
        assert request_client.send(event) == 2
        replay = None
        deadline = time.monotonic() + 3.0
        while replay is None and time.monotonic() < deadline:
            replay = session.serve_once()
            if replay is None:
                time.sleep(0.005)
        assert replay is not None and replay.replayed is True
        assert replay.effect == served.effect
        replay_evidence = TransitTranslationEvidence.from_dict(replay.effect["_semantic_translation"])
        replay_oracle = TransitOracleEvidence.from_dict(replay.effect["_semantic_oracle"])
        assert replay_oracle == oracle
        assert replay_oracle.digest == oracle.digest
        assert replay_evidence == evidence
        assert replay_evidence.digest == evidence.digest
        replay_evidence.validate_execution_result(replay, require_oracle=True)
        assert calls["count"] == 1
        replayed_response = _wait_for_response(response_client)
        assert replayed_response.replayed is True
        assert replayed_response.effect == served.effect
        _wait_for_ack(request_client.channel, (2,))
        _wait_for_ack(response_worker.channel, (2,))
        assert session.phase == "idle"
    finally:
        for transport in (
            request_client_transport,
            request_worker_transport,
            response_worker_transport,
            response_client_transport,
        ):
            if not transport.closed:
                transport.close()


def test_structural_memory_host_refuses_context_revision_and_local_authority_mismatch() -> None:
    """Mathematics: no result is emitted when context c differs from C_v or receiver capability G(a,r) is absent."""

    receiver, authority_pid, version = _prepare_receiver()
    host = TransitStructuralMemoryHost(receiver, authority_pid)

    wrong_context = _event(context={"tenant": "beta", "partition": 4}, granted=frozenset({"read"}))
    with pytest.raises(TransitStructuralMemoryError, match="context"):
        host.handle(wrong_context)

    unknown_revision = _event(revision=version.spec.revision + 1, granted=frozenset({"read"}))
    with pytest.raises(TransitStructuralMemoryError, match="no admitted revision"):
        host.handle(unknown_revision)

    limited_pid = receiver.environment.kernel.spawn(
        "structural-memory-no-read",
        capabilities=(Capability("/safe", frozenset({"read"})),),
        parent_pid=receiver.environment.init_pid,
    )
    unprivileged_host = TransitStructuralMemoryHost(receiver, limited_pid)
    forged_grant = _event(granted=frozenset({"read"}))
    with pytest.raises(TransitStructuralMemoryError, match="lacks 'read'"):
        unprivileged_host.handle(forged_grant)


def test_transit_worker_checkpoint_restores_structural_memory_and_replays_same_semantic_read() -> None:
    """Mathematics: checkpoint receiver registry and execution ledger, rebind transports, and replay E[I] without a second generator read."""

    request_client_transport, request_worker_transport = _tcp_pair("client", "worker")
    response_worker_transport, response_client_transport = _tcp_pair("worker", "client")
    policy = ReliabilityPolicy(lease_ticks=1, max_attempts=3, window_size=4)
    request_client = HypervisorOperationChannel(
        ReliableChannel(request_client_transport, "client", "worker", "structural.read", policy)
    )
    request_worker = HypervisorOperationChannel(
        ReliableChannel(request_worker_transport, "worker", "worker", "structural.read", policy, peer="client")
    )
    response_worker = HypervisorOperationResultChannel(
        ReliableChannel(response_worker_transport, "worker", "client", "structural.result", policy),
        "client",
        "structural.read",
    )
    response_client = HypervisorOperationResultChannel(
        ReliableChannel(response_client_transport, "client", "client", "structural.result", policy, peer="worker"),
        "client",
        "structural.read",
    )
    receiver, authority_pid, version = _prepare_receiver()
    initial_host_calls = {"count": 0}
    replacement_transports: list[SocketTransport] = []

    class CountingHost(TransitStructuralMemoryHost):
        """Count receiver host entries, independently of generator read-cache use."""

        def handle(self, event: HypervisorArbitrationEvent) -> dict[str, object]:
            """Mathematics: increment c for each actual first-seen operation handler invocation."""
            initial_host_calls["count"] += 1
            return super().handle(event)

    def factory(operating_system, pid):
        """Mathematics: reconstruct the exact operation relation R from checkpoint receiver state and local PID."""
        return _build_router(operating_system, pid, CountingHost)

    router = factory(receiver, authority_pid)
    worker = TransitComputeWorker(receiver, authority_pid, router)
    event = _event(coordinate=250)
    try:
        assert request_client.send(event) == 1
        first = None
        deadline = time.monotonic() + 3.0
        while first is None and time.monotonic() < deadline:
            first = worker.serve_once(request_worker, response_worker)
            if first is None:
                time.sleep(0.005)
        assert first is not None and first.executed and not first.replayed
        checkpoint_evidence = TransitTranslationEvidence.from_dict(first.effect["_semantic_translation"])
        assert checkpoint_evidence.identity == event.identity
        assert checkpoint_evidence.request_fingerprint == first.fingerprint
        checkpoint_evidence.validate_execution_result(first)
        first_result = _wait_for_response(response_client)
        assert first_result.effect == first.effect
        _wait_for_ack(request_client.channel, (1,))
        _wait_for_ack(response_worker.channel, (1,))
        assert initial_host_calls["count"] == 1

        worker_checkpoint = worker.snapshot(request_worker, response_worker)
        client_request_state = request_client.channel.snapshot()
        client_response_state = response_client.snapshot()
        assert worker_checkpoint["state"]["receiver"]["structural_memory"]["active"]
        assert receiver.environment.kernel.journal.verify()

        for transport in (
            request_client_transport,
            request_worker_transport,
            response_worker_transport,
            response_client_transport,
        ):
            if not transport.closed:
                transport.close()

        # Process restart: rebuild each logical channel on newly authenticated TCP streams.
        new_request_client_transport, new_request_worker_transport = _tcp_pair("client", "worker")
        new_response_worker_transport, new_response_client_transport = _tcp_pair("worker", "client")
        replacement_transports.extend((
            new_request_client_transport,
            new_request_worker_transport,
            new_response_worker_transport,
            new_response_client_transport,
        ))
        restored_request_client = HypervisorOperationChannel(
            ReliableChannel.from_snapshot(client_request_state, new_request_client_transport)
        )
        restored_response_client = HypervisorOperationResultChannel.from_snapshot(
            client_response_state,
            new_response_client_transport,
        )
        restored_worker_hosts: list[CountingHost] = []

        def restored_factory(operating_system, pid):
            """Mathematics: rebind the same backend manifest while retaining the restored receiver registry and local authority."""
            host = CountingHost(operating_system, pid)
            restored_worker_hosts.append(host)
            return _build_router(operating_system, pid, lambda _os, _pid: host)

        restored_worker, restored_request, restored_response = TransitComputeWorker.from_snapshot(
            worker_checkpoint,
            new_request_worker_transport,
            new_response_worker_transport,
            compute_host_factory=restored_factory,
        )
        restored_session = TransitComputeSession(
            restored_worker,
            restored_request,
            restored_response,
        )
        assert restored_worker.operating_system.structural_memory.active_version("orbit-alpha") == version
        assert restored_session.phase == "idle"

        # New transport sequence, same operation identity/payload: semantic effect is replayed.
        assert restored_request_client.send(event) == 2
        replay = None
        deadline = time.monotonic() + 3.0
        while replay is None and time.monotonic() < deadline:
            replay = restored_session.serve_once()
            if replay is None:
                time.sleep(0.005)
        assert replay is not None
        assert replay.replayed is True
        assert replay.effect == first.effect
        restored_evidence = TransitTranslationEvidence.from_dict(replay.effect["_semantic_translation"])
        assert restored_evidence == checkpoint_evidence
        assert restored_evidence.digest == checkpoint_evidence.digest
        restored_evidence.validate_execution_result(replay)
        assert restored_worker_hosts[0].operating_system.structural_memory.active_version("orbit-alpha") == version
        assert initial_host_calls["count"] == 1

        replay_result = _wait_for_response(restored_response_client)
        assert replay_result.replayed is True
        assert replay_result.effect == first.effect
        _wait_for_ack(restored_request_client.channel, (2,))
        _wait_for_ack(restored_response.channel, (2,))
        assert restored_worker.operating_system.environment.kernel.journal.verify()
    finally:
        for transport in (
            request_client_transport,
            request_worker_transport,
            response_worker_transport,
            response_client_transport,
            *replacement_transports,
        ):
            if not transport.closed:
                transport.close()
