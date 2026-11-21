"""INTERNET-006: select an RFC Ground observation *before* performing HTTPS.

The receiver's source/target, RFC policy, provider allowlist and credentials
are installed in this script, not obtained from a web page. A real GET occurs
only after native path-gap planning and current HeadlessOS capability checks.
The raw RFC capsule can be replay-verified without network access. A content
SHA discovered during the first read is NOT an externally pinned source hash.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

# Original INTERNET-006 CLI is also invoked directly by hosted INTERNET-005
# public HTTPS workflows, where the scripts directory is sys.path[0].
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mailcpu.headless import HeadlessOS
from mailcpu.kernel import Capability
from mailcpu.internet_ground_routing import (
    InternetGroundRouter, InternetIntention, admitted_rfc_observation,
)
from mailcpu.internet_prospective_qualification import (
    ProbeOffer, ProbePolicy, ProbeCapture, ProspectiveQualifier,
)
from mailcpu.public_internet_navigation import (
    Policy, navigate, verify_capsule, rfc_url, strict_loads, canonical,
)
from mailcpu.evidence_path_resolver import RouteMetric, RouteMetricKey
from mailcpu.semantic_translation import RepresentationRef, canonical_value_digest


LIMIT = 1_048_576


def setup(policy: Policy):
    """Produce exact receiver-owned intention and ONE hypothetical RFC offer."""
    source = RepresentationRef.from_payload("internet.rfc-request", 1, {
        "seed": policy.seeds[0], "target": policy.target, "ground": policy.as_dict(),
    })
    target = RepresentationRef.from_payload("internet.rfc-observed-path", 1, {
        "seed": policy.seeds[0], "target": policy.target,
        "expected_path": [rfc_url(policy.seeds[0]), rfc_url(policy.target)],
    })
    context = canonical_value_digest({"intent": "rfc-navigation", "seed": policy.seeds[0],
                                      "target": policy.target})
    intent = InternetIntention(source, target,
                               canonical_value_digest(policy.as_dict()), context, 15,
                               (RouteMetricKey("latency_us", "us"),
                                RouteMetricKey("bytes", "B")),
                               allowed_kinds=frozenset({"rfc"}))
    offer = ProbeOffer("rfceditor", "rfc", "navigate.references", source, target,
                       intent.ground_digest, context, 10, 30,
                       (RouteMetric("latency_us", "us", 2_000_000),
                        RouteMetric("bytes", "B", 900_000)),
                       max_response_bytes=LIMIT, max_requests=4)
    return intent, offer


def observe_or_replay(*, policy: Policy, capsule: dict | None = None) -> dict:
    """Actual first read or offline replay. Rereading never happens at verify."""
    intent, offer = setup(policy)
    retained: dict[str, Any] = {}
    expected_path = (rfc_url(policy.seeds[0]), rfc_url(policy.target))

    def receiver_verify(case):
        # Installed before I/O; no untrusted response may supply a callable.
        verifier = retained.get("verifier")
        return (verifier is not None and case.case_digest == retained.get("case_digest")
                and verifier(case) is True)

    router = InternetGroundRouter({"rfceditor": receiver_verify})
    os = HeadlessOS()
    pid = os.environment.kernel.spawn(
        "internet006-rfc-receiver", capabilities=(
            Capability("/internet/rfc/rfceditor", frozenset({"observe"})),
        ), parent_pid=os.environment.init_pid)

    def installed_probe(proposed: ProbeOffer, byte_ceiling: int) -> ProbeCapture:
        assert proposed.digest == offer.digest
        observed = navigate(policy) if capsule is None else capsule
        # Recompute the entire link chain from byte-level evidence; a
        # source-page content pin would be checked *here* if supplied by the
        # receiver from an independent source. This pilot has no such pin.
        proof = verify_capsule(observed, policy)
        total_bytes = proof["observed_bytes"]
        if total_bytes > byte_ceiling:
            raise ValueError("receiver raw response budget exhausted")
        new_case, verifier = admitted_rfc_observation(
            observed, policy, expected_capsule_digest=observed["capsule_digest"],
            expected_path=expected_path, provider_id="rfceditor",
            source=intent.source, target=intent.target, context_digest=intent.context_digest,
            observed_at=15, expires_at=30,
            costs=(RouteMetric("latency_us", "us", sum(
                max(1, int(x["elapsed_ns"] / 1000)) for x in observed["visits"])),
                   RouteMetric("bytes", "B", total_bytes)),
        )
        retained.update({"capsule": observed, "case_digest": new_case.case_digest,
                         "verifier": verifier})
        return ProbeCapture(new_case, total_bytes, len(observed["visits"]),
                            sum(x["elapsed_ns"] for x in observed["visits"]),
                            canonical_value_digest({"capsule_sha256": observed["capsule_digest"],
                                                    "raw_content": [x["content_sha256"] for x in observed["visits"]]}))

    qualifier = ProspectiveQualifier(
        router, {"rfceditor": installed_probe},
        ProbePolicy(frozenset({"rfceditor"}), max_attempts=1,
                    total_response_budget=LIMIT), (offer,))
    result = qualifier.run(intent, os, pid)
    if result["last_status"] != "qualified_and_routed":
        raise RuntimeError("RFC Internet Ground was not qualified: " + result["last_status"])
    return {"schema": "mailcpu.internet-prospective-rfc-pilot.v1",
            "prospective": result,
            "capsule": retained["capsule"],
            "receiver_independent_content_pin": False,
            "public_https_network_performed": capsule is None,
            "path_evidence_grade": "local_https_observation_with_offline_semantic_replay",
            "passive_network_arithmetic_claimed": False}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("mode", choices=("observe", "replay"))
    p.add_argument("--seed", type=int, default=9293)
    p.add_argument("--target", type=int, default=793)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--input", type=Path)
    args = p.parse_args()
    policy = Policy((args.seed,), args.target, max_pages=4, max_depth=2)
    if args.mode == "observe":
        if args.input is not None:
            p.error("observe forbids --input to prevent mixing replay and network evidence")
        result = observe_or_replay(policy=policy)
        output = result
    else:
        if args.input is None:
            p.error("replay requires a previously captured report")
        original = strict_loads(args.input.read_bytes())
        if (original.get("schema") != "mailcpu.internet-prospective-rfc-pilot.v1"
                or original.get("public_https_network_performed") is not True):
            raise ValueError("replay requires an actual recorded live observation")
        output = observe_or_replay(policy=policy, capsule=original["capsule"])
        if output["prospective"]["last_status"] != original["prospective"]["last_status"]:
            raise ValueError("replayed outcome differs")
        if output["capsule"] != original["capsule"]:
            raise ValueError("source capsule differs during replay")
        # Elapsed and discovery provenance are carried from the original;
        # the replay itself makes no claim to have contacted the RFC service.
        output = {"status": "offline_replay_verified",
                  "original_capsule_digest": original["capsule"]["capsule_digest"],
                  "selected_route": output["prospective"]["steps"][-1]["result"]["selected"],
                  "network_requests_performed": 0}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(canonical(output) + b"\n")
    print(json.dumps({"status": output.get("status", output.get("prospective", {}).get("last_status")),
                      "output": str(args.output)}, sort_keys=True))


if __name__ == "__main__":
    main()
