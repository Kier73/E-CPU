from __future__ import annotations

import pytest

from mailcpu.vl_procedural_primitives import feistel_open, feistel_seal, feistel_stream_byte
from mailcpu.image import ImageFile
from mailcpu import (
    Capability,
    ChoiceAnswer,
    ChoiceQuestion,
    ClassifierHypervisor,
    HeadlessOS,
    HypervisorArbitrationEvent,
    HypervisorAction,
    HypervisorError,
    HypervisorDomain,
    HypervisorIntentRevisionWitness,
    HypervisorRequest,
    HypervisorPolicy,
    HypervisorRevisionProposal,
    HypervisorRevisionWitness,
    IntentExample,
    IntentPrototypeModel,
    ExecutableImage,
    FsError,
    ImageRegistry,
    Instruction,
    LexicalDecisionModel,
    NoulAnswer,
    NoulQuestion,
    Op,
    Program,
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


def test_hypervisor_rsi_loop_reuses_exact_retransmission_receipt() -> None:
    """Mathematics: one identity `I` admits one decision `D(I)`, while exact retransmission returns `H(D(I))` without another policy evaluation."""

    operating_system = HeadlessOS()
    request = HypervisorRequest(
        "read filesystem file path descriptor",
        "/home/file",
        {"path": "/home/file"},
        frozenset({"read"}),
        frozenset({"read"}),
    )
    event = HypervisorArbitrationEvent("node-a", "control", 1, 7, request)

    first = operating_system.hypervisor_arbitrate(event)
    duplicate = operating_system.hypervisor_arbitrate(event)

    assert first.replayed is False
    assert first.decision is not None and first.decision.action is HypervisorAction.ALLOW
    assert duplicate.replayed is True
    assert duplicate.decision is None
    assert duplicate.decision_receipt == first.decision_receipt
    assert len([record for record in operating_system.environment.kernel.journal.records() if record.kind == "hypervisor.decision"]) == 1
    assert operating_system.environment.kernel.journal.verify()


def test_hypervisor_rsi_loop_refuses_conflicting_retransmission() -> None:
    """Mathematics: fixed identity `I` cannot transition from fingerprint `f` to `f'≠f`; conflict is refused before a second decision."""

    operating_system = HeadlessOS()
    original = HypervisorArbitrationEvent(
        "node-a",
        "control",
        1,
        7,
        HypervisorRequest(
            "read filesystem file path descriptor",
            "/home/file",
            {"path": "/home/file"},
            frozenset({"read"}),
            frozenset({"read"}),
        ),
    )
    conflicting = HypervisorArbitrationEvent(
        "node-a",
        "control",
        1,
        7,
        HypervisorRequest(
            "read filesystem file path descriptor",
            "/home/other",
            {"path": "/home/other"},
            frozenset({"read"}),
            frozenset({"read"}),
        ),
    )
    operating_system.hypervisor_arbitrate(original)

    with pytest.raises(HypervisorError, match="conflicting arbitration retransmission"):
        operating_system.hypervisor_arbitrate(conflicting)

    assert len([record for record in operating_system.environment.kernel.journal.records() if record.kind == "hypervisor.decision"]) == 1
    assert operating_system.environment.kernel.journal.verify()


def test_hypervisor_rsi_loop_ledger_survives_checkpoint_restore() -> None:
    """Mathematics: `restore(snapshot(L))` preserves `I↦(f,H)`, so a post-restore duplicate cannot re-enter policy evaluation."""

    operating_system = HeadlessOS()
    event = HypervisorArbitrationEvent(
        "node-a",
        "control",
        1,
        7,
        HypervisorRequest(
            "read filesystem file path descriptor",
            "/home/file",
            {"path": "/home/file"},
            frozenset({"read"}),
            frozenset({"read"}),
        ),
    )
    first = operating_system.hypervisor_arbitrate(event)
    restored = HeadlessOS.from_snapshot(operating_system.snapshot())
    duplicate = restored.hypervisor_arbitrate(event)

    assert duplicate.replayed is True
    assert duplicate.decision_receipt == first.decision_receipt
    assert restored.hypervisor_arbitration.snapshot() == operating_system.hypervisor_arbitration.snapshot()
    assert len([record for record in restored.environment.kernel.journal.records() if record.kind == "hypervisor.decision"]) == 1
    assert restored.environment.kernel.journal.verify()


def test_hypervisor_effect_ledger_replays_process_launch_after_duplicate_and_restore() -> None:
    """Mathematics: `I↦(f,e)` executes one child transition, while equal retransmissions preserve `|P|` and `e`."""

    operating_system = HeadlessOS()
    init_pid = operating_system.environment.init_pid
    operating_system.install_source("/bin/child.mca", "HALT\n")
    before = set(operating_system.environment.kernel.processes)
    calls = {"count": 0}

    def launch_handler() -> int:
        """Mathematics: execute one native process transition `P↦P∪{child}` and return its identity."""

        calls["count"] += 1
        return operating_system.launch_file("/bin/child.mca", parent_pid=init_pid, loader_pid=init_pid)

    def encode_pid(child_pid: int) -> dict[str, int]:
        """Mathematics: encode process identity `p` as replayable effect `{"pid":p}`."""

        return {"pid": int(child_pid)}

    first = operating_system.hypervisor_dispatch_event(
        init_pid,
        "node-a",
        "process",
        1,
        7,
        "spawn process executable file child image",
        "/bin/child.mca",
        {"path": "/bin/child.mca"},
        {HypervisorDomain.PROCESS: launch_handler},
        frozenset({"execute"}),
        effect_encoder=encode_pid,
    )
    after_first = set(operating_system.environment.kernel.processes)
    duplicate = operating_system.hypervisor_dispatch_event(
        init_pid,
        "node-a",
        "process",
        1,
        7,
        "spawn process executable file child image",
        "/bin/child.mca",
        {"path": "/bin/child.mca"},
        {HypervisorDomain.PROCESS: launch_handler},
        frozenset({"execute"}),
        effect_encoder=encode_pid,
    )

    assert first.executed is True
    assert first.replayed is False
    assert duplicate.replayed is True
    assert duplicate.effect == first.effect
    assert calls["count"] == 1
    assert after_first == before | {first.effect["pid"]}
    assert set(operating_system.environment.kernel.processes) == after_first

    restored = HeadlessOS.from_snapshot(operating_system.snapshot())
    restored_calls = {"count": 0}

    def restored_handler() -> int:
        """Mathematics: this handler would add a child, so its zero invocation count witnesses replay without mutation."""

        restored_calls["count"] += 1
        return restored.launch_file("/bin/child.mca", parent_pid=init_pid, loader_pid=init_pid)

    restored_duplicate = restored.hypervisor_dispatch_event(
        init_pid,
        "node-a",
        "process",
        1,
        7,
        "spawn process executable file child image",
        "/bin/child.mca",
        {"path": "/bin/child.mca"},
        {HypervisorDomain.PROCESS: restored_handler},
        frozenset({"execute"}),
        effect_encoder=encode_pid,
    )
    assert restored_duplicate.replayed is True
    assert restored_duplicate.effect == first.effect
    assert restored_calls["count"] == 0
    assert set(restored.environment.kernel.processes) == after_first
    assert restored.environment.kernel.journal.verify()

    conflicting = HypervisorArbitrationEvent(
        "node-a",
        "process",
        1,
        7,
        HypervisorRequest(
            "spawn process executable file child image",
            "/bin/other.mca",
            {"path": "/bin/other.mca"},
            frozenset({"execute"}),
            frozenset({"execute"}),
        ),
    )
    with pytest.raises(HypervisorError, match="conflicting execution retransmission"):
        restored.hypervisor_arbitration.execute(conflicting, {HypervisorDomain.PROCESS: restored_handler})


def test_hypervisor_effect_ledger_records_denial_without_invoking_handler() -> None:
    """Mathematics: `action≠ALLOW⇒effect=∅∧Δstate=0`, and retransmission returns that refusal without handler invocation."""

    operating_system = HeadlessOS()
    init_pid = operating_system.environment.init_pid
    limited_pid = operating_system.environment.kernel.spawn(
        "limited-process-launcher",
        capabilities=(Capability("/safe", frozenset({"read"})),),
        parent_pid=init_pid,
    )
    calls = {"count": 0}

    def forbidden_handler() -> dict[str, str]:
        """Mathematics: any invocation would violate the denial witness `ΔP=0`, so the counter exposes accidental dispatch."""

        calls["count"] += 1
        return {"unexpected": "mutation"}

    first = operating_system.hypervisor_dispatch_event(
        limited_pid,
        "node-a",
        "process",
        2,
        8,
        "spawn process executable file child image",
        "/bin/child.mca",
        {"path": "/bin/child.mca"},
        {HypervisorDomain.PROCESS: forbidden_handler},
        frozenset({"execute"}),
    )
    duplicate = operating_system.hypervisor_dispatch_event(
        limited_pid,
        "node-a",
        "process",
        2,
        8,
        "spawn process executable file child image",
        "/bin/child.mca",
        {"path": "/bin/child.mca"},
        {HypervisorDomain.PROCESS: forbidden_handler},
        frozenset({"execute"}),
    )

    assert first.executed is False
    assert first.effect is None
    assert duplicate.replayed is True
    assert duplicate.effect is None
    assert calls["count"] == 0
    assert operating_system.environment.kernel.journal.verify()


def test_hypervisor_effect_ledger_surfaces_handler_failure_without_fake_completion() -> None:
    """Mathematics: `handler↦⊥` records failure and leaves `I∉dom(E)`, so no false completion can be replayed."""

    operating_system = HeadlessOS()
    init_pid = operating_system.environment.init_pid

    def failing_handler() -> dict[str, str]:
        """Mathematics: model an uncommitted native transition by returning no effect and raising `⊥`."""

        raise RuntimeError("native operation failed")

    with pytest.raises(RuntimeError, match="native operation failed"):
        operating_system.hypervisor_dispatch_event(
            init_pid,
            "node-a",
            "process",
            3,
            9,
            "spawn process executable file child image",
            "/bin/child.mca",
            {"path": "/bin/child.mca"},
            {HypervisorDomain.PROCESS: failing_handler},
            frozenset({"execute"}),
        )

    assert operating_system.hypervisor_arbitration.snapshot()["executions"] == []
    assert any(record.kind == "hypervisor.execution.failure" for record in operating_system.environment.kernel.journal.records())
    assert operating_system.environment.kernel.journal.verify()


def test_hypervisor_revision_gate_admits_witnessed_candidate_and_restores() -> None:
    """Mathematics: candidate promotion satisfies `∀w∈W:π(H_candidate(w))=π(H_current(w))` and preserves revision identity across restore."""

    operating_system = HeadlessOS()
    requests = (
        HypervisorRequest(
            "read filesystem file path descriptor",
            "/home/file",
            {"path": "/home/file"},
            frozenset({"read"}),
            frozenset({"read"}),
        ),
        HypervisorRequest(
            "read filesystem file path descriptor",
            "/secret/file",
            {"path": "/secret/file"},
            frozenset({"read", "secret"}),
            frozenset({"read"}),
        ),
        HypervisorRequest(
            "delete filesystem file path descriptor overwrite",
            "/home/file",
            {"path": "/home/file"},
            frozenset({"write"}),
            frozenset({"write"}),
            destructive=True,
        ),
    )
    witnesses = tuple(
        HypervisorRevisionWitness.from_decision(request, operating_system.hypervisor.decide(request))
        for request in requests
    )
    candidate = ProceduralDecisionModel.from_snapshot(operating_system.hypervisor.classifier.snapshot())

    result = operating_system.hypervisor.admit_classifier_revision(candidate, witnesses)
    restored = HeadlessOS.from_snapshot(operating_system.snapshot())

    assert result.accepted is True
    assert result.revision == 1
    assert operating_system.hypervisor.snapshot()["revision"] == 1
    assert restored.hypervisor.snapshot() == operating_system.hypervisor.snapshot()
    assert any(record.kind == "hypervisor.revision.admit" for record in operating_system.environment.kernel.journal.records())
    assert operating_system.environment.kernel.journal.verify()


def test_hypervisor_revision_gate_refuses_mismatch_without_replacing_active_model() -> None:
    """Mathematics: `∃w:π(H_candidate(w))≠w.expected ⇒ H_after.classifier=H_before.classifier` and revision is unchanged."""

    operating_system = HeadlessOS()
    request = HypervisorRequest(
        "read filesystem file path descriptor",
        "/home/file",
        {"path": "/home/file"},
        frozenset({"read"}),
        frozenset({"read"}),
    )
    witness = HypervisorRevisionWitness.from_decision(request, operating_system.hypervisor.decide(request))
    before = operating_system.hypervisor.snapshot()
    result = operating_system.hypervisor.admit_classifier_revision(LexicalDecisionModel(), (witness,))

    assert result.accepted is False
    assert result.revision == 0
    assert result.mismatch_index == 0
    assert operating_system.hypervisor.snapshot() == before
    assert any(record.kind == "hypervisor.revision.refuse" for record in operating_system.environment.kernel.journal.records())
    assert operating_system.environment.kernel.journal.verify()


def test_hypervisor_arbitration_binds_revision_across_replay_and_restore() -> None:
    """Mathematics: `I↦(f,receipt,r)` remains fixed on replay even after the active revision advances to `r+1`."""

    operating_system = HeadlessOS()
    request = HypervisorRequest(
        "read filesystem file path descriptor",
        "/home/file",
        {"path": "/home/file"},
        frozenset({"read"}),
        frozenset({"read"}),
    )
    first_event = HypervisorArbitrationEvent("node-a", "control", 1, 7, request)
    first = operating_system.hypervisor_arbitrate(first_event)
    assert first.decision is not None
    assert first.decision_revision == 0
    assert first.decision.revision == 0

    candidate = ProceduralDecisionModel.from_snapshot(operating_system.hypervisor.classifier.snapshot())
    witness = HypervisorRevisionWitness.from_decision(request, first.decision)
    admission = operating_system.hypervisor.admit_classifier_revision(candidate, (witness,))
    assert admission.accepted is True
    assert admission.revision == 1

    second_event = HypervisorArbitrationEvent("node-a", "control", 2, 8, request)
    second = operating_system.hypervisor_arbitrate(second_event)
    assert second.decision is not None
    assert second.decision_revision == 1
    assert second.decision.revision == 1
    assert second.decision.to_dict()["revision"] == 1

    old_replay = operating_system.hypervisor_arbitrate(first_event)
    assert old_replay.replayed is True
    assert old_replay.decision is None
    assert old_replay.decision_receipt == first.decision_receipt
    assert old_replay.decision_revision == 0
    assert len([record for record in operating_system.environment.kernel.journal.records() if record.kind == "hypervisor.decision"]) == 2

    snapshot = operating_system.snapshot()
    restored = HeadlessOS.from_snapshot(snapshot)
    assert restored.hypervisor_arbitration.snapshot() == operating_system.hypervisor_arbitration.snapshot()
    assert restored.hypervisor_arbitrate(first_event).decision_revision == 0
    assert restored.hypervisor_arbitrate(second_event).decision_revision == 1
    assert restored.environment.kernel.journal.verify()


def test_hypervisor_revision_proposal_is_idempotent_and_checkpointable() -> None:
    """Mathematics: `P` admits once, exact retransmission returns the stored result, and `restore(L_r)` preserves admission identity."""

    operating_system = HeadlessOS()
    request = HypervisorRequest(
        "read filesystem file path descriptor",
        "/home/file",
        {"path": "/home/file"},
        frozenset({"read"}),
        frozenset({"read"}),
    )
    decision = operating_system.hypervisor_decide(request)
    assert decision.revision == 0
    candidate = ProceduralDecisionModel.from_snapshot(operating_system.hypervisor.classifier.snapshot())
    proposal = HypervisorRevisionProposal.from_candidate(
        "node-a",
        "revisions",
        1,
        11,
        candidate,
        (HypervisorRevisionWitness.from_decision(request, decision),),
    )

    first = operating_system.hypervisor_propose_revision(proposal)
    duplicate = operating_system.hypervisor_propose_revision(proposal)
    assert first.replayed is False
    assert first.admission.accepted is True
    assert first.admission.revision == 1
    assert duplicate.replayed is True
    assert duplicate.admission == first.admission
    assert operating_system.hypervisor.snapshot()["revision"] == 1
    assert len([record for record in operating_system.environment.kernel.journal.records() if record.kind == "hypervisor.revision.admit"]) == 1

    restored = HeadlessOS.from_snapshot(operating_system.snapshot())
    restored_duplicate = restored.hypervisor_propose_revision(proposal)
    assert restored_duplicate.replayed is True
    assert restored_duplicate.admission == first.admission
    assert restored.hypervisor.snapshot() == operating_system.hypervisor.snapshot()
    assert restored.environment.kernel.journal.verify()


def test_hypervisor_revision_proposal_refuses_conflict_and_bad_model_without_mutation() -> None:
    """Mathematics: fixed proposal identity `I` is single-valued; invalid reconstruction yields refusal and never changes `H.revision`."""

    operating_system = HeadlessOS()
    request = HypervisorRequest(
        "read filesystem file path descriptor",
        "/home/file",
        {"path": "/home/file"},
        frozenset({"read"}),
        frozenset({"read"}),
    )
    decision = operating_system.hypervisor_decide(request)
    candidate = ProceduralDecisionModel.from_snapshot(operating_system.hypervisor.classifier.snapshot())
    proposal = HypervisorRevisionProposal.from_candidate(
        "node-a",
        "revisions",
        1,
        11,
        candidate,
        (HypervisorRevisionWitness.from_decision(request, decision),),
    )
    assert operating_system.hypervisor_propose_revision(proposal).admission.accepted is True
    conflicting_snapshot = dict(proposal.candidate_snapshot)
    conflicting_snapshot["temperature"] = 2.0
    conflicting = HypervisorRevisionProposal(
        proposal.source,
        proposal.channel,
        proposal.sequence,
        proposal.logical_time,
        conflicting_snapshot,
        proposal.witnesses,
    )
    with pytest.raises(HypervisorError, match="conflicting revision proposal"):
        operating_system.hypervisor_propose_revision(conflicting)
    invalid = HypervisorRevisionProposal(
        "node-a",
        "revisions",
        2,
        12,
        {"kind": "unknown", "model": "unadmitted"},
        proposal.witnesses,
    )
    refused = operating_system.hypervisor_propose_revision(invalid)
    refused_duplicate = operating_system.hypervisor_propose_revision(invalid)
    assert refused.admission.accepted is False
    assert refused.admission.error is not None
    assert refused_duplicate.replayed is True
    assert refused_duplicate.admission == refused.admission
    assert operating_system.hypervisor.snapshot()["revision"] == 1
    assert operating_system.environment.kernel.journal.verify()


def test_hypervisor_intent_revision_is_typed_witnessed_and_checkpointable() -> None:
    """Mathematics: `M'` admits iff `M'(x)=w.expected` and `rank(a')≤rank(a)` for every held-out witness, then replays exactly."""

    operating_system = HeadlessOS()
    candidate = IntentPrototypeModel.fit(
        (
            IntentExample("network", {"operation": "receive network packet socket", "resource": "/network/remote"}),
            IntentExample("filesystem", {"operation": "read filesystem file", "resource": "/srv/data"}),
            IntentExample("service", {"operation": "restart service supervisor", "resource": "/service/worker"}),
        )
    )
    requests = (
        HypervisorRequest("receive network packet socket", "/network/remote", {"transport": "tcp"}),
        HypervisorRequest("read filesystem file", "/srv/data", {"path": "/srv/data"}),
        HypervisorRequest("restart service supervisor", "/service/worker", {"service": "worker"}),
    )
    witnesses = tuple(
        HypervisorIntentRevisionWitness.from_prediction(
            request,
            candidate.predict(request.state()),
            operating_system.hypervisor_decide(request),
        )
        for request in requests
    )
    classifier_before = operating_system.hypervisor.classifier.snapshot()
    proposal = HypervisorRevisionProposal.from_candidate(
        "node-a",
        "intent-training",
        1,
        19,
        candidate,
        witnesses,
        target="intent",
    )

    first = operating_system.hypervisor_propose_revision(proposal)
    assert first.admission.accepted is True
    assert first.admission.target == "intent"
    assert first.admission.revision == 1
    assert operating_system.hypervisor.classifier.snapshot() == classifier_before
    assert operating_system.hypervisor.intent_model.snapshot() == candidate.snapshot()

    restored = HeadlessOS.from_snapshot(operating_system.snapshot())
    duplicate = restored.hypervisor_propose_revision(proposal)
    assert duplicate.replayed is True
    assert duplicate.target == "intent"
    assert duplicate.admission == first.admission
    assert restored.hypervisor.snapshot() == operating_system.hypervisor.snapshot()
    assert restored.environment.kernel.journal.verify()


def test_hypervisor_intent_revision_refuses_stale_baseline_without_mutation() -> None:
    """Mathematics: `baseline(w)≠π(H_current,w)` implies refusal and preserves `(classifier,intent,revision)` exactly."""

    operating_system = HeadlessOS()
    candidate = IntentPrototypeModel.default()
    request = HypervisorRequest("read filesystem file", "/srv/data", {"path": "/srv/data"})
    prediction = candidate.predict(request.state())
    witness = HypervisorIntentRevisionWitness(
        request,
        prediction.to_dict(),
        HypervisorAction.DENY,
    )
    proposal = HypervisorRevisionProposal.from_candidate(
        "node-a",
        "intent-training",
        1,
        20,
        candidate,
        (witness,),
        target="intent",
    )
    before = operating_system.hypervisor.snapshot()

    result = operating_system.hypervisor_propose_revision(proposal)
    assert result.admission.accepted is False
    assert result.admission.target == "intent"
    assert "baseline" in (result.admission.error or "")
    assert operating_system.hypervisor.snapshot() == before
    assert operating_system.environment.kernel.journal.verify()


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


def test_headless_hypervisor_process_adapter_gates_launch_by_execute_capability() -> None:
    """Mathematics: `ALLOW∧execute⇒|Δprocesses|=1`, while `¬execute⇒DENY∧|Δprocesses|=0`."""

    operating_system = HeadlessOS()
    init_pid = operating_system.environment.init_pid
    operating_system.install_source("/bin/child.mca", "HALT\n")
    before = set(operating_system.environment.kernel.processes)
    allowed, child_pid = operating_system.hypervisor_launch_file(init_pid, "/bin/child.mca")
    assert allowed.action is HypervisorAction.ALLOW
    assert allowed.domain is HypervisorDomain.PROCESS
    assert child_pid is not None
    assert set(operating_system.environment.kernel.processes) == before | {child_pid}

    limited_pid = operating_system.environment.kernel.spawn(
        "limited-process-launcher",
        capabilities=(Capability("/safe", frozenset({"read"})),),
        parent_pid=init_pid,
    )
    denied_before = set(operating_system.environment.kernel.processes)
    denied, result = operating_system.hypervisor_launch_file(limited_pid, "/bin/child.mca")
    assert denied.action is HypervisorAction.DENY
    assert result is None
    assert set(operating_system.environment.kernel.processes) == denied_before
    assert operating_system.environment.kernel.journal.verify()


def test_headless_hypervisor_package_adapter_gates_verified_installation(tmp_path) -> None:
    """Mathematics: `REVIEW∨DENY⇒ΔF=0`, while explicit `ALLOW∧write⇒F_after=install(fetch_verified(h),F_before)` exactly once."""

    registry = ImageRegistry(tmp_path / "registry")
    image = ExecutableImage(
        "demo-package",
        Program((Instruction(Op.HALT, ()),)),
        files=(ImageFile("/opt/demo/data", b"package-bytes"),),
    )
    digest = registry.publish(image).digest

    reviewed_os = HeadlessOS()
    reviewed_decision, reviewed_result = reviewed_os.hypervisor_install_package(
        reviewed_os.environment.init_pid,
        registry,
        digest,
    )
    assert reviewed_decision.action is HypervisorAction.REVIEW
    assert reviewed_decision.domain is HypervisorDomain.PACKAGE
    assert reviewed_result is None
    with pytest.raises(FsError):
        reviewed_os.environment.kernel.fs.stat("/opt/demo/data")

    admitted_os = HeadlessOS()
    admitted_os.hypervisor.policy = HypervisorPolicy(
        review_confidence=0.0,
        automatic_confidence=0.0,
        destructive_confidence=0.0,
        danger_review_probability=1.0,
    )
    admitted_decision, installed = admitted_os.hypervisor_install_package(
        admitted_os.environment.init_pid,
        registry,
        digest,
    )
    assert admitted_decision.action is HypervisorAction.ALLOW
    assert admitted_decision.domain is HypervisorDomain.PACKAGE
    assert installed is not None
    assert admitted_os.environment.kernel.fs.read_file("/opt/demo/data") == b"package-bytes"

    denied_os = HeadlessOS()
    denied_os.hypervisor.policy = admitted_os.hypervisor.policy
    denied_pid = denied_os.environment.kernel.spawn(
        "limited-package-installer",
        capabilities=(Capability("/safe", frozenset({"read"})),),
        parent_pid=denied_os.environment.init_pid,
    )
    denied_decision, denied_result = denied_os.hypervisor_install_package(denied_pid, registry, digest)
    assert denied_decision.action is HypervisorAction.DENY
    assert denied_result is None
    with pytest.raises(FsError):
        denied_os.environment.kernel.fs.stat("/opt/demo/data")
    assert denied_os.environment.kernel.journal.verify()
