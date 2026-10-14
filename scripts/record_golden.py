"""Record transport-neutral traces for the current deterministic program corpus."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mailcpu import QueueInterpreter, canonical_result
from mailcpu.programs import addition_program, branch_program, countdown_program, wait_send_program


def main() -> None:
    """Mathematics: serialize the finite set `{π(run(program))}` as reproducible JSON fixtures."""

    cases = {
        "addition": (addition_program(1, 1), {}, {}),
        "branch_taken": (branch_program(1), {}, {}),
        "branch_not_taken": (branch_program(0), {}, {}),
        "countdown": (countdown_program(3), {}, {}),
        "wait_send": (wait_send_program(), {}, {"inbox": [42]}),
    }
    output = {}
    for name, (program, registers, inputs) in cases.items():
        result = QueueInterpreter(program).run(registers, inputs)
        output[name] = canonical_result(result)
    destination = ROOT / "tests" / "golden_traces.json"
    destination.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(destination)


if __name__ == "__main__":
    main()
