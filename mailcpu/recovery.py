r"""Checkpoint and reconnect composition for externally connected durable peers.

Mathematics:
The recoverable communication state is the product
\[
  C=(T,R,N),
\]
where `T` is socket transport state, `R` is reliable-channel state, and `N` is
the durable mailbox coordinator state.  Rebinding a fresh socket is the
composition
\[
  B=bind(rebind(T),restore(R,T),restore(N,R)).
\]
No new delivery or authority ledger is introduced by this module.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable, Literal, Mapping

from .classifier import (
    HypervisorArbitrationEvent,
    HypervisorArbitrationLoop,
    HypervisorDomain,
    HypervisorExecutionResult,
    HypervisorRevisionArbitrationResult,
)
from .headless import HeadlessOS
from .hypervisor_transport import HypervisorOperationChannel, HypervisorOperationResultChannel
from .replicated_mailbox import ReplicatedMailboxNode, ReplicatedMailboxStore
from .reliability import ReliableChannel
from .revision_relay import ReplicatedRevisionProposalRelay
from .socket_transport import SocketTransport
from .transport import InMemoryTransport


RecoveryDirection = Literal["outbound", "inbound"]
DuplexOperationRole = Literal["origin", "executor"]


def _validate_operation_binding(
    transport: Any,
    channel: ReliableChannel,
    direction: RecoveryDirection,
    peer: str,
) -> None:
    """Mathematics: enforce `direction=outbound⇒dest=peer` and `direction=inbound⇒dest=local` before operation recovery binding."""

    if direction not in ("outbound", "inbound") or not peer:
        raise RecoveryCoordinatorError("operation binding requires a valid direction and peer")
    local = str(getattr(transport, "local_endpoint", channel.source))
    remote = str(getattr(transport, "peer_endpoint", channel.peer))
    if remote != peer or channel.source != local or channel.peer != peer:
        raise RecoveryCoordinatorError("operation transport identity does not match peer binding")
    if direction == "outbound":
        valid = channel.destination == peer
    else:
        valid = channel.destination == local
    if not valid:
        raise RecoveryCoordinatorError("operation channel direction does not match endpoint binding")


class RecoveryCoordinatorError(RuntimeError):
    """A recovery checkpoint or rebinding identity violates the composition contract."""


def _transport_peer(transport: Any, channel: ReliableChannel) -> str:
    """Mathematics: project peer identity `p(T,R)=T.peer_endpoint` for sockets, otherwise `p(T,R)=R.peer`."""

    return str(getattr(transport, "peer_endpoint", channel.peer))


@dataclass(frozen=True)
class RecoveryCheckpoint:
    """A versioned product of transport, reliable, and durable coordinator state."""

    transport: dict[str, Any]
    channel: dict[str, Any]
    node: dict[str, Any]

    @classmethod
    def capture(
        cls,
        transport: SocketTransport,
        channel: ReliableChannel,
        node: ReplicatedMailboxNode,
    ) -> "RecoveryCheckpoint":
        """Mathematics: capture `C=(T,R,N)` only when all three states share one transport and node identity."""

        if not isinstance(transport, SocketTransport):
            raise RecoveryCoordinatorError("recovery checkpoint requires a SocketTransport")
        if not isinstance(channel, ReliableChannel) or channel.transport is not transport:
            raise RecoveryCoordinatorError("recovery checkpoint channel is not bound to transport")
        if not isinstance(node, ReplicatedMailboxNode):
            raise RecoveryCoordinatorError("recovery checkpoint requires a ReplicatedMailboxNode")
        if not any(candidate is channel for candidate in (*node.outbound.values(), *node.inbound.values())):
            raise RecoveryCoordinatorError("recovery checkpoint channel is not bound to mailbox node")
        return cls(
            deepcopy(transport.snapshot()),
            deepcopy(channel.snapshot()),
            deepcopy(node.snapshot()),
        )

    @classmethod
    def from_snapshot(cls, payload: Mapping[str, Any]) -> "RecoveryCheckpoint":
        """Mathematics: reconstruct `C=(T,R,N)` only from three complete mapping factors."""

        if int(payload.get("version", 1)) != 1:
            raise RecoveryCoordinatorError("unsupported recovery checkpoint version")
        factors = {name: payload.get(name) for name in ("transport", "channel", "node")}
        if any(not isinstance(value, Mapping) for value in factors.values()):
            raise RecoveryCoordinatorError("recovery checkpoint factors must be mappings")
        return cls(
            deepcopy(dict(factors["transport"])),
            deepcopy(dict(factors["channel"])),
            deepcopy(dict(factors["node"])),
        )

    def snapshot(self) -> dict[str, object]:
        """Mathematics: serialize the product identity `C=(T,R,N)` without sharing mutable factor state."""

        return {
            "version": 1,
            "transport": deepcopy(self.transport),
            "channel": deepcopy(self.channel),
            "node": deepcopy(self.node),
        }


@dataclass(frozen=True)
class RecoveryStatus:
    """Observable recovery state spanning transport delivery, quorum, and semantic admission."""

    operation_id: str | None
    pending_sequences: tuple[int, ...]
    acknowledged_peers: tuple[str, ...]
    quorum: int
    committed: bool | None
    mailbox: str | None
    mailbox_pending: int
    semantic_result: HypervisorRevisionArbitrationResult | None

    @property
    def semantic_admitted(self) -> bool:
        """Mathematics: evaluate `admitted(P) := result(P) exists ∧ result(P).accepted` for the latest result."""

        return self.semantic_result is not None and self.semantic_result.admission.accepted


class CrossHostRecoveryCoordinator:
    """Own one rebound durable peer and expose its existing recovery transitions."""

    def __init__(
        self,
        transport: SocketTransport,
        channel: ReliableChannel,
        node: ReplicatedMailboxNode,
        relay: ReplicatedRevisionProposalRelay | None = None,
    ) -> None:
        """Mathematics: bind `B=(T,R,N,L?)` while requiring `R.transport=T`, `R∈N`, and `L.node=N`."""

        if not isinstance(transport, SocketTransport):
            raise RecoveryCoordinatorError("recovery coordinator requires a SocketTransport")
        if not isinstance(channel, ReliableChannel) or channel.transport is not transport:
            raise RecoveryCoordinatorError("recovery coordinator channel is not bound to transport")
        if not isinstance(node, ReplicatedMailboxNode):
            raise RecoveryCoordinatorError("recovery coordinator requires a ReplicatedMailboxNode")
        if not any(candidate is channel for candidate in (*node.outbound.values(), *node.inbound.values())):
            raise RecoveryCoordinatorError("recovery coordinator channel is not bound to mailbox node")
        if relay is not None and (not isinstance(relay, ReplicatedRevisionProposalRelay) or relay.node is not node):
            raise RecoveryCoordinatorError("recovery coordinator relay is not bound to mailbox node")
        self.transport = transport
        self.channel = channel
        self.node = node
        self.relay = relay
        self._last_admission: HypervisorRevisionArbitrationResult | None = None

    @staticmethod
    def checkpoint(
        transport: SocketTransport,
        channel: ReliableChannel,
        node: ReplicatedMailboxNode,
    ) -> RecoveryCheckpoint:
        """Mathematics: expose checkpoint capture as the coordinator boundary `C=(T,R,N)`."""

        return RecoveryCheckpoint.capture(transport, channel, node)

    @classmethod
    def rebind(
        cls,
        checkpoint: RecoveryCheckpoint,
        raw_socket: Any,
        store: ReplicatedMailboxStore,
        *,
        direction: RecoveryDirection,
        peer: str,
        arbitration: HypervisorArbitrationLoop | None = None,
        mailbox: str | None = None,
    ) -> "CrossHostRecoveryCoordinator":
        """Mathematics: realize `B=bind(rebind(T),restore(R,T),restore(N,R))` with checked peer direction."""

        if not isinstance(checkpoint, RecoveryCheckpoint):
            raise RecoveryCoordinatorError("rebind requires a RecoveryCheckpoint")
        if not all(callable(getattr(raw_socket, method, None)) for method in ("send", "recv", "close")):
            raise RecoveryCoordinatorError("rebind requires a connected raw socket")
        if not isinstance(store, ReplicatedMailboxStore):
            raise RecoveryCoordinatorError("rebind requires a ReplicatedMailboxStore")
        if direction not in ("outbound", "inbound") or not peer:
            raise RecoveryCoordinatorError("rebind requires a non-empty outbound or inbound peer")
        if (arbitration is None) != (mailbox is None):
            raise RecoveryCoordinatorError("arbitration and mailbox must be supplied together")
        transport: SocketTransport | None = None
        try:
            transport = SocketTransport.from_snapshot(raw_socket, deepcopy(checkpoint.transport))
            node_id = str(checkpoint.node.get("node_id", ""))
            if not node_id or transport.local_endpoint != node_id or transport.peer_endpoint != peer:
                raise RecoveryCoordinatorError("rebound transport identity does not match node and peer")
            channel = ReliableChannel.from_snapshot(deepcopy(checkpoint.channel), transport)
            if direction == "outbound":
                if (
                    channel.source != node_id
                    or channel.destination != peer
                    or channel.peer != peer
                ):
                    raise RecoveryCoordinatorError("outbound channel identity does not match node and peer")
                outbound = {peer: channel}
                inbound: dict[str, ReliableChannel] = {}
            else:
                if (
                    channel.source != node_id
                    or channel.destination != node_id
                    or channel.peer != peer
                ):
                    raise RecoveryCoordinatorError("inbound channel identity does not match node and peer")
                outbound = {}
                inbound = {peer: channel}
            restored_node = ReplicatedMailboxNode.from_snapshot(
                deepcopy(checkpoint.node),
                store,
                outbound=outbound,
                inbound=inbound,
            )
            relay = (
                ReplicatedRevisionProposalRelay(restored_node, mailbox, arbitration)
                if arbitration is not None and mailbox is not None
                else None
            )
            return cls(transport, channel, restored_node, relay)
        except Exception:
            if transport is not None:
                transport.close()
            else:
                try:
                    raw_socket.close()
                except OSError:
                    pass
            raise

    def retry(self) -> tuple[int, ...]:
        """Mathematics: advance the existing reliability clock `t:=t+1` and return sequences classified failed."""

        return self.node.tick()

    def service(self) -> int:
        """Mathematics: fold inbound frames and acknowledgements through the existing durable transition `receive→commit→ACK`."""

        return self.node.service()

    def status(self, operation_id: str | None = None, mailbox: str | None = None) -> RecoveryStatus:
        """Mathematics: report `pending`, `committed(o)`, `|Q_mailbox|`, and the latest semantic admission together."""

        acknowledged: tuple[str, ...] = ()
        committed: bool | None = None
        quorum = self.node.quorum
        if operation_id is not None:
            receipt = self.node.receipt(operation_id)
            acknowledged = receipt.acknowledged_peers
            committed = receipt.committed
            quorum = receipt.quorum
        else:
            self.node.service()
        selected_mailbox = mailbox if mailbox is not None else (self.relay.mailbox if self.relay is not None else None)
        pending = self.node.pending(selected_mailbox) if selected_mailbox is not None else 0
        return RecoveryStatus(
            operation_id,
            self.channel.pending_sequences(),
            acknowledged,
            quorum,
            committed,
            selected_mailbox,
            pending,
            self._last_admission,
        )

    def admit_next(self) -> HypervisorRevisionArbitrationResult | None:
        """Mathematics: apply the existing relay transition `peek(Q)→RSI(P)→CONSUME(P)` and remember its result."""

        if self.relay is None:
            raise RecoveryCoordinatorError("recovery coordinator has no revision relay")
        result = self.relay.receive_and_arbitrate()
        if result is not None:
            self._last_admission = result
        return result


@dataclass(frozen=True)
class OperationRecoveryCheckpoint:
    """A versioned product of operation transport, reliable FIFO, and headless hypervisor state."""

    transport: dict[str, Any]
    channel: dict[str, Any]
    operating_system: dict[str, Any]
    direction: RecoveryDirection

    @classmethod
    def capture(
        cls,
        transport: SocketTransport,
        channel: ReliableChannel,
        operating_system: HeadlessOS,
        *,
        direction: RecoveryDirection,
    ) -> "OperationRecoveryCheckpoint":
        """Mathematics: capture `C_op=(T,R,OS,d)` only when `R.transport=T` and endpoint direction binds `OS` to the peer."""

        if not isinstance(transport, SocketTransport):
            raise RecoveryCoordinatorError("operation checkpoint requires a SocketTransport")
        if not isinstance(channel, ReliableChannel) or channel.transport is not transport:
            raise RecoveryCoordinatorError("operation checkpoint channel is not bound to transport")
        if not isinstance(operating_system, HeadlessOS):
            raise RecoveryCoordinatorError("operation checkpoint requires a HeadlessOS")
        if direction not in ("outbound", "inbound"):
            raise RecoveryCoordinatorError("operation checkpoint direction is invalid")
        _validate_operation_binding(transport, channel, direction, transport.peer_endpoint)
        return cls(
            deepcopy(transport.snapshot()),
            deepcopy(channel.snapshot()),
            deepcopy(operating_system.snapshot()),
            direction,
        )

    @classmethod
    def from_snapshot(cls, payload: Mapping[str, Any]) -> "OperationRecoveryCheckpoint":
        """Mathematics: reconstruct `C_op` only from complete mapping factors and one valid direction value."""

        if int(payload.get("version", 1)) != 1:
            raise RecoveryCoordinatorError("unsupported operation recovery checkpoint version")
        transport = payload.get("transport")
        channel = payload.get("channel")
        operating_system = payload.get("operating_system")
        direction = str(payload.get("direction", ""))
        if (
            not isinstance(transport, Mapping)
            or not isinstance(channel, Mapping)
            or not isinstance(operating_system, Mapping)
            or direction not in ("outbound", "inbound")
        ):
            raise RecoveryCoordinatorError("operation recovery checkpoint is incomplete")
        return cls(deepcopy(dict(transport)), deepcopy(dict(channel)), deepcopy(dict(operating_system)), direction)  # type: ignore[arg-type]

    def snapshot(self) -> dict[str, object]:
        """Mathematics: serialize `C_op=(T,R,OS,d)` without sharing mutable factor state."""

        return {
            "version": 1,
            "transport": deepcopy(self.transport),
            "channel": deepcopy(self.channel),
            "operating_system": deepcopy(self.operating_system),
            "direction": self.direction,
        }


@dataclass(frozen=True)
class OperationRecoveryStatus:
    """Observable operation-channel recovery state."""

    direction: RecoveryDirection
    peer: str
    pending_sequences: tuple[int, ...]
    next_receive_sequence: int
    failed_sequences: tuple[int, ...]


class HypervisorOperationRecoveryCoordinator:
    """Own one rebound operation peer while preserving reliable delivery and hypervisor effect identity."""

    def __init__(
        self,
        transport: SocketTransport,
        channel: ReliableChannel,
        operating_system: HeadlessOS,
        *,
        direction: RecoveryDirection,
    ) -> None:
        """Mathematics: bind `C_op=(T,R,OS,d)` with `R.transport=T` and direction-consistent endpoint identities."""

        if not isinstance(transport, SocketTransport):
            raise RecoveryCoordinatorError("operation coordinator requires a SocketTransport")
        if not isinstance(channel, ReliableChannel) or channel.transport is not transport:
            raise RecoveryCoordinatorError("operation coordinator channel is not bound to transport")
        if not isinstance(operating_system, HeadlessOS):
            raise RecoveryCoordinatorError("operation coordinator requires a HeadlessOS")
        self._validate_binding(transport, channel, direction, transport.peer_endpoint)
        self.transport = transport
        self.channel = channel
        self.operation_channel = HypervisorOperationChannel(channel)
        self.operating_system = operating_system
        self.direction = direction

    @staticmethod
    def _validate_binding(
        transport: SocketTransport,
        channel: ReliableChannel,
        direction: RecoveryDirection,
        peer: str,
    ) -> None:
        """Mathematics: delegate binding law `direction=outbound⇒dest=peer`, `direction=inbound⇒dest=local` to one validator."""

        _validate_operation_binding(transport, channel, direction, peer)

    @staticmethod
    def checkpoint(
        transport: SocketTransport,
        channel: ReliableChannel,
        operating_system: HeadlessOS,
        *,
        direction: RecoveryDirection,
    ) -> OperationRecoveryCheckpoint:
        """Mathematics: expose `capture(T,R,OS,d)` as the coordinator checkpoint boundary."""

        return OperationRecoveryCheckpoint.capture(transport, channel, operating_system, direction=direction)

    @classmethod
    def rebind(
        cls,
        checkpoint: OperationRecoveryCheckpoint,
        raw_socket: Any,
        *,
        direction: RecoveryDirection,
        peer: str,
    ) -> "HypervisorOperationRecoveryCoordinator":
        """Mathematics: realize `bind(rebind(T),restore(R,T),restore(OS))` after direction and peer validation."""

        if not isinstance(checkpoint, OperationRecoveryCheckpoint):
            raise RecoveryCoordinatorError("operation rebind requires an OperationRecoveryCheckpoint")
        if direction != checkpoint.direction:
            raise RecoveryCoordinatorError("operation rebind direction does not match checkpoint")
        if not all(callable(getattr(raw_socket, method, None)) for method in ("send", "recv", "close")):
            raise RecoveryCoordinatorError("operation rebind requires a connected raw socket")
        if not peer:
            raise RecoveryCoordinatorError("operation rebind requires a non-empty peer")
        transport: SocketTransport | None = None
        try:
            transport = SocketTransport.from_snapshot(raw_socket, deepcopy(checkpoint.transport))
            if transport.peer_endpoint != peer:
                raise RecoveryCoordinatorError("operation rebound transport peer does not match checkpoint")
            channel = ReliableChannel.from_snapshot(deepcopy(checkpoint.channel), transport)
            operating_system = HeadlessOS.from_snapshot(deepcopy(checkpoint.operating_system))
            return cls(transport, channel, operating_system, direction=direction)
        except Exception:
            if transport is not None:
                transport.close()
            else:
                try:
                    raw_socket.close()
                except OSError:
                    pass
            raise

    def retry(self) -> tuple[int, ...]:
        """Mathematics: advance reliable time `t:=t+1` and retransmit due pending operation frames."""

        if self.direction != "outbound":
            raise RecoveryCoordinatorError("only an outbound operation coordinator can retry")
        return self.channel.tick()

    def service(self) -> tuple[int, ...]:
        """Mathematics: fold transport bytes into `Q` and remove acknowledged sender frames `P:=P\\ACK` without executing operations."""

        return self.channel.process_ack()

    def send(self, event: HypervisorArbitrationEvent) -> int:
        """Mathematics: emit one outbound event frame `F_s` while retaining it in reliable pending set `P` until ACK."""

        if self.direction != "outbound":
            raise RecoveryCoordinatorError("only an outbound operation coordinator can send")
        return self.operation_channel.send(event)

    def receive_and_execute(
        self,
        pid: int,
        handlers: Mapping[HypervisorDomain | str, Callable[[], Any]],
        effect_encoder: Callable[[Any], Any] | None = None,
    ) -> HypervisorExecutionResult | None:
        """Mathematics: authorize from local `G(pid)` and apply `E[I]` before reliable consumption and ACK."""

        if self.direction != "inbound":
            raise RecoveryCoordinatorError("only an inbound operation coordinator can receive")

        def authorize(event: HypervisorArbitrationEvent) -> HypervisorArbitrationEvent:
            """Mathematics: project remote event authority through local capability relation `G(pid,resource)`."""

            return self.operating_system.hypervisor_authorize_event(pid, event)

        return self.operation_channel.receive_and_execute(
            self.operating_system.hypervisor_arbitration,
            authorize,
            handlers,
            effect_encoder,
        )

    def status(self) -> OperationRecoveryStatus:
        """Mathematics: expose `P`, receive cursor `r`, and failed set `F` for this rebound operation factor."""

        return OperationRecoveryStatus(
            self.direction,
            self.transport.peer_endpoint,
            self.channel.pending_sequences(),
            self.channel.next_receive_sequence,
            tuple(self.channel.failed_sequences),
        )


@dataclass(frozen=True)
class DuplexOperationRecoveryCheckpoint:
    """A versioned checkpoint for both reliable operation directions and their hypervisor state."""

    request_transport: dict[str, Any]
    request_channel: dict[str, Any]
    response_transport: dict[str, Any]
    response_channel: dict[str, Any]
    operating_system: dict[str, Any]
    role: DuplexOperationRole

    @classmethod
    def capture(
        cls,
        request_transport: Any,
        request_channel: ReliableChannel,
        response_transport: Any,
        response_channel: HypervisorOperationResultChannel,
        operating_system: HeadlessOS,
        *,
        role: DuplexOperationRole,
    ) -> "DuplexOperationRecoveryCheckpoint":
        """Mathematics: capture `D=(T_q,R_q,T_r,R_r,OS,S,role)` only after both direction laws and bindings hold."""

        _validate_duplex_binding(
            request_transport,
            request_channel,
            response_transport,
            response_channel,
            role,
            _transport_peer(request_transport, request_channel),
        )
        return cls(
            deepcopy(request_transport.snapshot()),
            deepcopy(request_channel.snapshot()),
            deepcopy(response_transport.snapshot()),
            deepcopy(response_channel.snapshot()),
            deepcopy(operating_system.snapshot()),
            role,
        )

    @classmethod
    def from_snapshot(cls, payload: Mapping[str, Any]) -> "DuplexOperationRecoveryCheckpoint":
        """Mathematics: reconstruct `D` only from six complete mapping factors and role `∈{origin,executor}`."""

        if int(payload.get("version", 1)) != 1:
            raise RecoveryCoordinatorError("unsupported duplex operation checkpoint version")
        request_transport = payload.get("request_transport")
        request_channel = payload.get("request_channel")
        response_transport = payload.get("response_transport")
        response_channel = payload.get("response_channel")
        operating_system = payload.get("operating_system")
        role = str(payload.get("role", ""))
        factors = (
            request_transport,
            request_channel,
            response_transport,
            response_channel,
            operating_system,
        )
        if any(not isinstance(factor, Mapping) for factor in factors) or role not in ("origin", "executor"):
            raise RecoveryCoordinatorError("duplex operation checkpoint is incomplete")
        return cls(
            deepcopy(dict(request_transport)),
            deepcopy(dict(request_channel)),
            deepcopy(dict(response_transport)),
            deepcopy(dict(response_channel)),
            deepcopy(dict(operating_system)),
            role,  # type: ignore[arg-type]
        )

    def snapshot(self) -> dict[str, object]:
        """Mathematics: serialize `D` with independent deep copies so restore cannot alias mutable factors."""

        return {
            "version": 1,
            "request_transport": deepcopy(self.request_transport),
            "request_channel": deepcopy(self.request_channel),
            "response_transport": deepcopy(self.response_transport),
            "response_channel": deepcopy(self.response_channel),
            "operating_system": deepcopy(self.operating_system),
            "role": self.role,
        }


@dataclass(frozen=True)
class DuplexOperationRecoveryStatus:
    """Observable request/response recovery state for one duplex hypervisor product."""

    role: DuplexOperationRole
    peer: str
    request_pending_sequences: tuple[int, ...]
    response_pending_sequences: tuple[int, ...]
    request_receive_sequence: int
    response_receive_sequence: int
    request_failed_sequences: tuple[int, ...]
    response_failed_sequences: tuple[int, ...]


class HypervisorOperationDuplexRecoveryCoordinator:
    """Own request and response recovery as one peer-bound hypervisor state product."""

    def __init__(
        self,
        request_transport: Any,
        request_channel: ReliableChannel,
        response_transport: Any,
        response_channel: HypervisorOperationResultChannel,
        operating_system: HeadlessOS,
        *,
        role: DuplexOperationRole,
    ) -> None:
        """Mathematics: bind `D=(T_q,R_q,T_r,R_r,OS,S,role)` and enforce reciprocal request/result directions."""

        _validate_duplex_binding(
            request_transport,
            request_channel,
            response_transport,
            response_channel,
            role,
            _transport_peer(request_transport, request_channel),
        )
        if not isinstance(operating_system, HeadlessOS):
            raise RecoveryCoordinatorError("duplex operation coordinator requires a HeadlessOS")
        self.request_transport = request_transport
        self.request_channel = request_channel
        self.request_operation = HypervisorOperationChannel(request_channel)
        self.response_transport = response_transport
        self.response_channel = response_channel
        self.operating_system = operating_system
        self.role = role

    @classmethod
    def capture(
        cls,
        request_transport: Any,
        request_channel: ReliableChannel,
        response_transport: Any,
        response_channel: HypervisorOperationResultChannel,
        operating_system: HeadlessOS,
        *,
        role: DuplexOperationRole,
    ) -> "DuplexOperationRecoveryCheckpoint":
        """Mathematics: expose the complete checkpoint boundary `capture(D)` without creating another ledger."""

        return DuplexOperationRecoveryCheckpoint.capture(
            request_transport,
            request_channel,
            response_transport,
            response_channel,
            operating_system,
            role=role,
        )

    def checkpoint(self) -> DuplexOperationRecoveryCheckpoint:
        """Mathematics: snapshot the current product `D` after socket buffers and semantic ledgers are quiescent."""

        return self.capture(
            self.request_transport,
            self.request_channel,
            self.response_transport,
            self.response_channel,
            self.operating_system,
            role=self.role,
        )

    @classmethod
    def rebind(
        cls,
        checkpoint: DuplexOperationRecoveryCheckpoint,
        request_socket: Any,
        response_socket: Any,
        *,
        role: DuplexOperationRole,
        peer: str,
    ) -> "HypervisorOperationDuplexRecoveryCoordinator":
        """Mathematics: realize `bind(rebind(T_q),restore(R_q),rebind(T_r),restore(R_r,S),restore(OS))` after identity checks."""

        if not isinstance(checkpoint, DuplexOperationRecoveryCheckpoint):
            raise RecoveryCoordinatorError("duplex rebind requires a DuplexOperationRecoveryCheckpoint")
        if role != checkpoint.role:
            raise RecoveryCoordinatorError("duplex rebind role does not match checkpoint")
        if not peer:
            raise RecoveryCoordinatorError("duplex rebind requires a non-empty peer")
        for raw_socket in (request_socket, response_socket):
            if not all(callable(getattr(raw_socket, method, None)) for method in ("send", "recv", "close")):
                raise RecoveryCoordinatorError("duplex rebind requires two connected raw sockets")
        if request_socket is response_socket:
            raise RecoveryCoordinatorError("duplex rebind requires independent request and response sockets")
        request_transport: SocketTransport | None = None
        response_transport: SocketTransport | None = None
        try:
            request_transport = SocketTransport.from_snapshot(request_socket, deepcopy(checkpoint.request_transport))
            response_transport = SocketTransport.from_snapshot(response_socket, deepcopy(checkpoint.response_transport))
            if request_transport.peer_endpoint != peer or response_transport.peer_endpoint != peer:
                raise RecoveryCoordinatorError("duplex rebound transport peer does not match checkpoint")
            request_channel = ReliableChannel.from_snapshot(deepcopy(checkpoint.request_channel), request_transport)
            response_channel = HypervisorOperationResultChannel.from_snapshot(
                deepcopy(checkpoint.response_channel),
                response_transport,
            )
            operating_system = HeadlessOS.from_snapshot(deepcopy(checkpoint.operating_system))
            return cls(
                request_transport,
                request_channel,
                response_transport,
                response_channel,
                operating_system,
                role=role,
            )
        except Exception:
            for transport in (request_transport, response_transport):
                if transport is not None:
                    transport.close()
            if request_transport is None:
                try:
                    request_socket.close()
                except OSError:
                    pass
            if response_transport is None:
                try:
                    response_socket.close()
                except OSError:
                    pass
            raise

    def retry(self) -> tuple[int, ...]:
        """Mathematics: advance `t:=t+1` and retransmit only the product's outbound reliable factor."""

        if self.role == "origin":
            return self.request_channel.tick()
        return self.response_channel.channel.tick()

    def service(self) -> tuple[int, ...]:
        """Mathematics: remove `ACK(s)` from the role's outbound pending set without executing a second effect."""

        if self.role == "origin":
            return self.request_channel.process_ack()
        return self.response_channel.channel.process_ack()

    def send(self, event: HypervisorArbitrationEvent) -> int:
        """Mathematics: origin transition `F_s := send(event)` retains the request until `ACK(s)` is serviced."""

        if self.role != "origin":
            raise RecoveryCoordinatorError("only an origin duplex coordinator can send")
        return self.request_operation.send(event)

    def receive_and_reply(
        self,
        pid: int,
        handlers: Mapping[HypervisorDomain | str, Callable[[], Any]],
        effect_encoder: Callable[[Any], Any] | None = None,
    ) -> HypervisorExecutionResult | None:
        """Mathematics: executor transition `peek(request)→authorize→execute/replay→send(result)→ACK(request)`."""

        if self.role != "executor":
            raise RecoveryCoordinatorError("only an executor duplex coordinator can receive operations")

        def authorize(event: HypervisorArbitrationEvent) -> HypervisorArbitrationEvent:
            """Mathematics: replace remote authority with local capability projection `G(pid,resource)` while preserving `I(e)` and time."""

            return self.operating_system.hypervisor_authorize_event(pid, event)

        return self.request_operation.receive_and_reply(
            self.operating_system.hypervisor_arbitration,
            authorize,
            handlers,
            self.response_channel,
            effect_encoder,
        )

    def receive_result(self) -> HypervisorExecutionResult | None:
        """Mathematics: origin transition `peek(result)→semantic ledger→consume(result)→ACK(result)` returns one canonical effect."""

        if self.role != "origin":
            raise RecoveryCoordinatorError("only an origin duplex coordinator can receive results")
        return self.response_channel.receive()

    def status(self) -> DuplexOperationRecoveryStatus:
        """Mathematics: expose both pending domains, FIFO cursors, and failed sets without changing `D`."""

        return DuplexOperationRecoveryStatus(
            self.role,
            _transport_peer(self.request_transport, self.request_channel),
            self.request_channel.pending_sequences(),
            self.response_channel.channel.pending_sequences(),
            self.request_channel.next_receive_sequence,
            self.response_channel.channel.next_receive_sequence,
            tuple(self.request_channel.failed_sequences),
            tuple(self.response_channel.channel.failed_sequences),
        )


