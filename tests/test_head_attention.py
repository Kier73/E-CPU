"""Quorum head observation, selective materialization and incremental attention."""
from hashlib import sha256
import json
from time import perf_counter

import pytest

from mailcpu.attention import Budget
from mailcpu.computational_objects import ComputationalObjectStore
from mailcpu.computational_session import (
    ComputationalSessionConflictError, ComputationalSessionError,
    ComputationalSessionIntegrityError, ComputationalSessionStore,
)
from mailcpu.head_attention import HeadAttentionIndex
from mailcpu.recovery_lineage import RecoveryLineageAuthority, RecoveryLineageCoordinator
from mailcpu.seed_commit_quorum import SeedCommitMembership


def digest(value):
    """Return the fixture content identity."""
    return sha256(value).hexdigest()


NS=digest(b"fab020-namespace")
DEMAND=Budget(1,16,0,1)


class CountingBacking:
    """Native fixed-page backing with an exact payload read counter."""
    page_size=4096

    def __init__(self):
        """Initialize immutable page storage and read accounting."""
        self.pages={}
        self.reads=0

    def put_page(self,raw):
        """Retain one exact padded page."""
        assert len(raw)==self.page_size
        key=digest(raw)
        assert self.pages.setdefault(key,raw)==raw
        return key

    def get_page(self,key):
        """Count every attempted native page read."""
        self.reads+=1
        return self.pages[key]


def session(root, backing, identity, namespace=NS):
    """Open one actual native M3 session with three local authority journals."""
    name=f"fab127.{namespace}.{identity:06x}"
    directory=root/name
    membership=SeedCommitMembership(name,1,("A","B","C"),"A",1,
                                   digest(b"mailcpu-recovery-lineage-genesis-v1"))
    authorities={m:RecoveryLineageAuthority(membership,m,directory/"authorities"/f"{m}.jsonl")
                 for m in membership.member_ids}
    return ComputationalSessionStore(directory/"sessions",ComputationalObjectStore(backing),
                 RecoveryLineageCoordinator(membership,authorities),
                 artifact_manifest_digest=digest(b"artifact"),
                 backend_fingerprint=digest(b"backend"),state_schema_id="fab020.fixture.v1")


def commit(store, first, state):
    """Advance one original native CAS transition."""
    return store.commit_state(state,expected_revision=first.revision,
                  expected_checkpoint_digest=first.checkpoint_digest,
                  transition_id="advance",operation_id="fixture.advance",
                  input_digest=digest(state),logical_time=first.checkpoint.logical_time+1)


def test_head_without_payload_and_stale_refusal(tmp_path):
    """Metadata is observable without available pages; recovery is not."""
    backing=CountingBacking()
    a=session(tmp_path,backing,0)
    with pytest.raises(ComputationalSessionError):
        a.observe_head()
    first=a.create_session(b"a"*8192)
    b=session(tmp_path,backing,0xffffff)
    b.create_session(b"b"*8192)
    backing.reads=0
    head=a.observe_head()
    assert head.checkpoint==first.checkpoint
    assert head.lineage_manifest.digest==first.lineage_manifest.digest
    assert backing.reads==0
    assert a.load_observed(head).state_bytes==first.state_bytes
    assert backing.reads==4
    backing.reads=0
    with pytest.raises(ComputationalSessionConflictError):
        b.load_observed(head)
    assert backing.reads==0
    key=head.checkpoint.state_manifest.chunks[0].page_digest
    saved=backing.pages.pop(key)
    before=a.lineage.high_water()
    assert a.observe_head().checkpoint_digest==head.checkpoint_digest
    assert backing.reads==0
    with pytest.raises(ComputationalSessionIntegrityError):
        a.load_observed(head)
    assert a.lineage.high_water()==before
    backing.pages[key]=saved
    second=commit(a,first,b"c"*8192)
    backing.reads=0
    with pytest.raises(ComputationalSessionConflictError):
        a.load_observed(head)
    assert backing.reads==0
    assert a.observe_head().checkpoint_digest==second.checkpoint_digest
    envelope=a._record_path(second.revision,second.lineage_manifest.digest)
    raw=envelope.read_bytes()
    envelope.write_bytes(raw+b" ")
    with pytest.raises(ComputationalSessionIntegrityError):
        a.observe_head()
    assert backing.reads==0
    envelope.write_bytes(raw)


