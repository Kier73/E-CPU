from __future__ import annotations

from dataclasses import replace

import pytest

from mailcpu import (
    DEFAULT_CHECKPOINT_KIND,
    InMemoryTransport,
    RecoveryPolicyAdvertisement,
    RecoveryPolicyChannel,
    RecoveryPolicyError,
    RecoveryPolicyOffer,
    ReliabilityPolicy,
    ReliableChannel,
    SocketTransport,
    advertise_recovery_policy,
    negotiate_recovery_policy,
)


def _tcp_pair() -> tuple[SocketTransport, SocketTransport]:
    """Mathematics: create reciprocal AF_INET streams `T_origin↔T_receiver` for policy control frames."""

    listener = SocketTransport.listen("127.0.0.1", 0)
    port = listener.getsockname()[1]
    origin = SocketTransport.connect("127.0.0.1", port, "origin", "receiver")
    receiver = SocketTransport.accept(listener, "receiver", "origin")
    listener.close()
    return origin, receiver


def _control_channels(
    origin_transport: SocketTransport,
    receiver_transport: SocketTransport,
    policy: ReliabilityPolicy,
) -> tuple[RecoveryPolicyChannel, RecoveryPolicyChannel, RecoveryPolicyChannel, RecoveryPolicyChannel, RecoveryPolicyChannel, RecoveryPolicyChannel]:
    """Mathematics: compose three reciprocal reliable FIFO pairs for `advertisement`, `offer`, and `agreement`."""

    advertisement_sender = RecoveryPolicyChannel(
        ReliableChannel(receiver_transport, "receiver", "origin", "recovery.advertisement", policy)
    )
    advertisement_receiver = RecoveryPolicyChannel(
        ReliableChannel(origin_transport, "origin", "origin", "recovery.advertisement", policy, peer="receiver")
    )
    offer_sender = RecoveryPolicyChannel(
        ReliableChannel(origin_transport, "origin", "receiver", "recovery.offer", policy)
    )
    offer_receiver = RecoveryPolicyChannel(
        ReliableChannel(receiver_transport, "receiver", "receiver", "recovery.offer", policy, peer="origin")
    )
    agreement_sender = RecoveryPolicyChannel(
        ReliableChannel(receiver_transport, "receiver", "origin", "recovery.agreement", policy)
    )
    agreement_receiver = RecoveryPolicyChannel(
        ReliableChannel(origin_transport, "origin", "origin", "recovery.agreement", policy, peer="receiver")
    )
    return (
        advertisement_sender,
        advertisement_receiver,
        offer_sender,
        offer_receiver,
        agreement_sender,
        agreement_receiver,
    )


def test_receiver_advertised_policy_negotiates_over_real_tcp_and_round_trips() -> None:
    """Mathematics: `G=O∩A` selects `W=min(8,3)=3`, `L=max(1,2)=2`, and `R=min(6,4)=4` over AF_INET."""

    origin_transport, receiver_transport = _tcp_pair()
    policy = ReliabilityPolicy(lease_ticks=1, max_attempts=6, window_size=8)
    (
        advertisement_sender,
        advertisement_receiver,
        offer_sender,
        offer_receiver,
        agreement_sender,
        agreement_receiver,
    ) = _control_channels(origin_transport, receiver_transport, policy)
    advertisement = advertise_recovery_policy(
        checkpoint_kinds=(DEFAULT_CHECKPOINT_KIND,),
        transport_kinds=("memory", "socket"),
        max_window_size=3,
        min_lease_ticks=2,
        max_attempts=4,
        allow_cross_transport=True,
        supports_effect_ledger=True,
    )
    offer = RecoveryPolicyOffer(
        1,
        DEFAULT_CHECKPOINT_KIND,
        "socket",
        "memory",
        policy,
        True,
    )
    try:
        assert advertisement_sender.send_advertisement(advertisement) == 1
        received_advertisement = advertisement_receiver.receive_advertisement()
        assert received_advertisement == advertisement
        assert offer_sender.send_offer(offer) == 1
        received_offer = offer_receiver.receive_offer()
        assert received_offer == offer
        agreement = negotiate_recovery_policy(received_offer, received_advertisement)
        assert agreement.reliability == ReliabilityPolicy(2, 4, 3)
        assert agreement.source_transport == "socket"
        assert agreement.target_transport == "memory"
        assert agreement.effect_ledger_required is True
        assert agreement_sender.send_agreement(agreement) == 1
        received_agreement = agreement_receiver.receive_agreement()
        assert received_agreement == agreement
        assert received_agreement.fingerprint == agreement.fingerprint
        assert type(received_agreement).from_dict(received_agreement.to_dict()) == agreement
        assert advertisement_sender.service() == (1,)
        assert offer_sender.service() == (1,)
        assert agreement_sender.service() == (1,)
    finally:
        origin_transport.close()
        receiver_transport.close()


def test_policy_channel_leaves_wrong_kind_queued_without_acknowledgement() -> None:
    """Mathematics: invalid head `F_r` leaves `Q` and `ACK(r)` unchanged until the matching parser consumes it."""

    transport = InMemoryTransport()
    policy = ReliabilityPolicy(window_size=2)
    sender = RecoveryPolicyChannel(ReliableChannel(transport, "origin", "receiver", "policy", policy))
    receiver_channel = RecoveryPolicyChannel(
        ReliableChannel(transport, "receiver", "receiver", "policy", policy, peer="origin")
    )
    offer = RecoveryPolicyOffer(1, DEFAULT_CHECKPOINT_KIND, "socket", "memory", policy)
    advertisement = advertise_recovery_policy()
    sender.send_offer(offer)
    with pytest.raises(RecoveryPolicyError, match="kind"):
        receiver_channel.receive_advertisement()
    assert receiver_channel.channel.peek() is not None
    assert sender.service() == ()
    assert receiver_channel.receive_offer() == offer
    assert sender.service() == (1,)
    assert receiver_channel.channel.next_receive_sequence == 2
    assert advertisement.protocol_version == 1


def test_policy_intersection_refuses_unsupported_or_unsafe_migration() -> None:
    """Mathematics: failure of any discrete predicate in `G=O∩A` yields refusal before state movement."""

    policy = ReliabilityPolicy(lease_ticks=1, max_attempts=3, window_size=4)
    offer = RecoveryPolicyOffer(1, DEFAULT_CHECKPOINT_KIND, "socket", "memory", policy, True)
    advertisement = advertise_recovery_policy()
    with pytest.raises(RecoveryPolicyError, match="target transport"):
        negotiate_recovery_policy(offer, replace(advertisement, transport_kinds=("socket",)))
    with pytest.raises(RecoveryPolicyError, match="checkpoint kind"):
        negotiate_recovery_policy(offer, replace(advertisement, checkpoint_kinds=("mailcpu.other.v1",)))
    with pytest.raises(RecoveryPolicyError, match="cross-transport"):
        negotiate_recovery_policy(offer, replace(advertisement, allow_cross_transport=False))
    with pytest.raises(RecoveryPolicyError, match="effect ledger"):
        negotiate_recovery_policy(offer, replace(advertisement, supports_effect_ledger=False))
    same_transport = replace(offer, source_transport="memory", target_transport="memory")
    agreement = negotiate_recovery_policy(same_transport, replace(advertisement, max_window_size=2, min_lease_ticks=2, max_attempts=2))
    assert agreement.reliability == ReliabilityPolicy(2, 2, 2)

