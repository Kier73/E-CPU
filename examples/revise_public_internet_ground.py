"""INTERNET-009: intention -> real public RFC observation -> revised Ground.

Use ORIGINAL INTERNET-006 bounded prospective probe/HeadlessOS permission,
INTERNET-004 raw RFC HTML link verifier and INTERNET-005 native route
admission. INTERNET-009 *after that* replays source bytes through a distinct
receiver-installed feature decoder and revises the finite hypothetical Ground
toward a source-conditioned answer. An offline reader repeats every step
without any network I/O, using only the exact original archived bytes.

Nothing claims arbitrary Internet execution, webpage-signed evidence, passive
fiber arithmetic or that the receiver's two-state hypothesis model is an
universal description of reality.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from mailcpu.headless import HeadlessOS
from mailcpu.kernel import Capability
from mailcpu.evidence_path_resolver import RouteMetric, _local_capability_snapshot
from mailcpu.internet_ground_routing import (
    InternetGroundRouter, admitted_rfc_observation,
)
from mailcpu.internet_prospective_qualification import (
    ProbeCapture, ProbePolicy, ProspectiveQualifier,
)
from mailcpu.internet_observed_ground_revision import (
    EvidenceGroundRevision, ReceiverFeatureBinding, SourceFeatureReading,
)
from mailcpu.intention_sufficiency import (
    FiniteState, FiniteGround, MeasurementCapability,
)
from mailcpu.public_internet_navigation import (
    Policy, navigate, verify_capsule, canonical, strict_loads, rfc_url,
)
from mailcpu.semantic_translation import canonical_value_digest
from examples.prospectively_navigate_public_internet import setup


RAW_LIMIT = 1_048_576
SOURCE_PIN_INDEPENDENTLY_ESTABLISHED = False


def build_model(intent, policy: Policy) -> FiniteGround:
    """A source-external finite alternative table, never supplied by HTML."""
    public={"seed": policy.seeds[0], "target": policy.target}
    rows=tuple(sorted((
        FiniteState.create(
            "a_no_path", public, {"observed_rfc_path": False},
            {"rfc_path": False},
        ),
        FiniteState.create(
            "b_path_reached", public, {"observed_rfc_path": True},
            {"rfc_path": True},
        ),
    ),key=lambda row:row.state_id))
    return FiniteGround(
        intent.ground_digest,
        canonical_value_digest({"contract": "rfc_public_path_v1"}),
        canonical_value_digest({"contract": "rfc_path_intention_v1"}),
        intent.context_digest, rows,
    )


def capture_digest(capsule: dict) -> str:
    """Recompute original INTERNET-006 event's source-evidence projection."""
    return canonical_value_digest({
        "capsule_sha256": capsule["capsule_digest"],
        "raw_content": [v["content_sha256"] for v in capsule["visits"]],
    })


