"""INTERNET-005: native route decisions and refusal controls.

Run against E-CPU itself, not a substitute for the native resolver/OS. The
separate offline stubs in local development are not part of this test file.
"""
from __future__ import annotations

from dataclasses import replace
import unittest

from mailcpu.active_ground_discovery import (
    GroundAdmission, ObservedCodeHost, ProbeAuthority, discover,
)
from mailcpu.evidence_path_resolver import (
    EvidenceStrength, RouteMetric, RouteMetricKey,
)
from mailcpu.headless import HeadlessOS
from mailcpu.internet_ground_routing import (
    InternetGroundRefused, InternetGroundRouter,
    InternetObservationCase, InternetIntention, admitted_affine_observation,
    admitted_rfc_observation,
)
from mailcpu.kernel import Capability
from mailcpu.semantic_translation import RepresentationRef, canonical_value_digest


def ref(node: str) -> RepresentationRef:
    return RepresentationRef.from_payload("internet.testing.representation", 1, {"node": node})


def pin(value) -> str:
    return canonical_value_digest(value)


GROUND = pin({"source": "independent-immutable-user-pin", "v": 1})
CONTEXT = pin({"intent": "retrieve-exact-source-observation", "v": 1})
METRICS = (RouteMetricKey("latency_us", "us"), RouteMetricKey("bytes", "B"))


def candidate(provider: str, kind: str, operation: str, source: str, target: str,
              latency: int, byte_count: int, *, ground=GROUND, context=CONTEXT,
              observed=10, expires=30, result=None) -> InternetObservationCase:
    actual = {"object_sha256": "e" * 64} if result is None else result
    return InternetObservationCase(
        provider_id=provider, kind=kind, operation=operation, source=ref(source),
        target=ref(target), ground_digest=ground, context_digest=context,
        observed_at=observed, expires_at=expires,
        evidence_digest=pin({"trusted-external-receipt": provider, "source": source,
                             "target": target, "value": actual}),
        expected_projection={"object_sha256": "e" * 64},
        observed_projection=actual,
        costs=(RouteMetric("latency_us", "us", latency),
               RouteMetric("bytes", "B", byte_count)),
    )


def os_with(*providers: tuple[str, str]) -> tuple[HeadlessOS, int]:
    os = HeadlessOS()
    caps = tuple(Capability(f"/internet/{kind}/{provider}", frozenset({"observe"}))
                 for provider, kind in providers)
    pid = os.environment.kernel.spawn(
        "internet-005-observer", capabilities=caps,
        parent_pid=os.environment.init_pid,
    )
    return os, pid


def intention(*, metric_order=METRICS, now=15, kinds=None, max_hops=4,
              ground=GROUND, context=CONTEXT, ceilings=(), minimum=EvidenceStrength.PAIRED_CASE):
    return InternetIntention(
        ref("start"), ref("goal"), ground, context, now,
        metric_order, resource_ceilings=tuple(ceilings),
        allowed_kinds=frozenset(kinds or {"git", "http", "dns", "rfc", "law"}),
        max_hops=max_hops, minimum_evidence=minimum,
    )


def registry(*offers: InternetObservationCase, additional_verifiers=None):
    # A trustworthy policy must pin its own evidence, not accept a hash
    # submitted by a service. This fixture simulates such external pins.
    pins = {x.provider_id: (x.case_digest, x.evidence_digest) for x in offers}
    if additional_verifiers is not None:
        pins.update(additional_verifiers)
    checker = {
        name: (lambda case, n=name: (case.case_digest, case.evidence_digest) == pins[n])
        for name in pins
    }
    router = InternetGroundRouter(checker)
    for x in offers:
        router.add(x)
    return router


