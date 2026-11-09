from __future__ import annotations

from pathlib import Path
import runpy


def test_operation_frontier_benchmark_builds_a_reference_equivalent_plan() -> None:
    """Import the benchmark and validate its deterministic workload without opening sockets."""
    script = Path(__file__).resolve().parents[1] / "examples" / "operation_frontier_benchmark.py"
    namespace = runpy.run_path(str(script))
    program, plan, frontier_index, multiplier, coordinate = namespace["_make_plan"](
        lanes=4,
        multiplier_bits=32,
    )

    assert plan.frontiers[frontier_index]
    multiply_nodes = [
        node for node in plan.nodes
        if node.payload.get("opcode") == "MUL"
    ]
    assert len(multiply_nodes) == 4

    report = namespace["evaluate_dataflow"](plan, max_work_units=len(plan.nodes))
    comparison = namespace["compare_dataflow_with_reference"](plan, report, program)
    assert comparison.equivalent is True
    assert all(
        report.observation["registers"][f"product_{index}"] == coordinate * multiplier
        for index in range(4)
    )
