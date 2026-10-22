from __future__ import annotations

import math

import pytest

from mailcpu import (
    ClassifierHypervisor,
    HypervisorAction,
    HypervisorDomain,
    HypervisorRequest,
    IntentEmbedding,
    IntentEmbeddingError,
    IntentExample,
    IntentPrototypeModel,
    LexicalDecisionModel,
    estimate_virtual_cost,
    structural_tokens,
)


def test_structural_embedding_is_deterministic_normalized_and_typed() -> None:
    """Mathematics: verify `φ(x)=φ(x)` for repeated input, `||φ(x)||₂=1`, and typed paths affect identity."""

    state = {
        "operation": "read filesystem file path",
        "resource": "/home/data",
        "payload": {"path": "/home/data", "size": 32},
    }
    encoder = IntentEmbedding(dimension=128)
    first = encoder.encode(state)
    second = encoder.encode(state)
    renamed = encoder.encode({**state, "resource": "/network/data"})
    assert first == second
    assert first.digest != renamed.digest
    assert math.isclose(sum(value * value for value in first.vector), 1.0, abs_tol=1e-12)
    assert first.token_count == len(structural_tokens(state))
    assert first.to_dict()["norm_l2"] == pytest.approx(1.0)


def test_structural_embedding_refuses_unbounded_input_instead_of_truncating() -> None:
    """Mathematics: verify `|T(x)|>B ⇒ refusal`, preserving the information-loss boundary."""

    with pytest.raises(IntentEmbeddingError):
        structural_tokens({"items": [f"item-{index}" for index in range(32)]}, max_tokens=16)


def test_prototype_model_routes_held_out_typed_requests_and_round_trips() -> None:
    """Mathematics: verify `argmax_d μ_d·φ(x)` selects held-out domains and checkpoint regeneration is exact."""

    model = IntentPrototypeModel.default()
    held_out = {
        "filesystem": {"operation": "inspect filesystem descriptor file", "resource": "/srv/data", "payload": {"path": "/srv/data"}},
        "network": {"operation": "receive network packet socket", "resource": "/network/2", "payload": {"route": "remote"}},
        "service": {"operation": "stop service process supervisor", "resource": "/service/worker", "payload": {"service": "worker"}},
    }
    for expected, state in held_out.items():
        prediction = model.predict(state)
        assert prediction.domain == expected
        assert abs(sum(prediction.probabilities.values()) - 1.0) <= 1e-9
    restored = IntentPrototypeModel.from_snapshot(model.snapshot())
    assert restored.snapshot() == model.snapshot()
    assert restored.predict(held_out["network"]).to_dict() == model.predict(held_out["network"]).to_dict()


def test_virtual_time_preserves_ceiling_identity_and_monotonic_work_price() -> None:
    """Mathematics: verify `(τ_v−1)C<E_v≤τ_vC` and adding structure cannot reduce `E_v`."""

    small = {"operation": "read", "resource": "/x", "payload": {}}
    large = {"operation": "read", "resource": "/x", "payload": {"items": ["x" * 16 for _ in range(8)]}}
    small_cost = estimate_virtual_cost(small, capacity=64)
    large_cost = estimate_virtual_cost(large, capacity=64)
    assert (small_cost.virtual_ticks - 1) * small_cost.capacity < small_cost.virtual_energy <= small_cost.virtual_ticks * small_cost.capacity
    assert large_cost.virtual_energy >= small_cost.virtual_energy
    assert large_cost.virtual_ticks >= small_cost.virtual_ticks
    assert large_cost.to_dict()["evidence_tier"] == "E0"


def test_high_confidence_embedding_disagreement_requires_review_without_authority() -> None:
    """Mathematics: verify `ALLOW ∧ c_embedding≥τ ∧ d_embedding≠d_exact ⇒ REVIEW`, with no permission bypass."""

    state = {"operation": "read filesystem file path descriptor", "resource": "/home/file", "payload": {"path": "/home/file"}}
    intent_model = IntentPrototypeModel.fit(
        (
            IntentExample("network", state),
            IntentExample("filesystem", {"operation": "write file", "resource": "/tmp", "payload": {"path": "/tmp"}}),
        ),
        temperature=0.05,
    )
    hypervisor = ClassifierHypervisor(classifier=LexicalDecisionModel(), intent_model=intent_model)
    decision, result = hypervisor.dispatch(
        HypervisorRequest(state["operation"], state["resource"], state["payload"]),
        {HypervisorDomain.FILESYSTEM: lambda: "must-not-run"},
    )
    assert decision.action is HypervisorAction.REVIEW
    assert result is None
    assert decision.intent_domain == "network"
    assert decision.to_dict()["virtual_cost"] is not None


def test_capability_denial_remains_stronger_than_embedding_disagreement() -> None:
    """Mathematics: verify `R⊄G ⇒ DENY` even when the advisory model strongly disagrees with exact routing."""

    state = {"operation": "read filesystem file path descriptor", "resource": "/home/file", "payload": {"path": "/home/file"}}
    intent_model = IntentPrototypeModel.fit(
        (IntentExample("network", state), IntentExample("filesystem", {"operation": "write file", "resource": "/tmp", "payload": {}})),
        temperature=0.05,
    )
    decision = ClassifierHypervisor(classifier=LexicalDecisionModel(), intent_model=intent_model).decide(
        HypervisorRequest(state["operation"], state["resource"], state["payload"], frozenset({"read"}), frozenset())
    )
    assert decision.action is HypervisorAction.DENY


def test_headless_hypervisor_receipt_contains_scheduler_epoch_and_virtual_price() -> None:
    """Mathematics: verify `H(request,τ)` records the scheduler epoch and `τ_v=ceil(E_v/C)` before an allowed handler."""

    from mailcpu import HeadlessOS

    operating_system = HeadlessOS()
    pid = operating_system.environment.init_pid
    operating_system.environment.kernel.fs.create_file("/home/time", b"time")
    decision, contents = operating_system.hypervisor_read_file(pid, "/home/time")
    assert decision.action is HypervisorAction.ALLOW
    assert contents == b"time"
    record = next(record for record in reversed(operating_system.hypervisor.journal.records()) if record.kind == "hypervisor.decision")
    request = record.payload["request"]
    assert set(request["temporal"]) == {"event_lambda", "chronon_real", "chronon_imag", "chemical_tau"}
    cost = record.payload["virtual_cost"]
    assert (cost["virtual_ticks"] - 1) * cost["capacity"] < cost["virtual_energy"] <= cost["virtual_ticks"] * cost["capacity"]
