"""INTERNET-009: real native E-CPU + VGI advice then source-checked revision.

These tests use the original INTERNET-008 native fixtures and genuine
HeadlessOS / EvidencePathResolver / VGI objects. The sample probe handler in
the *fixture* is synthetic: these tests establish the revision contract, NOT
public Internet observation. A separate network job uses original RFC HTTPS
observer, native prospective case admission and an offline independent reader.
"""
from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import json
import unittest

from mailcpu.internet_observed_ground_revision import (
    EvidenceGroundRevision, GroundRevisionRefused, SourceFeatureReading,
    ReceiverFeatureBinding,
)
from mailcpu.semantic_translation import canonical_value_digest
from mailcpu.intention_sufficiency import plan_sufficiency
from mailcpu.internet_prospective_qualification import ProbeEvent
from mailcpu.evidence_path_resolver import _local_capability_snapshot
from test_internet_distinguishability_attention import fixture, intention, finite_ground


SOURCE = b'{"source":"receiver-test-HTTP-fixture","body":"verified-link","value":1}'


def decoder(case, raw):
    """A test-only exact source checker, never represented as public HTTPS."""
    if sha256(raw).digest() != sha256(SOURCE).digest():
        raise ValueError("actual raw source differs from receiver's independent test pin")
    obj = json.loads(raw)
    if (obj != {"source": "receiver-test-HTTP-fixture",
                "body": "verified-link", "value": 1}
            or case.provider_id != "httpalt"
            or case.kind != "http"):
        raise ValueError("test source payload lacks exact installed origin contract")
    return SourceFeatureReading(
        value=obj["value"],
        raw_evidence_digest=canonical_value_digest({"raw": case.provider_id}),
        case_evidence_digest=case.evidence_digest,
    )


def contradicted_decoder(case, raw):
    """Different explicit observation, test only: finite model cannot cover 2."""
    first=decoder(case, raw)
    return SourceFeatureReading(2, first.raw_evidence_digest,
                                first.case_evidence_digest)


def engine(f, *,contradiction=False):
    match=next(o for o in f.qualifier.offers if o.provider_id == "httpalt")
    return EvidenceGroundRevision(
        finite_ground(), {"scope": "one-observation-fiber"},
        f.qualifier.attention.measurement_offers,
        (ReceiverFeatureBinding(
            match.digest, "httpalt", "http",
            contradicted_decoder if contradiction else decoder,
            2048,
        ),),
        _local_capability_snapshot(f.os,f.pid)[1],
    )


