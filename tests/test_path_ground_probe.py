"""PATH-GROUND-001: real TCP loopback + evidence-scoped operator characterization."""
from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import unittest

from mailcpu.substrate_bootstrap import ChannelObservation
from mailcpu.path_ground_probe import (
    PathGroundRefused, TcpPathObservation, TransferObservation,
    characterize_transfer, fir_response, probe_tcp_loopback,
    verify_tcp_path, verify_transfer_candidate,
)


def channel(*, max_bytes=16384, start=10, end=100, source="sender", target="receiver"):
    return ChannelObservation(
        channel_id="local-tcp",source=source,target=target,carries=("bytes",),
        estimated_quanta=1,observed_at=start,expires_at=end,
        evidence_digest=sha256(b"local-declared-loopback-channel-not-authenticated").hexdigest(),
        max_payload_bytes=max_bytes,
    )


def observations(kernel=(0.625,0.25,-0.125), *, perturb=0, mechanism="software_fir_reference"):
    n=9
    probes=[(1,)+(0,)*(n-1),(0,1)+(0,)*(n-2),
            (1,3,-2,0,1,0,-1,0,2),(2,0,1,-1,4,3,1,-1,0),
            (-3,1,0,2,1,-1,2,3,4)]
    environment=sha256(b"deliberately-modelled-software-fir").hexdigest()
    ans=[]
    for i,v in enumerate(probes):
        y=list(fir_response(v,kernel))
        if i==2:y[3]+=perturb
        ans.append(TransferObservation(tuple(v),tuple(y),mechanism,environment,f"probe-{i}"))
    return ans


