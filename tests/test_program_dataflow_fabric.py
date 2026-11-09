from __future__ import annotations

from dataclasses import replace

import pytest

from mailcpu.assembler import assemble
from mailcpu.program_dataflow import MailCPUDataflowCompiler, compare_dataflow_with_reference
from mailcpu.program_dataflow_fabric import (
    DataflowAddFrontierReceipt,
    OperationNativeDataflowError,
    execute_dataflow_operation_native,
)


def _good_receipt(request):
    values = tuple(
        (lane.node_id, lane.left + lane.right)
        for lane in request.lanes
    )
    return DataflowAddFrontierReceipt(
        request_digest=request.digest,
        results=values,
        host_id="logical-gpu",
        peer_id="peer-b",
        peer_path=("peer-a", "peer-b"),
        route_witness_digest="a" * 64,
        forwarding_receipt_digest="b" * 64,
        operator_effect_digest="c" * 64,
        implementation_fingerprint="d" * 64,
        backend_receipt_digest="e" * 64,
    )


def _program():
    return assemble(
        "set a 3\n"
        "set b 5\n"
        "add x a b\n"
        "set c 7\n"
        "set d 11\n"
        "add y c d\n"
        "add z x y\n"
        "halt"
    )


def test_operation_native_executor_batches_frontiers_and_preserves_node_identity() -> None:
    program = _program()
    plan = MailCPUDataflowCompiler().compile_program(program)
    requests = []

    def dispatch(request):
        requests.append(request)
        return _good_receipt(request)

    report = execute_dataflow_operation_native(plan, dispatch)

    assert len(requests) == 2
    assert requests[0].frontier_index == 1
    assert tuple(item.node_id for item in requests[0].lanes) == ("pc-000002", "pc-000005")
    assert requests[1].frontier_index == 2
    assert tuple(item.node_id for item in requests[1].lanes) == ("pc-000006",)
    assert report.execution.observation["registers"] == {
        "a": 3, "b": 5, "c": 7, "d": 11, "x": 8, "y": 18, "z": 26,
    }
    assert tuple(item.request_digest for item in report.frontier_receipts) == tuple(
        item.digest for item in requests
    )
    assert compare_dataflow_with_reference(
        plan, report.execution, program
    ).equivalent is True


def test_operation_native_executor_refuses_wrong_lane_identity_before_frontier_commit() -> None:
    program = _program()
    plan = MailCPUDataflowCompiler().compile_program(program)

    def dispatch(request):
        receipt = _good_receipt(request)
        corrupted = tuple(
            (f"other-{node_id}", value)
            for node_id, value in receipt.results
        )
        return replace(receipt, results=corrupted)

    with pytest.raises(OperationNativeDataflowError, match="lane identities"):
        execute_dataflow_operation_native(plan, dispatch)


def test_operation_native_executor_refuses_semantically_wrong_remote_value() -> None:
    program = _program()
    plan = MailCPUDataflowCompiler().compile_program(program)

    def dispatch(request):
        receipt = _good_receipt(request)
        first_id, first_value = receipt.results[0]
        corrupted = ((first_id, first_value + 1),) + receipt.results[1:]
        return replace(receipt, results=corrupted)

    with pytest.raises(OperationNativeDataflowError, match="independent scalar oracle"):
        execute_dataflow_operation_native(plan, dispatch)


def _lazy_structural_memory():
    from mailcpu.headless import HeadlessOS
    from mailcpu.law_certifier import Law
    from mailcpu.virtual_layer import VirtualStructuralMemoryRef

    operating_system = HeadlessOS(
        structural_memory_admission_policy=lambda proposal: proposal.spec.domain == "integer-orbit"
    )
    law = Law(
        family="int",
        params={"x0": 5, "step": 3, "mod": 97},
        order=1,
        verdict="GROUND",
    )
    proposal = operating_system.structural_memory.propose(
        "operation-native-lazy-orbit",
        law,
        {0: 5, 1: 8, 2: 11, 3: 14},
        domain="integer-orbit",
        context={"tenant": "operation-native", "partition": 2},
    )
    version = operating_system.structural_memory.admit(
        proposal.proposal_id,
        expected_revision=0,
    )
    reference = VirtualStructuralMemoryRef.from_version("memory_value", version, 4)
    return operating_system, reference, version


def _receipt_for_reference(operating_system, reference, version):
    return operating_system.structural_memory.read_revision(
        reference.memory_id,
        version.spec.revision,
        reference.coordinate,
        context=dict(reference.context),
    )


