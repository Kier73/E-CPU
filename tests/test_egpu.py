from __future__ import annotations

import pytest

from mailcpu.classifier import HypervisorArbitrationEvent, HypervisorRequest
from mailcpu.egpu import EGPUError, EGPUHost, EGPUOperationalLocus
from mailcpu.transit_router import TransitBackendRouter


def _event(payload: dict[str, object], *, sequence: int = 1,
           granted: frozenset[str] = frozenset({"execute"})) -> HypervisorArbitrationEvent:
    """Mathematics: create a typed E-GPU operation event with a stable semantic identity."""

    request = HypervisorRequest(
        EGPUHost.operation_name, EGPUHost.resource_name, payload,
        frozenset({"execute"}), granted, False,
    )
    return HypervisorArbitrationEvent("test-client", "egpu", sequence, 7, request)


def test_egpu_vector_methods_navigate_simt_and_verify_scalar_results() -> None:
    """Mathematics: lane-wise vector add and multiply equal independent scalar integer projections."""

    host = EGPUHost(host_id="egpu.test")
    left, right = [1, -2, 7, 12], [9, 5, -3, 8]
    added = host.handle(_event({"method": "vector.add", "left": left, "right": right, "max_steps": 16}))
    multiplied = host.handle(_event({"method": "vector.multiply", "left": left, "right": right, "max_steps": 16}, sequence=2))
    assert added["route"] == ["egpu.test.dispatch", "egpu.test.simt", "egpu.test.verify"]
    assert added["result"]["outputs"]["result"] == [a + b for a, b in zip(left, right)]
    assert multiplied["result"]["outputs"]["result"] == [a * b for a, b in zip(left, right)]
    assert len(added["result_digest"]) == len(added["receipt_digest"]) == 64
    assert added["receipt_digest"] != multiplied["receipt_digest"]


def test_egpu_tree_reduction_uses_stable_method_route_and_digest() -> None:
    """Mathematics: pairwise reduction preserves scalar sum and canonical level trace."""

    host = EGPUHost(host_id="egpu.reduce")
    payload = {"method": "vector.sum", "values": [3, -1, 8, 2, 4], "max_steps": 8}
    first, second = host.handle(_event(payload)), host.handle(_event(payload))
    assert first == second
    assert first["route"] == ["egpu.reduce.dispatch", "egpu.reduce.reduce", "egpu.reduce.verify"]
    assert first["result"]["sum"] == 16
    assert first["result"]["levels"] == 3
    assert first["result"]["work_units"] == 4
    assert first["result"]["trace"][-1]["output_width"] == 1


def test_egpu_general_simt_kernel_uses_existing_reference_instruction_algebra() -> None:
    """Mathematics: a custom bounded lane kernel preserves its SIMT output and route witness."""

    host = EGPUHost()
    result = host.handle(_event({
        "method": "simt.kernel", "lanes": 3, "inputs": {"x": [2, 4, 6]},
        "program": [["load", "value", "x"], ["mul", "square", "value", "value"],
                    ["store", "squares", "square"], ["halt"]],
        "max_steps": 16,
    }))
    assert result["result"]["outputs"]["squares"] == [4, 16, 36]
    assert result["route"] == ["egpu.default.dispatch", "egpu.default.simt", "egpu.default.verify"]


def test_egpu_route_resolution_is_minimum_hop_and_lexically_deterministic() -> None:
    """Mathematics: equal-hop routes to a capability select the lexically first path."""

    loci = (
        EGPUOperationalLocus("custom.dispatch", "dispatch", frozenset({"egpu.dispatch"}), ("custom.z", "custom.a")),
        EGPUOperationalLocus("custom.z", "relay", frozenset({"relay.z"}), ("custom.simt",)),
        EGPUOperationalLocus("custom.a", "relay", frozenset({"relay.a"}), ("custom.simt",)),
        EGPUOperationalLocus("custom.simt", "execution", frozenset({"simt.execute"}), ("custom.verify",)),
        EGPUOperationalLocus("custom.verify", "verification", frozenset({"result.verify"}), ()),
    )
    assert EGPUHost(host_id="egpu.custom", loci=loci).resolve_path("simt.execute") == (
        "custom.dispatch", "custom.a", "custom.simt", "custom.verify",
    )


def test_egpu_refuses_missing_authority_and_unreachable_method_locus() -> None:
    """Mathematics: execution requires the exact outer grant and a complete directed route."""

    payload = {"method": "vector.add", "left": [1, 2], "right": [3, 4], "max_steps": 8}
    with pytest.raises(EGPUError, match="receiver-local execute authority"):
        EGPUHost().handle(_event(payload, granted=frozenset()))
    loci = (
        EGPUOperationalLocus("broken.dispatch", "dispatch", frozenset({"egpu.dispatch"}), ("broken.verify",)),
        EGPUOperationalLocus("broken.simt", "execution", frozenset({"simt.execute"}), ("broken.verify",)),
        EGPUOperationalLocus("broken.verify", "verification", frozenset({"result.verify"}), ()),
    )
    with pytest.raises(EGPUError, match="no operational path"):
        EGPUHost(host_id="egpu.broken", loci=loci).handle(_event(payload))


def test_egpu_is_an_exact_backend_in_the_heterogeneous_transit_router() -> None:
    """Mathematics: E-GPU dispatch occurs only under its exact operation/resource key."""

    router = TransitBackendRouter()
    router.register_backend(EGPUHost(host_id="egpu.routed"))
    assert (EGPUHost.operation_name, EGPUHost.resource_name) in router.registered_backends()
    result = router.handle(_event({"method": "vector.add", "left": [5, 6], "right": [7, 8], "max_steps": 8}))
    assert result["result"]["outputs"]["result"] == [12, 14]
    with pytest.raises(ValueError, match="already registered"):
        router.register_backend(EGPUHost(host_id="egpu.duplicate"))
