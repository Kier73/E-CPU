"""PATH-GROUND-004: bind measured intermediate TTL transitions to native E-CPU observer paths.

This is an adapter to existing ObserverPathStage/ObserverContract/ObserverReceipt,
NOT another router or authority.  Each raw Ethernet ingress/egress pair is
reconstructed against exact sender and receiver frames first.  Then the
receiver-installed policy must explicitly admit the local capture provenance.

A native ObserverReceipt is content evidence, NOT an independently signed
router attestation.  A trusted capture callback returning True only proves
whatever provenance policy that receiver actually installed.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Callable, Mapping, Sequence

from .ip_router_path_ground import (
    IP_HOPS, LOCUS_TTL_STEPS, ROUTES, SCHEMA, TTL_PROBES,
    ObservedRoute, RouterGroundRefused, RouterTTLGround,
    parse_ethernet_ipv4_udp, probe_payload, verify_router_route,
)
from .observer_orbit import ObserverContract, ObserverReceipt
from .observer_path_evidence import (
    ObserverPathStage, VerifiedObserverPath,
    check_observer_path_receipt, verify_observer_path,
)
from .semantic_translation import (
    ObservationContract, RepresentationRef, canonical_value_digest,
)
from .substrate_bootstrap import ChannelObservation

PACKET_KIND = "pg4.ipv4.datagram"
CAPTURE_KIND = "pg4.ethernet.frame"
GROUND_KIND = "pg4.ttl.ground"
OBSERVATION = ObservationContract.from_definition(
    "pg4.observe.ttl", 1,
    {"projection": "actual_ip_ttl_and_raw_frame_digest",
     "measured_transition": "per_intermediate_locus",
     "bridge": "no_ipv4_ttl_change", "router": "ipv4_ttl_minus_one",
     "comparison": "exact"},
)


@dataclass(frozen=True)
class NativeRouterPathBinding:
    """A packet-specific native receiver-verified observer path and its evidence anchors."""

    route_id: str
    sequence: int
    initial_ttl: int
    destination_ttl: int
    route_evidence_digest: str
    ground_digest: str
    verified: VerifiedObserverPath
    stages: tuple[ObserverPathStage, ...]

    def __post_init__(self) -> None:
        """Mathematics: retain only the admitted packet coordinate and native verified path."""
        if (self.route_id not in ROUTES or type(self.sequence) is not int
                or not 0 <= self.sequence < len(TTL_PROBES)
                or self.initial_ttl != TTL_PROBES[self.sequence]
                or self.destination_ttl != self.initial_ttl - IP_HOPS[self.route_id]
                or not isinstance(self.verified, VerifiedObserverPath)
                or not isinstance(self.stages, tuple)
                or len(self.verified.stages) != len(self.stages)):
            raise RouterGroundRefused("native packet path binding has invalid coordinates")

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: retain a portable content-bound path without serializing trusted policy."""
        return {
            "schema": SCHEMA + ".native-observer-path",
            "route_id": self.route_id,
            "sequence": self.sequence,
            "initial_ttl": self.initial_ttl,
            "destination_ttl": self.destination_ttl,
            "route_evidence_digest": self.route_evidence_digest,
            "ground_digest": self.ground_digest,
            "native_path": self.verified.to_dict(),
            "authority": "receiver_policy_callback_not_remote_router_signature",
        }


def _packet_state(
    packet: Mapping[str, Any], *, expected_payload: bytes,
) -> RepresentationRef:
    """Mathematics: project only IP/UDP state that must persist across passive carriers."""
    if packet["payload_hex"] != expected_payload.hex():
        raise RouterGroundRefused("in-network raw packet differs from admitted source data")
    return RepresentationRef.from_payload(PACKET_KIND, 1, {
        "ttl": packet["ttl"],
        "source_ip": packet["source_ip"],
        "destination_ip": packet["destination_ip"],
        "source_port": packet["source_port"],
        "destination_port": packet["destination_port"],
        "payload_hex": packet["payload_hex"],
    })


def _raw_frame_ref(raw_hex: str, side: str) -> RepresentationRef:
    """Mathematics: independently bind the exact captured Ethernet bytes and interface side."""
    return RepresentationRef.from_payload(
        CAPTURE_KIND, 1, {"frame_hex": raw_hex, "side": side},
    )


def _edge(
    route_id: str, seq: int, source: str, target: str,
    state: RepresentationRef, ordinal: int, route_digest: str,
    length: int,
) -> ObserverPathStage:
    """Mathematics: native passive carrier preserves one exact packet representation."""
    if source == target:
        raise RouterGroundRefused("carrier must connect distinct observed loci")
    identifier = f"pg4.{route_id}.packet{seq}.edge{ordinal}"
    channel = ChannelObservation(
        channel_id=identifier, source=source, target=target,
        carries=(PACKET_KIND,), estimated_quanta=1,
        observed_at=1, expires_at=1,
        evidence_digest=canonical_value_digest({
            "route": route_id, "sequence": seq, "ordinal": ordinal,
            "packet": state.to_dict(), "route_evidence": route_digest,
        }),
        max_payload_bytes=length,
    )
    return ObserverPathStage(
        "carrier", source, target, state, state,
        channel=channel, payload_bytes=length,
    )


