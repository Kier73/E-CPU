"""FAB-018: recover and advance native M3 application sessions through structural M1."""
from hashlib import sha256
import json
from pathlib import Path
import random
import shutil
import sqlite3
import subprocess
import sys
from time import perf_counter

import pytest

from mailcpu import HeadlessOS, ReplicatedMailboxNode, ReplicatedMailboxStore
from mailcpu.attention import Budget, Offer, machine_scope, plan_attention, verify_plan
from mailcpu.computational_objects import ComputationalObjectStore
from mailcpu.computational_session import ComputationalSessionIntegrityError, ComputationalSessionStore
from mailcpu.computational_transition import (
    ComputationalSessionTransitionAdapter, ComputationalTransitionContract, ComputationalTransitionError,
)
from mailcpu.continuous_session import SessionRejoinAddress
from mailcpu.recovery_lineage import RecoveryLineageAuthority, RecoveryLineageCoordinator
from mailcpu.remote_memory import RemotePageStore
from mailcpu.seed_commit_quorum import SeedCommitMembership
from mailcpu.stream_os_session import (
    OS_STATE_SCHEMA, OS_STEP_INPUT_SCHEMA, OS_TRANSITION_ID, OS_BACKEND_FINGERPRINT,
    OS_INTERPRETATION_FINGERPRINT, HeadlessOSQuorumTransitionBackend,
    encode_headless_step, execute_headless_step, serialize_headless_state, restore_headless_state,
)
from mailcpu.structural_object_store import StructuralObjectStore

NS=sha256(b"fab018-native-structural-fabric").hexdigest()
GENESIS=sha256(b"mailcpu-recovery-lineage-genesis-v1").hexdigest()
ARTIFACT=sha256(b"fab018-native-file-application").hexdigest()
CONTRACT=ComputationalTransitionContract(
    OS_TRANSITION_ID, OS_STATE_SCHEMA, OS_STEP_INPUT_SCHEMA,
    OS_INTERPRETATION_FINGERPRINT, OS_BACKEND_FINGERPRINT,4096,4_194_304,
)


def _backing(root, name):
    """Open the existing native local durable page service."""
    node=ReplicatedMailboxNode(ReplicatedMailboxStore(root/"mailbox.jsonl","local"))
    return RemotePageStore(root/name,node,page_size=4096)


def _store(root, objects, identity):
    """Open an independent native M3 lineage for a canonical fabric machine name."""
    directory=root/"machines"/f"{identity:06x}"
    membership=SeedCommitMembership(f"fab127.{NS}.{identity:06x}",1,("A","B","C"),"A",1,GENESIS)
    authorities={m:RecoveryLineageAuthority(membership,m,directory/"authorities"/f"{m}.jsonl")
                 for m in membership.member_ids}
    return ComputationalSessionStore(
        directory/"sessions",objects,RecoveryLineageCoordinator(membership,authorities),
        artifact_manifest_digest=ARTIFACT,backend_fingerprint=OS_BACKEND_FINGERPRINT,
        state_schema_id=OS_STATE_SCHEMA,state_media_type="application/json",
    )


def _initial(identity, common):
    """Retain actual native private memory and an open descriptor at tick three."""
    data=sha256(identity.to_bytes(3,"big")).digest()
    os=HeadlessOS()
    os.environment.kernel.fs.create_file("/home/shared-data",common)
    pid=os.launch_source(
        "SYSCALL fd open path=/home/program-output mode=w create=true\n"
        "SYSCALL address mmap length=4096\n"
        f"SYSCALL staged mem_write address=$address data=hex:{data.hex()}\n"
        f"SYSCALL copied write_from fd=$fd address=$address size={len(data)}\n"
        "halt\n","native-file-app")
    os.run(3)
    assert os.process(pid).steps==3
    return serialize_headless_state(os),pid,data


