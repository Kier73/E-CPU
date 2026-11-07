from __future__ import annotations

import pytest

from mailcpu.classifier import HypervisorArbitrationEvent, HypervisorRequest
from mailcpu.egpu import EGPUError, EGPUHost, EGPUOperationalLocus
from mailcpu.transit_router import TransitBackendRouter
from mailcpu.transit_simt import TransitSIMTError, TransitSIMTHost, TransitSIMTSharedMemoryHost


def _event(payload: dict[str, object], *, sequence: int = 1,
           granted: frozenset[str] = frozenset({"execute"})) -> HypervisorArbitrationEvent:
    """Mathematics: create a typed E-GPU operation event with a stable semantic identity."""

    request = HypervisorRequest(
        EGPUHost.operation_name, EGPUHost.resource_name, payload,
        frozenset({"execute"}), granted, False,
    )
    return HypervisorArbitrationEvent("test-client", "egpu", sequence, 7, request)


def test_egpu_vector_methods_navigate_simt_and_verify_scalar_results() -> None:
    """Mathematics: lane-wise vector add and multiply equal independent scalar integer projections."""

    host = EGPUHost(host_id="egpu.test")
    left, right = [1, -2, 7, 12], [9, 5, -3, 8]
    added = host.handle(_event({"method": "vector.add", "left": left, "right": right, "max_steps": 16}))
    multiplied = host.handle(_event({"method": "vector.multiply", "left": left, "right": right, "max_steps": 16}, sequence=2))
    assert added["route"] == ["egpu.test.dispatch", "egpu.test.simt", "egpu.test.verify"]
    assert added["result"]["outputs"]["result"] == [a + b for a, b in zip(left, right)]
    assert multiplied["result"]["outputs"]["result"] == [a * b for a, b in zip(left, right)]
    assert len(added["result_digest"]) == len(added["receipt_digest"]) == 64
    assert added["receipt_digest"] != multiplied["receipt_digest"]


def test_egpu_tree_reduction_uses_stable_method_route_and_digest() -> None:
    """Mathematics: pairwise reduction preserves scalar sum and canonical level trace."""

    host = EGPUHost(host_id="egpu.reduce")
    payload = {"method": "vector.sum", "values": [3, -1, 8, 2, 4], "max_steps": 8}
    first, second = host.handle(_event(payload)), host.handle(_event(payload))
    assert first == second
    assert first["route"] == ["egpu.reduce.dispatch", "egpu.reduce.reduce", "egpu.reduce.verify"]
    assert first["result"]["sum"] == 16
    assert first["result"]["levels"] == 3
    assert first["result"]["work_units"] == 4
    assert first["result"]["trace"][-1]["output_width"] == 1


def test_egpu_general_simt_kernel_uses_existing_reference_instruction_algebra() -> None:
    """Mathematics: a custom bounded lane kernel preserves its SIMT output and route witness."""

    host = EGPUHost()
    result = host.handle(_event({
        "method": "simt.kernel", "lanes": 3, "inputs": {"x": [2, 4, 6]},
        "program": [["load", "value", "x"], ["mul", "square", "value", "value"],
                    ["store", "squares", "square"], ["halt"]],
        "max_steps": 16,
    }))
    assert result["result"]["outputs"]["squares"] == [4, 16, 36]
    assert result["route"] == ["egpu.default.dispatch", "egpu.default.simt", "egpu.default.verify"]


def test_egpu_route_resolution_is_minimum_hop_and_lexically_deterministic() -> None:
    """Mathematics: equal-hop routes to a capability select the lexically first path."""

    loci = (
        EGPUOperationalLocus("custom.dispatch", "dispatch", frozenset({"egpu.dispatch"}), ("custom.z", "custom.a")),
        EGPUOperationalLocus("custom.z", "relay", frozenset({"relay.z"}), ("custom.simt",)),
        EGPUOperationalLocus("custom.a", "relay", frozenset({"relay.a"}), ("custom.simt",)),
        EGPUOperationalLocus("custom.simt", "execution", frozenset({"simt.execute"}), ("custom.verify",)),
        EGPUOperationalLocus("custom.verify", "verification", frozenset({"result.verify"}), ()),
    )
    assert EGPUHost(host_id="egpu.custom", loci=loci).resolve_path("simt.execute") == (
        "custom.dispatch", "custom.a", "custom.simt", "custom.verify",
    )


