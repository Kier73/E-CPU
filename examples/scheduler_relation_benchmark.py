"""Run an exact full scheduler relation over a two-process ping-pong VM."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

from mailcpu.model import Instruction, Op, Program
from mailcpu.scheduler import DeterministicScheduler
from mailcpu.scheduler_relation import (
    capture_scheduler_trace,
    compare_scheduler_traces,
)


def producer(cycles: int) -> Program:
    return Program((
        Instruction(Op.SET, ("remaining", cycles)),
        Instruction(Op.SET, ("minus_one", -1)),
        Instruction(Op.SET, ("value", 1)),
        Instruction(Op.SEND, ("proc:2", "value")),
        Instruction(Op.WAIT, ("proc:1", "ack")),
        Instruction(Op.ADD, ("remaining", "remaining", "minus_one")),
        Instruction(Op.BRANCH, ("remaining", 3)),
        Instruction(Op.HALT),
    ))


def worker(cycles: int) -> Program:
    return Program((
        Instruction(Op.SET, ("remaining", cycles)),
        Instruction(Op.SET, ("acc", 0)),
        Instruction(Op.SET, ("minus_one", -1)),
        Instruction(Op.WAIT, ("proc:2", "incoming")),
        Instruction(Op.ADD, ("acc", "acc", "incoming")),
        Instruction(Op.COPY, ("out", "acc")),
        Instruction(Op.SEND, ("trace:worker", "out")),
        Instruction(Op.COPY, ("ack", "acc")),
        Instruction(Op.SEND, ("proc:1", "ack")),
        Instruction(Op.ADD, ("remaining", "remaining", "minus_one")),
        Instruction(Op.BRANCH, ("remaining", 3)),
        Instruction(Op.HALT),
    ))


def make_scheduler(cycles: int) -> DeterministicScheduler:
    scheduler = DeterministicScheduler()
    scheduler.add(producer(cycles), "producer", pid=1)
    scheduler.add(worker(cycles), "worker", pid=2)
    return scheduler


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cycles", type=int, default=32)
    parser.add_argument("--max-transitions", type=int, default=100_000)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.cycles <= 0:
        parser.error("--cycles must be positive")

    left = make_scheduler(args.cycles)
    right = make_scheduler(args.cycles)
    started = time.perf_counter()
    left_witness = capture_scheduler_trace(left, args.max_transitions)
    right_witness = capture_scheduler_trace(right, args.max_transitions)
    elapsed = time.perf_counter() - started
    relation = compare_scheduler_traces(left_witness, right_witness)

    raw_observed_bytes = (
        left_witness.state_payload_bytes_observed
        + left_witness.event_payload_bytes_observed
    )
    witness_bytes = left_witness.witness_bytes_estimate
    result = {
        "evidence_tier": "E0",
        "experiment": "two-process-exact-scheduler-state-relation",
        "cycles": args.cycles,
        "transition_count": left_witness.transition_count,
        "final_tick": left_witness.final_tick,
        "state_relation_equivalent": relation.equivalent,
        "first_divergence": relation.first_divergence,
        "receipt_valid": (
            relation.equivalent
            and left_witness.receipt == right_witness.receipt
        ),
        "worker_output_messages": len(left.bus.peek("trace:worker")),
        "journal_records": left_witness.journal_records,
        "observed_state_payload_bytes": (
            left_witness.state_payload_bytes_observed
        ),
        "observed_event_payload_bytes": (
            left_witness.event_payload_bytes_observed
        ),
        "raw_observed_bytes": raw_observed_bytes,
        "digest_witness_bytes_estimate": witness_bytes,
        "digest_index_ratio": (
            raw_observed_bytes / witness_bytes if witness_bytes else None
        ),
        "elapsed_seconds_two_replays_and_witnessing": elapsed,
        "important_limit": (
            "Digest receipts verify correspondence but cannot reconstruct "
            "scheduler state. This is not semantic history compression or "
            "permission to fast-forward."
        ),
    }
    encoded = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    if not relation.equivalent:
        raise SystemExit("deterministic scheduler relation failed")


if __name__ == "__main__":
    main()
