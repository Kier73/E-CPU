"""Github Actions job 1: construct and check the native E-CPU mathematical intention."""
import argparse
import hashlib
import json
from pathlib import Path
from room_protocol import digest, intention, make_capsule, value_at


def native_crosscheck(intent):
    from mailcpu.ground_native_realization import AffineGround, GroundIntention, independent_observation
    g = intent["ground"]
    native = GroundIntention(intent["request_id"],
                             AffineGround(g["a"], g["c"], g["modulus"], g["seed"]),
                             intent["coordinate"], intent["projection"])
    observed = independent_observation(native)
    if observed != value_at(intent):
        raise AssertionError("native SAB-008 Ground diverged from portable law")
    return native.fingerprint


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--require-native", action="store_true")
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    intent = intention()
    native_id = None
    try:
        native_id = native_crosscheck(intent)
    except ImportError:
        if args.require_native:
            raise
    capsule = make_capsule(intent)
    from room_protocol import verify_capsule
    head = verify_capsule(capsule, expected_generation=1)
    policy = {"schema": "ecpu.room001.external-policy.v1", "intention_digest": digest(intent),
              "expected_head": head, "generation": 1,
              "wasm_sha256": hashlib.sha256((Path(__file__).parent / "browser" / "affine.wasm").read_bytes()).hexdigest()}
    (args.out / "capsule.json").write_text(json.dumps(capsule, sort_keys=True, indent=2) + "\n")
    (args.out / "policy.json").write_text(json.dumps(policy, sort_keys=True, indent=2) + "\n")
    print(json.dumps({"status": "github-runner-checkpoint", "generation": 1,
                      "head": head, "intention": digest(intent), "result": value_at(intent),
                      "native_ecpu_fingerprint": native_id}, sort_keys=True))

if __name__ == "__main__":
    main()
