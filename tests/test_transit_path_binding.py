from __future__ import annotations

import pytest

from mailcpu import (
    Capability,
    HeadlessOS,
    HypervisorArbitrationEvent,
    HypervisorOperationChannel,
    HypervisorOperationResultChannel,
    HypervisorPolicy,
    HypervisorRequest,
    ReliabilityPolicy,
    ReliableChannel,
    SocketTransport,
    TransitComputeSession,
    TransitComputeWorker,
    TransitPathBindingError,
    TransitPathSessionBinding,
    TransitPathState,
    TransitPathStateError,
)


MODULI = (101, 103, 107, 109, 113)


def _tcp_pair(local: str, peer: str) -> tuple[SocketTransport, SocketTransport]:
    """Mathematics: create reciprocal real TCP transports with stable logical endpoint labels."""
    listener = SocketTransport.listen("127.0.0.1", 0)
    port = listener.getsockname()[1]
    local_transport = SocketTransport.connect("127.0.0.1", port, local, peer)
    peer_transport = SocketTransport.accept(listener, peer, local)
    listener.close()
    return local_transport, peer_transport


def _event(sequence: int) -> HypervisorArbitrationEvent:
    """Mathematics: create a bounded semantic operation whose expected terminal result is 48."""
    source = "\n".join((
        "set left 19",
        "set right 23",
        "add total left right",
        "set offset 6",
        "add result total offset",
        "halt",
    ))
    return HypervisorArbitrationEvent(
        "origin",
        "compute",
        sequence,
        500 + sequence,
        HypervisorRequest(
            "execute deterministic CPU arithmetic program",
            "/cpu/compute",
            {
                "source": source,
                "initial_registers": {"seed": 7},
                "max_ticks": 64,
            },
            frozenset({"execute"}),
            frozenset({"execute"}),
        ),
    )


def _harness(*, max_attempts: int = 3) -> dict[str, object]:
    """Mathematics: compose one TCP transit session and its matching requester-side reliable channels."""
    request_origin_transport, request_worker_transport = _tcp_pair("origin", "worker")
    response_worker_transport, response_origin_transport = _tcp_pair("worker", "origin")
    policy = ReliabilityPolicy(lease_ticks=1, max_attempts=max_attempts, window_size=8)

    request_sender = HypervisorOperationChannel(
        ReliableChannel(
            request_origin_transport, "origin", "worker", "compute", policy
        )
    )
    request_receiver = HypervisorOperationChannel(
        ReliableChannel(
            request_worker_transport, "worker", "worker", "compute", policy, peer="origin"
        )
    )
    response_sender = HypervisorOperationResultChannel(
        ReliableChannel(
            response_worker_transport, "worker", "origin", "compute.result", policy
        ),
        "origin",
        "compute",
    )
    result_receiver = HypervisorOperationResultChannel(
        ReliableChannel(
            response_origin_transport, "origin", "origin", "compute.result", policy, peer="worker"
        ),
        "origin",
        "compute",
    )

    receiver = HeadlessOS()
    worker_pid = receiver.environment.kernel.spawn(
        "bound-path-worker",
        capabilities=(Capability("/cpu/compute", frozenset({"execute"})),),
        parent_pid=receiver.environment.init_pid,
    )
    receiver.hypervisor.policy = HypervisorPolicy(
        review_confidence=0.0,
        automatic_confidence=0.0,
        destructive_confidence=0.0,
        danger_review_probability=1.0,
    )
    session = TransitComputeSession(
        TransitComputeWorker(receiver, worker_pid),
        request_receiver,
        response_sender,
    )
    binding = TransitPathSessionBinding(
        "origin-to-worker-compute",
        session,
        request_sender,
        result_receiver,
    )
    return {
        "binding": binding,
        "session": session,
        "request_sender": request_sender,
        "result_receiver": result_receiver,
        "transports": (
            request_origin_transport,
            request_worker_transport,
            response_worker_transport,
            response_origin_transport,
        ),
    }


def _close(harness: dict[str, object]) -> None:
    """Mathematics: close every socket allocated by one loopback test harness."""
    for transport in harness["transports"]:
        if not transport.closed:
            transport.close()


