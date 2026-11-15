"""Run CAPACITY-001 against two E-CPU-unaware information paths.

From the E-CPU repository root:
    python -m examples.run_latent_path_capacity
"""
from __future__ import annotations

from hashlib import sha256
import json
import statistics
import time
from mailcpu.latent_path_capacity import recognize_capacity, verify_live_capacity


class UnawareCompositePath:
    """Pure external transition relation; no MailCPU installation or registration."""
    def __init__(self, first: tuple[int,int], second: tuple[int,int], modulus: int):
        self.first, self.second, self.modulus = first, second, modulus
        self.probes = 0

    def send(self, x: int) -> int:
        self.probes += 1
        carrier_state = (self.first[0] * x + self.first[1]) % self.modulus
        return (self.second[0] * carrier_state + self.second[1]) % self.modulus


def independent_power(a: int, b: int, modulus: int, initial: int, tick: int) -> int:
    acc_a, acc_b = 1, 0
    while tick:
        if tick & 1:
            acc_a, acc_b = a * acc_a % modulus, (a * acc_b + b) % modulus
        a, b = a * a % modulus, (a * b + b) % modulus
        tick >>= 1
    return (acc_a * initial + acc_b) % modulus


def main() -> None:
    modulus, initial, target = 101, 39, 10**30+11
    ctx=sha256(b"CAPACITY-001:test-owned:transition-frame-A").hexdigest()
    paths = [
        ("anonymous-dual-stage", UnawareCompositePath((3, 5), (7, 11), modulus)),
        ("alternate-dual-stage", UnawareCompositePath((1, 0), (21, 46), modulus)),
    ]
    entries = []
    for name, path in paths:
        start=time.perf_counter_ns()
        certificate=recognize_capacity(path.send,path_id=name,snapshot_id="epoch-1",
                                       context_digest=ctx,modulus=modulus)
        discovery_ns=time.perf_counter_ns()-start
        probes_before_jump=path.probes
        start=time.perf_counter_ns()
        destination=certificate.state_at(initial,target)
        navigate_ns=time.perf_counter_ns()-start
        assert destination==independent_power(21,46,modulus,initial,target)
        assert path.probes==probes_before_jump
        assert verify_live_capacity(certificate,path.send,snapshot_id="epoch-1",context_digest=ctx)
        entries.append({"path_id":name,"path_probes":probes_before_jump,
                        "discovery_ns":discovery_ns,"navigation_ns":navigate_ns,
                        "ground_digest":certificate.ground_digest,
                        "evidence_digest":certificate.evidence_digest,
                        "multiplier":certificate.multiplier,"increment":certificate.increment,
                        "logical_tick":str(target),"initial":initial,"result":destination,
                        "independent_dense_oracle":True,"live_reverification":True})
    assert len({e["ground_digest"] for e in entries})==1
    assert len({e["evidence_digest"] for e in entries})==2
    result={"schema":"mailcpu.capacity-recognition.reference.v1",
            "status":"bounded_exact_opaque_path_recognition",
            "scope":"declared_finite_snapshot_not_external_attestation",
            "paths":entries,"no_host_knows_ecpu":True,
            "total_probes_for_two_certificates":2*modulus,
            "navigated_without_trajectory_replay":True,
            "caveats":[
                "Paths are pre-existing software-defined test relations, not live internet routes.",
                "Exhaustive finite-domain verification establishes the modeled relation at a declared snapshot, not future stability.",
                "Logical-time navigation is algebraic; no path traverses 10^30 states.",
                "The external path's provenance and receiver authorization are separately owned.",
                "A self-consistent certificate without independent path observations does not prove an external host's behavior.",
            ]}
    print(json.dumps(result,sort_keys=True,indent=2))


if __name__=="__main__":main()