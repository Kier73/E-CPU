"""FAB-015: canonical 127/8 identities and native M3 application continuation."""
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import random
import subprocess
import sys

import pytest

from mailcpu.fabric_identity import FabricMachineAddress, pack_ipv4, unpack_ipv4
from mailcpu import HeadlessOS, ReplicatedMailboxNode, ReplicatedMailboxStore
from mailcpu.computational_objects import ComputationalObjectStore
from mailcpu.computational_session import ComputationalSessionStore, ComputationalSessionConflictError
from mailcpu.computational_transition import (
    ComputationalSessionTransitionAdapter, ComputationalTransitionContract, ComputationalTransitionError,
)
from mailcpu.continuous_session import SessionRejoinAddress
from mailcpu.recovery_lineage import RecoveryLineageAuthority, RecoveryLineageCoordinator
from mailcpu.remote_memory import RemotePageStore
from mailcpu.seed_commit_quorum import SeedCommitMembership
from mailcpu.stream_os_session import (
    OS_STATE_SCHEMA, OS_STEP_INPUT_SCHEMA, OS_TRANSITION_ID,
    OS_BACKEND_FINGERPRINT, OS_INTERPRETATION_FINGERPRINT,
    HeadlessOSQuorumTransitionBackend, encode_headless_step,
    serialize_headless_state, restore_headless_state, execute_headless_step,
    OS_QUANTUM_INPUT_SCHEMA, OS_QUANTUM_TRANSITION_ID,
    OS_QUANTUM_BACKEND_FINGERPRINT, OS_QUANTUM_INTERPRETATION_FINGERPRINT,
    HeadlessOSQuorumQuantumBackend, encode_headless_quantum, execute_headless_quantum,
)

NAMESPACE = sha256(b"lab-fabric").hexdigest()
GENESIS = sha256(b"mailcpu-recovery-lineage-genesis-v1").hexdigest()
ARTIFACT = sha256(b"fab015-native-virtual-byte-application-v1").hexdigest()
CONTRACT = ComputationalTransitionContract(
    OS_TRANSITION_ID, OS_STATE_SCHEMA, OS_STEP_INPUT_SCHEMA,
    OS_INTERPRETATION_FINGERPRINT, OS_BACKEND_FINGERPRINT, 4096, 4_194_304,
)


def test_identity():
    """Verify full string and packed-coordinate round trips over seeded addresses."""
    for i in [0,1,255,256,65535,65536,2**24-1]+random.Random(127).sample(range(2**24),65536):
        a=FabricMachineAddress(NAMESPACE,i)
        assert a==FabricMachineAddress.from_ipv4(NAMESPACE,a.ipv4)
        assert a==FabricMachineAddress.from_session_id(a.session_id)
        assert unpack_ipv4(pack_ipv4(i))==i
    assert FabricMachineAddress(NAMESPACE,0).session_id!=FabricMachineAddress('0'*64,0).session_id


@pytest.mark.parametrize("value",["127.00.0.0","127.1","128.0.0.0","127.0.0.256",
                                  "127.0.0.-1","127.０.0.0","127.0.0.0\n"," 127.0.0.0"])
def test_bad_ip(value):
    """Refuse ambiguous textual coordinates and addresses outside the fabric."""
    with pytest.raises(ValueError):
        FabricMachineAddress.from_ipv4(NAMESPACE,value)


@pytest.mark.parametrize("value",[-1,2**24,True,1.0,"1"])
def test_bad_id(value):
    """Reject out-of-range and noninteger coordinates."""
    with pytest.raises(ValueError):
        FabricMachineAddress(NAMESPACE,value)


def test_bad_session():
    """Reject alternate spellings of stable native session identities."""
    for s in [f"fab127.{NAMESPACE}.00000A",f"fab127.{NAMESPACE}.0000000",
              f"fab127.{NAMESPACE}.0",f"fab127.{NAMESPACE}.000000\n"]:
        with pytest.raises(ValueError):
            FabricMachineAddress.from_session_id(s)


def _store(root: Path, address: FabricMachineAddress, *, quantum=False) -> ComputationalSessionStore:
    """Open native durable local CAS and three independently journaled M3 members."""
    # One local page service, shared by machines by immutable content hash.
    # This test does not claim page replication or independent failure domains.
    node = ReplicatedMailboxNode(ReplicatedMailboxStore(root/"mailbox.jsonl", "local"))
    backing = RemotePageStore(root/"pages", node, page_size=4096)
    membership = SeedCommitMembership(address.session_id, 1, ("A","B","C"), "A", 1, GENESIS)
    machine_root = root / "machines" / address.namespace / f"{address.identity:06x}"
    authorities = {member: RecoveryLineageAuthority(
        membership, member, machine_root/"authorities"/f"{member}.jsonl"
    ) for member in membership.member_ids}
    return ComputationalSessionStore(
        machine_root/"sessions", ComputationalObjectStore(backing,chunk_size=4096),
        RecoveryLineageCoordinator(membership,authorities),
        artifact_manifest_digest=ARTIFACT,
        backend_fingerprint=OS_QUANTUM_BACKEND_FINGERPRINT if quantum else OS_BACKEND_FINGERPRINT,
        state_schema_id=OS_STATE_SCHEMA, state_media_type="application/json",
    )


