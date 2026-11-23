"""Measure model behavior formed from retained original pretrained hosted bytes.

Run after installing E-CPU, original VL-I, VLD and checking out pinned VL-64:

    python scripts/benchmark_addressable_intelligence.py \
      --out artifacts/addressable-intelligence-benchmark.json

This measures exactly one requested Q-row comparison on novel hidden vectors,
not full text generation. Reports cold source construction, warm numerical
behavior, certified early stopping and finite generated-VL-I neural continuity.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import random
import statistics
import time

from mailcpu.addressable_intelligence import (
    _original_slice, compile_trained_model_intention,
    generate_neural_ground_from_trained_observations,
)
from vli.generative_response import GeneratedModelGround, GenerativeConversation

PIN = "36da1db26b256984abf73cfbeaf51fa7d67ed90ea7f473813e5376158bd37a74"
DEFAULT_CAPSULE = (
    Path(__file__).resolve().parents[1] / "original-vl64"
    / "experiments" / "model_fabric" / "datasets"
    / "2026-11-18-pretrained-bf16-slice-ground.json"
)


def benchmark(capsule: Path, *, trials: int) -> dict:
    """Compare intended original-weight behavior against complete 4-row work."""
    if type(trials) is not int or not 8 <= trials <= 256:
        raise ValueError("trials must be an exact integer in 8..256")
    raw = capsule.read_bytes()
    source = json.loads(raw)
    if source["ground_digest"] != PIN:
        raise ValueError("external trained source does not match trusted historic Ground")
    started = time.perf_counter_ns()
    compiled = compile_trained_model_intention(
        source, expected_source_head=PIN, row_a=0, row_b=1,
    )
    compiled_ns = time.perf_counter_ns() - started
    original, gain, q, original_replay = _original_slice(source, expected_head=PIN)
    width = compiled.width
    rng = random.Random(271828)
    samples = [
        [rng.uniform(-1, 1) for _ in range(width)]
        for _ in range(trials)
    ]
    def dense(hidden):
        """Full original BF16 four-coordinate Q-projection as warm FP64 reference."""
        den = math.sqrt(
            math.fsum(v*v for v in hidden)/width + original["rms_eps"],
        )
        v = [float(hidden[i])*gain[i]/den for i in range(width)]
        return [
            math.fsum(q[row*width+i]*v[i] for i in range(width))
            for row in range(4)
        ]
    baseline_start = time.perf_counter_ns()
    references = [dense(sample) for sample in samples]
    dense_ns = time.perf_counter_ns() - baseline_start
    nav_start = time.perf_counter_ns()
    observed = [compiled.observe(sample) for sample in samples]
    nav_ns = time.perf_counter_ns() - nav_start
    stable = 0
    ties = 0
    mismatches = []
    for i,(report,reference) in enumerate(zip(observed,references)):
        margin = reference[0]-reference[1]
        if abs(margin) < 1e-9:
            ties += 1
            continue
        stable += 1
        expected = 1 if margin > 0 else -1
        if report["sign"] != expected:
            mismatches.append(i)
    if mismatches:
        raise AssertionError("exact compiled original readout disagreed with FP64 oracle")
    direction = [v/compiled.denominator for v in compiled.coefficients]
    calibration = [
        direction,
        [-v for v in direction],
        [v * (1 if j%3 else -0.3) for j,v in enumerate(direction)],
        [v * (-1 if j%5 else 0.1) for j,v in enumerate(direction)],
    ]
    formation_start = time.perf_counter_ns()
    description, certificate = generate_neural_ground_from_trained_observations(
        compiled,
        [(sample,compiled.observe(sample)) for sample in calibration],
    )
    formed_ns = time.perf_counter_ns() - formation_start
    ground = GeneratedModelGround(description)
    session = GenerativeConversation(
        ground, observer="addressable-model-benchmark",
    )
    session_start = time.perf_counter_ns()
    for prompt, action in [
        ("inspect the observed trained behavior", "inspect"),
        ("advance to the next observed state", "advance"),
        ("follow the new neural model law", "advance"),
        ("inspect the resulting state", "inspect"),
    ]:
        session.respond(prompt, action, views=("text", "code", "tokens"))
    turn_ns = time.perf_counter_ns() - session_start
    checkpoint = session.checkpoint()
    if (GenerativeConversation.restore(
        ground, checkpoint,
        expected_head=checkpoint["checkpoint_digest"],
    ).checkpoint() != checkpoint):
        raise AssertionError("formed original VL-I neural state cannot replay")
    summary = {
        "schema": "mailcpu.addressable-intelligence-benchmark.v1",
        "source_model": source["model"], "source_revision": source["revision"],
        "source_ground_head": PIN,
        "source_capsule_file_sha256": hashlib.sha256(raw).hexdigest(),
        "original_source_replay": original_replay,
        "trained_payload_observed_historically_bytes": compiled.model_observation_bytes,
        "original_tensor_slice_bytes_relevant_to_intention": compiled.relevant_source_bytes,
        "new_remote_source_weight_reads": 0,
        "new_remote_source_weight_bytes": 0,
        "compiled_behavior_head": compiled.ground_digest,
        "hidden_width": width,
        "pair": [compiled.row_a,compiled.row_b],
        "held_out_input_vectors": trials,
        "numerically_stable_held_out_vectors": stable,
        "near_tie_reference_positions_excluded": ties,
        "stable_comparison_mismatches": mismatches,
        "certified_early_stops": sum(bool(row["certified_early"]) for row in observed),
        "mean_evaluated_coordinates": statistics.mean(row["observed_coordinates"] for row in observed),
        "min_evaluated_coordinates": min(row["observed_coordinates"] for row in observed),
        "max_evaluated_coordinates": max(row["observed_coordinates"] for row in observed),
        "compiled_neural_formation": certificate,
        "four_turn_causal_head": checkpoint["head"],
        "native_vli_generated_state": checkpoint["state"],
        "measurement_ns": {
            "source_admission_and_cold_compilation": compiled_ns,
            "warm_full_4row_reference_for_all_inputs": dense_ns,
            "warm_exact_partial_readout_for_all_inputs": nav_ns,
            "original_vld_generated_neural_formation": formed_ns,
            "original_vli_four_stateful_turns": turn_ns,
        },
        "scope": "one_original_trained_BF16_subgraph_and_finite_formed_neural_environment",
        "precision_note": "exact-dyadic sign compared against FP64 dense reference outside near ties; wall time includes Python overhead and is not a full-model speedup",
    }
    return summary


def main() -> int:
    """Reproduce one source-pinned executable trace and optional artifact."""
    parser = argparse.ArgumentParser(description="Intention-compiled original hosted-model behavior")
    parser.add_argument("--capsule", type=Path, default=DEFAULT_CAPSULE)
    parser.add_argument("--trials", type=int, default=64)
    parser.add_argument("--out", type=Path)
    opts = parser.parse_args()
    result = benchmark(opts.capsule, trials=opts.trials)
    printed = json.dumps(result, sort_keys=True, indent=2, allow_nan=False)
    print(printed)
    if opts.out is not None:
        opts.out.parent.mkdir(parents=True, exist_ok=True)
        opts.out.write_text(printed + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
