"""Measure immutable machine-head index density; synthetic heads, not OS checkpoints."""
import argparse
from hashlib import sha256
import json
import random
import resource
import time
from mailcpu.fabric_head_index import FabricHeadIndex, MachineHead, PAGE_SIZE, HEADER, RECORD


class MemoryBacking:
    """Count immutable page bytes in a native-compatible in-memory backing."""
    def __init__(self):
        """Initialize counters and content-addressed pages."""
        self.pages={}; self.reads=0; self.writes=0

    def get_page(self,d):
        """Read a retained immutable page."""
        self.reads+=1
        return self.pages[d]

    def put_page(self,b):
        """Retain a page under its exact content identity."""
        d=sha256(b).hexdigest()
        self.pages.setdefault(d,b)
        self.writes+=1
        return d


def synthetic(i,revision=1):
    """Unique test coordinate payload, explicitly not a real quorum checkpoint."""
    return sha256(i.to_bytes(3,'big')+revision.to_bytes(8,'big')).hexdigest()


def run(bits):
    """Build batches, independently verify every stored head and sample path lookups."""
    n=1<<bits
    backing=MemoryBacking(); ns=sha256(b'benchmark'); index=FabricHeadIndex(backing,ns.hexdigest()); empty=index.empty_root(); root=empty
    start=time.perf_counter()
    batch=1<<min(bits,18)
    for lo in range(0,n,batch):
        root=index.update(root,((i,MachineHead(1,synthetic(i))) for i in range(lo,lo+batch)))
        print(f'build {lo+batch}/{n}',flush=True)
    build=time.perf_counter()-start
    start=time.perf_counter(); count=0; seen_pages=set()
    def walk(d,level,prefix):
        """Independently check page digest, prefix, and all populated leaf records."""
        nonlocal count
        raw=backing.get_page(d)
        assert sha256(raw).hexdigest()==d and len(raw)==PAGE_SIZE
        assert HEADER.unpack_from(raw)==(b'FABIDX01',ns.digest(),level,prefix)
        assert d not in seen_pages; seen_pages.add(d)
        if level==3:
            for slot in range(64):
                rev,head=RECORD.unpack_from(raw,HEADER.size+slot*RECORD.size)
                i=prefix*64+slot
                if i<n:
                    assert rev==1 and head.hex()==synthetic(i); count+=1
                else: assert rev==0 and head==bytes(32)
        else:
            for slot in range(64):
                child=raw[HEADER.size+32*slot:HEADER.size+32*(slot+1)]
                if child!=bytes(32): walk(child.hex(),level+1,prefix*64+slot)
    walk(root,0,0); assert count==n
    verify=time.perf_counter()-start
    sample=random.Random(127).sample(range(n),min(n,4096)); before=backing.reads
    start=time.perf_counter()
    for i in sample: assert index.lookup(root,i)==MachineHead(1,synthetic(i))
    lookup=time.perf_counter()-start; reads=backing.reads-before
    old_pages=len(backing.pages); changes=sample[:64]; start=time.perf_counter()
    newroot=index.update(root,((i,MachineHead(2,synthetic(i,2))) for i in changes))
    update=time.perf_counter()-start
    for i in changes:
        assert index.lookup(root,i)==MachineHead(1,synthetic(i))
        assert index.lookup(newroot,i)==MachineHead(2,synthetic(i,2))
        assert index.lookup(empty,i) is None
    return dict(mode='synthetic checkpoint heads; no OS state or quorum verification',identities=n,verified_heads=count,live_index_pages=len(seen_pages),live_index_bytes=len(seen_pages)*PAGE_SIZE,retained_pages_before_update=old_pages,retained_bytes_before_update=old_pages*PAGE_SIZE,build_seconds=build,verify_seconds=verify,sampled_lookups=len(sample),sampled_page_reads=reads,sampled_lookup_seconds=lookup,updated_heads=len(changes),new_pages=len(backing.pages)-old_pages,update_seconds=update,peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,root=root,newroot=newroot)


if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--bits',type=int,choices=range(6,25),default=24); p.add_argument('--report',required=True); a=p.parse_args()
    result=run(a.bits)
    with open(a.report,'w') as f: json.dump(result,f,indent=2)
    print(json.dumps(result),flush=True)
