"""INTERNET-004: read-only RFC navigation by declared intention.

Run on an Internet-connected host; nonzero exit for unreachable/refused paths.
"""
import argparse
import json
from pathlib import Path
from mailcpu.public_internet_navigation import Policy, navigate, verify_capsule, strict_loads, canonical


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=("observe", "verify"))
    p.add_argument("--seed", type=int, default=9293)
    p.add_argument("--target", type=int, default=793)
    p.add_argument("--file", type=Path, required=True)
    p.add_argument("--max-pages", type=int, default=4)
    p.add_argument("--max-depth", type=int, default=2)
    p.add_argument("--expected-digest", default=None)
    args = p.parse_args()
    policy = Policy((args.seed,),args.target,max_pages=args.max_pages,max_depth=args.max_depth)
    if args.command == "observe":
        capsule = navigate(policy)
        if args.file.exists():
            p.error("refusing to replace existing observation evidence")
        args.file.write_bytes(canonical(capsule)+b"\n")
        report = verify_capsule(capsule,policy)
    else:
        capsule = strict_loads(args.file.read_bytes())
        report = verify_capsule(capsule,policy,expected_capsule_digest=args.expected_digest)
    print(json.dumps(report,sort_keys=True,indent=2))
    if report["status"] != "reached_observed_target":
        raise SystemExit(2)

if __name__ == "__main__":
    main()
