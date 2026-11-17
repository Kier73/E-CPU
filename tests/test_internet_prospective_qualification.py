"""INTERNET-006: real native E-CPU resolver and receiver policy integration.

Local isolated contract runners may use stubs; the checked-in hosted suite
imports the real E-CPU HeadlessOS, EvidencePathResolver and semantic types.
"""
from __future__ import annotations

from dataclasses import replace
import unittest

from mailcpu.evidence_path_resolver import EvidenceStrength, RouteMetric, RouteMetricKey
from mailcpu.headless import HeadlessOS
from mailcpu.internet_ground_routing import InternetGroundRouter, InternetIntention, InternetObservationCase
from mailcpu.internet_prospective_qualification import (
    ProbeOffer, ProbePolicy, ProbeCapture, ProspectiveQualifier, ProspectiveRefused,
)
from mailcpu.kernel import Capability
from mailcpu.semantic_translation import RepresentationRef, canonical_value_digest


G = canonical_value_digest({"ground": "pinned-source", "v": 1})
C = canonical_value_digest({"intent": "bounded-observation", "v": 1})
METRICS = (RouteMetricKey("latency_us", "us"), RouteMetricKey("bytes", "B"))
PROJECTION = {"content": "verified-fixed-representation"}


def ref(name):
    return RepresentationRef.from_payload("internet006.synthetic-state", 1, {"state": name})


def metric(latency, nbytes):
    return (RouteMetric("latency_us", "us", latency), RouteMetric("bytes", "B", nbytes))


def case(provider, kind, operation, source, target, latency=10, nbytes=200, *, projection=PROJECTION, at=10, end=45):
    return InternetObservationCase(
        provider, kind, operation, ref(source), ref(target), G, C, at, end,
        canonical_value_digest({"source-pinned-record": provider, "target": target}),
        PROJECTION, projection, metric(latency, nbytes))


def offer(c, latency, nbytes, *, max_bytes=256, max_requests=4, at=10, end=40):
    return ProbeOffer(c.provider_id, c.kind, c.operation, c.source, c.target,
                      c.ground_digest, c.context_digest, at, end, metric(latency, nbytes),
                      max_response_bytes=max_bytes, max_requests=max_requests)


def os_with(*rights):
    os = HeadlessOS()
    pid = os.environment.kernel.spawn(
        "internet006-receiver", parent_pid=os.environment.init_pid,
        capabilities=tuple(Capability(f"/internet/{kind}/{name}", frozenset({"observe"}))
                           for name, kind in rights),
    )
    return os, pid


def intent(*, now=15, kinds=None, minimum=EvidenceStrength.PAIRED_CASE,
           ceilings=(), hops=5):
    return InternetIntention(ref("start"), ref("goal"), G, C, now, METRICS,
                             allowed_kinds=frozenset(kinds or {"git", "dns", "http", "rfc", "law"}),
                             minimum_evidence=minimum, resource_ceilings=tuple(ceilings), max_hops=hops)


def build(*, include_http=True, dns=True, git=True, dns_probe=None, git_probe=None, pins=None):
    http = case("http1", "http", "observe.content", "mid", "goal", 5, 20)
    dnscase = case("dns1", "dns", "observe.rrset", "start", "mid", 4, 100)
    gitcase = case("git1", "git", "observe.object", "start", "goal", 25, 80)
    references = [http] if include_http else []
    choices = ([offer(dnscase, 4, 100)] if dns else []) + ([offer(gitcase, 25, 80)] if git else [])
    fixed = {c.provider_id: c.case_digest for c in [http, dnscase, gitcase]}
    if pins is not None:
        fixed.update(pins)
    checks = {name: (lambda c, n=name: c.case_digest == fixed.get(n)) for name in fixed}
    r = InternetGroundRouter(checks)
    for c in references:
        r.add(c)
    calls = []
    def generate(c, nbytes):
        def handler(proposal, remaining):
            calls.append(proposal.provider_id)
            assert proposal.provider_id == c.provider_id
            assert remaining >= nbytes
            return ProbeCapture(c, nbytes, 1, 12000, canonical_value_digest({"captured": c.provider_id}))
        return handler
    handlers = {}
    if dns:
        handlers["dns1"] = dns_probe or generate(dnscase, 100)
    if git:
        handlers["git1"] = git_probe or generate(gitcase, 80)
    q = ProspectiveQualifier(r, handlers, ProbePolicy(frozenset(handlers), max_attempts=3,
                                                      total_response_budget=400), tuple(choices))
    return q, calls


