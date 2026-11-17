"""PATH-GROUND-002: real owned kernel UDP filter versus bypass and symbolic Ground.

All live probes run on 127.0.0.1. They do NOT assert physical Internet
routing, independent hardware, authenticated source identity, or optical math.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import replace
from hashlib import sha256
import unittest

from mailcpu.substrate_bootstrap import ChannelObservation
from mailcpu.structural_memory import (
    StructuralMemoryRegistry, StructuralMemoryAuthorizationError,
)
from mailcpu.udp_path_projection_ground import (
    KernelUdpProjectionObservation, NativePathGroundRefused, SourceAffineStimulus,
    probe_connected_udp_projection, probe_unconnected_udp_control,
    recognize_kernel_projection_ground, verify_kernel_projection_ground,
    verify_kernel_udp_projection,
)


def channel(identifier: str = "route-a", *, max_bytes: int = 8192):
    return ChannelObservation(
        channel_id="path002." + identifier,
        source="owned.sender." + identifier,
        target="owned.receiver." + identifier,
        carries=("bytes",), estimated_quanta=1, observed_at=1,
        expires_at=1000,
        evidence_digest=sha256(("local-udp-policy:" + identifier).encode()).hexdigest(),
        max_payload_bytes=max_bytes,
    )


def source():
    """All numeric arithmetic is admitted as sender-side probe preparation."""
    return SourceAffineStimulus(a=5, c=1, modulus=257, initial=7)


def observations(*, holdout_source=None):
    """Two independent live socket bindings observing consecutive output windows."""
    stimulus = source()
    first = probe_connected_udp_projection(
        stimulus, channel=channel("route-a"), observed_at=10,
        first_coordinate=0, count=16,
    )
    second = probe_connected_udp_projection(
        stimulus if holdout_source is None else holdout_source,
        channel=channel("route-b"), observed_at=20,
        first_coordinate=16, count=12,
    )
    return first, second


def recognized(first, second, *, modulus=257):
    return recognize_kernel_projection_ground(
        first[0], second[0], modulus=modulus,
        train_trace=first[1], train_received=first[2],
        holdout_trace=second[1], holdout_received=second[2],
    )


def independent_affine_power(a, c, m, x0, t):
    """Independent affine composition: no existing law_certifier calls."""
    multiplier, offset = 1, 0
    while t:
        if t & 1:
            multiplier, offset = a * multiplier % m, (a * offset + c) % m
        c, a = (a + 1) * c % m, a * a % m
        t >>= 1
    return (multiplier * x0 + offset) % m


class LiveKernelNetworkTests(unittest.TestCase):
    def test_real_kernel_filters_nonselected_packets_and_retains_queue_until_read(self):
        obs, trace, frames = probe_connected_udp_projection(
            source(), channel=channel(), observed_at=10,
            first_coordinate=0, count=12, pause_seconds=0.012,
        )
        self.assertEqual(len(trace), 24)
        self.assertEqual(len(frames), 12)
        self.assertTrue(obs.ready_before_receive)
        self.assertTrue(obs.no_extra_datagrams)
        self.assertGreater(obs.pause_ns, 0)
        self.assertEqual(obs.source_count, 24)
        self.assertEqual(obs.result_values, tuple(source().at(2 * i) for i in range(12)))
        self.assertTrue(verify_kernel_udp_projection(obs, trace, frames, channel=channel()))
        self.assertNotEqual(obs.allowed_peer, obs.unselected_peer)
        self.assertNotEqual(obs.allowed_peer, obs.destination)
        self.assertEqual(obs.mechanism, "os_connected_ipv4_udp_source_filter")
        self.assertIn("not_physical_path", obs.scope)

    def test_bypass_without_kernel_peer_filter_receives_both_sources(self):
        trace, received = probe_unconnected_udp_control(
            source(), channel=channel("bypass"), observed_at=11,
            first_coordinate=0, count=12,
        )
        self.assertEqual(len(trace), len(received))
        self.assertEqual(Counter(received),
                         Counter(item["value"].to_bytes(4, "big") for item in trace))
        self.assertEqual(len(received), 24)

    def test_topology_rebinding_preserves_mathematical_ground_and_changes_path_evidence(self):
        (a, a_trace, a_frames), (b, b_trace, b_frames) = observations()
        self.assertNotEqual(a.channel.channel_id, b.channel.channel_id)
        self.assertNotEqual(a.destination, b.destination)
        self.assertNotEqual(a.digest, b.digest)
        ground = recognize_kernel_projection_ground(
            a, b, modulus=257, train_trace=a_trace, train_received=a_frames,
            holdout_trace=b_trace, holdout_received=b_frames,
        )
        self.assertEqual((ground.a, ground.c, ground.modulus, ground.initial),
                         (25, 6, 257, 7))
        self.assertTrue(verify_kernel_projection_ground(
            ground, a, b, modulus=257, train_trace=a_trace,
            train_received=a_frames, holdout_trace=b_trace,
            holdout_received=b_frames,
        ))
        self.assertEqual(ground.navigate(27)["value"], source().at(54))

    def test_distinct_native_socket_runs_support_one_ground_but_unique_evidence(self):
        first, second = observations()
        ground = recognized(first, second)
        first_again, second_again = observations()
        repeated = recognized(first_again, second_again)
        self.assertEqual(ground.ground_digest, repeated.ground_digest)
        self.assertNotEqual(ground.evidence_digest, repeated.evidence_digest)
        self.assertEqual(ground.scope, repeated.scope)

    def test_distant_state_navigation_does_not_replay_udp_writes(self):
        first, second = observations()
        ground = recognized(first, second)
        distant = 10**30 + 113
        result = ground.navigate(distant)
        self.assertEqual(result["value"], independent_affine_power(
            ground.a, ground.c, ground.modulus, ground.initial, distant,
        ))
        self.assertEqual(result["network_packets_sent_for_navigation"], 0)
        self.assertEqual(result["ground_digest"], ground.ground_digest)
        self.assertEqual(
            result["scope"], "symbolic_prediction_not_physical_replay_or_live_future_proof",
        )


class EvidenceAndRefusalTests(unittest.TestCase):
    def test_receiver_bytes_are_required_for_independent_verification(self):
        first, second = observations()
        observed, trace, frames = first
        bad = list(frames)
        bad[-1] = b"\x00\x00\x00\x00"
        self.assertFalse(verify_kernel_udp_projection(
            observed, trace, bad, channel=observed.channel,
        ))
        self.assertFalse(verify_kernel_projection_ground(
            recognized(first, second), observed, second[0], modulus=257,
            train_trace=trace, train_received=tuple(bad),
            holdout_trace=second[1], holdout_received=second[2],
        ))

    def test_source_trace_tampering_or_wrong_direction_refused(self):
        (obs, trace, frames), _ = observations()
        corrupted = [dict(v) for v in trace]
        corrupted[1]["role"] = "selected"
        self.assertFalse(verify_kernel_udp_projection(
            obs, corrupted, frames, channel=obs.channel,
        ))
        self.assertFalse(verify_kernel_udp_projection(
            obs, trace, frames, channel=channel("other"),
        ))

    def test_changed_sender_law_on_other_socket_is_not_same_ground(self):
        first, other = observations(holdout_source=SourceAffineStimulus(5, 2, 257, 7))
        with self.assertRaisesRegex(NativePathGroundRefused, "contradicts"):
            recognized(first, other)

    def test_same_channel_identity_does_not_count_as_topology_rebinding(self):
        first, second = observations()
        duplicate = replace(second[0], channel=first[0].channel)
        with self.assertRaisesRegex(NativePathGroundRefused, "topology"):
            recognize_kernel_projection_ground(
                first[0], duplicate, modulus=257,
                train_trace=first[1], train_received=first[2],
                holdout_trace=second[1], holdout_received=second[2],
            )

    def test_source_filter_or_queue_claim_cannot_be_conjured_from_digest(self):
        obs, _trace, _frames = observations()[0]
        with self.assertRaises(NativePathGroundRefused):
            replace(obs, mechanism="physical_fiber_computer")
        with self.assertRaises(NativePathGroundRefused):
            replace(obs, ready_before_receive=False)
        with self.assertRaises(NativePathGroundRefused):
            replace(obs, no_extra_datagrams=False)
        with self.assertRaises(NativePathGroundRefused):
            replace(obs, allowed_peer=obs.unselected_peer)

    def test_noncanonical_numeric_and_resource_inputs_fail_before_socket(self):
        with self.assertRaises(NativePathGroundRefused):
            SourceAffineStimulus(a=True, c=1, modulus=257, initial=7)
        with self.assertRaises(NativePathGroundRefused):
            probe_connected_udp_projection(
                source(), channel=channel(max_bytes=12), observed_at=10,
                first_coordinate=0, count=12,
            )
        with self.assertRaises(NativePathGroundRefused):
            probe_connected_udp_projection(
                source(), channel=channel(), observed_at=1001,
                first_coordinate=0, count=12,
            )
        with self.assertRaises(NativePathGroundRefused):
            recognized(*observations(), modulus=2)

    def test_no_unsupported_future_technology_claims(self):
        first, second = observations()
        ground = recognized(first, second)
        with self.assertRaises(NativePathGroundRefused):
            replace(ground, scope="universal_public_internet_operator")
        with self.assertRaises(NativePathGroundRefused):
            ground.navigate(10**35 + 1)
        self.assertIn("empirical", ground.scope)


class ExistingStructuralMemoryIntegrationTests(unittest.TestCase):
    def test_result_may_be_proposed_but_requires_receiver_owned_admission(self):
        first, second = observations()
        ground = recognized(first, second)
        memory_id = "kernel-filter-observed-orbit"
        registry = StructuralMemoryRegistry(
            admission_policy=lambda proposal: (
                proposal.spec.domain == "path-native-kernel-selection-observer"
                and proposal.spec.context["mathematical_ground"] == ground.ground_digest
            ),
        )
        proposal = ground.propose_to_structural_memory(
            registry, memory_id, first[0], second[0],
            train_trace=first[1], train_received=first[2],
            holdout_trace=second[1], holdout_received=second[2],
        )
        self.assertEqual(proposal.spec.family, "lcg")
        self.assertEqual(proposal.spec.context["observation_evidence"], ground.evidence_digest)
        self.assertEqual(proposal.spec.digest, registry.staged_proposal(proposal.proposal_id).spec.digest)
        self.assertIsNone(registry.active_version(memory_id))
        version = registry.admit(proposal.proposal_id, expected_revision=0)
        self.assertEqual(version.spec.digest, proposal.spec.digest)
        coordinate = 10**18 + 7
        receipt = registry.read_revision(
            memory_id, 1, coordinate, context=version.spec.context,
        )
        self.assertEqual(receipt.value, ground.navigate(coordinate)["value"])
        self.assertEqual(receipt.spec_digest, version.spec.digest)
        self.assertEqual(receipt.certificate_digest, version.certificate.digest)

    def test_untrusted_ground_or_missing_admission_authority_refused(self):
        first, second = observations()
        ground = recognized(first, second)
        registry = StructuralMemoryRegistry()
        proposal = ground.propose_to_structural_memory(
            registry, "not-admitted-path", first[0], second[0],
            train_trace=first[1], train_received=first[2],
            holdout_trace=second[1], holdout_received=second[2],
        )
        with self.assertRaises(StructuralMemoryAuthorizationError):
            registry.admit(proposal.proposal_id, expected_revision=0)
        self.assertIsNone(registry.active_version("not-admitted-path"))

    def test_structural_memory_stage_requires_original_receive_bytes(self):
        """A forged read receipt is not interchangeable with the real checked socket bytes."""
        first, second = observations()
        ground = recognized(first, second)
        registry = StructuralMemoryRegistry(admission_policy=lambda _p: True)
        changed = list(second[2])
        changed[0] = b"\\x00\\x00\\x00\\x00"
        with self.assertRaisesRegex(NativePathGroundRefused, "unverified original native path evidence"):
            ground.propose_to_structural_memory(
                registry, "tampered-original-endpoint", first[0], second[0],
                train_trace=first[1], train_received=first[2],
                holdout_trace=second[1], holdout_received=tuple(changed),
            )
        self.assertIsNone(registry.active_version("tampered-original-endpoint"))

    def test_cross_intention_witnesses_cannot_attach_to_other_ground(self):
        first, second = observations()
        ground = recognized(first, second)
        altered = replace(ground, c=(ground.c + 1) % ground.modulus)
        registry = StructuralMemoryRegistry(admission_policy=lambda _proposal: True)
        with self.assertRaisesRegex(NativePathGroundRefused, "unverified original native path evidence"):
            altered.propose_to_structural_memory(
                registry, "corrupted-intent", first[0], second[0],
                train_trace=first[1], train_received=first[2],
                holdout_trace=second[1], holdout_received=second[2],
            )


if __name__ == "__main__":
    unittest.main()
