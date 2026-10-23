"""Durable fixed-membership seed commits over reliable peer channels."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
import math
import time
from typing import Any, Mapping

from .durable_seed_commit import DurableSeedCommitJournal
from .headless import HeadlessOS
from .reliability import ReliableChannel
from .seed import SeedEnvelopeError, SeedNavigationError, SystemSeed
from .seed_admission import SeedAdmissionError
from .seed_commit_quorum import (
    DurableSeedCommitLedger,
    SeedCommitCertificate,
    SeedCommitDecision,
    SeedCommitMembership,
    SeedCommitProposal,
    SeedCommitTransitionArtifact,
    SeedPrepareVote,
)
from .seed_commit_transport import (
    HypervisorSeedCommitChannel,
    HypervisorSeedCommitResultChannel,
    SeedCommitRequest,
    SeedCommitResult,
    SeedCommitTransportError,
    _frontier_digest,
)
from .socket_transport import SocketTransport


SEED_QUORUM_REQUEST_CHANNEL = "seed.commit.quorum.request"
SEED_QUORUM_RESPONSE_CHANNEL = "seed.commit.quorum.response"
SEED_QUORUM_PREPARE_KIND = "mailcpu.hypervisor.seed.quorum.prepare"
SEED_QUORUM_VOTE_KIND = "mailcpu.hypervisor.seed.quorum.vote"
SEED_QUORUM_COMMIT_KIND = "mailcpu.hypervisor.seed.quorum.commit"
SEED_QUORUM_DECISION_KIND = "mailcpu.hypervisor.seed.quorum.decision"


class SeedCommitQuorumError(RuntimeError):
    """A peer quorum could not safely prepare, decide, recover, or publish a seed transition."""


@dataclass(frozen=True)
class SeedCommitPeerLink:
    """Owner-side reliable request and response channels bound to one configured peer."""

    peer_id: str
    requests: ReliableChannel
    responses: ReliableChannel

    def __post_init__(self) -> None:
        """Mathematics: enforce peer binding `requests.peer=responses.peer=peer_id` and distinct directional FIFOs."""

        if not isinstance(self.peer_id, str) or not self.peer_id:
            raise SeedCommitQuorumError("peer link id must be non-empty")
        if not isinstance(self.requests, ReliableChannel) or not isinstance(self.responses, ReliableChannel):
            raise SeedCommitQuorumError("peer link requires reliable request and response channels")
        if self.requests.peer != self.peer_id or self.responses.peer != self.peer_id:
            raise SeedCommitQuorumError("peer link reliable channels do not match configured peer")
        if self.requests.source == self.peer_id or self.responses.source != self.peer_id:
            raise SeedCommitQuorumError("peer link channel sources are not directionally bound")
        if self.requests.destination != self.peer_id or self.responses.destination != self.requests.source:
            raise SeedCommitQuorumError("peer link channel destinations are not directionally bound")
        if self.requests.channel != SEED_QUORUM_REQUEST_CHANNEL or self.responses.channel != SEED_QUORUM_RESPONSE_CHANNEL:
            raise SeedCommitQuorumError("peer link channel names are not seed-quorum channels")


@dataclass(frozen=True)
class SeedCommitQuorumRecoveryCheckpoint:
    """One consistent owner cut across membership, durable state, host state, and every peer channel product."""

    membership: dict[str, Any]
    ledger_path: str
    ledger_state: dict[str, Any]
    publication_state: dict[str, Any]
    operating_system: dict[str, Any]
    peer_links: tuple[dict[str, Any], ...]
    retry_interval: float

    def __post_init__(self) -> None:
        """Mathematics: require all captured factors to project the same owner `O`, membership `M`, and committed host digest."""

        membership = SeedCommitMembership.from_snapshot(self.membership)
        if not isinstance(self.ledger_path, str) or not self.ledger_path:
            raise SeedCommitQuorumError("quorum checkpoint ledger path must be non-empty")
        if not isinstance(self.ledger_state, Mapping) or not isinstance(self.publication_state, Mapping):
            raise SeedCommitQuorumError("quorum checkpoint durable states must be mappings")
        if not isinstance(self.operating_system, Mapping):
            raise SeedCommitQuorumError("quorum checkpoint host snapshot must be a mapping")
        if not isinstance(self.peer_links, (list, tuple)):
            raise SeedCommitQuorumError("quorum checkpoint peer links must be a finite sequence")
        if (
            not isinstance(self.retry_interval, (int, float))
            or isinstance(self.retry_interval, bool)
            or not math.isfinite(self.retry_interval)
            or self.retry_interval <= 0
        ):
            raise SeedCommitQuorumError("quorum checkpoint retry interval must be finite and positive")
        if (
            self.ledger_state.get("member_id") != membership.owner_id
            or self.ledger_state.get("membership_digest") != membership.digest
            or self.publication_state.get("executor_id") != membership.owner_id
        ):
            raise SeedCommitQuorumError("quorum checkpoint durable identities do not match membership owner")
        if self.publication_state.get("path") is None:
            raise SeedCommitQuorumError("quorum checkpoint publication journal path is missing")
        host = HeadlessOS.from_snapshot(deepcopy(dict(self.operating_system)))
        host_digest = SystemSeed.from_system(host).origin_digest
        committed = self.ledger_state.get("committed_state")
        expected_digest = membership.genesis_state_digest
        if committed is not None:
            if not isinstance(committed, Mapping):
                raise SeedCommitQuorumError("quorum checkpoint committed head is malformed")
            expected_digest = committed.get("state_digest")
            committed_slot = committed.get("slot")
            published_operations = self.publication_state.get("operations")
            if (
                not isinstance(committed_slot, int)
                or isinstance(committed_slot, bool)
                or not isinstance(published_operations, int)
                or isinstance(published_operations, bool)
                or published_operations not in (committed_slot, committed_slot - 1)
            ):
                raise SeedCommitQuorumError("quorum checkpoint publication and decision slots are not adjacent")
            if published_operations == committed_slot and host_digest != expected_digest:
                raise SeedCommitQuorumError("published checkpoint host does not match the committed ledger head")
        elif self.publication_state.get("operations") != 0 or host_digest != membership.genesis_state_digest:
            raise SeedCommitQuorumError("uncommitted checkpoint host does not match the membership genesis state")
        normalized_links = tuple(deepcopy(dict(link)) for link in self.peer_links)
        peer_ids: list[str] = []
        required_fields = {"peer_id", "transport", "requests", "responses"}
        for link in normalized_links:
            if set(link) != required_fields or not isinstance(link.get("peer_id"), str):
                raise SeedCommitQuorumError("quorum checkpoint peer link fields are malformed")
            peer = link["peer_id"]
            peer_ids.append(peer)
            transport = link.get("transport")
            requests = link.get("requests")
            responses = link.get("responses")
            if not all(isinstance(value, Mapping) for value in (transport, requests, responses)):
                raise SeedCommitQuorumError("quorum checkpoint peer factors must be mappings")
            if transport.get("local_endpoint") != membership.owner_id or transport.get("peer_endpoint") != peer:
                raise SeedCommitQuorumError("quorum checkpoint transport endpoints do not match peer identity")
        expected_peers = set(membership.member_ids) - {membership.owner_id}
        if len(peer_ids) != len(set(peer_ids)) or not set(peer_ids).issubset(expected_peers):
            raise SeedCommitQuorumError("quorum checkpoint peer domain is not a subset of fixed membership")
        object.__setattr__(self, "membership", deepcopy(dict(self.membership)))
        object.__setattr__(self, "ledger_state", deepcopy(dict(self.ledger_state)))
        object.__setattr__(self, "publication_state", deepcopy(dict(self.publication_state)))
        object.__setattr__(self, "operating_system", deepcopy(dict(self.operating_system)))
        object.__setattr__(self, "peer_links", normalized_links)

    @classmethod
    def capture(cls, coordinator: "SeedCommitQuorumCoordinator") -> "SeedCommitQuorumRecoveryCheckpoint":
        """Mathematics: capture cut `C=(M,L,J,OS,{T_i,Q_i,R_i})` only when a second projection proves no factor moved."""

        if not isinstance(coordinator, SeedCommitQuorumCoordinator):
            raise SeedCommitQuorumError("quorum recovery capture requires a seed commit coordinator")

        def capture_peer_factors() -> tuple[dict[str, Any], ...]:
            """Mathematics: project each peer link as `P_i=(peer,snapshot(T_i),snapshot(Q_i),snapshot(R_i))`."""

            captured: list[dict[str, Any]] = []
            transports: set[int] = set()
            for peer in sorted(coordinator.peers):
                link = coordinator.peers[peer]
                transport = link.requests.transport
                if not isinstance(transport, SocketTransport) or link.responses.transport is not transport:
                    raise SeedCommitQuorumError("quorum checkpoint requires one shared SocketTransport per peer link")
                if id(transport) in transports:
                    raise SeedCommitQuorumError("quorum checkpoint cannot alias one socket transport across peer links")
                transports.add(id(transport))
                if transport.local_endpoint != coordinator.membership.owner_id or transport.peer_endpoint != peer:
                    raise SeedCommitQuorumError("quorum checkpoint socket endpoints do not match configured peer")
                captured.append(
                    {
                        "peer_id": peer,
                        "transport": deepcopy(transport.snapshot()),
                        "requests": deepcopy(link.requests.snapshot()),
                        "responses": deepcopy(link.responses.snapshot()),
                    }
                )
            expected_peers = set(coordinator.membership.member_ids) - {coordinator.membership.owner_id}
            if not set(coordinator.peers).issubset(expected_peers):
                raise SeedCommitQuorumError("quorum checkpoint contains a peer outside fixed membership")
            return tuple(captured)

        before = (
            deepcopy(coordinator.operating_system.snapshot()),
            deepcopy(coordinator.ledger.snapshot()),
            deepcopy(coordinator.durable_journal.snapshot()),
            deepcopy(coordinator.durable_journal.latest_state_snapshot()),
            capture_peer_factors(),
        )
        after = (
            deepcopy(coordinator.operating_system.snapshot()),
            deepcopy(coordinator.ledger.snapshot()),
            deepcopy(coordinator.durable_journal.snapshot()),
            deepcopy(coordinator.durable_journal.latest_state_snapshot()),
            capture_peer_factors(),
        )
        if before != after:
            raise SeedCommitQuorumError("quorum recovery capture crossed a moving state or channel boundary")
        if before[3] != (None if before[2]["operations"] == 0 else before[0]):
            raise SeedCommitQuorumError("owner host snapshot differs from its latest published journal state")
        return cls(
            coordinator.membership.snapshot(),
            str(coordinator.ledger.path),
            before[1],
            before[2],
            before[0],
            before[4],
            coordinator.retry_interval,
        )

    def snapshot(self) -> dict[str, Any]:
        """Mathematics: serialize the complete factor product without aliases, preserving each durable and FIFO cursor."""

        return {
            "version": 1,
            "membership": deepcopy(self.membership),
            "ledger_path": self.ledger_path,
            "ledger_state": deepcopy(self.ledger_state),
            "publication_state": deepcopy(self.publication_state),
            "operating_system": deepcopy(self.operating_system),
            "peer_links": [deepcopy(link) for link in self.peer_links],
            "retry_interval": self.retry_interval,
        }

    @classmethod
    def from_snapshot(cls, payload: Mapping[str, Any]) -> "SeedCommitQuorumRecoveryCheckpoint":
        """Mathematics: reconstruct cut `C` only when its exact versioned factors satisfy the checkpoint constructor law."""

        fields = {
            "version",
            "membership",
            "ledger_path",
            "ledger_state",
            "publication_state",
            "operating_system",
            "peer_links",
            "retry_interval",
        }
        if not isinstance(payload, Mapping) or set(payload) != fields or payload.get("version") != 1:
            raise SeedCommitQuorumError("quorum recovery checkpoint fields or version are invalid")
        if not isinstance(payload.get("peer_links"), (list, tuple)):
            raise SeedCommitQuorumError("quorum recovery checkpoint peer links are malformed")
        try:
            return cls(
                deepcopy(dict(payload["membership"])),
                payload.get("ledger_path"),
                deepcopy(dict(payload["ledger_state"])),
                deepcopy(dict(payload["publication_state"])),
                deepcopy(dict(payload["operating_system"])),
                tuple(deepcopy(dict(link)) for link in payload["peer_links"]),
                payload.get("retry_interval"),
            )
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, SeedCommitQuorumError):
                raise
            raise SeedCommitQuorumError("quorum recovery checkpoint factors are invalid") from exc

    def rebind(
        self,
        raw_sockets: Mapping[str, Any],
    ) -> "SeedCommitQuorumCoordinator":
        """Mathematics: rebuild coordinator `C` only when reopened durable prefixes equal the captured cut and all peer factors rebind."""

        membership = SeedCommitMembership.from_snapshot(self.membership)
        captured_peers = {link["peer_id"] for link in self.peer_links}
        if not isinstance(raw_sockets, Mapping) or set(raw_sockets) != captured_peers:
            raise SeedCommitQuorumError("quorum rebind sockets must exactly cover captured peer links")
        raw_socket_ids = [id(sock) for sock in raw_sockets.values()]
        if len(raw_socket_ids) != len(set(raw_socket_ids)) or any(
            not all(callable(getattr(sock, method, None)) for method in ("send", "recv", "close"))
            for sock in raw_sockets.values()
        ):
            raise SeedCommitQuorumError("quorum rebind requires distinct connected socket objects for captured peers")
        ledger = DurableSeedCommitLedger(self.ledger_path, membership.owner_id, membership)
        publication_path = self.publication_state.get("path")
        if not isinstance(publication_path, str) or not publication_path:
            raise SeedCommitQuorumError("quorum rebind publication path is invalid")
        journal = DurableSeedCommitJournal(publication_path, membership.owner_id)
        if ledger.snapshot() != self.ledger_state or journal.snapshot() != self.publication_state:
            raise SeedCommitQuorumError("durable owner ledgers differ from the captured recovery cut")
        operating_system = HeadlessOS.from_snapshot(deepcopy(self.operating_system))
        if journal.latest_state_snapshot() != (None if journal.snapshot()["operations"] == 0 else self.operating_system):
            raise SeedCommitQuorumError("owner host snapshot differs from its latest published journal state")
        committed = ledger.committed_state()
        live_digest = SystemSeed.from_system(operating_system).origin_digest
        if committed is None:
            if live_digest != membership.genesis_state_digest:
                raise SeedCommitQuorumError("rebound owner host differs from the empty-ledger genesis state")
        elif committed[0] == journal.snapshot()["operations"]:
            if live_digest != committed[1]:
                raise SeedCommitQuorumError("rebound owner host differs from the published quorum head")
        elif committed[0] == journal.snapshot()["operations"] + 1:
            pending = ledger.proposal_at(committed[0])
            if (
                pending is None
                or pending.predecessor_state_digest != live_digest
                or ledger.transition_artifact(pending) is None
            ):
                raise SeedCommitQuorumError("unpublished committed edge cannot be recovered from the checkpoint")
        else:
            raise SeedCommitQuorumError("rebound owner ledger and publication journal have a slot gap")
        restored_links: dict[str, SeedCommitPeerLink] = {}
        restored_transports: list[SocketTransport] = []
        try:
            for saved in self.peer_links:
                peer = saved["peer_id"]
                transport = SocketTransport.from_snapshot(raw_sockets[peer], deepcopy(saved["transport"]))
                restored_transports.append(transport)
                requests = ReliableChannel.from_snapshot(deepcopy(saved["requests"]), transport)
                responses = ReliableChannel.from_snapshot(deepcopy(saved["responses"]), transport)
                restored_links[peer] = SeedCommitPeerLink(peer, requests, responses)
            coordinator = SeedCommitQuorumCoordinator(
                membership,
                ledger,
                operating_system,
                journal,
                restored_links,
                retry_interval=self.retry_interval,
            )
            if (
                coordinator.operating_system.snapshot() != self.operating_system
                or coordinator.ledger.snapshot() != self.ledger_state
                or coordinator.durable_journal.snapshot() != self.publication_state
            ):
                raise SeedCommitQuorumError("rebound coordinator does not reproduce the captured owner cut")
            return coordinator
        except Exception:
            for transport in restored_transports:
                transport.close()
            for raw_socket in raw_sockets.values():
                close = getattr(raw_socket, "close", None)
                if callable(close):
                    close()
            raise


class SeedCommitQuorumParticipant:
    """Participant that fsyncs a transition artifact before voting and before acknowledging commit."""

    def __init__(
        self,
        ledger: DurableSeedCommitLedger,
        inbound: ReliableChannel,
        outbound: ReliableChannel,
        operating_system: HeadlessOS,
        durable_journal: DurableSeedCommitJournal,
    ) -> None:
        """Mathematics: bind one participant ledger to duplex peer channels and a recoverable live state `OS` with `d(OS)=ledger.head` at service start."""

        if not isinstance(ledger, DurableSeedCommitLedger):
            raise SeedCommitQuorumError("participant requires a durable seed-commit ledger")
        if not isinstance(inbound, ReliableChannel) or not isinstance(outbound, ReliableChannel):
            raise SeedCommitQuorumError("participant requires reliable duplex peer channels")
        if not isinstance(operating_system, HeadlessOS) or not isinstance(durable_journal, DurableSeedCommitJournal):
            raise SeedCommitQuorumError("participant requires a live host and durable publication journal")
        if inbound.destination != ledger.member_id or outbound.source != ledger.member_id:
            raise SeedCommitQuorumError("participant channel endpoints do not match its ledger identity")
        if inbound.channel != SEED_QUORUM_REQUEST_CHANNEL or outbound.channel != SEED_QUORUM_RESPONSE_CHANNEL:
            raise SeedCommitQuorumError("participant channel names are not seed-quorum channels")
        if inbound.peer != ledger.membership.owner_id or outbound.peer != ledger.membership.owner_id:
            raise SeedCommitQuorumError("participant channels are not bound to the configured owner")
        if durable_journal.executor_id != ledger.member_id:
            raise SeedCommitQuorumError("participant durable journal identity does not match its ledger")
        self.ledger = ledger
        self.inbound = inbound
        self.outbound = outbound
        self.operating_system = operating_system
        self.durable_journal = durable_journal
        self.retry_interval = 0.05
        self._last_retry = time.monotonic()
        self._response_sequences: dict[tuple[str, str], tuple[dict[str, Any], int]] = {}

    def service_once(self) -> bool:
        """Mathematics: process FIFO head as `durable_effect; response; ACK`; a retry repeats only idempotent ledger projections."""

        peeked = self.inbound.peek()
        self.outbound.process_ack()
        self._tick_outbound_if_due()
        if peeked is None:
            return False
        sequence, payload = peeked
        if not isinstance(payload, Mapping):
            raise SeedCommitQuorumError("peer request payload must be a mapping")

        def apply_before_ack(received_sequence: int, received_payload: Any) -> None:
            """Mathematics: execute `f(request)` before reliable receive's consume/ACK transition."""

            if received_sequence != sequence or received_payload != payload:
                raise SeedCommitQuorumError("peer request changed between validation and commit")
            kind = payload.get("kind")
            if kind == SEED_QUORUM_PREPARE_KIND:
                self._handle_prepare(payload)
            elif kind == SEED_QUORUM_COMMIT_KIND:
                self._handle_commit(payload)
            else:
                raise SeedCommitQuorumError("peer request kind is unsupported")

        self.inbound.receive(commit=apply_before_ack)
        return True

    def _handle_prepare(self, payload: Mapping[str, Any]) -> None:
        """Mathematics: validate artifact `A`, persist `PREPARE(p,A)`, then emit its exact durable vote `v_i`."""

        if set(payload) != {"kind", "proposal", "artifact"}:
            raise SeedCommitQuorumError("prepare request fields are malformed")
        proposal = SeedCommitProposal.from_snapshot(payload["proposal"])
        artifact_raw = payload["artifact"]
        if not isinstance(artifact_raw, Mapping):
            raise SeedCommitQuorumError("prepare request transition artifact is missing")
        artifact = SeedCommitTransitionArtifact.from_snapshot(artifact_raw)
        _result, _candidate = _validate_artifact(self.ledger.membership, proposal, artifact)
        existing_vote = self.ledger.prepared_vote(proposal)
        if existing_vote is None:
            live_digest = SystemSeed.from_system(self.operating_system).origin_digest
            if live_digest != proposal.predecessor_state_digest:
                raise SeedCommitQuorumError("participant live state does not match proposal predecessor")
        vote = self.ledger.prepare(proposal, artifact)
        self._send_response(
            {
                "kind": SEED_QUORUM_VOTE_KIND,
                "proposal_digest": proposal.digest,
                "artifact_digest": artifact.digest,
                "vote": vote.snapshot(),
            }
        )

    def _handle_commit(self, payload: Mapping[str, Any]) -> None:
        """Mathematics: append local `COMMIT(p,C)`, persist the bound result/state, publish it, then emit decision evidence."""

        if set(payload) != {"kind", "proposal", "certificate"}:
            raise SeedCommitQuorumError("commit request fields are malformed")
        proposal = SeedCommitProposal.from_snapshot(payload["proposal"])
        certificate_raw = payload["certificate"]
        if not isinstance(certificate_raw, Mapping):
            raise SeedCommitQuorumError("commit request certificate is malformed")
        certificate = SeedCommitCertificate.from_snapshot(certificate_raw)
        artifact = self.ledger.transition_artifact(proposal)
        if artifact is None:
            raise SeedCommitQuorumError("participant has no durable artifact for this proposal")
        result, candidate = _validate_artifact(self.ledger.membership, proposal, artifact)
        decision = self.ledger.commit(proposal, certificate)
        self._publish(proposal, result, candidate)
        self._send_response(
            {
                "kind": SEED_QUORUM_DECISION_KIND,
                "proposal_digest": proposal.digest,
                "decision": decision.snapshot(),
            }
        )

    def _publish(
        self,
        proposal: SeedCommitProposal,
        result: SeedCommitResult,
        candidate: HeadlessOS,
    ) -> None:
        """Mathematics: fsync `J=(identity,f,result,candidate)` before replaying the admitted input into live `OS`."""

        latest = self.ledger.committed_state()
        if latest is None or latest[0] < proposal.slot:
            raise SeedCommitQuorumError("participant publication requires its durable commit decision")
        if latest[0] > proposal.slot:
            return
        if latest[1] != proposal.result_state_digest:
            raise SeedCommitQuorumError("participant latest committed digest conflicts with publication artifact")
        identity = (result.request_source, result.request_channel, result.request_sequence)
        self.durable_journal.record(identity, result.request_fingerprint, result, candidate)
        _install_seed_transition(self.operating_system, proposal, result, candidate)

    def _send_response(self, payload: Mapping[str, Any]) -> None:
        """Mathematics: preserve one sequence per `(proposal,phase)`; retransmit pending identity or do nothing after its ACK."""

        normalized = dict(payload)
        proposal_digest = normalized.get("proposal_digest")
        kind = normalized.get("kind")
        if not isinstance(proposal_digest, str) or not isinstance(kind, str):
            raise SeedCommitQuorumError("peer response lacks a proposal and phase identity")
        identity = (proposal_digest, kind)
        previous = self._response_sequences.get(identity)
        if previous is not None:
            previous_payload, sequence = previous
            if previous_payload != normalized:
                raise SeedCommitQuorumError("peer response identity conflicts with its durable prior projection")
            if sequence in self.outbound.pending_sequences():
                self.outbound.retransmit(sequence)
            return
        sequence = self.outbound.send(normalized)
        self._response_sequences[identity] = (normalized, sequence)

    def _tick_outbound_if_due(self) -> None:
        """Mathematics: advance response sender retry time once per configured interval `Δt≥50ms`."""

        now = time.monotonic()
        if now - self._last_retry >= self.retry_interval:
            self.outbound.tick()
            self._last_retry = now


