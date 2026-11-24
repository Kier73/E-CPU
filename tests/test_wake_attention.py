"""Native durable wake events, verified HeadlessOS successors and acknowledgement recovery."""
from dataclasses import replace
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
from time import perf_counter

import pytest

from mailcpu import HeadlessOS
from mailcpu.attention import Budget
from mailcpu.computational_objects import ComputationalObjectStore
from mailcpu.computational_session import ComputationalSessionStore
from mailcpu.computational_transition import ComputationalSessionTransitionAdapter, ComputationalTransitionContract
from mailcpu.model import Message
from mailcpu.recovery_lineage import RecoveryLineageAuthority, RecoveryLineageCoordinator
from mailcpu.replicated_mailbox import ReplicatedMailboxError, ReplicatedMailboxStore
from mailcpu.seed_commit_quorum import SeedCommitMembership
from mailcpu.stream_os_session import (
    OS_STATE_SCHEMA, OS_STEP_INPUT_SCHEMA, OS_TRANSITION_ID, OS_BACKEND_FINGERPRINT,
    OS_INTERPRETATION_FINGERPRINT, HeadlessOSQuorumTransitionBackend,
    encode_headless_step, execute_headless_step, serialize_headless_state, restore_headless_state,
)
from mailcpu.wake_attention import WakeController, WakeEvent


def digest(raw):
    """Derive an exact fixture identity."""
    return sha256(raw).hexdigest()


NS=digest(b"fab021-native-wake")
DEMAND=Budget(2,3,1,1)
CONTRACT=ComputationalTransitionContract(
    OS_TRANSITION_ID,OS_STATE_SCHEMA,OS_STEP_INPUT_SCHEMA,OS_INTERPRETATION_FINGERPRINT,
    OS_BACKEND_FINGERPRINT,4096,4_194_304,
)


class Pages:
    """Native fixed-page interface with immutable bytes and exact read accounting."""
    page_size=4096

    def __init__(self):
        """Retain page data for the local integration trial."""
        self.data={}
        self.reads=0

    def put_page(self,raw):
        """Store a native padded page under its exact identity."""
        assert len(raw)==4096
        key=digest(raw)
        assert self.data.setdefault(key,raw)==raw
        return key

    def get_page(self,key):
        """Count each native M1 page read."""
        self.reads+=1
        return self.data[key]


def store(root, pages, identity):
    """Use the existing native M3 session and three independent local journals."""
    name=f"fab127.{NS}.{identity:06x}"
    directory=root/name
    membership=SeedCommitMembership(name,1,("A","B","C"),"A",1,
                                    digest(b"mailcpu-recovery-lineage-genesis-v1"))
    authorities={m:RecoveryLineageAuthority(membership,m,directory/"authorities"/f"{m}.jsonl")
                 for m in membership.member_ids}
    return ComputationalSessionStore(directory/"sessions",ComputationalObjectStore(pages),
                RecoveryLineageCoordinator(membership,authorities),
                artifact_manifest_digest=digest(b"native-application-fixture"),
                backend_fingerprint=OS_BACKEND_FINGERPRINT,
                state_schema_id=OS_STATE_SCHEMA,state_media_type="application/json")


def test_native_enqueue_once(tmp_path):
    """Preserve exact operation identity through abrupt producer exit and consumption."""
    path=tmp_path/"mailbox.jsonl"
    script='''import os,sys
from mailcpu.model import Message
from mailcpu.replicated_mailbox import ReplicatedMailboxStore
m=ReplicatedMailboxStore(sys.argv[1],"local")
m.send_once("wake",Message(sender="local",op="wake",body=("payload",)),operation_id="stable")
os._exit(17)
'''
    result=subprocess.run([sys.executable,"-c",script,str(path)],check=False,
                          cwd=Path(__file__).resolve().parents[1])
    assert result.returncode==17
    m=ReplicatedMailboxStore(path,"local")
    original=m.list("wake")[0]
    message=Message(sender="local",op="wake",body=("payload",))
    assert m.send_once("wake",message,operation_id="stable")==original
    assert m.pending("wake")==1
    with pytest.raises(ReplicatedMailboxError,match="operation identity conflict"):
        m.send_once("wake",replace(message,body=("changed",)),operation_id="stable")
    assert m.consume(original,operation_id="ack")
    m=ReplicatedMailboxStore(path,"local")
    assert m.send_once("wake",message,operation_id="stable")==original
    assert m.pending()==0 and m.verify()


def test_wake_codec():
    """Refuse noncanonical and out-of-space wake intentions."""
    e=WakeEvent(NS,0xffffff,1,digest(b"base"),CONTRACT.digest,b"input",DEMAND)
    assert WakeEvent.decode(e.canonical())==e
    for bad in (e.canonical()+b" ",e.canonical().replace(b"[1,",b"[true,",1),b"{}"):
        with pytest.raises(ValueError):
            WakeEvent.decode(bad)
    with pytest.raises(ValueError):
        replace(e,identity=2**24)


class InterruptedAck(ReplicatedMailboxStore):
    """Inject loss after child publication but before acknowledging the parent."""

    def consume(self,message,operation_id=None):
        """Leave the original durable event available for exact recovery."""
        raise RuntimeError("injected acknowledgement interruption")


