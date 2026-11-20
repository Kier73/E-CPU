"""NCB-004 model-generated regression: existing mathematical compiler tests E-CPU.

Do not replace source-generated cases with hand-encoded expected trajectories:
that would measure a fixture, not direct use of constructed systems in development.
"""
from __future__ import annotations

import json
from hashlib import sha256

import pytest

pytest.importorskip(
    "navigable_compute.coupled",
    reason="dedicated NCB-004 CI checks out immutable NCP-002 producer",
)

from generated_controller_conformance import run_conformance


def test_intention_generated_processors_exercise_native_e_cpu_implementations() -> None:
    """Generated variants independently execute through real native Hypervisor."""
    report=run_conformance(max_instances=2)
    assert report["schema"]=="mailcpu.ncb004.generated-development-conformance.v1"
    assert report["generated_cases"]>=20
    assert report["generated_instances"]==4
    assert report["distinct_instance_digests"]==4
    assert report["native_handler_invocations"]>=report["generated_cases"]
    assert report["unsupported_receiver_capacity_refused"] is True
    assert {r["source_case"] for r in report["runs"]}=={
        "shared-capacity","joint-unsafe",
    }
    for run in report["runs"]:
        assert run["source_ground_verified"] and run["native_receiver_verified"]
        assert run["source_winning_states_tested"]>=1
        assert run["native_handler_invocations"]>=run["source_winning_states_tested"]
        assert run["packet_bytes"]>128
        assert run["native_verified_steps_ns"]>0
        assert run["receiver_verification_ns"]>0
    raw={k:v for k,v in report.items() if k!="sha256"}
    assert sha256(json.dumps(raw,sort_keys=True,separators=(",",":"),
                             ensure_ascii=True).encode()).hexdigest()==report["sha256"]


def test_budget_refuses_unbounded_development_experiment() -> None:
    """A test generator is still subject to explicit computational budgets."""
    for invalid in (-1,0,13,True,1.0):
        with pytest.raises(ValueError):
            run_conformance(max_instances=invalid)
