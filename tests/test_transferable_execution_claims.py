from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from mailcpu import (
    ExecutionClaimStatus,
    PortableExecutionClaimBundle,
    RecoveryLineageAuthority,
    RecoveryLineageCoordinator,
    SeedCommitMembership,
    TransferableExecutionClaimError,
    TransferableExecutionClaimStore,
    dataflow_add_operator_spec,
)

H = lambda value: hashlib.sha256(value.encode()).hexdigest()
GENESIS = "0" * 64
PARENT, CHILD, ADDRESS = H("parent"), H("child"), H("address")
CONTRACT, GROUND = dataflow_add_operator_spec().digest, H("ground")
IMPL_B, IMPL_C = H("cpu-b"), H("egpu-c")
RESULT, RECEIPT, FAILURE = H("result"), H("receipt"), H("failure")


def _membership() -> SeedCommitMembership:
    """Mathematics: configure one strict-majority recovery membership for transferable claim generations."""
    return SeedCommitMembership("execution-claim-authority", 1, ("A", "B", "C"), "A", 1, GENESIS)


def _coordinator(path: Path) -> RecoveryLineageCoordinator:
    """Mathematics: bind three independent durable authority journals to one fixed claim-state membership."""
    membership = _membership()
    authorities = {
        member: RecoveryLineageAuthority(membership, member, path / f"{member}.log")
        for member in membership.member_ids
    }
    return RecoveryLineageCoordinator(membership, authorities)


def _store(root: Path):
    """Mathematics: construct the immutable claim state store and its quorum coordinator."""
    coordinator = _coordinator(root / "authorities")
    return TransferableExecutionClaimStore(root / "claims", coordinator), coordinator


def _create(store: TransferableExecutionClaimStore):
    """Mathematics: issue one pure replay-safe ADD child claim tied to exact parent, child, address, contract and Ground."""
    return store.create(
        parent_request_digest=PARENT,
        child_request_digest=CHILD,
        address_digest=ADDRESS,
        operator_spec=dataflow_add_operator_spec(),
        computational_ground_fingerprint=GROUND,
        owner_peer_id="peer-b",
        owner_host_id="logical-cpu-b",
        implementation_fingerprint=IMPL_B,
    )


def test_quorum_claim_round_trip_and_exact_target_admission(tmp_path: Path) -> None:
    """Mathematics: a portable claim is admitted only for its exact workload and current assignment."""
    store, coordinator = _store(tmp_path)
    bundle = _create(store)
    assert bundle.claim.status is ExecutionClaimStatus.ASSIGNED
    assert bundle.claim.current_assignment.epoch == 1
    assert store.high_water == (1, bundle.manifest.digest)
    bundle.verify_for_target(
        coordinator,
        parent_request_digest=PARENT,
        child_request_digest=CHILD,
        address_digest=ADDRESS,
        operator_spec=dataflow_add_operator_spec(),
        computational_ground_fingerprint=GROUND,
        owner_peer_id="peer-b",
        owner_host_id="logical-cpu-b",
        implementation_fingerprint=IMPL_B,
    )
    restored = PortableExecutionClaimBundle.from_dict(bundle.to_dict())
    restored.verify_current(coordinator)
    assert restored.digest == bundle.digest
    assert store.get(bundle.claim.claim_id).digest == bundle.digest
    with pytest.raises(TransferableExecutionClaimError, match="does not authorize"):
        restored.verify_for_target(
            coordinator,
            parent_request_digest=PARENT,
            child_request_digest=CHILD,
            address_digest=ADDRESS,
            operator_spec=dataflow_add_operator_spec(),
            computational_ground_fingerprint=GROUND,
            owner_peer_id="peer-c",
            owner_host_id="logical-egpu-c",
            implementation_fingerprint=IMPL_C,
        )
    with pytest.raises(TransferableExecutionClaimError, match="deterministic pure OperatorSpec"):
        store.create(
            parent_request_digest=PARENT,
            child_request_digest=CHILD,
            address_digest=ADDRESS,
            operator_spec=replace(dataflow_add_operator_spec(), deterministic=False),
            computational_ground_fingerprint=GROUND,
            owner_peer_id="peer-b",
            owner_host_id="logical-cpu-b",
            implementation_fingerprint=IMPL_B,
        )
    with pytest.raises(TransferableExecutionClaimError, match="only pure replay-safe"):
        store.create(
            parent_request_digest=PARENT,
            child_request_digest=CHILD,
            address_digest=ADDRESS,
            operator_spec=dataflow_add_operator_spec(),
            computational_ground_fingerprint=GROUND,
            owner_peer_id="peer-b",
            owner_host_id="logical-cpu-b",
            implementation_fingerprint=IMPL_B,
            replay_policy="external-side-effect",
        )


