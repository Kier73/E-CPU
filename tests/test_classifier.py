from __future__ import annotations

import pytest

from mailcpu.vl_procedural_primitives import feistel_open, feistel_seal, feistel_stream_byte
from mailcpu import (
    ChoiceAnswer,
    ChoiceQuestion,
    ClassifierHypervisor,
    HeadlessOS,
    HypervisorAction,
    HypervisorDomain,
    HypervisorRequest,
    LexicalDecisionModel,
    NoulAnswer,
    NoulQuestion,
    ScoreQuestion,
    choice_confidence,
    score_confidence,
)
from mailcpu.vl_procedural_primitives import feistel_open, feistel_seal, feistel_stream_byte
from mailcpu import (
    ProceduralDecisionModel,
    ProceduralModelSpec,
    ProceduralWeightField,
    ServiceSpec,
)


def test_typed_primitives_preserve_probability_invariants() -> None:
    """Mathematics: verify `Σ_i p_i=1`, Choice confidence, Score expectation, and binary bounds."""

    assert choice_confidence({"a": 0.7, "b": 0.3}) == pytest.approx(0.4)
    score = score_confidence((0.0, 0.2, 0.8))
    assert 0.0 < score < 1.0
    model = LexicalDecisionModel()
    batch = model.evaluate(
        {"operation": "read filesystem file path"},
        {
            "domain": ChoiceQuestion.from_mapping(
                "choose a domain",
                {"filesystem": "file path descriptor", "network": "packet socket"},
            ),
            "risk": NoulQuestion("is this destructive?", "delete overwrite", "read inspect"),
            "quality": ScoreQuestion("how strong is the match?", ("weak", "medium", "strong")),
        },
    )
    choice = batch.answers["domain"]
    risk = batch.answers["risk"]
    assert isinstance(choice, ChoiceAnswer)
    assert isinstance(risk, NoulAnswer)
    assert abs(sum(choice.probabilities.values()) - 1.0) <= 1e-9
    assert 0.0 <= risk.noul <= 1.0


def test_hypervisor_allows_clear_read_and_dispatches_one_handler() -> None:
    """Mathematics: verify `ALLOW ⇒ exactly one selected handler` for a high-confidence non-destructive request."""

    hypervisor = ClassifierHypervisor()
    request = HypervisorRequest(
        "read filesystem file path descriptor",
        "/home/file",
        {"path": "/home/file"},
        frozenset({"read"}),
        frozenset({"read"}),
    )
    calls: list[str] = []
    decision, result = hypervisor.dispatch(
        request,
        {HypervisorDomain.FILESYSTEM: lambda: calls.append("filesystem") or b"contents"},
    )
    assert decision.action is HypervisorAction.ALLOW
    assert decision.domain is HypervisorDomain.FILESYSTEM
    assert decision.confidence >= 0.70
    assert result == b"contents"
    assert calls == ["filesystem"]
    assert hypervisor.journal.verify()


def test_hypervisor_decision_is_journaled_before_the_reply() -> None:
    """Mathematics: `dispatch` appends the `hypervisor.decision` record before entering the handler, so the audit trail is strictly earlier than the reply it authorizes."""

    hypervisor = ClassifierHypervisor()
    request = HypervisorRequest(
        "read filesystem file path descriptor",
        "/home/file",
        {"path": "/home/file"},
        frozenset({"read"}),
        frozenset({"read"}),
    )
    observed: list[tuple[str, ...]] = []

    def handler() -> bytes:
        """Mathematics: project the journal prefix visible from inside the handler invocation."""

        observed.append(tuple(record.kind for record in hypervisor.journal.records()))
        return b"ok"

    decision, result = hypervisor.dispatch(request, {HypervisorDomain.FILESYSTEM: handler})
    assert decision.action is HypervisorAction.ALLOW
    assert result == b"ok"
    assert observed == [("hypervisor.decision",)]
    assert hypervisor.journal.records()[-1].kind == "hypervisor.decision"
    assert hypervisor.journal.verify()


