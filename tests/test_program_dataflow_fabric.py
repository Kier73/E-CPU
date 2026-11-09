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
