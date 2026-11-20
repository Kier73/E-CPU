"""NCB-006 independent process holds or crashes with a receiver-owned claim.

The parent has no access to the child Python objects, E-CPU system or local
reservation token. Persistent receiver SQLite lock state is the only authority
shared between the original worker and its successor.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
from time import monotonic,sleep

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_constructed_controller_admission import _world,_resources  # noqa: E402
from mailcpu.constructed_controller_admission import verify_coupled_controller  # noqa: E402
from mailcpu.constructed_resource_reservations import ReceiverOwnedResourceReservations  # noqa: E402


def main()->None:
    """Reserve one genuine source-derived action, then hold or hard-crash."""
    if len(sys.argv)!=5 or sys.argv[1] not in ("hold","crash"):
        raise SystemExit("usage: reservation_worker.py hold|crash DB READY STOP")
    mode,db,ready,stop=sys.argv[1:]
    controller=verify_coupled_controller(_world().packet())
    resource=ReceiverOwnedResourceReservations(db,resources=_resources(controller))
    claim=resource.reserve(controller,(2,2))
    Path(ready).write_text("resource reserved before process exit",encoding="utf8")
    if mode=="crash":
        os._exit(73)
    deadline=monotonic()+15
    while monotonic()<deadline:
        if Path(stop).exists():
            resource.release(claim)
            return
        sleep(.025)
    raise SystemExit("timed out holding receiver resource")


if __name__=="__main__":
    main()
