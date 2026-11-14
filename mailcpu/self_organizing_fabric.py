"""SAB-006: reconcile authenticated peer leases with empirically qualified hosts.

A ComputationalFabricDirectory is the *only* source of active peer membership.
Peer snapshots locate candidate observers; receiver-owned policies authorize
finite probes, and SAB-004 still independently authorizes every operation.
This is a bounded orchestration layer, not an independent trust system.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

from .adaptive_placement import (
    AdaptivePlacement, CompiledPlacement, CompositeIntent, PlacementAuthority,
    PlacementRefused, QualifiedHost,
)
from .computational_fabric import ComputationalFabricDirectory, ComputationalPeerSnapshot
from .federated_placement import MutualTLSQualificationEndpoint
from .runtime_qualification import (
    QualificationEndpoint, QualificationPolicy, QualificationRefused, digest,
    qualify, verify_report,
)

SCHEMA = "mailcpu.sab006.self-organizing-fabric.v1"
_MAX_PEERS = 32


class ReconciliationRefused(PlacementRefused):
    """A discovery observation, local grant, or placement epoch is not valid."""


@dataclass(frozen=True)
class PeerRoleEvidence:
    """Receiver-evaluated role evidence pinned to a native peer snapshot revision."""

    peer_id: str
    revision: int
    snapshot_digest: str
    report_digest: str
    roles: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        """Expose only finite evidence identifiers and tested roles, never authority."""
        return {"peer_id": self.peer_id, "revision": self.revision,
                "snapshot_digest": self.snapshot_digest, "report_digest": self.report_digest,
                "roles": list(self.roles)}


@dataclass(frozen=True)
class FederatedView:
    """One ephemeral materialization of active leases, policy and tested roles."""

    evidence: tuple[PeerRoleEvidence, ...]
    missing_peers: tuple[str, ...]
    directory_digest: str
    authority_digest: str
    coordinate: int

    @property
    def active_hosts(self) -> tuple[str, ...]:
        """Return only currently qualified peer IDs in deterministic order."""
        return tuple(item.peer_id for item in self.evidence)

    @property
    def fingerprint(self) -> str:
        """Bind the present directory membership and local qualification evidence."""
        return digest({"schema": SCHEMA, "evidence": [item.to_dict() for item in self.evidence],
                       "missing": list(self.missing_peers), "directory": self.directory_digest,
                       "authority": self.authority_digest, "coordinate": self.coordinate})


@dataclass(frozen=True)
class FederatedPlacement:
    """A SAB-004 placement additionally bound to a specific directory view."""

    view_fingerprint: str
    intention_fingerprint: str
    placement: CompiledPlacement

    @property
    def fingerprint(self) -> str:
        """Bind semantic intention, qualified directory epoch, and concrete route."""
        return digest({"schema": SCHEMA, "view": self.view_fingerprint,
                       "intention": self.intention_fingerprint,
                       "placement": self.placement.fingerprint})


class SelfOrganizingFabric:
    """Compile fresh authenticated peer observations into a SAB-004 controller.

    One peer corresponds to one SAB-005 host ID in this experimental bridge.
    A host must be explicitly permitted by both the local qualification
    policy and the SAB-004 operation-grant catalogue. The native directory
    keeps its own TLS validation, lease deadlines and anti-rollback rules.
    """

    def __init__(
        self,
        directory: ComputationalFabricDirectory,
        endpoint_for: Callable[[ComputationalPeerSnapshot], QualificationEndpoint],
        policy_for: Callable[[str], QualificationPolicy],
        authority: PlacementAuthority,
        *,
        quanta: Mapping[tuple[str, str], int] | None = None,
        include_local: bool = False,
        discovery_service: object | None = None,
    ) -> None:
        """Bind native discovery and receiver-owned endpoint/policy factories."""
        if not isinstance(directory, ComputationalFabricDirectory):
            raise ReconciliationRefused("native ComputationalFabricDirectory required")
        if not callable(endpoint_for) or not callable(policy_for):
            raise ReconciliationRefused("locally installed endpoint and policy factories required")
        if not isinstance(authority, PlacementAuthority) or type(include_local) is not bool:
            raise ReconciliationRefused("invalid local grant or local-peer inclusion")
        if discovery_service is not None and not callable(getattr(discovery_service, "refresh_all", None)):
            raise ReconciliationRefused("discovery service requires native refresh_all interface")
        self.directory = directory
        self.endpoint_for = endpoint_for
        self.policy_for = policy_for
        self.authority = authority
        self.quanta = dict(quanta or {})
        self.include_local = include_local
        self.discovery_service = discovery_service
        self._cache: dict[str, tuple[tuple[object, ...], QualifiedHost]] = {}
        self._history: dict[str, QualifiedHost] = {}
        self._high_water: dict[str, tuple[int, str]] = {}
        self._last_coordinate = -1

    def refresh(self, *, coordinate: int, force_probes: bool = False) -> FederatedView:
        """Refresh configured authenticated peers, then materialize only live evidence.

        Expired peers disappear from active_hosts even if a previous qualification
        report survives in history. A changed peer revision requires fresh probes.
        """
        if self.discovery_service is not None:
            self.discovery_service.refresh_all()
        return self.reconcile(coordinate=coordinate, force_probes=force_probes)

    def reconcile(self, *, coordinate: int, force_probes: bool = False) -> FederatedView:
        """Intersect native active leases with mTLS identity, empirical roles and grants."""
        if type(coordinate) is not int or not 0 <= coordinate <= 10**18:
            raise ReconciliationRefused("invalid reconciliation coordinate")
        if coordinate < self._last_coordinate:
            raise ReconciliationRefused("reconciliation coordinates cannot move backwards")
        if type(force_probes) is not bool:
            raise ReconciliationRefused("force_probes must be Boolean")
        self._last_coordinate = coordinate
        snapshots = self.directory.active_snapshots
        if len(snapshots) > _MAX_PEERS:
            raise ReconciliationRefused("active peer inventory exceeds bounded experiment")
        trust = self.directory.trusted_peers
        latest: dict[str, ComputationalPeerSnapshot] = {}
        for snap in snapshots:
            if not isinstance(snap, ComputationalPeerSnapshot) or snap.peer_id in latest:
                raise ReconciliationRefused("directory returned duplicate or malformed peer")
            if snap.peer_id == self.directory.local_peer_id:
                if not self.include_local:
                    continue
            elif trust.get(snap.peer_id) != snap.endpoint.tls_server_name:
                raise ReconciliationRefused("active peer is not bound to pinned TLS DNS identity")
            prior = self._high_water.get(snap.peer_id)
            if prior is not None and (snap.revision < prior[0] or
                                      (snap.revision == prior[0] and snap.digest != prior[1])):
                raise ReconciliationRefused("peer revision rollback or equivocation in active view")
            latest[snap.peer_id] = snap
        evidence: list[PeerRoleEvidence] = []
        missing: list[str] = []
        # A failed probe cannot replace a prior high-water snapshot or create a role.
        for peer_id, snap in sorted(latest.items()):
            self._high_water[peer_id] = (snap.revision, snap.digest)
            if not any(host == peer_id for host, _op in self.authority.granted):
                missing.append(peer_id)
                continue
            endpoint = self.endpoint_for(snap)
            if getattr(endpoint, "host_id", None) != peer_id:
                raise ReconciliationRefused("endpoint host differs from authenticated peer")
            if peer_id != self.directory.local_peer_id:
                if not isinstance(endpoint, MutualTLSQualificationEndpoint):
                    raise ReconciliationRefused("remote host requires the SAB-005 mutual-TLS adapter")
                if (endpoint.server_dns != snap.endpoint.tls_server_name or
                        endpoint.address[0] != snap.endpoint.endpoint_host):
                    raise ReconciliationRefused("runtime TLS identity/address differs from native directory")
            policy = self.policy_for(peer_id)
            if (not isinstance(policy, QualificationPolicy) or
                    policy.allowed_hosts != frozenset({peer_id})):
                raise ReconciliationRefused("host qualification is not scoped to exact local permission")
            endpoint_pin = (type(endpoint).__qualname__,
                            getattr(endpoint, "server_dns", None),
                            getattr(endpoint, "address", None),
                            getattr(endpoint, "command", None))
            cache_key = (snap.digest, policy.fingerprint, endpoint_pin)
            entry = self._cache.get(peer_id)
            qualified: QualifiedHost | None = None
            if not force_probes and entry is not None and entry[0] == cache_key:
                try:
                    entry[1].validate(coordinate=coordinate)
                    qualified = QualifiedHost(endpoint, entry[1].report, policy)
                except PlacementRefused:
                    pass
            if qualified is None:
                try:
                    candidate = qualify(endpoint, policy, coordinate=coordinate,
                                        seed=digest({"schema": SCHEMA, "peer": peer_id,
                                                     "snapshot": snap.digest,
                                                     "coordinate": coordinate}))
                    verify_report(candidate.payload, policy, coordinate=coordinate)
                    qualified = QualifiedHost(endpoint, candidate.payload, policy)
                    qualified.validate(coordinate=coordinate)
                except (QualificationRefused, PlacementRefused, TimeoutError, OSError):
                    self._cache.pop(peer_id, None)
                    missing.append(peer_id)
                    continue
                self._cache[peer_id] = (cache_key, qualified)
            self._history[peer_id] = qualified
            evidence.append(PeerRoleEvidence(peer_id, snap.revision, snap.digest,
                                             qualified.report["report_digest"],
                                             tuple(sorted(qualified.report["verified_roles"]))))
        # Direct snapshots are authentication/advertisement inputs; transport links
        # are NOT treated as direct user-data channels or executable processors.
        state = {"peer_snapshots": [
                     {"id": peer_id, "revision": snap.revision, "digest": snap.digest}
                     for peer_id, snap in sorted(latest.items())],
                 "directory_checkpoint": self.directory.checkpoint()["digest"]}
        return FederatedView(tuple(evidence), tuple(sorted(missing)),
                             digest(state), self.authority.fingerprint, coordinate)

    def _controller(self) -> AdaptivePlacement:
        """Retain historical replica identities for SAB-004 decision verification."""
        if not self._history:
            raise ReconciliationRefused("no previously qualified host bindings")
        costs = {key: value for key, value in self.quanta.items() if key[0] in self._history}
        return AdaptivePlacement(self._history, self.authority, quanta=costs)

    def compile(self, intent: CompositeIntent, *, coordinate: int) -> FederatedPlacement:
        """Construct a fresh qualified SAB-004 plan from the active native directory."""
        if not isinstance(intent, CompositeIntent):
            raise ReconciliationRefused("typed CompositeIntent required")
        view = self.reconcile(coordinate=coordinate)
        placement = self._controller().compile(intent, active_hosts=view.active_hosts,
                                               coordinate=coordinate)
        return FederatedPlacement(view.fingerprint, intent.fingerprint, placement)

    def execute(self, intent: CompositeIntent, selected: FederatedPlacement, *,
                coordinate: int, copies: int = 1) -> dict[str, object]:
        """Fail closed on any changed directory, qualifier, grant, or selected path."""
        if not isinstance(selected, FederatedPlacement) or not isinstance(intent, CompositeIntent):
            raise ReconciliationRefused("typed intention and placement required")
        view = self.reconcile(coordinate=coordinate)
        if (selected.view_fingerprint != view.fingerprint or
                selected.intention_fingerprint != intent.fingerprint):
            raise ReconciliationRefused("stale federated plan: directory/qualification/authority changed")
        receipt = self._controller().execute(intent, selected.placement,
                                             active_hosts=view.active_hosts,
                                             coordinate=coordinate, copies=copies)
        # A lease/revision change during execution must not be acknowledged as
        # success, even though already-issued effects cannot be rolled back.
        after = self.reconcile(coordinate=coordinate)
        if after.fingerprint != view.fingerprint:
            raise ReconciliationRefused("federated membership changed during execution")
        return {**receipt, "federated_view": view.fingerprint,
                "federated_placement": selected.fingerprint}

    def resume(self, intent: CompositeIntent, *, coordinate: int) -> dict[str, object]:
        """Recover from a currently qualified durable peer without new computation."""
        view = self.reconcile(coordinate=coordinate)
        receipt = self._controller().resume(intent, active_hosts=view.active_hosts,
                                            coordinate=coordinate)
        return {**receipt, "federated_view": view.fingerprint}