def _initial(payload: bytes):
    """Boot a native application whose file descriptor and mutable page cross a cut."""
    machine=HeadlessOS()
    source=(
        "SYSCALL fd open path=/home/program-output mode=w create=true\n"
        "SYSCALL address mmap length=4096\n"
        f"SYSCALL staged mem_write address=$address data=hex:{payload.hex()}\n"
        f"SYSCALL copied write_from fd=$fd address=$address size={len(payload)}\n"
        "SYSCALL code exit code=0\n"
    )
    pid=machine.launch_source(source,"byte-userland")
    return serialize_headless_state(machine),pid


def _backend(address, calls, *, abort=False, wrong=None, quantum=False):
    """Run native closed-state continuation in a fresh interpreter; optional abrupt loss."""
    def execute(state, request, context):
        """Refuse misrouted work and compute the successor in an independent process."""
        assert context.session_id==address.session_id
        calls.append(context.operation_id)
        if wrong is not None:
            return wrong
        entry = "execute_headless_quantum" if quantum else "execute_headless_step"
        script=(
            "import os,sys\n"
            f"from mailcpu.stream_os_session import {entry}\n"
            f"result={entry}(sys.stdin.buffer.read(),bytes.fromhex(sys.argv[1]))\n"
            "sys.stdout.buffer.write(result);sys.stdout.buffer.flush()\n"
            "if sys.argv[2]=='abort': os._exit(17)\n"
        )
        result=subprocess.run([sys.executable,"-c",script,request.hex(),"abort" if abort else "ok"],
                              input=state,capture_output=True,check=True,timeout=60)
        return result.stdout
    return (HeadlessOSQuorumQuantumBackend if quantum else HeadlessOSQuorumTransitionBackend)(execute)


def _apply(store, backend, base, ticks, operation):
    """Use native transition admission and exact predecessor CAS."""
    adapter=ComputationalSessionTransitionAdapter(store,CONTRACT,backend)
    return adapter.apply(encode_headless_step(ticks=ticks),operation_id=operation,
                         expected_revision=base.revision,
                         expected_checkpoint_digest=base.checkpoint_digest)


def test_independent_machine_application_continuation(tmp_path):
    """Two address extremes retain independent native application state through worker loss."""
    addresses=[FabricMachineAddress(NAMESPACE,i) for i in (0,2**24-1)]
    payloads=[b"machine-zero",b"machine-last"]
    initial,first,locators,pids={}, {}, {}, {}
    for address,payload in zip(addresses,payloads):
        store=_store(tmp_path,address)
        raw,pid=_initial(payload)
        pids[address]=pid
        initial[address]=store.create_session(raw)
        locators[address]=SessionRejoinAddress.bootstrap(store)
        assert address.bind_session(store,locators[address])==locators[address]
        first[address]=_apply(store,_backend(address,[]),initial[address],3,"stage")
        staged=restore_headless_state(first[address].state_bytes)
        report=staged.process(pid)
        assert report.status=="runnable" and report.steps==3
        assert staged.vm.memories[pid].read(report.registers["address"],len(payload))==payload
        assert staged.environment.kernel.fs.read_file("/home/program-output")==b""
        assert report.registers["fd"] in staged.environment.kernel.processes[pid].fds
    a,b=addresses
    with pytest.raises(ValueError,match="identity differ"):
        a.bind_session(_store(tmp_path,b),locators[b])
    with pytest.raises(ValueError,match="scope differs"):
        a.bind_session(_store(tmp_path,a),replace(locators[a],membership_digest="0"*64))

    # Both machine checkpoints are independently reopened from actual files.
    store=_store(tmp_path,a)
    assert a.bind_session(store,locators[a])==locators[a]
    assert store.load_latest().checkpoint_digest==first[a].checkpoint_digest
    assert _store(tmp_path,b).load_latest().checkpoint_digest==first[b].checkpoint_digest
    calls=[]
    with pytest.raises(ComputationalTransitionError):
        _apply(store,_backend(a,calls,abort=True),first[a],10,"finish")
    assert store.load_latest().checkpoint_digest==first[a].checkpoint_digest
    assert _store(tmp_path,b).load_latest().checkpoint_digest==first[b].checkpoint_digest
    # A valid but unrelated OS state cannot stand in for the requested successor.
    with pytest.raises(ComputationalTransitionError):
        _apply(store,_backend(a,calls,wrong=first[b].state_bytes),first[a],10,"finish")
    assert store.load_latest().checkpoint_digest==first[a].checkpoint_digest

    final={}
    for address,payload in zip(reversed(addresses),reversed(payloads)):
        store=_store(tmp_path,address)
        assert address.bind_session(store,locators[address])==locators[address]
        backend=_backend(address,calls)
        final[address]=_apply(store,backend,first[address],10,"finish")
        retry=_apply(store,backend,first[address],10,"finish")
        assert retry.replayed and retry.checkpoint_digest==final[address].checkpoint_digest
        assert backend.remote_calls==1
        with pytest.raises(ComputationalSessionConflictError):
            _apply(store,backend,initial[address],10,"stale")
        assert backend.remote_calls==1
        recovered=_store(tmp_path,address).load_latest()
        assert recovered.revision==3 and recovered.checkpoint_digest==final[address].checkpoint_digest
        os=restore_headless_state(recovered.state_bytes)
        report=os.process(pids[address])
        assert report.status=="exited" and report.exit_code==0
        assert os.environment.kernel.fs.read_file("/home/program-output")==payload
        assert os.vm.memories[pids[address]].read(report.registers["address"],len(payload))==payload
        assert os.environment.kernel.journal.verify()
    assert calls==["finish","finish","finish","finish"]
    assert final[a].checkpoint_digest!=final[b].checkpoint_digest


