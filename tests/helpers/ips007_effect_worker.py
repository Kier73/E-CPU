"""IPS-007 effect receiver worker: separate process for delayed-write races."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import time

from mailcpu.fenced_effect_receiver import (
    EffectFencingRefused, FencedGroundEffectReceiver, PublishedGroundEffect,
)


def main(args: list[str]) -> int:
    """Reopen a pinned receiver DB after an interprocess barrier and write."""
    if len(args) != 6:
        raise ValueError("need DB, resource, pinned Ground plan, claim, ready and go")
    db_file, resource, plan_digest, claim_file, ready_file, go_file = args
    receiver = FencedGroundEffectReceiver(
        db_file, resource=resource, plan_digest=plan_digest
    )
    claim = PublishedGroundEffect.from_dict(
        json.loads(Path(claim_file).read_text(encoding="utf-8"))
    )
    Path(ready_file).write_text("ready", encoding="utf-8")
    until = time.monotonic() + 16
    while not Path(go_file).is_file():
        if time.monotonic() >= until:
            raise TimeoutError("start barrier not released")
        time.sleep(.02)
    try:
        result = receiver.apply(claim)
    except EffectFencingRefused as exc:
        print(json.dumps({"accepted": False, "reason": str(exc)}), flush=True)
        return 0
    print(json.dumps({"accepted": True, "receipt": result}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
