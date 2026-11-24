"""Exact structural snapshot delta conformance."""
from dataclasses import replace
import json
import random
import pytest
from mailcpu.snapshot_delta import form_snapshot_delta


def raw(v):
    """Encode canonical test data."""
    return json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()


@pytest.mark.parametrize('a,b', [({},{}),({'a':1},{'a':True}),({'a':1},{'a':1.0}),({'a':0.0},{'a':-0.0}),
    ({'a':[1,2,3],'b':'old'},{'a':[1,8,3,4],'c':'new'}), ('x'*9000,'x'*4500+'y'+'x'*4499),
    ([1]*1000,[1]*500+[2]+[1]*499), ({'a':None},{'b':None}), ('é'*1000,'é'*999+'雪')])
def test_roundtrip(a,b):
    """Preserve byte identity across heterogeneous JSON values."""
    d=form_snapshot_delta(raw(a),raw(b)); assert d.reconstruct(raw(a))==raw(b)


def test_corrupt():
    """Reject base substitutions, malformed patches and wrong target sizes."""
    a,b=raw({'memory':'a'*8192}),raw({'memory':'a'*4096+'b'+'a'*4095})
    d=form_snapshot_delta(a,b)
    with pytest.raises(ValueError): d.reconstruct(b)
    with pytest.raises(ValueError): replace(d,patch=b'[0,null]').reconstruct(a)
    with pytest.raises(ValueError): replace(d,target_size=d.target_size+1).reconstruct(a)
    for invalid in (b'[2,-1,0,[]]',b'[3,999999,0,"x"]',b'[1,["missing"],{}]',b'[1,[],{"new":null}]',b'{"a":1,"a":1}',b'[false,0]'):
        with pytest.raises(ValueError): replace(d,patch=invalid).reconstruct(a)
    for invalid in (b'{"x": 1}',b'{"a":1,"a":2}',b'NaN',b'\xff'):
        with pytest.raises(ValueError): form_snapshot_delta(invalid,b)


def test_random():
    """Exercise 200 independent field, sequence and memory changes."""
    rng=random.Random(127)
    for i in range(200):
        a={'m':{'page':'ab'*4096,'pc':i,'v':i%3},'q':list(range(i)), 'v':True}
        b=json.loads(raw(a)); b['m']['page']=b['m']['page'][:rng.randrange(8192)]+'new';b['m']['pc']+=1;b['q']+=list(range(rng.randrange(10)));b['v']=1
        assert form_snapshot_delta(raw(a),raw(b)).reconstruct(raw(a))==raw(b)


def test_disjoint_memory_writes():
    """Do not retain unchanged data between distant same-length mutations."""
    a='a'*16384; b='b'+a[1:-1]+'c'; d=form_snapshot_delta(raw(a),raw(b))
    assert d.reconstruct(raw(a))==raw(b) and len(d.patch)<100
    for patch in (b'[4,[[0,"b"],[0,"c"]]]',b'[4,[[16384,"b"]]]',b'[4,[[-1,"b"]]]'):
        with pytest.raises(ValueError): replace(d,patch=patch).reconstruct(raw(a))
