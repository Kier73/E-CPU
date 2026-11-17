"""INTERNET-003: qualified HTTP proxy observation through existing MailCPU contracts.

A receiver with independently pinned source bytes and locally installed
admission policy decides whether a real HTTP exchange can become a typed
observer-path witness.  No authority is inferred from Nginx response headers,
SHA digests, advertised names, or network reachability.  This adapter does not
claim a passive physical link implements the transform.
"""
from __future__ import annotations

from typing import Callable

from mailcpu.observer_orbit import ObserverContract, ObserverReceipt
from mailcpu.observer_path_evidence import ObserverPathStage, check_observer_path_receipt, verify_observer_path
from mailcpu.semantic_translation import ObservationContract, RepresentationRef, canonical_value_digest
from probe_internet_path_nginx import verify_response, digest, InternetPathRefused


def admit_http_observation(
    observed: dict,
    *, receiver_source: bytes,
    mode: str,
    receiver_policy_digest: str,
    observed_at: int,
    receiver_admit: Callable[[ObserverPathStage], bool],
    offset: int = 0,
    length: int | None = None,
    supplied_etag: str | None = None,
    baseline_reference: dict | None = None,
) -> dict:
    """Construct a native transformation witness only after local source verification.

    Deliberately models one active proxy stage: the endpoint-observed HTTP
    transformation is not proof that a specific interface, fiber or router
    contributed work.  The controller must authenticate/isolate its own proxy.
    """
    if (type(observed_at) is not int or observed_at < 0 or
            type(receiver_policy_digest) is not str or len(receiver_policy_digest) != 64 or
            any(ch not in '0123456789abcdef' for ch in receiver_policy_digest) or
            not callable(receiver_admit)):
        raise InternetPathRefused('receiver-owned policy and observation coordinate required')
    if observed.get('route') != 'proxy':
        raise InternetPathRefused('native intermediary witness requires controlled proxy observation')
    verdict = verify_response(observed, current_source=receiver_source,
                               mode=mode, offset=offset, length=length,
                               supplied_etag=supplied_etag,
                               baseline_reference=baseline_reference)
    source_identity = {'sha256':digest(receiver_source),'byte_length':len(receiver_source)}
    subject = RepresentationRef.from_payload('internet.http.source-representation',1,source_identity)
    result_identity = {'mode':mode,'status':verdict['status'],
                       'bytes_sha256':digest(observed['body']),
                       'byte_length':len(observed['body']),
                       'etag':verdict['etag'],
                       'encoding':observed['headers'].get('content-encoding','identity')}
    rendered = RepresentationRef.from_payload('internet.http.observed-representation',1,result_identity)
    ground = RepresentationRef.from_payload('internet.http.observer-ground',1,{
        'schema':'mailcpu.internet-path-http.v1',
        'origin_source_sha256':digest(receiver_source),
        'observer':'nginx.proxy.http',
        'supported_modes':['complete','conditional','range'],
        'physical_claim':'controlled-local-process-observation-only',
    })
    definition = ObservationContract.from_definition('internet.http-selected-response',1,{
        'fields':['source_sha256','mode','status','payload_bytes','etag'],
        'exactness':'receiver-byte-verified-conditional-or-projection',
    })
    context = canonical_value_digest({'source':source_identity, 'mode':mode,
                                      'offset':offset if mode == 'range' else None,
                                      'length':length if mode == 'range' else None,
                                      'etag':supplied_etag if mode=='conditional' else None})
    contract = ObserverContract('nginx.proxy.http',1,subject,ground,definition,context)
    projection={key:verdict[key] for key in ('status','source_sha256','etag','mode','payload_bytes')}
    input_evidence = RepresentationRef.from_payload('internet.http-client-measurement',1,{
        'status':verdict['status'], 'body_sha256':result_identity['bytes_sha256'],
        'scope':'client-socket-read-not-physical-hop-attribution',
    })
    receipt = ObserverReceipt.issue(contract,
        operation_id='http-source-bound-response',
        input_digest=subject.content_digest,
        projection_value=projection,
        subject_state_before_digest=subject.content_digest,
        subject_state_after_digest=rendered.content_digest,
        evidence=(input_evidence,))
    stage = ObserverPathStage('transform', 'nginx.proxy.http','nginx.proxy.http',
                              subject, rendered, contract=contract,receipt=receipt,
                              payload_bytes=len(observed['body']))

    def receiver_checker(item: ObserverPathStage) -> bool:
        return item is stage and receiver_admit(item) is True and item.receipt.projection==projection

    args=dict(ground=ground,context_digest=context,
              receiver_policy_digest=receiver_policy_digest,observed_at=observed_at,
              verify_carrier=lambda _:False,verify_observer=receiver_checker)
    path=verify_observer_path((stage,),**args)
    if not check_observer_path_receipt(path,(stage,),verify_carrier=lambda _:False,
                                      verify_observer=receiver_checker):
        raise InternetPathRefused('native observer path receipt verification refused')
    return {'schema':'mailcpu.internet-native-http-path-observation.v1',
            'source_sha256':digest(receiver_source),'mode':mode,
            'native_path':path.to_dict(), 'native_receipt':receipt.to_dict(),
            'scope':'one-receiver-verified-local-active-intermediary-no-external-attestation'}
