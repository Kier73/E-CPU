"""Independent Python receiver: integrity, semantics, high-water and native cross-check."""
import argparse
import json
from pathlib import Path
from room_protocol import RoomRefused, digest, verify_capsule, value_at


def audit(capsule, policy, *, native=False):
    if set(policy) != {"schema", "intention_digest", "expected_head", "generation", "wasm_sha256"} or policy["schema"] != "ecpu.room001.external-policy.v1":
        raise RoomRefused("independently supplied policy format invalid")
    head = verify_capsule(capsule, expected_intention=policy["intention_digest"],
                          expected_head=policy["expected_head"], expected_generation=policy["generation"])
    if native:
        from build_runner import native_crosscheck
        native_id = native_crosscheck(capsule["intention"])
    else:
        native_id = None
    return {"schema": "ecpu.room001.offline-verification.v1", "head": head,
            "generation": len(capsule["receipts"]), "result": value_at(capsule["intention"]),
            "rooms": [r["room"] for r in capsule["receipts"]],
            "new_source_calls": 0, "native_ground_fingerprint": native_id,
            "external_pin_scope": "caller_supplied_test_supervisor_policy_not_publisher_signature"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--capsule", type=Path, required=True)
    ap.add_argument("--policy", type=Path, required=True)
    ap.add_argument("--require-native", action="store_true")
    ap.add_argument("--output", type=Path)
    args = ap.parse_args()
    cap = json.loads(args.capsule.read_text())
    pol = json.loads(args.policy.read_text())
    report = audit(cap, pol, native=args.require_native)
    print(json.dumps(report, sort_keys=True))
    if args.output:
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")

if __name__ == "__main__": main()
