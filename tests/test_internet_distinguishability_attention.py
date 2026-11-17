"""INTERNET-008: actual VGI partial-attention + native E-CPU sufficiency.

Requires the real pinned VGI checkout in PYTHONPATH. This suite tests
receiver-owned counterfactual planning only; it never makes public requests.
"""
from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import unittest

from vgi.transitions import GroundTransitionSystem, TransitionObservation, TransitionOutcome
from vgi.relational import ObserverContext
from vgi.partial_attention import ProbeScenario, TransitionProbe, score_partial_probe

from mailcpu.internet_distinguishability_attention import (
    DistinguishabilityGround, DistinguishabilityFrontierQualifier,
)
from mailcpu.internet_prospective_qualification import ProspectiveRefused
from mailcpu.intention_sufficiency import FiniteGround, FiniteState, MeasurementCapability
from mailcpu.semantic_translation import canonical_value_digest
from mailcpu.kernel import Capability
from mailcpu.headless import HeadlessOS

# Reuse the original native test fixture: these probes still use the REAL
# InternetGroundRouter, EvidencePathResolver, and HeadlessOS process rights.
from test_internet_partial_frontier import (
    Fixture, case, offer, intention, process, G, C,
)


def predictive_ground():
    states = ("a", "b", "c", "d")
    actions = ("dns", "http", "noop")
    seen = []
    for state in states:
        for action in actions:
            if (state, action) in {("a", "dns"), ("b", "http")}:
                continue
            seen.append(TransitionObservation(state, action,
                (TransitionOutcome(state, (0,)),)))
    ground = GroundTransitionSystem(states, actions, "a", ("signal",), tuple(seen),
                                    {"description": "explicit hypothetical probe outcomes"})
    observer = ObserverContext.full(ground, "receiver-visible")
    dns = TransitionProbe("a", "dns", (
        ProbeScenario(TransitionOutcome("a", (1,))),
        ProbeScenario(TransitionOutcome("a", (2,))),
    ), label="dnsroot")
    http = TransitionProbe("b", "http", (
        ProbeScenario(TransitionOutcome("b", (0,))),
        ProbeScenario(TransitionOutcome("b", (1,))),
    ), label="httpalt")
    return ground, observer, dns, http


def finite_ground():
    rows = []
    for n, target, http, dns in (("s1", 0, 0, 0),
                                 ("s2", 1, 1, 0),
                                 ("s3", 0, 0, 1),
                                 ("s4", 1, 1, 1)):
        rows.append(FiniteState.create(n, {"scope": "one-observation-fiber"},
                                        {"intended_result": target},
                                        {"http": http, "dns": dns}))
    return FiniteGround(G, canonical_value_digest({"public": 1}),
                        canonical_value_digest({"intention": 1}), C, tuple(rows))


def fixture(failures=()):
    f = Fixture(unknown=(
        case("dnsroot", "dns", "observe.rrset", "start", "dns", latency=1),
        case("gita", "git", "observe.object", "dns", "goal", latency=1),
        case("gitb", "git", "observe.graph", "dns", "goal", latency=1),
        case("httpalt", "http", "observe.content", "start", "web", latency=8),
        case("rfcend", "rfc", "navigate.references", "web", "goal", latency=6),
    ), failures=failures, max_attempts=5)
    ground, observer, dns, http = predictive_ground()
    keys = {item.provider_id: item.digest for item in f.qualifier.offers}
    attention = DistinguishabilityGround(
        ground, observer,
        {keys["dnsroot"]: dns, keys["httpalt"]: http},
        finite_ground(), {"scope": "one-observation-fiber"},
        {keys["dnsroot"]: "dns", keys["httpalt"]: "http"},
        (MeasurementCapability("dns", canonical_value_digest({"feature": "dns"}), "dnsroot", 1),
         MeasurementCapability("http", canonical_value_digest({"feature": "http"}), "httpalt", 4)),
        1,
    )
    f.qualifier = DistinguishabilityFrontierQualifier(
        f.router, f.qualifier.handlers, f.qualifier.policy,
        f.qualifier.offers, attention=attention,
    )
    return f


