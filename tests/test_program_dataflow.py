from __future__ import annotations

from dataclasses import replace
import hashlib

import pytest

from mailcpu.assembler import assemble
from mailcpu.computation_dag import NavigableComputationDAG
from mailcpu.law_certifier import Law
from mailcpu.headless import HeadlessOS
from mailcpu.program_dataflow import (
    MailCPUDataflowCompiler,
    ProgramDataflowError,
    compare_dataflow_with_reference,
    evaluate_dataflow,
    verify_dataflow_compilation,
)


def test_dataflow_compiler_preserves_program_identity_and_reference_terminal_observation() -> None:
    source = b"\n".join((
        b"set left 5",
        b"set right 11",
        b"set offset 9",
        b"add sum left right",
        b"add mirror right left",
        b"add answer sum offset",
        b"compare relation answer sum",
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
        "pc": 7,
        "steps": 8,
        "halted": True,
        "blocked": False,
        "registers": {
            "answer": 25,
            "left": 5,
            "mirror": 16,
            "offset": 9,
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
    with pytest.raises(ProgramDataflowError, match="both inline state and Structural Memory"):
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
