from __future__ import annotations

from dataclasses import replace

import pytest

from mailcpu.assembler import assemble
from mailcpu.computation_dag import NavigableComputationDAG
from mailcpu.program_dataflow import MailCPUDataflowCompiler, compare_dataflow_with_reference
from mailcpu import (
    ContextualOrbitAddress,
    ContextualOrbitDataflowInput,
    ContextualOrbitLocateValueReceipt,
    ContextualOrbitLocateValueRequest,
    ContextualOrbitNavigator,
    ObserverContract,
    RepresentationRef,
    SchedulerReading,
    StructuralMemoryRegistry,
    VirtualGroundRef,
    VirtualStructuralMemoryRef,
    contextual_orbit_context,
    structural_memory_spec_representation_ref,
)
from mailcpu.law_certifier import Law
from mailcpu.semantic_translation import ObservationContract, canonical_value_digest
from mailcpu.seed import SystemIdentity
from mailcpu.program_dataflow_fabric import (
    DataflowAddFrontierReceipt,
    DataflowCompareFrontierReceipt,
    OperationNativeDataflowError,
    dataflow_compare_operator_spec,
    execute_dataflow_operation_native,
    make_cpu_dataflow_compare_handler,
    make_egpu_dataflow_compare_handler,
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



def _contextual_orbit_inputs():
    """Mathematics: produce two scalar projections over the same receiver-verified inverse result."""
    system = SystemIdentity("operation-native-orbit-system", 1)
    base_ground = VirtualGroundRef("a" * 64, "b" * 64, 41, "c" * 64)
    interpretation = RepresentationRef.from_payload(
        "test.operation-native.integer-ground",
        1,
        {"domain": "integer", "meaning": "counter-state"},
    )
    extensions = {"lane": "primary", "purpose": "operation-native-orbit"}
    context = contextual_orbit_context(
        system,
        base_ground,
        interpretation,
        scheduler_id="vm-scheduler",
        extensions=extensions,
    )
    law = Law(
        family="int",
        params={"step": 7, "mod": 101, "x0": 4},
        order=1,
        verdict="GROUND",
    )
    registry = StructuralMemoryRegistry(admission_policy=lambda _proposal: True)
    proposal = registry.propose(
        "operation-native-contextual-orbit",
        law,
        {index: law.navigate(index) for index in range(8)},
        domain="contextual-orbit-test",
        context=context,
    )
    version = registry.admit(proposal.proposal_id, expected_revision=0)
    reference = VirtualStructuralMemoryRef.from_version("orbit-generator", version, 0)
    address = ContextualOrbitAddress(
        system_identity=system,
        base_ground=base_ground,
        computational_ground=interpretation,
        coordinate=SchedulerReading("vm-scheduler", base_ground.coordinate),
        structural_memory=reference,
        context_extensions=extensions,
    )
    observer = ObserverContract(
        observer_id="operation-native-orbit-observer",
        revision=1,
        subject=structural_memory_spec_representation_ref(version.spec),
        interpretation=interpretation,
        observation=ObservationContract.from_definition(
            "mailcpu.orbit.scalar-value",
            1,
            {"fields": ["coordinate", "offset", "value", "value_digest"]},
        ),
        context_digest=canonical_value_digest(context),
    )
    target_coordinate = 37
    target_value = law.navigate(target_coordinate)
    request = ContextualOrbitLocateValueRequest(address, observer, target_value)
    result = ContextualOrbitNavigator(registry).locate_value(
        address,
        observer,
        target_value,
        operation_id=request.operation_id,
    )
    receipt = ContextualOrbitLocateValueReceipt(
        request_digest=request.digest,
        result=result,
        host_id="logical-host-c",
        peer_id="peer-c",
        peer_path=("peer-a", "peer-c"),
        route_witness_digest="1" * 64,
        forwarding_receipt_digest="2" * 64,
        operator_effect_digest=canonical_value_digest({
            "request_digest": request.digest,
            "result": result.to_dict(),
        }),
        implementation_fingerprint="3" * 64,
    )
    return (
        ContextualOrbitDataflowInput(request, receipt, field="coordinate"),
        ContextualOrbitDataflowInput(request, receipt, field="value"),
    )




def _good_compare_receipt(request):
    from mailcpu.interpreter import compare_values

    values = tuple(
        (lane.node_id, compare_values(lane.left, lane.right))
        for lane in request.lanes
    )
    return DataflowCompareFrontierReceipt(
        request_digest=request.digest,
        results=values,
        host_id="logical-gpu",
        peer_id="peer-b",
        peer_path=("peer-a", "peer-b"),
        route_witness_digest="f" * 64,
        forwarding_receipt_digest="e" * 64,
        operator_effect_digest="d" * 64,
        implementation_fingerprint="c" * 64,
        backend_receipt_digest="b" * 64,
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
    assert requests[0].to_dict()["schema"] == "mailcpu.dataflow.add-frontier-request.v3"
    assert report.frontier_receipts[0].to_dict()["schema"] == "mailcpu.dataflow.add-frontier-receipt.v3"
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



def test_operation_native_add_carries_orbit_receipts_through_multiple_dag_generations() -> None:
    """Mathematics: later fabric operations can recover exact orbit evidence from a value's DAG ancestry."""
    coordinate_input, value_input = _contextual_orbit_inputs()
    program = assemble(
        "add partial orbit_coordinate orbit_value\n"
        "add answer partial orbit_value\n"
        "halt"
    )
    plan = MailCPUDataflowCompiler().compile_program(
        program,
        contextual_orbit_inputs={
            "orbit_coordinate": coordinate_input,
            "orbit_value": value_input,
        },
    )
    requests = []

    def dispatch(request):
        requests.append(request)
        return _good_receipt(request)

    report = execute_dataflow_operation_native(plan, dispatch)

    assert len(requests) == 2
    first_lane = requests[0].lanes[0]
    second_lane = requests[1].lanes[0]
    assert [item.digest for item in first_lane.left_orbit_inputs] == [coordinate_input.digest]
    assert [item.digest for item in first_lane.right_orbit_inputs] == [value_input.digest]
    assert {item.digest for item in second_lane.left_orbit_inputs} == {
        coordinate_input.digest,
        value_input.digest,
    }
    assert [item.digest for item in second_lane.right_orbit_inputs] == [value_input.digest]
    assert requests[1].to_dict()["lanes"][0]["left_orbit_inputs"][0]["schema"] == "mailcpu.contextual-orbit.dataflow-input.v1"
    assert report.execution.observation["registers"]["partial"] == coordinate_input.value + value_input.value
    assert report.execution.observation["registers"]["answer"] == (
        coordinate_input.value + value_input.value * 2
    )
    assert compare_dataflow_with_reference(
        plan, report.execution, program
    ).equivalent is True


def test_cpu_add_receiver_revalidates_contextual_orbit_receipt_payload() -> None:
    """Mathematics: receiver-side ADD realization accepts typed orbit evidence, not a naked value substitution."""
    from mailcpu.program_dataflow_fabric import (
        OperationNativeDataflowError,
        dataflow_add_operator_spec,
        make_cpu_dataflow_add_handler,
    )

    _coordinate_input, value_input = _contextual_orbit_inputs()
    payload = {
        "lanes": [{
            "node_id": "pc-000001",
            "left": {
                "kind": "contextual_orbit",
                "value": value_input.value,
                "inputs": [value_input.to_dict()],
            },
            "right": {"kind": "inline", "value": 11},
        }],
        "max_steps": 16,
    }
    result = make_cpu_dataflow_add_handler()(payload, None)
    assert result["values"] == [value_input.value + 11]
    assert dataflow_add_operator_spec().version == 3

    tampered = {
        **payload,
        "lanes": [{
            **payload["lanes"][0],
            "left": {
                **payload["lanes"][0]["left"],
                "inputs": [{
                    **value_input.to_dict(),
                    "receipt": {
                        **value_input.receipt.to_dict(),
                        "operator_effect_digest": "f" * 64,
                    },
                }],
            },
        }],
    }
    with pytest.raises(OperationNativeDataflowError, match="operator effect"):
        make_cpu_dataflow_add_handler()(tampered, None)



def test_operation_native_compare_frontier_preserves_orbit_provenance_and_commits_operator_receipt() -> None:
    """Mathematics: route sign(left-right), retain the inverse witness, and reuse the existing DAG frontier contract."""
    coordinate_input, value_input = _contextual_orbit_inputs()
    program = assemble(
        "set threshold 40\\n"
        "compare relation orbit_coordinate threshold\\n"
        "add answer relation orbit_value\\n"
        "halt"
    )
    plan = MailCPUDataflowCompiler().compile_program(
        program,
        contextual_orbit_inputs={
            "orbit_coordinate": coordinate_input,
            "orbit_value": value_input,
        },
    )
    compare_requests = []
    add_requests = []

    def dispatch_compare(request):
        compare_requests.append(request)
        return _good_compare_receipt(request)

    def dispatch_add(request):
        add_requests.append(request)
        return _good_receipt(request)

    report = execute_dataflow_operation_native(
        plan,
        dispatch_add,
        operation_dispatchers={"COMPARE": dispatch_compare},
    )

    assert len(compare_requests) == len(add_requests) == 1
    compare_lane = compare_requests[0].lanes[0]
    add_lane = add_requests[0].lanes[0]
    assert compare_lane.left == coordinate_input.value
    assert [item.digest for item in compare_lane.left_orbit_inputs] == [coordinate_input.digest]
    assert [item.digest for item in add_lane.right_orbit_inputs] == [value_input.digest]
    assert report.execution.observation["registers"]["relation"] == -1
    assert report.execution.observation["registers"]["answer"] == value_input.value - 1
    assert len(report.frontier_receipts) == 2
    assert report.frontier_receipts[0].to_dict()["schema"] == "mailcpu.dataflow.compare-frontier-receipt.v1"
    assert report.frontier_receipts[1].to_dict()["schema"] == "mailcpu.dataflow.add-frontier-receipt.v3"

    restored = NavigableComputationDAG.from_snapshot(report.execution.dag_snapshot)
    compare_node = restored.result("pc-000001")
    assert compare_node["operation"] == "COMPARE"
    assert compare_node["operation_receipt"]["schema"] == "mailcpu.dataflow.compare-frontier-receipt.v1"
    assert compare_node["operation_receipt_digest"] == report.frontier_receipts[0].digest
    assert compare_node["frontier_request_digest"] == compare_requests[0].digest
    assert compare_node["operator_id"] == dataflow_compare_operator_spec().operator_id
    assert restored.result("pc-000002")["operation_receipt"]["schema"] == "mailcpu.dataflow.add-frontier-receipt.v3"
    assert compare_dataflow_with_reference(plan, report.execution, program).equivalent is True


def test_cpu_and_egpu_compare_handlers_share_the_same_sign_semantics() -> None:
    """Mathematics: strict ordering outputs {-1,0,1} agree across CPU and the existing bounded SIMT kernel."""
    from mailcpu import EGPUHost

    payload = {
        "lanes": [
            {"node_id": "pc-000001", "left": {"kind": "inline", "value": 1}, "right": {"kind": "inline", "value": 2}},
            {"node_id": "pc-000002", "left": {"kind": "inline", "value": 5}, "right": {"kind": "inline", "value": 5}},
            {"node_id": "pc-000003", "left": {"kind": "inline", "value": 9}, "right": {"kind": "inline", "value": 4}},
        ],
        "max_steps": 32,
    }
    cpu = make_cpu_dataflow_compare_handler()(payload, None)
    egpu_host = EGPUHost(host_id="egpu.compare")
    egpu = make_egpu_dataflow_compare_handler(egpu_host)(payload, None)

    assert cpu["values"] == [-1, 0, 1]
    assert egpu["values"] == cpu["values"]
    assert cpu["backend_method"] == "cpu.vector.compare"
    assert egpu["backend_method"] == "egpu.simt.compare"
    assert len(egpu["backend_receipt_digest"]) == 64
    assert dataflow_compare_operator_spec().substrates == ("cpu", "gpu")


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
    """Mathematics: admit a finite integer orbit and return its exact symbolic read coordinate."""
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
    """Mathematics: read the exact version/context/coordinate named by one symbolic reference."""
    return operating_system.structural_memory.read_revision(
        reference.memory_id,
        version.spec.revision,
        reference.coordinate,
        context=dict(reference.context),
    )


def test_operation_native_add_resolves_symbolic_memory_and_compares_reference_observation() -> None:
    """Mathematics: accept an ADD only after its receiver read receipt matches the symbolic input and scalar oracle."""
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
    """Mathematics: reject a correct numeric value when its Structural Memory identity is not the requested one."""
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
    """Mathematics: confirm both implementations share the same strict lane and integer domain."""
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
    from mailcpu.program_dataflow_fabric import dataflow_add_operator_spec
    assert dataflow_add_operator_spec().version == 3
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