def test_quorum_reassignment_fences_old_epoch_and_new_host_completes(tmp_path: Path) -> None:
    """Mathematics: a quorum transition A_e→A_(e+1) revokes stale result-acceptance authority."""
    store, coordinator = _store(tmp_path)
    original = _create(store)
    claim_id = original.claim.claim_id
    moved = store.reassign(
        claim_id,
        expected_epoch=1,
        owner_peer_id="peer-c",
        owner_host_id="logical-egpu-c",
        implementation_fingerprint=IMPL_C,
        failure_evidence_digest=FAILURE,
    )
    assert moved.claim.claim_id == claim_id
    assert moved.claim.current_assignment.epoch == 2
    assert moved.claim.assignments[0] == original.claim.assignments[0]
    assert moved.claim.assignments[1].failure_evidence_digest == FAILURE
    assert store.reassign(
        claim_id,
        expected_epoch=1,
        owner_peer_id="peer-c",
        owner_host_id="logical-egpu-c",
        implementation_fingerprint=IMPL_C,
        failure_evidence_digest=FAILURE,
    ).digest == moved.digest
    with pytest.raises(TransferableExecutionClaimError, match="not current"):
        original.verify_current(coordinator)
    with pytest.raises(TransferableExecutionClaimError, match="stale assignment epoch"):
        store.complete(
            claim_id,
            expected_epoch=1,
            owner_peer_id="peer-b",
            owner_host_id="logical-cpu-b",
            implementation_fingerprint=IMPL_B,
            result_digest=RESULT,
            child_receipt_digest=RECEIPT,
        )
    completed = store.complete(
        claim_id,
        expected_epoch=2,
        owner_peer_id="peer-c",
        owner_host_id="logical-egpu-c",
        implementation_fingerprint=IMPL_C,
        result_digest=RESULT,
        child_receipt_digest=RECEIPT,
    )
    assert completed.claim.status is ExecutionClaimStatus.COMPLETED
    assert completed.claim.completion_generation == 3
    assert completed.claim.result_digest == RESULT
    assert completed.claim.child_receipt_digest == RECEIPT
    assert store.complete(
        claim_id,
        expected_epoch=2,
        owner_peer_id="peer-c",
        owner_host_id="logical-egpu-c",
        implementation_fingerprint=IMPL_C,
        result_digest=RESULT,
        child_receipt_digest=RECEIPT,
    ).digest == completed.digest
    with pytest.raises(TransferableExecutionClaimError, match="already completed"):
        store.complete(
            claim_id,
            expected_epoch=2,
            owner_peer_id="peer-c",
            owner_host_id="logical-egpu-c",
            implementation_fingerprint=IMPL_C,
            result_digest=H("other-result"),
            child_receipt_digest=RECEIPT,
        )
    with pytest.raises(TransferableExecutionClaimError, match="cannot be reassigned"):
        store.reassign(
            claim_id,
            expected_epoch=2,
            owner_peer_id="peer-b",
            owner_host_id="logical-cpu-b",
            implementation_fingerprint=IMPL_B,
            failure_evidence_digest=FAILURE,
        )


