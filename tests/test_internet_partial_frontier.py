"""INTERNET-007 multi-gap observation attention: native E-CPU integration tests.

No network request occurs unless a receiver-installed test handler is called.
These tests use the REAL E-CPU HeadlessOS, GroundRouter and EvidencePathResolver
when executed from the repository; no fabricated route is admitted.
"""
from __future__ import annotations

from dataclasses import replace
import unittest

from mailcpu.evidence_path_resolver import EvidenceStrength, RouteMetric, RouteMetricKey
from mailcpu.headless import HeadlessOS
from mailcpu.internet_ground_routing import (
    InternetGroundRouter, InternetIntention, InternetObservationCase,
)
from mailcpu.internet_prospective_qualification import (
    ProbeOffer, ProbePolicy, ProbeCapture,
)
from mailcpu.internet_partial_frontier import PartialFrontierQualifier
from mailcpu.kernel import Capability
from mailcpu.semantic_translation import RepresentationRef, canonical_value_digest

G = canonical_value_digest({"ground": "internet007-partial", "version": 1})
C = canonical_value_digest({"context": "partial-frontier-controlled", "version": 1})
METRICS = (RouteMetricKey("latency_us", "us"), RouteMetricKey("bytes", "B"))
PROJECTION = {"value": "receiver-pinned-exact-case"}


def ref(name):
    return RepresentationRef.from_payload("internet007.test-state", 1, {"state": name})


def costs(latency=10, nbytes=20):
    return (RouteMetric("latency_us", "us", latency), RouteMetric("bytes", "B", nbytes))


def case(provider, kind, operation, start, end, *, latency=10, nbytes=20,
         observed_at=10, expires_at=60, projection=PROJECTION):
    return InternetObservationCase(
        provider, kind, operation, ref(start), ref(end), G, C,
        observed_at, expires_at,
        canonical_value_digest({"provider": provider, "state": end, "observed": observed_at}),
        PROJECTION, projection, costs(latency, nbytes),
    )


def offer(observed, *, estimate=None, max_bytes=128):
    return ProbeOffer(
        observed.provider_id, observed.kind, observed.operation,
        observed.source, observed.target, observed.ground_digest, observed.context_digest,
        10, 50, estimate or observed.costs,
        max_response_bytes=max_bytes, max_requests=2,
    )


def process(*permissions):
    os = HeadlessOS()
    pid = os.environment.kernel.spawn(
        "internet007-attention-receiver",
        capabilities=tuple(Capability(f"/internet/{kind}/{name}", frozenset({"observe"}))
                           for name, kind in permissions),
        parent_pid=os.environment.init_pid,
    )
    return os, pid


def intention(*, hops=6, now=15, ceilings=(), kinds=None,
              minimum=EvidenceStrength.PAIRED_CASE, source="start", target="goal"):
    return InternetIntention(
        ref(source), ref(target), G, C, now, METRICS,
        resource_ceilings=tuple(ceilings), max_hops=hops,
        minimum_evidence=minimum,
        allowed_kinds=frozenset(kinds or {"git", "http", "dns", "rfc", "law"}),
    )


class Fixture:
    def __init__(self, known=(), unknown=(), *, failures=(), max_attempts=8,
                 max_bytes=65536):
        self.known = tuple(known)
        self.unknown = tuple(unknown)
        self.calls = []
        self.failure_names = set(failures)
        complete = self.known + self.unknown
        pinned = {c.provider_id: c.case_digest for c in complete}
        self.router = InternetGroundRouter({
            name: lambda observed, n=name: observed.case_digest == pinned[n]
            for name in pinned
        })
        for item in self.known:
            self.router.add(item)

        def handler(observed):
            def run(proposed, byte_ceiling):
                self.calls.append(observed.provider_id)
                assert proposed.digest == offer(observed).digest
                if observed.provider_id in self.failure_names:
                    raise TimeoutError("test service unavailable")
                assert byte_ceiling >= 25
                return ProbeCapture(observed, 25, 1, 10_000,
                                    canonical_value_digest({"raw": observed.provider_id}))
            return run
        handlers = {c.provider_id: handler(c) for c in self.unknown}
        self.qualifier = PartialFrontierQualifier(
            self.router, handlers,
            ProbePolicy(frozenset(handlers), max_attempts=max_attempts,
                        total_response_budget=max_bytes),
            tuple(offer(c) for c in self.unknown),
        )
        self.os, self.pid = process(*((c.provider_id, c.kind) for c in complete))


