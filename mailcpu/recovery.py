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
from typing import Any, Literal, Mapping

from .classifier import HypervisorArbitrationLoop, HypervisorRevisionArbitrationResult
from .replicated_mailbox import ReplicatedMailboxNode, ReplicatedMailboxStore
from .reliability import ReliableChannel
from .revision_relay import ReplicatedRevisionProposalRelay
from .socket_transport import SocketTransport


RecoveryDirection = Literal["outbound", "inbound"]


class RecoveryCoordinatorError(RuntimeError):
    """A recovery checkpoint or rebinding identity violates the composition contract."""


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
