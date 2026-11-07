"""Hosted Virtual Ground Interpreter operator for the E-CPU Virtual Layer.

The adapter keeps VGI's mathematical Ground separate from E-CPU's admitted
system Ground. It transports typed task data, never Python code or authority.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any, Callable

from .virtual_layer import (
    OperatorRegistry,
    OperatorSpec,
    VirtualLayerError,
    VirtualLayerWorkload,
)

VGI_SIGNAL8_OPERATOR_ID = "vgi.signal8.execute"
VGI_SIGNAL8_INPUT_SCHEMA = "vgi.signal8.request.v1"


class VGIHostError(VirtualLayerError):
    """A VGI hosted computation is malformed, incompatible, or outside its bounds."""


def _canonical_digest(value: Any) -> str:
    """Return a stable SHA-256 digest for a finite JSON-compatible value."""
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _positive_integer(value: Any, name: str, maximum: int) -> int:
    """Validate a positive, bounded integer without accepting booleans."""
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 1
        or value > maximum
    ):
        raise VGIHostError(f"{name} must be an integer in [1, {maximum}]")
    return value


def _signal_value(raw: Any, address: str, signal_value_type: type[Any]) -> Any:
    """Build one signal value from its exact finite wire representation."""
    required = {"real", "imag", "observer", "phase_error_bound"}
    if not isinstance(raw, Mapping) or set(raw) != required:
        raise VGIHostError(
            f"signal memory cell {address!r} must contain exactly {sorted(required)}"
        )
    real = raw["real"]
    imag = raw["imag"]
    observer = raw["observer"]
    error = raw["phase_error_bound"]
    if (
        isinstance(real, bool)
        or not isinstance(real, (int, float))
        or isinstance(imag, bool)
        or not isinstance(imag, (int, float))
        or isinstance(observer, bool)
        or not isinstance(observer, int)
        or isinstance(error, bool)
        or not isinstance(error, (int, float))
    ):
        raise VGIHostError(f"signal memory cell {address!r} has invalid field types")
    try:
        return signal_value_type(complex(real, imag), observer, float(error))
    except (TypeError, ValueError) as exc:
        raise VGIHostError(f"signal memory cell {address!r} is outside the VGI Ground") from exc


def execute_vgi_signal8(
    input_value: Mapping[str, Any],
    workload: VirtualLayerWorkload,
    *,
    max_configured_steps: int = 10_000,
) -> dict[str, object]:
    """Compile, execute, and checkpoint one typed VGI Signal8 task."""
    if not isinstance(workload, VirtualLayerWorkload):
        raise VGIHostError("VGI execution requires a typed VirtualLayerWorkload")
    if not isinstance(input_value, Mapping):
        raise VGIHostError("VGI input must be a JSON object")
    _positive_integer(max_configured_steps, "max_configured_steps", 10_000_000)

    expected_fields = {
        "schema",
        "ground_fingerprint",
        "task",
        "initial_memory",
        "max_steps",
    }
    if set(input_value) != expected_fields:
        raise VGIHostError(
            f"VGI request fields must be exactly {sorted(expected_fields)}"
        )
    if input_value.get("schema") != VGI_SIGNAL8_INPUT_SCHEMA:
        raise VGIHostError("unsupported VGI Signal8 request schema")

    try:
        from vgi import (
            SIGNAL8_GROUND,
            SignalValue,
            TaskSpec,
            VirtualGroundInterpreter,
            __version__ as vgi_version,
        )
    except ImportError as exc:
        raise VGIHostError(
            "VGI is not installed; install the E-CPU 'vgi' extra to enable this operator"
        ) from exc

    supplied_fingerprint = input_value.get("ground_fingerprint")
    if supplied_fingerprint != SIGNAL8_GROUND.fingerprint:
        raise VGIHostError(
            "VGI computational Ground fingerprint does not match the local Signal8 Ground"
        )

    max_steps = _positive_integer(
        input_value.get("max_steps"),
        "max_steps",
        min(max_configured_steps, workload.budget.max_virtual_ticks),
    )
    task_data = input_value.get("task")
    raw_memory = input_value.get("initial_memory")
    if not isinstance(task_data, Mapping):
        raise VGIHostError("VGI task must be a typed task-expression object")
    if not isinstance(raw_memory, Mapping):
        raise VGIHostError("VGI initial_memory must be an object")

    try:
        task = TaskSpec.from_dict(task_data)
        if set(raw_memory) != set(task.inputs):
            raise VGIHostError(
                "VGI initial_memory addresses must exactly match the task's declared inputs"
            )
        memory = {
            address: _signal_value(value, address, SignalValue)
            for address, value in raw_memory.items()
        }
        interpreter = VirtualGroundInterpreter(ground=SIGNAL8_GROUND)
        program = interpreter.compile_task(task)
        machine = interpreter.instantiate(program, memory)
        result = machine.run(max_steps=max_steps)
        snapshot = machine.snapshot()
    except VGIHostError:
        raise
    except (TypeError, ValueError, RuntimeError) as exc:
        raise VGIHostError(f"VGI task compilation or execution refused: {exc}") from exc

    outputs = [
        {"label": emission.label, "value": emission.value.to_dict()}
        for emission in result.outputs
    ]
    receipt: dict[str, object] = {
        "kind": "vgi.signal8.execution",
        "schema_version": 1,
        "interpreter": {
            "name": "virtual-ground-interpreter",
            "version": vgi_version,
        },
        "system_ground": workload.ground.to_dict(),
        "computation_ground": {
            **SIGNAL8_GROUND.canonical_dict(),
            "fingerprint": SIGNAL8_GROUND.fingerprint,
        },
        "program": {
            "name": task.name,
            "fingerprint": result.program_fingerprint,
            "instruction_count": len(program.instructions),
        },
        "execution": {
            "halted": result.halted,
            "final_pc": result.final_pc,
            "step_count": len(result.trace),
            "outputs": outputs,
            "trace": result.trace_dicts(),
        },
        "checkpoint": snapshot,
    }
    receipt["execution_digest"] = _canonical_digest(receipt)
    return receipt


def make_vgi_signal8_operator(
    *,
    max_steps: int = 10_000,
) -> tuple[OperatorSpec, Callable[[Any, VirtualLayerWorkload], Any]]:
    """Create the declarative Signal8 operator and its node-local implementation."""
    _positive_integer(max_steps, "max_steps", 10_000_000)
    spec = OperatorSpec(
        operator_id=VGI_SIGNAL8_OPERATOR_ID,
        version=1,
        description=(
            "Compile and execute a typed Virtual Ground Interpreter Signal8 task "
            "under its exact computational Ground fingerprint"
        ),
        input_kind="object",
        output_kind="object",
        substrates=("cpu",),
        required_rights=frozenset({"compute"}),
        base_energy=32,
        energy_per_byte=1,
        max_input_bytes=1_000_000,
        max_output_bytes=2_000_000,
        deterministic=True,
        effect_mode="pure",
    )

    def handle(input_value: Any, workload: VirtualLayerWorkload) -> dict[str, object]:
        """Run the bounded VGI computation after Virtual Layer admission."""
        return execute_vgi_signal8(
            input_value,
            workload,
            max_configured_steps=max_steps,
        )

    return spec, handle


def register_vgi_signal8_operator(
    registry: OperatorRegistry,
    *,
    max_steps: int = 10_000,
) -> OperatorSpec:
    """Register the VGI Signal8 contract and trusted handler on one local node."""
    if not isinstance(registry, OperatorRegistry):
        raise TypeError("registry must be an OperatorRegistry")
    spec, handler = make_vgi_signal8_operator(max_steps=max_steps)
    registry.register(spec, handler)
    return spec
