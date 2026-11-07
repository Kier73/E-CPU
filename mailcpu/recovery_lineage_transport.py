"""Independent-process participants for quorum-anchored recovery lineage.

The protocol reuses the seed-commit reliable-channel names, SocketTransport,
fixed-membership proposal algebra, and durable per-member ledger. The owner
process keeps its own authority journal and coordinates remote participants;
each remote process owns exactly one authority journal.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable, Mapping

from .recovery_lineage import (
    RecoveryCheckpointManifest,
    RecoveryLineageAuthority,
    RecoveryLineageCoordinator,
    RecoveryLineageError,
    RecoveryLineageProof,
)
from .seed_commit_coordinator import (
    SEED_QUORUM_REQUEST_CHANNEL,
    SEED_QUORUM_RESPONSE_CHANNEL,
)
from .seed_commit_quorum import (
    SeedCommitCertificate,
    SeedCommitDecision,
    SeedCommitMembership,
    SeedCommitProposal,
    SeedPrepareVote,
)
from .reliability import ReliabilityPolicy, ReliableChannel
from .socket_transport import SocketTransport


RECOVERY_LINEAGE_PREPARE = "mailcpu.seed.quorum.recovery.prepare"
RECOVERY_LINEAGE_COMMIT = "mailcpu.seed.quorum.recovery.commit"
RECOVERY_LINEAGE_INSPECT = "mailcpu.seed.quorum.recovery.inspect"
RECOVERY_LINEAGE_VOTE = "mailcpu.seed.quorum.recovery.vote"
RECOVERY_LINEAGE_DECISION = "mailcpu.seed.quorum.recovery.decision"
RECOVERY_LINEAGE_STATE = "mailcpu.seed.quorum.recovery.state"
RECOVERY_LINEAGE_ERROR = "mailcpu.seed.quorum.recovery.error"


class RecoveryLineageTransportError(RecoveryLineageError):
    """Mathematics: A remote authority could not complete a reliable request/response transition."""


def _request_channels(
    transport: SocketTransport,
    membership: SeedCommitMembership,
    member_id: str,
    policy: ReliabilityPolicy,
) -> tuple[ReliableChannel, ReliableChannel]:
    """Mathematics: Bind owner→member requests and member→owner responses to the seed-commit reliable-channel coordinates."""

    owner = membership.owner_id
    requests = ReliableChannel(
        transport,
        owner,
        member_id,
        SEED_QUORUM_REQUEST_CHANNEL,
        policy,
    )
    responses = ReliableChannel(
        transport,
        owner,
        owner,
        SEED_QUORUM_RESPONSE_CHANNEL,
        policy,
        peer=member_id,
    )
    return requests, responses


def _participant_channels(
    transport: SocketTransport,
    membership: SeedCommitMembership,
    member_id: str,
    policy: ReliabilityPolicy,
) -> tuple[ReliableChannel, ReliableChannel]:
    """Mathematics: Bind remote member request reception and response emission to the reciprocal seed-commit channel coordinates."""

    owner = membership.owner_id
    inbound = ReliableChannel(
        transport,
        member_id,
        member_id,
        SEED_QUORUM_REQUEST_CHANNEL,
        policy,
        peer=owner,
    )
    outbound = ReliableChannel(
        transport,
        member_id,
        owner,
        SEED_QUORUM_RESPONSE_CHANNEL,
        policy,
    )
    return inbound, outbound


class RecoveryLineageProcessParticipant:
    """One independently runnable participant serving a durable recovery-lineage journal over TCP."""

    def __init__(
        self,
        membership: SeedCommitMembership,
        member_id: str,
        journal_path: str | Path,
        transport: SocketTransport,
        *,
        policy: ReliabilityPolicy | None = None,
        fault_hook: Callable[[str, SeedCommitProposal], None] | None = None,
    ) -> None:
        """Mathematics: bind one fixed-membership durable ledger to reciprocal reliable request/response channels and a peer-authenticated stream."""

        if not isinstance(membership, SeedCommitMembership):
            raise RecoveryLineageTransportError("process participant requires fixed seed-commit membership")
        if not isinstance(transport, SocketTransport):
            raise RecoveryLineageTransportError("process participant requires a SocketTransport")
        if member_id not in membership.member_ids or not isinstance(member_id, str):
            raise RecoveryLineageTransportError("process participant identity is outside fixed membership")
        if (
            transport.local_endpoint != member_id
            or transport.peer_endpoint != membership.owner_id
        ):
            raise RecoveryLineageTransportError("participant stream endpoints do not match its fixed member and owner")
        selected_policy = policy or ReliabilityPolicy(lease_ticks=3, max_attempts=16, window_size=8)
        self.membership = membership
        self.member_id = member_id
        self.transport = transport
        self.authority = RecoveryLineageAuthority(membership, member_id, journal_path)
        self.inbound, self.outbound = _participant_channels(
            transport,
            membership,
            member_id,
            selected_policy,
        )
        self.fault_hook = fault_hook
        self._last_retry = time.monotonic()
        self.retry_interval = 0.03

    def service_once(self) -> bool:
        """Mathematics: execute one inbound command only after the durable handler completes, then process response ACKs and due retries."""

        self.outbound.process_ack()

        def apply_before_ack(sequence: int, payload: Any) -> None:
            """Mathematics: persist PREPARE or COMMIT before ReliableChannel consumes and acknowledges its inbound sequence."""

            if not isinstance(payload, Mapping):
                raise RecoveryLineageTransportError("recovery-lineage peer request must be a mapping")
            self._dispatch(payload)

        received = self.inbound.receive(commit=apply_before_ack)
        now = time.monotonic()
        if now - self._last_retry >= self.retry_interval:
            self.outbound.tick()
            self._last_retry = now
        return received is not None

    def _dispatch(self, payload: Mapping[str, Any]) -> None:
        """Mathematics: map one owner RPC to a journal transition or read projection and publish its typed response."""

        request_id = payload.get("request_id")
        if not isinstance(request_id, str) or not request_id:
            raise RecoveryLineageTransportError("recovery-lineage request id is malformed")
        kind = payload.get("kind")
        try:
            if kind == RECOVERY_LINEAGE_PREPARE:
                if set(payload) != {"kind", "request_id", "proposal"} or not isinstance(payload["proposal"], Mapping):
                    raise RecoveryLineageTransportError("recovery prepare fields are malformed")
                proposal = SeedCommitProposal.from_snapshot(payload["proposal"])
                vote = self.authority.prepare(proposal)
                self._after_durable("after_prepare_fsync", proposal)
                self._send({
                    "kind": RECOVERY_LINEAGE_VOTE,
                    "request_id": request_id,
                    "member_id": self.member_id,
                    "proposal_digest": proposal.digest,
                    "vote": vote.snapshot(),
                })
                return

            if kind == RECOVERY_LINEAGE_COMMIT:
                if set(payload) != {"kind", "request_id", "proposal", "certificate"}:
                    raise RecoveryLineageTransportError("recovery commit fields are malformed")
                if not isinstance(payload["proposal"], Mapping) or not isinstance(payload["certificate"], Mapping):
                    raise RecoveryLineageTransportError("recovery commit proposal or certificate is malformed")
                proposal = SeedCommitProposal.from_snapshot(payload["proposal"])
                certificate = SeedCommitCertificate.from_snapshot(payload["certificate"])
                decision = self.authority.commit(proposal, certificate)
                self._after_durable("after_commit_fsync", proposal)
                self._send({
                    "kind": RECOVERY_LINEAGE_DECISION,
                    "request_id": request_id,
                    "member_id": self.member_id,
                    "proposal_digest": proposal.digest,
                    "decision": decision.snapshot(),
                })
                return

            if kind == RECOVERY_LINEAGE_INSPECT:
                if set(payload) != {"kind", "request_id", "generation"}:
                    raise RecoveryLineageTransportError("recovery inspect fields are malformed")
                generation = payload.get("generation")
                if not isinstance(generation, int) or isinstance(generation, bool) or generation <= 0:
                    raise RecoveryLineageTransportError("recovery inspect generation must be positive")
                proposal = self.authority.proposal_at(generation)
                certificate = None if proposal is None else self.authority.certificate(proposal)
                decision = None if proposal is None else self.authority.decision(proposal)
                committed_state = self.authority.committed_state()
                self._send({
                    "kind": RECOVERY_LINEAGE_STATE,
                    "request_id": request_id,
                    "member_id": self.member_id,
                    "generation": generation,
                    "committed_state": None if committed_state is None else list(committed_state),
                    "proposal": None if proposal is None else proposal.snapshot(),
                    "certificate": None if certificate is None else certificate.snapshot(),
                    "decision": None if decision is None else decision.snapshot(),
                    "journal_valid": self.authority.verify(),
                })
                return

            raise RecoveryLineageTransportError("unsupported recovery-lineage request kind")
        except RecoveryLineageError as exc:
            self._send({
                "kind": RECOVERY_LINEAGE_ERROR,
                "request_id": request_id,
                "member_id": self.member_id,
                "error": str(exc),
            })

    def _after_durable(self, stage: str, proposal: SeedCommitProposal) -> None:
        """Mathematics: expose the precise post-fsync/pre-response cut for process-kill fault injection."""

        if self.fault_hook is not None:
            self.fault_hook(stage, proposal)

    def _send(self, payload: Mapping[str, Any]) -> None:
        """Mathematics: append one response to the participant's reliable response FIFO after its journal transition is durable."""

        self.outbound.process_ack()
        try:
            self.outbound.send(dict(payload))
        except Exception as exc:
            raise RecoveryLineageTransportError(f"cannot publish recovery-lineage response: {exc}") from exc