class SeedCommitQuorumCoordinator:
    """Owner-side prepare/decision barrier with durable recovery artifacts and gated host publication."""

    def __init__(
        self,
        membership: SeedCommitMembership,
        ledger: DurableSeedCommitLedger,
        operating_system: HeadlessOS,
        durable_journal: DurableSeedCommitJournal,
        peers: Mapping[str, SeedCommitPeerLink],
        *,
        retry_interval: float = 0.05,
    ) -> None:
        r"""Mathematics: bind owner state `OS`, ledger `L`, and peer links `P⊆N\{owner}` to one immutable membership `M`."""

        if not isinstance(membership, SeedCommitMembership) or not isinstance(ledger, DurableSeedCommitLedger):
            raise SeedCommitQuorumError("coordinator requires fixed membership and durable ledger")
        if ledger.member_id != membership.owner_id or ledger.membership.digest != membership.digest:
            raise SeedCommitQuorumError("coordinator ledger is not the configured membership owner")
        if not isinstance(operating_system, HeadlessOS) or not isinstance(durable_journal, DurableSeedCommitJournal):
            raise SeedCommitQuorumError("coordinator requires a live host and durable publication journal")
        if durable_journal.executor_id != membership.owner_id:
            raise SeedCommitQuorumError("owner durable journal identity does not match membership")
        if not isinstance(peers, Mapping) or any(not isinstance(link, SeedCommitPeerLink) for link in peers.values()):
            raise SeedCommitQuorumError("coordinator peer links must be a mapping of typed links")
        if any(peer != link.peer_id for peer, link in peers.items()):
            raise SeedCommitQuorumError("coordinator peer map key differs from link identity")
        if any(peer not in membership.member_ids or peer == membership.owner_id for peer in peers):
            raise SeedCommitQuorumError("coordinator peer link is outside fixed membership")
        if not isinstance(retry_interval, (int, float)) or isinstance(retry_interval, bool) or retry_interval <= 0:
            raise SeedCommitQuorumError("retry interval must be positive")
        self.membership = membership
        self.ledger = ledger
        self.operating_system = operating_system
        self.durable_journal = durable_journal
        self.peers = dict(peers)
        self.retry_interval = float(retry_interval)
        self._last_retry = time.monotonic()

    def propose_seed_input(
        self,
        request: SeedCommitRequest,
        request_source: str,
        request_channel: str,
        request_sequence: int,
    ) -> tuple[SeedCommitProposal, SeedCommitTransitionArtifact]:
        """Mathematics: evaluate input `T_q` on a shadow host, then bind `A=(result,OS')` to the next chain edge `(k,d₋,d₊)`."""

        if not isinstance(request, SeedCommitRequest):
            raise SeedCommitQuorumError("seed proposal requires a typed seed input request")
        if not isinstance(request_source, str) or not request_source or not isinstance(request_channel, str) or not request_channel:
            raise SeedCommitQuorumError("request transport source and channel must be non-empty")
        if not isinstance(request_sequence, int) or isinstance(request_sequence, bool) or request_sequence <= 0:
            raise SeedCommitQuorumError("request transport sequence must be positive")
        latest = self.ledger.committed_state()
        slot = 1 if latest is None else latest[0] + 1
        predecessor = self.membership.genesis_state_digest if latest is None else latest[1]
        current_digest = SystemSeed.from_system(self.operating_system).origin_digest
        if current_digest != predecessor or request.base_state_digest != predecessor:
            raise SeedCommitQuorumError("live host and request do not extend the durable seed predecessor")
        current = self.operating_system.seed_admission.current(request.system_id)
        if current is None or request.system_id != self.membership.system_id:
            raise SeedCommitQuorumError("request system is not admitted under fixed membership")
        if current.identity.incarnation != self.membership.incarnation or current.state_digest != predecessor:
            raise SeedCommitQuorumError("admitted system identity or state does not match fixed membership")
        if any(event.source == request.source and event.sequence == request.sequence for event in current.seed.input_events):
            raise SeedCommitQuorumError("input identity already exists; recover its prior quorum decision instead")

        candidate = HeadlessOS.from_snapshot(self.operating_system.snapshot())
        admission, envelope = candidate.commit_seed_input(
            request.system_id,
            request.source,
            request.sequence,
            request.pid,
            request.mailbox,
            request.values,
        )
        if not admission.accepted:
            raise SeedCommitQuorumError(admission.reason or "seed input was refused by admission")
        result = SeedCommitResult(
            request_source,
            request_channel,
            request_sequence,
            request.fingerprint,
            request.system_id,
            True,
            admission.replayed,
            envelope.state_digest,
            _frontier_digest(envelope),
            admission.admission_receipt,
            envelope,
        )
        artifact = SeedCommitTransitionArtifact(result.to_dict(), candidate.snapshot())
        proposal = SeedCommitProposal(
            self.membership.digest,
            self.membership.system_id,
            self.membership.incarnation,
            self.membership.owner_id,
            self.membership.owner_term,
            slot,
            predecessor,
            request.fingerprint,
            envelope.state_digest,
            artifact.digest,
        )
        _validate_artifact(self.membership, proposal, artifact)
        return proposal, artifact

    def execute(
        self,
        proposal: SeedCommitProposal,
        artifact: SeedCommitTransitionArtifact,
        *,
        timeout: float = 10.0,
    ) -> SeedCommitResult:
        """Mathematics: `prepare quorum → fsync owner decision → commit quorum → fsync publication journal → publish live OS`."""

        self._validate_owner_transition(proposal, artifact)
        if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0:
            raise SeedCommitQuorumError("quorum execution timeout must be positive")
        self._discard_prior_responses(proposal)
        decision = self.ledger.decision(proposal)
        latest = self.ledger.committed_state()
        if decision is not None and latest is not None and latest[0] > proposal.slot:
            raise SeedCommitQuorumError("proposal is older than the latest committed owner state")
        if decision is not None:
            certificate = self.ledger.certificate(proposal)
            if certificate is None:
                raise SeedCommitQuorumError("durable owner decision has no recoverable certificate")
        else:
            local_vote = self.ledger.prepare(proposal, artifact)
            votes = {self.membership.owner_id: local_vote}
            votes.update({vote.member_id: vote for vote in self.ledger.observed_votes(proposal)})
            if len(votes) < self.membership.quorum:
                self._send_prepare(proposal, artifact)
                self._collect_votes(proposal, artifact, votes, time.monotonic() + float(timeout))
            certificate = SeedCommitCertificate(
                self.membership.digest,
                proposal.digest,
                tuple(votes[member] for member in sorted(votes)),
            )
            self.ledger.commit(proposal, certificate)

        decisions = {self.membership.owner_id: self.ledger.decision(proposal)}
        decisions.update({item.member_id: item for item in self.ledger.observed_decisions(proposal)})
        if len(decisions) < self.membership.quorum:
            self._send_commit(proposal, certificate)
            self._collect_decisions(proposal, decisions, certificate, time.monotonic() + float(timeout))
        result, candidate = _validate_artifact(self.membership, proposal, artifact)
        self._publish_owner(proposal, result, candidate)
        return result

    def resume(self, proposal: SeedCommitProposal, *, timeout: float = 10.0) -> SeedCommitResult:
        """Mathematics: recover `A` and `C` from the durable owner prefix, re-drive missing peer decisions, then publish after quorum."""

        artifact = self.ledger.transition_artifact(proposal)
        if artifact is None:
            raise SeedCommitQuorumError("owner ledger has no recoverable transition artifact")
        return self.execute(proposal, artifact, timeout=timeout)

    def receive_and_commit(
        self,
        requests: HypervisorSeedCommitChannel,
        responses: HypervisorSeedCommitResultChannel,
        *,
        timeout: float = 10.0,
    ) -> SeedCommitResult | None:
        """Mathematics: `peek(q)→quorum(q)→fsync(result,state)→reply→ACK(q)`; timeout leaves the same FIFO head retryable."""

        if not isinstance(requests, HypervisorSeedCommitChannel):
            raise SeedCommitQuorumError("quorum request service requires a typed seed commit request channel")
        if not isinstance(responses, HypervisorSeedCommitResultChannel):
            raise SeedCommitQuorumError("quorum request service requires a typed seed commit result channel")
        if (
            requests.channel.destination != self.membership.owner_id
            or responses.operation_source != requests.channel.peer
            or responses.operation_channel != requests.channel.channel
        ):
            raise SeedCommitQuorumError("request/result channels do not bind to this owner operation")
        peeked = requests.channel.peek()
        if peeked is None:
            return None
        transport_sequence, payload = peeked
        request = requests._decode_payload(payload)
        identity = (requests.channel.peer, requests.channel.channel, transport_sequence)

        self._reconcile_owner_publication(timeout)
        result = self.durable_journal.lookup(identity, request.fingerprint)
        if result is not None:
            result = replace(result, replayed=True)
        else:
            pending = self.ledger.proposal_for_request_identity(identity)
            if pending is not None:
                proposal, artifact = pending
                if proposal.request_fingerprint != request.fingerprint:
                    raise SeedCommitQuorumError("transport request identity conflicts with a durable prepared proposal")
                if artifact is None:
                    raise SeedCommitQuorumError("durable request proposal has no recoverable transition artifact")
                result = self.resume(proposal, timeout=timeout)
            else:
                result = self._receive_new_or_replayed_input(request, identity, transport_sequence, timeout)
        responses.send(result)
        received = requests.channel.receive()
        if received is not None and received[0] != transport_sequence:
            raise SeedCommitQuorumError("request FIFO head changed after durable quorum result")
        return result

    def _receive_new_or_replayed_input(
        self,
        request: SeedCommitRequest,
        identity: tuple[str, str, int],
        transport_sequence: int,
        timeout: float,
    ) -> SeedCommitResult:
        """Mathematics: choose exactly one branch: `new→quorum`, `same event→committed replay`, or `invalid→durable refusal`."""

        current = self.operating_system.seed_admission.current(request.system_id)
        if current is None or request.system_id != self.membership.system_id:
            return self._record_request_refusal(
                request,
                identity,
                "seed commit precondition system is not admitted under this membership",
            )
        existing_event = next(
            (
                event
                for event in current.seed.input_events
                if event.source == request.source and event.sequence == request.sequence
            ),
            None,
        )
        if existing_event is not None:
            if (
                existing_event.pid != request.pid
                or existing_event.mailbox != request.mailbox
                or existing_event.values != request.values
            ):
                return self._record_request_refusal(request, identity, "conflicting input retransmission")
            prior = self.ledger.committed_proposal_for_fingerprint(request.fingerprint)
            if prior is None:
                return self._record_request_refusal(
                    request,
                    identity,
                    "input identity exists without a matching committed quorum transition",
                )
            prior_proposal, prior_artifact = prior
            prior_result, _prior_host = _validate_artifact(self.membership, prior_proposal, prior_artifact)
            if prior_result.envelope is None or not any(
                event.source == request.source
                and event.sequence == request.sequence
                and event.digest == existing_event.digest
                for event in prior_result.envelope.seed.input_events
            ):
                raise SeedCommitQuorumError("durable quorum artifact does not contain the retransmitted input event")

            result = SeedCommitResult(
                identity[0],
                identity[1],
                identity[2],
                request.fingerprint,
                request.system_id,
                True,
                True,
                current.state_digest,
                _frontier_digest(current),
                prior_result.admission_receipt,
                current,
            )
            self.durable_journal.record(identity, request.fingerprint, result, self.operating_system)
            return result

        if current.state_digest != request.base_state_digest:
            return self._record_request_refusal(
                request,
                identity,
                "seed commit precondition state digest mismatch",
            )
        try:
            proposal, artifact = self.propose_seed_input(
                request,
                identity[0],
                identity[1],
                identity[2],
            )
        except (SeedAdmissionError, SeedEnvelopeError, SeedNavigationError, OSError, ValueError) as exc:
            if isinstance(exc, SeedCommitQuorumError):
                raise
            return self._record_request_refusal(
                request,
                identity,
                f"seed commit refused: {type(exc).__name__}: {exc}",
            )
        return self.execute(proposal, artifact, timeout=timeout)

    def _record_request_refusal(
        self,
        request: SeedCommitRequest,
        identity: tuple[str, str, int],
        reason: str,
    ) -> SeedCommitResult:
        """Mathematics: persist deterministic refusal `R(q)` with unchanged `OS` before allowing response and request ACK."""

        result = SeedCommitResult(
            identity[0],
            identity[1],
            identity[2],
            request.fingerprint,
            request.system_id,
            False,
            False,
            None,
            None,
            None,
            None,
            reason,
        )
        self.durable_journal.record(identity, request.fingerprint, result, self.operating_system)
        return result

    def _reconcile_owner_publication(self, timeout: float) -> None:
        """Mathematics: require `d(live)=d(ledger_head)`; if behind by the pending committed edge, replay its durable quorum artifact."""

        committed = self.ledger.committed_state()
        expected = self.membership.genesis_state_digest if committed is None else committed[1]
        actual = SystemSeed.from_system(self.operating_system).origin_digest
        if actual == expected:
            return
        if committed is None:
            raise SeedCommitQuorumError("live owner host differs from the membership genesis state")
        proposal = self.ledger.proposal_at(committed[0])
        if proposal is None or proposal.result_state_digest != expected:
            raise SeedCommitQuorumError("latest committed owner transition cannot be recovered")
        self.resume(proposal, timeout=timeout)
        if SystemSeed.from_system(self.operating_system).origin_digest != expected:
            raise SeedCommitQuorumError("owner publication recovery did not reach the durable quorum head")

    def _validate_owner_transition(
        self,
        proposal: SeedCommitProposal,
        artifact: SeedCommitTransitionArtifact,
    ) -> None:
        """Mathematics: require owner proposal/artifact identity and, before decision, live state equal the predecessor digest."""

        if proposal.owner_id != self.membership.owner_id or proposal.membership_digest != self.membership.digest:
            raise SeedCommitQuorumError("proposal does not belong to this owner and membership")
        _validate_artifact(self.membership, proposal, artifact)
        if self.ledger.decision(proposal) is None:
            live_digest = SystemSeed.from_system(self.operating_system).origin_digest
            if live_digest != proposal.predecessor_state_digest:
                raise SeedCommitQuorumError("owner live state does not match proposal predecessor")

    def _send_prepare(self, proposal: SeedCommitProposal, artifact: SeedCommitTransitionArtifact) -> None:
        """Mathematics: fan out identical prepare pair `(p,A)` to every configured reachable link, preserving each peer FIFO."""

        payload = {
            "kind": SEED_QUORUM_PREPARE_KIND,
            "proposal": proposal.snapshot(),
            "artifact": artifact.snapshot(),
        }
        for peer in sorted(self.peers):
            self.peers[peer].requests.process_ack()
            self.peers[peer].requests.send(payload)

    def _send_commit(self, proposal: SeedCommitProposal, certificate: SeedCommitCertificate) -> None:
        """Mathematics: fan out the persisted decision certificate `C` only after owner ledger `COMMIT(p,C)` is fsynced."""

        if self.ledger.decision(proposal) is None:
            raise SeedCommitQuorumError("owner decision must be durable before commit fanout")
        payload = {
            "kind": SEED_QUORUM_COMMIT_KIND,
            "proposal": proposal.snapshot(),
            "certificate": certificate.snapshot(),
        }
        for peer in sorted(self.peers):
            self.peers[peer].requests.process_ack()
            self.peers[peer].requests.send(payload)

    def _collect_votes(
        self,
        proposal: SeedCommitProposal,
        artifact: SeedCommitTransitionArtifact,
        votes: dict[str, SeedPrepareVote],
        deadline: float,
    ) -> None:
        """Mathematics: collect unique peer votes until `|V|≥q`, requiring channel peer identity and both digests to agree."""

        while len(votes) < self.membership.quorum:
            self._tick_due_channels()
            progressed = False
            for peer in sorted(self.peers):
                channel = self.peers[peer].responses
                self.peers[peer].requests.process_ack()
                peeked = channel.peek()
                if peeked is None:
                    continue
                _sequence, payload = peeked
                if isinstance(payload, Mapping) and payload.get("proposal_digest") != proposal.digest:
                    self._discard_prior_responses(proposal)
                    progressed = True
                    continue
                if not isinstance(payload, Mapping) or set(payload) != {
                    "kind", "proposal_digest", "artifact_digest", "vote"
                }:
                    raise SeedCommitQuorumError("peer prepare response fields are malformed")
                if payload["kind"] != SEED_QUORUM_VOTE_KIND or payload["proposal_digest"] != proposal.digest:
                    raise SeedCommitQuorumError("peer prepare response is for a different protocol phase or proposal")
                if payload["artifact_digest"] != artifact.digest or not isinstance(payload["vote"], Mapping):
                    raise SeedCommitQuorumError("peer vote is not bound to the prepared transition artifact")
                vote = SeedPrepareVote.from_snapshot(payload["vote"])
                if vote.member_id != peer or vote.member_id not in self.membership.member_ids:
                    raise SeedCommitQuorumError("peer vote identity does not match its configured channel")
                if vote.membership_digest != self.membership.digest or vote.proposal_digest != proposal.digest:
                    raise SeedCommitQuorumError("peer vote identity does not match fixed membership proposal")
                def persist_vote_before_ack(received_sequence: int, received_payload: Any) -> None:
                    """Mathematics: fsync `observe_vote(p,v)` before `ReliableChannel.receive` consumes the frame and emits ACK."""

                    if received_sequence != peeked[0] or received_payload != payload:
                        raise SeedCommitQuorumError("peer vote changed before durable acknowledgement")
                    self.ledger.observe_vote(proposal, vote)

                received = channel.receive(commit=persist_vote_before_ack)
                if received is None:
                    continue
                if received != peeked:
                    raise SeedCommitQuorumError("peer vote frame changed between inspection and consume")
                previous = votes.get(peer)
                if previous is not None and previous != vote:
                    raise SeedCommitQuorumError("peer returned conflicting durable votes")
                votes[peer] = vote
                progressed = True
            if len(votes) >= self.membership.quorum:
                return
            if time.monotonic() >= deadline:
                raise SeedCommitQuorumError(
                    f"prepare quorum unavailable: received {len(votes)} of {self.membership.quorum} required votes"
                )
            if not progressed:
                time.sleep(min(self.retry_interval / 4, max(0.0, deadline - time.monotonic())))

    def _collect_decisions(
        self,
        proposal: SeedCommitProposal,
        decisions: dict[str, SeedCommitDecision | None],
        certificate: SeedCommitCertificate,
        deadline: float,
    ) -> None:
        """Mathematics: collect unique durable decisions until `|D|≥q`; local owner decision is explicitly in `D`."""

        decisions = {member: decision for member, decision in decisions.items() if decision is not None}
        while len(decisions) < self.membership.quorum:
            self._tick_due_channels()
            progressed = False
            for peer in sorted(self.peers):
                channel = self.peers[peer].responses
                self.peers[peer].requests.process_ack()
                peeked = channel.peek()
                if peeked is None:
                    continue
                _sequence, payload = peeked
                if isinstance(payload, Mapping) and payload.get("proposal_digest") != proposal.digest:
                    self._discard_prior_responses(proposal)
                    progressed = True
                    continue
                if isinstance(payload, Mapping) and payload.get("kind") == SEED_QUORUM_VOTE_KIND:
                    if (
                        set(payload) != {"kind", "proposal_digest", "artifact_digest", "vote"}
                        or payload.get("proposal_digest") != proposal.digest
                        or not isinstance(payload.get("vote"), Mapping)
                    ):
                        raise SeedCommitQuorumError("late prepare vote is malformed or belongs to another proposal")
                    late_vote = SeedPrepareVote.from_snapshot(payload["vote"])
                    if (
                        late_vote.member_id != peer
                        or late_vote.membership_digest != self.membership.digest
                        or late_vote.proposal_digest != proposal.digest
                        or payload.get("artifact_digest") != proposal.transition_artifact_digest
                    ):
                        raise SeedCommitQuorumError("late prepare vote identity does not match peer channel")
                    def persist_late_vote(received_sequence: int, received_payload: Any) -> None:
                        """Mathematics: fsync `observe_vote(p,v)` before acknowledging a valid late vote behind the same FIFO."""

                        if received_sequence != peeked[0] or received_payload != payload:
                            raise SeedCommitQuorumError("late peer vote changed before acknowledgement")
                        self.ledger.observe_vote(proposal, late_vote)

                    late_received = channel.receive(commit=persist_late_vote)
                    if late_received is not None and late_received != peeked:
                        raise SeedCommitQuorumError("late vote frame changed between inspection and consume")
                    progressed = True
                    continue
                if not isinstance(payload, Mapping) or set(payload) != {"kind", "proposal_digest", "decision"}:
                    raise SeedCommitQuorumError("peer commit response fields are malformed")
                if payload["kind"] != SEED_QUORUM_DECISION_KIND or payload["proposal_digest"] != proposal.digest:
                    raise SeedCommitQuorumError("peer commit response is for a different protocol phase or proposal")
                if not isinstance(payload["decision"], Mapping):
                    raise SeedCommitQuorumError("peer commit decision payload is malformed")
                decision = SeedCommitDecision.from_snapshot(payload["decision"])
                if (
                    decision.member_id != peer
                    or decision.proposal_digest != proposal.digest
                    or decision.slot != proposal.slot
                    or decision.state_digest != proposal.result_state_digest
                    or decision.certificate_members
                    != tuple(sorted(vote.member_id for vote in certificate.votes))
                ):
                    raise SeedCommitQuorumError("peer decision does not match configured identity and proposal")

                def persist_decision_before_ack(received_sequence: int, received_payload: Any) -> None:
                    """Mathematics: fsync `observe_decision(p,d)` before consuming the peer response and emitting its ACK."""

                    if received_sequence != peeked[0] or received_payload != payload:
                        raise SeedCommitQuorumError("peer decision changed before durable acknowledgement")
                    self.ledger.observe_decision(proposal, decision)

                received = channel.receive(commit=persist_decision_before_ack)
                if received is None:
                    continue
                if received != peeked:
                    raise SeedCommitQuorumError("peer decision frame changed between inspection and consume")
                previous = decisions.get(peer)
                if previous is not None and previous != decision:
                    raise SeedCommitQuorumError("peer returned conflicting durable commit decisions")
                decisions[peer] = decision
                progressed = True
            if len(decisions) >= self.membership.quorum:
                return
            if time.monotonic() >= deadline:
                raise SeedCommitQuorumError(
                    f"commit quorum unavailable: received {len(decisions)} of {self.membership.quorum} required decisions"
                )
            if not progressed:
                time.sleep(min(self.retry_interval / 4, max(0.0, deadline - time.monotonic())))

    def _discard_prior_responses(self, proposal: SeedCommitProposal) -> None:
        """Mathematics: consume only responses for durable slots `< proposal.slot`, persisting their evidence before ACK."""

        prior_by_digest = {}
        for slot in range(1, proposal.slot):
            prior = self.ledger.proposal_at(slot)
            if prior is not None:
                prior_by_digest[prior.digest] = prior
        for peer in sorted(self.peers):
            channel = self.peers[peer].responses
            while True:
                peeked = channel.peek()
                if peeked is None:
                    break
                _sequence, payload = peeked
                if not isinstance(payload, Mapping):
                    raise SeedCommitQuorumError("stale peer response is not a typed mapping")
                response_digest = payload.get("proposal_digest")
                if response_digest == proposal.digest:
                    break
                prior = prior_by_digest.get(response_digest)
                if prior is None:
                    raise SeedCommitQuorumError("peer response is not bound to current or prior durable proposal")
                kind = payload.get("kind")
                if kind == SEED_QUORUM_VOTE_KIND:
                    if set(payload) != {"kind", "proposal_digest", "artifact_digest", "vote"} or not isinstance(payload.get("vote"), Mapping):
                        raise SeedCommitQuorumError("stale prepare response fields are malformed")
                    vote = SeedPrepareVote.from_snapshot(payload["vote"])
                    if (
                        vote.member_id != peer
                        or vote.membership_digest != self.membership.digest
                        or vote.proposal_digest != prior.digest
                        or payload.get("artifact_digest") != prior.transition_artifact_digest
                    ):
                        raise SeedCommitQuorumError("stale prepare response does not match its peer and proposal")
                    def receive_commit(received_sequence: int, received_payload: Any) -> None:
                        """Mathematics: fsync prior vote `v` before consuming or acknowledging its stale FIFO frame."""

                        if received_sequence != peeked[0] or received_payload != payload:
                            raise SeedCommitQuorumError("prior vote changed before durable acknowledgement")
                        self.ledger.observe_vote(prior, vote)
                elif kind == SEED_QUORUM_DECISION_KIND:
                    if set(payload) != {"kind", "proposal_digest", "decision"} or not isinstance(payload.get("decision"), Mapping):
                        raise SeedCommitQuorumError("stale commit response fields are malformed")
                    decision = SeedCommitDecision.from_snapshot(payload["decision"])
                    certificate = self.ledger.certificate(prior)
                    if certificate is None or (
                        decision.member_id != peer
                        or decision.proposal_digest != prior.digest
                        or decision.slot != prior.slot
                        or decision.state_digest != prior.result_state_digest
                        or decision.certificate_members
                        != tuple(sorted(vote.member_id for vote in certificate.votes))
                    ):
                        raise SeedCommitQuorumError("stale commit response does not match durable prior decision")
                    def receive_commit(received_sequence: int, received_payload: Any) -> None:
                        """Mathematics: fsync prior decision `d` before consuming or acknowledging its stale FIFO frame."""

                        if received_sequence != peeked[0] or received_payload != payload:
                            raise SeedCommitQuorumError("prior decision changed before durable acknowledgement")
                        self.ledger.observe_decision(prior, decision)
                else:
                    raise SeedCommitQuorumError("stale peer response kind is unsupported")
                received = channel.receive(commit=receive_commit)
                if received is not None and received != peeked:
                    raise SeedCommitQuorumError("stale peer response changed between inspection and consume")

    def _tick_due_channels(self) -> None:
        """Mathematics: advance each sender's logical retry clock by one iff real elapsed time reaches `retry_interval`."""

        now = time.monotonic()
        if now - self._last_retry < self.retry_interval:
            return
        for link in self.peers.values():
            link.requests.process_ack()
            link.requests.tick()
        self._last_retry = now

    def _publish_owner(
        self,
        proposal: SeedCommitProposal,
        result: SeedCommitResult,
        candidate: HeadlessOS,
    ) -> None:
        """Mathematics: require latest durable `(slot,digest)=p.(k,d₊)`, fsync publication, then replay `p` into live state."""

        latest = self.ledger.committed_state()
        if latest != (proposal.slot, proposal.result_state_digest):
            raise SeedCommitQuorumError("owner publication is not the latest durable seed decision")
        identity = (result.request_source, result.request_channel, result.request_sequence)
        self.durable_journal.record(identity, result.request_fingerprint, result, candidate)
        _install_seed_transition(self.operating_system, proposal, result, candidate)