def _backend(store,calls,abort=False):
    """Realize a candidate in a disposable interpreter; optionally lose its response."""
    def remote(raw,request,context):
        """Bind the actual session and execute native closed-state continuation."""
        assert context.session_id==store.session_id
        calls.append(context.operation_id)
        script=(
            "import os,sys\n"
            "from mailcpu.stream_os_session import execute_headless_step\n"
            "result=execute_headless_step(sys.stdin.buffer.read(),bytes.fromhex(sys.argv[1]))\n"
            "sys.stdout.buffer.write(result);sys.stdout.buffer.flush()\n"
            "if sys.argv[2]=='abort': os._exit(17)\n"
        )
        return subprocess.run([sys.executable,"-c",script,request.hex(),"abort" if abort else "ok"],
                              input=raw,capture_output=True,check=True,timeout=60,
                              cwd=Path(__file__).resolve().parents[1]).stdout
    return HeadlessOSQuorumTransitionBackend(remote)


def test_native_m3_representation_change_and_attention(tmp_path):
    """Replace raw state representation, reopen M3, and advance selected machines."""
    start=perf_counter()
    common=random.Random(127).randbytes(16384)
    identities=[0,2**24-1,1,0x100001,0x200002,0x400004,0x800008,0xc0000c]
    raw_backing=_backing(tmp_path,"raw-pages")
    raw_objects=ComputationalObjectStore(raw_backing)
    structural_backing=_backing(tmp_path,"structural-pages")
    native=ComputationalObjectStore(structural_backing)
    base,_,_=_initial(0xabcdef,common)
    template=native.put_bytes(base,media_type="application/json")
    catalog_path=tmp_path/"representations.sqlite"
    structural=StructuralObjectStore(structural_backing,catalog_path,base_manifest=template)
    base_pages=structural_backing.page_ids()
    originals={}; exports={}; locators={}; processes={}; payloads={}
    for identity in identities:
        raw,pid,payload=_initial(identity,common)
        source=_store(tmp_path,raw_objects,identity)
        snapshot=source.create_session(raw)
        originals[identity]=snapshot
        exports[identity]=source.export_latest()
        locators[identity]=SessionRejoinAddress.bootstrap(source)
        processes[identity]=pid; payloads[identity]=payload
        represented=structural.put_bytes(raw,media_type="application/json")
        assert represented==snapshot.checkpoint.state_manifest
        assert structural.catalog.get(represented.manifest_digest) is not None
        imported=_store(tmp_path,structural,identity).restore_export(exports[identity])
        assert imported.checkpoint_digest==snapshot.checkpoint_digest and imported.state_bytes==raw
    assert structural_backing.page_ids()==base_pages
    raw_page_bytes=len(raw_backing.page_ids())*4096
    # Remove only the explicitly isolated test backing, after exact alternate
    # representation verification. Production deletion/GC is not implemented.
    shutil.rmtree(raw_backing.root)
    del raw_objects,raw_backing,source,structural
    assert not (tmp_path/"raw-pages").exists()

    # The native attention contract selects one ready application at a time.
    # The vector is an advisory workload reservation, not total host metering.
    demand=Budget(2,3,0,1)
    service={}; pending=set(identities); completed={}; calls=[]
    while pending:
        offers=[]; scopes={}
        for identity in sorted(pending):
            scope=machine_scope(identity,"application")
            # Verify actual native state before exposing the observed revision.
            objects=StructuralObjectStore(_backing(tmp_path,"structural-pages"),catalog_path)
            session=_store(tmp_path,objects,identity)
            current=session.load_latest()
            assert SessionRejoinAddress.bootstrap(session)==locators[identity]
            assert current.checkpoint_digest==originals[identity].checkpoint_digest
            machine=restore_headless_state(current.state_bytes)
            report=machine.process(processes[identity])
            assert report.status=="runnable" and report.steps==3
            assert report.registers["fd"] in machine.environment.kernel.processes[processes[identity]].fds
            assert machine.vm.memories[processes[identity]].read(report.registers["address"],len(payloads[identity]))==payloads[identity]
            scopes[scope]=identity
            offers.append(Offer(scope,current.revision,current.checkpoint_digest,demand))
        epoch=len(completed)
        plan=plan_attention(offers,demand,epoch=epoch,service=service)
        assert verify_plan(plan,offers,demand,epoch=epoch,service=service)
        assert len(plan.grants)==1 and not plan.authoritative
        grant=plan.grants[0]; identity=scopes[grant.scope]
        # Reopen after selection and revalidate the exact observed coordinate.
        objects=StructuralObjectStore(_backing(tmp_path,"structural-pages"),catalog_path)
        store=_store(tmp_path,objects,identity)
        current=store.load_latest()
        assert (current.revision,current.checkpoint_digest)==(grant.revision,grant.evidence)
        request=encode_headless_step(ticks=5)
        args=dict(operation_id="finish",expected_revision=current.revision,
                  expected_checkpoint_digest=current.checkpoint_digest)
        if epoch==0:
            with pytest.raises(ComputationalTransitionError):
                ComputationalSessionTransitionAdapter(store,CONTRACT,_backend(store,calls,abort=True)).apply(request,**args)
            assert store.load_latest().checkpoint_digest==current.checkpoint_digest
        backend=_backend(store,calls)
        adapter=ComputationalSessionTransitionAdapter(store,CONTRACT,backend)
        successor=adapter.apply(request,**args)
        assert successor.revision==2 and successor.state_bytes==execute_headless_step(current.state_bytes,request)
        assert objects.catalog.get(successor.checkpoint.state_manifest.manifest_digest) is not None
        retry=adapter.apply(request,**args)
        assert retry.replayed and retry.checkpoint_digest==successor.checkpoint_digest and backend.remote_calls==1
        restored=restore_headless_state(successor.state_bytes)
        assert restored.process(processes[identity]).status=="exited"
        assert restored.environment.kernel.fs.read_file("/home/program-output")==payloads[identity]
        assert restored.environment.kernel.fs.read_file("/home/shared-data")==common
        assert restored.environment.kernel.journal.verify()
        completed[identity]=successor
        pending.remove(identity)
        for i in range(1,len(grant.scope)+1):
            prefix=grant.scope[:i]; service[prefix]=service.get(prefix,0)+1
        assert not verify_plan(plan,offers,demand,epoch=epoch+1,service=service)
    assert len(calls)==len(identities)+1
    objects=StructuralObjectStore(_backing(tmp_path,"structural-pages"),catalog_path)
    assert objects.page_backing.page_ids()==base_pages
    for identity in identities:
        session=_store(tmp_path,objects,identity)
        observed=session.load_latest()
        assert observed.checkpoint_digest==completed[identity].checkpoint_digest
        assert observed.state_bytes==completed[identity].state_bytes
        assert SessionRejoinAddress.bootstrap(session)==locators[identity]
    # Corruption fails native M3 recovery, without changing the high-water.
    identity=identities[0]
    session=_store(tmp_path,objects,identity)
    manifest=completed[identity].checkpoint.state_manifest
    saved=objects.catalog.get(manifest.manifest_digest)
    before=session.lineage.high_water()
    with sqlite3.connect(catalog_path) as db:
        db.execute("UPDATE delta SET patch=? WHERE manifest=?",(b"[0,null]",manifest.manifest_digest))
    with pytest.raises(ComputationalSessionIntegrityError):
        session.load_latest()
    assert session.lineage.high_water()==before
    with sqlite3.connect(catalog_path) as db:
        db.execute("UPDATE delta SET patch=? WHERE manifest=?",(saved.patch,manifest.manifest_digest))
    assert session.load_latest().checkpoint_digest==completed[identity].checkpoint_digest
    print("FAB018_NATIVE",json.dumps({
        "machines":len(identities),"original_revisions_represented":len(originals),
        "successors_committed":len(completed),"raw_initial_page_bytes":raw_page_bytes,
        "base_page_bytes":len(base_pages)*4096,"catalog_file_bytes":catalog_path.stat().st_size,
        "lineage_and_session_bytes":sum(p.stat().st_size for p in (tmp_path/"machines").rglob("*") if p.is_file()),
        "seconds":perf_counter()-start,
    },sort_keys=True),flush=True)
