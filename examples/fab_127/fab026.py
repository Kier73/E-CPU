"""FAB-026: layered exact dense contraction across a 24-bit logical fabric.
Local subprocess workers own disjoint output rows; immutable shard records.
No physical network or native M3 authority is implied.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

# The worker is a separate process; one BLAS thread per assigned shard.
os.environ['OPENBLAS_NUM_THREADS'] = '1'
os.environ['OMP_NUM_THREADS'] = '1'
import numpy as np


def digest(raw):
    """Return SHA-256 over exact bytes."""
    return hashlib.sha256(raw).hexdigest()


def canonical(obj):
    """Encode deterministic receipt metadata."""
    return json.dumps(obj, sort_keys=True, separators=(',', ':')).encode()


def publish(path, body):
    """Publish a complete immutable local record through fsync and atomic rename."""
    temp = path.with_name(path.name + f'.tmp.{os.getpid()}')
    with temp.open('xb') as f:
        f.write(body)
        f.flush()
        os.fsync(f.fileno())
    # Single coordinator never assigns the same live shard twice.
    if path.exists():
        raise ValueError('shard already published')
    os.replace(temp, path)
    fd = os.open(path.parent, os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def geometry(n, layers, workers, layer, shard):
    """Partition the dense summation and output rows without overlap."""
    return (n*layer//layers, n*(layer+1)//layers, n*shard//workers, n*(shard+1)//workers)


def shard_path(root, layer, shard):
    """Address one immutable contribution by layer and row partition."""
    return root / f'layer-{layer:03d}-shard-{shard:03d}.bin'


def worker(root, n, layers, workers, layer, shard, identity, fail):
    """Compute all assigned output coordinate contributions and publish a receipt."""
    a = np.load(root/'a.npy', mmap_mode='r', allow_pickle=False)
    b = np.load(root/'b.npy', mmap_mode='r', allow_pickle=False)
    k0,k1,r0,r1 = geometry(n,layers,workers,layer,shard)
    t = time.perf_counter()
    out = (a[r0:r1,k0:k1].astype(np.float32) @ b[k0:k1,:].astype(np.float32)).astype('<i4')
    elapsed = time.perf_counter()-t
    if fail:
        os._exit(17)
    raw = out.tobytes(order='C')
    header = {'schema':1,'identity':identity,'n':n,'layers':layers,'workers':workers,
              'layer':layer,'shard':shard,'geometry':[k0,k1,r0,r1], 'digest':digest(raw)}
    publish(shard_path(root,layer,shard), canonical(header)+b'\n'+raw)
    print(json.dumps({'layer':layer,'shard':shard,'pid':os.getpid(),'compute_seconds':elapsed}),flush=True)


def read_shard(root,n,layers,workers,layer,shard,identity):
    """Validate identity, extent, partition scope and exact stored payload."""
    k0,k1,r0,r1=geometry(n,layers,workers,layer,shard)
    with shard_path(root,layer,shard).open('rb') as f:
        h=f.readline(4096)
        raw=f.read((r1-r0)*n*4+1)
    expected={'schema':1,'identity':identity,'n':n,'layers':layers,'workers':workers,
              'layer':layer,'shard':shard,'geometry':[k0,k1,r0,r1],'digest':digest(raw)}
    if h!=canonical(expected)+b'\n' or len(raw)!=(r1-r0)*n*4:
        raise ValueError('shard receipt differs')
    data=np.frombuffer(raw,dtype='<i4').reshape(r1-r0,n)
    if np.max(np.abs(data.astype(np.int64))) > (k1-k0)*49:
        raise ValueError('shard value exceeds exact arithmetic domain')
    return r0,r1,data


def run(root,n,layers,workers,resume=False):
    """Measure dense layered work, retry one failed shard, and verify full output."""
    if not (2<=n<=4096 and 1<=layers<=n and 1<=workers<=min(n,16)):
        raise ValueError('invalid geometry')
    root=Path(root)
    if not resume:
        root.mkdir(parents=True,exist_ok=False)
        rng=np.random.default_rng(127)
        for name in ('a','b'):
            np.save(root/f'{name}.npy',rng.integers(-7,8,(n,n),dtype=np.int8),allow_pickle=False)
        descriptor={'n':n,'layers':layers,'workers':workers,'inputs':{name:digest((root/f'{name}.npy').read_bytes()) for name in ('a','b')}}
        publish(root/'input.json',canonical(descriptor))
    descriptor={'n':n,'layers':layers,'workers':workers,'inputs':{name:digest((root/f'{name}.npy').read_bytes()) for name in ('a','b')}}
    if (root/'input.json').read_bytes()!=canonical(descriptor):
        raise ValueError('input identity differs')
    identity=digest(canonical(descriptor))
    result=np.zeros((n,n),dtype=np.int32)
    started=time.perf_counter(); calls=0; failed=0; reused=0; attempted_macs=0; records=[]; worker_log=[]
    script=str(Path(__file__).resolve())
    for layer in range(layers):
        jobs={}
        for shard in range(workers):
            if shard_path(root,layer,shard).exists():
                read_shard(root,n,layers,workers,layer,shard,identity); reused+=1; continue
            inject=not resume and layer==layers//2 and shard==workers-1
            args=[sys.executable,script,'worker',str(root),str(n),str(layers),str(workers),str(layer),str(shard),identity,str(int(inject))]
            jobs[shard]=(subprocess.Popen(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True),inject)
            k0,k1,r0,r1=geometry(n,layers,workers,layer,shard)
            attempted_macs+=(k1-k0)*(r1-r0)*n; calls+=1
        for shard,(proc,inject) in jobs.items():
            out,err=proc.communicate()
            if inject:
                if proc.returncode!=17 or shard_path(root,layer,shard).exists():
                    raise RuntimeError('injected failure did not occur before publication')
                failed+=1
                args=[sys.executable,script,'worker',str(root),str(n),str(layers),str(workers),str(layer),str(shard),identity,'0']
                retry=subprocess.run(args,capture_output=True,text=True,check=True)
                worker_log.append(json.loads(retry.stdout)); calls+=1
                k0,k1,r0,r1=geometry(n,layers,workers,layer,shard)
                attempted_macs+=(k1-k0)*(r1-r0)*n
            elif proc.returncode:
                raise RuntimeError(err)
            else:
                worker_log.append(json.loads(out))
        for shard in range(workers):
            r0,r1,out=read_shard(root,n,layers,workers,layer,shard,identity)
            result[r0:r1,:]+=out
        records.append({'layer':layer,'elapsed_seconds':time.perf_counter()-started})
        print(f'layer {layer+1}/{layers} verified stored extents; total elapsed {records[-1]["elapsed_seconds"]:.3f}s',file=sys.stderr,flush=True)
    elapsed=time.perf_counter()-started
    # Independent complete exact reference: different dtype and no layer decomposition.
    # All integer products/sums have magnitude <= 49*n < 2^24, so both paths
    # represent all intermediate and final arithmetic exactly in IEEE binary32/64.
    from threadpoolctl import threadpool_limits
    a=np.load(root/'a.npy',allow_pickle=False); b=np.load(root/'b.npy',allow_pickle=False)
    t=time.perf_counter()
    with threadpool_limits(limits=min(workers,4),user_api='blas'):
        oracle=a.astype(np.float64) @ b.astype(np.float64)
    if not np.array_equal(oracle,result):
        raise AssertionError('full reference differs')
    reference=time.perf_counter()-t
    t=time.perf_counter(); rng=np.random.default_rng(73); sample=min(n*n,4096)
    for index in rng.choice(n*n,sample,replace=False):
        row,col=divmod(int(index),n)
        literal=int(np.dot(a[row,:].astype(np.int64),b[:,col].astype(np.int64)))
        if literal!=int(result[row,col]): raise AssertionError('literal dot differs')
    literal_time=time.perf_counter()-t
    report={'dimension':n,'logical_coordinates':n*n,'layers':layers,'layer_coordinate_realizations':layers*n*n,
            'workers_per_layer':workers,'distinct_worker_processes':len({x['pid'] for x in worker_log})+failed,
            'worker_invocations':calls,'failed_before_publication':failed,'reused_shards':reused,
            'committed_shards':layers*workers,'logical_multiply_accumulates':n**3,'attempted_multiply_accumulates':attempted_macs,
            'full_exact_reference_matches':n*n,'literal_dot_checks':sample,'realization_seconds':elapsed,
            'full_reference_seconds':reference,'literal_check_seconds':literal_time,'result_sha256':digest(result.astype('<i4',copy=False).tobytes()),
            'result_sum':int(result.sum(dtype=np.int64)),'shard_storage_bytes':sum(p.stat().st_size for p in root.glob('layer-*.bin')),
            'layer_timings':records,'worker_log':worker_log,'input_identity':identity,'resume':resume}
    return report


if __name__=='__main__':
    if sys.argv[1]=='worker':
        _,_,root,n,layers,workers,layer,shard,identity,fail=sys.argv
        worker(Path(root),int(n),int(layers),int(workers),int(layer),int(shard),identity,int(fail))
    else:
        p=argparse.ArgumentParser();p.add_argument('root');p.add_argument('--n',type=int,default=4096);p.add_argument('--layers',type=int,default=8);p.add_argument('--workers',type=int,default=4);p.add_argument('--resume',action='store_true');args=p.parse_args()
        print(json.dumps(run(args.root,args.n,args.layers,args.workers,args.resume),indent=2))