def test_pending_intention_lifecycle(tmp_path):
    """Cache only explicit work and refuse stale grants before state reads."""
    backing=CountingBacking()
    a=session(tmp_path,backing,1)
    b=session(tmp_path,backing,2)
    foreign=session(tmp_path,backing,1,digest(b"foreign"))
    first=a.create_session(b"a"*4096)
    b.create_session(b"b"*4096)
    index=HeadAttentionIndex(NS)
    backing.reads=0
    index.refresh(a,Budget(1,1,0,1))
    index.refresh(b)
    assert len(index.offers())==1 and backing.reads==0
    epoch=index.epoch
    index.refresh(a,Budget(1,1,0,1))
    assert index.epoch==epoch
    with pytest.raises(ValueError,match="another fabric"):
        index.refresh(foreign,Budget(1,1,0,1))
    cap=Budget(1,1,0,1)
    plan=index.plan(cap)
    assert index.verify(plan,cap) and not plan.authoritative
    grant=plan.grants[0]
    assert index.load_grant(a,grant).checkpoint_digest==first.checkpoint_digest
    second=commit(a,first,b"c"*4096)
    backing.reads=0
    with pytest.raises(ComputationalSessionConflictError):
        index.load_grant(a,grant)
    assert backing.reads==0
    index.refresh(a,cap)
    assert not index.verify(plan,cap)
    with pytest.raises(ComputationalSessionConflictError):
        index.withdraw(grant)
    new=index.plan(cap)
    assert index.load_grant(a,new.grants[0]).checkpoint_digest==second.checkpoint_digest
    index.withdraw(new.grants[0])
    assert not index.offers() and not index.verify(new,cap)


@pytest.mark.parametrize("count,selected",[(8,2),(32,4)])
def test_attention_read_accounting(tmp_path,count,selected):
    """Compare complete fleet recovery with metadata-first native selection."""
    backing=CountingBacking()
    ids=[(5*i+3)&0xffffff for i in range(count-1)]+[0xffffff]
    stores={i:session(tmp_path,backing,i) for i in ids}
    states={}
    for i,store in stores.items():
        state=b"".join(sha256(i.to_bytes(3,"big")+p.to_bytes(2,"big")).digest()*128
                       for p in range(16))
        states[i]=store.create_session(state)
    backing.reads=0; start=perf_counter()
    for i,store in stores.items():
        assert store.load_latest().checkpoint_digest==states[i].checkpoint_digest
    baseline_time=perf_counter()-start
    baseline_reads=backing.reads
    assert baseline_reads==count*32
    index=HeadAttentionIndex(NS)
    backing.reads=0; start=perf_counter()
    for store in stores.values():
        index.refresh(store,DEMAND)
    observe_time=perf_counter()-start
    assert backing.reads==0
    capacity=Budget(selected,selected*16,0,selected)
    start=perf_counter()
    plan=index.plan(capacity)
    assert index.verify(plan,capacity) and len(plan.grants)==selected
    plan_time=perf_counter()-start
    assert backing.reads==0
    start=perf_counter()
    for grant in plan.grants:
        i=int("".join(grant.scope[:6]),16)
        materialized=index.load_grant(stores[i],grant)
        assert materialized.state_bytes==states[i].state_bytes
    materialize_time=perf_counter()-start
    selected_reads=backing.reads
    assert selected_reads==selected*32
    # Advance one selected session, refresh only that changed work leaf.
    g=plan.grants[0]; i=int("".join(g.scope[:6]),16)
    second=commit(stores[i],states[i],b"next-state")
    backing.reads=0
    index.refresh(stores[i])
    assert not index.verify(plan,capacity)
    assert backing.reads==0 and len(index.offers())==count-1
    assert stores[i].observe_head().checkpoint_digest==second.checkpoint_digest
    print("FAB020_NATIVE",json.dumps({
        "machines":count,"selected":selected,"pages_per_state":16,
        "baseline_payload_reads":baseline_reads,"metadata_and_planning_payload_reads":0,
        "selected_payload_reads":selected_reads,"incremental_refresh_payload_reads":backing.reads,
        "baseline_seconds":baseline_time,"head_observation_seconds":observe_time,
        "planning_and_verification_seconds":plan_time,"selected_materialization_seconds":materialize_time,
    },sort_keys=True),flush=True)
