"""INTERNET-007: two individually qualified public-Internet RFC reference hops.

No E-CPU code is deployed to the RFC site. The local observer alone parses
read-only HTTPS representations, checks actual references and grants no remote
capabilities. Two unobserved relations are resolved in separate attempts;
first result is NOT a completed intention. Replay makes no HTTPS request.

Pilot: RFC 9293 -> RFC 793 -> RFC 761; the latter RFC replaced RFC 761.
These are document *reference* relations, not packet transformations.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from mailcpu.evidence_path_resolver import RouteMetric, RouteMetricKey
from mailcpu.headless import HeadlessOS
from mailcpu.internet_ground_routing import (
    InternetGroundRouter, InternetIntention, InternetObservationCase,
)
from mailcpu.internet_partial_frontier import PartialFrontierQualifier
from mailcpu.internet_prospective_qualification import (
    ProbeOffer, ProbePolicy, ProbeCapture,
)
from mailcpu.kernel import Capability
from mailcpu.public_internet_navigation import (
    Policy, navigate, verify_capsule, rfc_url, strict_loads, canonical,
)
from mailcpu.semantic_translation import RepresentationRef, canonical_value_digest

STAGES = ((9293, 793), (793, 761))
RAW_BUDGET = 1_048_576  # Existing INTERNET-006 total raw capture ceiling.
METRICS = (RouteMetricKey("latency_us", "us"), RouteMetricKey("bytes", "B"))
GROUND = canonical_value_digest({"schema": "mailcpu.internet007.rfc-link-chain.v1",
                                 "stages": [list(x) for x in STAGES]})
CONTEXT = canonical_value_digest({"purpose": "public-rfc-reference-navigation",
                                  "endpoints": [9293, 761]})


def ref(number: int) -> RepresentationRef:
    return RepresentationRef.from_payload("internet.rfc-document-identity", 1,
                                          {"rfc": number})


def stage_policy(start: int, end: int) -> Policy:
    return Policy((start,), end, max_pages=2, max_depth=1,
                  page_budget=800_000, total_budget=950_000)


def run(*, prior_capsules: dict | None = None, fetch=None) -> dict:
    """Observe or independently replay two short source-linked observations.

    The optional fetch is an injected TEST callback, not a remote-supplied
    executable. Production mode uses INTERNET-004's allowlisted HTTPSFetcher.
    """
    if prior_capsules is not None and (
        type(prior_capsules) is not dict or set(prior_capsules) != {"rfc9293", "rfc793"}
    ):
        raise ValueError("replay needs the exact two retained RFC capsules")

    intention = InternetIntention(
        ref(9293), ref(761), GROUND, CONTEXT, 15, METRICS,
        allowed_kinds=frozenset({"rfc"}), max_hops=3, max_expansions=64,
    )
    retained: dict[str, dict] = {}
    offers: list[ProbeOffer] = []
    handlers = {}
    verifiers = {}
    for start, end in STAGES:
        provider = f"rfc{start}"
        policy = stage_policy(start, end)
        offer = ProbeOffer(provider, "rfc", "navigate.references", ref(start), ref(end),
                           GROUND, CONTEXT, 10, 45,
                           (RouteMetric("latency_us", "us", 1_000_000),
                            RouteMetric("bytes", "B", 400_000)),
                           max_response_bytes=850_000, max_requests=2)
        offers.append(offer)
        expected = {"status": "reached_observed_target",
                    "path": [rfc_url(start), rfc_url(end)]}

        def verifier(case: InternetObservationCase, *, name=provider,
                     accepted=expected, rule=policy) -> bool:
            entry = retained.get(name)
            if entry is None or case.case_digest != entry["case_digest"]:
                return False
            try:
                proof = verify_capsule(entry["capsule"], rule,
                                       expected_capsule_digest=entry["capsule"]["capsule_digest"])
            except Exception:
                return False
            return {"status": proof["status"], "path": proof["path"]} == accepted

        verifiers[provider] = verifier

        def handler(proposed: ProbeOffer, allowed: int, *, name=provider,
                    rule=policy, expected_projection=expected) -> ProbeCapture:
            if proposed.digest != next(x for x in offers if x.provider_id == name).digest:
                raise ValueError("unexpected hypothetical provider or intention")
            if prior_capsules is None:
                capsule = navigate(rule, fetch=fetch)
            else:
                capsule = prior_capsules[name]
            # INTERNET-004 independently reconstructs original raw HTML bytes,
            # links, source parent relationship and actual observed target.
            proof = verify_capsule(capsule, rule)
            actual = {"status": proof["status"], "path": proof["path"]}
            if actual != expected_projection:
                raise ValueError("RFC reference not actually observed")
            nbytes = proof["observed_bytes"]
            if nbytes > allowed or len(capsule["visits"]) > proposed.max_requests:
                raise ValueError("raw RFC observation exceeded receiver quota")
            elapsed = sum(v["elapsed_ns"] for v in capsule["visits"])
            observed_case = InternetObservationCase(
                provider_id=name, kind="rfc", operation="navigate.references",
                source=proposed.source, target=proposed.target,
                ground_digest=GROUND, context_digest=CONTEXT,
                observed_at=15, expires_at=45,
                evidence_digest=capsule["capsule_digest"],
                expected_projection=expected_projection,
                observed_projection=actual,
                costs=(RouteMetric("latency_us", "us", max(1, elapsed // 1000)),
                       RouteMetric("bytes", "B", nbytes)),
            )
            retained[name] = {"capsule": capsule, "case_digest": observed_case.case_digest}
            return ProbeCapture(observed_case, nbytes, len(capsule["visits"]), elapsed,
                                canonical_value_digest({
                                    "raw_sha256": [v["content_sha256"] for v in capsule["visits"]],
                                    "capsule": capsule["capsule_digest"],
                                }))

        handlers[provider] = handler

    router = InternetGroundRouter(verifiers)
    os = HeadlessOS()
    pid = os.environment.kernel.spawn(
        "internet007-rfc-observer",
        capabilities=tuple(Capability(f"/internet/rfc/{offer.provider_id}",
                                      frozenset({"observe"})) for offer in offers),
        parent_pid=os.environment.init_pid,
    )
    qualifier = PartialFrontierQualifier(
        router, handlers,
        ProbePolicy(frozenset(handlers), max_attempts=2,
                    total_response_budget=RAW_BUDGET),
        tuple(offers),
    )
    result = qualifier.run(intention, os, pid)
    if (result["last_status"] != "qualified_and_routed" or
        [step["status"] for step in result["steps"]] !=
            ["case_accepted_not_selected", "qualified_and_routed"] or
        [x["provider"] for x in result["steps"][-1]["result"]["selected"]] !=
            ["rfc9293", "rfc793"]):
        raise RuntimeError("two-stage RFC intention was not independently qualified")
    return {"schema": "mailcpu.internet007.rfc-partial-frontier-pilot.v1",
            "source_identity": [9293, 793, 761],
            "capsules": {name: retained[name]["capsule"] for name in ("rfc9293", "rfc793")},
            "qualified_result": result,
            "live_https_observed": prior_capsules is None and fetch is None,
            "receiver_external_content_pins": False,
            "passive_fiber_executed_reference_navigation": False}


def main() -> None:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("mode", choices=("observe", "replay"))
    cli.add_argument("--input", type=Path)
    cli.add_argument("--output", required=True, type=Path)
    a = cli.parse_args()
    if a.mode == "observe":
        if a.input is not None:
            cli.error("observe never accepts untrusted replay input")
        result = run()
    else:
        if a.input is None:
            cli.error("offline replay needs the original live report")
        original = strict_loads(a.input.read_bytes())
        if (original.get("schema") != "mailcpu.internet007.rfc-partial-frontier-pilot.v1"
                or original.get("live_https_observed") is not True):
            raise ValueError("input is not a documented live HTTP observation")
        result = run(prior_capsules=original["capsules"])
        if (result["qualified_result"]["event_chain_tip"] !=
                original["qualified_result"]["event_chain_tip"] or
                result["qualified_result"]["last_status"] !=
                original["qualified_result"]["last_status"]):
            raise ValueError("replayed frontier/observation evidence differs")
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_bytes(canonical(result) + b"\n")
    print(json.dumps({
        "status": result["qualified_result"]["last_status"],
        "probes": [s["decision"]["provider_id"] for s in result["qualified_result"]["steps"]],
        "bytes": result["qualified_result"]["consumed_response_bytes"],
        "real_https": result["live_https_observed"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
