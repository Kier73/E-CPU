"""IPS-004: realize intention-synthesized virtual Grounds through admitted hosts.

This bridge uses IPS-003's exact generated operator word, E-CPU's native
NavigableComputationDAG, SAB-003 qualified endpoint contracts (including mTLS
endpoints), SAB-008 Ground receipts, and the existing Virtual Layer Hypervisor.

A checkpoint rechecks the exact intermediate computation before allowing a
later qualified host to receive the next value. Endpoint qualification does
not attest independent physical hosts, and digest equality is not a signature.
No host is probed or contacted during plan compilation or checkpoint replay.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Mapping, Sequence

from .computation_dag import NavigableComputationDAG
from .generative_ground_construction import (
    AffineBehaviorIntention, AffinePrimitive, GroundConstructionPlan,
    compile_ground_dag, verify_ground_plan,
)
from .ground_native_realization import (
    AffineGround, FixedInterpreterRealizer, GroundIntention, RealizationPolicy,
    verify_receipt,
)
from .runtime_qualification import QualificationEndpoint, QualificationPolicy, verify_report
from .seed import SystemIdentity
from .semantic_translation import canonical_value_digest
from .virtual_layer import (
    OperatorRegistry, OperatorSpec, VirtualBudget, VirtualGroundRef,
    VirtualLayerRuntime, VirtualLayerWorkload, VirtualOperatorRef,
)
from .headless import HeadlessOS

SCHEMA = "mailcpu.ips004.qualified-generated-ground.v1"
OPERATOR_ID = "ips004.affine_step"
_NODE_PREFIX = "ips004.stage."
_MAX_STAGES = 32


class QualifiedGroundExecutionError(ValueError):
    """Generated work, receiver authority, host qualification or checkpoint refused."""


def _copy(value: Any) -> Any:
    """Return canonical detached JSON without accepting untyped objects."""
    return json.loads(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False))


def _operator_spec() -> OperatorSpec:
    """Return one fixed and replay-safe Virtual Layer arithmetic operator contract."""
    return OperatorSpec(
        OPERATOR_ID, 1, "Qualified generated affine Ground stage",
        "object", "object", ("cpu",), required_rights=frozenset({"compute"}),
        base_energy=1, energy_per_byte=1,
        max_input_bytes=2048, max_output_bytes=16384,
        deterministic=True, effect_mode="pure",
    )


def _policy_record(policy: RealizationPolicy) -> dict[str, Any]:
    """Retain only local public policy terms needed for historical verification."""
    return {
        "allowed": [list(pair) for pair in sorted(policy.allowed)],
        "expires_at": policy.expires_at, "max_events": policy.max_events,
        "max_bytes": policy.max_bytes,
    }


def _parse_policy(value: Mapping[str, Any]) -> RealizationPolicy:
    """Rebuild SAB-008 local permission without treating a checkpoint as a grant."""
    if not isinstance(value, Mapping) or set(value) != {
        "allowed", "expires_at", "max_events", "max_bytes"
    }:
        raise QualifiedGroundExecutionError("invalid retained local permission schema")
    try:
        pairs = value["allowed"]
        if not isinstance(pairs, list) or any(
            not isinstance(pair, list) or len(pair) != 2 or
            any(type(s) is not str for s in pair) for pair in pairs
        ):
            raise ValueError("permission tuples malformed")
        return RealizationPolicy(frozenset((a, b) for a, b in pairs),
                                 value["expires_at"], value["max_events"],
                                 value["max_bytes"])
    except (ValueError, TypeError, KeyError) as exc:
        raise QualifiedGroundExecutionError("malformed retained permission") from exc


def _qualification_record(policy: QualificationPolicy) -> dict[str, Any]:
    """Persist the qualification constraints, not transport credentials."""
    return {
        "allowed_hosts": sorted(policy.allowed_hosts),
        "observer_id": policy.observer_id,
        "expires_at": policy.expires_at,
        "permitted_roles": sorted(policy.permitted_roles),
        "max_calls": policy.max_calls,
        "max_response_bytes": policy.max_response_bytes,
    }


def _parse_qualification(value: Mapping[str, Any]) -> QualificationPolicy:
    """Reconstruct exact locally declared finite qualification conditions."""
    if not isinstance(value, Mapping) or set(value) != {
        "allowed_hosts", "observer_id", "expires_at", "permitted_roles",
        "max_calls", "max_response_bytes",
    }:
        raise QualifiedGroundExecutionError("invalid retained qualification schema")
    try:
        return QualificationPolicy(
            frozenset(value["allowed_hosts"]), value["observer_id"],
            value["expires_at"], frozenset(value["permitted_roles"]),
            value["max_calls"], value["max_response_bytes"],
        )
    except (TypeError, ValueError, KeyError) as exc:
        raise QualifiedGroundExecutionError("invalid retained qualification policy") from exc


@dataclass(frozen=True)
class QualifiedStageHost:
    """One locally selected, independently probed receiver process or TLS peer.

    The endpoint remains locally controlled. Its declared source class is
    advisory; mTLS authentication comes only from the endpoint's actual
    connection validation. Receiver Hypervisor rights are checked separately.
    """

    locus: str
    endpoint: QualificationEndpoint
    qualification_report: Mapping[str, Any]
    qualification_policy: QualificationPolicy
    realization_policy: RealizationPolicy

    def __post_init__(self) -> None:
        """Refuse a mismatched endpoint or unverified fixed computation role."""
        if (not isinstance(self.locus, str) or self.endpoint.host_id != self.locus
                or not isinstance(self.qualification_policy, QualificationPolicy)
                or not isinstance(self.realization_policy, RealizationPolicy)):
            raise QualifiedGroundExecutionError("host binding is not typed or locally owned")
        report = self.qualification_report
        verify_report(report, self.qualification_policy, coordinate=report["coordinate"])
        if (report["host"] != self.locus
                or "computational_fragment" not in report["verified_roles"]
                or report["coordinate"] > 1 or report["expires_at"] < 1):
            raise QualifiedGroundExecutionError("host is not qualified for requested stage")
        self.realization_policy.permits(self.locus, "interpreter", 1)


def _ground_for_step(primitive: AffinePrimitive, value: int,
                     index: int) -> GroundIntention:
    """Describe one typed scalar operation at logical coordinate one."""
    return GroundIntention(
        f"ips004-stage-{index:03d}",
        AffineGround(primitive.multiplier, primitive.offset,
                     primitive.modulus, value), 1,
    )


def _input_for_stage(
    plan: GroundConstructionPlan, intention: AffineBehaviorIntention,
    primitive: AffinePrimitive, index: int, value: int,
    predecessor_digest: str | None,
) -> dict[str, Any]:
    """Bind typed intermediate input to exact predecessor evidence."""
    return {
        "plan_digest": plan.digest, "intention_digest": intention.digest,
        "stage_index": index, "primitive_name": primitive.name,
        "primitive_digest": primitive.digest, "modulus": intention.modulus,
        "value": value, "predecessor_receipt_digest": predecessor_digest,
    }


def _workload(
    session: "QualifiedGroundExecution", primitive: AffinePrimitive,
    index: int, input_value: Mapping[str, Any],
) -> VirtualLayerWorkload:
    """Construct a portable, fully Ground-pinned one-stage Virtual Layer request."""
    return VirtualLayerWorkload(
        f"ips004-{session.plan.digest[:20]}-{index:03d}",
        session.system, session.ground,
        {"goal": {"plan_digest": session.plan.digest, "stage_index": index,
                  "desired_primitive_digest": primitive.digest}},
        (VirtualOperatorRef(OPERATOR_ID, 1, "cpu"),),
        dict(input_value),
        VirtualBudget(100000, 100000, 1000),
        index + 1,
        (f"ips004-node-{index:03d}",),
        1,
    )


class QualifiedGroundExecution:
    """Prefix-committing generated Ground runner with exact detached checkpoints.

    Recovery from a snapshot never calls a previous host or executes a stored
    operation; it reconstructs the entire mathematical and observational
    prefix, including the native DAG, before accepting the next stage.
    """

    def __init__(
        self,
        plan: GroundConstructionPlan,
        intention: AffineBehaviorIntention,
        primitives: Sequence[AffinePrimitive],
        system: SystemIdentity,
        ground: VirtualGroundRef,
        *,
        max_states: int = 4096,
        max_depth: int = 12,
    ) -> None:
        """Bind a previously proved synthesis to a current admitted virtual Ground."""
        if (not verify_ground_plan(plan, intention, primitives,
                                   max_states=max_states, max_depth=max_depth)
                or plan.status != "constructed_exact_affine_ground"
                or not isinstance(system, SystemIdentity)
                or not isinstance(ground, VirtualGroundRef)
                or len(plan.primitive_names) > _MAX_STAGES):
            raise QualifiedGroundExecutionError("non-current generated Ground or system binding")
        self.plan = plan
        self.intention = intention
        self.primitives = tuple(primitives)
        self.system = system
        self.ground = ground
        self.max_states = max_states
        self.max_depth = max_depth
        self.dag = compile_ground_dag(plan, intention, primitives)
        self.stages: list[dict[str, Any]] = []

    @property
    def complete(self) -> bool:
        """Check native DAG completion, independent of current host liveness."""
        return self.dag.is_complete

    @property
    def value(self) -> int | None:
        """Read the checked final committed value, if all required stages finished."""
        if not self.dag.is_complete:
            return None
        if not self.plan.primitive_names:
            return self.intention.query_input
        return int(self.dag.result(f"ips003.stage.{len(self.plan.primitive_names)-1:03d}")["value"])

    def _state(self) -> dict[str, Any]:
        """Compose a canonical portable snapshot without duplicating the DAG authority."""
        return {
            "schema": SCHEMA, "plan_digest": self.plan.digest,
            "intention_digest": self.intention.digest,
            "system": self.system.snapshot(), "ground": self.ground.to_dict(),
            "max_states": self.max_states, "max_depth": self.max_depth,
            "dag_snapshot": self.dag.snapshot(), "stages": _copy(self.stages),
            "claim": "receiver-checked historical execution; no remote physical host attestation",
        }

    def checkpoint(self) -> dict[str, Any]:
        """Return a content-addressed, detached checkpoint suitable for persistence."""
        payload = self._state()
        return {"payload": payload, "digest": canonical_value_digest(payload)}

    @classmethod
    def from_checkpoint(
        cls,
        plan: GroundConstructionPlan,
        intention: AffineBehaviorIntention,
        primitives: Sequence[AffinePrimitive],
        snapshot: Mapping[str, Any],
    ) -> "QualifiedGroundExecution":
        """Replay and check the exact prefix without touching prior observer-hosts."""
        if (not isinstance(snapshot, Mapping)
                or set(snapshot) != {"payload", "digest"}
                or not isinstance(snapshot["payload"], Mapping)):
            raise QualifiedGroundExecutionError("checkpoint envelope malformed")
        payload = snapshot["payload"]
        if (type(snapshot["digest"]) is not str
                or snapshot["digest"] != canonical_value_digest(dict(payload))
                or set(payload) != {
                    "schema", "plan_digest", "intention_digest", "system",
                    "ground", "max_states", "max_depth", "dag_snapshot", "stages", "claim",
                } or payload["schema"] != SCHEMA):
            raise QualifiedGroundExecutionError("checkpoint identity or schema mismatch")
        if (payload["plan_digest"] != plan.digest
                or payload["intention_digest"] != intention.digest
                or payload["claim"] != "receiver-checked historical execution; no remote physical host attestation"):
            raise QualifiedGroundExecutionError("checkpoint changed the intended Ground")
        session = cls(
            plan, intention, primitives,
            SystemIdentity.from_snapshot(payload["system"]),
            VirtualGroundRef.from_dict(payload["ground"]),
            max_states=payload["max_states"], max_depth=payload["max_depth"],
        )
        records = payload["stages"]
        if not isinstance(records, list) or len(records) > len(plan.primitive_names):
            raise QualifiedGroundExecutionError("invalid saved stage prefix")
        by_name = {p.name: p for p in session.primitives}
        value = intention.query_input
        prev = None
        spec = _operator_spec()
        for index, item in enumerate(records):
            if (not isinstance(item, Mapping)
                    or set(item) != {
                        "index", "host", "qualification_policy",
                        "qualification_report", "local_policy", "stage_receipt",
                        "hypervisor_effect", "execution_fingerprint",
                    } or type(item["index"]) is not int or item["index"] != index):
                raise QualifiedGroundExecutionError("non-prefix or untyped retained stage")
            primitive = by_name[plan.primitive_names[index]]
            local_policy = _parse_policy(item["local_policy"])
            qpolicy = _parse_qualification(item["qualification_policy"])
            report = item["qualification_report"]
            verify_report(report, qpolicy, coordinate=report["coordinate"])
            if (report["host"] != item["host"]
                    or "computational_fragment" not in report["verified_roles"]
                    or report["coordinate"] > 1 or report["expires_at"] < 1):
                raise QualifiedGroundExecutionError("retained host qualification mismatch")
            local_policy.permits(item["host"], "interpreter", 1)
            stage_intent = _ground_for_step(primitive, value, index)
            verified = verify_receipt(item["stage_receipt"], stage_intent, local_policy)
            if (verified["locus"] != item["host"]
                    or verified["method"] != "interpreter"
                    or verified["evidence"]["qualification"] != report["report_digest"]):
                raise QualifiedGroundExecutionError("stage evidence differs from its host")
            observed = verified["output"]["value"]
            effect = item["hypervisor_effect"]
            if (not isinstance(effect, Mapping)
                    or effect.get("kind") != "virtual_layer.operator_result"
                    or effect.get("operator_id") != OPERATOR_ID
                    or effect.get("operator_contract_digest") != spec.digest
                    or effect.get("node_id") != f"ips004-node-{index:03d}"
                    or effect.get("ground") != session.ground.to_dict()
                    or effect.get("logical_time") != index + 1
                    or effect.get("result") != {
                        "value": observed, "stage_receipt": dict(verified)
                    } or effect.get("result_digest") != canonical_value_digest(effect["result"])):
                raise QualifiedGroundExecutionError("retained Hypervisor effect mismatch")
            input_value = _input_for_stage(
                plan, intention, primitive, index, value, prev
            )
            workload = _workload(session, primitive, index, input_value)
            if (effect.get("workload_digest") != workload.digest
                    or effect.get("input_digest") != canonical_value_digest(input_value)):
                raise QualifiedGroundExecutionError("retained typed predecessor input mismatch")
            node_id = f"ips003.stage.{index:03d}"
            session.dag.commit(node_id, {
                "input": value, "value": observed,
                "primitive_digest": primitive.digest,
                "stage_receipt_digest": verified["receipt_digest"],
                "hypervisor_effect_digest": canonical_value_digest(dict(effect)),
            })
            value, prev = observed, verified["receipt_digest"]
            session.stages.append(_copy(dict(item)))
        if not plan.primitive_names and payload["dag_snapshot"]["state"]["commits"]:
            session.dag.commit(
                "ips003.identity",
                {"input": value, "value": value},
            )
        if session.dag.snapshot() != payload["dag_snapshot"]:
            raise QualifiedGroundExecutionError("rehashed checkpoint DAG disagrees with computed stages")
        return session

    def finish_identity(self) -> dict[str, Any]:
        """Commit an identity description without inventing a remote effect."""
        if self.plan.primitive_names or self.complete:
            raise QualifiedGroundExecutionError("identity completion is not applicable")
        self.dag.commit(
            "ips003.identity",
            {"input": self.intention.query_input, "value": self.intention.query_input},
        )
        return self.checkpoint()

    def advance(
        self,
        operating_system: HeadlessOS,
        pid: int,
        host: QualifiedStageHost,
    ) -> dict[str, Any]:
        """Perform exactly one dependency-ready stage through native Hypervisor.

        The handler closes over one **receiver-selected and already qualified**
        endpoint. The description cannot choose arbitrary Python or shell code.
        No stage is sent when the receiver lacks an admitted Virtual Ground or
        capability. A failed operation leaves the DAG and prefix unchanged.
        """
        if self.complete or not self.plan.primitive_names:
            raise QualifiedGroundExecutionError("no pending generated operation")
        if not isinstance(host, QualifiedStageHost):
            raise QualifiedGroundExecutionError("stage needs a qualified host")
        index = len(self.stages)
        node_id = f"ips003.stage.{index:03d}"
        ready = self.dag.ready_nodes()
        if len(ready) != 1 or ready[0].node_id != node_id:
            raise QualifiedGroundExecutionError("native DAG predecessor frontier mismatch")
        primitive = {p.name: p for p in self.primitives}[self.plan.primitive_names[index]]
        value = (self.intention.query_input if not index
                 else int(self.dag.result(f"ips003.stage.{index-1:03d}")["value"]))
        prev = None if not index else self.stages[-1]["stage_receipt"]["receipt_digest"]
        input_value = _input_for_stage(
            self.plan, self.intention, primitive, index, value, prev
        )
        workload = _workload(self, primitive, index, input_value)
        host.realization_policy.permits(host.locus, "interpreter", 1)
        verify_report(
            host.qualification_report, host.qualification_policy,
            coordinate=host.qualification_report["coordinate"],
        )

        def handler(argument: Any, supplied_workload: VirtualLayerWorkload) -> dict[str, Any]:
            """Execute only the bound native mathematical primitive on this host."""
            if (dict(argument) != input_value
                    or supplied_workload.digest != workload.digest):
                raise QualifiedGroundExecutionError("operator received foreign stage input")
            receipt = FixedInterpreterRealizer(
                host.locus, host.endpoint, host.qualification_report,
                host.qualification_policy,
            ).observe(_ground_for_step(primitive, value, index), host.realization_policy)
            verified = verify_receipt(
                receipt, _ground_for_step(primitive, value, index),
                host.realization_policy,
            )
            return {"value": verified["output"]["value"], "stage_receipt": verified}

        registry = OperatorRegistry()
        registry.register(_operator_spec(), handler)
        runtime = VirtualLayerRuntime(
            registry, f"ips004-node-{index:03d}", frozenset({"cpu"}),
        )
        outcome = runtime.execute_operator(
            operating_system, pid, "ips004-origin", f"ips004.step.{index:03d}",
            index + 1, workload.logical_time, workload, OPERATOR_ID,
        )
        if (not outcome.executed or outcome.action.value != "allow"
                or outcome.effect is None):
            raise QualifiedGroundExecutionError("receiver Hypervisor denied stage")
        effect = dict(outcome.effect)
        result = effect.get("result")
        if (not isinstance(result, Mapping)
                or set(result) != {"value", "stage_receipt"}
                or type(result["value"]) is not int):
            raise QualifiedGroundExecutionError("native operator returned no typed result")
        checked = verify_receipt(
            result["stage_receipt"], _ground_for_step(primitive, value, index),
            host.realization_policy,
        )
        if checked["output"]["value"] != result["value"]:
            raise QualifiedGroundExecutionError("native result differs from Ground receipt")
        # Preserve a detached, replayable prefix. This is an observed
        # computation output, *not* a certificate of network reliability.
        self.dag.commit(node_id, {
            "input": value, "value": result["value"],
            "primitive_digest": primitive.digest,
            "stage_receipt_digest": checked["receipt_digest"],
            "hypervisor_effect_digest": canonical_value_digest(effect),
        })
        self.stages.append(_copy({
            "index": index, "host": host.locus,
            "qualification_policy": _qualification_record(host.qualification_policy),
            "qualification_report": dict(host.qualification_report),
            "local_policy": _policy_record(host.realization_policy),
            "stage_receipt": checked, "hypervisor_effect": effect,
            "execution_fingerprint": outcome.fingerprint,
        }))
        snapshot = self.checkpoint()
        self.from_checkpoint(self.plan, self.intention, self.primitives, snapshot)
        return snapshot
