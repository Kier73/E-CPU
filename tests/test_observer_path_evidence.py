"""Observer-host / carrier path invariants using actual native E-CPU class contracts.

The CI suite runs these against the full E-CPU package; a local API-compatible
stub is used only for focused source-level regression in this environment.
"""
from dataclasses import replace
import pytest

from mailcpu.observer_path_evidence import (
    ObserverPathStage, ObserverPathError, VerifiedObserverPath,
    verify_observer_path, check_observer_path_receipt,
)
from mailcpu.observer_orbit import ObserverContract, ObserverReceipt
from mailcpu.semantic_translation import RepresentationRef, ObservationContract, canonical_value_digest
from mailcpu.substrate_bootstrap import ChannelObservation


def _f():
    before = RepresentationRef.from_payload("test.frame", 1, {"seq": 1, "data": "abc"})
    after = RepresentationRef.from_payload("test.frame", 1, {"seq": 2, "data": "ABC"})
    ground = RepresentationRef.from_payload("test.computational-ground", 1, {"rule": "upper"})
    context = canonical_value_digest({"session": "alpha", "revision": 1})
    obsdef = ObservationContract.from_definition("test.observe", 1, {"exact": True})
    carried1 = ChannelObservation("edge-1", "origin", "observer", (before.type_id,), 2, 0, 100, "a"*64, 128)
    carried2 = ChannelObservation("edge-2", "observer", "worker", (before.type_id,), 2, 0, 100, "b"*64, 128)
    carried3 = ChannelObservation("edge-3", "worker", "verifier", (after.type_id,), 2, 0, 100, "c"*64, 128)
    c1 = ObserverContract("observer", 1, before, ground, obsdef, context)
    r1 = ObserverReceipt.issue(c1, operation_id="observe-frame", input_digest=before.content_digest,
                               projection_value={"seen": before.content_digest},
                               subject_state_before_digest=before.content_digest,
                               subject_state_after_digest=before.content_digest)
    c2 = ObserverContract("worker", 1, before, ground, obsdef, context)
    r2 = ObserverReceipt.issue(c2, operation_id="transform-frame", input_digest=before.content_digest,
                               projection_value={"transformed": True},
                               subject_state_before_digest=before.content_digest,
                               subject_state_after_digest=after.content_digest)
    c3 = ObserverContract("verifier", 1, after, ground, obsdef, context)
    r3 = ObserverReceipt.issue(c3, operation_id="verify-frame", input_digest=after.content_digest,
                               projection_value={"valid": True},
                               subject_state_before_digest=after.content_digest,
                               subject_state_after_digest=after.content_digest)
    hops = (
        ObserverPathStage("carrier", "origin", "observer", before, before, channel=carried1, payload_bytes=40),
        ObserverPathStage("observe", "observer", "observer", before, before, contract=c1, receipt=r1),
        ObserverPathStage("carrier", "observer", "worker", before, before, channel=carried2, payload_bytes=40),
        ObserverPathStage("transform", "worker", "worker", before, after, contract=c2, receipt=r2),
        ObserverPathStage("carrier", "worker", "verifier", after, after, channel=carried3, payload_bytes=40),
        ObserverPathStage("observe", "verifier", "verifier", after, after, contract=c3, receipt=r3),
    )
    return hops, ground, context


def _accept(hops=None, *, ground=None, context=None, now=22, verify_carrier=lambda _: True,
            verify_observer=lambda _: True, max_stages=64):
    orig, g, c = _f()
    return verify_observer_path(orig if hops is None else hops,
                                ground=g if ground is None else ground,
                                context_digest=c if context is None else context,
                                receiver_policy_digest="9"*64, observed_at=now,verify_carrier=verify_carrier,
                                verify_observer=verify_observer,max_stages=max_stages)


def test_operational_path_roundtrip_preserves_ground_observers_and_edges():
    hops, ground, ctx = _f()
    receipt = _accept(hops)
    assert receipt.source == "origin" and receipt.destination == "verifier"
    assert receipt.input_ref == hops[0].input_ref and receipt.output_ref == hops[-1].output_ref
    assert [stage["mode"] for stage in receipt.stages] == ["carrier", "observe", "carrier", "transform", "carrier", "observe"]
    assert len(receipt.path_digest) == 64
    assert receipt.to_dict()["verification_scope"] == "receiver_callbacks_not_external_attestation"
    assert check_observer_path_receipt(receipt, hops, verify_carrier=lambda _: True, verify_observer=lambda _: True)
    assert _accept(hops).path_digest == receipt.path_digest


def test_carriers_are_passive_even_if_reachable():
    hops, _, _ = _f()
    with pytest.raises(ObserverPathError, match="passive carrier"):
        replace(hops[0], output_ref=hops[3].output_ref)
    with pytest.raises(ObserverPathError, match="channel direction"):
        replace(hops[0], source="other")
    with pytest.raises(ObserverPathError, match="only a native channel"):
        replace(hops[0], contract=hops[1].contract)


def test_receiver_cannot_accept_self_authored_delivery_or_operator_authority():
    hops, _, _ = _f()
    with pytest.raises(ObserverPathError, match="carrier delivery"):
        _accept(hops, verify_carrier=lambda _: False)
    with pytest.raises(ObserverPathError, match="observer operation"):
        _accept(hops, verify_observer=lambda _: False)
    with pytest.raises(ObserverPathError, match="carrier delivery"):
        _accept(hops, verify_carrier=lambda _: 1)
    with pytest.raises(ObserverPathError, match="observer operation"):
        _accept(hops, verify_observer=lambda _: 1)


