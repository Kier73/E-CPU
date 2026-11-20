"""NCB-004 executable development benchmark: source-generated E-CPU conformance.

Run on pinned NCP-002 producer and current local E-CPU source, producing JSON
artifacts for independent CI review. No credentials, network calls, or remote
effects are needed in the source-driven tests.
"""
from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"tests"))
from generated_controller_conformance import main  # noqa: E402


if __name__=="__main__":
    main()
