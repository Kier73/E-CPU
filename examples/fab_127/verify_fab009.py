"""Cross-check actual FAB-009 kernel observations using E-CPU's native law navigator."""
from pathlib import Path
import re
import subprocess
import sys

from mailcpu.law_certifier import lcg_navigate


def verify_samples(executable, increment):
    """Check independent recurrence replay and the native symbolic navigator."""
    report = subprocess.check_output([str(executable), "--samples", str(increment)], text=True, timeout=60)
    lines = report.splitlines()
    if lines[0] != f"formation=1025 lanes=256 increment={increment} native_jump_instructions=167":
        raise ValueError("formation evidence differs")
    checked = set()
    for line in lines[1:]:
        match = re.fullmatch(r"sample=([0-9a-f]{6}) result=(\d+)", line)
        if match is None:
            raise ValueError("invalid sample record")
        coord, observed = int(match[1], 16), int(match[2])
        a, x, t = coord >> 16, (coord >> 8) & 255, coord & 255
        expected = x
        for _ in range(t):
            expected = (a * expected + increment) & 255
        if expected != observed or lcg_navigate(a, increment, 256, x, t) != observed:
            raise ValueError(f"native observation differs at {coord:06x}")
        if coord in checked:
            raise ValueError("duplicate coordinate")
        checked.add(coord)
    if len(checked) != 1026 or not {0, 0xffffff} <= checked:
        raise ValueError("sample coverage differs")
    print(f"increment={increment}: {len(checked)} actual observations agree with native lcg_navigate and sequential reference")


def verify_full(path):
    """Verify all four disjoint worker domains and the full sweep summary."""
    rows = Path(path).read_text().splitlines()
    if rows[0] != "formation=1025 lanes=256 increment=1 native_jump_instructions=167":
        raise ValueError("formation report differs")
    expected = {(0, 64): 514621440, (64, 128): 466509824,
                (128, 192): 597868544, (192, 256): 564158464}
    observed = {}
    for row in rows[1:-1]:
        match = re.fullmatch(r"lanes=(\d+):(\d+) states=256 times=256 count=4194304 seconds=[0-9.]+ sum=(\d+) encoding=path", row)
        if match is None:
            raise ValueError("worker report differs")
        interval = int(match[1]), int(match[2])
        if interval in observed:
            raise ValueError("duplicate worker")
        observed[interval] = int(match[3])
    if observed != expected or not re.fullmatch(r"total_seconds=[0-9.]+ workers=4 complete=1 batch=1", rows[-1]):
        raise ValueError("incomplete or inconsistent full-space sweep")
    print("16,777,216 individually checked coordinates; four disjoint complete worker reports")


if __name__ == "__main__":
    exe = Path(sys.argv[1]).resolve()
    for c in (1, 193):
        verify_samples(exe, c)
    if len(sys.argv) > 2:
        verify_full(sys.argv[2])