class PathGroundProbeTests(unittest.TestCase):
    def test_real_tcp_stream_and_elapsed_observation(self):
        parts=(b"first",b"-second-",b"third"*31)
        report, received=probe_tcp_loopback(parts,channel=channel(),logical_observed_at=19)
        self.assertEqual(received,b"".join(parts))
        self.assertTrue(verify_tcp_path(report,sent=b"".join(parts),received=received,
                                        channel=channel(),logical_observed_at=19))
        self.assertTrue(report.elapsed_ns>0)
        self.assertEqual(report.send_calls,3)
        self.assertTrue(report.recv_calls>=1)
        self.assertEqual(report.scope,"local_kernel_stack_including_endpoint_scheduling")
        self.assertEqual(report.to_dict()["payload_equal"],True)

    def test_real_transport_requires_receiver_selected_channel(self):
        report,output=probe_tcp_loopback((b"a",b"b"),channel=channel(),logical_observed_at=20)
        self.assertFalse(verify_tcp_path(report,sent=b"ab",received=output,
                                         channel=channel(source="different"),logical_observed_at=20))
        self.assertFalse(verify_tcp_path(report,sent=b"ab",received=output,
                                         channel=channel(),logical_observed_at=21))

    def test_corrupted_or_relabelled_delivery_refused(self):
        report,output=probe_tcp_loopback((b"abc",b"def"),channel=channel(),logical_observed_at=21)
        self.assertFalse(verify_tcp_path(report,sent=b"abcdef",received=b"xxxxxx",channel=channel(),logical_observed_at=21))
        self.assertFalse(verify_tcp_path(replace(report,output_sha256="0"*64),sent=b"abcdef",received=output,channel=channel(),logical_observed_at=21))

    def test_reject_expired_or_early_channel(self):
        for at in (9,101):
            with self.assertRaises(PathGroundRefused):
                probe_tcp_loopback((b"a",b"b"),channel=channel(),logical_observed_at=at)

    def test_reject_oversized_payload_before_network(self):
        with self.assertRaises(PathGroundRefused):
            probe_tcp_loopback((b"abc",b"def"),channel=channel(max_bytes=5),logical_observed_at=20)

    def test_reject_invalid_stream_parts_and_timeout(self):
        for bad in ((b"",b"a"),(b"a",),(b"a","b")):
            with self.assertRaises(PathGroundRefused):
                probe_tcp_loopback(bad,channel=channel(),logical_observed_at=20)
        with self.assertRaises(PathGroundRefused):
            probe_tcp_loopback((b"a",b"b"),channel=channel(),logical_observed_at=20,timeout_seconds=0)

    def test_candidate_kernel_fit_with_independent_holdouts(self):
        probes=observations()
        c=characterize_transfer(probes[0],probes[1],probes[2:],taps=3,tolerance=1e-11)
        self.assertEqual(c.kernel,(.625,.25,-.125))
        self.assertEqual(c.observation_count,5)
        self.assertLessEqual(c.worst_holdout_abs_error,1e-11)
        self.assertTrue(verify_transfer_candidate(c,probes[0],probes[1],probes[2:],taps=3,tolerance=1e-11))
        self.assertEqual(c.scope,"empirically_checked_probes_not_universal_law")
        self.assertEqual(c.mechanism,"software_fir_reference")

    def test_invalid_heldout_refuses_even_with_good_impulse(self):
        probes=observations(perturb=.2)
        with self.assertRaisesRegex(PathGroundRefused,"contradicts"):
            characterize_transfer(probes[0],probes[1],probes[2:],taps=3,tolerance=1e-6)

    def test_changed_input_or_output_refuses_memory(self):
        probes=observations()
        c=characterize_transfer(probes[0],probes[1],probes[2:],taps=3,tolerance=1e-10)
        altered=observations(perturb=.05)
        self.assertFalse(verify_transfer_candidate(c,altered[0],altered[1],altered[2:],taps=3,tolerance=1e-10))

    def test_nonlinearity_refused(self):
        probes=observations()
        target=probes[3]
        bad=replace(target,response=tuple(x+x*x*.01 for x in target.response))
        with self.assertRaises(PathGroundRefused):
            characterize_transfer(probes[0],probes[1],(probes[2],bad,probes[4]),taps=3,tolerance=1e-4)

    def test_shift_invariance_refused(self):
        probes=observations()
        shifted=replace(probes[1],response=tuple(x+.02 for x in probes[1].response))
        with self.assertRaises(PathGroundRefused):
            characterize_transfer(probes[0],shifted,probes[2:],taps=3,tolerance=1e-3)

    def test_mixed_provenance_refused(self):
        probes=observations()
        foreign=replace(probes[2],environment_digest="1"*64)
        with self.assertRaises(PathGroundRefused):
            characterize_transfer(probes[0],probes[1],(foreign,*probes[3:]),taps=3,tolerance=1e-3)
        foreign=replace(probes[2],mechanism="instrument_observation")
        with self.assertRaises(PathGroundRefused):
            characterize_transfer(probes[0],probes[1],(foreign,*probes[3:]),taps=3,tolerance=1e-3)

    def test_bad_calibration_receipts_refused(self):
        probes=observations()
        with self.assertRaises(PathGroundRefused):
            characterize_transfer(probes[0],probes[1],(probes[2],probes[2]),taps=3,tolerance=.01)
        with self.assertRaises(PathGroundRefused):
            characterize_transfer(probes[0],probes[1],(probes[2],),taps=3,tolerance=.01)
        with self.assertRaises(PathGroundRefused):
            characterize_transfer(probes[0],probes[1],probes[2:],taps=0,tolerance=.01)

    def test_nonfinite_measurements_refused(self):
        probes=observations()
        with self.assertRaises(PathGroundRefused):
            replace(probes[2],response=(float("nan"),)+probes[2].response[1:])
        with self.assertRaises(PathGroundRefused):
            fir_response((1,0),(.5,float("inf")))

    def test_only_sampled_envelope_is_certified(self):
        p=observations()
        c=characterize_transfer(p[0],p[1],p[2:],taps=3,tolerance=.01)
        with self.assertRaises(PathGroundRefused):
            replace(c,scope="universal_optical_law")
        self.assertNotIn("physical",c.mechanism)

    def test_fake_optical_claim_cannot_masquerade_as_software(self):
        p=observations()
        with self.assertRaises(PathGroundRefused):
            replace(p[2],mechanism="measured_fiber_without_instrument")



