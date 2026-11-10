from __future__ import annotations

from pathlib import Path
import runpy


def test_state_space_navigation_experiment_compares_three_verified_paths() -> None:
    """Smoke the actual E-CPU Ground, direct observer, and inverse observer paths."""
    script = (
        Path(__file__).resolve().parents[1]
        / "examples"
        / "state_space_navigation_experiment.py"
    )
    namespace = runpy.run_path(str(script))
    report = namespace["run_experiment"]((8, 64), repeats=1)

    assert report["status"] == "PASS"
    assert report["ground"]["family"] == "integer modular progression"
    assert len(report["results"]) == 2
    for row in report["results"]:
        coordinate = row["target_coordinate"]
        assert row["all_methods_agree"] is True
        assert row["sequential_iteration"]["transition_evaluations_by_sample"] == [coordinate]
        assert row["direct_evaluation"]["expanded_states_per_query"] == 0
        assert row["direct_evaluation"]["verified_observations"] == 1
        assert row["inverse_then_observe"]["expanded_states_per_query"] == 0
        assert row["inverse_then_observe"]["verified_observations"] == 1
