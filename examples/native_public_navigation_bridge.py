"""INTERNET-004: admit one locally checked public-web observation via E-CPU.

The *local HTTPS client* is the evidence observer. The remote RFC service is a
qualified response source, but is not claimed to issue native E-CPU receipts.
All interpretation/permission is supplied by the trusted receiving host.
No carrier observation, identity attestation, or Hypervisor grant is fabricated.
"""
from __future__ import annotations

from typing import Callable, Any

from mailcpu.public_internet_navigation import Policy, verify_capsule, NavigationRefused
from mailcpu.observer_orbit import ObserverContract, ObserverReceipt
from mailcpu.observer_path_evidence import (
    ObserverPathStage, verify_observer_path, check_observer_path_receipt,
)
from mailcpu.semantic_translation import (
    RepresentationRef, ObservationContract, canonical_value_digest,
)


def admit_navigation(capsule: dict, policy: Policy, *,
                     receiver_policy_digest: str, observed_at: int,
                     receiver_admit: Callable[[ObserverPathStage], bool],
                     expected_capsule_sha256: str | None = None,
                     ) -> dict[str, Any]:
    """Bind independently replayed public HTTP observations to native receipts.

    A receiver's policy is *not serialized into the request*. Even a perfect
    hash of an observed page cannot authenticate the remote author or give
    permission to execute content found in that page.
    """
    result = verify_capsule(capsule, policy,
                            expected_capsule_digest=expected_capsule_sha256)
    if (type(receiver_policy_digest) is not str or len(receiver_policy_digest) != 64
            or any(c not in "0123456789abcdef" for c in receiver_policy_digest)
            or type(observed_at) is not int or observed_at < 0
            or not callable(receiver_admit)):
        raise NavigationRefused("receiver policy and admission callback are required")
    intention = {"seed_numbers": list(policy.seeds), "target_number": policy.target,
                 "scope": "bounded-rfc-document-links", "capsule_digest": capsule["capsule_digest"]}
    subject = RepresentationRef.from_payload("internet.public-rfc-navigation-input",1,intention)
    ground = RepresentationRef.from_payload("internet.public-rfc-document-ground",1,policy.as_dict())
    observation = ObservationContract.from_definition(
        "internet.public-rfc-navigation-verdict",1,
        {"fields":["status","path","pages","observed_bytes"],
         "origin":"local-HTTPS-observer-untrusted-content"})
    context = canonical_value_digest(intention)
    contract = ObserverContract("ecpu.public-https-observer",1,subject,ground,observation,context)
    evidence = RepresentationRef.from_payload("internet.public-rfc-captured-bytes",1,{
        "capsule_digest": capsule["capsule_digest"],
        "observed": [
            {"url": x["url"], "sha256": x["content_sha256"]}
            for x in capsule["visits"]
        ],
    })
    projection = {"status": result["status"], "path": result["path"],
                  "pages": result["pages"], "observed_bytes": result["observed_bytes"]}
    receipt = ObserverReceipt.issue(
        contract,operation_id="bounded-public-https-link-observation",
        input_digest=subject.content_digest,projection_value=projection,
        subject_state_before_digest=subject.content_digest,
        subject_state_after_digest=subject.content_digest,evidence=(evidence,))
    stage = ObserverPathStage(
        "observe","ecpu.public-https-observer","ecpu.public-https-observer",
        subject,subject,contract=contract,receipt=receipt)

    def allowed(proposed):
        return proposed is stage and receiver_admit(proposed) is True

    path = verify_observer_path(
        (stage,),ground=ground,context_digest=context,
        receiver_policy_digest=receiver_policy_digest,observed_at=observed_at,
        verify_carrier=lambda _: False,verify_observer=allowed)
    if not check_observer_path_receipt(path,(stage,),verify_carrier=lambda _: False,
                                       verify_observer=allowed):
        raise NavigationRefused("native witness reconstruction failed")
    return {"schema": "mailcpu.public-internet-navigation-native.v1",
            "native_observer_contract": contract.to_dict(),
            "native_observer_receipt": receipt.to_dict(),
            "native_observer_path": path.to_dict(),
            "source_capsule_digest": capsule["capsule_digest"],
            "observation": projection,
            "scope": "receiver-admitted-HTTPS-observation-no-remote-ECPU-or-router-attestation"}