class NativeCarrierIntegrationTests(unittest.TestCase):
    def test_actual_tcp_probe_binds_native_observer_path_as_carrier(self):
        from mailcpu.path_ground_probe import bind_tcp_carrier_witness
        from mailcpu.semantic_translation import RepresentationRef, canonical_value_digest
        observed, delivered = probe_tcp_loopback((b"path",b"-ground"),channel=channel(),
                                                 logical_observed_at=17)
        ground=RepresentationRef.from_payload('path.byte-ground',1,
                                              {"rule":"identity_at_endpoint"})
        result=bind_tcp_carrier_witness(observed,sent=b"path-ground",received=delivered,
                         ground=ground,context_digest=canonical_value_digest({'scope':'local'}),
                         receiver_policy_digest=sha256(b'local-controlled-endpoint-verifier').hexdigest())
        self.assertEqual(len(result.stages),1)
        self.assertEqual(result.stages[0]['mode'],'carrier')
        self.assertEqual(result.input_ref,result.output_ref)
        self.assertEqual(result.ground,ground)

    def test_corruption_cannot_be_recoded_as_native_carrier_evidence(self):
        from mailcpu.path_ground_probe import bind_tcp_carrier_witness
        from mailcpu.semantic_translation import RepresentationRef, canonical_value_digest
        observed,delivered=probe_tcp_loopback((b"a",b"b"),channel=channel(),
                                               logical_observed_at=23)
        with self.assertRaises(PathGroundRefused):
            bind_tcp_carrier_witness(observed,sent=b"ab",received=b"ac",
                         ground=RepresentationRef.from_payload('path.byte-ground',1,{}),
                         context_digest=canonical_value_digest({'scope':'local'}),
                         receiver_policy_digest=sha256(b'local-policy').hexdigest())


class TemporalGroundRefusalTests(unittest.TestCase):
    def test_stable_endpoint_span_candidate_requires_heldouts(self):
        from mailcpu.path_ground_probe import characterize_temporal_span
        original,_=probe_tcp_loopback((b"a",b"b"),channel=channel(),logical_observed_at=40)
        samples=[replace(original,logical_observed_at=41+i,elapsed_ns=1000+i*4) for i in range(8)]
        accepted=characterize_temporal_span(samples[:5],samples[5:],
                                           nominal_elapsed_ns=1016,tolerance_ns=16)
        self.assertEqual(accepted.samples_checked,8)
        self.assertEqual(accepted.scope,"empirical_same_clock_endpoint_duration_only")

    def test_temporal_drift_refuses_a_predeclared_narrow_envelope(self):
        from mailcpu.path_ground_probe import characterize_temporal_span
        original,_=probe_tcp_loopback((b"a",b"b"),channel=channel(),logical_observed_at=40)
        samples=[replace(original,logical_observed_at=41+i,elapsed_ns=1000+i*2) for i in range(8)]
        bad=replace(samples[7],elapsed_ns=1900)
        with self.assertRaisesRegex(PathGroundRefused,"rejects"):
            characterize_temporal_span(samples[:5],(*samples[5:7],bad),
                                       nominal_elapsed_ns=1004,tolerance_ns=16)

    def test_timing_does_not_certify_multiple_path_identities(self):
        from mailcpu.path_ground_probe import characterize_temporal_span
        original,_=probe_tcp_loopback((b"a",b"b"),channel=channel(),logical_observed_at=40)
        samples=[replace(original,logical_observed_at=41+i,elapsed_ns=1000) for i in range(8)]
        samples[-1]=replace(samples[-1],channel=channel(source="foreign"))
        with self.assertRaises(PathGroundRefused):
            characterize_temporal_span(samples[:5],samples[5:],
                                       nominal_elapsed_ns=1000,tolerance_ns=10)


class AdditionalEvidenceControls(unittest.TestCase):
    def test_temporal_candidate_refuses_changed_evidence(self):
        from mailcpu.path_ground_probe import characterize_temporal_span,verify_temporal_candidate
        base,_=probe_tcp_loopback((b"a",b"b"),channel=channel(),logical_observed_at=40)
        records=[replace(base,logical_observed_at=40+i,elapsed_ns=2000) for i in range(8)]
        cert=characterize_temporal_span(records[:5],records[5:],nominal_elapsed_ns=2000,tolerance_ns=10)
        self.assertTrue(verify_temporal_candidate(cert,records[:5],records[5:],nominal_elapsed_ns=2000,tolerance_ns=10))
        mutated=[*records[5:]]
        mutated[-1]=replace(mutated[-1],elapsed_ns=2007)
        self.assertFalse(verify_temporal_candidate(cert,records[:5],mutated,nominal_elapsed_ns=2000,tolerance_ns=10))

    def test_extreme_signal_sample_refused_before_conversion(self):
        with self.assertRaises(PathGroundRefused):
            fir_response((10**400,1),(1.0,0.0))

    def test_malformed_holdout_refused_cleanly(self):
        probes=observations()
        with self.assertRaises(PathGroundRefused):
            characterize_transfer(probes[0],probes[1],(None,probes[2]),taps=3,tolerance=.01)

if __name__ == "__main__":
    unittest.main()