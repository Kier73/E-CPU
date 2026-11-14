"""SAB-002 bounded code-and-data worker for an independently launched interpreter.

This is a known local program, NOT a sandbox for arbitrary third-party code.
It exposes only the fixed observation ABI and retains no E-CPU authority.
"""

from __future__ import annotations

import argparse
import json
import sys

from .law_certifier import lcg_navigate


def main(argv: list[str] | None = None) -> int:
    """Serve exactly one structured observation request with no dynamic code loading."""
    parser = argparse.ArgumentParser()
    for key in ("host", "a", "c", "mod", "x0"):
        parser.add_argument("--" + key, required=True)
    args = parser.parse_args(argv)
    try:
        message = json.loads(sys.stdin.readline())
        if (not isinstance(message, dict) or set(message) != {"kind", "host", "coordinate"}
                or message["kind"] != "sab002.observe" or message["host"] != args.host
                or type(message["coordinate"]) is not int or not 0 <= message["coordinate"] <= 10**18):
            return 2
        a, c, m, x0 = int(args.a), int(args.c), int(args.mod), int(args.x0)
        if not (2 <= m <= 2**31 - 1 and all(0 <= x < m for x in (a, c, x0))):
            return 2
        value = lcg_navigate(a, c, m, x0, message["coordinate"])
        print(json.dumps({"kind": "sab002.observation", "host": args.host,
                          "coordinate": message["coordinate"], "value": value}, sort_keys=True))
        return 0
    except (ValueError, TypeError, KeyError, OSError):
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
