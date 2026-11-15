"""Isolated model-inference worker for the USM-001 E-CPU operating experiment.

This program has no registry, OS, hypervisor, or admission capability. It
accepts one bounded JSON model artifact and observation window, performs
inference, and returns a correlation-bound advisory value.
"""

from __future__ import annotations

import json
import sys

from examples.model_ground_os import GroundPolicyModel, _digest


def serve() -> dict[str, object]:
    """Interpret exactly one model request as an unprivileged subprocess."""
    raw = sys.stdin.read(65537)
    if len(raw) > 65536:
        raise ValueError("oversized model request")
    request = json.loads(raw)
    if not isinstance(request, dict) or set(request) != {"kind", "model", "window"}:
        raise ValueError("invalid model request envelope")
    if request["kind"] != "mailcpu.use-system.predict.v1":
        raise ValueError("unsupported model request")
    if not isinstance(request["window"], list) or not 4 <= len(request["window"]) <= 4096:
        raise ValueError("invalid model observation window")
    model = GroundPolicyModel.from_snapshot(request["model"])
    probability = model.predict(request["window"])
    return {
        "kind": "mailcpu.use-system.prediction.v1",
        "request_digest": _digest(request),
        "model_digest": model.digest,
        "probability": probability,
    }


if __name__ == "__main__":
    try:
        print(json.dumps(serve(), sort_keys=True, separators=(",", ":")))
    except (ValueError, TypeError, KeyError) as exc:
        print(f"refused model request: {type(exc).__name__}", file=sys.stderr)
        sys.exit(2)
