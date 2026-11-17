"""Reconstruct actual E-CPU compiled neural parameters from Ground addresses."""
from examples.model_weight_ground_demo import main


def test_compiled_model_snapshots_are_recovered_and_exhaustively_checked():
    report = main()
    assert report["parameter_count"] == 10_000
    assert report["full_domain_checked"] == 4
    assert report["snapshots"]["xor"] != report["snapshots"]["and"]
    assert len(report["edited_coordinates"]) == 2
    assert report["sampled_parameter_before"] != report["sampled_parameter_after"]
