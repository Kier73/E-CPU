"""FAB-008 finite compiler, kernel observations, and native SAB admission."""
import random
import sys
import pytest

from mailcpu.loopback_truth_fabric import KernelTable, codes, experiment, form_adder
from mailcpu.substrate_bootstrap import (
    AdaptiveBootstrap, BootstrapPolicy, BootstrapRefused, BootstrapTask,
    OperationOffer, ResourceObservation, SubstrateObservation,
    digest, verify_bootstrap_report,
)

linux = pytest.mark.skipif(sys.platform != "linux", reason="Linux cBPF realization")

@pytest.mark.parametrize("values,width", [
    ((),1), ((0,2),1), ((False,1),1), ((0,1),True), ((0,1,0),1)
])
def test_bad_ground(values,width):
    with pytest.raises(ValueError):
        codes(values,width)

def test_compiler_shape():
    selector, gate = codes((0,1,1,2,1,2,2,3),2)
    assert len(selector) == 7
    assert selector[3][3] == 0xe994
    assert len(gate) == 16

@linux
def test_quick_native():
    report = experiment(full=False)
    assert report["table"] == (0,1,1,2,1,2,2,3)
    assert report["byte_additions"] == 36
    assert report["composition_packets"] == 288
    assert report["rebound_checks"] == 16
    assert report["refusal_controls"] == 8

@linux
def test_generated_tables():
    rng = random.Random(127)
    checks = 0
    for size in (2,4,8,16):
        for width in (1,2):
            for _ in range(10):
                values = tuple(rng.randrange(1<<width) for _ in range(size))
                with KernelTable(values,width) as table:
                    for x,v in enumerate(values):
                        assert table.observe(x) == v
                        checks += 1
    assert checks == 600

@linux
def test_contradictory_formation():
    with KernelTable((0,0,0,0),1) as wrong:
        with pytest.raises(RuntimeError, match="contradicts"):
            form_adder(wrong)

@linux
def test_native_bootstrap_admission_and_rebinding():
    with KernelTable((1,1,1,0),1) as nand:
        values = form_adder(nand)
    with KernelTable(values,2) as first, KernelTable(values,2) as second:
        operation = "fabric.truth.observe.v1"
        task_ground = digest(["fab008.truth.v1",2,values])
        reports = []
        for table in (first,second):
            # Explicitly observe every coordinate before advertising the local offer.
            measured = tuple(table.observe(x) for x in range(8))
            assert measured == values
            resource = "loopback-truth"
            inventory = SubstrateObservation((ResourceObservation(
                resource, "linux-loopback", 1, 5, "local-observer",
                digest([table.port,measured,table.code]),
                (OperationOffer(operation,"coordinate","ordinal",1),),
            ),), ())
            task = BootstrapTask("full-adder", task_ground, resource, "coordinate",
                                 resource, "ordinal", 7, require_oracle=True)
            binding = table.realizer_binding(resource)
            refused = AdaptiveBootstrap(inventory, BootstrapPolicy(frozenset(),frozenset(),"local-policy"), (binding,), ())
            with pytest.raises(BootstrapRefused):
                refused.plan(task,coordinate=1)
            admitted = AdaptiveBootstrap(inventory, BootstrapPolicy(frozenset({(resource,operation)}),frozenset(),"local-policy"), (binding,), ())
            plan = admitted.plan(task,coordinate=1)
            report = admitted.execute(task,plan,coordinate=1)
            assert report["output"] == 3
            assert report["receiver_oracle_checked_steps"] == 1
            assert verify_bootstrap_report(report,task,plan)
            with pytest.raises(BootstrapRefused):
                admitted.plan(task,coordinate=6)
            reports.append(report)
        assert reports[0]["task_digest"] == reports[1]["task_digest"]
        assert reports[0]["inventory_digest"] != reports[1]["inventory_digest"]
        assert reports[0]["plan_digest"] != reports[1]["plan_digest"]
    with pytest.raises(ValueError):
        first.observe(7)
