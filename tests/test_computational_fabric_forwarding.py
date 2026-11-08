from __future__ import annotations

import pytest

from mailcpu.computational_fabric_forwarding import (
    ComputationalFabricForwardingError,
    ComputationalFabricHopReceipt,
    computational_fabric_forward_channel_id,
)


def _terminal(status: str = "executed") -> ComputationalFabricHopReceipt:
    """Mathematics: Construct one bounded terminal hop result for receipt-chain relation tests."""
    accepted = status in {"executed", "replayed"}
    return ComputationalFabricHopReceipt(
        peer_id="peer-c",
        previous_peer_id="peer-b",
        next_peer_id=None,
        hop_index=2,
        operation_digest="a" * 64,
        envelope_digest="b" * 64,
        next_envelope_digest=None,
        decision_receipt="c" * 64,
        status=status,
        terminal_execution={
            "status": status,
            "accepted": accepted,
            "executed": accepted,
            "replayed": status == "replayed",
        },
    )


def test_hop_receipt_round_trip_binds_two_hop_result_to_terminal_execution() -> None:
    """Mathematics: The relay receipt is valid iff its child receipt continues the exact envelope and operation."""
    terminal = _terminal()
    relay = ComputationalFabricHopReceipt(
        peer_id="peer-b",
        previous_peer_id="peer-a",
        next_peer_id="peer-c",
        hop_index=1,
        operation_digest="a" * 64,
        envelope_digest="d" * 64,
        next_envelope_digest="b" * 64,
        decision_receipt="e" * 64,
        status="forwarded",
        downstream=terminal,
    )

    restored = ComputationalFabricHopReceipt.from_dict(relay.to_dict())

    assert relay.succeeded
    assert restored.succeeded
    assert restored.digest == relay.digest
    assert restored.downstream is not None
    assert restored.downstream.terminal_execution is not None
    assert restored.downstream.terminal_execution["status"] == "executed"


def test_hop_receipt_refuses_wrong_child_identity_or_envelope() -> None:
    """Mathematics: A downstream receipt must bind the parent operation, next peer, hop index and child envelope."""
    terminal = _terminal()
    with pytest.raises(ComputationalFabricForwardingError, match="does not continue"):
        ComputationalFabricHopReceipt(
            peer_id="peer-b",
            previous_peer_id="peer-a",
            next_peer_id="peer-c",
            hop_index=1,
            operation_digest="a" * 64,
            envelope_digest="d" * 64,
            next_envelope_digest="f" * 64,
            decision_receipt="e" * 64,
            status="forwarded",
            downstream=terminal,
        )


def test_refused_terminal_execution_cannot_be_reported_as_federated_success() -> None:
    """Mathematics: A local route refusal propagates through the receipt tree without becoming an execution grant."""
    terminal = _terminal("refused")
    relay = ComputationalFabricHopReceipt(
        peer_id="peer-b",
        previous_peer_id="peer-a",
        next_peer_id="peer-c",
        hop_index=1,
        operation_digest="a" * 64,
        envelope_digest="d" * 64,
        next_envelope_digest="b" * 64,
        decision_receipt="e" * 64,
        status="refused",
        downstream=terminal,
    )

    assert not terminal.succeeded
    assert not relay.succeeded

    with pytest.raises(ComputationalFabricForwardingError, match="status differs"):
        ComputationalFabricHopReceipt(
            peer_id="peer-b",
            previous_peer_id="peer-a",
            next_peer_id="peer-c",
            hop_index=1,
            operation_digest="a" * 64,
            envelope_digest="d" * 64,
            next_envelope_digest="b" * 64,
            decision_receipt="e" * 64,
            status="forwarded",
            downstream=terminal,
        )


def test_forward_channel_identity_is_stable_and_scoped_to_origin_channel() -> None:
    """Mathematics: Distinct origin channels have distinct replay namespaces independent of their intermediary peer."""
    first = computational_fabric_forward_channel_id("peer-a", "application.batch")
    retry = computational_fabric_forward_channel_id("peer-a", "application.batch")
    other = computational_fabric_forward_channel_id("peer-a", "application.interactive")

    assert first == retry
    assert first != other
    assert first.startswith("computational.fabric.forward.v1.")
