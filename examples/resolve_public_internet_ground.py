"""INTERNET-005: plan a receiver-verified RFC observation via native E-CPU.

First run INTERNET-004's `observe` command to actually fetch public HTML.
This example only replays the captured bytes and *selects* a qualified path.
It never claims to perform a second live network operation or issue authority.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from mailcpu.headless import HeadlessOS
from mailcpu.internet_ground_routing import (
    InternetGroundRouter, InternetIntention, admitted_rfc_observation,
)
from mailcpu.kernel import Capability
from mailcpu.public_internet_navigation import (
    NavigationRefused, Policy, rfc_url, strict_loads,
)
from mailcpu.evidence_path_resolver import RouteMetric, RouteMetricKey
from mailcpu.semantic_translation import RepresentationRef, canonical_value_digest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--expected-capsule-sha256", required=True,
                        help="Receiver-owned digest from a separate admitted observation")
    parser.add_argument("--seed", type=int, default=9293)
    parser.add_argument("--target", type=int, default=793)
    parser.add_argument("--max-pages", type=int, default=4)
    parser.add_argument("--max-depth", type=int, default=2)
    args = parser.parse_args()
    policy = Policy((args.seed,), args.target, max_pages=args.max_pages,
                    max_depth=args.max_depth)
    capsule = strict_loads(args.file.read_bytes())
    context = canonical_value_digest({"intent": "rfc-navigation", "seed": args.seed,
                                      "target": args.target})
    source = RepresentationRef.from_payload("internet.rfc-request", 1, {
        "seed": args.seed, "target": args.target, "ground": policy.as_dict()})
    target = RepresentationRef.from_payload("internet.rfc-observed-path", 1, {
        "seed": args.seed, "target": args.target,
        "expected_path": [rfc_url(args.seed), rfc_url(args.target)]})
    case, verifier = admitted_rfc_observation(
        capsule, policy, expected_capsule_digest=args.expected_capsule_sha256,
        expected_path=(rfc_url(args.seed), rfc_url(args.target)),
        provider_id="rfceditor", source=source, target=target,
        context_digest=context, observed_at=10, expires_at=20,
        costs=(RouteMetric("latency_us", "us", sum(
                   max(1, int(x["elapsed_ns"] / 1000)) for x in capsule["visits"])),
               RouteMetric("bytes", "B", sum(x["size_bytes"] for x in capsule["visits"]))),
    )
    router = InternetGroundRouter({"rfceditor": verifier})
    router.add(case)
    os = HeadlessOS()
    # This test fixture explicitly gives its LOCAL receiving process the
    # observation right. Real deployments must use the existing host's
    # independently approved process capabilities, not user input or web data.
    pid = os.environment.kernel.spawn(
        "rfc-observer-test", capabilities=(
            Capability("/internet/rfc/rfceditor", frozenset({"observe"})),
        ), parent_pid=os.environment.init_pid)
    intent = InternetIntention(source, target, canonical_value_digest(policy.as_dict()),
                               context, 15,
                               (RouteMetricKey("latency_us", "us"),
                                RouteMetricKey("bytes", "B")),
                               allowed_kinds=frozenset({"rfc"}))
    result = router.resolve(intent, os, pid)
    if result["status"] != "found":
        raise NavigationRefused("receiver could not select the pinned RFC observation")
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