class InternetGroundRoutingTests(unittest.TestCase):
    def setUp(self):
        self.git = candidate("git1", "git", "observe.object", "start", "goal", 25, 128)
        self.dns = candidate("dns1", "dns", "observe.rrset", "start", "resolved", 4, 100)
        self.http = candidate("http1", "http", "observe.content", "resolved", "goal", 5, 280)
        self.rfc = candidate("rfc1", "rfc", "navigate.references", "start", "rfc", 12, 170)
        self.http_rfc = candidate("http2", "http", "observe.content", "rfc", "goal", 6, 70)

    def test_native_resolver_selects_qualified_dns_http_composition(self):
        router = registry(self.git, self.dns, self.http, self.rfc, self.http_rfc)
        os, pid = os_with(("git1", "git"), ("dns1", "dns"), ("http1", "http"),
                          ("rfc1", "rfc"), ("http2", "http"))
        decision = router.resolve(intention(), os, pid)
        self.assertEqual(decision["status"], "found")
        self.assertEqual([x["provider"] for x in decision["selected"]], ["dns1", "http1"])
        self.assertFalse(decision["authoritative"])
        self.assertEqual({x["name"]: x["amount"] for x in decision["route"]["total_costs"]},
                         {"latency_us": 9, "bytes": 380})

    def test_metric_basis_changes_selected_path_without_mixing_units(self):
        router = registry(self.git, self.dns, self.http, self.rfc, self.http_rfc)
        os, pid = os_with(("git1", "git"), ("dns1", "dns"), ("http1", "http"),
                          ("rfc1", "rfc"), ("http2", "http"))
        metric_order = (RouteMetricKey("bytes", "B"), RouteMetricKey("latency_us", "us"))
        d = router.resolve(intention(metric_order=metric_order), os, pid)
        self.assertEqual([x["provider"] for x in d["selected"]], ["git1"])

    def test_live_headless_capability_blocks_unpermitted_provider(self):
        router = registry(self.git, self.dns, self.http)
        os, pid = os_with(("git1", "git"))
        d = router.resolve(intention(), os, pid)
        self.assertEqual([x["provider"] for x in d["selected"]], ["git1"])
        self.assertTrue(any(x["code"] == "authority_missing" for x in d["route"]["blockers"]))

    def test_without_any_live_capabilities_route_is_blocked(self):
        router = registry(self.git, self.dns, self.http)
        os, pid = os_with()
        d = router.resolve(intention(), os, pid)
        self.assertEqual(d["status"], "blocked")
        self.assertEqual(d["selected"], [])

    def test_expired_cheap_path_falls_back_to_still_qualified_git(self):
        router = registry(self.git, replace(self.dns, expires_at=14), self.http)
        os, pid = os_with(("git1", "git"), ("dns1", "dns"), ("http1", "http"))
        d = router.resolve(intention(), os, pid)
        self.assertEqual([x["provider"] for x in d["selected"]], ["git1"])
        self.assertIn("expired_or_future_observation", [x["reason"] for x in d["refusals"]])

    def test_future_dated_evidence_cannot_be_selected(self):
        newer = replace(self.git, observed_at=20)
        r = registry(newer)
        os, pid = os_with(("git1", "git"))
        self.assertEqual(r.resolve(intention(now=15), os, pid)["status"], "unreachable")

    def test_new_source_ground_cannot_reuse_old_verified_case(self):
        r = registry(self.git)
        os, pid = os_with(("git1", "git"))
        self.assertEqual(r.resolve(intention(ground=pin({"source": "changed"})), os, pid)["status"],
                         "unreachable")

    def test_new_context_cannot_reuse_old_verified_case(self):
        r = registry(self.git)
        os, pid = os_with(("git1", "git"))
        self.assertEqual(r.resolve(intention(context=pin({"change": True})), os, pid)["status"],
                         "unreachable")

    def test_rehashed_false_projection_refused_even_when_verifier_accepts(self):
        wrong = replace(self.git, observed_projection={"object_sha256": "a" * 64},
                        evidence_digest=pin({"rehashed": True}))
        r = registry(wrong)
        os, pid = os_with(("git1", "git"))
        d = r.resolve(intention(), os, pid)
        self.assertEqual(d["status"], "unreachable")
        self.assertIn("projection_mismatch", [x["reason"] for x in d["refusals"]])

    def test_changed_case_rejected_against_receiver_owned_external_pin(self):
        r = registry(self.git)
        corrupt = replace(self.git, evidence_digest=pin({"changed": True}))
        r.add(corrupt)
        os, pid = os_with(("git1", "git"))
        d = r.resolve(intention(), os, pid)
        self.assertEqual([x["provider"] for x in d["selected"]], ["git1"])
        self.assertIn("receiver_evidence_refused", [x["reason"] for x in d["refusals"]])

    def test_requested_oracle_tier_not_satisfied_by_paired_case(self):
        r = registry(self.git)
        os, pid = os_with(("git1", "git"))
        d = r.resolve(intention(minimum=EvidenceStrength.INDEPENDENT_ORACLE), os, pid)
        self.assertEqual(d["status"], "blocked")
        self.assertTrue(any(x["code"] == "evidence_insufficient" for x in d["route"]["blockers"]))

    def test_resource_ceiling_excludes_cheaper_route(self):
        r = registry(self.git, self.dns, self.http)
        os, pid = os_with(("git1", "git"), ("dns1", "dns"), ("http1", "http"))
        d = r.resolve(intention(ceilings=(RouteMetric("bytes", "B", 200),)), os, pid)
        self.assertEqual([x["provider"] for x in d["selected"]], ["git1"])

    def test_hop_limit_blocks_composition_but_preserves_direct_option(self):
        r = registry(self.git, self.dns, self.http)
        os, pid = os_with(("git1", "git"), ("dns1", "dns"), ("http1", "http"))
        d = r.resolve(intention(max_hops=1), os, pid)
        self.assertEqual([x["provider"] for x in d["selected"]], ["git1"])

    def test_intention_kind_filter_is_exact(self):
        r = registry(self.git, self.dns, self.http)
        os, pid = os_with(("git1", "git"), ("dns1", "dns"), ("http1", "http"))
        d = r.resolve(intention(kinds={"git"}), os, pid)
        self.assertEqual([x["provider"] for x in d["selected"]], ["git1"])

    def test_provider_cannot_be_self_admitted_without_local_checker(self):
        with self.assertRaises(InternetGroundRefused):
            InternetGroundRouter({}).add(self.git)

    def test_invalid_or_ambiguous_protocol_names_are_refused(self):
        with self.assertRaises(InternetGroundRefused):
            replace(self.git, provider_id="git/../../outside")
        with self.assertRaises(InternetGroundRefused):
            replace(self.git, kind="tcp", operation="arbitrary.execute")
        with self.assertRaises(InternetGroundRefused):
            replace(self.git, kind="dns", operation="observe.object")

    def test_observation_projection_is_detached_from_mutable_input(self):
        observed = {"object_sha256": "e" * 64, "items": [1, {"a": 2}]}
        c = candidate("immutable", "http", "observe.content", "start", "goal", 1, 8,
                      result=observed)
        stable = c.case_digest
        observed["items"][1]["a"] = 9
        self.assertEqual(c.case_digest, stable)
        self.assertEqual(c.to_dict()["observed_projection"]["items"][1]["a"], 2)
        with self.assertRaises(TypeError):
            c.observed_projection["object_sha256"] = "a" * 64

    def test_receiver_revocation_between_selection_and_publication_refuses(self):
        calls = {"n": 0}
        def policy(case):
            calls["n"] += 1
            return calls["n"] == 1
        r = InternetGroundRouter({"git1": policy})
        r.add(self.git)
        os, pid = os_with(("git1", "git"))
        with self.assertRaisesRegex(InternetGroundRefused, "rescinded"):
            r.resolve(intention(), os, pid)

    def test_actual_internet004_capsule_enters_native_resolver_after_replay(self):
        from mailcpu.public_internet_navigation import (
            Policy, Response, navigate, rfc_url,
        )
        policy = Policy((9293,), 793, max_pages=2, max_depth=1,
                        page_budget=4096, total_budget=8192)
        seed = b'<html><title>TCP</title><a href="/rfc/rfc793">RFC793</a></html>'
        dest = b'<html><title>TCP 1981</title></html>'
        content = {rfc_url(9293): seed, rfc_url(793): dest}

        def local_fixture_fetch(url, *, limit, timeout):
            return Response(content[url], 200, "text/html")

        capsule = navigate(policy, fetch=local_fixture_fetch)
        expected_path = (rfc_url(9293), rfc_url(793))
        case, verifier = admitted_rfc_observation(
            capsule, policy, expected_capsule_digest=capsule["capsule_digest"],
            expected_path=expected_path, provider_id="rfcfixture",
            source=ref("start"), target=ref("goal"), context_digest=CONTEXT,
            observed_at=10, expires_at=40,
            costs=(RouteMetric("latency_us", "us", 10),
                   RouteMetric("bytes", "B", len(seed)+len(dest))),
        )
        r = InternetGroundRouter({"rfcfixture": verifier})
        r.add(case)
        os, pid = os_with(("rfcfixture", "rfc"))
        d = r.resolve(intention(ground=pin(policy.as_dict()), kinds={"rfc"}), os, pid)
        self.assertEqual(d["status"], "found")
        self.assertEqual([x["provider"] for x in d["selected"]], ["rfcfixture"])
        # Rehashed wrong path is refused even if internally consistent.
        with self.assertRaises(InternetGroundRefused):
            admitted_rfc_observation(
                capsule, policy, expected_capsule_digest=capsule["capsule_digest"],
                expected_path=(rfc_url(9293), rfc_url(9294)),
                provider_id="rfcfixture", source=ref("start"), target=ref("goal"),
                context_digest=CONTEXT, observed_at=10, expires_at=40,
                costs=(RouteMetric("latency_us", "us", 10),
                       RouteMetric("bytes", "B", 100)),
            )

    def test_sab002_discovery_reuses_native_ground_admission_and_oracle(self):
        mod, a, c, x0 = 101, 7, 3, 5
        def value(t):
            v = x0
            for _ in range(t):
                v = (a * v + c) % mod
            return v
        host = ObservedCodeHost("lawhost", "local-independent-observer", mod, "reader", 100, value)
        candidate_ground = discover(host, ProbeAuthority(frozenset({"lawhost"}), "reader"), coordinate=10)
        admit = GroundAdmission(frozenset({("lawhost", candidate_ground.ground_digest)}), "receiver")
        cse = admitted_affine_observation(candidate_ground, admit,
                                          source=ref("start"), target=ref("goal"),
                                          context_digest=CONTEXT, coordinate=10**12+9,
                                          observed_at=15,
                                          costs=(RouteMetric("latency_us", "us", 7),
                                                 RouteMetric("bytes", "B", 96)))
        r = registry(cse)
        os, pid = os_with(("lawhost", "law"))
        d = r.resolve(intention(ground=candidate_ground.ground_digest, kinds={"law"}), os, pid)
        self.assertEqual(d["status"], "found")
        self.assertEqual([x["provider"] for x in d["selected"]], ["lawhost"])
        with self.assertRaises(Exception):
            admitted_affine_observation(candidate_ground,
                GroundAdmission(frozenset(), "receiver"),
                source=ref("start"), target=ref("goal"), context_digest=CONTEXT,
                coordinate=123, observed_at=15,
                costs=(RouteMetric("latency_us", "us", 7), RouteMetric("bytes", "B", 96)))


if __name__ == "__main__":
    unittest.main()
