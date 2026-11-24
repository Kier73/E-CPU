"""Exact page realization, failure isolation and local transaction recovery."""
from hashlib import sha256
import random
import sqlite3
import subprocess
import sys
from pathlib import Path
import zlib
import pytest
from mailcpu.page_ground import PageGroundBacking, PAGE_SIZE, digest
from mailcpu.computational_objects import ComputationalObjectStore, ComputationalObjectError


def test_exact_and_independent(tmp_path):
    """Reopen private mutations and refuse damaged pages without scanning others."""
    rng=random.Random(127); base=rng.randbytes(PAGE_SIZE); path=tmp_path/'pages.db'
    b=PageGroundBacking(path,create=True,bases=[base]); expected={}
    for i in range(128):
        value=bytearray(base); value[i*7:i*7+4]=i.to_bytes(4,'big'); value=bytes(value)
        key=b.put_page(value); assert key==sha256(value).hexdigest(); expected[key]=value
    assert b.counts()[2][0]==128
    b.close(); b=PageGroundBacking(path)
    for key,value in expected.items(): assert b.get_page(key)==value
    a,c=list(expected)[:2]
    b.db.execute('UPDATE page SET body=? WHERE digest=?',(b'bad',a)); b.db.commit()
    with pytest.raises((ValueError,zlib.error)): b.get_page(a)
    assert b.get_page(c)==expected[c]
    b.db.execute('DELETE FROM page WHERE digest=?',(digest(base),)); b.db.commit()
    with pytest.raises(KeyError): b.get_page(c)
    b.close()


def test_fallback_and_corruption(tmp_path):
    """Use raw and independently compressed fallback; refuse changed bytes."""
    base=random.Random(0).randbytes(PAGE_SIZE); b=PageGroundBacking(tmp_path/'p.db',create=True,bases=[base])
    assert b.put_page(base)==digest(base)
    a=b.put_page(bytes(PAGE_SIZE)); c=b.put_page(random.Random(1).randbytes(PAGE_SIZE))
    assert b.counts()[1][0]==1 and b.counts()[0][0]==2
    assert b.get_page(a)==bytes(PAGE_SIZE)
    with pytest.raises(ValueError): b.put_page(b'x')
    with pytest.raises(KeyError): b.get_page('0'*64)
    b.db.execute('UPDATE page SET body=? WHERE digest=?',(bytes(PAGE_SIZE),c)); b.db.commit()
    with pytest.raises(ValueError,match='digest'): b.get_page(c)
    b.close()


def test_loss(tmp_path):
    """Recover a committed page after abrupt worker loss during a later transaction."""
    path=tmp_path/'p.db'; base=random.Random(2).randbytes(PAGE_SIZE); b=PageGroundBacking(path,create=True,bases=[base]); b.close()
    value=base[:100]+b'x'+base[101:]; key=digest(value)
    script='''import os,sys
from mailcpu.page_ground import PageGroundBacking
b=PageGroundBacking(sys.argv[1]); key=b.put_page(bytes.fromhex(sys.argv[2])); b.db.execute('BEGIN IMMEDIATE'); b.db.execute('DELETE FROM page WHERE digest=?',(key,)); os._exit(17)'''
    r=subprocess.run([sys.executable,'-c',script,str(path),value.hex()],cwd=Path(__file__).resolve().parents[1])
    assert r.returncode==17
    b=PageGroundBacking(path); assert b.get_page(key)==value; b.close()
    with pytest.raises(sqlite3.OperationalError): PageGroundBacking(tmp_path/'absent.db')


