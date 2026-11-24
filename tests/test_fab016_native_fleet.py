"""FAB-016 native density trial: real OS sessions behind a sparse observed index."""
from concurrent.futures import ProcessPoolExecutor
from hashlib import sha256
from multiprocessing import get_context
import json
import os
from pathlib import Path
from time import perf_counter

import pytest

from mailcpu import HeadlessOS, ReplicatedMailboxNode, ReplicatedMailboxStore
from mailcpu.computational_objects import ComputationalObjectStore
from mailcpu.computational_session import ComputationalSessionStore
from mailcpu.computational_transition import ComputationalSessionTransitionAdapter, ComputationalTransitionContract
from mailcpu.fabric_head_index import FabricHeadIndex, MachineHead
from mailcpu.recovery_lineage import RecoveryLineageAuthority, RecoveryLineageCoordinator
from mailcpu.remote_memory import RemotePageStore
from mailcpu.seed_commit_quorum import SeedCommitMembership
from mailcpu.stream_os_session import (
    OS_STATE_SCHEMA, OS_STEP_INPUT_SCHEMA, OS_TRANSITION_ID,
    OS_BACKEND_FINGERPRINT, OS_INTERPRETATION_FINGERPRINT,
    HeadlessOSQuorumTransitionBackend, encode_headless_step,
    execute_headless_step, serialize_headless_state, restore_headless_state,
)

NS=sha256(b"fab016-native-density").hexdigest()
GENESIS=sha256(b"mailcpu-recovery-lineage-genesis-v1").hexdigest()
ARTIFACT=sha256(b"fab016-test-native-file-application").hexdigest()
CONTRACT=ComputationalTransitionContract(
    OS_TRANSITION_ID,OS_STATE_SCHEMA,OS_STEP_INPUT_SCHEMA,
    OS_INTERPRETATION_FINGERPRINT,OS_BACKEND_FINGERPRINT,4096,4_194_304,
)


def _page_services(root):
    """Reopen native local CAS services; no remote-replica claim."""
    node=ReplicatedMailboxNode(ReplicatedMailboxStore(root/"mailbox.jsonl","local"))
    state=RemotePageStore(root/"state-pages",node,page_size=4096)
    index=RemotePageStore(root/"index-pages",node,page_size=4096)
    return state,index


def _store(root, backing, identity):
    """Open independent M3 lineage over shared immutable M1 bytes."""
    directory=root/"machines"/f"{identity:06x}"
    membership=SeedCommitMembership(f"fab127.{NS}.{identity:06x}",1,("A","B","C"),"A",1,GENESIS)
    authorities={m:RecoveryLineageAuthority(membership,m,directory/"authorities"/f"{m}.jsonl") for m in membership.member_ids}
    return ComputationalSessionStore(
        directory/"sessions",ComputationalObjectStore(backing,chunk_size=4096),
        RecoveryLineageCoordinator(membership,authorities),
        artifact_manifest_digest=ARTIFACT,backend_fingerprint=OS_BACKEND_FINGERPRINT,
        state_schema_id=OS_STATE_SCHEMA,state_media_type="application/json",
    )


def _head(snapshot):
    """Project already accepted native M3 checkpoint coordinates."""
    return MachineHead(snapshot.revision,snapshot.checkpoint_digest)


def _payload(identity):
    """Construct independent application data, including both address extremes."""
    return identity.to_bytes(3,"big")+sha256(identity.to_bytes(3,"big")).digest()


def _initial(identity):
    """Boot genuine native application with a private memory and file write."""
    payload=_payload(identity)
    machine=HeadlessOS()
    pid=machine.launch_source(
        "SYSCALL fd open path=/home/program-output mode=w create=true\n"
        "SYSCALL address mmap length=4096\n"
        f"SYSCALL staged mem_write address=$address data=hex:{payload.hex()}\n"
        f"SYSCALL copied write_from fd=$fd address=$address size={len(payload)}\n"
        "SYSCALL code exit code=0\n","native-file-app")
    return serialize_headless_state(machine),pid


def _candidate(raw,request):
    """Realize closed-state successor in a disposable process."""
    return os.getpid(),execute_headless_step(raw,request)


