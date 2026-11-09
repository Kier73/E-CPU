from __future__ import annotations

from dataclasses import replace
import hashlib

import pytest

from mailcpu.assembler import assemble
from mailcpu.computation_dag import NavigableComputationDAG
from mailcpu.law_certifier import Law
from mailcpu.headless import HeadlessOS
from mailcpu import (
    ContextualOrbitAddress,
    ContextualOrbitDataflowInput,
    ContextualOrbitLocateValueReceipt,
    ContextualOrbitLocateValueRequest,
    ContextualOrbitNavigator,
    ObserverContract,
    OperationTimingProbe,
    RepresentationRef,
    SchedulerReading,
    StructuralMemoryRegistry,
    VirtualGroundRef,
    VirtualStructuralMemoryRef,
    contextual_orbit_context,
    structural_memory_spec_representation_ref,
)
from mailcpu.semantic_translation import ObservationContract, canonical_value_digest
from mailcpu.seed import SystemIdentity
from mailcpu.program_dataflow import (
    MailCPUDataflowCompiler,
    ProgramDataflowError,
    compare_dataflow_with_reference,
    evaluate_dataflow,
    verify_dataflow_compilation,
)



def _contextual_orbit_dataflow_input(*, field: str, coordinate: int = 37) -> ContextualOrbitDataflowInput:
    """Mathematics: create an origin-verified, trajectory-free inverse result for the compiled DAG."""
    system = SystemIdentity("dataflow-orbit-system", 1)
    base_ground = VirtualGroundRef("a" * 64, "b" * 64, 41, "c" * 64)
    interpretation = RepresentationRef.from_payload(
        "test.dataflow.integer-ground",
        1,
        {"domain": "integer", "meaning": "counter-state"},
    )
    extensions = {"lane": "primary", "purpose": "typed-dataflow-predecessor"}
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
        "dataflow-contextual-orbit",
        law,
        {index: law.navigate(index) for index in range(8)},
        domain="contextual-orbit-test",
        context=context,
    )
    version = registry.admit(proposal.proposal_id, expected_revision=0)
    memory_reference = VirtualStructuralMemoryRef.from_version(
        "orbit-generator",
        version,
        0,
    )
    address = ContextualOrbitAddress(
        system_identity=system,
        base_ground=base_ground,
        computational_ground=interpretation,
        coordinate=SchedulerReading("vm-scheduler", base_ground.coordinate),
        structural_memory=memory_reference,
        context_extensions=extensions,
    )
    observer = ObserverContract(
        observer_id="dataflow-orbit-observer",
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
    target_value = law.navigate(coordinate)
    request = ContextualOrbitLocateValueRequest(
        address=address,
        observer=observer,
        target_value=target_value,
    )
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
    return ContextualOrbitDataflowInput(request, receipt, field=field)


def test_dataflow_compiler_preserves_program_identity_and_reference_terminal_observation() -> None:
    source = b"\n".join((
        b"set left 5",
        b"set right 11",
        b"set offset 9",
        b"add sum left right",
        b"add mirror right left",
        b"add answer sum offset",
        b"compare relation answer sum",
        b"mul product sum offset",
        b"halt",
    ))
    compiler = MailCPUDataflowCompiler()
    plan = compiler.compile_bytes(source, initial_registers={"seed": 17})

    assert plan.source_bytes_ref is not None
    assert plan.source_bytes_ref.content_digest == hashlib.sha256(source).hexdigest()
    assert plan.program_ref == plan.translation.source
    assert plan.dataflow_representation == plan.translation.target
    assert plan.metrics.max_frontier_width == 3
    assert plan.metrics.topology_candidate == "dataflow"
    assert plan.metrics.recommendation_basis == "structural-frontier-only"
    assert plan.metrics.theoretical_parallelism > 1
    assert plan.frontiers[0] == ("pc-000000", "pc-000001", "pc-000002")

    report = evaluate_dataflow(plan)
    reference = assemble(source.decode("utf-8"))
    comparison = compare_dataflow_with_reference(plan, report, reference)

    assert comparison.equivalent is True
    assert report.observation == {
        "status": "halted",
        "pc": 8,
        "steps": 9,
        "halted": True,
        "blocked": False,
        "registers": {
            "answer": 25,
            "left": 5,
            "mirror": 16,
            "offset": 9,
            "product": 144,
            "relation": 1,
            "right": 11,
            "seed": 17,
            "sum": 16,
        },
    }
    restored = NavigableComputationDAG.from_snapshot(report.dag_snapshot)
    assert restored.is_complete
    assert restored.committed_nodes == report.committed_node_ids
    assert report.dag_snapshot_digest == hashlib.sha256(
        __import__("json").dumps(
            report.dag_snapshot,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def test_latest_register_definition_wins_without_false_write_dependency() -> None:
    program = assemble(
        "set x 4\n"
        "add previous x x\n"
        "set x 10\n"
        "add total x previous\n"
        "halt"
    )
    plan = MailCPUDataflowCompiler().compile_program(program)
    report = evaluate_dataflow(plan)

    assert report.observation["registers"] == {
        "previous": 8,
        "total": 18,
        "x": 10,
    }
    assert "pc-000000" in plan.frontiers[0]
    assert "pc-000002" in plan.frontiers[0]
    assert "pc-000002" not in plan.nodes[1].dependencies
    assert compare_dataflow_with_reference(plan, report, program).equivalent is True


def test_structural_memory_receipt_becomes_a_pinned_initial_register_input() -> None:
    operating_system = HeadlessOS(
        structural_memory_admission_policy=lambda proposal: proposal.spec.domain == "integer-orbit"
    )
    law = Law(
        family="int",
        params={"x0": 3, "step": 2, "mod": 97},
        order=1,
        verdict="GROUND",
    )
    proposal = operating_system.structural_memory.propose(
        "dataflow-input-orbit",
        law,
        {0: 3, 1: 5, 2: 7, 3: 9},
        domain="integer-orbit",
        context={"program": "dataflow", "partition": 1},
    )
    version = operating_system.structural_memory.admit(
        proposal.proposal_id,
        expected_revision=0,
    )
    receipt = operating_system.structural_memory.read_revision(
        "dataflow-input-orbit",
        version.spec.revision,
        10,
        context=version.spec.context,
    )
    source = b"set offset 7\nadd answer memory_value offset\nhalt"
    compiler = MailCPUDataflowCompiler()
    plan = compiler.compile_bytes(
        source,
        structural_memory_reads={"memory_value": receipt},
    )

    assert receipt.value == 23
    assert plan.initial_values == {"memory_value": 23}
    assert plan.structural_memory_reads[0][1].receipt_id == receipt.receipt_id
    assert receipt.receipt_id in str(plan.to_dict())
    report = evaluate_dataflow(plan)

    assert report.observation["registers"] == {
        "answer": 30,
        "memory_value": 23,
        "offset": 7,
    }
    assert compare_dataflow_with_reference(
        plan,
        report,
        assemble(source.decode("utf-8")),
    ).equivalent is True
    assert verify_dataflow_compilation(
        compiler,
        assemble(source.decode("utf-8")),
        plan,
        source_bytes=source,
    )



def test_contextual_orbit_receipts_compile_as_typed_predecessor_nodes_without_trajectory_expansion() -> None:
    """Mathematics: selected coordinate/value become DAG sources while the intervening orbit is never serialized."""
    coordinate_input = _contextual_orbit_dataflow_input(field="coordinate")
    value_input = _contextual_orbit_dataflow_input(field="value")
    program = assemble("add answer orbit_coordinate orbit_value\nhalt")
    compiler = MailCPUDataflowCompiler()
    plan = compiler.compile_program(
        program,
        contextual_orbit_inputs={
            "orbit_coordinate": coordinate_input,
            "orbit_value": value_input,
        },
    )

    source_nodes = {
        node.payload["register"]: node
        for node in plan.nodes
        if node.payload.get("kind") == "mailcpu.register-dataflow.contextual-orbit-input"
    }
    add_node = next(node for node in plan.nodes if node.payload.get("opcode") == "ADD")
    assert set(source_nodes) == {"orbit_coordinate", "orbit_value"}
    assert set(add_node.dependencies) == {item.node_id for item in source_nodes.values()}
    assert coordinate_input.digest in str(plan.to_dict())
    assert value_input.receipt.result.navigation.projection.read_receipt.receipt_id in str(plan.to_dict())
    assert "trajectory" not in str(plan.to_dict()).lower()
    with pytest.raises(ProgramDataflowError, match="typed predecessor nodes"):
        _ = plan.initial_values

    report = evaluate_dataflow(plan)
    restored = NavigableComputationDAG.from_snapshot(report.dag_snapshot)
    assert restored.is_complete
    assert restored.result(source_nodes["orbit_coordinate"].node_id)["selected_coordinate"] == 37
    assert restored.result(source_nodes["orbit_value"].node_id)["selected_value"] == value_input.selected_value
    assert restored.result(source_nodes["orbit_value"].node_id)["receipt_digest"] == value_input.receipt.digest
    assert report.resolved_initial_registers == (
        ("orbit_coordinate", 37),
        ("orbit_value", value_input.value),
    )
    assert report.observation["registers"]["answer"] == coordinate_input.value + value_input.value
    assert compare_dataflow_with_reference(plan, report, program).equivalent is True
    assert verify_dataflow_compilation(compiler, program, plan)


def test_contextual_orbit_dataflow_input_refuses_request_or_receipt_identity_drift() -> None:
    """Mathematics: a typed predecessor cannot detach a routed result from its exact query."""
    from mailcpu import ContextualOrbitFabricError

    predecessor = _contextual_orbit_dataflow_input(field="value")
    changed_request = replace(predecessor.request, target_value=predecessor.request.target_value + 1)
    with pytest.raises(ContextualOrbitFabricError, match="different orbit request"):
        replace(predecessor, request=changed_request)

    payload = predecessor.to_dict()
    payload["receipt"]["operator_effect_digest"] = "f" * 64
    with pytest.raises(ContextualOrbitFabricError, match="operator effect"):
        ContextualOrbitDataflowInput.from_dict(payload)


def test_compiler_refuses_control_flow_effects_and_nonterminal_halt() -> None:
    compiler = MailCPUDataflowCompiler()
    unsupported = (
        "set condition 1\nbranch condition 2\nhalt",
        "send mailbox value\nhalt",
        "wait mailbox value\nhalt",
        "syscall result clock\nhalt",
        "set value 1\nhalt\nset after 2",
        "set value 1",
    )
    for source in unsupported:
        with pytest.raises(ProgramDataflowError):
            compiler.compile_bytes(source.encode("utf-8"))


def test_compiler_rejects_ambiguous_structural_memory_register_sources() -> None:
    operating_system = HeadlessOS(
        structural_memory_admission_policy=lambda proposal: proposal.spec.domain == "integer-orbit"
    )
    law = Law(
        family="int",
        params={"x0": 1, "step": 1, "mod": 97},
        order=1,
        verdict="GROUND",
    )
    proposal = operating_system.structural_memory.propose(
        "ambiguous-dataflow-input",
        law,
        {0: 1, 1: 2, 2: 3},
        domain="integer-orbit",
    )
    version = operating_system.structural_memory.admit(
        proposal.proposal_id,
        expected_revision=0,
    )
    receipt = operating_system.structural_memory.read_revision(
        "ambiguous-dataflow-input",
        version.spec.revision,
        4,
    )
    compiler = MailCPUDataflowCompiler()
    program = assemble("add answer input 1\nhalt")
    with pytest.raises(ProgramDataflowError, match="more than one inline, Structural Memory receipt/reference, or contextual-orbit source"):
        compiler.compile_program(
            program,
            initial_registers={"input": 8},
            structural_memory_reads={"input": receipt},
        )
    corrupted = replace(receipt, value=receipt.value + 1)
    with pytest.raises(ProgramDataflowError, match="inconsistent value digest"):
        compiler.compile_program(
            program,
            structural_memory_reads={"input": corrupted},
        )


def test_compilation_verification_binds_initial_state_and_source_bytes() -> None:
    compiler = MailCPUDataflowCompiler()
    source = b"set answer 42\nhalt"
    program = assemble(source.decode("utf-8"))
    plan = compiler.compile_bytes(source)
    assert verify_dataflow_compilation(compiler, program, plan, source_bytes=source)
    assert not verify_dataflow_compilation(
        compiler,
        program,
        plan,
        source_bytes=b"set answer 43\nhalt",
    )
    changed_initial = compiler.compile_program(program, initial_registers={"seed": 1})
    assert changed_initial.digest != plan.digest
    with pytest.raises(ProgramDataflowError, match="max_work_units"):
        evaluate_dataflow(plan, max_work_units=1)


def test_local_dataflow_records_multiply_compute_phase_with_endpoint_timing_probe() -> None:
    """Mathematics: one profiled MUL node emits exactly one actor-local compute interval correlated to its compiled plan."""
    program = assemble("set left 6\nset right 7\nmul answer left right\nhalt")
    plan = MailCPUDataflowCompiler().compile_program(program)
    readings = iter((100, 125))
    probe = OperationTimingProbe("local/dataflow", monotonic_ns=lambda: next(readings))

    report = evaluate_dataflow(plan, timing_probe=probe)

    assert report.observation["registers"]["answer"] == 42
    samples = probe.samples
    assert len(samples) == 1
    assert samples[0].phase == "local_compute"
    assert samples[0].correlation_id == plan.digest
    assert samples[0].elapsed_ns == 25


def test_local_dataflow_rejects_a_malformed_timing_probe() -> None:
    """Mathematics: a non-null timing observer must expose a callable measure context manager before DAG execution."""
    program = assemble("set left 6\nset right 7\nmul answer left right\nhalt")
    plan = MailCPUDataflowCompiler().compile_program(program)

    with pytest.raises(ProgramDataflowError, match="measure context manager"):
        evaluate_dataflow(plan, timing_probe=object())


def test_symbolic_structural_memory_is_compiled_as_a_pinned_initial_operand_without_a_read() -> None:
    """Mathematics: compile a digest-pinned memory coordinate without performing a receiver read."""
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
        "lazy-dataflow-orbit",
        law,
        {0: 5, 1: 8, 2: 11, 3: 14},
        domain="integer-orbit",
        context={"tenant": "dataflow", "partition": 2},
    )
    version = operating_system.structural_memory.admit(
        proposal.proposal_id,
        expected_revision=0,
    )
    reference = VirtualStructuralMemoryRef.from_version(
        "caller-binding-is-normalized",
        version,
        4,
    )
    program = assemble("set offset 11\nadd answer memory_value offset\nhalt")
    compiler = MailCPUDataflowCompiler()
    plan = compiler.compile_program(
        program,
        structural_memory_refs={"memory_value": reference},
    )

    assert plan.to_dict()["schema"] == "mailcpu.program-dataflow.v3"
    assert plan.structural_memory_refs[0][0] == "memory_value"
    assert plan.structural_memory_refs[0][1].binding == "memory_value"
    assert plan.nodes[1].payload["operands"][0]["kind"] == "structural_memory"
    assert plan.nodes[1].payload["operands"][0]["reference"] == plan.structural_memory_refs[0][1].to_dict()
    assert next(item for item in plan.final_register_sources if item.register == "memory_value").kind == "structural_memory"
    assert plan.to_dict()["structural_memory_refs"][0][0] == "memory_value"
    assert verify_dataflow_compilation(compiler, program, plan)
    with pytest.raises(ProgramDataflowError, match="not materialized"):
        _ = plan.initial_values
    with pytest.raises(ProgramDataflowError, match="receiver-authorized operation-native execution"):
        evaluate_dataflow(plan)
    assert not [
        record for record in operating_system.environment.kernel.journal.records()
        if record.kind == "structural_memory.read_revision"
    ]