def test_native_relative_quantum_continues_beyond_legacy_ceiling(tmp_path):
    """Three fresh realizers advance one quorum OS beyond 200 absolute ticks."""
    address=FabricMachineAddress(NAMESPACE,0x812345)
    store=_store(tmp_path,address,quantum=True)
    machine=HeadlessOS()
    pid=machine.launch_source("set value 0\nset one 1\nloop:\nadd value value one\nbranch one loop\n","continuous")
    base=store.create_session(serialize_headless_state(machine))
    expected=SessionRejoinAddress.bootstrap(store)
    contract=ComputationalTransitionContract(
        OS_QUANTUM_TRANSITION_ID,OS_STATE_SCHEMA,OS_QUANTUM_INPUT_SCHEMA,
        OS_QUANTUM_INTERPRETATION_FINGERPRINT,OS_QUANTUM_BACKEND_FINGERPRINT,
        4096,4_194_304,
    )
    calls=[]
    for epoch in range(1,4):
        store=_store(tmp_path,address,quantum=True)
        assert address.bind_session(store,expected)==expected
        backend=_backend(address,calls,quantum=True)
        adapter=ComputationalSessionTransitionAdapter(store,contract,backend)
        if epoch==1:
            with pytest.raises(ComputationalTransitionError,match="schema differs"):
                adapter.apply(encode_headless_step(ticks=100),operation_id="legacy",
                              expected_revision=base.revision,expected_checkpoint_digest=base.checkpoint_digest)
            assert backend.remote_calls==0
        base=adapter.apply(encode_headless_quantum(ticks=100),operation_id=f"epoch-{epoch}",
                           expected_revision=base.revision,expected_checkpoint_digest=base.checkpoint_digest)
        restored=restore_headless_state(base.state_bytes)
        assert restored.vm.scheduler.tick==epoch*100
        assert restored.process(pid).registers["value"]==epoch*50-1
        assert restored.process(pid).status=="runnable"
        assert base.revision==epoch+1
    assert calls==["epoch-1","epoch-2","epoch-3"]
    assert _store(tmp_path,address,quantum=True).load_latest().checkpoint_digest==base.checkpoint_digest
    with pytest.raises(ComputationalTransitionError,match="schema differs"):
        execute_headless_step(base.state_bytes,encode_headless_quantum(ticks=1))
    with pytest.raises(ComputationalTransitionError,match="schema differs"):
        execute_headless_quantum(base.state_bytes,encode_headless_step(ticks=1))


def test_terminal_syscall_coordinate_roundtrip_and_active_refusal():
    """Preserve the native terminal successor PC, never an out-of-range active PC."""
    from mailcpu.scheduler import DeterministicScheduler
    machine=HeadlessOS()
    pid=machine.launch_source("SYSCALL code exit code=7\n","terminal")
    machine.run(1)
    report=machine.process(pid)
    assert report.status=="exited" and report.pc==1 and report.exit_code==7
    raw=serialize_headless_state(machine)
    recovered=restore_headless_state(raw)
    assert recovered.process(pid)==report
    assert serialize_headless_state(recovered)==raw
    assert recovered.run(100)==()
    for pc,status,halted in ((2,"halted",True),(1,"runnable",False),(1,"blocked",False),
                             (1,"suspended",False),(-1,"halted",True)):
        snap=machine.vm.scheduler.snapshot()
        task=snap["tasks"][str(pid)]
        task.update(pc=pc,status=status,halted=halted)
        with pytest.raises(ValueError,match="invalid scheduler machine coordinates"):
            DeterministicScheduler.from_snapshot(snap,machine.environment.kernel.bus,
                                                 machine.environment.kernel.journal,
                                                 machine.vm._dispatch_program_syscall)
    other=HeadlessOS()
    q=other.launch_source("halt\n","explicit-halt")
    other.run(1)
    assert other.process(q).pc==0
    assert serialize_headless_state(restore_headless_state(serialize_headless_state(other)))==serialize_headless_state(other)