def test_egpu_refuses_missing_authority_and_unreachable_method_locus() -> None:
    """Mathematics: execution requires the exact outer grant and a complete directed route."""

    payload = {"method": "vector.add", "left": [1, 2], "right": [3, 4], "max_steps": 8}
    with pytest.raises(EGPUError, match="receiver-local execute authority"):
        EGPUHost().handle(_event(payload, granted=frozenset()))
    loci = (
        EGPUOperationalLocus("broken.dispatch", "dispatch", frozenset({"egpu.dispatch"}), ("broken.verify",)),
        EGPUOperationalLocus("broken.simt", "execution", frozenset({"simt.execute"}), ("broken.verify",)),
        EGPUOperationalLocus("broken.verify", "verification", frozenset({"result.verify"}), ()),
    )
    with pytest.raises(EGPUError, match="no operational path"):
        EGPUHost(host_id="egpu.broken", loci=loci).handle(_event(payload))


def test_egpu_is_an_exact_backend_in_the_heterogeneous_transit_router() -> None:
    """Mathematics: E-GPU dispatch occurs only under its exact operation/resource key."""

    router = TransitBackendRouter()
    router.register_backend(EGPUHost(host_id="egpu.routed"))
    assert (EGPUHost.operation_name, EGPUHost.resource_name) in router.registered_backends()
    result = router.handle(_event({"method": "vector.add", "left": [5, 6], "right": [7, 8], "max_steps": 8}))
    assert result["result"]["outputs"]["result"] == [12, 14]
    with pytest.raises(ValueError, match="already registered"):
        router.register_backend(EGPUHost(host_id="egpu.duplicate"))


def _shared_broadcast_payload() -> dict[str, object]:
    """Mathematics: construct a workgroup where lane zero publishes one cell and every lane reads it after a barrier."""

    return {
        "method": "workgroup.shared_kernel",
        "lanes": 4,
        "inputs": {"sample": [73, 11, 29, 47]},
        "shared_buffers": {"scratch": 1},
        "program": [
            ["load", "sample_value", "sample"],
            ["lane_id", "lane"],
            ["const", "zero", 0],
            ["const", "one", 1],
            ["lt", "leader", "lane", "one"],
            ["if", "leader"],
            ["shared_store", "scratch", "zero", "sample_value"],
            ["endif"],
            ["barrier"],
            ["shared_load", "broadcast", "scratch", "zero"],
            ["store", "broadcast_output", "broadcast"],
            ["halt"],
        ],
        "max_steps": 16,
    }


def test_egpu_navigates_workgroup_and_shared_memory_hosts_for_lane_broadcast() -> None:
    """Mathematics: a lane-zero shared write becomes visible to all four lanes only after one converged barrier epoch."""

    host = EGPUHost(host_id="egpu.workgroup")
    result = host.handle(_event(_shared_broadcast_payload()))
    assert result["route"] == [
        "egpu.workgroup.dispatch",
        "egpu.workgroup.workgroup",
        "egpu.workgroup.shared",
        "egpu.workgroup.verify",
    ]
    assert result["capability"] == "workgroup.execute"
    assert result["result"]["outputs"]["broadcast_output"] == [73, 73, 73, 73]
    assert result["result"]["shared_memory"] == {"scratch": [73]}
    assert result["result"]["shared_epochs"] == [
        {
            "epoch": 1,
            "pc": 8,
            "arrivals": 4,
            "published": {"scratch": [0]},
        }
    ]
    assert result["result"]["barriers"] == [{"epoch": 1, "pc": 8, "arrivals": 4}]
    assert len(result["result_digest"]) == 64
    assert len(result["receipt_digest"]) == 64


def test_shared_memory_refuses_unfenced_reads_and_conflicting_writers() -> None:
    """Mathematics: shared loads require a committed visibility epoch and each address has at most one writer per epoch."""

    host = TransitSIMTHost()
    before_barrier = {
        "lanes": 2,
        "inputs": {"x": [5, 9]},
        "shared_buffers": {"scratch": 2},
        "program": [
            ["lane_id", "lane"],
            ["load", "value", "x"],
            ["shared_store", "scratch", "lane", "value"],
            ["shared_load", "observed", "scratch", "lane"],
            ["store", "out", "observed"],
            ["halt"],
        ],
        "max_steps": 16,
    }
    event = HypervisorArbitrationEvent(
        "client", "simt", 1, 100,
        HypervisorRequest(
            TransitSIMTHost.operation_name,
            TransitSIMTHost.resource_name,
            before_barrier,
            frozenset({"execute"}),
            frozenset({"execute"}),
        ),
    )
    with pytest.raises(TransitSIMTError, match="barrier is required before load"):
        host.handle(event)

    conflict = {
        "lanes": 2,
        "inputs": {"x": [5, 9]},
        "shared_buffers": {"scratch": 1},
        "program": [
            ["const", "zero", 0],
            ["load", "value", "x"],
            ["shared_store", "scratch", "zero", "value"],
            ["barrier"],
            ["shared_load", "observed", "scratch", "zero"],
            ["store", "out", "observed"],
            ["halt"],
        ],
        "max_steps": 16,
    }
    conflict_event = HypervisorArbitrationEvent(
        "client", "simt", 2, 101,
        HypervisorRequest(
            TransitSIMTHost.operation_name,
            TransitSIMTHost.resource_name,
            conflict,
            frozenset({"execute"}),
            frozenset({"execute"}),
        ),
    )
    with pytest.raises(TransitSIMTError, match="shared write conflict"):
        host.handle(conflict_event)