def _validate_artifact(
    membership: SeedCommitMembership,
    proposal: SeedCommitProposal,
    artifact: SeedCommitTransitionArtifact,
) -> tuple[SeedCommitResult, HeadlessOS]:
    """Mathematics: prove `d(A)=p.artifact`, result identity/state binds `p`, and `SystemSeed(OS_A)=p.d₊`."""

    if not isinstance(artifact, SeedCommitTransitionArtifact):
        raise SeedCommitQuorumError("transition artifact has the wrong type")
    if proposal.transition_artifact_digest is None or artifact.digest != proposal.transition_artifact_digest:
        raise SeedCommitQuorumError("transition artifact digest does not match proposal")
    if (
        proposal.membership_digest != membership.digest
        or proposal.system_id != membership.system_id
        or proposal.incarnation != membership.incarnation
        or proposal.owner_id != membership.owner_id
        or proposal.owner_term != membership.owner_term
    ):
        raise SeedCommitQuorumError("proposal coordinates do not match fixed membership")
    try:
        result = SeedCommitResult.from_dict(artifact.result)
        candidate = HeadlessOS.from_snapshot(dict(artifact.operating_system))
        candidate_digest = SystemSeed.from_system(candidate).origin_digest
    except (KeyError, TypeError, ValueError, SeedCommitTransportError) as exc:
        raise SeedCommitQuorumError("transition artifact cannot be restored as a seed result and host") from exc
    if (
        not result.accepted
        or result.system_id != membership.system_id
        or result.request_fingerprint != proposal.request_fingerprint
        or result.state_digest != proposal.result_state_digest
        or candidate_digest != proposal.result_state_digest
    ):
        raise SeedCommitQuorumError("transition artifact result does not match proposal state identity")
    current = candidate.seed_admission.current(membership.system_id)
    if current is None or current.identity.incarnation != membership.incarnation or current.state_digest != proposal.result_state_digest:
        raise SeedCommitQuorumError("transition artifact host admission state does not match proposal")
    if current.snapshot() != result.envelope.snapshot():
        raise SeedCommitQuorumError("transition artifact result envelope differs from candidate host")
    return result, candidate