def _observation(
    locus: str, route: str, seq: int, before: RepresentationRef,
    after: RepresentationRef, ground: RepresentationRef,
    context_digest: str, projection: Mapping[str, Any],
    evidence: Sequence[RepresentationRef], mode: str,
) -> ObserverPathStage:
    """Mathematics: retain an observed local relation without forging router authority."""
    contract = ObserverContract(
        locus, 1, before, ground, OBSERVATION, context_digest,
    )
    receipt = ObserverReceipt.issue(
        contract, operation_id=f"pg4.{route}.packet{seq}.{mode}",
        input_digest=before.content_digest,
        projection_value=dict(projection),
        subject_state_before_digest=before.content_digest,
        subject_state_after_digest=after.content_digest,
        evidence=tuple(evidence),
    )
    return ObserverPathStage(
        mode, locus, locus, before, after,
        contract=contract, receipt=receipt,
    )


def bind_router_packet_observer_path(
    ground: RouterTTLGround, route_id: str, sequence: int,
    source: Mapping[str, Any], receiver: Mapping[str, Any],
    routers: Sequence[Mapping[str, Any]], *,
    admit_capture: Callable[[ObservedRoute], bool],
    receiver_policy_digest: str,
) -> NativeRouterPathBinding:
    """Mathematics: form an exact native path only after raw bytes and receiver policy agree.

    A trusted callback MUST be receiver-installed; this function does not
    authenticate the kernel namespace, a remote packet sensor, or any remote
    signing identity. It does not treat hashes as identity authentication.
    """
    if not isinstance(ground, RouterTTLGround):
        raise RouterGroundRefused("native typed router Ground required")
    if type(route_id) is not str or route_id not in ROUTES:
        raise RouterGroundRefused("unrecognized route")
    if type(sequence) is not int or not 0 <= sequence < len(TTL_PROBES):
        raise RouterGroundRefused("packet sequence outside observed probe set")
    if not callable(admit_capture):
        raise RouterGroundRefused("receiver-owned provenance admission callback required")
    observed = verify_router_route(route_id, source, receiver, routers)
    if not any(
        candidate.route_id == observed.route_id and candidate == observed
        for candidate in ground.routes
    ):
        raise RouterGroundRefused("raw packet evidence does not match admitted Ground route")
    if admit_capture(observed) is not True:
        raise RouterGroundRefused("receiver did not admit this raw capture provenance")

    # Bind this particular packet coordinate; abstracting away Ethernet MAC
    # changes does NOT hide an IP/UDP identity or TTL change.
    sent = source["frames"][sequence]
    received = receiver["frames"][sequence]
    initial_ttl = sent["sent_ttl"]
    destination_ttl = received["received_ttl"]
    packet_bytes = len(probe_payload(sequence))
    origin = "pg4.source." + route_id
    destination = "pg4.receiver." + route_id
    computational_ground = RepresentationRef.from_payload(
        GROUND_KIND, 1, {
            "mathematical_ground_digest": ground.ground_digest,
            "scope": ground.scope,
            "operator": "per_ipv4_router_ttl_step",
        },
    )
    context_digest = canonical_value_digest({
        "schema": SCHEMA + ".packet-context",
        "route_id": route_id, "sequence": sequence,
        "raw_route_digest": observed.evidence_digest,
    })
    state = RepresentationRef.from_payload(PACKET_KIND, 1, {
        "ttl": initial_ttl,
        "source_ip": source["source_ip"],
        "destination_ip": source["destination_ip"],
        "source_port": source["source_port"],
        "destination_port": source["destination_port"],
        "payload_hex": probe_payload(sequence).hex(),
    })
    previous_locus = origin
    previous_ip_id: int | None = None
    stages: list[ObserverPathStage] = []

    for index, (router, locus_name) in enumerate(
        zip(routers, ROUTES[route_id], strict=True),
    ):
        locus = "pg4." + locus_name
        entries = {
            x["side"]: x
            for x in router["frames"]
            if x["side"] in ("ingress", "egress")
            and parse_ethernet_ipv4_udp(bytes.fromhex(x["raw_hex"]))["seq"] == sequence
        }
        if set(entries) != {"ingress", "egress"}:
            raise RouterGroundRefused("missing native ingress/egress packet witness")
        before_frame = bytes.fromhex(entries["ingress"]["raw_hex"])
        after_frame = bytes.fromhex(entries["egress"]["raw_hex"])
        incoming = parse_ethernet_ipv4_udp(before_frame)
        outgoing = parse_ethernet_ipv4_udp(after_frame)
        if (previous_ip_id is not None and incoming["ip_id"] != previous_ip_id):
            raise RouterGroundRefused("inter-router IP identification changed in transit")
        before = _packet_state(incoming, expected_payload=probe_payload(sequence))
        after = _packet_state(outgoing, expected_payload=probe_payload(sequence))
        if before != state:
            raise RouterGroundRefused("adjacent carrier did not preserve the observed IP packet state")
        stages.append(_edge(
            route_id, sequence, previous_locus, locus, state,
            len(stages), observed.evidence_digest, packet_bytes,
        ))
        expected_step = LOCUS_TTL_STEPS[locus_name]
        if outgoing["ttl"] - incoming["ttl"] != expected_step:
            raise RouterGroundRefused("native router/bridge operation contradicts raw Ethernet bytes")
        stages.append(_observation(
            locus, route_id, sequence, before, after,
            computational_ground, context_digest,
            {
                "seq": sequence, "ingress_ttl": incoming["ttl"],
                "egress_ttl": outgoing["ttl"], "step": expected_step,
                "ingress_sha256": sha256(before_frame).hexdigest(),
                "egress_sha256": sha256(after_frame).hexdigest(),
                "mechanism": "ipv4_kernel_forward" if expected_step == -1 else "l2_kernel_bridge",
            },
            (
                _raw_frame_ref(entries["ingress"]["raw_hex"], "ingress"),
                _raw_frame_ref(entries["egress"]["raw_hex"], "egress"),
            ),
            "transform" if expected_step != 0 else "observe",
        ))
        state = after
        previous_ip_id = outgoing["ip_id"]
        previous_locus = locus

    if state != RepresentationRef.from_payload(PACKET_KIND, 1, {
        "ttl": destination_ttl,
        "source_ip": receiver["frames"][sequence]["source_ip"],
        "destination_ip": receiver["destination_ip"],
        "source_port": receiver["frames"][sequence]["source_port"],
        "destination_port": source["destination_port"],
        "payload_hex": receiver["frames"][sequence]["payload_hex"],
    }):
        raise RouterGroundRefused("receiver's actual ancillary TTL disagrees with final path state")
    stages.append(_edge(
        route_id, sequence, previous_locus, destination, state,
        len(stages), observed.evidence_digest, packet_bytes,
    ))
    receiver_ref = RepresentationRef.from_payload(
        "pg4.receiver.ancillary", 1, received,
    )
    stages.append(_observation(
        destination, route_id, sequence, state, state,
        computational_ground, context_digest,
        {"seq": sequence, "actual_received_ttl": destination_ttl,
         "source_port": received["source_port"],
         "receiver_record_digest": receiver_ref.content_digest},
        (receiver_ref,), "observe",
    ))
    immutable_stages = tuple(stages)
    allowed_carriers = tuple(stage for stage in immutable_stages if stage.mode == "carrier")
    allowed_observers = tuple(stage for stage in immutable_stages if stage.mode != "carrier")
    verified = verify_observer_path(
        immutable_stages, ground=computational_ground,
        context_digest=context_digest,
        receiver_policy_digest=receiver_policy_digest,
        observed_at=1,
        # The receiver first validated actual raw evidence and explicitly
        # admitted provenance. Never accept an arbitrary serialized stage.
        verify_carrier=lambda stage: stage in allowed_carriers,
        verify_observer=lambda stage: stage in allowed_observers,
    )
    if not check_observer_path_receipt(
        verified, immutable_stages,
        verify_carrier=lambda stage: stage in allowed_carriers,
        verify_observer=lambda stage: stage in allowed_observers,
    ):
        raise RouterGroundRefused("reconstructed native path receipt changed during verification")
    return NativeRouterPathBinding(
        route_id, sequence, initial_ttl, destination_ttl,
        observed.evidence_digest, ground.ground_digest,
        verified, immutable_stages,
    )


def verify_router_packet_path_binding(
    binding: NativeRouterPathBinding,
    ground: RouterTTLGround, route_id: str, sequence: int,
    source: Mapping[str, Any], receiver: Mapping[str, Any],
    routers: Sequence[Mapping[str, Any]], *,
    admit_capture: Callable[[ObservedRoute], bool],
    receiver_policy_digest: str,
) -> bool:
    """Mathematics: recompute the full native witness from original raw bytes and a fresh policy decision."""
    if not isinstance(binding, NativeRouterPathBinding):
        return False
    try:
        checked = bind_router_packet_observer_path(
            ground, route_id, sequence, source, receiver, routers,
            admit_capture=admit_capture,
            receiver_policy_digest=receiver_policy_digest,
        )
        return binding == checked
    except (RouterGroundRefused, ValueError, KeyError, TypeError, IndexError):
        return False