def test_claim_tampering_and_stale_semantic_identity_are_refused(tmp_path: Path) -> None:
    """Mathematics: claim data is admitted only when nested state bytes, request identities and quorum root remain exact."""
    store, coordinator = _store(tmp_path)
    bundle = _create(store)
    tampered = bundle.to_dict()
    tampered["state_snapshot"]["claims"][0]["assignments"][0]["owner_host_id"] = "attacker-host"
    with pytest.raises(TransferableExecutionClaimError, match="digest|state bytes|bundle"):
        PortableExecutionClaimBundle.from_dict(tampered)
    bundle.state_snapshot["claims"][0]["assignments"][0]["owner_host_id"] = "mutated-after-construction"
    with pytest.raises(TransferableExecutionClaimError, match="changed after construction"):
        bundle.verify_current(coordinator)
    with pytest.raises(TransferableExecutionClaimError, match="does not authorize"):
        bundle.verify_for_target(
            coordinator,
            parent_request_digest=PARENT,
            child_request_digest=H("different-child"),
            address_digest=ADDRESS,
            operator_spec=dataflow_add_operator_spec(),
            computational_ground_fingerprint=GROUND,
            owner_peer_id="peer-b",
            owner_host_id="logical-cpu-b",
            implementation_fingerprint=IMPL_B,
        )


def test_quorum_claim_state_survives_coordinator_restart(tmp_path: Path) -> None:
    """Mathematics: authority journal replay plus immutable generation bytes restore the exact latest portable assignment."""
    store, _coordinator_instance = _store(tmp_path)
    created = _create(store)
    moved = store.reassign(
        created.claim.claim_id,
        expected_epoch=1,
        owner_peer_id="peer-c",
        owner_host_id="logical-egpu-c",
        implementation_fingerprint=IMPL_C,
        failure_evidence_digest=FAILURE,
    )
    del store
    reopened = _coordinator(tmp_path / "authorities")
    restored = TransferableExecutionClaimStore(tmp_path / "claims", reopened).get(created.claim.claim_id)
    restored.verify_for_target(
        reopened,
        parent_request_digest=PARENT,
        child_request_digest=CHILD,
        address_digest=ADDRESS,
        operator_id="mailcpu.add",
        operator_contract_digest=CONTRACT,
        computational_ground_fingerprint=GROUND,
        owner_peer_id="peer-c",
        owner_host_id="logical-egpu-c",
        implementation_fingerprint=IMPL_C,
    )
    assert restored.digest == moved.digest
    assert restored.claim.assignments == moved.claim.assignments


def test_claim_store_refuses_mutated_persisted_generation(tmp_path: Path) -> None:
    """Mathematics: a claim artifact cannot be modified after its state digest and quorum manifest are anchored."""
    store, _coordinator_instance = _store(tmp_path)
    bundle = _create(store)
    state_path = (
        tmp_path / "claims" / f"generation-{bundle.manifest.generation:020d}" / "claims.json"
    )
    state_path.write_bytes(state_path.read_bytes() + b" ")
    with pytest.raises(TransferableExecutionClaimError, match="high-water|quorum|canonical"):
        store.get(bundle.claim.claim_id)


def test_durable_unquorummed_claim_generation_resumes_exact_same_proposal(tmp_path: Path) -> None:
    """Mathematics: after an incomplete prepare majority, recovery seals the exact fsynced proposal rather than substituting a new value."""
    store, coordinator = _store(tmp_path)
    authority_b = coordinator.authorities["B"]
    authority_c = coordinator.authorities["C"]
    original_b = authority_b.prepare
    original_c = authority_c.prepare

    def unavailable(_proposal):
        """Mathematics: model one authority outage before its durable prepare vote."""
        from mailcpu import RecoveryLineageError

        raise RecoveryLineageError("simulated authority unavailable")

    authority_b.prepare = unavailable
    authority_c.prepare = unavailable
    with pytest.raises(TransferableExecutionClaimError, match="lacks a quorum"):
        _create(store)

    # Generation bytes and A's exact prepare vote survive. Restoring the
    # participants lets the store complete that same proposal at the same slot.
    authority_b.prepare = original_b
    authority_c.prepare = original_c
    assert store.resume_pending() is True
    recovered = _create(store)
    assert recovered.manifest.generation == 1
    assert recovered.claim.current_assignment.epoch == 1
    assert store.resume_pending() is False