def _install_seed_transition(
    operating_system: HeadlessOS,
    proposal: SeedCommitProposal,
    result: SeedCommitResult,
    candidate: HeadlessOS,
) -> None:
    """Mathematics: apply event `e` once when `d(live)=d₋`, then require `d(live')=d₊` and `snapshot(live')=snapshot(candidate)`."""

    if result.envelope is None or not result.envelope.seed.input_events:
        raise SeedCommitQuorumError("accepted quorum artifact has no replayable seed input event")
    event = result.envelope.seed.input_events[-1]
    before = deepcopy(operating_system.snapshot())
    trajectory = operating_system.vm.trajectory
    trajectory_checkpoint = None if trajectory is None else trajectory.checkpoint()
    current_digest = SystemSeed.from_system(operating_system).origin_digest
    if current_digest not in (proposal.predecessor_state_digest, proposal.result_state_digest):
        raise SeedCommitQuorumError("live host is neither the committed predecessor nor its exact result")
    if current_digest == proposal.result_state_digest:
        if before != candidate.snapshot():
            raise SeedCommitQuorumError("live host digest matches but full candidate snapshot differs")
        return
    try:
        admission, _envelope = operating_system.commit_seed_input(
            result.system_id,
            event.source,
            event.sequence,
            event.pid,
            event.mailbox,
            event.values,
        )
        if not admission.accepted:
            raise SeedCommitQuorumError(admission.reason or "committed seed event was refused during publication")
        actual_digest = SystemSeed.from_system(operating_system).origin_digest
        if actual_digest != proposal.result_state_digest or operating_system.snapshot() != candidate.snapshot():
            raise SeedCommitQuorumError("live publication diverged from the prepared deterministic artifact")
    except Exception:
        operating_system._restore_snapshot_in_place(before)
        if trajectory_checkpoint is not None:
            trajectory.rollback(trajectory_checkpoint)
        raise
