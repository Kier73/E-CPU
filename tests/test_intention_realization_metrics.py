"""Exact timing arithmetic and comparison invariants; no external packages."""
from dataclasses import replace
import unittest

from mailcpu.intention_realization_metrics import IntentionReceipt, summarize_campaign


def receipt(mode, goal='g', source='s', ns=100, probes=3, value=7):
    return IntentionReceipt(mode,goal,'s_witness',source,'machine','route',
                            value,probes,{'work':ns},'evidence')


class TimingMathTests(unittest.TestCase):
    def test_report_preserves_stage_accounting(self):
        r=receipt('cold-observation-formed',ns=23)
        self.assertEqual(r.total_ns,23)
        self.assertEqual(r.to_dict()['total_ns'],23)

    def test_seed_amortization_strict_inequality(self):
        seed=receipt('cold-observation-formed',ns=100)
        cold=[receipt('cold-observation-formed',ns=40)]*3
        warm=[receipt('verified-reformed-processor',ns=20,probes=0)]*3
        self.assertEqual(summarize_campaign(seed,cold,warm)['seed_amortization_queries'],6)

    def test_no_gain_is_not_invented(self):
        seed=receipt('cold-observation-formed',ns=50)
        cold=[receipt('cold-observation-formed',ns=20)]
        warm=[receipt('verified-reformed-processor',ns=30,probes=0)]
        self.assertIsNone(summarize_campaign(seed,cold,warm)['seed_amortization_queries'])

    def test_exact_equal_cold_warm_goal_required(self):
        seed=receipt('cold-observation-formed')
        cold=[receipt('cold-observation-formed')]
        warm=[receipt('verified-reformed-processor',goal='changed',probes=0)]
        with self.assertRaises(ValueError):summarize_campaign(seed,cold,warm)

    def test_exact_same_source_required(self):
        seed=receipt('cold-observation-formed')
        cold=[receipt('cold-observation-formed')]
        warm=[receipt('verified-reformed-processor',source='altered',probes=0)]
        with self.assertRaises(ValueError):summarize_campaign(seed,cold,warm)

    def test_wrong_result_refused(self):
        seed=receipt('cold-observation-formed')
        cold=[receipt('cold-observation-formed')]
        warm=[receipt('verified-reformed-processor',value=9,probes=0)]
        with self.assertRaises(ValueError):summarize_campaign(seed,cold,warm)

    def test_new_source_probes_cannot_hide_in_warm_mode(self):
        seed=receipt('cold-observation-formed')
        cold=[receipt('cold-observation-formed')]
        warm=[receipt('verified-reformed-processor',probes=1)]
        with self.assertRaises(ValueError):summarize_campaign(seed,cold,warm)

    def test_absent_or_mismatched_trials_refused(self):
        seed=receipt('cold-observation-formed')
        cold=[receipt('cold-observation-formed')]
        warm=[receipt('verified-reformed-processor',probes=0)]
        for a,b in [(cold,()),((),warm),(cold+cold,warm)]:
            with self.assertRaises(ValueError):summarize_campaign(seed,a,b)

    def test_negative_or_non_integer_time_refused(self):
        seed=receipt('cold-observation-formed')
        cold=[receipt('cold-observation-formed')]
        for bad in [-1,1.2]:
            warm=[receipt('verified-reformed-processor',ns=bad,probes=0)]
            with self.assertRaises(ValueError):summarize_campaign(seed,cold,warm)


if __name__=='__main__':unittest.main()
