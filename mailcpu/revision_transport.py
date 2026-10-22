"""Reliable transport adapter for checkpointable hypervisor revision proposals."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .classifier import (
    ClassifierError,
    HypervisorArbitrationLoop,
    HypervisorRevisionArbitrationResult,
    HypervisorRevisionProposal,
)
from .model import Message
from .reliability import ReliableChannel


_WIRE_KIND = "mailcpu.hypervisor.revision.proposal"


class HypervisorRevisionTransportError(ValueError):
    """A revision proposal is malformed, misbound, or not safe to acknowledge."""


class HypervisorRevisionChannel:
    """Carry revision proposals through one existing reliable, ordered channel."""

    def __init__(self, channel: ReliableChannel) -> None:
        """Mathematics: bind proposal stream `S` to reliable channel identity `(source,peer,channel)` without adding a second delivery ledger."""

        if not isinstance(channel, ReliableChannel):
            raise HypervisorRevisionTransportError("revision transport requires a ReliableChannel")
        self.channel = channel

    def send(self, proposal: HypervisorRevisionProposal) -> int:
        """Mathematics: encode `P` as one reliable payload `RDATA(kind,P)` and return its transport sequence."""

        if not isinstance(proposal, HypervisorRevisionProposal):
            raise HypervisorRevisionTransportError("revision transport requires a HypervisorRevisionProposal")
        if proposal.source != self.channel.source or proposal.channel != self.channel.channel:
            raise HypervisorRevisionTransportError("proposal identity does not match reliable channel source or channel")
        return self.channel.send({"kind": _WIRE_KIND, "proposal": proposal.to_dict()})

    def receive(self) -> HypervisorRevisionProposal | None:
        """Mathematics: validate `P` while it is peeked, then consume and acknowledge it only when `decode(P)` succeeds."""

        peeked = self.channel.peek()
        if peeked is None:
            return None
        transport_sequence, payload = peeked
        proposal = self._decode_payload(payload)
        received = self.channel.receive()
        if received is None:
            return None
        if received[0] != transport_sequence:
            raise HypervisorRevisionTransportError("revision transport receive sequence changed during validation")
        return proposal

    def receive_and_arbitrate(
        self,
        arbitration: HypervisorArbitrationLoop,
    ) -> HypervisorRevisionArbitrationResult | None:
        """Mathematics: apply `R_r:=RSI_r(R_r,P)` while `F_s∈Q`, then consume and acknowledge `F_s` only after a typed result exists."""

        if not isinstance(arbitration, HypervisorArbitrationLoop):
            raise HypervisorRevisionTransportError("revision transport requires a HypervisorArbitrationLoop")
        peeked = self.channel.peek()
        if peeked is None:
            return None
        transport_sequence, payload = peeked
        proposal = self._decode_payload(payload)
        result = arbitration.propose_revision(proposal)
        received = self.channel.receive()
        if received is None or received[0] != transport_sequence:
            raise HypervisorRevisionTransportError("revision transport frame disappeared after arbitration")
        return result

    def _decode_payload(self, payload: Any) -> HypervisorRevisionProposal:
        """Mathematics: invert wire relation `W=(kind,proposal)` only for the expected kind and peer-bound identity."""

        if not isinstance(payload, Mapping) or payload.get("kind") != _WIRE_KIND:
            raise HypervisorRevisionTransportError("revision payload kind is invalid")
        raw_proposal = payload.get("proposal")
        if not isinstance(raw_proposal, Mapping):
            raise HypervisorRevisionTransportError("revision payload proposal is not a mapping")
        try:
            proposal = HypervisorRevisionProposal.from_dict(raw_proposal)
        except (ClassifierError, TypeError, ValueError) as exc:
            raise HypervisorRevisionTransportError(f"revision payload is invalid: {exc}") from exc
        if proposal.source != self.channel.peer or proposal.channel != self.channel.channel:
            raise HypervisorRevisionTransportError("revision payload source or channel is not peer-bound")
        return proposal

