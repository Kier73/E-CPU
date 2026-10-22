"""Durable multi-node relay for typed hypervisor revision proposals."""

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
from .replicated_mailbox import ReplicatedMailboxError, ReplicatedMailboxNode, ReplicationReceipt
from .revision_transport import REVISION_PROPOSAL_KIND


_MAILBOX_OPERATION = "HREV"


class HypervisorRevisionRelayError(ValueError):
    """A durable revision mailbox message is malformed, misbound, or not safe to consume."""


class ReplicatedRevisionProposalRelay:
    """Carry revision proposals through one existing durable replicated mailbox."""

    def __init__(
        self,
        node: ReplicatedMailboxNode,
        mailbox: str,
        arbitration: HypervisorArbitrationLoop | None = None,
    ) -> None:
        """Mathematics: bind relay state `R=(N,a,H?)` to one durable FIFO `Q_a` without adding delivery state."""

        if not isinstance(node, ReplicatedMailboxNode):
            raise HypervisorRevisionRelayError("revision relay requires a ReplicatedMailboxNode")
        if not isinstance(mailbox, str) or not mailbox:
            raise HypervisorRevisionRelayError("revision relay mailbox must be non-empty")
        if arbitration is not None and not isinstance(arbitration, HypervisorArbitrationLoop):
            raise HypervisorRevisionRelayError("revision relay arbitration must be a HypervisorArbitrationLoop")
        self.node = node
        self.mailbox = mailbox
        self.arbitration = arbitration

    @property
    def node_id(self) -> str:
        """Mathematics: project durable sender identity `N.id` without changing mailbox state."""

        return self.node.store.node_id

    def submit(self, proposal: HypervisorRevisionProposal) -> str:
        """Mathematics: commit `ENQUEUE(o,P)` locally, replicate it, and return operation identity `o`."""

        self._validate_submission(proposal)
        operation_id, _message = self.node.send_with_operation(
            self.mailbox,
            Message(
                sender=self.node_id,
                recipient=self.mailbox,
                op=_MAILBOX_OPERATION,
                addr=self.mailbox,
                body=(REVISION_PROPOSAL_KIND, proposal.to_dict()),
            ),
        )
        return operation_id

    def receipt(self, operation_id: str) -> ReplicationReceipt:
        """Mathematics: project replicated quorum predicate `1+|A(o)|≥q` for submitted operation `o`."""

        try:
            return self.node.receipt(operation_id)
        except ReplicatedMailboxError as exc:
            raise HypervisorRevisionRelayError(str(exc)) from exc

    def receive_and_arbitrate(self) -> HypervisorRevisionArbitrationResult | None:
        """Mathematics: apply `peek(Q_a) -> RSI(P) -> CONSUME(P)` and leave `Q_a` unchanged on decode or arbitration failure."""

        if self.arbitration is None:
            raise HypervisorRevisionRelayError("revision relay has no arbitration loop")
        messages = self.node.list(self.mailbox)
        if not messages:
            return None
        message = messages[0]
        proposal = self._decode_message(message)
        result = self.arbitration.propose_revision(proposal)
        if not self.node.consume(message):
            raise HypervisorRevisionRelayError("revision mailbox message disappeared after arbitration")
        return result

    def pending(self) -> int:
        """Mathematics: expose durable FIFO cardinality `|Q_mailbox|` without changing its contents."""

        return self.node.pending(self.mailbox)

    def _validate_submission(self, proposal: HypervisorRevisionProposal) -> None:
        """Mathematics: require `proposal.source = node.id` before `ENQUEUE`, binding semantic origin to durable sender."""

        if not isinstance(proposal, HypervisorRevisionProposal):
            raise HypervisorRevisionRelayError("revision relay requires a HypervisorRevisionProposal")
        if proposal.source != self.node_id:
            raise HypervisorRevisionRelayError("proposal source does not match durable node identity")

    def _decode_message(self, message: Message) -> HypervisorRevisionProposal:
        """Mathematics: invert `body=(K,P)` only for `op=HREV`, `sender=P.source`, and the configured mailbox route."""

        if (
            not isinstance(message, Message)
            or message.sender == ""
            or message.recipient != self.mailbox
            or message.addr != self.mailbox
            or message.op != _MAILBOX_OPERATION
            or not isinstance(message.body, tuple)
            or len(message.body) != 2
            or message.body[0] != REVISION_PROPOSAL_KIND
            or not isinstance(message.body[1], Mapping)
        ):
            raise HypervisorRevisionRelayError("revision mailbox message is malformed")
        try:
            proposal = HypervisorRevisionProposal.from_dict(message.body[1])
        except (ClassifierError, KeyError, TypeError, ValueError) as exc:
            raise HypervisorRevisionRelayError(f"revision mailbox proposal is invalid: {exc}") from exc
        if proposal.source != message.sender:
            raise HypervisorRevisionRelayError("revision mailbox proposal source is not message-bound")
        return proposal
