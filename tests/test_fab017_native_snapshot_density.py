"""Measure real native HeadlessOS snapshot sharing over M1, not a new authority."""
from hashlib import sha256
import json
import random
import struct
import time
import zlib
import pytest
from mailcpu import HeadlessOS
from mailcpu.computational_objects import ComputationalObjectStore
from mailcpu.snapshot_delta import SnapshotDelta, form_snapshot_delta
from mailcpu.stream_os_session import serialize_headless_state, restore_headless_state, execute_headless_step, encode_headless_step

HEADER=struct.Struct("!32s32sQ")


class Pages:
    """Test backing that counts distinct native M1 page payloads."""
    page_size=4096

    def __init__(self):
        """Initialize a local immutable page map."""
        self.data={}

    def put_page(self,raw):
        """Store one padded native page under SHA-256."""
        assert len(raw)==self.page_size
        key=sha256(raw).hexdigest()
        assert self.data.setdefault(key,raw)==raw
        return key

    def get_page(self,key):
        """Resolve exactly one stored page."""
        return self.data[key]


def _initial(i,shared):
    """Build a distinct native process paused with open descriptor and private data."""
    payload=sha256(i.to_bytes(3,"big")).digest()
    machine=HeadlessOS()
    if shared:
        machine.environment.kernel.fs.create_file("/home/shared-data",shared)
    pid=machine.launch_source(
        "SYSCALL fd open path=/home/program-output mode=w create=true\n"
        "SYSCALL address mmap length=4096\n"
        f"SYSCALL staged mem_write address=$address data=hex:{payload.hex()}\n"
        f"SYSCALL copied write_from fd=$fd address=$address size={len(payload)}\n"
        "halt\n","native-file-app")
    machine.run(3)
    assert machine.process(pid).steps==3
    return serialize_headless_state(machine),pid,payload


@pytest.mark.parametrize("count,shared_size",[(8,0),(64,16384)])
def test_native_snapshot_density(count,shared_size):
    """Measure native snapshots, packed deltas, and independently continued OS state."""
    shared=random.Random(127).randbytes(shared_size)
    original_pages=Pages(); packed_pages=Pages()
    raw_store=ComputationalObjectStore(original_pages)
    packed_store=ComputationalObjectStore(packed_pages)
    states=[_initial(i,shared) for i in range(count)]
    base=states[0][0]
    raw_manifests=[raw_store.put_bytes(raw) for raw,_,_ in states]
    base_manifest=packed_store.put_bytes(base)
    start=time.perf_counter()
    bundle=bytearray(); extents=[]
    for raw,_,_ in states:
        delta=form_snapshot_delta(base,raw)
        wire=HEADER.pack(bytes.fromhex(delta.base_digest),bytes.fromhex(delta.target_digest),delta.target_size)+delta.patch
        assert len(wire)==delta.encoded_size
        extents.append((len(bundle),len(wire)))
        bundle.extend(wire)
    form_time=time.perf_counter()-start
    bundle_manifest=packed_store.put_bytes(bytes(bundle))
    assert packed_store.verify(base_manifest) and packed_store.verify(bundle_manifest)
    restored_base=packed_store.read_bytes(base_manifest)
    start=time.perf_counter()
    for (raw,pid,payload),manifest,(offset,length) in zip(states,raw_manifests,extents):
        encoded=packed_store.read_range(bundle_manifest,offset,length)
        b,t,size=HEADER.unpack_from(encoded)
        reconstructed=SnapshotDelta(b.hex(),t.hex(),size,encoded[HEADER.size:]).reconstruct(restored_base)
        assert reconstructed==raw_store.read_bytes(manifest)==raw
        machine=restore_headless_state(reconstructed)
        report=machine.process(pid)
        assert machine.vm.memories[pid].read(report.registers["address"],len(payload))==payload
        assert report.registers["fd"] in machine.environment.kernel.processes[pid].fds
        request=encode_headless_step(ticks=10)
        successor=execute_headless_step(reconstructed,request)
        assert successor==execute_headless_step(raw,request)
        final=restore_headless_state(successor)
        assert final.environment.kernel.fs.read_file("/home/program-output")==payload
        assert final.process(pid).status=="exited"
        assert final.environment.kernel.journal.verify()
    print("FAB017_NATIVE",json.dumps({
        "machines":count,"shared_file_bytes":shared_size,
        "raw_logical_bytes":sum(len(raw) for raw,_,_ in states),
        "independent_zlib_bytes":sum(len(zlib.compress(raw)) for raw,_,_ in states),
        "native_M1_unique_raw_page_bytes":len(original_pages.data)*4096,
        "native_M1_unique_packed_page_bytes":len(packed_pages.data)*4096,
        "raw_manifest_bytes":sum(len(m.canonical_bytes()) for m in raw_manifests),
        "packed_manifest_bytes":len(base_manifest.canonical_bytes())+len(bundle_manifest.canonical_bytes()),
        "extent_table_bytes_if_u64_pairs":16*len(extents),
        "structural_payload_bytes":len(base)+len(bundle),
        "form_seconds":form_time,"reconstruct_verify_continue_seconds":time.perf_counter()-start,
    },sort_keys=True),flush=True)
