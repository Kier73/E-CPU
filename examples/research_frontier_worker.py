"""Bounded model-side adviser for E-CPU's repository research frontier.

This separate process receives a receiver-defined, digest-bound observation.
It only proposes an operation; it has no GitHub token, DAG commit authority,
merge capability or access to unobserved repository state.

The current adviser is a deterministic linear ranking model, not a trained
language model. It can be substituted without changing receiver authority.
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
from typing import Any

POLICY = "mailcpu.research-frontier.linear-policy.v1"
REQUEST = "mailcpu.research-frontier.prompt.v1"
RESPONSE = "mailcpu.research-frontier.advice.v1"


def digest(value: Any) -> str:
    """Calculate the shared canonical observation identity."""
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def advise(prompt: dict[str, Any]) -> dict[str, Any]:
    """Recommend one ready operation from exact receiver-provided choices."""
    required = {"schema", "intent", "graph_digest", "evidence_digest", "frontier"}
    if not isinstance(prompt, dict) or set(prompt) != required or prompt["schema"] != REQUEST:
        raise ValueError("invalid research adviser prompt")
    if prompt["intent"] != "verify-next-safe-research-operation":
        raise ValueError("unsupported research intention")
    if not isinstance(prompt["frontier"], list) or not prompt["frontier"]:
        raise ValueError("empty or malformed research frontier")
    choices = []
    identifiers = set()
    for item in prompt["frontier"]:
        if not isinstance(item, dict) or set(item) != {
            "id", "status", "descendants", "required_checks", "completed_checks"
        }:
            raise ValueError("invalid research frontier candidate")
        if (type(item["id"]) is not str or item["id"] in identifiers
                or item["status"] not in {
                    "queued", "missing", "failed", "verified", "in_progress"
                }
                or any(type(item[k]) is not int or item[k] < 0
                       for k in ("descendants", "required_checks", "completed_checks"))
                or item["completed_checks"] > item["required_checks"]):
            raise ValueError("invalid research candidate values")
        identifiers.add(item["id"])
        # Higher impact on blocked descendants receives priority; a real
        # failing run is prioritized over a queued check at equal impact.
        scores = {"failed": 30, "missing": 20, "queued": 15,
                  "in_progress": 10, "verified": 0}
        score = 100 * item["descendants"] + scores[item["status"]]
        choices.append((score, item["id"]))
    score, selected = sorted(choices, key=lambda row: (-row[0], row[1]))[0]
    item = next(candidate for candidate in prompt["frontier"] if candidate["id"] == selected)
    proposed_action = {
        "failed": "investigate_failure",
        "missing": "collect_verification",
        "queued": "run_verification",
        "in_progress": "inspect_running_verification",
        "verified": "review_verified_change",
    }[item["status"]]
    result = {
        "schema": RESPONSE,
        "policy": POLICY,
        "prompt_digest": digest(prompt),
        "selected_id": selected,
        "action": proposed_action,
        "score": score,
    }
    return {**result, "advice_digest": digest(result)}


def main() -> int:
    """Process one bounded receiver-issued prompt on standard input."""
    incoming = sys.stdin.read(65537)
    if len(incoming) > 65536:
        raise ValueError("research prompt exceeds bounded input")
    result = advise(json.loads(incoming))
    output = json.dumps(result, sort_keys=True, separators=(",", ":"))
    if len(output) > 4096:
        raise ValueError("advice exceeds response budget")
    sys.stdout.write(output + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
