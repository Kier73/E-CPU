"""INTERNET-002: adapt an independently checked live Git observation to E-CPU.

Uses existing MailCPU ObserverContract, ObserverReceipt, ObserverPathStage and
verify_observer_path. Does NOT construct a transport channel, install code at
GitHub, assert passive link transformation, bypass a local receiver policy,
or create a Hypervisor authority grant. The receiver must supply and enforce
its own exact manifest pin, runtime read function, and admission callback.
"""
from __future__ import annotations

from typing import Callable, Mapping, Any

from mailcpu.observer_orbit import ObserverContract, ObserverReceipt
from mailcpu.observer_path_evidence import (
    ObserverPathStage, VerifiedObserverPath,
    check_observer_path_receipt, verify_observer_path,
)
from mailcpu.semantic_translation import (
    ObservationContract, RepresentationRef, canonical_value_digest,
)
from verify_internet_graph_ground import (
    InternetGraphRefused, observe_remote_graph, independent_comparison,
    validate_manifest, HEX64, digest,
)


def native_git_observation(
    read: Callable[[str], Mapping[str, Any]],
    manifest: dict, *,
    manifest_sha256: str,
    base: str,
    head: str,
    receiver_policy_digest: str,
    observed_at: int,
    receiver_admit: Callable[[ObserverPathStage], bool],
) -> dict:
    """Bind one real Internet-service observation into *existing* E-CPU types.

    Native observer evidence is recomputed in a receiver-owned process from
    exact remote commit, tree, ref and comparison observations. The resulting
    receipt's observer ID describes a declared information locus; the record
    remains unsigned after export, and the path has NO inferred carrier stage.
    """
    validate_manifest(manifest)
    if (type(receiver_policy_digest) is not str or not HEX64.fullmatch(receiver_policy_digest)
            or type(observed_at) is not int or observed_at < 0
            or not callable(receiver_admit)):
        raise InternetGraphRefused('receiver-owned policy, observer coordinate or admission missing')
    if base not in manifest['nodes'] or head not in manifest['nodes'] or [base,head] not in manifest['queries']:
        raise InternetGraphRefused('intention does not belong to declared query Ground')
    remote = observe_remote_graph(read, manifest, manifest_sha256=manifest_sha256)
    comparison = next(x for x in remote['comparisons'] if (x['base'],x['head'])==(base,head))
    if comparison['merge_base_sha'] != independent_comparison(manifest, base, head)['merge_base_sha']:
        raise InternetGraphRefused('actual service result differs from observer Ground')
    payload={'repo':manifest['repository'], 'manifest_sha256':manifest_sha256,
             'base_commit':manifest['nodes'][base]['sha'],
             'head_commit':manifest['nodes'][head]['sha']}
    subject=RepresentationRef.from_payload('internet.git-graph-query-state',1,payload)
    ground=RepresentationRef.from_payload('internet.git-native-compare-ground',1,{
        'schema':manifest['schema'], 'source_manifest_sha256':manifest_sha256,
        'root_sha':manifest['nodes'][manifest['root']]['sha'],
        'operator':'existing-GitHub-compare-service-operator'})
    observation=ObservationContract.from_definition('internet.git-ancestry-projection',1,{
        'fields':['status','ahead_by','behind_by','merge_base_sha'],
        'comparison':'exact-finite-graph-ancestry'})
    context=canonical_value_digest(payload)
    contract=ObserverContract('github.git.compare',1,subject,ground,observation,context)
    projection={key:comparison[key] for key in
                ('base','head','status','ahead_by','behind_by','merge_base_sha','total_commits')}
    projection['remote_observation_sha256']=remote['receipt_sha256']
    evidence=RepresentationRef.from_payload('internet.git-remote-comparison',1,comparison)
    receipt=ObserverReceipt.issue(contract,operation_id='git-compare-projection',
        input_digest=subject.content_digest,projection_value=projection,
        subject_state_before_digest=subject.content_digest,
        subject_state_after_digest=subject.content_digest,
        evidence=(evidence,))
    stage=ObserverPathStage('observe','github.git.compare','github.git.compare',
                            subject,subject,contract=contract,receipt=receipt)

    def allowed(step: ObserverPathStage) -> bool:
        # This callback is receiver-installed; never infer admission from
        # a remote content digest or a sender-provided capability flag.
        return (step is stage and receiver_admit(step) is True and
                step.receipt.projection==projection)

    path=verify_observer_path((stage,),ground=ground,context_digest=context,
        receiver_policy_digest=receiver_policy_digest,observed_at=observed_at,
        verify_carrier=lambda _: False, verify_observer=allowed)
    if not check_observer_path_receipt(path,(stage,),verify_carrier=lambda _: False,
                                       verify_observer=allowed):
        raise InternetGraphRefused('native observer path witness could not be reconstructed')
    return {
        'schema':'mailcpu.internet-git-native-observer-projection.v1',
        'ground_digest':ground.content_digest,
        'remote_observation_sha256':remote['receipt_sha256'],
        'declared_intention':{'base':base,'head':head},
        'native_observer_contract':contract.to_dict(),
        'native_observer_receipt':receipt.to_dict(),
        'native_observer_path':path.to_dict(),
        'scope':'one-receiver-admitted-application-service-observer-no-carrier-stage-or-signature',
    }