def _apply(store, base, request, candidate, operation):
    """Independently validate candidate against exact state and native M3 context."""
    def remote(state, input_bytes, context):
        """Bind a precomputed candidate to the exact selected machine and request."""
        assert state==base.state_bytes and input_bytes==request
        assert context.session_id==store.session_id and context.checkpoint_digest==base.checkpoint_digest
        return candidate
    backend=HeadlessOSQuorumTransitionBackend(remote)
    result=ComputationalSessionTransitionAdapter(store,CONTRACT,backend).apply(
        request,operation_id=operation,expected_revision=base.revision,
        expected_checkpoint_digest=base.checkpoint_digest)
    assert backend.remote_calls==1 and result.revision==base.revision+1
    return result


@pytest.mark.parametrize("count",[8,64])
def test_native_application_density(tmp_path,count):
    """Commit three revisions per machine; realize at most four candidates in flight."""
    start=perf_counter()
    backing,index_backing=_page_services(tmp_path)
    index=FabricHeadIndex(index_backing,NS)
    root=index.empty_root()
    identities=[0,2**24-1]+[(i*2654435761)&0xffffff for i in range(1,count-1)]
    assert len(set(identities))==count
    pids={}; heads=[]; logical_bytes=0
    for identity in identities:
        raw,pids[identity]=_initial(identity)
        created=_store(tmp_path,backing,identity).create_session(raw)
        assert created.revision==1
        heads.append((identity,_head(created)))
        logical_bytes+=len(raw)
    root=index.update(root,heads); initial_root=root
    worker_sets=[]
    for phase,ticks in enumerate((3,10),start=1):
        # Reopen the backing from actual files and replace the worker pool.
        backing,index_backing=_page_services(tmp_path)
        index=FabricHeadIndex(index_backing,NS)
        worker_pids=set()
        request=encode_headless_step(ticks=ticks)
        with ProcessPoolExecutor(max_workers=4,mp_context=get_context("spawn")) as pool:
            for offset in range(0,count,4):
                work=[]
                for identity in identities[offset:offset+4]:
                    store=_store(tmp_path,backing,identity)
                    base=store.load_latest()
                    assert index.lookup(root,identity)==_head(base)
                    work.append((identity,store,base,pool.submit(_candidate,base.state_bytes,request)))
                changes=[]
                for identity,store,base,future in work:
                    worker,candidate=future.result(timeout=120)
                    worker_pids.add(worker); assert worker!=os.getpid()
                    result=_apply(store,base,request,candidate,f"phase-{phase}")
                    changes.append((identity,_head(result)))
                    logical_bytes+=len(result.state_bytes)
                    machine=restore_headless_state(result.state_bytes)
                    report=machine.process(pids[identity])
                    payload=_payload(identity)
                    assert machine.vm.memories[pids[identity]].read(report.registers["address"],len(payload))==payload
                    if phase==1:
                        assert report.status=="runnable" and report.steps==3
                        assert machine.environment.kernel.fs.read_file("/home/program-output")==b""
                        assert report.registers["fd"] in machine.environment.kernel.processes[pids[identity]].fds
                    else:
                        assert report.status=="exited" and report.exit_code==0
                        assert machine.environment.kernel.fs.read_file("/home/program-output")==payload
                root=index.update(root,changes)
        assert 1<=len(worker_pids)<=4
        worker_sets.append(sorted(worker_pids))
    backing,index_backing=_page_services(tmp_path)
    index=FabricHeadIndex(index_backing,NS)
    for identity in identities:
        recovered=_store(tmp_path,backing,identity).load_latest()
        assert recovered.revision==3 and index.lookup(root,identity)==_head(recovered)
        assert index.lookup(initial_root,identity).revision==1
        assert index.lookup(initial_root,identity)!=_head(recovered)
        machine=restore_headless_state(recovered.state_bytes)
        assert machine.environment.kernel.fs.read_file("/home/program-output")==_payload(identity)
        assert machine.environment.kernel.journal.verify()
    state_files=list((tmp_path/"state-pages").glob("*.page"))
    index_files=list((tmp_path/"index-pages").glob("*.page"))
    assert state_files and index_files
    report={"machines":count,"committed_revisions":count*3,"candidate_workers":worker_sets,
            "max_in_flight":4,"logical_snapshot_bytes":logical_bytes,
            "unique_state_page_bytes":sum(f.stat().st_size for f in state_files),
            "retained_index_page_bytes":sum(f.stat().st_size for f in index_files),
            "lineage_and_session_file_bytes":sum(f.stat().st_size for f in (tmp_path/"machines").rglob("*") if f.is_file()),
            "seconds":perf_counter()-start}
    print("FAB016_NATIVE",json.dumps(report,sort_keys=True),flush=True)
