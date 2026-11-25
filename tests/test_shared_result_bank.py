"""Test durable reuse, exact admission, dependency replacement and interrupted publication."""
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import sqlite3
import subprocess
import sys
import pytest
from mailcpu.shared_result_bank import PureContract, Consumer, ResultBank


def h(raw):
    """Fixture digest."""
    return sha256(raw).hexdigest()


C = PureContract(h(b'square'),h(b'context'),h(b'checker'),8,16)
NS = h(b'namespace')


def produce(raw):
    """Compute an exact nonnegative square."""
    return (int.from_bytes(raw,'big')**2).to_bytes(16,'big')


def verify(raw, result):
    """Independently compare square via integer multiplication."""
    x=int.from_bytes(raw,'big')
    return len(result)==16 and int.from_bytes(result,'big')==x*x


def test_reuse(tmp_path):
    """One producer/checker per distinct input, including reopening with a new verifier pass."""
    p=tmp_path/'bank.db'; b=ResultBank(p,create=True)
    inputs=[b'a',b'b',b'a']*100
    assert b.resolve_batch(C,inputs,produce,verify)==tuple(map(produce,inputs))
    assert (b.produced,b.checked)==(2,2)
    b.close(); b=ResultBank(p)
    def no_producer(raw):
        """A durable hit must not execute the producer."""
        raise AssertionError('unexpected producer')
    assert b.resolve_batch(C,inputs,no_producer,verify)==tuple(map(produce,inputs))
    assert (b.produced,b.checked)==(0,2)
    other=replace(C,context=h(b'other'))
    assert b.resolve(other,b'a',produce,verify)==produce(b'a') and b.produced==1
    b.close()


def test_corruption(tmp_path):
    """Reject false results even with a self-consistent altered digest."""
    b=ResultBank(tmp_path/'bank.db',create=True)
    with pytest.raises(ValueError,match='verification refused'):
        b.resolve(C,b'a',lambda _:bytes(16),verify)
    assert b.db.execute('SELECT count(*) FROM result').fetchone()[0]==0
    b.resolve(C,b'a',produce,verify)
    with b.db:
        b.db.execute('UPDATE result SET output=?,output_digest=?',(bytes(16),h(bytes(16))))
    with pytest.raises(ValueError,match='verification refused'):
        b.resolve(C,b'a',produce,verify)
    b.close()


def test_dependencies(tmp_path):
    """Only changed dependency subscribers move; no stale or conflicting replacement."""
    p=tmp_path/'bank.db'; b=ResultBank(p,create=True)
    a=Consumer(NS,0,1,h(b'a'),C.key(b'a')); z=Consumer(NS,0xffffff,1,h(b'z'),C.key(b'a'))
    foreign=replace(z,namespace=h(b'other'))
    b.observe_consumers([a,z,foreign]); b.close(); b=ResultBank(p)
    assert b.affected(a.key,NS)==(a,z)
    next_a=replace(a,revision=2,checkpoint=h(b'a2'),key=C.key(b'b'))
    b.observe_consumers([next_a]); assert b.affected(a.key,NS)==(z,)
    with pytest.raises(ValueError,match='stale'):
        b.observe_consumers([replace(z,revision=2),a])
    assert b.affected(a.key,NS)==(z,)
    with pytest.raises(ValueError,match='conflicting'):
        b.observe_consumers([replace(next_a,key=C.key(b'c'))])
    with pytest.raises(ValueError,match='duplicate'):
        b.observe_consumers([next_a,next_a])
    assert b.affected(next_a.key,NS)==(next_a,)
    b.close()


def test_abrupt_exit(tmp_path):
    """A committed result survives abrupt termination, a later deletion rolls back."""
    p=tmp_path/'bank.db'
    script='''import os,sys
from mailcpu.shared_result_bank import PureContract,ResultBank
from hashlib import sha256
h=lambda x:sha256(x).hexdigest()
c=PureContract(h(b'square'),h(b'context'),h(b'checker'),8,16)
b=ResultBank(sys.argv[1],create=True)
b.resolve(c,b'a',lambda x:(int.from_bytes(x,'big')**2).to_bytes(16,'big'),lambda x,y:int.from_bytes(y,'big')==int.from_bytes(x,'big')**2)
b.db.execute('BEGIN IMMEDIATE'); b.db.execute('DELETE FROM result'); os._exit(19)
'''
    result=subprocess.run([sys.executable,'-c',script,str(p)],cwd=Path(__file__).resolve().parents[1])
    assert result.returncode==19
    b=ResultBank(p); assert b.resolve(C,b'a',produce,verify)==produce(b'a'); assert b.produced==0
    b.close()
    with pytest.raises(sqlite3.OperationalError): ResultBank(tmp_path/'absent.db')