def test_headless_dispatch_derives_grants_from_kernel_capabilities() -> None:
    """Mathematics: verify `G` comes from kernel capabilities and `G ⊉ R ⇒ DENY` before handler execution."""

    from mailcpu import Capability

    operating_system = HeadlessOS()
    operating_system.environment.kernel.fs.mkdir("/safe")
    operating_system.environment.kernel.fs.create_file("/safe/data", b"ok")
    limited_pid = operating_system.environment.kernel.spawn(
        "limited",
        capabilities=(Capability("/safe", frozenset({"read"})),),
    )
    calls: list[str] = []
    handlers = {HypervisorDomain.FILESYSTEM: lambda: calls.append("ran") or b"ok"}
    denied, result = operating_system.hypervisor_dispatch(
        limited_pid,
        "read filesystem file path descriptor",
        "/secret/data",
        {"path": "/secret/data"},
        handlers,
        frozenset({"read"}),
    )
    assert denied.action is HypervisorAction.DENY
    assert result is None
    assert calls == []

    allowed, result = operating_system.hypervisor_dispatch(
        limited_pid,
        "read filesystem file path descriptor",
        "/safe/data",
        {"path": "/safe/data"},
        handlers,
        frozenset({"read"}),
    )
    assert allowed.action is HypervisorAction.ALLOW
    assert result == b"ok"
    assert calls == ["ran"]


def test_hypervisor_denies_missing_authority_and_reviews_ambiguity() -> None:
    """Mathematics: verify `missing_rights ≠ ∅ ⇒ DENY` and low-confidence classification ⇒ REVIEW without side effects."""

    hypervisor = ClassifierHypervisor()
    denied = hypervisor.decide(
        HypervisorRequest(
            "read filesystem file path descriptor",
            "/home/file",
            {"path": "/home/file"},
            frozenset({"read", "secret"}),
            frozenset({"read"}),
        )
    )
    reviewed = hypervisor.decide(HypervisorRequest("mystery", "/unknown", {}))
    assert denied.action is HypervisorAction.DENY
    assert reviewed.action is HypervisorAction.REVIEW
    assert hypervisor.journal.verify()


def test_hypervisor_reviews_destructive_request_even_with_rights() -> None:
    """Mathematics: verify `destructive ∧ (p_danger≥τ or c<τ_d) ⇒ REVIEW`."""

    hypervisor = ClassifierHypervisor()
    decision = hypervisor.decide(
        HypervisorRequest(
            "delete filesystem file path descriptor overwrite",
            "/home/file",
            {"path": "/home/file"},
            frozenset({"write"}),
            frozenset({"write"}),
            destructive=True,
        )
    )
    assert decision.action is HypervisorAction.REVIEW
    assert decision.danger_probability >= 0.70


def test_headless_checkpoint_preserves_hypervisor_policy_and_receipts() -> None:
    """Mathematics: verify `restore(snapshot(OS))` preserves policy and the journal prefix exactly."""

    operating_system = HeadlessOS()
    operating_system.hypervisor_decide(HypervisorRequest("mystery", "/unknown", {}))
    snapshot = operating_system.snapshot()
    restored = HeadlessOS.from_snapshot(snapshot)
    assert restored.hypervisor.snapshot() == operating_system.hypervisor.snapshot()
    assert restored.environment.kernel.journal.snapshot() == operating_system.environment.kernel.journal.snapshot()
    assert restored.environment.kernel.journal.verify()


def test_procedural_field_is_deterministic_bounded_and_sparse() -> None:
    """Mathematics: verify `W_F(a)` is repeatable, bounded, and generated without a stored dense tensor."""

    field = ProceduralWeightField(ProceduralModelSpec(seed=1234, feature_buckets=64))
    first = field.weight("choice:domain:filesystem", "path")
    second = field.weight("choice:domain:filesystem", "path")
    vector = field.feature_vector({"operation": "read filesystem", "path": "/tmp/a"})
    assert first == second
    assert 0.75 <= first < 1.25
    assert len(vector) == 64
    assert abs(sum(value * value for value in vector) - 1.0) < 1e-12
    assert not hasattr(field, "weights")