class NativeProspectiveTests(unittest.TestCase):
    def test_closes_one_missing_dns_http_relation_using_native_resolver(self):
        q, calls = build()
        os, pid = os_with(("dns1", "dns"), ("http1", "http"), ("git1", "git"))
        d = q.choose(intent(), os, pid)
        self.assertEqual(d.status, "probe_recommended")
        self.assertEqual(d.provider_id, "dns1")
        self.assertEqual(dict((x.name, x.amount) for x in d.estimated_total_costs),
                         {"latency_us": 9, "bytes": 120})
        self.assertEqual(calls, [])  # speculation makes no requests
        s = q.step(intent(), os, pid)
        self.assertEqual(s["status"], "qualified_and_routed")
        self.assertEqual(calls, ["dns1"])
        self.assertEqual([x["provider"] for x in s["result"]["selected"]], ["dns1", "http1"])
        self.assertFalse(s["result"]["authoritative"])
        self.assertEqual(q.step(intent(), os, pid)["status"], "already_sufficient")

    def test_probe_failure_is_not_a_negative_ground_value_and_fallback_uses_git(self):
        def fail(offer, bytes_allowed):
            raise TimeoutError("external service did not respond")
        q, calls = build(dns_probe=fail)
        os, pid = os_with(("dns1", "dns"), ("http1", "http"), ("git1", "git"))
        result = q.run(intent(), os, pid)
        self.assertEqual(result["last_status"], "qualified_and_routed")
        self.assertEqual([s["status"] for s in result["steps"]],
                         ["probe_refused", "qualified_and_routed"])
        self.assertEqual(calls, ["git1"])
        self.assertEqual(result["steps"][0]["event"]["detail"], "TimeoutError")
        self.assertEqual(result["steps"][1]["event"]["predecessor_digest"],
                         result["steps"][0]["event_digest"])
        self.assertEqual([x["provider"] for x in result["steps"][1]["result"]["selected"]], ["git1"])

    def test_existing_verified_path_prevents_unnecessary_network_probe(self):
        q, calls = build()
        git = case("git1", "git", "observe.object", "start", "goal", 25, 80)
        q.router.add(git)
        os, pid = os_with(("dns1", "dns"), ("http1", "http"), ("git1", "git"))
        d = q.step(intent(), os, pid)
        self.assertEqual(d["status"], "already_sufficient")
        self.assertEqual(calls, [])

    def test_live_receiver_capability_blocks_cheaper_disallowed_probe(self):
        q, calls = build()
        os, pid = os_with(("git1", "git"), ("http1", "http"))
        d = q.step(intent(), os, pid)
        self.assertEqual(d["status"], "qualified_and_routed")
        self.assertEqual(calls, ["git1"])
        self.assertTrue(any(x["reason"] == "local_probe_authority_missing"
                            for x in d["decision"]["considered"]))

    def test_without_live_capability_does_not_call_out(self):
        q, calls = build()
        os, pid = os_with(("http1", "http"))
        d = q.step(intent(), os, pid)
        self.assertEqual(d["status"], "no_eligible_probe")
        self.assertEqual(calls, [])

    def test_requires_native_verified_prefix_and_suffix(self):
        q, calls = build(include_http=False, dns=True, git=False)
        os, pid = os_with(("dns1", "dns"))
        d = q.step(intent(), os, pid)
        self.assertEqual(d["status"], "no_eligible_probe")
        self.assertEqual(calls, [])
        self.assertEqual(d["decision"]["considered"][0]["reason"], "not_a_single_verified_route_gap")

    def test_stale_lease_and_wrong_ground_fail_before_read(self):
        q, calls = build()
        os, pid = os_with(("dns1", "dns"), ("http1", "http"), ("git1", "git"))
        self.assertEqual(q.step(intent(now=80), os, pid)["status"], "no_eligible_probe")
        self.assertEqual(calls, [])
        q.offers = (replace(q.offers[0], ground_digest="e" * 64),)
        self.assertEqual(q.step(intent(), os, pid)["status"], "no_eligible_probe")
        self.assertEqual(calls, [])

    def test_unsupported_oracle_grade_is_not_speculatively_promoted(self):
        q, calls = build()
        os, pid = os_with(("dns1", "dns"), ("http1", "http"), ("git1", "git"))
        d = q.step(intent(minimum=EvidenceStrength.INDEPENDENT_ORACLE), os, pid)
        self.assertEqual(d["status"], "no_eligible_probe")
        self.assertEqual(calls, [])

    def test_rehashed_wrong_projection_refused_before_catalogue_mutation(self):
        wrong = case("git1", "git", "observe.object", "start", "goal",
                     projection={"content": "changed"})
        q, calls = build(dns=False, git=True, git_probe=lambda _, __: ProbeCapture(
            wrong, 80, 1, 10, canonical_value_digest({"wrong": True})),
            pins={"git1": wrong.case_digest})
        os, pid = os_with(("git1", "git"))
        d = q.step(intent(), os, pid)
        self.assertEqual(d["status"], "probe_refused")
        self.assertFalse(any(x.kind == "git" for x in q.router._cases.values()))

    def test_receiver_verifier_refuses_forged_case_and_does_not_publish(self):
        wrong = case("git1", "git", "observe.object", "start", "goal", 11, 81)
        q, calls = build(dns=False, git=True, git_probe=lambda _, __: ProbeCapture(
            wrong, 80, 1, 10, canonical_value_digest({"wrong": True})))
        os, pid = os_with(("git1", "git"))
        d = q.step(intent(), os, pid)
        self.assertEqual(d["status"], "probe_refused")
        self.assertFalse(any(x.kind == "git" for x in q.router._cases.values()))

    def test_changed_target_and_source_rejected_after_probe(self):
        wrong = case("git1", "git", "observe.object", "start", "intruder")
        q, _ = build(dns=False, git=True, git_probe=lambda _, __: ProbeCapture(
            wrong, 80, 1, 10, canonical_value_digest({"wrong": True})),
            pins={"git1": wrong.case_digest})
        os, pid = os_with(("git1", "git"))
        self.assertEqual(q.step(intent(), os, pid)["status"], "probe_refused")

    def test_response_budget_overrun_refused_and_charged(self):
        captured = case("git1", "git", "observe.object", "start", "goal")
        q, _ = build(dns=False, git=True, git_probe=lambda _, __: ProbeCapture(
            captured, 300, 1, 10, canonical_value_digest({"oversize": True})))
        os, pid = os_with(("git1", "git"))
        d = q.step(intent(), os, pid)
        self.assertEqual(d["status"], "probe_refused")
        self.assertEqual(d["event"]["captured_bytes"], 300)
        self.assertFalse(any(x.kind == "git" for x in q.router._cases.values()))

    def test_probe_request_count_limit_refused(self):
        captured = case("git1", "git", "observe.object", "start", "goal")
        q, _ = build(dns=False, git=True, git_probe=lambda _, __: ProbeCapture(
            captured, 10, 5, 10, canonical_value_digest({"over_requests": True})))
        os, pid = os_with(("git1", "git"))
        self.assertEqual(q.step(intent(), os, pid)["status"], "probe_refused")

    def test_existing_sab002_ground_discovery_is_prospectively_qualified(self):
        from mailcpu.active_ground_discovery import (
            GroundAdmission, ObservedCodeHost, ProbeAuthority, discover,
        )
        from mailcpu.internet_ground_routing import admitted_affine_observation
        modulus, a, c, seed = 101, 7, 3, 5
        def read(t):
            value = seed
            for _ in range(t):
                value = (a * value + c) % modulus
            return value
        host = ObservedCodeHost("lawhost", "bounded-candidate-source", modulus,
                                "attention-reader", 100, read)
        authority = ProbeAuthority(frozenset({"lawhost"}), "attention-reader")
        # Receiver has a declared mathematical intention; the handler still
        # has to recreate the finite witness from observations during probe.
        initial = discover(host, authority, coordinate=10)
        admission = GroundAdmission(frozenset({("lawhost", initial.ground_digest)}),
                                    "trusted-local-hypervisor-policy")
        expected = admitted_affine_observation(
            initial, admission, source=ref("start"), target=ref("goal"),
            context_digest=C, coordinate=10**12 + 9, observed_at=15,
            costs=metric(15, 160))
        router = InternetGroundRouter({"lawhost": lambda case: (
            case.case_digest == expected.case_digest and
            case.evidence_digest == initial.transcript_digest)})
        o = offer(expected, 15, 160, max_bytes=256, max_requests=8)
        def discover_during_probe(proposed, allowed):
            fresh = discover(host, authority, coordinate=10)
            new_case = admitted_affine_observation(
                fresh, admission, source=ref("start"), target=ref("goal"),
                context_digest=C, coordinate=10**12 + 9, observed_at=15,
                costs=metric(15, 160))
            return ProbeCapture(new_case, 160, 8, 34000, fresh.transcript_digest)
        q = ProspectiveQualifier(router, {"lawhost": discover_during_probe},
                                 ProbePolicy(frozenset({"lawhost"}),
                                             max_attempts=1, total_response_budget=256), (o,))
        os, pid = os_with(("lawhost", "law"))
        intention = replace(intent(kinds={"law"}), ground_digest=initial.ground_digest)
        out = q.step(intention, os, pid)
        self.assertEqual(out["status"], "qualified_and_routed")
        self.assertEqual(out["result"]["selected"][0]["kind"], "law")
        self.assertEqual(out["event"]["request_count"], 8)
        self.assertEqual(out["event"]["raw_evidence_digest"], initial.transcript_digest)

    def test_untested_provider_and_injected_network_callable_rejected(self):
        q, _ = build()
        with self.assertRaises(ProspectiveRefused):
            ProspectiveQualifier(q.router, {"unapproved": lambda a, b: None},
                                 ProbePolicy(frozenset({"dns1"})), q.offers)
        with self.assertRaises(ProspectiveRefused):
            replace(q.offers[0], provider_id="dns1/../../local")
        with self.assertRaises(ProspectiveRefused):
            replace(q.offers[0], operation="remote.execute")
        with self.assertRaises(ProspectiveRefused):
            replace(q.offers[0], max_requests=0)

    def test_estimated_cost_budget_restricts_probe_choice(self):
        q, calls = build()
        os, pid = os_with(("dns1", "dns"), ("http1", "http"), ("git1", "git"))
        # DNS+HTTP costs 120 bytes, while Git directly costs 80.
        d = q.step(intent(ceilings=(RouteMetric("bytes", "B", 85),)), os, pid)
        self.assertEqual([x["provider"] for x in d["result"]["selected"]], ["git1"])
        self.assertEqual(calls, ["git1"])

    def test_finite_policy_quota_prevents_another_attempt(self):
        q, _ = build(dns=False, git=True, git_probe=lambda a, b: (_ for _ in ()).throw(TimeoutError()))
        q.policy = ProbePolicy(frozenset({"git1"}), max_attempts=1, total_response_budget=200)
        os, pid = os_with(("git1", "git"))
        out = q.run(intent(), os, pid)
        self.assertEqual(out["attempts"], 1)
        self.assertEqual(out["last_status"], "probe_refused")
        self.assertEqual(q.step(intent(), os, pid)["status"], "budget_exhausted")


if __name__ == "__main__":
    unittest.main()