def test_native_endogenous_attention(tmp_path):
    """Actual runnable application successors generate bounded wake events until exit."""
    start=perf_counter()
    ids=(0,1,0x123456,0xffffff,2,3,4,5)
    active=set(ids[:4]); dormant=set(ids[4:])
    pages={i:Pages() for i in ids}
    sessions={i:store(tmp_path,pages[i],i) for i in ids}
    initial={}; pids={}; calls=[]
    for i,session in sessions.items():
        machine=HeadlessOS()
        pids[i]=machine.launch_source(
            "set one 1\nadd value value one\nadd value value one\n"
            "add value value one\nadd value value one\nhalt\n",
            "endogenous-application",initial_registers={"value":i})
        initial[i]=session.create_session(serialize_headless_state(machine))

    def resolve(i):
        """Resolve only requested sessions and independently realize native candidates."""
        assert i in active
        session=sessions[i]
        def realize(raw,request,context):
            """Use the original native execution path in a disposable process."""
            assert context.session_id==session.session_id
            calls.append(i)
            script=("import sys\nfrom mailcpu.stream_os_session import execute_headless_step\n"
                    "sys.stdout.buffer.write(execute_headless_step(sys.stdin.buffer.read(),bytes.fromhex(sys.argv[1])))")
            return subprocess.run([sys.executable,"-c",script,request.hex()],input=raw,
                                  capture_output=True,check=True,timeout=60,
                                  cwd=Path(__file__).resolve().parents[1]).stdout
        return session,ComputationalSessionTransitionAdapter(session,CONTRACT,HeadlessOSQuorumTransitionBackend(realize))

    def followup(event,result):
        """Derive a new exact intention from the actual verified process state."""
        machine=restore_headless_state(result.state_bytes)
        report=machine.process(pids[event.identity])
        if report.status=="runnable":
            return WakeEvent(NS,event.identity,result.revision,result.checkpoint_digest,
                    CONTRACT.digest,encode_headless_step(ticks=machine.vm.scheduler.tick+2),DEMAND)
        assert report.status=="exited"
        return None

    path=tmp_path/"wake.jsonl"
    mailbox=InterruptedAck(path,"local")
    controller=WakeController(NS,mailbox,resolve,followup)
    original_events={}
    for i in sorted(active):
        e=WakeEvent(NS,i,initial[i].revision,initial[i].checkpoint_digest,
                    CONTRACT.digest,encode_headless_step(ticks=2),DEMAND)
        original_events[i]=e
        controller.publish(e); controller.publish(e)
    assert mailbox.pending(controller.addr)==len(active)
    for page in pages.values():
        page.reads=0
    with pytest.raises(RuntimeError,match="acknowledgement interruption"):
        controller.run_epoch(DEMAND,epoch=0)
    assert len(calls)==1 and mailbox.pending(controller.addr)==len(active)+1
    assert all(pages[i].reads==0 for i in dormant)
    # Reopen durable mailbox and all native lineage journals. The local page
    # backing remains resident for this integration fixture.
    sessions={i:store(tmp_path,pages[i],i) for i in ids}
    mailbox=ReplicatedMailboxStore(path,"local")
    controller=WakeController(NS,mailbox,resolve,followup)
    result=controller.run_epoch(DEMAND,epoch=1)
    assert len(result["completed"])==1 and result["completed"][0][2] is True
    assert len(calls)==1 and mailbox.pending(controller.addr)==len(active)
    epochs=2; completed=1
    while mailbox.pending(controller.addr):
        assert epochs<32
        result=controller.run_epoch(Budget(4,6,2,2),epoch=epochs)
        assert not result["stale"]
        completed+=len(result["completed"]); epochs+=1
    assert len(calls)==completed==len(active)*3
    assert all(pages[i].reads==0 for i in dormant)
    for i in active:
        current=sessions[i].load_latest()
        assert current.revision==4
        report=restore_headless_state(current.state_bytes).process(pids[i])
        assert report.status=="exited" and report.registers["value"]==i+4
        controller.publish(original_events[i])
    assert mailbox.pending(controller.addr)==0 and mailbox.verify()
    # A different intention based on an old head is not silently rebound.
    stale=replace(original_events[0],payload=encode_headless_step(ticks=3))
    controller.publish(stale)
    prior_calls=len(calls); prior_reads=pages[0].reads
    result=controller.run_epoch(DEMAND,epoch=epochs)
    assert result["stale"]==(stale.event_id,) and result["selected"]==0
    assert len(calls)==prior_calls and pages[0].reads==prior_reads
    assert mailbox.pending(controller.addr)==1
    print("FAB021_NATIVE",json.dumps({
        "actual_native_sessions":len(ids),"active_native_sessions":len(active),
        "dormant_native_sessions":len(dormant),"successor_commits":completed,
        "native_candidate_calls":len(calls),"acknowledgement_replays":1,
        "dormant_payload_reads":sum(pages[i].reads for i in dormant),
        "mailbox_journal_bytes":path.stat().st_size,"seconds":perf_counter()-start,
    },sort_keys=True),flush=True)
