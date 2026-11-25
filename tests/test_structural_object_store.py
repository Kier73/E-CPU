"""Native M1 manifest identity and alternate representation conformance."""
from dataclasses import replace
from hashlib import sha256
import io
import json
import sqlite3

import pytest
from mailcpu.computational_objects import ComputationalObjectError, ComputationalObjectStore
from mailcpu.structural_object_store import StructuralObjectStore


class Pages:
    """Count exact retained pages in a test backing compatible with native M1."""
    page_size=4096
    def __init__(self):
        """Initialize an empty immutable page map."""
        self.pages={}
    def put_page(self,data):
        """Retain exact padded bytes under their content identity."""
        assert len(data)==self.page_size
        d=sha256(data).hexdigest(); assert self.pages.setdefault(d,data)==data; return d
    def get_page(self,digest):
        """Read one existing page."""
        return self.pages[digest]


def raw(i):
    """Generate distinct canonical objects sharing a long memory string."""
    return json.dumps({'memory':'a'*16384,'register':i},sort_keys=True,separators=(',',':')).encode()


def setup(tmp_path):
    """Pin one native base and separate ordinary baseline page backing."""
    pages=Pages(); native=ComputationalObjectStore(pages); base=native.put_bytes(raw(0),media_type='application/json')
    catalog=tmp_path/'representations.sqlite'
    return pages,base,catalog,StructuralObjectStore(pages,catalog,base_manifest=base),ComputationalObjectStore(Pages())


def test_native_identity_and_range(tmp_path):
    """Identical manifest, range and full verification with no target raw pages."""
    pages,base,path,store,ordinary=setup(tmp_path); before=dict(pages.pages)
    for i in range(1,33):
        expected=ordinary.put_bytes(raw(i),media_type='application/json')
        observed=store.put_bytes(raw(i),media_type='application/json')
        assert observed==expected and observed.canonical_bytes()==expected.canonical_bytes()
        assert store.catalog.get(observed.manifest_digest) is not None
        assert store.verify(observed.to_dict())
        assert store.read_range(observed,4090,20)==raw(i)[4090:4110]
        assert store.read_bytes(observed)==raw(i)
        assert store.put_bytes(raw(i),media_type='application/json')==observed
        assert StructuralObjectStore(pages,path).read_bytes(observed)==raw(i)
        with pytest.raises(ComputationalObjectError): store.read_bytes(observed,max_bytes=100)
        with pytest.raises(ComputationalObjectError): store.read_range(observed,True,1)
        with pytest.raises(ComputationalObjectError): store.read_range(observed,0,-1)
    assert pages.pages==before
    assert store.read_bytes(base)==raw(0)


def test_fallback_and_stream(tmp_path):
    """Leave ordinary noncanonical, non-JSON, and stream inputs on native M1."""
    pages,base,path,store,ordinary=setup(tmp_path)
    for value,media in [(b'not-json','application/json'),(b'{ "x": 1 }','application/json'),(b'{"x":1}','application/json'),(raw(5),'application/octet-stream')]:
        m=store.put_bytes(value,media_type=media)
        assert m==ordinary.put_bytes(value,media_type=media)
        assert store.catalog.get(m.manifest_digest) is None
        assert store.read_bytes(m)==value
    value=raw(99); m=store.put_stream(io.BytesIO(value),len(value),media_type='application/json')
    assert store.catalog.get(m.manifest_digest) is None and store.verify(m)


def test_fail_closed(tmp_path):
    """Refuse wrong target metadata and corrupt patch even when raw pages exist."""
    pages,base,path,store,ordinary=setup(tmp_path)
    m=store.put_bytes(raw(7),media_type='application/json')
    ComputationalObjectStore(pages).put_bytes(raw(7),media_type='application/json')
    with sqlite3.connect(path) as db: db.execute('UPDATE delta SET patch=? WHERE manifest=?',(b'[0,null]',m.manifest_digest))
    with pytest.raises(ValueError,match='target identity'): store.read_bytes(m)
    with sqlite3.connect(path) as db: db.execute('UPDATE delta SET target=? WHERE manifest=?',('0'*64,m.manifest_digest))
    with pytest.raises(ComputationalObjectError,match='target identity'): store.verify(m)


def test_missing_representation_or_base(tmp_path):
    """A lost row cannot regenerate blank state; a lost base cannot be hidden by cache."""
    pages,base,path,store,ordinary=setup(tmp_path)
    m=store.put_bytes(raw(7),media_type='application/json')
    with sqlite3.connect(path) as db: db.execute('DELETE FROM delta WHERE manifest=?',(m.manifest_digest,))
    with pytest.raises(ComputationalObjectError): store.read_bytes(m)
    m=store.put_bytes(raw(8),media_type='application/json')
    del pages.pages[base.chunks[0].page_digest]
    with pytest.raises(ComputationalObjectError): store.read_bytes(m)
    with pytest.raises(ComputationalObjectError): StructuralObjectStore(pages,path)


def test_manifest_page_integrity(tmp_path):
    """A self-consistent forged manifest cannot change the exact page identities."""
    pages,base,path,store,ordinary=setup(tmp_path)
    m=store.put_bytes(raw(7),media_type='application/json')
    bad=replace(m,chunks=(replace(m.chunks[0],page_digest='0'*64),*m.chunks[1:]))
    d=store.catalog.get(m.manifest_digest); store.catalog.record(bad.manifest_digest,d)
    with pytest.raises(ComputationalObjectError,match='native manifest differs'): store.verify(bad)