def observe_and_revise(policy: Policy, *, archived: dict|None=None) -> dict[str, Any]:
    """Only observable bytes from the allowlisted RFC host can change model."""
    intent,offer=setup(policy)
    receiver_owned: dict[str,Any]={}
    expected_path=(rfc_url(policy.seeds[0]),rfc_url(policy.target))
    public={"seed":policy.seeds[0],"target":policy.target}

    def source_verify(case):
        fn=receiver_owned.get("verifier")
        return bool(fn and case.case_digest==receiver_owned.get("case_digest")
                    and fn(case) is True)

    router=InternetGroundRouter({"rfceditor": source_verify})
    os=HeadlessOS()
    pid=os.environment.kernel.spawn(
        "internet009-source-observer",
        capabilities=(Capability("/internet/rfc/rfceditor",
                                 frozenset({"observe"})),),
        parent_pid=os.environment.init_pid,
    )

    def bounded_probe(proposed,byte_ceiling):
        if proposed.digest!=offer.digest:
            raise ValueError("remote site may not change receiver-approved offer")
        capsule=navigate(policy) if archived is None else archived
        proof=verify_capsule(capsule,policy)
        if proof["observed_bytes"]>byte_ceiling:
            raise ValueError("raw HTTP observation exceeds prospective quota")
        case, independent=admitted_rfc_observation(
            capsule,policy,
            expected_capsule_digest=capsule["capsule_digest"],
            expected_path=expected_path,provider_id="rfceditor",
            source=intent.source,target=intent.target,
            context_digest=intent.context_digest,
            observed_at=15,expires_at=30,
            costs=(
                RouteMetric("latency_us","us",sum(
                    max(1,int(x["elapsed_ns"]/1000)) for x in capsule["visits"]
                )),
                RouteMetric("bytes","B",proof["observed_bytes"]),
            ),
        )
        receiver_owned.update({
            "case_digest":case.case_digest,"verifier":independent,
            "capsule":capsule,
        })
        return ProbeCapture(
            case, proof["observed_bytes"],len(capsule["visits"]),
            sum(x["elapsed_ns"] for x in capsule["visits"]),
            capture_digest(capsule),
        )

    qualifier=ProspectiveQualifier(
        router,{"rfceditor":bounded_probe},
        ProbePolicy(frozenset({"rfceditor"}),max_attempts=1,
                    total_response_budget=RAW_LIMIT),(offer,),
    )
    base=build_model(intent,policy)
    catalogue=(
        MeasurementCapability(
            "rfc_path",canonical_value_digest(
                {"feature":"rfc_path","receiver_contract":policy.as_dict()}),
            "rfceditor",1,
        ),
    )

    def independent_source_decoder(case, raw:bytes)->SourceFeatureReading:
        # This is receiver-installed, not supplied by a website or its URL.
        # The complete original bytes, link graph and exact expected path are
        # reconstructed here, distinct from the original native handler.
        capsule=strict_loads(raw)
        verified=verify_capsule(
            capsule,policy,expected_capsule_digest=case.evidence_digest,
        )
        path=tuple(verified["path"])
        if (case.provider_id!="rfceditor"
                or case.kind!="rfc"
                or case.operation!="navigate.references"
                or path!=expected_path
                or verified["status"]!="reached_observed_target"):
            raise ValueError("source bytes cannot establish receiver's declared RFC feature")
        return SourceFeatureReading(
            value=True,raw_evidence_digest=capture_digest(capsule),
            case_evidence_digest=capsule["capsule_digest"],
        )

    authority=_local_capability_snapshot(os,pid)[1]
    revision=EvidenceGroundRevision(
        base,public,catalogue,
        (ReceiverFeatureBinding(
            offer.digest,"rfceditor","rfc_path",
            independent_source_decoder,max_archive_bytes=8*1024*1024,
        ),),
        authority,
    )
    before=revision.snapshot()
    step=qualifier.step(intent,os,pid)
    if step["status"]!="qualified_and_routed":
        raise RuntimeError("receiver native Internet Ground refused: "+step["status"])
    actual=receiver_owned["capsule"]
    original_source_bytes=canonical(actual)
    event=qualifier.history[-1]
    receipt=revision.admit(qualifier,intent,event,original_source_bytes)
    after=revision.snapshot()
    if (after["model_status"]!="CONDITIONALLY_RESOLVED"
            or after["conditional_result"]!={"observed_rfc_path":True}
            or after["candidate_count"]!=1
            or receipt["status"]!="EVIDENCE_CONDITIONED"):
        raise RuntimeError("source-qualified model revision did not resolve its own finite intention")

    # Independent fresh reader, same original native-qualified case, original
    # archived raw bytes, same source verification policy. No extra network.
    verifier=EvidenceGroundRevision(
        base,public,catalogue,revision.bindings,authority,
    )
    if verifier.replay(qualifier,intent,((event,original_source_bytes),))!=after:
        raise RuntimeError("independent mathematical Ground replay failed")

    return {
        "schema":"mailcpu.internet009.source-conditioned-rfc-pilot.v1",
        "mode":"live_HTTPS_observation" if archived is None else "offline_raw_replay",
        "allowlisted_source":rfc_url(policy.seeds[0]),
        "intention_target":rfc_url(policy.target),
        "capsule":actual,
        "native_prospective_event":step["event"],
        "native_prospective_status":step["status"],
        "native_route":step["result"]["selected"],
        "source_feature_receipt":receipt,
        "finite_ground_before":before,
        "finite_ground_after":after,
        "untrusted_finite_model_warning":True,
        "source_content_independently_pinned_before_fetch":SOURCE_PIN_INDEPENDENTLY_ESTABLISHED,
        "source_http_requests_this_run":len(actual["visits"]) if archived is None else 0,
        "source_observed_bytes":sum(x["size_bytes"] for x in actual["visits"]),
        "passive_internet_circuit_execution_claimed":False,
    }


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode",choices=("observe","replay"))
    parser.add_argument("--seed",type=int,default=9293)
    parser.add_argument("--target",type=int,default=793)
    parser.add_argument("--input",type=Path)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    policy=Policy((args.seed,),args.target,max_pages=4,max_depth=2)
    if args.mode=="observe":
        if args.input is not None:
            parser.error("observe cannot use recorded input")
        result=observe_and_revise(policy)
    else:
        if args.input is None:
            parser.error("replay requires the actual prior live report")
        prior=strict_loads(args.input.read_bytes())
        if (prior.get("schema")!="mailcpu.internet009.source-conditioned-rfc-pilot.v1"
                or prior.get("mode")!="live_HTTPS_observation"
                or prior.get("source_http_requests_this_run",0)<1):
            raise ValueError("offline reader requires an original live HTTPS capsule")
        result=observe_and_revise(policy,archived=prior["capsule"])
        for key in (
            "capsule","source_feature_receipt","finite_ground_after",
            "finite_ground_before","native_route","native_prospective_event",
        ):
            if result[key]!=prior[key]:
                raise ValueError("offline source and native Ground reconstruction diverged: "+key)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_bytes(canonical(result)+b"\n")
    print(json.dumps({
        "mode":result["mode"],
        "source_requests":result["source_http_requests_this_run"],
        "native_ground":result["native_prospective_status"],
        "model_status":result["finite_ground_after"]["model_status"],
        "revision_tip":result["finite_ground_after"]["revision_tip"],
        "output":str(args.output),
    },sort_keys=True))


if __name__=="__main__":
    main()
