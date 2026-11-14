"""USM-002 model-only process: choose typed E-CPU system calls, never run them."""

from __future__ import annotations

import json
import sys

from examples.model_ground_os import GroundPolicyModel, _digest
from examples.model_system_calls import CALL_SCHEMA, REQUEST_SCHEMA, RESPONSE_SCHEMA


def serve() -> dict[str, object]:
    """Stateless decision for one host-supplied phase, with immutable correlation."""
    raw = sys.stdin.read(65537)
    if len(raw) > 65536:
        raise ValueError("oversized model request")
    request = json.loads(raw)
    required = {"kind", "session_id", "stream_id", "seq", "previous_head",
                "phase", "coordinate", "threshold", "model", "last_response"}
    if type(request) is not dict or set(request) != required or request["kind"] != REQUEST_SCHEMA:
        raise ValueError("invalid model system-call request")
    model = GroundPolicyModel.from_snapshot(request["model"])
    stage = request["phase"]
    probability = None
    if stage == "new":
        if request["last_response"] is not None:
            raise ValueError("new sessions have no earlier observation")
        operation = "observe"
    elif stage == "observed":
        previous = request["last_response"]
        if type(previous) is not dict or previous.get("status") != "observed":
            raise ValueError("model has no host-returned observation")
        window = previous.get("window")
        if type(window) is not list or not 4 <= len(window) <= 4096:
            raise ValueError("host observation is invalid")
        if previous.get("window_digest") != _digest(window):
            raise ValueError("host observation digest changed")
        probability = model.predict(window)
        operation = "propose" if probability >= request["threshold"] else "stop"
    elif stage == "admitted":
        previous = request["last_response"]
        if type(previous) is not dict or previous.get("status") != "admitted":
            raise ValueError("model has no Ground admission receipt")
        operation = "read"
    else:
        raise ValueError("system-call stage is not actionable")
    call = {
        "schema": CALL_SCHEMA,
        "session_id": request["session_id"],
        "stream_id": request["stream_id"],
        "seq": request["seq"],
        "previous_head": request["previous_head"],
        "op": operation,
        "coordinate": request["coordinate"] if operation == "read" else None,
    }
    return {
        "kind": RESPONSE_SCHEMA,
        "request_digest": _digest(request),
        "model_digest": model.digest,
        "call": call,
        "probability": probability,
    }


if __name__ == "__main__":
    try:
        print(json.dumps(serve(), sort_keys=True, separators=(",", ":"), allow_nan=False))
    except (ValueError, TypeError, KeyError) as exc:
        print(f"refused model system-call request: {type(exc).__name__}", file=sys.stderr)
        sys.exit(2)