class NativeVgiInternetAttentionTests(unittest.TestCase):
    def test_native_structural_coverage_and_intention_attention_disagree(self):
        f = fixture()
        from mailcpu.internet_partial_frontier import PartialFrontierQualifier
        structural = PartialFrontierQualifier(
            f.router, f.qualifier.handlers, f.qualifier.policy, f.qualifier.offers)
        self.assertEqual(structural.choose(intention(), f.os, f.pid).provider_id,
                         "dnsroot")  # two possible suffixes
        focused = f.qualifier.choose(intention(), f.os, f.pid)
        self.assertEqual(focused.provider_id, "httpalt") # only one, but informative
        self.assertEqual(f.calls, [])
        self.assertEqual(len(f.router._cases), 0)
        diag = next(x for x in focused.considered if
                    x.get("reason") == "vgi_counterfactual_attention_model_only")
        self.assertEqual(diag["sufficiency_status"], "MEASURE")
        self.assertEqual(diag["sufficiency_required_features"], ["http"])
        self.assertEqual(diag["ranked_candidates"][0]["feature"], "http")
        self.assertFalse(diag["ranked_candidates"][0]["vgi_expectation_used_for_ranking"])
        self.assertEqual(diag["headless_authority_digest"],
                         focused.existing_route["route"]["authority_digest"])

    def test_actual_vgi_three_valued_counterfactual_score(self):
        system, observer, dns, http = predictive_ground()
        a = score_partial_probe(system, observer, dns, 1)
        b = score_partial_probe(system, observer, http, 1)
        self.assertEqual(a.minimum_resolved_pairs, 3)
        self.assertLess(b.minimum_resolved_pairs, a.minimum_resolved_pairs)
        self.assertIsNone(a.expected_gain_per_cost)
        self.assertIsNone(b.expected_gain_per_cost)

    def test_qualified_observation_then_native_reroute(self):
        f = fixture()
        result = f.qualifier.run(intention(), f.os, f.pid)
        self.assertEqual(result["last_status"], "qualified_and_routed")
        self.assertEqual(f.calls, ["httpalt", "rfcend"])
        self.assertEqual([x["status"] for x in result["steps"]],
                         ["case_accepted_not_selected", "qualified_and_routed"])
        self.assertEqual([x["provider"] for x in result["steps"][-1]["result"]["selected"]],
                         ["httpalt", "rfcend"])
        self.assertEqual(len(f.router._cases), 2)

    def test_probe_failure_remains_refusal_and_structural_fallback(self):
        f = fixture(failures=("httpalt",))
        outcome = f.qualifier.run(intention(), f.os, f.pid)
        self.assertEqual(f.calls, ["httpalt", "dnsroot", "gita"] if f.calls[-1] == "gita"
                         else ["httpalt", "dnsroot", "gitb"])
        self.assertEqual(outcome["steps"][0]["status"], "probe_refused")
        self.assertEqual(outcome["last_status"], "qualified_and_routed")
        self.assertEqual(len(f.router._cases), 2)
        self.assertNotIn("httpalt", [c.provider_id for c in f.router._cases.values()])

    def test_live_authority_denial_cannot_be_replaced_by_vgi_score(self):
        f = fixture()
        os, pid = process(("dnsroot", "dns"), ("gita", "git"), ("gitb", "git"),
                          ("rfcend", "rfc"))
        d = f.qualifier.choose(intention(), os, pid)
        self.assertEqual(d.provider_id, "dnsroot")
        self.assertEqual(f.calls, [])

    def test_foreign_ground_refused_before_network(self):
        f = fixture()
        other = replace(f.qualifier.attention.finite_ground, ground_digest="a" * 64)
        f.qualifier.attention = replace(f.qualifier.attention, finite_ground=other)
        with self.assertRaises(ProspectiveRefused):
            f.qualifier.choose(intention(), f.os, f.pid)
        self.assertEqual(f.calls, [])

    def test_invalid_vgi_probe_cell_refused(self):
        f = fixture()
        g = f.qualifier.attention
        any_key = next(iter(g.probes_by_offer))
        bad = TransitionProbe("c", "noop", (
            ProbeScenario(TransitionOutcome("c", (1,))),))
        with self.assertRaises(Exception):
            replace(g, probes_by_offer=dict(g.probes_by_offer, **{any_key: bad}))

    def test_source_or_scenario_digest_revision_changes_model_identity(self):
        f = fixture()
        original = f.qualifier.attention
        # The VGI scenario Ground is hypothetical, but changing it must
        # change the model fingerprint and invalidate a pinned model revision.
        changed = GroundTransitionSystem(
            original.predictive_ground.states,
            original.predictive_ground.actions,
            original.predictive_ground.initial_state,
            original.predictive_ground.channels,
            original.predictive_ground.observations,
            {"description": "a new hypothesis revision"},
        )
        new = replace(original, predictive_ground=changed)
        self.assertNotEqual(original.digest, new.digest)

    def test_unsupported_oracle_grade_remains_non_executable(self):
        from mailcpu.evidence_path_resolver import EvidenceStrength
        f = fixture()
        d = f.qualifier.step(intention(minimum=EvidenceStrength.INDEPENDENT_ORACLE),
                             f.os, f.pid)
        self.assertEqual(d["status"], "no_eligible_probe")
        self.assertEqual(f.calls, [])

    def test_no_internet_request_in_intention_model_planning(self):
        f = fixture()
        before = f.qualifier.attention.digest
        f.qualifier.choose(intention(), f.os, f.pid)
        self.assertEqual(f.qualifier.attention.digest, before)
        self.assertEqual(f.calls, [])
        self.assertEqual(f.qualifier.history, [])


if __name__ == "__main__":
    unittest.main()