def test_operation_native_add_resolves_symbolic_memory_and_compares_reference_observation() -> None:
    from mailcpu.program_dataflow_fabric import (
        DataflowAddFrontierReceipt,
        execute_dataflow_operation_native,
    )

    operating_system, reference, version = _lazy_structural_memory()
    program = assemble("set offset 11\nadd answer memory_value offset\nhalt")
    compiler = MailCPUDataflowCompiler()
    plan = compiler.compile_program(
        program,
        structural_memory_refs={"memory_value": reference},
    )
    requests = []

    def dispatch(request):
        requests.append(request)
        lane = request.lanes[0]
        assert lane.left is None
        assert lane.left_register == "memory_value"
        assert lane.left_reference is not None
        memory_receipt = _receipt_for_reference(operating_system, reference, version)
        assert lane.left_reference.memory_id == memory_receipt.memory_id
        result = memory_receipt.value + lane.right
        return DataflowAddFrontierReceipt(
            request_digest=request.digest,
            results=((lane.node_id, result),),
            host_id="memory-cpu",
            peer_id="peer-memory",
            peer_path=("peer-origin", "peer-memory"),
            route_witness_digest="a" * 64,
            forwarding_receipt_digest="b" * 64,
            operator_effect_digest="c" * 64,
            implementation_fingerprint="d" * 64,
            backend_receipt_digest="e" * 64,
            structural_memory_receipts=((lane.left_reference.binding, memory_receipt),),
        )

    report = execute_dataflow_operation_native(plan, dispatch)
    comparison = compare_dataflow_with_reference(plan, report.execution, program)

    assert len(requests) == 1
    assert report.execution.resolved_initial_registers == (("memory_value", 17),)
    assert report.execution.observation["registers"] == {
        "answer": 28,
        "memory_value": 17,
        "offset": 11,
    }
    assert comparison.equivalent is True
    assert report.frontier_receipts[0].structural_memory_receipts[0][1].receipt_id
    assert len([
        event for event in operating_system.environment.kernel.journal.records()
        if event.kind == "structural_memory.read_revision"
    ]) == 1


def test_operation_native_add_refuses_a_receipt_from_another_memory_identity() -> None:
    from dataclasses import replace
    from mailcpu.program_dataflow_fabric import (
        DataflowAddFrontierReceipt,
        OperationNativeDataflowError,
        execute_dataflow_operation_native,
    )

    operating_system, reference, version = _lazy_structural_memory()
    program = assemble("set offset 11\nadd answer memory_value offset\nhalt")
    plan = MailCPUDataflowCompiler().compile_program(
        program,
        structural_memory_refs={"memory_value": reference},
    )

    def dispatch(request):
        lane = request.lanes[0]
        correct = _receipt_for_reference(operating_system, reference, version)
        tampered = replace(correct, memory_id="other-structural-memory")
        return DataflowAddFrontierReceipt(
            request_digest=request.digest,
            results=((lane.node_id, correct.value + lane.right),),
            host_id="memory-cpu",
            peer_id="peer-memory",
            peer_path=("peer-origin", "peer-memory"),
            route_witness_digest="a" * 64,
            forwarding_receipt_digest="b" * 64,
            operator_effect_digest="c" * 64,
            implementation_fingerprint="d" * 64,
            backend_receipt_digest="e" * 64,
            structural_memory_receipts=((lane.left_reference.binding, tampered),),
        )

    with pytest.raises(OperationNativeDataflowError, match="exact pinned reference"):
        execute_dataflow_operation_native(plan, dispatch)


def test_cpu_and_egpu_share_the_declared_bounded_add_domain() -> None:
    from mailcpu.egpu import EGPUHost
    from mailcpu.program_dataflow_fabric import (
        OperationNativeDataflowError,
        make_cpu_dataflow_add_handler,
        make_egpu_dataflow_add_handler,
    )
    from mailcpu.transit_simt import TransitSIMTHost

    payload = {
        "lanes": [
            {"node_id": "pc-000001", "left": {"kind": "inline", "value": -7}, "right": {"kind": "inline", "value": 19}},
            {"node_id": "pc-000002", "left": {"kind": "inline", "value": 0}, "right": {"kind": "inline", "value": 42}},
        ],
        "max_steps": 16,
    }
    cpu_result = make_cpu_dataflow_add_handler()(payload, None)
    egpu_result = make_egpu_dataflow_add_handler(EGPUHost(host_id="egpu-domain-test"))(payload, None)

    assert cpu_result["values"] == egpu_result["values"] == [12, 42]
    oversized = {
        "lanes": [{"node_id": "pc-000001", "left": {"kind": "inline", "value": 1 << 4096}, "right": {"kind": "inline", "value": 1}}],
        "max_steps": 16,
    }
    with pytest.raises(OperationNativeDataflowError, match="4096-bit"):
        make_cpu_dataflow_add_handler()(oversized, None)
    with pytest.raises(OperationNativeDataflowError, match="4096-bit"):
        make_egpu_dataflow_add_handler(EGPUHost(host_id="egpu-domain-test-2"))(oversized, None)
    with pytest.raises(OperationNativeDataflowError, match="full shared 64-lane/4096-bit"):
        make_egpu_dataflow_add_handler(
            EGPUHost(host_id="egpu-small-domain", simt_host=TransitSIMTHost(max_lanes=32))
        )