class RecoveryLineagePeerClient:
    """Owner-side reliable RPC endpoint for one independently running authority process."""

    def __init__(
        self,
        membership: SeedCommitMembership,
        member_id: str,
        transport: SocketTransport,
        *,
        timeout: float = 3.0,
        policy: ReliabilityPolicy | None = None,
    ) -> None:
        """Mathematics: bind one remote member to a single duplex reliable stream and bounded RPC deadline."""

        if not isinstance(membership, SeedCommitMembership):
            raise RecoveryLineageTransportError("peer client requires fixed seed-commit membership")
        if not isinstance(transport, SocketTransport):
            raise RecoveryLineageTransportError("peer client requires a SocketTransport")
        if member_id not in membership.member_ids or member_id == membership.owner_id:
            raise RecoveryLineageTransportError("remote peer must be a non-owner configured member")
        if (
            transport.local_endpoint != membership.owner_id
            or transport.peer_endpoint != member_id
        ):
            raise RecoveryLineageTransportError("peer client stream endpoints do not match owner and member")
        if (
            not isinstance(timeout, (int, float))
            or isinstance(timeout, bool)
            or timeout <= 0
        ):
            raise RecoveryLineageTransportError("peer RPC timeout must be positive")
        self.membership = membership
        self.member_id = member_id
        self.transport = transport
        self.timeout = float(timeout)
        selected_policy = policy or ReliabilityPolicy(lease_ticks=3, max_attempts=16, window_size=8)
        self.requests, self.responses = _request_channels(
            transport,
            membership,
            member_id,
            selected_policy,
        )
        self._request_sequence = 0
        self._inspection_cache: dict[int, dict[str, Any]] = {}

    @classmethod
    def connect(
        cls,
        membership: SeedCommitMembership,
        member_id: str,
        host: str,
        port: int,
        *,
        timeout: float = 3.0,
        policy: ReliabilityPolicy | None = None,
    ) -> "RecoveryLineagePeerClient":
        """Mathematics: create a peer-authenticated SocketTransport and bind it to one fixed-membership remote authority."""

        try:
            transport = SocketTransport.connect(host, port, membership.owner_id, member_id)
        except Exception as exc:
            raise RecoveryLineageTransportError(f"cannot connect to recovery authority {member_id}: {exc}") from exc
        try:
            return cls(
                membership,
                member_id,
                transport,
                timeout=timeout,
                policy=policy,
            )
        except Exception:
            transport.close()
            raise

    def close(self) -> None:
        """Mathematics: close the one transport underlying this peer's request and response channel pair."""

        self.transport.close()

    def prepare(self, proposal: SeedCommitProposal) -> SeedPrepareVote:
        """Mathematics: request one remote fsynced prepare vote and verify its configured member and proposal identity."""

        response = self._exchange({
            "kind": RECOVERY_LINEAGE_PREPARE,
            "proposal": proposal.snapshot(),
        }, RECOVERY_LINEAGE_VOTE)
        vote = SeedPrepareVote.from_snapshot(response["vote"])
        if (
            response.get("member_id") != self.member_id
            or response.get("proposal_digest") != proposal.digest
            or vote.member_id != self.member_id
            or vote.membership_digest != self.membership.digest
            or vote.proposal_digest != proposal.digest
        ):
            raise RecoveryLineageTransportError("remote recovery prepare vote identity is not peer-bound")
        self._inspection_cache.clear()
        return vote

    def commit(
        self,
        proposal: SeedCommitProposal,
        certificate: SeedCommitCertificate,
    ) -> SeedCommitDecision:
        """Mathematics: request a remote fsynced commit decision and verify its exact fixed-membership certificate projection."""

        response = self._exchange({
            "kind": RECOVERY_LINEAGE_COMMIT,
            "proposal": proposal.snapshot(),
            "certificate": certificate.snapshot(),
        }, RECOVERY_LINEAGE_DECISION)
        decision = SeedCommitDecision.from_snapshot(response["decision"])
        if (
            response.get("member_id") != self.member_id
            or response.get("proposal_digest") != proposal.digest
            or decision.member_id != self.member_id
            or decision.proposal_digest != proposal.digest
            or decision.slot != proposal.slot
            or decision.state_digest != proposal.result_state_digest
            or decision.certificate_members
            != tuple(sorted(vote.member_id for vote in certificate.votes))
        ):
            raise RecoveryLineageTransportError("remote recovery commit decision identity is not peer-bound")
        self._inspection_cache.clear()
        return decision

    def committed_state(self) -> tuple[int, str] | None:
        """Mathematics: read this remote member's durable committed high-water without trusting the owner-side process cache."""

        self._inspection_cache.clear()
        state = self._inspect(1)["committed_state"]
        if state is None:
            return None
        if (
            not isinstance(state, list)
            or len(state) != 2
            or not isinstance(state[0], int)
            or isinstance(state[0], bool)
            or state[0] <= 0
            or not isinstance(state[1], str)
        ):
            raise RecoveryLineageTransportError("remote recovery high-water projection is malformed")
        return state[0], state[1]

    def proposal_at(self, generation: int) -> SeedCommitProposal | None:
        """Mathematics: read a remote authority's exact prepared proposal for one recovery generation slot."""

        record = self._inspect(generation)
        raw = record.get("proposal")
        if raw is None:
            return None
        if not isinstance(raw, Mapping):
            raise RecoveryLineageTransportError("remote recovery proposal projection is malformed")
        return SeedCommitProposal.from_snapshot(raw)

    def certificate(self, proposal: SeedCommitProposal) -> SeedCommitCertificate | None:
        """Mathematics: read the original durable prepare certificate for the exact remote proposal."""

        record = self._inspect(proposal.slot)
        candidate = record.get("proposal")
        if not isinstance(candidate, Mapping):
            return None
        if SeedCommitProposal.from_snapshot(candidate).digest != proposal.digest:
            return None
        raw = record.get("certificate")
        return None if raw is None else SeedCommitCertificate.from_snapshot(raw)

    def decision(self, proposal: SeedCommitProposal) -> SeedCommitDecision | None:
        """Mathematics: read the remote durable decision only when its occupied slot matches the exact proposal."""

        record = self._inspect(proposal.slot)
        candidate = record.get("proposal")
        if not isinstance(candidate, Mapping):
            return None
        if SeedCommitProposal.from_snapshot(candidate).digest != proposal.digest:
            return None
        raw = record.get("decision")
        return None if raw is None else SeedCommitDecision.from_snapshot(raw)

    def verify(self) -> bool:
        """Mathematics: ask the remote authority to report its journal replay-integrity result."""

        return bool(self._inspect(1).get("journal_valid", False))

    def _inspect(self, generation: int) -> dict[str, Any]:
        """Mathematics: perform one remote slot inspection and cache its read-only proposal/certificate/decision projection."""

        cached = self._inspection_cache.get(generation)
        if cached is not None:
            return cached
        response = self._exchange({
            "kind": RECOVERY_LINEAGE_INSPECT,
            "generation": generation,
        }, RECOVERY_LINEAGE_STATE)
        if response.get("member_id") != self.member_id or response.get("generation") != generation:
            raise RecoveryLineageTransportError("remote recovery inspect response is not peer-bound")
        if response.get("journal_valid") is not True:
            raise RecoveryLineageTransportError("remote recovery authority journal failed replay verification")
        self._inspection_cache[generation] = dict(response)
        return self._inspection_cache[generation]

    def _exchange(self, payload: Mapping[str, Any], expected_kind: str) -> dict[str, Any]:
        """Mathematics: send one reliable request and consume exactly its correlated response before the bounded deadline."""

        self._request_sequence += 1
        request_id = f"{self.member_id}:{self._request_sequence}"
        message = dict(payload)
        message["request_id"] = request_id
        try:
            self.requests.process_ack()
            self.requests.send(message)
        except Exception as exc:
            raise RecoveryLineageTransportError(f"cannot send request to recovery authority {self.member_id}: {exc}") from exc

        deadline = time.monotonic() + self.timeout
        last_tick = time.monotonic()
        while time.monotonic() < deadline:
            try:
                self.requests.process_ack()
                now = time.monotonic()
                if now - last_tick >= 0.03:
                    self.requests.tick()
                    last_tick = now
                received = self.responses.receive()
            except Exception as exc:
                raise RecoveryLineageTransportError(
                    f"recovery authority {self.member_id} stream failed: {exc}"
                ) from exc
            if received is not None:
                _sequence, response = received
                if not isinstance(response, Mapping):
                    raise RecoveryLineageTransportError("remote recovery response must be a mapping")
                if response.get("request_id") != request_id or response.get("member_id") != self.member_id:
                    raise RecoveryLineageTransportError("remote recovery response correlation or peer identity mismatch")
                kind = response.get("kind")
                if kind == RECOVERY_LINEAGE_ERROR:
                    raise RecoveryLineageError(str(response.get("error", "remote recovery authority refused request")))
                if kind != expected_kind:
                    raise RecoveryLineageTransportError("remote recovery response phase does not match request")
                return dict(response)
            time.sleep(0.002)
        raise RecoveryLineageTransportError(
            f"recovery authority {self.member_id} did not answer {expected_kind} before the RPC deadline"
        )


