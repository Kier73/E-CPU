"""FAB-013: compose native OS, dependency readiness and demand-backed memory."""
from hashlib import sha256
import json
from mailcpu.attention import Budget, Offer, machine_scope, plan_attention, verify_plan

import pytest

from mailcpu import HeadlessOS, ComputationNode, NavigableComputationDAG, Capability
from mailcpu.law_certifier import Law
from mailcpu.providers import StructuralMemoryFileRef
from mailcpu.memory import ResidentQuotaExceeded

PAGE = 4096
BASE = 2 * PAGE
MACHINES = (0, 0xffffff)
PROGRAM = "wait inbox value\nset one 1\nadd result value one\nhalt\n"


def test_attention_composition(tmp_path):
    """Run two address-scoped process trees under one shared page and task budget."""
    os = HeadlessOS(max_resident_pages=9, structural_memory_admission_policy=lambda p: True)
    proposal = os.structural_memory.propose(
        "attention-bytes", Law(family="int", params={"x0": 0, "step": 1, "mod": 251},
                               order=1, verdict="GROUND"),
        {0: 0, 1: 1, 250: 250, 251: 0, 4097: 81},
        context={"experiment": "fab013"},
    )
    version = os.structural_memory.admit(proposal.proposal_id, expected_revision=0)
    pids, payloads, nodes = {}, {}, []
    for machine in MACHINES:
        parent = os.launch_source(PROGRAM, f"machine-{machine:06x}")
        child = os.launch_source(PROGRAM, f"child-{machine:06x}", parent_pid=parent)
        assert os.process(child).parent_pid == parent
        for depth, pid in enumerate((parent, child)):
            key = f"m{machine:06x}.p{depth}"
            pids[key] = pid
            os.environment.kernel.processes[pid].capabilities = (
                Capability(f"/memory/{pid}", frozenset({"read", "write"})),
            )
            os.suspend(pid)
            offset = len(pids) * PAGE
            data = bytes((offset + j) % 251 for j in range(PAGE))
            ref = StructuralMemoryFileRef.from_version(version, offset, PAGE)
            digest = sha256(data).hexdigest()
            os.register_structural_memory_page(digest, ref)
            os.vm.memories[pid].reserve(BASE, PAGE, writable=False, backing_blob_ids=(digest,))
            payloads[key] = (data, digest)
            deps = (f"m{machine:06x}.p1",) if depth == 0 else ()
            nodes.append(ComputationNode(key, 1, "fab013.observe-and-run", "/cpu/context",
                                         sha256(key.encode()).hexdigest(), deps,
                                         {"machine": machine, "depth": depth}))
    assert os.vm.resident_pages() == 8
    dag = NavigableComputationDAG(nodes)
    grants = {m: 0 for m in MACHINES}
    order = []
    service = {}
    while not dag.is_complete:
        # An advisory, bounded allocator: native DAG decides readiness; native
        # OS decides the effects. Only one admitted leaf owns the working page.
        available = {}
        for node in dag.ready_nodes():
            p = pids[node.node_id]
            scope = machine_scope(node.payload["machine"], "parent",
                                  "child" if node.payload["depth"] else "self")
            evidence = sha256(json.dumps({
                "node": node.digest, "process": os.process(p).to_dict(),
                "predecessors": {dep: dag.result(dep) for dep in node.dependencies},
                "page": payloads[node.node_id][1],
                "memory": os.syscall(p, "mem_info"),
            }, sort_keys=True).encode()).hexdigest()
            available[scope] = (node, Offer(scope, node.revision, evidence, Budget(3,1,1,1)))
        offers = tuple(o for _,o in available.values())
        cap = Budget(3, os.vm.max_resident_pages-os.vm.resident_pages(), 1, 1)
        plan = plan_attention(offers, cap, epoch=len(order), service=service)
        assert not plan.authoritative and len(plan.grants) == 1
        assert verify_plan(plan, offers, cap, epoch=len(order), service=service)
        chosen = plan.grants[0]
        selected = available[chosen.scope][0]
        key, pid = selected.node_id, pids[selected.node_id]
        machine = selected.payload["machine"]
        data, digest = payloads[key]
        info = os.syscall(pid, "mem_info")
        assert info["mapped_pages"] == 2 and info["reserved_pages"] == 1
        assert os.syscall(pid, "mem_read", address=BASE, size=PAGE) == data
        receipt = os.vm.page_backing.read_receipt(digest)
        assert receipt is not None and receipt.content_digest == digest
        assert os.vm.resident_pages() == 9
        other = next(p for k,p in pids.items() if k != key)
        with pytest.raises(ResidentQuotaExceeded):
            os.syscall(other, "mem_read", address=BASE, size=1)
        assert os.vm.resident_pages() == 9
        predecessor = sum(dag.result(dep)["result"] for dep in selected.dependencies)
        os.inject(pid, "inbox", [data[0] + predecessor])
        os.resume(pid)
        before = os.vm.scheduler.tick
        os.run(before + 3)
        result = os.process(pid)
        assert result.status == "runnable" and result.steps == 3
        os.suspend(pid)
        assert result.registers["result"] == data[0] + predecessor + 1
        assert os.syscall(pid, "mem_reclaim", count=1, pages=[2]) == (2,)
        assert os.vm.resident_pages() == 8
        assert dag.commit(key, {"result": result.registers["result"], "page": digest}) is False
        for i in range(1,len(chosen.scope)+1):
            prefix = chosen.scope[:i]
            service[prefix] = service.get(prefix,0)+1
        assert not verify_plan(plan, offers, cap, epoch=len(order)+1, service=service)
        grants[machine] += 1
        order.append(key)
        if len(order) == 2:
            path = tmp_path / "os.json"
            os.save_checkpoint(path)
            os = HeadlessOS.restore_checkpoint(path)
            dag = NavigableComputationDAG.from_snapshot(dag.snapshot())
            assert os.vm.resident_pages() == 8
    assert order == ["m000000.p1", "mffffff.p1", "m000000.p0", "mffffff.p0"]
    assert grants == {0: 2, 0xffffff: 2}
    for key,pid in pids.items():
        data,_ = payloads[key]
        assert os.syscall(pid, "mem_read", address=BASE, size=PAGE) == data
        os.syscall(pid, "mem_reclaim", count=1, pages=[2])
    assert os.vm.resident_pages() == 8
    for pid in pids.values():
        os.resume(pid)
    os.run(os.vm.scheduler.tick + len(pids))
    assert all(os.process(pid).status == "exited" for pid in pids.values())
    assert os.environment.kernel.journal.verify()