def test_live_binding_measures_rtt_service_queue_and_acknowledgements() -> None:
    """Mathematics: one live request yields independent requester RTT, receiver service time, queue observations, and ACK evidence."""
    harness = _harness()
    binding = harness["binding"]
    try:
        retained = binding.state.store(42, k=3, moduli=MODULI)
        assert binding.send_request(_event(1)) == 1
        assert binding.queue_observations[-1].cause == "request-sent"
        assert binding.queue_observations[-1].request_ready is True

        execution = binding.serve_once()
        assert execution is not None
        assert execution.executed is True
        assert execution.effect["registers"]["result"] == 48
        assert len(binding.service_samples) == 1
        assert binding.service_samples[0].operation_sequence == 1
        assert binding.service_samples[0].service_us >= 0

        result = binding.receive_result()
        assert result is not None
        assert result.sequence == 1
        assert result.effect["registers"]["result"] == 48
        assert binding.state.mode == "memory"
        assert binding.state.read(retained) == 42

        acks = binding.process_acknowledgements()
        assert acks["request_transport_sequences"] == (1,)
        assert acks["request_operations"] == (1,)
        assert acks["response_transport_sequences"] == (1,)
        assert acks["response_operations"] == (1,)
        assert harness["session"].phase == "idle"

        binding.state.set_mode("processor")
        summary = binding.state.summarize()
        assert summary.sample_count == 1
        assert summary.loss_count == 0
        assert summary.mean_latency_us is not None
        assert binding.state.mode == "processor"

        causes = [item.cause for item in binding.queue_observations]
        assert "request-sent" in causes
        assert "service-completed" in causes
        assert "result-received" in causes
        assert "acknowledgements-processed" in causes
    finally:
        _close(harness)


def test_ack_retry_exhaustion_is_not_silently_counted_as_operation_loss() -> None:
    """Mathematics: a failed transport ACK/retry relation is not proof that the semantic operation was lost."""
    harness = _harness(max_attempts=1)
    binding = harness["binding"]
    try:
        binding.send_request(_event(9))
        outcome = binding.tick_reliability()
        assert outcome["request_transport_sequences"] == (1,)
        assert outcome["request_operations"] == (9,)

        binding.state.set_mode("processor")
        summary_before = binding.state.summarize()
        assert summary_before.loss_count == 0

        binding.record_request_timeout(9)
        summary_after = binding.state.summarize()
        assert summary_after.loss_count == 1
        assert summary_after.unresolved_loss_count == 1
        assert any(item["kind"] == "operation-timeout" for item in binding.protocol_events)
    finally:
        _close(harness)


def test_binding_snapshot_round_trip_requires_quiescent_session_and_matching_channels() -> None:
    """Mathematics: binding restore is valid only at an idle session boundary with matching session and endpoint-channel digests."""
    harness = _harness()
    binding = harness["binding"]
    try:
        binding.send_request(_event(1))
        assert binding.serve_once() is not None
        assert binding.receive_result() is not None
        binding.process_acknowledgements()

        snapshot = binding.snapshot()
        restored = TransitPathSessionBinding.from_snapshot(
            snapshot,
            harness["session"],
            harness["request_sender"],
            harness["result_receiver"],
        )
        assert restored.path_id == binding.path_id
        assert restored.state.snapshot() == binding.state.snapshot()
        assert restored.queue_observations == binding.queue_observations
        assert restored.service_samples == binding.service_samples
        assert restored.protocol_events == binding.protocol_events
        assert restored.snapshot() == snapshot
    finally:
        _close(harness)


def test_binding_rejects_checkpoint_with_unacknowledged_response() -> None:
    """Mathematics: a response frame pending ACK prevents the composed binding checkpoint even when the result was already produced."""
    harness = _harness()
    binding = harness["binding"]
    try:
        binding.send_request(_event(1))
        assert binding.serve_once() is not None
        assert binding.session.phase == "response-unacknowledged"
        with pytest.raises(TransitPathBindingError, match="not idle"):
            binding.snapshot()
    finally:
        _close(harness)


def test_binding_rejects_mismatched_endpoint_contract() -> None:
    """Mathematics: a requester result channel from a different peer cannot be attached to this receiver session."""
    harness = _harness()
    binding = harness["binding"]
    try:
        wrong_transport = InMemoryTransport()
        wrong_request = HypervisorOperationChannel(
            ReliableChannel(wrong_transport, "someone-else", "worker", "compute")
        )
        with pytest.raises(TransitPathBindingError, match="do not match"):
            TransitPathSessionBinding(
                "bad-path",
                harness["session"],
                wrong_request,
                harness["result_receiver"],
            )
    finally:
        _close(harness)
