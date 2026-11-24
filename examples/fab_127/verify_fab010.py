"""Independent native E-CPU law cross-check and FAB-010 report validation."""
from pathlib import Path
import random
import re
import subprocess
import sys
from mailcpu.law_certifier import lcg_navigate

def probe(executable, coordinate):
    """Verify a live UDP destination observation against the existing law."""
    raw = subprocess.check_output([str(executable), "--probe", str(coordinate)], text=True, timeout=10)
    match = re.fullmatch(r"coordinate=(\d+) pc=(\d+) register=(\d+)\n", raw)
    if not match:
        raise ValueError("malformed probe")
    t, pc, value = map(int, match.groups())
    q, r = divmod(coordinate, 3)
    x = lcg_navigate(5, 3, 2**32, 12345, q)
    expected = (x if r == 0 else 5*x if r == 1 else 5*x+3) % 2**32
    if (t,pc,value) != (coordinate,r,expected):
        raise ValueError("native law disagreement")

def report(path):
    """Require all primary, secondary and temporal counts and checksums."""
    rows = Path(path).read_text().splitlines()
    if len(rows) != 4:
        raise ValueError("incomplete sweep")
    expected = [
        {"CPUs":16777216, "packets":16777216},
        {"machines":16777216, "halted":16777216, "instructions":124518400,
         "sends":16777216, "receives":16777216, "taken_branches":9699328,
         "checksum":36349145441370112, "state_bytes":536870912},
        {"secondary_contexts":16777216, "secondary_instructions":150994944,
         "secondary_checksum":36028801104216064, "primary_preserved":16777216,
         "retained_state_bytes":939524096},
        {"motion_positions":16777216, "packets":16777216, "checksum":36033477933371508},
    ]
    for row, fields in zip(rows, expected):
        actual = dict(re.findall(r"(\w+)=([0-9]+)(?=\s|$)", row))
        if any(actual.get(k) != str(v) for k,v in fields.items()):
            raise ValueError("full sweep summary differs")
    print("All full-space count and result summaries verified")

def main():
    """Probe endpoints, phase transitions, and seeded distant times."""
    exe = Path(sys.argv[1]).resolve()
    rng = random.Random(127)
    for coordinate in [0,1,2,3,4,5,2**24-1,2**24-2] + rng.sample(range(6,2**24-2), 32):
        probe(exe, coordinate)
    print("40 live temporal probes verified by native E-CPU law")
    if len(sys.argv)>2:
        report(sys.argv[2])

if __name__ == "__main__":
    main()
