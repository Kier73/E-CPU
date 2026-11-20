"""NCB-006: real source-generated two-controller contention and topology changes.

The pre-repair native NCB-003 path admitted both controllers concurrently
despite a declared shared capacity of one (red run #44828590800).
Here we keep the exact same independently constructed source actions but
exercise the NEW explicit receiver-owned SQLite reservation pathway.

No physical actuator, quorum reassignment, or external side effect is implied.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import sys
from threading import Event, Lock
from time import monotonic,sleep

import pytest
pytest.importorskip("navigable_compute.coupled")
from navigable_compute.coupled import navigate_coupled
from mailcpu import ComputationalExecutionAdmissionCoordinator
from mailcpu.constructed_controller_admission import (
    NativeResourceBinding,verify_coupled_controller,
    CoupledControllerAdmissionError,
)
from mailcpu.constructed_resource_reservations import (
    ConstructedResourceReservationRefused,ReceiverOwnedResourceReservations,
    execute_reserved_constructed_action,
)
from test_constructed_controller_admission import _world,_native,_bindings,_resources


def _worlds():
    """Produce distinct valid implementations of one joint resource intention."""
    original=_world()
    alternative=navigate_coupled(original,1)
    a=verify_coupled_controller(original.packet())
    b=verify_coupled_controller(alternative.packet())
    assert a.packet_digest!=b.packet_digest
    assert a.resources==b.resources
    return a,b,original.packet(),alternative.packet()


def _run(controller,packet,resource,*,on_execute=None,origin="ncb006"):
    """Actually execute selected actions through a separate live native E-CPU OS."""
    os,identity,ground,catalogue,runtimes,calls=_native(
        packet,on_execute=on_execute,
    )
    result=execute_reserved_constructed_action(
        controller,(2,2),_bindings(controller,(2,2),identity,ground,runtimes),
        catalogue,ComputationalExecutionAdmissionCoordinator(os),
        reservations=resource,source=origin,
    )
    return result,calls


def _minimal_source_generated_contention(a,b):
    """A two-request trace is the smallest conflict for capacity one."""
    names=a.next_action((2,2)).names,b.next_action((2,2)).names
    selected=((0,names[0]),(1,names[1]))
    claims=set((f,n) for f,n in a.resources[0][2])
    units=[sum((f,n) in claims for f,n in enumerate(actions) if n is not None)
           for actions in names]
    assert units==[1,1]
    assert a.resources[0][1]==1
    assert all(value<=1 for value in units)
    assert sum(units)>1
    return selected,units


def test_source_generated_two_controller_schedule_obeys_receiver_capacity(tmp_path) -> None:
    """Green phase: only one actual live pure operator may hold the same claim."""
    first,second,packet_a,packet_b=_worlds()
    source_actions,units=_minimal_source_generated_contention(first,second)
    assert units==[1,1]
    shared_path=tmp_path/"receiver-owned-resource.sqlite3"
    owner=ReceiverOwnedResourceReservations(
        shared_path,resources=_resources(first),
    )
    other=ReceiverOwnedResourceReservations(
        shared_path,resources=_resources(second),
    )
    entered=Event()
    finish=Event()
    lock=Lock()
    active=[0]
    maximum=[0]

    def instrument(factor,operation,argument):
        if operation!="advance":
            return
        with lock:
            active[0]+=1
            maximum[0]=max(maximum[0],active[0])
        try:
            entered.set()
            if not finish.wait(timeout=15):
                raise AssertionError("timed out awaiting controlled claimant release")
        finally:
            with lock:
                active[0]-=1

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future=executor.submit(
            _run,first,packet_a,owner,on_execute=instrument,origin="ncb006-owner-a",
        )
        try:
            assert entered.wait(timeout=12), "first real host never entered resource"
            during=other.snapshot()
            assert during["active_lease_count"]==1
            assert during["occupied_units"]["shared-actuator"]==1
            os,identity,ground,catalogue,runtimes,calls=_native(
                packet_b,on_execute=instrument,
            )
            with pytest.raises(ConstructedResourceReservationRefused,
                               match="capacity already reserved"):
                execute_reserved_constructed_action(
                    second,(2,2),_bindings(second,(2,2),identity,ground,runtimes),
                    catalogue,ComputationalExecutionAdmissionCoordinator(os),
                    reservations=other,source="ncb006-owner-b",
                )
            assert calls==[], "second pure native host should not be invoked"
        finally:
            finish.set()
        actual,first_calls=first_future.result(timeout=15)
    assert actual.execution.status=="verified_native_pure_step"
    assert first_calls
    assert maximum[0]==1 and active[0]==0
    assert owner.snapshot()["active_lease_count"]==0
    after,after_calls=_run(second,packet_b,other,on_execute=instrument,
                           origin="ncb006-owner-b-retry")
    assert after.execution.status=="verified_native_pure_step"
    assert after_calls
    assert maximum[0]==1
    assert other.snapshot()["occupied_units"]["shared-actuator"]==0
    assert actual.reservation_receipt["controller_digest"]!=after.reservation_receipt["controller_digest"]
    assert actual.release_receipt["released"] and after.release_receipt["released"]


def test_topology_change_after_durable_reservation_refuses_and_releases(tmp_path) -> None:
    """A fresh receiver-local route check still applies AFTER taking the claim."""
    first,_,packet,_=_worlds()
    os,identity,ground,catalogue,runtimes,calls=_native(packet)
    initial=(2,2)
    bindings=_bindings(first,initial,identity,ground,runtimes)
    store=ReceiverOwnedResourceReservations(
        tmp_path/"lost-host.sqlite3",resources=_resources(first),
    )

    class DisappearingHostReservations(ReceiverOwnedResourceReservations):
        def reserve(self,controller,state):
            live=super().reserve(controller,state)
            victim=bindings[0]
            catalogue.remove(victim.host_id,victim.address.operator_id)
            return live

    failing=DisappearingHostReservations(store.path,resources=_resources(first))
    with pytest.raises(CoupledControllerAdmissionError,
                       match="native host capability"):
        execute_reserved_constructed_action(
            first,initial,bindings,catalogue,
            ComputationalExecutionAdmissionCoordinator(os),
            reservations=failing,
        )
    assert not calls, "no handler should run after a preflight host loss"
    assert store.snapshot()["active_lease_count"]==0
    # Another newly provisioned native host can execute the same pure source
    # intent under the still-pinned resource policy, with fresh local rights.
    restored,restored_calls=_run(
        first,packet,store,origin="ncb006-reprovisioned-native-host",
    )
    assert restored.execution.status=="verified_native_pure_step"
    assert restored_calls
    assert store.snapshot()["active_lease_count"]==0


def test_local_resource_policy_is_pinned_and_untrusted_packet_cannot_expand_it(tmp_path) -> None:
    """The source-declared resource amount is not the receiver's capacity."""
    first,_,packet,_=_worlds()
    path=tmp_path/"policy.sqlite3"
    owner=ReceiverOwnedResourceReservations(path,resources=_resources(first))
    with pytest.raises(ConstructedResourceReservationRefused,
                       match="policy differs"):
        ReceiverOwnedResourceReservations(
            path,resources=(NativeResourceBinding(
                "shared-actuator",2,((0,"advance"),(1,"advance")),
            ),),
        )
    assert owner.snapshot()["active_lease_count"]==0