class NativePartialFrontierTests(unittest.TestCase):
    def two_missing(self, **kwargs):
        return Fixture(
            known=(case("httpcache", "http", "observe.content", "mid2", "goal", latency=3),),
            unknown=(case("dnsroot", "dns", "observe.rrset", "start", "mid1", latency=2),
                     case("gitfollow", "git", "observe.object", "mid1", "mid2", latency=5)),
            **kwargs,
        )

    def test_selects_first_missing_edge_and_completes_in_two_observations(self):
        f = self.two_missing()
        q = f.qualifier
        d = q.choose(intention(), f.os, f.pid)
        self.assertEqual(d.status, "probe_recommended")
        self.assertEqual(d.provider_id, "dnsroot")
        detail = next(x for x in d.considered if x.get("reason") == "multi_gap_hypothesis_only")
        self.assertEqual(detail["minimum_missing_relations"], 2)
        self.assertEqual(detail["candidate_completions"], 1)
        self.assertEqual(f.calls, [])
        self.assertEqual(len(f.router._cases), 1)
        first = q.step(intention(), f.os, f.pid)
        self.assertEqual(first["status"], "case_accepted_not_selected")
        self.assertEqual(first["event"]["status"], "case_accepted_not_selected")
        self.assertEqual(f.calls, ["dnsroot"])
        second = q.step(intention(), f.os, f.pid)
        self.assertEqual(second["status"], "qualified_and_routed")
        self.assertEqual(f.calls, ["dnsroot", "gitfollow"])
        self.assertEqual([x["provider"] for x in second["result"]["selected"]],
                         ["dnsroot", "gitfollow", "httpcache"])
        self.assertEqual(second["event"]["predecessor_digest"], first["event_digest"])
        self.assertEqual(q.step(intention(), f.os, f.pid)["status"], "already_sufficient")

    def test_run_keeps_incomplete_success_as_evidence_and_advances(self):
        f = self.two_missing()
        result = f.qualifier.run(intention(), f.os, f.pid)
        self.assertEqual(result["attempts"], 2)
        self.assertEqual([x["status"] for x in result["steps"]],
                         ["case_accepted_not_selected", "qualified_and_routed"])
        self.assertEqual(result["consumed_response_bytes"], 50)

    def test_first_probe_failure_remains_refusal_not_negative_ground(self):
        f = self.two_missing(failures=("dnsroot",))
        result = f.qualifier.run(intention(), f.os, f.pid)
        self.assertEqual(result["last_status"], "no_eligible_probe")
        self.assertEqual(f.calls, ["dnsroot"])
        self.assertEqual(result["steps"][0]["event"]["status"], "probe_refused")
        self.assertEqual(result["steps"][0]["event"]["observed_case_digest"], None)
        self.assertEqual(len(f.router._cases), 1)

    def test_incomplete_first_route_falls_back_to_second_multi_gap_candidate(self):
        f = Fixture(
            known=(case("httpcache", "http", "observe.content", "mid2", "goal", latency=3),),
            unknown=(case("dnsroot", "dns", "observe.rrset", "start", "mid1", latency=2),
                     case("gitfollow", "git", "observe.object", "mid1", "mid2", latency=5),
                     case("httpother", "http", "observe.range", "start", "alternative", latency=8),
                     case("dnsother", "dns", "observe.rrset", "alternative", "mid2", latency=6)),
            failures=("dnsroot",), max_attempts=5,
        )
        result = f.qualifier.run(intention(), f.os, f.pid)
        self.assertEqual(result["last_status"], "qualified_and_routed")
        self.assertEqual(f.calls, ["dnsroot", "httpother", "dnsother"])
        self.assertEqual([x["status"] for x in result["steps"]],
                         ["probe_refused", "case_accepted_not_selected", "qualified_and_routed"])
        self.assertEqual([s["provider"] for s in result["steps"][-1]["result"]["selected"]],
                         ["httpother", "dnsother", "httpcache"])
        self.assertNotIn("dnsroot", [c.provider_id for c in f.router._cases.values()])

    def test_coverage_ranks_accessible_first_probe_with_more_completions(self):
        f = Fixture(unknown=(
            case("dnsroot", "dns", "observe.rrset", "start", "mid1", latency=2),
            case("gitone", "git", "observe.object", "mid1", "goal", latency=5),
            case("gittwo", "git", "observe.graph", "mid1", "goal", latency=7),
            case("httpalt", "http", "observe.content", "start", "alt", latency=1),
            case("rfcend", "rfc", "navigate.references", "alt", "goal", latency=1),
        ))
        # No probability model: count 2 eligible paths beginning at dnsroot,
        # versus only 1 beginning at httpalt. DNS is selected even though the
        # single alternate completion has a cheaper estimated latency.
        d = f.qualifier.choose(intention(), f.os, f.pid)
        self.assertEqual(d.provider_id, "dnsroot")
        evidence = next(x for x in d.considered if x.get("reason") == "multi_gap_hypothesis_only")
        self.assertEqual(evidence["candidate_completions"], 3)
        self.assertEqual(evidence["first_probe_coverage"], 2)

    def test_preverified_route_skips_all_hypothetical_readouts(self):
        f = self.two_missing()
        f.router._verifiers["direct"] = lambda c: True
        f.router.add(case("direct", "git", "observe.object", "start", "goal"))
        d = f.qualifier.step(intention(), f.os, f.pid)
        # The process had not been granted /internet/git/direct permission,
        # so this edge is correctly inaccessible even though its bytes match.
        self.assertEqual(d["status"], "case_accepted_not_selected")
        self.assertEqual(f.calls, ["dnsroot"])

    def test_existing_authorized_route_prevents_all_probes(self):
        f = self.two_missing()
        direct = case("direct", "git", "observe.object", "start", "goal")
        f.router._verifiers["direct"] = lambda c: c.case_digest == direct.case_digest
        f.router.add(direct)
        # Add live runtime capability via a separate receiver process.
        os, pid = process(("direct", "git"), ("httpcache", "http"),
                          ("dnsroot", "dns"), ("gitfollow", "git"))
        result = f.qualifier.step(intention(), os, pid)
        self.assertEqual(result["status"], "already_sufficient")
        self.assertEqual(f.calls, [])

    def test_requires_live_authority_at_first_missing_relation(self):
        f = self.two_missing()
        os, pid = process(("gitfollow", "git"), ("httpcache", "http"))
        d = f.qualifier.step(intention(), os, pid)
        self.assertEqual(d["status"], "no_eligible_probe")
        self.assertEqual(f.calls, [])

    def test_rejects_stale_lease_and_wrong_context_before_dispatch(self):
        f = self.two_missing()
        self.assertEqual(f.qualifier.step(intention(now=70), f.os, f.pid)["status"],
                         "no_eligible_probe")
        f.qualifier.offers = tuple(replace(o, ground_digest="a" * 64)
                                   for o in f.qualifier.offers)
        self.assertEqual(f.qualifier.step(intention(), f.os, f.pid)["status"],
                         "no_eligible_probe")
        self.assertEqual(f.calls, [])

    def test_oracle_tier_cannot_be_promoted_from_paired_cases(self):
        f = self.two_missing()
        result = f.qualifier.step(intention(minimum=EvidenceStrength.INDEPENDENT_ORACLE),
                                  f.os, f.pid)
        self.assertEqual(result["status"], "no_eligible_probe")
        self.assertEqual(f.calls, [])

    def test_route_estimate_must_fit_total_resource_and_hop_budget(self):
        f = self.two_missing()
        constrained = intention(ceilings=(RouteMetric("bytes", "B", 45),))
        self.assertEqual(f.qualifier.step(constrained, f.os, f.pid)["status"],
                         "no_eligible_probe")
        self.assertEqual(f.qualifier.step(intention(hops=2), f.os, f.pid)["status"],
                         "no_eligible_probe")
        self.assertEqual(f.calls, [])

    def test_unconnected_offers_cannot_fabricate_a_qualified_route(self):
        f = Fixture(unknown=(case("first", "git", "observe.object", "start", "orphan"),
                             case("other", "dns", "observe.rrset", "elsewhere", "goal")))
        d = f.qualifier.step(intention(), f.os, f.pid)
        self.assertEqual(d["status"], "no_eligible_probe")
        self.assertEqual(f.calls, [])

    def test_prospective_cycles_are_not_counted_as_state_advance(self):
        f = Fixture(unknown=(case("first", "git", "observe.object", "start", "mid"),
                             case("return", "dns", "observe.rrset", "mid", "start"),
                             case("elsewhere", "http", "observe.content", "orphan", "goal")))
        d = f.qualifier.step(intention(), f.os, f.pid)
        self.assertEqual(d["status"], "no_eligible_probe")
        self.assertEqual(f.calls, [])

    def test_false_observation_cannot_enter_catalogue_even_if_digest_pinned(self):
        f = self.two_missing()
        # Replace authorized handler with matching identity but changed projected
        # response; independent receiver verifier and paired comparison refuse.
        bad = case("dnsroot", "dns", "observe.rrset", "start", "mid1",
                   projection={"value": "contradiction"})
        f.qualifier.handlers = dict(f.qualifier.handlers, dnsroot=lambda o, b: ProbeCapture(
            bad, 25, 1, 100, canonical_value_digest({"false": True})))
        d = f.qualifier.step(intention(), f.os, f.pid)
        self.assertEqual(d["status"], "probe_refused")
        self.assertEqual(len(f.router._cases), 1)

    def test_negative_observation_does_not_spend_authority_on_next_gap(self):
        f = self.two_missing(failures=("dnsroot",))
        first = f.qualifier.step(intention(), f.os, f.pid)
        self.assertEqual(first["status"], "probe_refused")
        self.assertEqual(f.qualifier.step(intention(), f.os, f.pid)["status"],
                         "no_eligible_probe")
        self.assertEqual(f.calls, ["dnsroot"])

    def test_no_invented_probabilities_or_implicit_internet_dispatch(self):
        f = self.two_missing()
        decision = f.qualifier.choose(intention(), f.os, f.pid)
        diag = next(x for x in decision.considered if x.get("reason") == "multi_gap_hypothesis_only")
        self.assertIn("not", diag)
        self.assertNotIn("expected_information_gain", diag)
        self.assertEqual(f.calls, [])
        self.assertEqual(len(f.router._cases), 1)


    def test_bounded_search_refuses_when_frontier_completion_count_explodes(self):
        # 8 x 8 x 8 three-gap possibilities, beyond the explicit 256-plan
        # ceiling. Partial enumeration is *not* presented as an exhaustive
        # attention ranking; the system refuses before performing any reads.
        unknown = tuple(case(f"a{i}", "git", "observe.object", "start", "a")
                        for i in range(8)) + tuple(
            case(f"b{i}", "dns", "observe.rrset", "a", "b") for i in range(8)
        ) + tuple(case(f"c{i}", "http", "observe.content", "b", "goal")
                        for i in range(8))
        f = Fixture(unknown=unknown)
        d = f.qualifier.step(intention(), f.os, f.pid)
        self.assertEqual(d["status"], "budget_exhausted")
        self.assertTrue(any(x.get("reason") == "bounded_search_incomplete"
                            for x in d["decision"]["considered"]))
        self.assertEqual(f.calls, [])
        self.assertEqual(len(f.router._cases), 0)

    def test_two_real_rfc_link_parsers_qualify_separate_simulated_observations(self):
        # Uses the actual INTERNET-004 HTML parser and capsule verifier, not a
        # native network call. The hosted job independently does real HTTPS.
        from examples.navigate_rfc_partial_frontier import run
        from mailcpu.public_internet_navigation import Response, rfc_url
        bodies = {
            rfc_url(9293): b'<html><title>RFC9293</title><a href="/rfc/rfc793">793</a></html>',
            rfc_url(793): b'<html><title>RFC793</title><a href="/rfc/rfc761">761</a></html>',
            rfc_url(761): b'<html><title>RFC761</title></html>',
        }
        def fetch(url, *, limit, timeout):
            return Response(bodies[url], 200, "text/html")
        observed = run(fetch=fetch)
        self.assertFalse(observed["live_https_observed"])
        self.assertEqual(observed["qualified_result"]["last_status"], "qualified_and_routed")
        self.assertEqual(len(observed["capsules"]), 2)
        replayed = run(prior_capsules=observed["capsules"])
        self.assertEqual(replayed["qualified_result"]["event_chain_tip"],
                         observed["qualified_result"]["event_chain_tip"])
        self.assertFalse(replayed["live_https_observed"])

    def test_rfc_pilot_rejects_changed_raw_link_after_capture(self):
        from examples.navigate_rfc_partial_frontier import run
        from mailcpu.public_internet_navigation import Response, rfc_url
        import copy
        bodies = {
            rfc_url(9293): b'<html><a href="/rfc/rfc793">793</a></html>',
            rfc_url(793): b'<html><a href="/rfc/rfc761">761</a></html>',
            rfc_url(761): b'<html>761</html>',
        }
        original = run(fetch=lambda url, **_: Response(bodies[url], 200, "text/html"))
        tampered = copy.deepcopy(original["capsules"])
        tampered["rfc9293"]["visits"][0]["links"] = []
        with self.assertRaises(RuntimeError):
            run(prior_capsules=tampered)


if __name__ == "__main__":
    unittest.main()
