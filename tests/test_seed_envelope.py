from __future__ import annotations

import hashlib
import json

import pytest

from mailcpu import (
    HeadlessOS,
    InMemoryTransport,
    SeedEnvelopeError,
    SeedInputReceipt,
    SocketTransport,
    SystemIdentity,
    SystemSeed,
    SystemSeedEnvelope,
)


def _envelope(system_id: str, incarnation: int = 1) -> SystemSeedEnvelope:
    """Mathematics: construct `E=(I,R,C,Σ,F)` with one canonical external input frontier receipt."""

    seed = SystemSeed.from_system(HeadlessOS())
    receipt = SeedInputReceipt("resolver", 1, "a" * 64)
    return SystemSeedEnvelope(
        SystemIdentity(system_id, incarnation),
        "origin",
        "ops",
        seed,
        (receipt,),
    )


def test_seed_envelope_round_trips_and_separates_shared_mailboxes() -> None:
    """Mathematics: `decode(encode(E))=E` and distinct `(system_id,incarnation)` pairs have disjoint routes."""

    first = _envelope("shared-host-a")
    second = _envelope("shared-host-b")
    renewed = _envelope("shared-host-a", incarnation=2)
    assert len({first.route(), second.route(), renewed.route()}) == 3
    assert SystemSeedEnvelope.from_bytes(first.to_bytes()).snapshot() == first.snapshot()

    transport = InMemoryTransport()
    transport.send(first.route(), first.to_message("node"))
    transport.send(second.route(), second.to_message("node"))
    first_message = transport.poll(first.route())
    second_message = transport.poll(second.route())
    assert first_message is not None and second_message is not None
    assert SystemSeedEnvelope.from_message(first_message).snapshot() == first.snapshot()
    assert SystemSeedEnvelope.from_message(second_message).snapshot() == second.snapshot()


def test_seed_envelope_crosses_real_socket_transport() -> None:
    """Mathematics: the transport algebra preserves the envelope bytes `B` across `SocketTransport` framing."""

    sender_listener = SocketTransport.listen("127.0.0.1", 0)
    sender_transport = SocketTransport.connect(
        "127.0.0.1",
        sender_listener.getsockname()[1],
        "node-a",
        "node-b",
    )
    receiver_transport = SocketTransport.accept(sender_listener, "node-b", "node-a")
    sender_listener.close()
    envelope = _envelope("socket-system")
    try:
        sender_transport.send(envelope.route(), envelope.to_message("node-a"))
        received = receiver_transport.list(envelope.route())
        assert len(received) == 1
        assert SystemSeedEnvelope.from_message(received[0]).snapshot() == envelope.snapshot()
    finally:
        sender_transport.close()
        receiver_transport.close()


def test_seed_envelope_rejects_tampering_before_state_restore() -> None:
    """Mathematics: `digest(payload')≠digest(payload)` implies envelope refusal before `restore(Σ)` is callable."""

    envelope = _envelope("tamper-proof")
    document = json.loads(envelope.to_bytes().decode("utf-8"))
    payload_entries = document["payload"]["dict"]
    identity_entry = next(entry for entry in payload_entries if entry[0] == "identity")
    identity_entry[1]["dict"] = [
        ["incarnation", 2],
        ["system_id", "tamper-proof"],
    ]
    with pytest.raises(SeedEnvelopeError, match="digest"):
        SystemSeedEnvelope.from_bytes(json.dumps(document).encode("utf-8"))


def test_seed_envelope_freezes_frontier_and_rejects_duplicate_receipts() -> None:
    """Mathematics: the frontier is a finite set `F`, so `|F|=|set(F)|` and later list mutation cannot alter `E`."""

    receipt = SeedInputReceipt("resolver", 1, "b" * 64)
    frontier = [receipt]
    envelope = SystemSeedEnvelope(
        SystemIdentity("frontier-system", 1),
        "origin",
        "ops",
        SystemSeed.from_system(HeadlessOS()),
        frontier,
    )
    frontier.append(SeedInputReceipt("resolver", 2, "c" * 64))
    assert envelope.input_frontier == (receipt,)
    with pytest.raises(SeedEnvelopeError, match="duplicate"):
        SystemSeedEnvelope(
            SystemIdentity("frontier-system", 1),
            "origin",
            "ops",
            envelope.seed,
            (receipt, receipt),
        )


def test_seed_envelope_rejects_route_mismatch_before_restore() -> None:
    """Mathematics: message admission requires `recipient=addr=ρ(E)` before `restore(Σ)` is reachable."""

    envelope = _envelope("route-bound")
    message = envelope.to_message("node")
    forged = message.__class__(
        sender=message.sender,
        recipient="sys:5:other:1:6:origin:3:ops",
        op=message.op,
        addr=message.addr,
        value=message.value,
        seq=message.seq,
        body=message.body,
        message_id=message.message_id,
    )
    with pytest.raises(SeedEnvelopeError, match="route"):
        SystemSeedEnvelope.from_message(forged)


def test_seed_envelope_restore_requires_expected_identity() -> None:
    """Mathematics: admission is partial, `restore(E,H)` exists only when `H.identity=E.identity`."""

    envelope = _envelope("identity-bound")
    with pytest.raises(SeedEnvelopeError, match="identity"):
        envelope.restore(SystemIdentity("different-host", 1))


def test_seed_envelope_rejects_digest_valid_noncanonical_payload() -> None:
    """Mathematics: a canonical encoding must be a fixed point, `encode(decode(C))=C`, before admission."""

    document = json.loads(_envelope("canonical-only").to_bytes().decode("utf-8"))
    payload_entries = document["payload"]["dict"]
    identity_entry = next(entry for entry in payload_entries if entry[0] == "identity")
    identity_entry[1]["dict"].append(["system_id", "duplicate-key"])
    canonical = json.dumps(
        document["payload"],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    document["digest"] = hashlib.sha256(canonical).hexdigest()
    with pytest.raises(SeedEnvelopeError, match="normalized"):
        SystemSeedEnvelope.from_bytes(json.dumps(document).encode("utf-8"))
