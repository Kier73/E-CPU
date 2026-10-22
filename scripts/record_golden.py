"""Record transport-neutral traces for the current deterministic program corpus."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mailcpu import ReferenceInterpreter, canonical_result
from mailcpu.programs import addition_program, branch_program, countdown_program, wait_send_program


def _render_golden() -> dict[str, object]:
    """Mathematics: construct `G[name] = π(reference(P_name, I_name))` over the fixed corpus relation."""

    cases = {
        "addition": (addition_program(1, 1), {}, {}),
        "branch_taken": (branch_program(1), {}, {}),
        "branch_not_taken": (branch_program(0), {}, {}),
        "countdown": (countdown_program(3), {}, {}),
        "wait_send": (wait_send_program(), {}, {"inbox": [42]}),
    }
    output: dict[str, object] = {}
    for name, (program, registers, inputs) in cases.items():
        result = ReferenceInterpreter(program).run(registers, inputs)
        output[name] = canonical_result(result)
    return output


def main(argv: list[str] | None = None) -> None:
    """Mathematics: verify `G=JSON(path)` by default and write it only under explicit `--write` authority."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write",
        action="store_true",
        help="replace the checked-in fixture with the reference-interpreter result",
    )
    arguments = parser.parse_args(argv)
    output = _render_golden()
    destination = ROOT / "tests" / "golden_traces.json"
    if arguments.write:
        destination.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {destination}")
        return
    if not destination.exists():
        raise SystemExit(f"golden fixture is missing: {destination}")
    try:
        current = json.loads(destination.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"golden fixture cannot be read: {error}") from error
    if current != output:
        raise SystemExit("golden fixture diverges; rerun with --write only after diagnosing the semantic change")
    print(f"verified {destination}")


if __name__ == "__main__":
    main()
