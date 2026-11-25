"""Single-owner local checkpoint coordinator for two independent full-space trials."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time


def digest(path):
    """Hash a bounded-memory stream of file bytes."""
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def syncdir(root):
    """Persist local directory updates."""
    fd = os.open(root, os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def record(root, name, scope, command, size, fail=False, must_exist=False):
    """Read a committed contribution or stage and publish a new one.

    A receipt is the publication marker, written only after data fsync and
    rename. One trusted coordinator owns the directory; no distributed CAS.
    """
    data, receipt = root/(name+'.bin'), root/(name+'.json')
    stage, marker = root/(name+'.stage'), root/(name+'.receipt.stage')
    if receipt.exists():
        r = json.loads(receipt.read_text())
        if r['scope'] != scope or data.stat().st_size != size or digest(data) != r['digest']:
            raise ValueError('committed record differs: '+name)
        return r, True
    if must_exist:
        raise ValueError('required committed record absent: '+name)
    for p in (data, stage, marker):
        p.unlink(missing_ok=True)
    proc = subprocess.run(command+[str(stage),str(int(fail))], capture_output=True, text=True)
    if fail:
        if proc.returncode != 17 or receipt.exists() or data.exists() or not stage.exists():
            raise RuntimeError('failure injection differs: '+proc.stderr)
        return None, False
    if proc.returncode:
        raise RuntimeError('worker refused: '+proc.stderr+' '+proc.stdout)
    if stage.stat().st_size != size:
        raise ValueError('staged extent differs')
    r = dict(scope=scope,digest=digest(stage),metrics=json.loads(proc.stdout))
    os.replace(stage,data); syncdir(root)
    with marker.open('x') as f:
        json.dump(r,f,sort_keys=True,separators=(',',':')); f.flush(); os.fsync(f.fileno())
    os.replace(marker,receipt); syncdir(root)
    return r, False


def fleet(root,exe,bits,shards,workers,phase,interrupt):
    """Keep every shard independently committed; restart only unfinished work."""
    n=1<<bits; root.mkdir(exist_ok=True,parents=True)
    started=time.perf_counter(); exe_id=digest(exe)
    def one(i):
        """Realize one disjoint identity interval, bound to its predecessor."""
        lo,hi=n*i//shards,n*(i+1)//shards; size=(hi-lo)*128
        base=f'initial-{i:03d}'; final=f'final-{i:03d}'
        scope=dict(schema=1,kind='fleet-initial',exe=exe_id,lo=lo,hi=hi)
        prev,reused=record(root,base,scope,[str(exe),'init',str(lo),str(hi),'-'],size,must_exist=phase!='init')
        if phase=='init': return prev,reused
        scope=dict(schema=1,kind='fleet-final',exe=exe_id,lo=lo,hi=hi,predecessor=prev['digest'])
        if phase=='verify':
            p=root/(final+'.bin'); r=json.loads((root/(final+'.json')).read_text())
            if r['scope']!=scope or p.stat().st_size!=size or digest(p)!=r['digest']:
                raise ValueError('final record differs')
            result=subprocess.run([str(exe),'verify',str(lo),str(hi),str(p),'-','0'],capture_output=True,text=True,check=True)
            return dict(metrics=json.loads(result.stdout),digest=r['digest']),True
        return record(root,final,scope,[str(exe),'advance',str(lo),str(hi),str(root/(base+'.bin'))],size,interrupt and i==shards//2)
    results=[]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        # Stop dispatch after the batch containing the injected failure; completed
        # siblings are already published and will be reused on restart.
        for start in range(0,shards,workers):
            batch=list(pool.map(one,range(start,min(start+workers,shards))))
            results.extend(batch)
            if any(r is None for r,_ in batch): break
    good=[r for r,_ in results if r is not None]
    report=dict(phase=phase,machines=n,shards=shards,committed=len(good),reused=sum(reused for r,reused in results if r is not None),failed=sum(r is None for r,_ in results),new_commits=sum(r is not None and not reused for r,reused in results),seconds=time.perf_counter()-started,metrics=[r['metrics'] for r in good],digests=[r['digest'] for r in good])
    for key in ('instructions','checksum','debits'):
        report[key]=sum(r['metrics'][key] for r in good)
    return report


def graph(root,exe,bits,workers,interrupt):
    """Continue a data-dependent sequence of immutable pointer-jump layers."""
    n=1<<bits; size=n*8; root.mkdir(exist_ok=True,parents=True); started=time.perf_counter()
    scope=dict(schema=1,kind='weighted-forest',exe=digest(exe),bits=bits)
    prev,reused=record(root,'layer-000',scope,[str(exe),'init',str(bits),str(workers),'-'],size)
    reports=[dict(layer=0,reused=reused,**prev['metrics'])]; failed=0
    for layer in range(1,bits+1):
        if prev['metrics']['unresolved']==0: break
        scope=dict(schema=1,kind='jump',exe=scope['exe'],bits=bits,layer=layer,predecessor=prev['digest'])
        name=f'layer-{layer:03d}'
        current,reused=record(root,name,scope,[str(exe),'step',str(bits),str(workers),str(root/f'layer-{layer-1:03d}.bin')],size,interrupt and layer==min(5,bits-1))
        if current is None:
            failed=1; break
        reports.append(dict(layer=layer,reused=reused,**current['metrics'])); prev=current
    elapsed=time.perf_counter()-started
    final=None
    if not failed:
        if prev['metrics']['unresolved']!=0: raise ValueError('unresolved after bounded layers')
        p=subprocess.run([str(exe),'verify',str(bits),str(workers),str(root/'layer-000.bin'),str(root/f'layer-{reports[-1]["layer"]:03d}.bin'),'0'],capture_output=True,text=True,check=True)
        final=json.loads(p.stdout)
    return dict(nodes=n,layers=len(reports)-1,failed=failed,reused=sum(r['reused'] for r in reports),new_commits=sum(not r['reused'] for r in reports),seconds=elapsed,active_updates=sum(r['active'] for r in reports),layer_scans=(len(reports)-1)*n,final_digest=prev['digest'],oracle=final,reports=reports)


def main():
    """Expose explicit phases for fresh process recovery and reproducibility."""
    p=argparse.ArgumentParser();p.add_argument('kind',choices=['fleet','graph']);p.add_argument('root',type=Path);p.add_argument('exe',type=Path);p.add_argument('--bits',type=int,default=24);p.add_argument('--workers',type=int,default=4);p.add_argument('--shards',type=int,default=16);p.add_argument('--phase',choices=['init','advance','verify'],default='advance');p.add_argument('--interrupt',action='store_true');a=p.parse_args()
    if not 4<=a.bits<=24 or not 1<=a.workers<=16 or not 1<=a.shards<=min(1<<(a.bits-1),256):p.error('invalid geometry')
    r=(fleet(a.root,a.exe.resolve(),a.bits,a.shards,a.workers,a.phase,a.interrupt) if a.kind=='fleet' else graph(a.root,a.exe.resolve(),a.bits,a.workers,a.interrupt))
    print(json.dumps(r,indent=2));return 17 if r['failed'] else 0


if __name__=='__main__':
    raise SystemExit(main())
