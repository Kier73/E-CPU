"""Measure native M1 identity preservation with a durable structural catalog."""
from hashlib import sha256
import json
from pathlib import Path
import random
import sys
import time

from mailcpu.computational_objects import ComputationalObjectStore
from mailcpu.structural_object_store import StructuralObjectStore


class Pages:
    """Count native M1 immutable page payloads in a local in-memory backing."""
    page_size=4096
    def __init__(self):
        """Initialize a page map."""
        self.pages={}
    def put_page(self,raw):
        """Retain a native page and return its content digest."""
        assert len(raw)==self.page_size
        d=sha256(raw).hexdigest(); assert self.pages.setdefault(d,raw)==raw; return d
    def get_page(self,d):
        """Resolve one exact retained page."""
        return self.pages[d]


def run(path,count=1024):
    """Measure synthetic states through actual native M1 and exact alternate reads."""
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    rng=random.Random(127); immutable=rng.randbytes(16384).hex(); page=rng.randbytes(4096)
    def state(i):
        """Form an independent synthetic mutation of a common template."""
        mutable=bytearray(page); pos=(i*13)%4092; mutable[pos:pos+4]=i.to_bytes(4,'big')
        return json.dumps({'artifact':immutable,'vm':{'memory':mutable.hex(),'registers':{'machine':i,'pc':3}},
                           'filesystem':{'output':f'machine-{i:06x}'},'journal':[{'event':'boot'},{'event':'write','identity':i}]},
                          sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
    raw_pages,structural_pages=Pages(),Pages()
    native=ComputationalObjectStore(raw_pages); base_store=ComputationalObjectStore(structural_pages)
    base=base_store.put_bytes(state(0),media_type='application/json')
    store=StructuralObjectStore(structural_pages,path,base_manifest=base)
    manifests=[]; logical=0; manifest_bytes=0; raw_seconds=0.0; structural_seconds=0.0
    for i in range(count):
        value=state(i); logical+=len(value)
        t=time.perf_counter(); original=native.put_bytes(value,media_type='application/json'); raw_seconds+=time.perf_counter()-t
        t=time.perf_counter(); actual=store.put_bytes(value,media_type='application/json'); structural_seconds+=time.perf_counter()-t
        assert actual==original; manifests.append(actual); manifest_bytes+=len(actual.canonical_bytes())
    del store,native
    store=StructuralObjectStore(structural_pages,path); start=time.perf_counter()
    for i,m in enumerate(manifests):
        assert store.verify(m) and store.read_bytes(m)==state(i)
    read_seconds=time.perf_counter()-start
    result={'workload':'synthetic application-shaped objects through exact native M1 source; local SQLite catalog; in-memory page backing',
            'objects':count,'identical_manifests':count,'verified_after_reopen':count,
            'logical_object_bytes':logical,'identical_manifest_bytes_both_routes':manifest_bytes,
            'raw_unique_page_bytes':len(raw_pages.pages)*4096,'structural_unique_base_page_bytes':len(structural_pages.pages)*4096,
            'catalog_file_bytes':path.stat().st_size,'structural_base_and_catalog_bytes':len(structural_pages.pages)*4096+path.stat().st_size,
            'raw_native_put_seconds':raw_seconds,'structural_put_seconds':structural_seconds,'verify_and_read_seconds':read_seconds}
    print(json.dumps(result,indent=2)); return result


if __name__=='__main__':
    run(sys.argv[1])
