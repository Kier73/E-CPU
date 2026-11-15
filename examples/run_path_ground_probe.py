"""PATH-GROUND-001 reference experiment with REAL loopback and MODEL transfer.

Run from E-CPU repository root: python -m examples.run_path_ground_probe

Only 127.0.0.1 is used; no external resources, optical fiber, or remote hosts.
"""
from __future__ import annotations

from hashlib import sha256
import json
import platform
from statistics import median
import sys

from mailcpu.path_ground_probe import (
    TransferObservation, characterize_transfer, fir_response, bind_tcp_carrier_witness,
    probe_tcp_loopback, verify_tcp_path, verify_transfer_candidate,
    characterize_temporal_span, PathGroundRefused,
)
from mailcpu.substrate_bootstrap import ChannelObservation
from mailcpu.semantic_translation import RepresentationRef, canonical_value_digest


def run() -> dict:
    channel=ChannelObservation(
        channel_id='localhost.tcp.001',source='local.sender',target='local.observer',
        carries=('bytes',),estimated_quanta=1,observed_at=10,expires_at=1000,
        evidence_digest=sha256(b'local-clock-and-loopback-observation-no-peer-attestation').hexdigest(),
        max_payload_bytes=65536,
    )
    payload=b'E-CPU observed communication-path identity | '+bytes(range(256))
    parts=(payload[:13], payload[13:27], payload[27:181], payload[181:])
    elapsed=[]
    recv_counts=[]
    digests=[]
    live_samples=[]
    first=None
    last_observation=None
    last_output=None
    for logical_coordinate in range(20,52):
        witness, output=probe_tcp_loopback(parts,channel=channel,
                                           logical_observed_at=logical_coordinate)
        assert verify_tcp_path(witness,sent=payload,received=output,channel=channel,
                               logical_observed_at=logical_coordinate)
        if first is None:first=witness.to_dict()
        last_observation=witness
        last_output=output
        live_samples.append(witness)
        elapsed.append(witness.elapsed_ns)
        recv_counts.append(witness.recv_calls)
        digests.append(witness.digest)
    
    assert last_observation is not None and last_output is not None
    ground=RepresentationRef.from_payload('path.byte-ground',1,
                                          {'rule':'exact_stream_reassembly_at_receiver'})
    native_witness=bind_tcp_carrier_witness(
        last_observation,sent=payload,received=last_output,ground=ground,
        context_digest=canonical_value_digest({'controlled_environment':'local_loopback'}),
        receiver_policy_digest=sha256(b'test-controller-checks-live-endpoint-bytes').hexdigest(),
    )

    # Freeze a practical timing tolerance before inspecting the heldouts.
    # Calibration may itself fail; that is useful evidence, not a test failure.
    timing_nominal=int(median(elapsed[:16]))
    timing_tolerance=25_000  # ns, explicit experimental policy not optical timing accuracy
    try:
        timing=characterize_temporal_span(live_samples[:16],live_samples[16:],
                    nominal_elapsed_ns=timing_nominal,tolerance_ns=timing_tolerance)
        timing_result={'status':'accepted_for_observed_endpoint_span_only',
                       'certificate':timing.to_dict()}
    except PathGroundRefused as exc:
        timing_result={'status':'refused', 'reason':str(exc),
                       'nominal_ns':timing_nominal,'tolerance_ns':timing_tolerance}

    # Synthetic software transfer kernel. It is NOT claimed to be a measured
    # physical/optical kernel. Independent probes keep false assumptions visible.
    transfer_kernel=(0.625,0.25,-0.125)
    n=9
    stimuli=[(1,)+(0,)*(n-1),(0,1)+(0,)*(n-2),
             (1,3,-2,0,1,0,-1,0,2),(2,0,1,-1,4,3,1,-1,0),
             (-3,1,0,2,1,-1,2,3,4)]
    env=sha256(b'synthetic-known-FIR-controlled-reference').hexdigest()
    samples=[TransferObservation(tuple(x),fir_response(x,transfer_kernel),
                                 'software_fir_reference',env,f'transfer-{i}')
             for i,x in enumerate(stimuli)]
    candidate=characterize_transfer(samples[0],samples[1],samples[2:],taps=3,tolerance=1e-12)
    assert verify_transfer_candidate(candidate,samples[0],samples[1],samples[2:],
                                     taps=3,tolerance=1e-12)
    report={
        'schema':'mailcpu.path-ground-001.reference-report.v1',
        'provenance':{'python':sys.version.split()[0],'platform':platform.platform(),
                      'repository':'Kier73/E-CPU', 'external_network_used':False},
        'tcp_experiment':{
            'status':'live_os_loopback_observation',
            'what_this_proves':'32 locally verified ordered byte streams and corresponding endpoint elapsed time intervals',
            'what_this_does_not_prove':'optical transfer, physically independent host, pure fiber time-of-flight, stable delay law, or E-CPU executing in the medium',
            'probes':len(elapsed),'input_bytes':len(payload),'write_calls_per_probe':len(parts),
            'received_bytes_match':True,
            'clock_domain':'one_process_monotonic_ns',
            'elapsed_ns':{'min':min(elapsed),'median':median(elapsed),'max':max(elapsed)},
            'observed_recv_call_range':[min(recv_counts),max(recv_counts)],
            'first_probe':first,
            'native_e_cpu_carrier_path_witness':native_witness.to_dict(),
            'declared_duration_envelope':timing_result,
            'probe_identity_digest':sha256(json.dumps(digests,sort_keys=True).encode()).hexdigest(),
        },
        'transfer_experiment':{
            'status':'software_reference_not_physical_measurement',
            'what_this_proves':'bounded LTI candidate fits exact impulse, shift, and three independent held-out synthetic probes',
            'what_this_does_not_prove':'any actual fiber performed this FIR transformation',
            'witness':candidate.to_dict(),
            'held_out_count':3,
        },
        'next_measurement':'replace software FIR reference with instrument-acquired optical-path input/output; retain heldouts, environment controls and explicit equipment/receiver cost accounting',
    }
    return report


def main() -> None:
    print(json.dumps(run(),sort_keys=True,indent=2))


if __name__=='__main__':main()