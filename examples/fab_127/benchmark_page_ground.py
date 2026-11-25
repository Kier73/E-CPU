"""Matched durable page representation trial with private sparse mutations."""
from pathlib import Path
import json
import random
import time
from mailcpu.page_ground import PageGroundBacking, PAGE_SIZE, digest


def run(root, count=1024):
    """Verify all pages after reopen and measure independent sparse reads."""
    root=Path(root); root.mkdir(exist_ok=True,parents=True)
    rng=random.Random(127)
    bases=[rng.randbytes(PAGE_SIZE) for _ in range(16)]
    def object_pages(i):
        """Retain shared pages and two independent sparse mutations per object."""
        pages=list(bases)
        for slot in (i%16,(i+7)%16):
            page=bytearray(pages[slot]); off=(i*13)%4092
            page[off:off+4]=(i+1).to_bytes(4,'big'); pages[slot]=bytes(page)
        return pages
    reports={}
    for mode in ('raw','compressed','ground'):
        path=root/(mode+'.db'); b=PageGroundBacking(path,create=True,bases=bases,mode=mode)
        start=time.perf_counter(); manifests=[]
        for i in range(count):
            pages=object_pages(i); keys=tuple(b.put_page(p) for p in pages)
            assert keys==tuple(digest(p) for p in pages); manifests.append(keys)
        write=time.perf_counter()-start; counts=b.counts(); b.close()
        b=PageGroundBacking(path,mode=mode); start=time.perf_counter(); verified=0
        for i,keys in enumerate(manifests):
            for key,p in zip(keys,object_pages(i)):
                assert b.get_page(key)==p; verified+=1
        read=time.perf_counter()-start
        queries=[]; b.db.set_trace_callback(queries.append); start=time.perf_counter()
        for i in random.Random(73).sample(range(count),count):
            slot=i%16; assert b.get_page(manifests[i][slot])==object_pages(i)[slot]
        sparse=time.perf_counter()-start; b.db.set_trace_callback(None); b.close()
        reports[mode]=dict(db_bytes=path.stat().st_size,counts=counts,write_seconds=write,full_verify_seconds=read,verified_pages=verified,sparse_reads=count,sparse_seconds=sparse,sparse_sql_selects=sum(q.startswith('SELECT') for q in queries))
    return dict(workload='synthetic fixed-page objects; all three modes SQLite FULL; 16 common incompressible basis pages, two sparse private mutations per object',objects=count,logical_bytes=count*16*PAGE_SIZE,results=reports)


if __name__=='__main__':
    import sys
    print(json.dumps(run(sys.argv[1]),indent=2))
