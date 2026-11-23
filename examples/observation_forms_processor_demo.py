"""Reproduce ONP-001: observation → constructed processor → realized result.

The source's unknown law exists only inside the sensor closure. The observer
does not read that closure or receive a precompiled operation list.
No network or unverified host privileges are used in this local experiment.
"""
from __future__ import annotations

import json

from mailcpu.evidence_path_resolver import RouteMetric
from mailcpu.generative_ground_construction import AffinePrimitive
from mailcpu.ground_native_realization import RealizationPolicy
from mailcpu.inverse_architecture_synthesis import ProposedRelation
from mailcpu.observation_formed_processor import (
    ObserverConstructionIntention, ProbeOffer, realize_observed_processor,
    sign_observation, verify_observed_processor,
)
from mailcpu.semantic_translation import RepresentationRef

SOURCE = "c" * 64
KEY = bytes(range(32))


def main() -> None:
    intention = ObserverConstructionIntention(
        relation=ProposedRelation(
            "e"*64,
            RepresentationRef.from_payload("onp001.state", 1, {"kind":"original"}),
            RepresentationRef.from_payload("onp001.state", 1, {"kind":"realized"}),
            "f"*64, "a"*64, "d"*64,
            (RouteMetric("latency_us", "us", 1),),
        ),
        source_digest=SOURCE, observer_id="observer-01",
        authority_digest="b"*64, modulus=13, query_input=9,
    )
    offers = tuple(
        ProbeOffer(SOURCE, "actual-source-sensor", x, cost)
        for x, cost in ((0,1),(1,1),(2,3),(4,8))
    )
    primitives = (
        AffinePrimitive("first", 13, 3, 2),
        AffinePrimitive("second", 13, 8, 5),
        AffinePrimitive("optional", 13, 1, 1),
    )
    actual_source_probes = []

    # This closed-over actual source law is held ONLY by the sensor. The
    # intention, candidate-law planner and processor builder cannot inspect it.
    def independent_source_observer(intent, offer, nonce, now):
        actual_source_probes.append(offer.point)
        return sign_observation(
            intent, offer, nonce, (11*offer.point+8)%13,
            issued_at=now, expires_at=now+30, secret=KEY,
        )

    policy = RealizationPolicy(frozenset({("onp001-local","port")}),
                               expires_at=10)
    report = realize_observed_processor(
        intention, offers, {"actual-source-sensor":independent_source_observer},
        {"actual-source-sensor":KEY}, primitives, policy, clock=lambda:10,
    )
    assert verify_observed_processor(
        report, intention, offers, primitives, policy,
        {"actual-source-sensor":KEY}, now=10,
    )
    assert actual_source_probes == [0,1,2]
    assert report.realization.output == (11*9+8)%13
    print(json.dumps({
        "experiment": "ONP-001",
        "status": "OBSERVATION_CONSTRUCTED_AND_REALIZED_PROCESSOR",
        "requested_target": intention.query_input,
        "observed_source_coordinates": actual_source_probes,
        "source_target_directly_observed": False,
        "finite_candidate_laws": report.sufficiency_plan["candidate_count"],
        "remaining_laws": report.sufficiency_resolution["remaining_candidates"],
        "derived_law": report.sufficiency_resolution["result"],
        "generated_native_operations": list(report.construction_plan.primitive_names),
        "native_execution_frames": len(report.realization.port_frames),
        "realized_value": report.realization.output,
        "receipt_digest": report.digest,
        "independently_verified": True,
    }, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