def _validate_duplex_binding(
    request_transport: Any,
    request_channel: ReliableChannel,
    response_transport: Any,
    response_channel: HypervisorOperationResultChannel,
    role: DuplexOperationRole,
    peer: str,
) -> None:
    """Mathematics: enforce reciprocal bindings `R_q` and `R_r` share `(local,peer)` and reverse direction by role."""

    supported = (SocketTransport, InMemoryTransport)
    if not isinstance(request_transport, supported) or not isinstance(response_transport, supported):
        raise RecoveryCoordinatorError("duplex binding requires supported transport substrates")
    if request_transport is response_transport and not isinstance(request_transport, InMemoryTransport):
        raise RecoveryCoordinatorError("socket duplex binding requires independent request and response transports")
    if not isinstance(request_channel, ReliableChannel) or request_channel.transport is not request_transport:
        raise RecoveryCoordinatorError("duplex request channel is not bound to request transport")
    if not isinstance(response_channel, HypervisorOperationResultChannel) or response_channel.channel.transport is not response_transport:
        raise RecoveryCoordinatorError("duplex response channel is not bound to response transport")
    if role not in ("origin", "executor") or not peer:
        raise RecoveryCoordinatorError("duplex binding requires role and peer")
    request_local = str(getattr(request_transport, "local_endpoint", request_channel.source))
    response_local = str(getattr(response_transport, "local_endpoint", response_channel.channel.source))
    request_peer = _transport_peer(request_transport, request_channel)
    response_peer = _transport_peer(response_transport, response_channel.channel)
    if request_local != response_local or request_peer != response_peer or request_peer != peer:
        raise RecoveryCoordinatorError("duplex transports do not share local and peer identities")
    request_direction: RecoveryDirection = "outbound" if role == "origin" else "inbound"
    response_direction: RecoveryDirection = "inbound" if role == "origin" else "outbound"
    _validate_operation_binding(request_transport, request_channel, request_direction, peer)
    _validate_operation_binding(response_transport, response_channel.channel, response_direction, peer)
    expected_source = request_channel.source if role == "origin" else request_channel.peer
    if response_channel.operation_source != expected_source or response_channel.operation_channel != request_channel.channel:
        raise RecoveryCoordinatorError("duplex response identity does not match request operation identity")