class DistributedRecoveryLineageCoordinator(RecoveryLineageCoordinator):
    """Fixed-membership coordinator combining its local owner journal with remote process authorities."""

    def __init__(
        self,
        membership: SeedCommitMembership,
        authorities: Mapping[str, RecoveryLineageAuthority | RecoveryLineagePeerClient],
    ) -> None:
        """Mathematics: require one authority endpoint per configured member, with the owner local and every non-owner remotely bound."""

        if not isinstance(membership, SeedCommitMembership):
            raise RecoveryLineageTransportError("distributed coordinator requires fixed membership")
        if not isinstance(authorities, Mapping):
            raise RecoveryLineageTransportError("distributed coordinator authorities must be a mapping")
        selected: dict[str, RecoveryLineageAuthority | RecoveryLineagePeerClient] = {}
        for member_id in membership.member_ids:
            authority = authorities.get(member_id)
            if authority is None:
                raise RecoveryLineageTransportError(f"distributed coordinator is missing authority {member_id}")
            if member_id == membership.owner_id:
                valid = (
                    isinstance(authority, RecoveryLineageAuthority)
                    and authority.member_id == member_id
                    and authority.membership.digest == membership.digest
                )
            else:
                valid = (
                    isinstance(authority, RecoveryLineagePeerClient)
                    and authority.member_id == member_id
                    and authority.membership.digest == membership.digest
                )
            if not valid:
                raise RecoveryLineageTransportError(f"distributed authority {member_id} is not correctly bound")
            selected[member_id] = authority
        if set(authorities) != set(membership.member_ids):
            raise RecoveryLineageTransportError("distributed coordinator authority set must equal fixed membership")
        self.membership = membership
        self.authorities = dict(sorted(selected.items()))

    def close(self) -> None:
        """Mathematics: release all remote streams while leaving the owner's durable local authority journal intact."""

        for authority in self.authorities.values():
            if isinstance(authority, RecoveryLineagePeerClient):
                authority.close()
