"""ITR-001 native ONP/IPS/INTENT/SAB usage; no supplied source program."""
from __future__ import annotations

from dataclasses import replace

import pytest

from mailcpu.intention_realization_latency import (
    ReceiverCapacity, cold_realize, warm_realize, summarize_campaign,
)
from mailcpu.observation_formed_processor import ObservationFormationRefused
from mailcpu.substrate_bootstrap import BootstrapRefused, verify_bootstrap_report

# Existing upstream native test fixture: no copied/quasi-execution protocol.
from test_observation_formed_processor import (
    request, offers, palette, policy, sensors, KEY, _observed_host_inventory,
)


def capacity(*, alpha=True, beta=True, shadow=False, interpreters=("alpha", "beta")):
    inv, placement, carriers = _observed_host_inventory(
        include_alpha=alpha, include_beta=beta, include_shadow=shadow)
    return ReceiverCapacity(
        offers(), palette(), policy(), {"signed-local-source": KEY},
        inv, placement, carriers, tuple(interpreters), ("witness",),
        "input", "witness", 5,
    )


def run_cold(goal=None, *, capacity_override=None):
    actor, sampled = sensors()
    nonce = iter(range(1, 100))
    got = cold_realize(
        request() if goal is None else goal,
        capacity() if capacity_override is None else capacity_override,
        actor, now=10, nonce_factory=lambda: f"{next(nonce):032x}")
    return got, sampled


def test_no_program_or_source_coefficients_given_to_constructor():
    (receipt, source, formed), sampled = run_cold()
    assert sampled == [0, 1, 2]
    assert receipt.output == 3
    assert receipt.source_probes == 3
    assert receipt.mode == "cold-observation-formed"
    assert receipt.machine_digest == formed.machine.fingerprint
    assert receipt.route_digest == formed.plan.fingerprint
    assert source.construction_plan.primitive_names == ("pre", "post")
    assert not any(key in request().to_dict() for key in ("multiplier", "offset", "selected_program"))
    assert any(step.locus == "alpha" for step in formed.plan.steps)
    assert verify_bootstrap_report(formed.report, formed.task, formed.plan)


def test_new_intention_reuses_qualified_law_without_new_source_observations():
    (_, seeded, _), sampled = run_cold()
    reuse, formed = warm_realize(seeded, request(query=7), capacity(), now=10)
    assert sampled == [0, 1, 2]
    assert reuse.output == (11*7+8)%13
    assert reuse.source_probes == 0
    assert reuse.mode == "verified-reformed-processor"
    assert formed is not None
    assert formed.machine.fingerprint == reuse.machine_digest
    assert verify_bootstrap_report(formed.report, formed.task, formed.plan)


def test_intention_is_host_independent_when_preferred_locus_disappears():
    (_, seed, _), sampled = run_cold()
    a, fa = warm_realize(seed, request(query=7), capacity(), now=10)
    b, fb = warm_realize(seed, request(query=7), capacity(alpha=False), now=10)
    assert len(sampled) == 3
    assert a.output == b.output
    assert a.derived_source_digest == b.derived_source_digest
    assert a.machine_digest == b.machine_digest
    assert a.route_digest != b.route_digest
    assert any(step.locus == "beta" for step in fb.plan.steps)
    assert not any(step.locus == "alpha" for step in fb.plan.steps)


def test_verified_retained_result_requires_no_new_host_execution():
    (cold, seed, _), sampled = run_cold()
    reused, formed = warm_realize(seed, request(), capacity(), now=10)
    assert formed is None
    assert reused.output == cold.output == 3
    assert reused.source_probes == 0
    assert reused.machine_digest is None and reused.route_digest is None
    assert reused.mode == "verified-retained-result"
    assert sampled == [0,1,2]


def test_source_substitution_and_expired_evidence_are_refused():
    (_, seed, _), _ = run_cold()
    with pytest.raises(ObservationFormationRefused):
        warm_realize(seed, request(source="f"*64), capacity(), now=10)
    with pytest.raises(ObservationFormationRefused):
        warm_realize(seed, request(query=7), capacity(), now=50)


def test_rejected_host_advertisement_is_not_execution_authority():
    (_, seed, _), _ = run_cold()
    with pytest.raises(BootstrapRefused):
        warm_realize(seed, request(query=7),
                     capacity(alpha=False, beta=False, shadow=True,
                              interpreters=("shadow",)), now=10)


def test_same_goal_cold_and_warm_compare_total_formation_cost():
    (seed_receipt, seed, _), _ = run_cold()
    (fresh, _, _), new_samples = run_cold(request(query=7))
    warm, _ = warm_realize(seed, request(query=7), capacity(), now=10)
    assert new_samples == [0,1,2]
    report = summarize_campaign(seed_receipt, (fresh,), (warm,))
    assert report["trials"] == 1
    assert report["source"] == fresh.derived_source_digest
    assert report["cold_source_probes_per_trial"] == [3]
    assert report["warm_source_probes_per_trial"] == [0]
    assert report["cold_median_ns"] == fresh.total_ns
    assert report["warm_median_ns"] == warm.total_ns
    assert report["seed_amortization_queries"] is None or report["seed_amortization_queries"] > 0


def test_wrong_goal_or_measurement_comparison_rejected():
    (seed_receipt, _, _), _ = run_cold()
    (cold, _, _), _ = run_cold(request(query=7))
    bogus = replace(cold, source_probes=0)
    with pytest.raises(ValueError):
        summarize_campaign(seed_receipt, (bogus,), (bogus,))
    with pytest.raises(ValueError):
        summarize_campaign(seed_receipt, (cold,), ())
