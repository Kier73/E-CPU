"""Measure exact structural sharing on synthetic canonical snapshot-shaped states."""
from hashlib import sha256
import json
import random
import time
import zlib
from mailcpu.snapshot_delta import form_snapshot_delta


def canonical(value):
    """Use the native canonical JSON encoding."""
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()


def run(count=1024):
    """Compare independent compression, fixed-page dedup and one-hop structural deltas."""
    rng=random.Random(127)
    immutable=rng.randbytes(16384).hex()
    page=rng.randbytes(4096)
    def state(i):
        """Construct synthetic private register, page, file and journal changes."""
        mutable=bytearray(page); pos=(i*13)%4092; mutable[pos:pos+4]=i.to_bytes(4,'big')
        return canonical({'artifact':immutable,'vm':{'memory':mutable.hex(),'registers':{'machine':i,'pc':3}},
                          'filesystem':{'output':f'machine-{i:06x}'},'journal':[{'event':'boot'},{'event':'write','identity':i}]})
    base=state(0); raw_bytes=0; compressed_bytes=0; patch_bytes=len(base); compressed_patch_bytes=len(zlib.compress(base)); pages=set(); encode=decode=0.0
    for i in range(count):
        target=state(i); raw_bytes+=len(target); compressed_bytes+=len(zlib.compress(target))
        for offset in range(0,len(target),4096): pages.add(sha256(target[offset:offset+4096].ljust(4096,b'\0')).digest())
        start=time.perf_counter(); d=form_snapshot_delta(base,target); encode+=time.perf_counter()-start
        start=time.perf_counter(); restored=d.reconstruct(base); decode+=time.perf_counter()-start
        assert restored==target
        patch_bytes+=d.encoded_size; compressed_patch_bytes+=72+len(zlib.compress(d.patch))
    return dict(workload='synthetic canonical application-shaped snapshots, not actual native HeadlessOS states',snapshots=count,verified=count,base_bytes=len(base),logical_bytes=raw_bytes,independent_zlib_bytes=compressed_bytes,fixed_page_unique_bytes=len(pages)*4096,structural_delta_bytes=patch_bytes,zlib_structural_delta_bytes=compressed_patch_bytes,form_seconds=encode,reconstruct_seconds=decode)


if __name__=='__main__':
    print(json.dumps(run(),indent=2))