def test_native_m1_selective_range(tmp_path):
    """Use actual M1 manifests and range reads unchanged across storage realizations."""
    rng=random.Random(127)
    bases=[rng.randbytes(PAGE_SIZE) for _ in range(16)]
    raw=PageGroundBacking(tmp_path/'raw.db',create=True,bases=bases,mode='raw')
    structural=PageGroundBacking(tmp_path/'ground.db',create=True,bases=bases)
    native=ComputationalObjectStore(raw)
    alternate=ComputationalObjectStore(structural)
    data=bytearray(b''.join(bases)); data[100:104]=b'abcd'; data[12*PAGE_SIZE+100:12*PAGE_SIZE+104]=b'efgh'
    data=bytes(data)
    m=native.put_bytes(data)
    assert alternate.put_bytes(data)==m and alternate.verify(m)
    structural.close(); raw.close()
    structural=PageGroundBacking(tmp_path/'ground.db')
    alternate=ComputationalObjectStore(structural)
    traces=[]; structural.db.set_trace_callback(traces.append)
    assert alternate.read_range(m,100,4)==b'abcd'
    structural.db.set_trace_callback(None)
    assert sum(q.startswith('SELECT') for q in traces)==3
    # Corrupt a distant page: a valid local observation is still possible,
    # but whole-object verification must refuse.
    distant=m.chunks[12].page_digest
    structural.db.execute('UPDATE page SET body=? WHERE digest=?',(b'bad',distant)); structural.db.commit()
    assert alternate.read_range(m,100,4)==b'abcd'
    with pytest.raises(ComputationalObjectError): alternate.verify(m)
    structural.close()


def test_native_m3_page_representation(tmp_path):
    """Preserve native checkpoint identity and exact successor across backing reopen."""
    from mailcpu.computational_session import ComputationalSessionStore, ComputationalSessionIntegrityError
    from mailcpu.recovery_lineage import RecoveryLineageAuthority, RecoveryLineageCoordinator
    from mailcpu.seed_commit_quorum import SeedCommitMembership

    bases=[random.Random(i).randbytes(PAGE_SIZE) for i in range(16)]
    path=tmp_path/'ground.db'
    backing=PageGroundBacking(path,create=True,bases=bases)
    genesis=digest(b'mailcpu-recovery-lineage-genesis-v1')
    namespace=digest(b'fab019-test')
    membership=SeedCommitMembership(f'fab127.{namespace}.ffffff',1,('A','B','C'),'A',1,genesis)

    def session(backing):
        """Open original native M3 over the selected native M1 backing."""
        authorities={m:RecoveryLineageAuthority(membership,m,tmp_path/'authorities'/f'{m}.jsonl')
                     for m in membership.member_ids}
        return ComputationalSessionStore(tmp_path/'sessions',ComputationalObjectStore(backing),
                  RecoveryLineageCoordinator(membership,authorities),
                  artifact_manifest_digest=digest(b'fixture'),backend_fingerprint=digest(b'backend'),
                  state_schema_id='fab019.fixed-page-state.v1')

    initial=bytearray(b''.join(bases)); initial[100:104]=b'abcd'; initial=bytes(initial)
    store=session(backing); first=store.create_session(initial); exported=store.export_latest()
    assert backing.counts()[2][0]==1
    backing.close()
    backing=PageGroundBacking(path); store=session(backing)
    restored=store.restore_export(exported)
    assert restored.checkpoint_digest==first.checkpoint_digest and restored.state_bytes==initial
    nxt=bytearray(initial); nxt[12*PAGE_SIZE+100:12*PAGE_SIZE+104]=b'efgh'; nxt=bytes(nxt)
    second=store.commit_state(nxt,expected_revision=first.revision,expected_checkpoint_digest=first.checkpoint_digest,
                  transition_id='change-page',operation_id='operation',input_digest=digest(b'efgh'),logical_time=2)
    assert second.revision==2 and backing.counts()[2][0]==2
    assert store.load_latest().state_bytes==nxt
    backing.close()
    backing=PageGroundBacking(path); store=session(backing)
    current=store.load_latest()
    assert current.checkpoint_digest==second.checkpoint_digest
    manifest=current.checkpoint.state_manifest
    assert store.object_store.read_range(manifest,100,4)==b'abcd'
    target=manifest.chunks[12].page_digest
    before=store.lineage.high_water()
    original=backing._row(target)
    backing.db.execute('UPDATE page SET body=? WHERE digest=?',(b'bad',target)); backing.db.commit()
    assert store.object_store.read_range(manifest,100,4)==b'abcd'
    with pytest.raises(ComputationalSessionIntegrityError): store.load_latest()
    assert store.lineage.high_water()==before
    backing.db.execute('UPDATE page SET body=? WHERE digest=?',(original[2],target)); backing.db.commit()
    assert store.load_latest().checkpoint_digest==second.checkpoint_digest
    backing.close()
