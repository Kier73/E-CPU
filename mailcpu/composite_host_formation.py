"""SAB-011: form a durable E-CPU composite host from incomplete primitive roles.

SAB-010 constructs an arithmetic observer from receiver-bound primitives.
SAB-003 independently qualifies the constructed operation. SAB-004 then
composes that host with independently qualified framed/retention endpoints,
under exact local grants. The caller cannot promote advertisements into grants;
SAB-004's immutable checkpoint and separate commit decision remain authoritative
for this bounded pure mathematical experiment.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import secrets
import threading
from typing import Any, Mapping

from .adaptive_placement import (
    AdaptivePlacement, CompositeIntent, CompiledPlacement, PlacementAuthority,
    PlacementRefused, QualifiedHost, expected_result,
)
from .capability_construction import (
    CapabilityConstructionCompiler, ConstructionRefused,
)
from .active_host_formation import FormationPolicy
from .ground_native_realization import (
    AffineGround, GroundIntention, RealizationRefused, verify_receipt,
)
from .runtime_qualification import (
    REQUEST_KIND, RESPONSE_KIND, QualificationPolicy, QualificationRefused,
    canonical, digest, qualify, _check_response,
)

SCHEMA = "mailcpu.sab011.constructed-composite-host.v1"
COMPUTE_ROLES = frozenset({"observer", "computational_fragment"})


class CompositeFormationRefused(PlacementRefused):
    """Unformed, unqualified, unauthorized, or semantically contradictory host."""


def semantic_intention(intent: CompositeIntent) -> GroundIntention:
    """Project the same mathematical meaning without including host placement."""
    if not isinstance(intent, CompositeIntent):
        raise CompositeFormationRefused("composite formation requires a typed intention")
    return GroundIntention(
        intent.request_id,
        AffineGround(intent.a, intent.c, intent.modulus, intent.x0),
        intent.coordinate,
    )


class ConstructedComputationEndpoint:
    """Expose a SAB-010 formed operation using the closed SAB-003 request vocabulary.

    The endpoint is locally bound, not network authenticated. Its evidence is
    distinguishable from the mTLS-certified relay and durable storage peers.
    Each computation is recompiled, formed, and checked with SAB-010's oracle.
    """

    separate_process_per_exchange = False

    def __init__(
        self, host_id: str, compiler: CapabilityConstructionCompiler,
        *, formation_policy: FormationPolicy | None = None,
    ) -> None:
        if (type(host_id) is not str or not 1 <= len(host_id) <= 100 or
                any(ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._:-" for ch in host_id)):
            raise CompositeFormationRefused("invalid constructed host identity")
        if not isinstance(compiler, CapabilityConstructionCompiler):
            raise CompositeFormationRefused("constructed host requires a receiver-bound capability compiler")
        if formation_policy is not None and not isinstance(formation_policy, FormationPolicy):
            raise CompositeFormationRefused("invalid separate host formation grant")
        self.host_id = host_id
        self.compiler = compiler
        self.formation_policy = formation_policy
        self._lock = threading.RLock()
        self._observations: dict[str, tuple[str, dict[str, Any]]] = {}
        self.last_formation: dict[str, Any] | None = None
        self.execution_count = 0

    @property
    def formation_fingerprint(self) -> str:
        """Bind installed primitives and exact construction/installation authority."""
        return digest({"host": self.host_id,
                       "inventory": self.compiler.inventory.fingerprint,
                       "authority": self.compiler.authority.fingerprint,
                       "installation": self.formation_policy.fingerprint if self.formation_policy else None})

    def exchange(self, request: Mapping[str, Any], *, max_bytes: int) -> Mapping[str, Any]:
        """Perform one fixed operation; never execute source supplied by request."""
        if (not isinstance(request, Mapping) or
                set(request) != {"kind", "host", "nonce", "operation", "payload"} or
                request.get("kind") != REQUEST_KIND or request.get("host") != self.host_id or
                type(request.get("nonce")) is not str or not 8 <= len(request["nonce"]) <= 64 or
                type(request.get("operation")) is not str or not isinstance(request.get("payload"), Mapping) or
                type(max_bytes) is not int or not 256 <= max_bytes <= 8192):
            raise CompositeFormationRefused("constructed endpoint refuses malformed request or resource bound")
        try:
            raw = canonical(dict(request))
        except (TypeError, ValueError) as exc:
            raise CompositeFormationRefused("request is not a finite JSON object") from exc
        if len(raw) + 1 > 8192:
            raise CompositeFormationRefused("request exceeds fixed operation frame")
        token = request["nonce"]
        with self._lock:
            replay = self._observations.get(token)
            if replay is not None:
                if replay[0] != digest(dict(request)):
                    raise CompositeFormationRefused("same host nonce was reused for another request")
                return json.loads(canonical(replay[1]))
            boot = secrets.token_hex(16)
            op = request["operation"]
            reply: dict[str, Any] = {"kind": RESPONSE_KIND, "host": self.host_id,
                "nonce": token, "boot": boot, "ok": False, "result": None, "error": "unsupported"}
            if op == "observe":
                if request["payload"] == {"word": "sab003:observe:hello"}:
                    reply.update(ok=True, result={"word_digest": digest("sab003:observe:hello")}, error=None)
            elif op == "affine_mod":
                p = request["payload"]
                if set(p) != {"a", "c", "mod", "x0", "coordinate"}:
                    raise CompositeFormationRefused("arithmetic input schema malformed")
                try:
                    ground = AffineGround(p["a"], p["c"], p["mod"], p["x0"])
                    intention = GroundIntention("sab011-" + digest({"host":self.host_id,
                        "request":dict(request)})[:32], ground, p["coordinate"])
                    plan = self.compiler.compile(intention)
                    formed, observation = self.compiler.form(
                        intention, plan, formation_policy=self.formation_policy,
                    )
                    # The compiler already checked the independent Ground oracle;
                    # retain the exact output and semantic receipt for provenance.
                    value = observation.payload["output"]["value"]
                    reply.update(ok=True, result={"value":value}, error=None)
                    self.last_formation = {"ground": ground.fingerprint,
                        "coordinate": intention.coordinate, "plan": plan.fingerprint,
                        "receipt": observation.fingerprint, "method": formed.method,
                        "locus": formed.locus, "formation": self.formation_fingerprint}
                    self.execution_count += 1
                except (ConstructionRefused, RealizationRefused, ValueError, TypeError, KeyError) as exc:
                    raise CompositeFormationRefused("constructed computation failed qualification or independent oracle") from exc
            # Unsupported operations must never invoke external source or grant capability.
            if len(canonical(reply)) + 1 > max_bytes:
                raise CompositeFormationRefused("constructed response exceeds caller's budget")
            _check_response(request, reply)
            self._observations[token] = (digest(dict(request)), json.loads(canonical(reply)))
            return reply

    def qualify(self, *, coordinate: int, expires_at: int,
                observer: str = "sab011-constructor") -> QualifiedHost:
        """Actively qualify before a controller can route to this constructed host."""
        policy = QualificationPolicy(frozenset({self.host_id}), observer, expires_at,
                COMPUTE_ROLES, max_calls=4)
        report = qualify(self, policy, coordinate=coordinate,
                         seed="sab011-formed-computation-qualified")
        if "computational_fragment" not in report.payload["verified_roles"]:
            raise CompositeFormationRefused("constructed host did not qualify as computation")
        return QualifiedHost(self, report.payload, policy)


@dataclass(frozen=True)
class CompositeFormationPlan:
    """A proposal binding semantic Ground, SAB-004 placement and formed primitives."""

    placement: CompiledPlacement
    semantic_digest: str
    formation_digest: str

    @property
    def fingerprint(self) -> str:
        return digest({"schema": SCHEMA + ".plan",
                       "placement": self.placement.fingerprint,
                       "semantic": self.semantic_digest,
                       "formation": self.formation_digest})


class CompositeFormationController:
    """Compose SAB-010 constructed arithmetic with admitted SAB-004 remote roles.

    Only actual SAB-003 role qualification, local placement grants, and actual
    receiver-owned transport handlers can effect work. The controller does not
    authenticate network peers itself: network peers should be SAB-005 mTLS
    endpoints; subprocess-only tests retain their weaker evidence grade.
    """

    def __init__(
        self, hosts: Mapping[str, QualifiedHost],
        authority: PlacementAuthority,
        *, quanta: Mapping[tuple[str, str], int] | None = None,
    ) -> None:
        if not hosts or not isinstance(authority, PlacementAuthority):
            raise CompositeFormationRefused("composite requires qualified hosts and exact local authority")
        self.hosts = dict(hosts)
        self.authority = authority
        self.quanta = dict(quanta or {})
        self.placement = AdaptivePlacement(hosts, authority, quanta=quanta)

    def _formation_digest(self, active_hosts: tuple[str, ...]) -> str:
        """Reject compiled plans whose constructed primitive inventory has changed."""
        return digest({"hosts": [
            {"host":host, "formation": self.hosts[host].endpoint.formation_fingerprint}
            for host in sorted(active_hosts)
            if isinstance(self.hosts[host].endpoint, ConstructedComputationEndpoint)
        ]})

    def compile(self, intent: CompositeIntent, *, active_hosts: tuple[str, ...],
                coordinate: int) -> CompositeFormationPlan:
        """Select one existing SAB-004 route and bind all formed primitive evidence."""
        semantic = semantic_intention(intent)
        for host in active_hosts:
            if host not in self.hosts:
                raise CompositeFormationRefused("unknown composite host in active inventory")
            ep = self.hosts[host].endpoint
            if isinstance(ep, ConstructedComputationEndpoint):
                ep.compiler.compile(semantic)
        chosen = self.placement.compile(intent, active_hosts=active_hosts, coordinate=coordinate)
        if not isinstance(self.hosts[chosen.assignment[0]].endpoint, ConstructedComputationEndpoint):
            raise CompositeFormationRefused("computation must be actively formed from primitives")
        return CompositeFormationPlan(chosen, semantic.fingerprint,
                                      self._formation_digest(active_hosts))

    def execute(self, intent: CompositeIntent, plan: CompositeFormationPlan, *,
                active_hosts: tuple[str, ...], coordinate: int, copies: int = 2) -> dict[str, Any]:
        """Revalidate the exact construction and commit SAB-004 durable replicas."""
        fresh = self.compile(intent, active_hosts=active_hosts, coordinate=coordinate)
        if not isinstance(plan, CompositeFormationPlan) or plan.fingerprint != fresh.fingerprint:
            raise CompositeFormationRefused("stale composite formation proposal")
        output = self.placement.execute(intent, fresh.placement, active_hosts=active_hosts,
                                        coordinate=coordinate, copies=copies)
        ep = self.hosts[fresh.placement.assignment[0]].endpoint
        if not isinstance(ep, ConstructedComputationEndpoint) or ep.last_formation is None:
            raise CompositeFormationRefused("computation was not formed under the selected qualified host")
        semantic = semantic_intention(intent)
        if (ep.last_formation["ground"] != semantic.ground.fingerprint or
                ep.last_formation["coordinate"] != intent.coordinate or
                output["result"] != expected_result(intent)):
            raise CompositeFormationRefused("formed computation does not match accepted Ground")
        body = {"schema": SCHEMA, "semantic": semantic.fingerprint,
                "ground": semantic.ground.fingerprint,
                "sab004_receipt": output["receipt_digest"],
                "constructed_host": ep.host_id,
                "construction_evidence": dict(ep.last_formation),
                "checkpoint_digest": output["checkpoint_digest"],
                "decision_digest": output["decision_digest"],
                "replicas": output["replicas"], "result": output["result"],
                "independent_physical_hosts_attested": False,
                "quorum_certificate_supplied": False}
        body["digest"] = digest(body)
        return body

    def resume(self, intent: CompositeIntent, *, active_hosts: tuple[str, ...],
               coordinate: int) -> dict[str, Any]:
        """Restore accepted SAB-004 checkpoint using surviving storage only."""
        result = self.placement.resume(intent, active_hosts=active_hosts, coordinate=coordinate)
        semantic = semantic_intention(intent)
        if result["ground"] != intent.ground or result["result"] != expected_result(intent):
            raise CompositeFormationRefused("recovered checkpoint changed its semantic Ground")
        body = {"schema": SCHEMA + ".resume",
                "semantic": semantic.fingerprint, "ground": semantic.ground.fingerprint,
                "sab004_receipt": result["receipt_digest"],
                "checkpoint_digest": result["checkpoint_digest"],
                "decision_digest": result["decision_digest"],
                "replicas": result["replicas"], "result": result["result"],
                "reexecuted_computation": False,
                "independent_physical_hosts_attested": False,
                "quorum_certificate_supplied": False}
        body["digest"] = digest(body)
        return body