@dataclass(frozen=True)
class PeerRecoveryCheckpoint:
    """One peer factor in a multi-peer recovery product."""

    peer: str
    direction: RecoveryDirection
    transport: dict[str, Any]
    channel: dict[str, Any]

    def snapshot(self) -> dict[str, object]:
        """Mathematics: serialize peer factor `(p,d,T_p,R_p)` without sharing mutable snapshot state."""

        return {
            "peer": self.peer,
            "direction": self.direction,
            "transport": deepcopy(self.transport),
            "channel": deepcopy(self.channel),
        }


@dataclass(frozen=True)
class MultiPeerRecoveryCheckpoint:
    """A product checkpoint for one durable node and every externally bound peer."""

    node: dict[str, Any]
    peers: tuple[PeerRecoveryCheckpoint, ...]

    @classmethod
    def capture(
        cls,
        transports: Mapping[str, SocketTransport],
        channels: Mapping[str, ReliableChannel],
        node: ReplicatedMailboxNode,
        directions: Mapping[str, RecoveryDirection],
    ) -> "MultiPeerRecoveryCheckpoint":
        """Mathematics: capture `C_multi=(N,{(p,d,T_p,R_p)}_p)` with one-to-one peer factors bound to `N`."""

        if not isinstance(node, ReplicatedMailboxNode):
            raise RecoveryCoordinatorError("multi-peer checkpoint requires a ReplicatedMailboxNode")
        peers = set(transports) | set(channels) | set(directions)
        if not peers:
            raise RecoveryCoordinatorError("multi-peer checkpoint requires at least one peer")
        if set(transports) != peers or set(channels) != peers or set(directions) != peers:
            raise RecoveryCoordinatorError("multi-peer checkpoint peer factors must have equal domains")
        node_id = node.store.node_id
        factors: list[PeerRecoveryCheckpoint] = []
        for peer in sorted(peers):
            transport = transports[peer]
            channel = channels[peer]
            direction = directions[peer]
            if not isinstance(transport, SocketTransport) or not isinstance(channel, ReliableChannel):
                raise RecoveryCoordinatorError(f"invalid recovery factor for peer {peer}")
            if channel.transport is not transport:
                raise RecoveryCoordinatorError(f"channel transport mismatch for peer {peer}")
            if transport.local_endpoint != node_id or transport.peer_endpoint != peer:
                raise RecoveryCoordinatorError(f"transport identity mismatch for peer {peer}")
            if direction == "outbound":
                if (
                    node.outbound.get(peer) is not channel
                    or channel.source != node_id
                    or channel.destination != peer
                    or channel.peer != peer
                ):
                    raise RecoveryCoordinatorError(f"outbound channel identity mismatch for peer {peer}")
            elif direction == "inbound":
                if (
                    node.inbound.get(peer) is not channel
                    or channel.source != node_id
                    or channel.destination != node_id
                    or channel.peer != peer
                ):
                    raise RecoveryCoordinatorError(f"inbound channel identity mismatch for peer {peer}")
            else:
                raise RecoveryCoordinatorError(f"invalid recovery direction for peer {peer}")
            factors.append(
                PeerRecoveryCheckpoint(
                    peer,
                    direction,
                    deepcopy(transport.snapshot()),
                    deepcopy(channel.snapshot()),
                )
            )
        return cls(deepcopy(node.snapshot()), tuple(factors))

    @classmethod
    def from_snapshot(cls, payload: Mapping[str, Any]) -> "MultiPeerRecoveryCheckpoint":
        """Mathematics: reconstruct `C_multi` from one node factor and a unique finite peer-factor relation."""

        if int(payload.get("version", 1)) != 1:
            raise RecoveryCoordinatorError("unsupported multi-peer recovery checkpoint version")
        raw_node = payload.get("node")
        raw_peers = payload.get("peers")
        if not isinstance(raw_node, Mapping) or not isinstance(raw_peers, (list, tuple)) or not raw_peers:
            raise RecoveryCoordinatorError("multi-peer recovery checkpoint is incomplete")
        factors: list[PeerRecoveryCheckpoint] = []
        seen: set[str] = set()
        for raw_peer in raw_peers:
            if not isinstance(raw_peer, Mapping):
                raise RecoveryCoordinatorError("multi-peer recovery peer factor is malformed")
            peer = str(raw_peer.get("peer", ""))
            direction = str(raw_peer.get("direction", ""))
            transport = raw_peer.get("transport")
            channel = raw_peer.get("channel")
            if (
                not peer
                or peer in seen
                or direction not in ("outbound", "inbound")
                or not isinstance(transport, Mapping)
                or not isinstance(channel, Mapping)
            ):
                raise RecoveryCoordinatorError("multi-peer recovery peer factor identity is invalid")
            seen.add(peer)
            factors.append(
                PeerRecoveryCheckpoint(
                    peer,
                    direction,  # type: ignore[arg-type]
                    deepcopy(dict(transport)),
                    deepcopy(dict(channel)),
                )
            )
        return cls(deepcopy(dict(raw_node)), tuple(sorted(factors, key=lambda factor: factor.peer)))

    def snapshot(self) -> dict[str, object]:
        """Mathematics: serialize `C_multi=(N,{factor_p})` with deterministic peer ordering."""

        return {
            "version": 1,
            "node": deepcopy(self.node),
            "peers": [factor.snapshot() for factor in sorted(self.peers, key=lambda item: item.peer)],
        }


