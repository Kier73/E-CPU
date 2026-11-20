"""NCB-005: source-generated semantic counterexamples must be refused at admission.

These regressions intentionally FAIL against the parent NCB-004 main commit.
The generator starts from the actual pinned NCP-002 source controller and
shrinks a three-cell integrity-preserving invalid representation to one cell.
No native capability or physical actuator is imported from the source.
"""
from __future__ import annotations

from dataclasses import replace
import pytest

pytest.importorskip("navigable_compute.coupled",
                    reason="NCB-005 dedicated CI installs pinned NCP-002 source")

from mailcpu import ComputationalExecutionAdmissionCoordinator
from mailcpu.constructed_controller_admission import (
    CoupledControllerAdmissionError,execute_constructed_action,
    verify_coupled_controller,
)
from test_constructed_controller_admission import _world,_native,_bindings,_resources
from generated_counterexample_probe import (
    apply_edits,generate_and_reduce_alias,report_minimal_source_alias,
    discover_native_input_alias,exact_type_oracle,legacy_equality_would_accept,
)


def test_source_generated_minimal_invalid_certificate_is_refused() -> None:
    """Real proof SHA can match while bool/float states change the source type."""
    base,edits,changed=generate_and_reduce_alias()
    assert len(edits)==1
    assert legacy_equality_would_accept(base,changed)
    assert not exact_type_oracle(changed)
    assert verify_coupled_controller(base).packet_digest==base["sha256"]
    with pytest.raises(CoupledControllerAdmissionError,match="source joint state|coordinate|type"):
        verify_coupled_controller(changed)
    # Deletion-minimal: removing the last edit returns the admitted source.
    assert apply_edits(base,())==base
    report=report_minimal_source_alias()
    assert report["remaining_edits"]==1
    assert report["old_value_equality"] is True
    assert report["strict_source_type_oracle"] is False


def test_generated_source_rejects_bool_or_float_runtime_input_before_handler() -> None:
    """An otherwise correct native action cannot use a type-aliased input field."""
    world=_world()
    checked=verify_coupled_controller(world.packet())
    state,factor,_=discover_native_input_alias(checked)
    for field,alias in (("factor_index",True),("source_state",True),
                        ("factor_index",1.0),("source_state",1.0)):
        os,identity,ground,catalogue,runtimes,calls=_native(world.packet())
        coordinator=ComputationalExecutionAdmissionCoordinator(os)
        bindings=list(_bindings(checked,state,identity,ground,runtimes))
        index=next(i for i,b in enumerate(bindings) if b.factor==factor)
        original=bindings[index]
        input_value=dict(original.address.workload.input_value)
        assert input_value[field]==1
        assert type(input_value[field]) is int
        input_value[field]=alias
        retyped_workload=replace(original.address.workload,input_value=input_value)
        changed_address=replace(original.address,workload=retyped_workload)
        bindings[index]=replace(original,address=changed_address)
        # Independently valid typed workload JSON, altered AFTER the source
        # controller was checked. It must fail exact binding before any work.
        with pytest.raises(CoupledControllerAdmissionError,match="workload input"):
            execute_constructed_action(
                checked,state,tuple(bindings),catalogue,coordinator,
                resources=_resources(checked),
                source=f"ncb005-{field}-{type(alias).__name__}",
            )
        assert not calls


def test_runtime_current_state_has_exact_integer_coordinate_types() -> None:
    """A Boolean/float observer coordinate must not alias an integer state."""
    world=_world()
    controller=verify_coupled_controller(world.packet())
    state,factor,_=discover_native_input_alias(controller)
    modified=list(state)
    modified[factor]=True
    assert tuple(modified)==state  # Demonstrate actual Python equality hazard.
    with pytest.raises(CoupledControllerAdmissionError,match="state"):
        controller.next_action(tuple(modified))
    modified[factor]=1.0
    assert tuple(modified)==state
    with pytest.raises(CoupledControllerAdmissionError,match="state"):
        controller.next_action(tuple(modified))


def test_positive_control_preserves_native_program_execution() -> None:
    """Repair cannot improve refusal at cost of disabling qualified pure work."""
    world=_world()
    checked=verify_coupled_controller(world.packet())
    state,factor,_=discover_native_input_alias(checked)
    os,identity,ground,catalogue,runtimes,calls=_native(world.packet())
    result=execute_constructed_action(
        checked,state,_bindings(checked,state,identity,ground,runtimes),
        catalogue,ComputationalExecutionAdmissionCoordinator(os),
        resources=_resources(checked),source="ncb005-valid-control",
    )
    assert result.status=="verified_native_pure_step"
    assert result.observed in checked.next_action(state).allowed
    assert calls
