"""IPS-006: reconnect E-CPU generated Grounds to independent mTLS lineage services.

This module never implements votes, commits, host qualification or execution.
It binds externally provisioned, pinned authority identities to E-CPU's
existing DistributedRecoveryLineageCoordinator, then hands that coordinator
to IPS-005's already quorum-fenced generated Ground publisher.

An unavailable peer is *omitted* only from the current connection set, never
from durable SeedCommitMembership, quorum mathematics, or owner term.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import ssl
from typing import Sequence

from .fenced_generated_ground import FencedGroundHead, FencedGroundLineage
from .generative_ground_construction import (
    AffineBehaviorIntention, AffinePrimitive, GroundConstructionPlan,
)
from .recovery_lineage import RecoveryLineageAuthority
from .recovery_lineage_transport import (
    DistributedRecoveryLineageCoordinator,
    RecoveryLineagePeerClient,
    RecoveryLineageTransportError,
)
from .seed_commit_quorum import SeedCommitMembership


class GeneratedGroundAuthorityError(ValueError):
    """An authority configuration or authenticated network bind was refused."""


@dataclass(frozen=True)
class PinnedRecoveryAuthority:
    """One explicitly provisioned remote member and pinned server DNS identity."""

    member_id: str
    host: str
    port: int
    server_dns: str

    def __post_init__(self) -> None:
        """Reject untyped, unaddressable or ambiguous service descriptions."""
        if (not isinstance(self.member_id, str) or
            not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", self.member_id)):
            raise GeneratedGroundAuthorityError("invalid configured authority ID")
        if (not isinstance(self.host, str) or not self.host or
            len(self.host) > 253 or any(c.isspace() for c in self.host)):
            raise GeneratedGroundAuthorityError("invalid configured authority address")
        if type(self.port) is not int or not 1 <= self.port <= 65535:
            raise GeneratedGroundAuthorityError("invalid authority port")
        if (not isinstance(self.server_dns, str) or
            len(self.server_dns) > 253 or not self.server_dns or
            not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]*", self.server_dns)):
            raise GeneratedGroundAuthorityError("invalid pinned certificate DNS name")


@dataclass
class GeneratedGroundQuorumConnection:
    """An open owner+remote quorum connection and its existing IPS-005 publisher."""

    publisher: FencedGroundLineage
    coordinator: DistributedRecoveryLineageCoordinator
    unavailable_members: tuple[str, ...]

    @property
    def connected_members(self) -> tuple[str, ...]:
        """Name configured authority identities with a currently bound stream."""
        return tuple(sorted(self.coordinator.authorities))

    def restore_latest(self) -> FencedGroundHead:
        """Read quorum high-water and reconstruct its exact externally saved DAG."""
        return self.publisher.restore_latest()

    def close(self) -> None:
        """Close only this session's remote network streams, not authority journals."""
        self.coordinator.close()

    def __enter__(self) -> "GeneratedGroundQuorumConnection":
        """Make ownership of this session's authenticated streams explicit."""
        return self

    def __exit__(self, _exc_type: object, _exc: object, _trace: object) -> None:
        """Release all peer streams even when an operation is refused."""
        self.close()


def connect_generated_ground_quorum(
    membership: SeedCommitMembership,
    owner_journal: str | Path,
    pinned_peers: Sequence[PinnedRecoveryAuthority],
    client_tls_context: ssl.SSLContext,
    artifact_directory: str | Path,
    plan: GroundConstructionPlan,
    intention: AffineBehaviorIntention,
    primitives: Sequence[AffinePrimitive],
    *,
    degraded: bool = False,
    timeout: float = 0.8,
    handshake_timeout: float = 0.8,
) -> GeneratedGroundQuorumConnection:
    """Connect exactly configured mTLS authorities and preserve quorum size.

    With degraded=True, an unreachable configured peer can be absent from the
    *connected* subset. A reconstructed coordinator still requires the fixed
    owner, the original membership and an unchanged strict-majority quorum
    for every read or commit. With degraded=False, every configured peer must
    authenticate successfully or setup fails.
    """
    if not isinstance(membership, SeedCommitMembership):
        raise GeneratedGroundAuthorityError("fixed SeedCommitMembership is required")
    if (not isinstance(client_tls_context, ssl.SSLContext) or
        client_tls_context.verify_mode != ssl.CERT_REQUIRED or
        not client_tls_context.check_hostname):
        raise GeneratedGroundAuthorityError("authenticated TLS peer and DNS validation are required")
    if type(degraded) is not bool:
        raise GeneratedGroundAuthorityError("degraded mode must be an explicit boolean")
    for name, value in (("timeout", timeout), ("handshake timeout", handshake_timeout)):
        if (not isinstance(value, (int, float)) or isinstance(value, bool)
            or not 0 < value <= 10):
            raise GeneratedGroundAuthorityError(f"invalid {name}")
    if not isinstance(pinned_peers, (tuple, list)) or any(
        not isinstance(peer, PinnedRecoveryAuthority) for peer in pinned_peers
    ):
        raise GeneratedGroundAuthorityError("remote authority descriptions must be typed")
    expected = set(membership.member_ids) - {membership.owner_id}
    by_id = {peer.member_id: peer for peer in pinned_peers}
    if (len(by_id) != len(pinned_peers) or set(by_id) != expected or
        len({peer.server_dns for peer in pinned_peers}) != len(pinned_peers)):
        raise GeneratedGroundAuthorityError(
            "configured network endpoints must represent every fixed non-owner exactly once"
        )

    owner = RecoveryLineageAuthority(
        membership, membership.owner_id, owner_journal,
    )
    peers: dict[str, RecoveryLineagePeerClient] = {}
    unavailable: list[str] = []
    try:
        for member_id in sorted(expected):
            peer = by_id[member_id]
            try:
                bound = RecoveryLineagePeerClient.connect_mutual_tls(
                    membership, member_id, peer.host, peer.port,
                    client_tls_context,
                    server_hostname=peer.server_dns,
                    timeout=timeout,
                    handshake_timeout=handshake_timeout,
                )
            except RecoveryLineageTransportError:
                if not degraded:
                    raise
                unavailable.append(member_id)
                continue
            peers[member_id] = bound

        authorities: dict[str, RecoveryLineageAuthority | RecoveryLineagePeerClient] = {
            membership.owner_id: owner,
            **peers,
        }
        coordinator = (
            DistributedRecoveryLineageCoordinator.with_available_peers(
                membership, authorities,
            ) if degraded else DistributedRecoveryLineageCoordinator(
                membership, authorities,
            )
        )
        publisher = FencedGroundLineage(
            coordinator, artifact_directory, plan, intention, primitives,
        )
        return GeneratedGroundQuorumConnection(
            publisher, coordinator, tuple(unavailable),
        )
    except Exception:
        for client in peers.values():
            client.close()
        raise
