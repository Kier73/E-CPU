"""Independent sparse index tests; no M3 authority is inferred."""
from hashlib import sha256
import random
import pytest
from mailcpu.fabric_head_index import FabricHeadIndex, MachineHead, PAGE_SIZE

NS=sha256(b'fabric').hexdigest()

def head(i,r=1):
    """Form deterministic synthetic checkpoint coordinates."""
    return MachineHead(r,sha256(f'{i}/{r}'.encode()).hexdigest())

class Backing:
    """Minimal native-compatible immutable page store for unit tests."""
    def __init__(self):
        """Initialize counters and immutable byte map."""
        self.pages={}; self.reads=0; self.writes=0
    def get_page(self,d):
        """Return exact bytes and count the read."""
        self.reads+=1; return self.pages[d]
    def put_page(self,b):
        """Publish one exact content-addressed page."""
        assert len(b)==PAGE_SIZE
        d=sha256(b).hexdigest(); self.pages.setdefault(d,b); self.writes+=1; return d

def test_persistence_and_batch():
    """Verify extremes, path-local writes, historical roots and exact retry."""
    b=Backing(); idx=FabricHeadIndex(b,NS); r0=idx.empty_root()
    ids=[0,1,63,64,4095,4096,2**18,2**24-1]
    r1=idx.update(r0,[(i,head(i)) for i in ids]); assert r1!=r0
    for i in ids:
        assert idx.lookup(r0,i) is None
        before=b.reads; assert idx.lookup(r1,i)==head(i); assert b.reads-before==4
    assert idx.lookup(r1,2) is None
    before=b.writes; r2=idx.update(r1,[(0,head(0,2)),(1,head(1,2))]); assert b.writes-before==4
    assert idx.lookup(r1,0)==head(0); assert idx.lookup(r2,0)==head(0,2)
    assert idx.lookup(r2,2**24-1)==head(2**24-1)
    before=b.writes; assert idx.update(r2,[(0,head(0,2))])==r2; assert b.writes==before
    assert idx.update(r2,[])==r2

def test_conflicts_and_corruption():
    """Refuse regression, conflicting revision, missing pages and invalid scope."""
    b=Backing(); idx=FabricHeadIndex(b,NS); r0=idx.empty_root(); r1=idx.update(r0,[(0,head(0,2))])
    for changes in [[(0,head(0))],[(0,head(1,2))],[(0,head(0,3)),(0,head(0,3))]]:
        with pytest.raises(ValueError): idx.update(r1,changes)
    with pytest.raises(ValueError): FabricHeadIndex(b,sha256(b'other').hexdigest()).lookup(r1,0)
    assert idx.lookup(r1,0)==head(0,2)
    original=b.pages[r1]; b.pages[r1]=b'x'*PAGE_SIZE
    with pytest.raises(ValueError,match='integrity'): idx.lookup(r1,0)
    del b.pages[r1]
    with pytest.raises(KeyError): idx.lookup(r1,0)
    b.pages[r1]=original
    for i in [-1,2**24,True]:
        with pytest.raises(ValueError): idx.lookup(r1,i)

def test_random_history():
    """Compare every sampled historical root with independent dictionary state."""
    rng=random.Random(127); b=Backing(); idx=FabricHeadIndex(b,NS); root=idx.empty_root(); expected={}; history=[]
    for _ in range(40):
        history.append((root,dict(expected)))
        changes={i:head(i,expected[i].revision+1 if i in expected else 1) for i in rng.sample(range(1024),32)}
        root=idx.update(root,changes.items()); expected.update(changes)
        for i in rng.sample(range(1024),64): assert idx.lookup(root,i)==expected.get(i)
    for root,expected in history:
        for i in rng.sample(range(1024),64): assert idx.lookup(root,i)==expected.get(i)

def test_reopen_disk(tmp_path):
    """Reopen immutable index from files without the original Python object."""
    class Disk:
        """Test-only file backing, not a crash-safe replication protocol."""
        def get_page(self,d):
            """Read page bytes from the test directory."""
            return (tmp_path/d).read_bytes()
        def put_page(self,b):
            """Write a page under its content identity."""
            d=sha256(b).hexdigest(); (tmp_path/d).write_bytes(b); return d
    idx=FabricHeadIndex(Disk(),NS); root=idx.update(idx.empty_root(),[(42,head(42))])
    del idx
    idx=FabricHeadIndex(Disk(),NS); assert idx.lookup(root,42)==head(42)
    assert idx.lookup(root,43) is None