class NativeEvidenceRevisionTests(unittest.TestCase):

    def observed(self):
        f=fixture()
        assert f.qualifier.choose(intention(),f.os,f.pid).provider_id=="httpalt"
        result=f.qualifier.step(intention(),f.os,f.pid)
        self.assertEqual(result["status"],"case_accepted_not_selected")
        self.assertEqual(f.calls,["httpalt"])
        self.assertEqual(len(f.router._cases),1)
        self.assertEqual(len(f.qualifier.history),1)
        return f,f.qualifier.history[-1]

    def test_real_vgi_priority_then_native_case_conditions_ground(self):
        f,event=self.observed()
        ground=engine(f)
        initial=ground.snapshot()
        self.assertEqual(initial["model_status"],"MORE_SOURCE_EVIDENCE_REQUIRED")
        self.assertEqual(initial["sufficiency_plan"]["selected_features"],["http"])
        self.assertEqual(initial["candidate_count"],4)
        self.assertFalse(initial["source_conditioned"])
        receipt=ground.admit(f.qualifier,intention(),event,SOURCE)
        self.assertEqual(receipt["status"],"EVIDENCE_CONDITIONED")
        self.assertEqual(receipt["previous_states"],["s1","s2","s3","s4"])
        self.assertEqual(receipt["remaining_states"],["s2","s4"])
        self.assertEqual(receipt["feature_id"],"http")
        result=ground.snapshot()
        self.assertEqual(result["candidate_count"],2)
        self.assertEqual(result["measured_features"],["http"])
        self.assertEqual(result["model_status"],"CONDITIONALLY_RESOLVED")
        self.assertEqual(result["conditional_result"],1)
        self.assertEqual(result["sufficiency_plan"]["status"],"READY")
        self.assertEqual(len(f.router._cases),1)
        # Distinguish the mathematical target from the NATIVE route:
        # the HTTP observation alone did not realize the RFC path.
        self.assertEqual(f.calls,["httpalt"])
        self.assertEqual(ground.snapshot()["digest"],result["digest"])
        self.assertIn("not_a_remotely_attested_world_fact",result["not"])

    def test_independent_replay_reconstructs_all_source_conditioned_digests(self):
        f,event=self.observed()
        original=engine(f)
        first=original.admit(f.qualifier,intention(),event,SOURCE)
        replay=engine(f)
        self.assertEqual(replay.replay(f.qualifier,intention(),((event,SOURCE),)),
                         original.snapshot())
        self.assertEqual(replay.receipts[0],first)
        self.assertEqual(first["raw_archive_sha256"],sha256(SOURCE).hexdigest())
        self.assertEqual(replay.admit(f.qualifier,intention(),event,SOURCE),first)
        self.assertEqual(replay.snapshot()["revision_count"],1)

    def test_modified_bytes_and_rehashed_local_label_do_not_change_ground(self):
        f,event=self.observed()
        e=engine(f)
        with self.assertRaisesRegex(GroundRevisionRefused,"source-specific"):
            e.admit(f.qualifier,intention(),event,
                    SOURCE.replace(b"verified-link",b"forged-link"))
        with self.assertRaisesRegex(GroundRevisionRefused,"source-specific"):
            e.admit(f.qualifier,intention(),event,
                    SOURCE.replace(b'"value":1',b'"value":0'))
        self.assertEqual(e.snapshot()["revision_count"],0)
        self.assertEqual(e.snapshot()["candidate_count"],4)

    def test_decoded_feature_must_match_original_native_capture_digest(self):
        f,event=self.observed()
        e=engine(f)
        bound=e.bindings[0]
        bad=lambda case,raw: SourceFeatureReading(
            1,"a"*64,case.evidence_digest)
        e.bindings=(replace(bound,decoder=bad),)
        with self.assertRaisesRegex(GroundRevisionRefused,"digests disagree"):
            e.admit(f.qualifier,intention(),event,SOURCE)
        self.assertEqual(e.snapshot()["revision_count"],0)

    def test_actual_source_can_contradict_finite_hypothesis_without_becoming_negative(self):
        f,event=self.observed()
        e=engine(f,contradiction=True)
        receipt=e.admit(f.qualifier,intention(),event,SOURCE)
        self.assertEqual(receipt["status"],"MODEL_CONTRADICTION")
        self.assertEqual(receipt["remaining_states"],[])
        state=e.snapshot()
        self.assertEqual(state["model_status"],"MODEL_CONTRADICTED")
        self.assertEqual(state["candidate_count"],0)
        self.assertIsNone(state["sufficiency_plan"])
        self.assertIsNone(state["conditional_result"])
        self.assertEqual(state["revision_count"],1)
        self.assertIsNone(e.current_ground())
        # Never reinterpret a model mismatch as an observed negative ground.
        self.assertEqual(receipt["reading"],2)

    def test_failed_probe_and_counterfactual_vgi_score_are_not_evidence(self):
        f=fixture(failures=("httpalt",))
        report=f.qualifier.step(intention(),f.os,f.pid)
        self.assertEqual(report["status"],"probe_refused")
        e=engine(f)
        with self.assertRaisesRegex(GroundRevisionRefused,"native-qualified"):
            e.admit(f.qualifier,intention(),f.qualifier.history[-1],SOURCE)
        self.assertEqual(e.snapshot()["candidate_count"],4)
        self.assertEqual(e.snapshot()["revision_count"],0)

    def test_an_unrecorded_self_hashed_event_cannot_be_promoted(self):
        f,event=self.observed()
        e=engine(f)
        forgery=replace(event,ordinal=8)
        self.assertIsInstance(forgery,ProbeEvent)
        with self.assertRaisesRegex(GroundRevisionRefused,"original native observation history"):
            e.admit(f.qualifier,intention(),forgery,SOURCE)
        self.assertEqual(e.snapshot()["revision_count"],0)

    def test_wrong_context_stale_lease_and_revoked_native_verifier(self):
        f,event=self.observed()
        e=engine(f)
        with self.assertRaisesRegex(GroundRevisionRefused,"native-qualified"):
            e.admit(f.qualifier,replace(intention(),context_digest="f"*64),event,SOURCE)
        with self.assertRaisesRegex(GroundRevisionRefused,"current receiver"):
            e.admit(f.qualifier,intention(now=90),event,SOURCE)
        old=f.router._verifiers["httpalt"]
        f.router._verifiers["httpalt"]=lambda candidate: False
        with self.assertRaisesRegex(GroundRevisionRefused,"native receiver refused"):
            e.admit(f.qualifier,intention(),event,SOURCE)
        f.router._verifiers["httpalt"]=old
        self.assertEqual(e.snapshot()["candidate_count"],4)

    def test_native_observation_log_predecessor_tampering_refuses_revision(self):
        f,event=self.observed()
        f.qualifier.history.append(replace(event,ordinal=9))
        with self.assertRaisesRegex(GroundRevisionRefused,"attempt chain changed"):
            engine(f).admit(f.qualifier,intention(),event,SOURCE)

    def test_decoder_policy_is_not_supplied_by_external_data(self):
        f,event=self.observed()
        e=engine(f)
        invalid=replace(e.bindings[0],feature_id="unknown")
        with self.assertRaises(GroundRevisionRefused):
            EvidenceGroundRevision(
                e.base,e.public_value,e.offers,(invalid,),e.authority_digest)
        self.assertEqual(e.snapshot()["revision_count"],0)

    def test_model_identity_and_original_rows_are_unchanged_after_revision(self):
        f,event=self.observed()
        e=engine(f)
        old=e.base.digest
        old_ids=[x.state_id for x in e.base.states]
        e.admit(f.qualifier,intention(),event,SOURCE)
        self.assertEqual(e.base.digest,old)
        self.assertEqual([x.state_id for x in e.base.states],old_ids)
        self.assertNotEqual(e.current_ground().digest,old)
        self.assertEqual([x.state_id for x in e.current_ground().states],["s2","s4"])


if __name__=="__main__":
    unittest.main()