def test_procedural_classifier_round_trips_generator_identity() -> None:
    """Mathematics: verify `f_F(state,q)=f_{decode(encode(F))}(state,q)` for typed decisions."""

    model = ProceduralDecisionModel(ProceduralModelSpec(seed=99, feature_buckets=128, temperature=0.75))
    restored = ProceduralDecisionModel.from_snapshot(model.snapshot())
    question = ChoiceQuestion.from_mapping(
        "choose domain",
        {"filesystem": "file path read", "network": "packet socket", "review": "unknown ambiguous"},
    )
    state = {"operation": "read file path", "resource": "/tmp/x"}
    assert model.evaluate(state, {"domain": question}).to_dict() == restored.evaluate(state, {"domain": question}).to_dict()


def test_headless_hypervisor_uses_procedural_model_by_default() -> None:
    """Mathematics: verify the default OS classifier is the checkpointable procedural field `F`, not a copied external model."""

    operating_system = HeadlessOS()
    assert isinstance(operating_system.hypervisor.classifier, ProceduralDecisionModel)
    assert operating_system.hypervisor.snapshot()["model"]["kind"] == "procedural"


def test_vl_feistel_primitive_is_reversible_and_drives_procedural_addresses() -> None:
    """Mathematics: verify `open(seal(x,τ,s),τ,s)=x` and deterministic byte-stream regeneration."""

    values = (0, 1, 2**32 - 1, 2**64 - 1, 0x1234567890ABCDEF)
    for value in values:
        sealed = feistel_seal(value, 0xB16B00B5CAFE, 17)
        assert feistel_open(sealed, 0xB16B00B5CAFE, 17) == value
    first = bytes(feistel_stream_byte(index, 0xB16B00B5CAFE, 17) for index in range(64))
    second = bytes(feistel_stream_byte(index, 0xB16B00B5CAFE, 17) for index in range(64))
    assert first == second
    assert len(set(first)) > 1


def test_headless_hypervisor_adapters_reach_files_services_and_network() -> None:
    """Mathematics: verify each adapter obeys `ALLOW ⇒ one native subsystem transition` and preserves journal integrity."""

    operating_system = HeadlessOS()
    init_pid = operating_system.environment.init_pid
    operating_system.environment.kernel.fs.create_file("/home/message", b"hello")
    file_decision, data = operating_system.hypervisor_read_file(init_pid, "/home/message")
    assert file_decision.action is HypervisorAction.ALLOW
    assert file_decision.domain is HypervisorDomain.FILESYSTEM
    assert data == b"hello"

    operating_system.install_source("/bin/service.mca", "HALT\n")
    operating_system.services.register(ServiceSpec("demo", "/bin/service.mca"))
    service_decision, service_report = operating_system.hypervisor_start_service(init_pid, "demo")
    assert service_decision.action is HypervisorAction.ALLOW
    assert service_decision.domain is HypervisorDomain.SERVICE
    assert service_report is not None and service_report.state == "runnable"

    packet = bytearray(40)
    packet[0] = 0x45
    packet[2:4] = (40).to_bytes(2, "big")
    packet[9] = 6
    packet[12:16] = bytes((10, 0, 0, 1))
    packet[16:20] = bytes((10, 0, 0, 2))
    packet[20:22] = (4000).to_bytes(2, "big")
    packet[22:24] = (80).to_bytes(2, "big")
    packet[32] = 0x50
    packet[33] = 0x02
    network_decision, events = operating_system.hypervisor_ingest_network(init_pid, 1, bytes(packet))
    assert network_decision.action is HypervisorAction.ALLOW
    assert network_decision.domain is HypervisorDomain.NETWORK
    assert events and events[0].kind == "connection.state"
    assert operating_system.environment.kernel.journal.verify()