@dataclass(frozen=True)
class MultiPeerRecoveryStatus:
    """Observable multi-peer pending, acknowledgement, quorum, mailbox, and semantic state."""

    operation_id: str | None
    pending_by_peer: tuple[tuple[str, tuple[int, ...]], ...]
    acknowledged_peers: tuple[str, ...]
    quorum: int
    committed: bool | None
    mailbox: str | None
    mailbox_pending: int
    semantic_result: HypervisorRevisionArbitrationResult | None

    @property
    def pending_sequences(self) -> dict[str, tuple[int, ...]]:
        """Mathematics: project the peer relation `P={peer↦sort(dom(P_peer))}` as a fresh immutable-valued mapping."""

        return dict(self.pending_by_peer)

    @property
    def semantic_admitted(self) -> bool:
        """Mathematics: evaluate `admitted(P) := result(P) exists ∧ result(P).accepted` for the latest result."""

        return self.semantic_result is not None and self.semantic_result.admission.accepted


class CrossHostMultiPeerRecoveryCoordinator:
    """Own every rebound peer channel of one durable node while preserving its existing quorum algebra."""

    def __init__(
        self,
        transports: Mapping[str, SocketTransport],
        channels: Mapping[str, ReliableChannel],
        node: ReplicatedMailboxNode,
        relay: ReplicatedRevisionProposalRelay | None = None,
    ) -> None:
        """Mathematics: bind `M=(N,{(T_p,R_p)}_p,L?)` with equal peer domains and `R_p.transport=T_p` for all `p`."""

        if not isinstance(node, ReplicatedMailboxNode):
            raise RecoveryCoordinatorError("multi-peer coordinator requires a ReplicatedMailboxNode")
        if not transports or set(transports) != set(channels):
            raise RecoveryCoordinatorError("multi-peer coordinator transport and channel domains must match")
        for peer in sorted(transports):
            transport = transports[peer]
            channel = channels[peer]
            if not isinstance(transport, SocketTransport) or not isinstance(channel, ReliableChannel):
                raise RecoveryCoordinatorError(f"invalid multi-peer binding for peer {peer}")
            if channel.transport is not transport:
                raise RecoveryCoordinatorError(f"multi-peer channel transport mismatch for peer {peer}")
            if node.outbound.get(peer) is not channel and node.inbound.get(peer) is not channel:
                raise RecoveryCoordinatorError(f"multi-peer channel is not bound to node for peer {peer}")
        if relay is not None and (not isinstance(relay, ReplicatedRevisionProposalRelay) or relay.node is not node):
            raise RecoveryCoordinatorError("multi-peer coordinator relay is not bound to mailbox node")
        self.transports = dict(transports)
        self.channels = dict(channels)
        self.node = node
        self.relay = relay
        self._last_admission: HypervisorRevisionArbitrationResult | None = None

    @staticmethod
    def checkpoint(
        transports: Mapping[str, SocketTransport],
        channels: Mapping[str, ReliableChannel],
        node: ReplicatedMailboxNode,
        directions: Mapping[str, RecoveryDirection],
    ) -> MultiPeerRecoveryCheckpoint:
        """Mathematics: expose multi-peer checkpoint capture as `C_multi=(N,{factor_p})`."""

        return MultiPeerRecoveryCheckpoint.capture(transports, channels, node, directions)

    @classmethod
    def rebind(
        cls,
        checkpoint: MultiPeerRecoveryCheckpoint,
        raw_sockets: Mapping[str, Any],
        store: ReplicatedMailboxStore,
        *,
        arbitration: HypervisorArbitrationLoop | None = None,
        mailbox: str | None = None,
    ) -> "CrossHostMultiPeerRecoveryCoordinator":
        """Mathematics: realize `M=bind(N,{rebind(T_p),restore(R_p,T_p)}_p)` only after every peer factor validates."""

        if not isinstance(checkpoint, MultiPeerRecoveryCheckpoint):
            raise RecoveryCoordinatorError("multi-peer rebind requires a MultiPeerRecoveryCheckpoint")
        if not isinstance(store, ReplicatedMailboxStore):
            raise RecoveryCoordinatorError("multi-peer rebind requires a ReplicatedMailboxStore")
        expected = {factor.peer for factor in checkpoint.peers}
        if set(raw_sockets) != expected:
            raise RecoveryCoordinatorError("multi-peer rebind socket domain does not match checkpoint peers")
        if (arbitration is None) != (mailbox is None):
            raise RecoveryCoordinatorError("arbitration and mailbox must be supplied together")
        transports: dict[str, SocketTransport] = {}
        channels: dict[str, ReliableChannel] = {}
        try:
            node_id = str(checkpoint.node.get("node_id", ""))
            if not node_id:
                raise RecoveryCoordinatorError("multi-peer checkpoint has no node identity")
            for factor in sorted(checkpoint.peers, key=lambda item: item.peer):
                raw_socket = raw_sockets[factor.peer]
                if not all(callable(getattr(raw_socket, method, None)) for method in ("send", "recv", "close")):
                    raise RecoveryCoordinatorError(f"peer {factor.peer} is not a connected raw socket")
                transport = SocketTransport.from_snapshot(raw_socket, deepcopy(factor.transport))
                transports[factor.peer] = transport
                if transport.local_endpoint != node_id or transport.peer_endpoint != factor.peer:
                    raise RecoveryCoordinatorError(f"rebound transport identity mismatch for peer {factor.peer}")
                channel = ReliableChannel.from_snapshot(deepcopy(factor.channel), transport)
                if factor.direction == "outbound":
                    valid = (
                        channel.source == node_id
                        and channel.destination == factor.peer
                        and channel.peer == factor.peer
                    )
                else:
                    valid = (
                        channel.source == node_id
                        and channel.destination == node_id
                        and channel.peer == factor.peer
                    )
                if not valid:
                    raise RecoveryCoordinatorError(f"rebound channel identity mismatch for peer {factor.peer}")
                channels[factor.peer] = channel
            outbound = {
                factor.peer: channels[factor.peer]
                for factor in checkpoint.peers
                if factor.direction == "outbound"
            }
            inbound = {
                factor.peer: channels[factor.peer]
                for factor in checkpoint.peers
                if factor.direction == "inbound"
            }
            node = ReplicatedMailboxNode.from_snapshot(
                deepcopy(checkpoint.node),
                store,
                outbound=outbound,
                inbound=inbound,
            )
            relay = (
                ReplicatedRevisionProposalRelay(node, mailbox, arbitration)
                if arbitration is not None and mailbox is not None
                else None
            )
            return cls(transports, channels, node, relay)
        except Exception:
            for transport in transports.values():
                transport.close()
            for peer, raw_socket in raw_sockets.items():
                if peer not in transports:
                    try:
                        raw_socket.close()
                    except OSError:
                        pass
            raise

    def retry(self) -> tuple[int, ...]:
        """Mathematics: advance every outbound lease `t_p:=t_p+1` and return the union of failed peer sequences."""

        return self.node.tick()

    def service(self) -> int:
        """Mathematics: fold all inbound frames and acknowledgement queues through the existing durable node transition."""

        return self.node.service()

    def status(self, operation_id: str | None = None, mailbox: str | None = None) -> MultiPeerRecoveryStatus:
        """Mathematics: report `P_p`, `A(o)`, `1+|A(o)|≥q`, `|Q_mailbox|`, and the latest semantic result."""

        acknowledged: tuple[str, ...] = ()
        committed: bool | None = None
        quorum = self.node.quorum
        if operation_id is not None:
            receipt = self.node.receipt(operation_id)
            acknowledged = receipt.acknowledged_peers
            committed = receipt.committed
            quorum = receipt.quorum
        else:
            self.node.service()
        selected_mailbox = mailbox if mailbox is not None else (self.relay.mailbox if self.relay is not None else None)
        pending = self.node.pending(selected_mailbox) if selected_mailbox is not None else 0
        return MultiPeerRecoveryStatus(
            operation_id,
            tuple((peer, self.channels[peer].pending_sequences()) for peer in sorted(self.channels)),
            acknowledged,
            quorum,
            committed,
            selected_mailbox,
            pending,
            self._last_admission,
        )

    def admit_next(self) -> HypervisorRevisionArbitrationResult | None:
        """Mathematics: apply the existing relay transition `peek(Q)→RSI(P)→CONSUME(P)` once on the restored node."""

        if self.relay is None:
            raise RecoveryCoordinatorError("multi-peer coordinator has no revision relay")
        result = self.relay.receive_and_arbitrate()
        if result is not None:
            self._last_admission = result
        return result
