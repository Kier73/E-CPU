"""NCB-006 RED witness: independent valid controllers can overlap one local resource.

A real source-selected NCP-002 action is independently executed by E-CPU's
existing native Hypervisor. The deliberately missing cross-controller atomic
reservation permits two native handlers to occupy the same claimed shared
actuator simultaneously. This is a test of the *existing* static resource
check, not a claim of actual effects on an external device.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock
from navigable_compute.coupled import navigate_coupled
from mailcpu import ComputationalExecutionAdmissionCoordinator
from mailcpu.constructed_controller_admission import (
    execute_constructed_action,verify_coupled_controller,
)
from test_constructed_controller_admission import _world,_native,_bindings,_resources


def test_source_generated_two_controller_schedule_obeys_receiver_capacity() -> None:
    """Red phase: show the existing static admission does not serialize claimants."""
    source=_world()
    selected=(source,navigate_coupled(source,1))
    barrier=Barrier(2)
    lock=Lock()
    active=[0]
    largest=[0]
    observations=[]

    def instrument(factor,operation,argument):
        if operation!="advance":
            return
        with lock:
            active[0]+=1
            largest[0]=max(largest[0],active[0])
        try:
            barrier.wait(timeout=12)
        finally:
            with lock:
                active[0]-=1

    def run(instance):
        checked=verify_coupled_controller(instance.packet())
        os,identity,ground,catalogue,runtimes,calls=_native(
            instance.packet(),on_execute=instrument,
        )
        initial=(2,2)
        result=execute_constructed_action(
            checked,initial,_bindings(checked,initial,identity,ground,runtimes),
            catalogue,ComputationalExecutionAdmissionCoordinator(os),
            resources=_resources(checked),
            source=f"ncb006-{checked.coordinate}",
        )
        return result

    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(run,selected))
    assert all(x.status=="verified_native_pure_step" for x in results)
    assert active[0]==0
    assert largest[0]<=1, (
        "source-generated counterexample: two independently valid controllers "
        "simultaneously occupied a receiver-declared capacity-one resource"
    )
