"""Shared verified pure work consumed by separate native M3 state transitions."""
from hashlib import sha256
import struct
from types import MappingProxyType

import pytest

from mailcpu.computational_objects import ComputationalObjectStore
from mailcpu.computational_session import ComputationalSessionConflictError, ComputationalSessionStore
from mailcpu.computational_transition import ComputationalSessionTransitionAdapter, ComputationalTransitionContract
from mailcpu.recovery_lineage import RecoveryLineageAuthority, RecoveryLineageCoordinator
from mailcpu.seed_commit_quorum import SeedCommitMembership
from mailcpu.shared_result_bank import Consumer, PureContract, ResultBank


def h(raw):
    """Return exact content identity."""
    return sha256(raw).hexdigest()


NS=h(b'fab023-native')
BACKEND=h(b'fab023-projection-v1')
SCHEMA='fab023.private-state.v1'
PURE=PureContract(h(b'exact-square'),h(b'public-fixture'),h(b'multiply-checker'),8,16)
CONTRACT=ComputationalTransitionContract('fab023.project',SCHEMA,'fab023.project-input.v1',
    h(b'projection-interpretation'),BACKEND,16,1024)
STATE=struct.Struct('!8sQQ')


class Pages:
    """Native immutable page backing fixture."""
    page_size=4096
    def __init__(self):
        """Retain padded pages."""
        self.pages={}
    def put_page(self,data):
        """Publish exact padded bytes."""
        assert len(data)==4096
        k=h(data)
        assert self.pages.setdefault(k,data)==data
        return k
    def get_page(self,key):
        """Recover one native page."""
        return self.pages[key]


def store(root,pages,identity):
    """Open the original native M3 session with three local journals."""
    name=f'fab127.{NS}.{identity:06x}'
    directory=root/name
    membership=SeedCommitMembership(name,1,('A','B','C'),'A',1,
                h(b'mailcpu-recovery-lineage-genesis-v1'))
    authorities={m:RecoveryLineageAuthority(membership,m,directory/'authorities'/f'{m}.jsonl')
                 for m in membership.member_ids}
    return ComputationalSessionStore(directory/'sessions',ComputationalObjectStore(pages),
            RecoveryLineageCoordinator(membership,authorities),
            artifact_manifest_digest=h(b'fixture'),backend_fingerprint=BACKEND,state_schema_id=SCHEMA)


def produce(raw):
    """Compute the shared exact operation."""
    return (int.from_bytes(raw,'big')**2).to_bytes(16,'big')


def check(raw,result):
    """Independently verify shared output."""
    x=int.from_bytes(raw,'big')
    return len(result)==16 and int.from_bytes(result,'big')==x*x


class Projection:
    """Trusted pure fixture backend consuming one immutable receiver-verified batch."""
    backend_fingerprint=BACKEND
    def __init__(self,admitted):
        """Pin the shared exact results for this batch."""
        self.admitted=MappingProxyType(dict(admitted))
        self.calls=0
    def transition(self,state_bytes,input_bytes,context):
        """Bind the shared operand to this machine's actual native state."""
        assert input_bytes==b'project'
        source,bias,_=STATE.unpack(state_bytes)
        result=int.from_bytes(self.admitted[source],'big')+bias
        self.calls+=1
        return STATE.pack(source,bias,result)


def test_native_shared_result_admission(tmp_path):
    """Two pure results feed eight independent native CAS histories, not shared commits."""
    ids=[0,1,2,3,4,5,6,0xffffff]
    inputs=[(5+i%2).to_bytes(8,'big') for i in range(len(ids))]
    pages=Pages(); stores={i:store(tmp_path,pages,i) for i in ids}
    initial={i:stores[i].create_session(STATE.pack(raw,i,0)) for i,raw in zip(ids,inputs)}
    path=tmp_path/'bank.db'; bank=ResultBank(path,create=True)
    bank.observe_consumers([Consumer(NS,i,initial[i].revision,initial[i].checkpoint_digest,PURE.key(raw))
                            for i,raw in zip(ids,inputs)])
    outputs=bank.resolve_batch(PURE,inputs,produce,check)
    assert (bank.produced,bank.checked)==(2,2)
    bank.close(); bank=ResultBank(path)
    def no_producer(raw):
        """Reopening must recover without repeating shared production."""
        raise AssertionError('unexpected repeated production')
    recovered=bank.resolve_batch(PURE,inputs,no_producer,check)
    assert recovered==outputs and (bank.produced,bank.checked)==(0,2)
    backend=Projection(zip(inputs,recovered))
    commits={}
    for i,raw in zip(ids,inputs):
        adapter=ComputationalSessionTransitionAdapter(stores[i],CONTRACT,backend)
        args=dict(operation_id='project',expected_revision=initial[i].revision,
                  expected_checkpoint_digest=initial[i].checkpoint_digest)
        committed=adapter.apply(b'project',**args)
        assert committed.revision==2 and committed.checkpoint.predecessor_checkpoint_digest==initial[i].checkpoint_digest
        assert STATE.unpack(committed.state_bytes)==(raw,i,int.from_bytes(raw,'big')**2+i)
        assert adapter.apply(b'project',**args).replayed
        commits[i]=committed
        bank.observe_consumers([Consumer(NS,i,committed.revision,committed.checkpoint_digest,PURE.key(raw))])
    assert backend.calls==8
    assert len({c.checkpoint_digest for c in commits.values()})==8
    assert len({c.lineage_manifest.digest for c in commits.values()})==8
    for i in ids:
        reopened=store(tmp_path,pages,i)
        assert reopened.load_latest().checkpoint_digest==commits[i].checkpoint_digest
    # Changing a dependency identifies only its subscribers; M3 remains authority.
    affected=bank.affected(PURE.key(inputs[0]),NS)
    assert {c.identity for c in affected}==set(ids[::2])
    for c in affected:
        assert c.checkpoint==commits[c.identity].checkpoint_digest
    adapter=ComputationalSessionTransitionAdapter(stores[0],CONTRACT,backend)
    with pytest.raises(ComputationalSessionConflictError):
        adapter.apply(b'project',operation_id='different',expected_revision=1,
                      expected_checkpoint_digest=initial[0].checkpoint_digest)
    assert backend.calls==8
    bank.close()