def _worker(mode,root):
    """A different Python interpreter/process shares only durable SQLite."""
    return [
        sys.executable,
        str(Path(__file__).parent/"helpers"/"ncb006_reservation_worker.py"),
        mode,str(root/"resource.sqlite3"),str(root/"ready"),str(root/"stop"),
    ]


def _await_ready(marker: Path, worker: subprocess.Popen) -> None:
    deadline=monotonic()+12
    while monotonic()<deadline:
        if marker.exists():
            return
        if worker.poll() is not None:
            raise AssertionError(f"reservation worker exited prematurely: {worker.returncode}")
        sleep(.025)
    raise AssertionError("independent process never installed local reservation")


def test_separate_os_process_occupancy_blocks_then_recovers_after_release(tmp_path) -> None:
    """Independent interpreter reopens same DB and sees actual outstanding claim."""
    first,second,packet_a,packet_b=_worlds()
    owner=ReceiverOwnedResourceReservations(
        tmp_path/"resource.sqlite3",resources=_resources(first),
    )
    proc=subprocess.Popen(_worker("hold",tmp_path),stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE,text=True)
    try:
        _await_ready(tmp_path/"ready",proc)
        assert owner.snapshot()["occupied_units"]["shared-actuator"]==1
        with pytest.raises(ConstructedResourceReservationRefused,
                           match="capacity already reserved"):
            owner.reserve(second,(2,2))
        (tmp_path/"stop").write_text("complete pure operation",encoding="utf8")
        out,err=proc.communicate(timeout=12)
        assert proc.returncode==0,(out,err)
        assert owner.snapshot()["active_lease_count"]==0
        verified,calls=_run(second,packet_b,owner,origin="ncb006-new-process")
        assert verified.execution.status=="verified_native_pure_step"
        assert calls
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate(timeout=8)


def test_hard_process_death_keeps_capacity_fenced_without_time_reclaim(tmp_path) -> None:
    """A killed host cannot create an unverified resource release certificate."""
    first,second,_,_=_worlds()
    resource=ReceiverOwnedResourceReservations(
        tmp_path/"resource.sqlite3",resources=_resources(first),
    )
    crashed=subprocess.run(_worker("crash",tmp_path),
                           stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                           text=True,timeout=12,check=False)
    assert crashed.returncode==73,crashed.stderr
    assert (tmp_path/"ready").exists()
    restarted=ReceiverOwnedResourceReservations(
        resource.path,resources=_resources(second),
    )
    state=restarted.snapshot()
    assert state["active_lease_count"]==1
    assert state["occupied_units"]["shared-actuator"]==1
    assert state["crash_reclamation_supported"] is False
    with pytest.raises(ConstructedResourceReservationRefused,
                       match="capacity already reserved"):
        restarted.reserve(second,(2,2))


def test_failed_pure_handler_refuses_and_releases_its_claim(tmp_path) -> None:
    """No capacity is leaked on an ordinary native semantic error."""
    first,_,packet,_=_worlds()
    resource=ReceiverOwnedResourceReservations(
        tmp_path/"bad-effect.sqlite3",resources=_resources(first),
    )
    os,identity,ground,catalogue,runtimes,calls=_native(packet,incorrect=True)
    with pytest.raises(CoupledControllerAdmissionError,
                       match="violates declared Ground"):
        execute_reserved_constructed_action(
            first,(2,2),_bindings(first,(2,2),identity,ground,runtimes),
            catalogue,ComputationalExecutionAdmissionCoordinator(os),
            reservations=resource,
        )
    assert calls
    assert resource.snapshot()["active_lease_count"]==0
