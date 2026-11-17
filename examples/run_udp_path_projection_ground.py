"""PATH-GROUND-002: a real network-stack transform becomes an E-CPU Ground.

Run: python -m examples.run_udp_path_projection_ground

Uses only owned 127.0.0.1 IPv4 sockets, no public Internet endpoints.
The kernel selects and queues datagrams; SOURCE Python prepares the numeric
stimuli. The distant-state result is a symbolic mathematical prediction, not
a claim that a public network router executed the affine recurrence.
"""
from __future__ import annotations

from hashlib import sha256
import json
import platform
import sys

from mailcpu.substrate_bootstrap import ChannelObservation
from mailcpu.structural_memory import StructuralMemoryRegistry
from mailcpu.udp_path_projection_ground import (
    SourceAffineStimulus, probe_connected_udp_projection,
    probe_unconnected_udp_control, recognize_kernel_projection_ground,
    verify_kernel_projection_ground,
)


def _channel(label: str) -> ChannelObservation:
    return ChannelObservation(
        channel_id="path002." + label, source="owned.sender." + label,
        target="owned.receiver." + label, carries=("bytes",),
        estimated_quanta=1, observed_at=1, expires_at=1000,
        evidence_digest=sha256(("local-controlled-kernel:" + label).encode()).hexdigest(),
        max_payload_bytes=8192,
    )


def run() -> dict:
    """Measure native kernel selection, bind its observed law, and navigate by Ground."""
    stimulus = SourceAffineStimulus(5, 1, 257, 7)
    bypass_trace, bypass_bytes = probe_unconnected_udp_control(
        stimulus, channel=_channel("bypass"), observed_at=9,
        first_coordinate=0, count=16,
    )
    train, train_trace, train_bytes = probe_connected_udp_projection(
        stimulus, channel=_channel("route-one"), observed_at=10,
        first_coordinate=0, count=16,
    )
    holdout, holdout_trace, holdout_bytes = probe_connected_udp_projection(
        stimulus, channel=_channel("route-two"), observed_at=11,
        first_coordinate=16, count=16,
    )
    ground = recognize_kernel_projection_ground(
        train, holdout, modulus=stimulus.modulus,
        train_trace=train_trace, train_received=train_bytes,
        holdout_trace=holdout_trace, holdout_received=holdout_bytes,
    )
    assert verify_kernel_projection_ground(
        ground, train, holdout, modulus=stimulus.modulus,
        train_trace=train_trace, train_received=train_bytes,
        holdout_trace=holdout_trace, holdout_received=holdout_bytes,
    )
    # A local trusted policy admits this exact observed mathematics. An
    # arbitrary sender or Internet endpoint cannot supply the policy.
    registry = StructuralMemoryRegistry(
        admission_policy=lambda p: (
            p.spec.domain == "path-native-kernel-selection-observer"
            and p.spec.context.get("mathematical_ground") == ground.ground_digest
            and p.spec.context.get("observation_evidence") == ground.evidence_digest
        ),
    )
    proposal = ground.propose_to_structural_memory(
        registry, "path002-kernel-selected-output", train, holdout,
    )
    admitted = registry.admit(proposal.proposal_id, expected_revision=0)
    logical_target = 10**30 + 113
    symbolic = ground.navigate(logical_target)
    native_read = registry.read_revision(
        "path002-kernel-selected-output", admitted.spec.revision,
        logical_target, context=admitted.spec.context,
    )
    assert native_read.value == symbolic["value"]
    return {
        "schema": "mailcpu.path-ground-002.reference-report.v1",
        "provenance": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "physical_path": "local_os_ipv4_udp_receive_queue",
            "internet_wide_route_tested": False,
            "authentication": "none_beyond_local_ownership",
            "sender_computed_stimuli": True,
            "receiver_performs_no_application_source_filter": True,
        },
        "counterfactual": {
            "without_kernel_peer_filter_received": len(bypass_bytes),
            "two_source_events": len(bypass_trace),
            "with_kernel_peer_filter_received": len(train_bytes),
            "with_filter_source_events": len(train_trace),
            "kernel_contribution": "source_peer_selection_and_pre_read_queue_retention",
        },
        "topology": {
            "first_path_receipt_digest": train.digest,
            "second_path_receipt_digest": holdout.digest,
            "physical_failure_domain": "same_local_machine",
            "first_socket": list(train.destination),
            "second_socket": list(holdout.destination),
            "first_peer": list(train.allowed_peer),
            "second_peer": list(holdout.allowed_peer),
            "receiver_ready_before_first_read": (
                train.ready_before_receive and holdout.ready_before_receive
            ),
            "first_receiver_idle_interval_ns": train.pause_ns,
            "second_receiver_idle_interval_ns": holdout.pause_ns,
        },
        "discovery": {
            "status": "finite_witness_empirical_candidate",
            "ground_digest": ground.ground_digest,
            "evidence_digest": ground.evidence_digest,
            "source_generated_base_law": {
                "a": stimulus.a, "c": stimulus.c, "modulus": stimulus.modulus,
                "initial": stimulus.initial,
            },
            "receiver_recovered_projected_law": {
                "a": ground.a, "c": ground.c, "modulus": ground.modulus,
                "initial": ground.initial,
            },
            "training_observations": ground.train_count,
            "withheld_observations_on_other_socket": ground.holdout_count,
        },
        "navigation": {
            "result": symbolic,
            "structural_memory_spec_digest": admitted.spec.digest,
            "structural_memory_certificate_digest": admitted.certificate.digest,
            "receiver_read_receipt": native_read.to_dict(),
            "source_network_packets_needed_to_observe_distant_state": None,
            "note": "The returned state is a symbolic projection of the finite-witness Ground, not a live measurement of the future kernel socket.",
        },
        "next": "Instrument a remote owned IPv4/IPv6 path with an authenticated endpoint and verify whether in-network transitions or queue relations preserve this Ground across distinct physical failure domains.",
    }


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, sort_keys=True))