def test_expired_not_yet_observed_and_wrong_type_channels_refuse():
    hops, _, _ = _f()
    with pytest.raises(ObserverPathError, match="expired|not yet"):
        _accept(hops, now=101)
    with pytest.raises(ObserverPathError, match="observation coordinate"):
        _accept(hops, now=-1)
    with pytest.raises(ObserverPathError, match="payload"):
        _accept((replace(hops[0], payload_bytes=200),)+hops[1:])
    other=replace(hops[0].channel, carries=("other.type",))
    with pytest.raises(ObserverPathError, match="cannot carry"):
        _accept((replace(hops[0], channel=other),)+hops[1:])


def test_adjacent_loci_and_representation_are_exact():
    hops, _, _ = _f()
    with pytest.raises(ObserverPathError, match="adjacency|continuity"):
        _accept((hops[0],hops[3]))
    with pytest.raises(ObserverPathError, match="adjacency|continuity"):
        _accept((hops[0],hops[1])+hops[4:])


def test_native_receipt_input_and_ground_anchor_refuse_rebinding():
    hops, ground, ctx = _f()
    with pytest.raises(ObserverPathError, match="Ground"):
        _accept(hops,ground=RepresentationRef.from_payload("different",1,{"rule":"lower"}))
    with pytest.raises(ObserverPathError, match="context"):
        _accept(hops,context="0"*64)
    invalid=replace(hops[1].receipt,input_digest="0"*64)
    with pytest.raises(ObserverPathError, match="receipt input"):
        _accept(hops[:1]+(replace(hops[1],receipt=invalid),)+hops[2:])


def test_transform_requires_correspondence_to_new_content_digest():
    hops, _, _ = _f()
    wrong=replace(hops[3].receipt,subject_state_after_digest="f"*64)
    with pytest.raises(ObserverPathError, match="before/after"):
        _accept(hops[:3]+(replace(hops[3],receipt=wrong),)+hops[4:])
    with pytest.raises(ObserverPathError, match="subject-state"):
        _accept(hops[:1]+(replace(hops[1],receipt=replace(hops[1].receipt,subject_state_after_digest="f"*64)),)+hops[2:])


def test_changed_observer_contract_revision_fails_closed():
    hops, _, _ = _f()
    wrong=replace(hops[1].contract,revision=2)
    with pytest.raises(ObserverPathError, match="native observer receipt"):
        _accept(hops[:1]+(replace(hops[1],contract=wrong),)+hops[2:])


def test_no_duplicate_receipt_can_explain_two_actions():
    hops, _, _ = _f()
    # Insert second local read with same receipt and same subject into the sequence.
    duplicate=hops[:2]+(hops[1],)+hops[2:]
    with pytest.raises(ObserverPathError, match="cannot stand for two"):
        _accept(duplicate)


def test_a_tampered_path_witness_cannot_verify_against_original_hops():
    hops, _, _ = _f()
    good=_accept(hops)
    forged=replace(good,path_digest="0"*64)
    assert not check_observer_path_receipt(forged,hops,verify_carrier=lambda _: True,verify_observer=lambda _: True)
    assert not check_observer_path_receipt(good,hops,verify_carrier=lambda _: True,verify_observer=lambda _: False)


def test_single_transport_has_no_execution_receipt():
    hops, _, _ = _f()
    single=_accept((hops[0],))
    assert len(single.stages)==1 and single.stages[0]["mode"]=="carrier"
    assert single.output_ref==single.input_ref


def test_path_budgets_and_boolean_coordinates_refuse():
    hops, _, _ = _f()
    with pytest.raises(ObserverPathError, match="finite stage"):
        _accept(hops,max_stages=5)
    with pytest.raises(ObserverPathError, match="observation coordinate"):
        _accept(hops,now=True)
    with pytest.raises(ObserverPathError, match="payload"):
        replace(hops[0],payload_bytes=True)


def test_rehosting_changes_transport_witness_not_mathematical_ground():
    hops, ground, ctx = _f()
    old=_accept(hops)
    # Different observed channel path, same ground and transform receipts.
    changed_edge=replace(hops[2].channel,evidence_digest="d"*64)
    newer=_accept(hops[:2]+(replace(hops[2],channel=changed_edge),)+hops[3:])
    assert newer.ground == old.ground
    assert newer.path_digest != old.path_digest
    assert newer.output_ref == old.output_ref


def test_two_logical_observers_do_not_imply_independent_physical_hosts():
    hops, _, _ = _f()
    receipt=_accept(hops)
    assert "placement" not in receipt.to_dict()
    assert "failure_domain" not in receipt.to_dict()


def test_receiver_policy_identity_is_part_of_path_identity():
    hops, ground, ctx = _f()
    old = _accept(hops)
    newer = verify_observer_path(hops, ground=ground, context_digest=ctx,
        receiver_policy_digest="a"*64, observed_at=22,
        verify_carrier=lambda _:True, verify_observer=lambda _:True)
    assert old.ground == newer.ground
    assert old.path_digest != newer.path_digest