def test_shared_memory_host_enforces_capacity_and_initialization() -> None:
    """Mathematics: declared shared storage remains finite and an uninitialized cell is not observable as a value."""

    with pytest.raises(TransitSIMTError, match="total shared-memory capacity"):
        TransitSIMTSharedMemoryHost({"a": 3, "b": 2}, max_total_elements=4)
    memory = TransitSIMTSharedMemoryHost({"scratch": 2})
    with pytest.raises(TransitSIMTError, match="has not been initialized"):
        memory.load("scratch", 0, 0)


def _tcp_pair(local: str, peer: str):
    """Mathematics: create reciprocal loopback TCP transports for one persistent transit request and response path."""

    from mailcpu import SocketTransport

    listener = SocketTransport.listen("127.0.0.1", 0)
    port = listener.getsockname()[1]
    local_transport = SocketTransport.connect("127.0.0.1", port, local, peer)
    peer_transport = SocketTransport.accept(listener, peer, local)
    listener.close()
    return local_transport, peer_transport


def test_egpu_shared_workgroup_survives_transit_checkpoint_and_semantic_replay(tmp_path) -> None:
    """Mathematics: a shared-memory E-GPU result is durably checkpointed, then the same semantic identity replays without backend re-entry."""

    import time

    from mailcpu import (
        Capability,
        HeadlessOS,
        HypervisorPolicy,
        HypervisorOperationChannel,
        HypervisorOperationResultChannel,
        HypervisorRequest,
        ReliabilityPolicy,
        ReliableChannel,
        TransitComputeSession,
        TransitComputeWorker,
    )

    backend_calls: list[tuple[str, str, int]] = []

    def build_router(operating_system, authority_pid):
        """Mathematics: reconstruct the identical scalar-plus-EGPU backend domain against the restored receiver and authority."""

        from mailcpu import EGPUHost, TransitBackendRouter

        router = TransitBackendRouter()
        egpu = EGPUHost()
        original_handle = egpu.handle

        def counted_handle(event):
            """Mathematics: record an actual E-GPU entry, distinguishing backend execution from semantic-ledger replay."""

            backend_calls.append(event.identity)
            return original_handle(event)

        egpu.handle = counted_handle
        router.register_backend(egpu)
        return router

    policy = ReliabilityPolicy(lease_ticks=1, max_attempts=3, window_size=4)
    client_transport, worker_transport = _tcp_pair("client", "worker")
    request_sender = HypervisorOperationChannel(
        ReliableChannel(client_transport, "client", "worker", "compute", policy)
    )
    request_receiver = HypervisorOperationChannel(
        ReliableChannel(worker_transport, "worker", "worker", "compute", policy, peer="client")
    )
    response_sender = HypervisorOperationResultChannel(
        ReliableChannel(worker_transport, "worker", "client", "compute.result", policy),
        "client",
        "compute",
    )
    response_receiver = HypervisorOperationResultChannel(
        ReliableChannel(client_transport, "client", "client", "compute.result", policy, peer="worker"),
        "client",
        "compute",
    )

    receiver = HeadlessOS()
    receiver.hypervisor.policy = HypervisorPolicy(
        review_confidence=0.0,
        automatic_confidence=0.0,
        destructive_confidence=0.0,
        danger_review_probability=1.0,
    )
    authority_pid = receiver.environment.kernel.spawn(
        "egpu-shared-worker",
        capabilities=(Capability("/gpu/egpu", frozenset({"execute"})),),
        parent_pid=receiver.environment.init_pid,
    )
    router = build_router(receiver, authority_pid)
    session = TransitComputeSession(
        TransitComputeWorker(receiver, authority_pid, router),
        request_receiver,
        response_sender,
    )
    event = HypervisorArbitrationEvent(
        "client",
        "compute",
        77,
        900,
        HypervisorRequest(
            EGPUHost.operation_name,
            EGPUHost.resource_name,
            _shared_broadcast_payload(),
            frozenset({"execute"}),
            frozenset(),
            False,
        ),
    )
    restored_client_transport = None
    restored_worker_transport = None
    try:
        assert request_sender.send(event) == 1
        deadline = time.monotonic() + 3.0
        while session.phase != "request-ready" and time.monotonic() < deadline:
            time.sleep(0.005)
        assert session.phase == "request-ready"

        served = None
        deadline = time.monotonic() + 3.0
        while served is None and time.monotonic() < deadline:
            served = session.serve_once()
            if served is None:
                time.sleep(0.005)
        assert served is not None and served.executed and not served.replayed
        assert served.effect["result"]["outputs"]["broadcast_output"] == [73, 73, 73, 73]
        assert "_semantic_translation" in served.effect
        assert backend_calls == [event.identity]

        returned = None
        deadline = time.monotonic() + 3.0
        while returned is None and time.monotonic() < deadline:
            returned = response_receiver.receive()
            if returned is None:
                time.sleep(0.005)
        assert returned is not None and not returned.replayed
        assert returned.effect == served.effect

        request_acks: tuple[int, ...] = ()
        response_acks: tuple[int, ...] = ()
        deadline = time.monotonic() + 3.0
        while (request_acks != (1,) or response_acks != (1,)) and time.monotonic() < deadline:
            request_acks = request_sender.channel.process_ack()
            response_acks = response_sender.channel.process_ack()
            if request_acks != (1,) or response_acks != (1,):
                time.sleep(0.005)
        assert request_acks == (1,) and response_acks == (1,)
        assert session.phase == "idle"

        checkpoint = tmp_path / "egpu-shared-session.json"
        checkpoint_digest = session.save_checkpoint(checkpoint)
        client_request_state = request_sender.channel.snapshot()
        client_response_state = response_receiver.snapshot()

        restored_client_transport, restored_worker_transport = _tcp_pair("client", "worker")
        restored_request_sender = HypervisorOperationChannel(
            ReliableChannel.from_snapshot(client_request_state, restored_client_transport)
        )
        restored_response_receiver = HypervisorOperationResultChannel.from_snapshot(
            client_response_state,
            restored_client_transport,
        )
        restored_session = TransitComputeSession.from_checkpoint(
            checkpoint,
            restored_worker_transport,
            restored_worker_transport,
            compute_host_factory=build_router,
        )
        assert restored_session.state()["phase"] == "idle"
        assert restored_session.worker.operating_system.environment.kernel.journal.verify()
        assert checkpoint_digest

        # The transport delivery identity advances to 2, but the semantic
        # operation identity (source, channel, sequence) remains unchanged.
        assert restored_request_sender.send(event) == 2
        deadline = time.monotonic() + 3.0
        while restored_session.phase != "request-ready" and time.monotonic() < deadline:
            time.sleep(0.005)
        assert restored_session.phase == "request-ready"

        replayed = None
        deadline = time.monotonic() + 3.0
        while replayed is None and time.monotonic() < deadline:
            replayed = restored_session.serve_once()
            if replayed is None:
                time.sleep(0.005)
        assert replayed is not None
        assert replayed.replayed is True
        assert replayed.effect == served.effect
        assert backend_calls == [event.identity]

        replayed_delivery = None
        deadline = time.monotonic() + 3.0
        while replayed_delivery is None and time.monotonic() < deadline:
            replayed_delivery = restored_response_receiver.receive()
            if replayed_delivery is None:
                time.sleep(0.005)
        assert replayed_delivery is not None and replayed_delivery.replayed is True
        assert replayed_delivery.effect == served.effect

        request_acks = ()
        response_acks = ()
        deadline = time.monotonic() + 3.0
        while (request_acks != (2,) or response_acks != (2,)) and time.monotonic() < deadline:
            request_acks = restored_request_sender.channel.process_ack()
            response_acks = restored_session.response.channel.process_ack()
            if request_acks != (2,) or response_acks != (2,):
                time.sleep(0.005)
        assert request_acks == (2,) and response_acks == (2,)
        assert restored_session.phase == "idle"
        assert restored_session.worker.operating_system.environment.kernel.journal.verify()
        assert backend_calls == [event.identity]
    finally:
        for transport in (
            client_transport,
            worker_transport,
            restored_client_transport,
            restored_worker_transport,
        ):
            if transport is not None and not transport.closed:
                transport.close()


def test_shared_memory_refuses_halt_with_unpublished_writes() -> None:
    """Mathematics: a workgroup cannot terminate while its pending shared-memory write set is non-empty."""

    event = HypervisorArbitrationEvent(
        "client",
        "simt",
        3,
        102,
        HypervisorRequest(
            TransitSIMTHost.operation_name,
            TransitSIMTHost.resource_name,
            {
                "lanes": 1,
                "inputs": {"x": [17]},
                "shared_buffers": {"scratch": 1},
                "program": [
                    ["const", "zero", 0],
                    ["load", "value", "x"],
                    ["shared_store", "scratch", "zero", "value"],
                    ["halt"],
                ],
                "max_steps": 8,
            },
            frozenset({"execute"}),
            frozenset({"execute"}),
        ),
    )
    with pytest.raises(TransitSIMTError, match="HALT requires a barrier"):
        TransitSIMTHost().handle(event)
