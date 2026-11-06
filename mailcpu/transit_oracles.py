"""Independent, bounded semantic oracles for receiver-side Transit operations.

The oracle implementations intentionally do not call the production CPU
instruction transition function or Structural Memory generator adapter.
They compare a second derivation with the effect produced by the admitted
backend, then store the exact observation pair and deterministic work cost.
"""

from __future__ import annotations

from typing import Any, Mapping

from .assembler import AssemblyError, assemble
from .classifier import HypervisorArbitrationEvent
from .model import Op
from .semantic_translation import (
    SemanticTranslationError,
    TransitOracleEvidence,
    _CPU_ORACLE_PROJECTION_DIGEST,
    _CPU_ORACLE_REF,
    _STRUCTURAL_MEMORY_ORACLE_PROJECTION_DIGEST,
    _STRUCTURAL_MEMORY_ORACLE_REF,
    _transit_oracle_effect_projection,
    canonical_value_digest,
)
from .structural_memory import (
    StructuralMemoryError,
    StructuralMemoryVersion,
)
from .transit_structural_memory import (
    TRANSIT_STRUCTURAL_MEMORY_OPERATION,
    TRANSIT_STRUCTURAL_MEMORY_RESOURCE,
)

_CPU_OPERATION = "execute deterministic CPU arithmetic program"
_CPU_RESOURCE = "/cpu/compute"
_CPU_RIGHTS = frozenset({"execute"})
_SM_RIGHTS = frozenset({"read"})

MAX_CPU_ORACLE_SOURCE_BYTES = 16_384
MAX_CPU_ORACLE_INSTRUCTIONS = 512
MAX_CPU_ORACLE_REGISTERS = 32
MAX_CPU_ORACLE_TICKS = 10_000

MAX_STRUCTURAL_ORACLE_WORK_UNITS = 1_000_000
MAX_STRUCTURAL_ORACLE_INTEGER_BITS = 4_096
MAX_GF2_ORACLE_ORDER = 64


class TransitOracleError(ValueError):
    """The independent Transit oracle cannot safely derive or match a result."""


def _strict_integer(value: Any, name: str, *, minimum: int | None = None) -> int:
    if type(value) is not int:
        raise TransitOracleError(f"{name} must be a strict integer")
    if minimum is not None and value < minimum:
        raise TransitOracleError(f"{name} must be at least {minimum}")
    return value


def _fingerprint(event: HypervisorArbitrationEvent) -> str:
    return canonical_value_digest(event.to_dict())


def _cpu_expected_observation(event: HypervisorArbitrationEvent) -> tuple[dict[str, Any], int, dict[str, Any]]:
    """Evaluate the bounded arithmetic ISA without using apply_instruction or a VM."""
    request = event.request
    if request.operation != _CPU_OPERATION or request.resource != _CPU_RESOURCE:
        raise TransitOracleError("CPU oracle received an unexpected operation identity")
    if request.required_rights != _CPU_RIGHTS or request.granted_rights != _CPU_RIGHTS:
        raise TransitOracleError("CPU oracle requires exact receiver-authorized execute rights")
    if request.destructive:
        raise TransitOracleError("CPU oracle refuses destructive requests")

    payload = request.payload
    if not isinstance(payload, Mapping) or set(payload) != {
        "source", "initial_registers", "max_ticks"
    }:
        raise TransitOracleError("CPU oracle request payload fields are invalid")
    source = payload["source"]
    if not isinstance(source, str) or not source.strip():
        raise TransitOracleError("CPU oracle source must be non-empty text")
    if len(source.encode("utf-8")) > MAX_CPU_ORACLE_SOURCE_BYTES:
        raise TransitOracleError("CPU oracle source exceeds its byte limit")

    initial = payload["initial_registers"]
    if not isinstance(initial, Mapping) or len(initial) > MAX_CPU_ORACLE_REGISTERS:
        raise TransitOracleError("CPU oracle initial-register map exceeds its limit")
    registers: dict[str, int] = {}
    for name, value in initial.items():
        if (
            not isinstance(name, str)
            or not name
            or len(name) > 64
            or not (name[0].isalpha() or name[0] == "_")
            or any(not (ch.isalnum() or ch == "_") for ch in name)
            or type(value) is not int
        ):
            raise TransitOracleError("CPU oracle initial-register entry is invalid")
        registers[name] = value

    budget = _strict_integer(payload["max_ticks"], "CPU oracle max_ticks", minimum=1)
    if budget > MAX_CPU_ORACLE_TICKS:
        raise TransitOracleError("CPU oracle tick budget exceeds its fixed limit")

    try:
        program = assemble(source)
    except (AssemblyError, TypeError, ValueError) as exc:
        raise TransitOracleError(f"CPU oracle could not assemble the request: {exc}") from exc
    if not program.instructions or len(program.instructions) > MAX_CPU_ORACLE_INSTRUCTIONS:
        raise TransitOracleError("CPU oracle instruction count exceeds its fixed limit")
    if any(instruction.op not in {Op.SET, Op.COPY, Op.ADD, Op.COMPARE, Op.BRANCH, Op.HALT}
           for instruction in program.instructions):
        raise TransitOracleError("CPU oracle refuses an opcode outside the pure arithmetic subset")

    # This evaluator is intentionally explicit instead of reusing the
    # production apply_instruction relation. Its work unit is one fetched
    # instruction; HALT is a fetched instruction and is counted.
    pc = 0
    steps = 0
    halted = False
    while steps < budget:
        if pc < 0 or pc >= len(program.instructions):
            raise TransitOracleError("CPU oracle program counter escaped the admitted program")
        instruction = program.instructions[pc]
        args = instruction.args

        if instruction.op is Op.SET:
            registers[args[0]] = args[1]
            next_pc = pc + 1
        elif instruction.op is Op.COPY:
            registers[args[0]] = registers.get(args[1], 0)
            next_pc = pc + 1
        elif instruction.op is Op.ADD:
            registers[args[0]] = registers.get(args[1], 0) + registers.get(args[2], 0)
            next_pc = pc + 1
        elif instruction.op is Op.COMPARE:
            left = registers.get(args[1], 0)
            right = registers.get(args[2], 0)
            registers[args[0]] = int(left > right) - int(left < right)
            next_pc = pc + 1
        elif instruction.op is Op.BRANCH:
            next_pc = args[1] if registers.get(args[0], 0) != 0 else pc + 1
        elif instruction.op is Op.HALT:
            next_pc = pc
            halted = True
        else:  # Defensive: the allowed-op check above is the admission gate.
            raise TransitOracleError(f"CPU oracle has no rule for {instruction.op.value}")

        pc = next_pc
        steps += 1
        if halted:
            break

    if not halted:
        raise TransitOracleError("CPU oracle exhausted the tick budget without HALT")

    observation = {
        "status": "exited",
        "exit_code": 0,
        "pc": pc,
        "steps": steps,
        "registers": dict(sorted(registers.items())),
    }
    case = {
        "request_fingerprint": _fingerprint(event),
        "source": source,
        "initial_registers": dict(sorted(initial.items())),
        "max_ticks": budget,
    }
    return observation, steps, case


def _compose_affine(
    left: tuple[int, int],
    right: tuple[int, int],
    modulus: int,
) -> tuple[int, int]:
    """Return left ∘ right for maps x ↦ ax+b over Z/modulus Z."""
    la, lb = left
    ra, rb = right
    return (la * ra) % modulus, (la * rb + lb) % modulus


def _reference_lcg_value(params: Mapping[str, Any], coordinate: int) -> tuple[int, int]:
    """Binary affine-map exponentiation independent of the production LCG helper."""
    modulus = params["mod"]
    if modulus <= 1:
        return 0, 1
    result = (1 % modulus, 0)
    base = (params["a"] % modulus, params["c"] % modulus)
    exponent = coordinate
    work = 0
    while exponent:
        if exponent & 1:
            result = _compose_affine(base, result, modulus)
            work += 1
        exponent >>= 1
        if exponent:
            base = _compose_affine(base, base, modulus)
            work += 1
    value = (result[0] * params["x0"] + result[1]) % modulus
    return value, max(1, work + 1)


def _reference_gf2_value(params: Mapping[str, Any], order: int, coordinate: int) -> tuple[int, int]:
    """Bit-packed companion-matrix powering over GF(2), independent of lfsr_jump."""
    if order <= 0 or order > MAX_GF2_ORACLE_ORDER:
        raise TransitOracleError(
            f"GF(2) oracle order must be between 1 and {MAX_GF2_ORACLE_ORDER}"
        )
    coefficients = params["C"]
    initial = params["init"]
    if len(initial) != order or len(coefficients) < order + 1:
        raise TransitOracleError("GF(2) oracle received inconsistent recurrence dimensions")

    # Each integer stores one matrix row. Bit j is the coefficient of state[j].
    rows = [1 << (index + 1) for index in range(order - 1)]
    last_row = 0
    for recurrence_index in range(1, min(len(coefficients), order + 1)):
        if coefficients[recurrence_index]:
            last_row |= 1 << (order - recurrence_index)
    rows.append(last_row)
    state = sum(bit << index for index, bit in enumerate(initial))

    exponent = coordinate
    work = 0
    while exponent:
        if exponent & 1:
            next_state = 0
            for row_index, row in enumerate(rows):
                next_state |= ((row & state).bit_count() & 1) << row_index
                work += 1
            state = next_state
        exponent >>= 1
        if exponent:
            squared: list[int] = []
            for row in rows:
                composed_row = 0
                remaining = row
                while remaining:
                    low_bit = remaining & -remaining
                    source_index = low_bit.bit_length() - 1
                    composed_row ^= rows[source_index]
                    remaining ^= low_bit
                    work += 1
                squared.append(composed_row)
                work += 1
            rows = squared
        if work > MAX_STRUCTURAL_ORACLE_WORK_UNITS:
            raise TransitOracleError("GF(2) oracle exceeded its deterministic work limit")

    return state & 1, max(1, work)


def _reference_structural_value(
    spec: Any,
    coordinate: int,
) -> tuple[int, int]:
    """Derive one value from the admitted parameter schema without the generator adapter."""
    if coordinate.bit_length() > MAX_STRUCTURAL_ORACLE_INTEGER_BITS:
        raise TransitOracleError("Structural Memory coordinate exceeds the oracle integer-width limit")
    params = spec.parameters

    def check_integer_width(value: Any, path: str = "parameters") -> None:
        if type(value) is int and value.bit_length() > MAX_STRUCTURAL_ORACLE_INTEGER_BITS:
            raise TransitOracleError(f"Structural Memory {path} exceeds the oracle integer-width limit")
        if isinstance(value, Mapping):
            for key, item in value.items():
                check_integer_width(item, f"{path}.{key}")
        elif isinstance(value, (list, tuple)):
            for index, item in enumerate(value):
                check_integer_width(item, f"{path}[{index}]")

    check_integer_width(params)
    family = spec.family

    if family == "int":
        value = (params["x0"] + params["step"] * coordinate) % params["mod"]
        return value, 1
    if family == "lcg":
        return _reference_lcg_value(params, coordinate)
    if family == "gf2":
        return _reference_gf2_value(params, spec.order, coordinate)
    if family == "fgraph":
        mu = params["mu"]
        lam = params["lam"]
        index = coordinate if coordinate < mu else mu + ((coordinate - mu) % lam)
        return params["orbit"][index], 1
    raise TransitOracleError(f"Structural Memory oracle does not admit family {family!r}")


def _read_version(
    operating_system: Any,
    memory_id: str,
    revision: int,
) -> StructuralMemoryVersion:
    registry = getattr(operating_system, "structural_memory", None)
    if registry is None or not callable(getattr(registry, "version_for_revision", None)):
        raise TransitOracleError("receiver does not expose exact admitted Structural Memory revisions")
    try:
        version = registry.version_for_revision(memory_id, revision)
    except StructuralMemoryError as exc:
        raise TransitOracleError(f"pinned Structural Memory revision cannot be resolved: {exc}") from exc
    if not isinstance(version, StructuralMemoryVersion):
        raise TransitOracleError("receiver returned an invalid Structural Memory version")
    return version


def _structural_expected_observation(
    event: HypervisorArbitrationEvent,
    operating_system: Any,
) -> tuple[dict[str, Any], int, dict[str, Any]]:
    request = event.request
    if (
        request.operation != TRANSIT_STRUCTURAL_MEMORY_OPERATION
        or request.resource != TRANSIT_STRUCTURAL_MEMORY_RESOURCE
    ):
        raise TransitOracleError("Structural Memory oracle received an unexpected operation identity")
    if request.required_rights != _SM_RIGHTS or request.granted_rights != _SM_RIGHTS:
        raise TransitOracleError("Structural Memory oracle requires exact receiver-authorized read rights")
    if request.destructive:
        raise TransitOracleError("Structural Memory oracle refuses destructive reads")

    payload = request.payload
    if not isinstance(payload, Mapping) or set(payload) != {
        "memory_id", "revision", "context", "coordinate"
    }:
        raise TransitOracleError("Structural Memory oracle request fields are invalid")
    memory_id = payload["memory_id"]
    revision = _strict_integer(payload["revision"], "Structural Memory revision", minimum=1)
    coordinate = _strict_integer(payload["coordinate"], "Structural Memory coordinate", minimum=0)
    context = payload["context"]
    if not isinstance(memory_id, str) or not memory_id.strip():
        raise TransitOracleError("Structural Memory memory_id is invalid")
    if not isinstance(context, Mapping):
        raise TransitOracleError("Structural Memory context must be an object")

    version = _read_version(operating_system, memory_id, revision)
    spec = version.spec
    certificate = version.certificate
    if spec.memory_id != memory_id or spec.revision != revision:
        raise TransitOracleError("resolved Structural Memory version does not match the request")
    registry = operating_system.structural_memory
    try:
        context_digest = registry.navigator.validate(
            spec,
            certificate,
            coordinate,
            context=context,
        )
    except StructuralMemoryError as exc:
        raise TransitOracleError(f"Structural Memory context or horizon refused: {exc}") from exc

    value, work_units = _reference_structural_value(spec, coordinate)
    if work_units > MAX_STRUCTURAL_ORACLE_WORK_UNITS:
        raise TransitOracleError("Structural Memory oracle exceeded its deterministic work limit")

    # This digest schema matches StructuralMemoryReadReceipt.value_digest,
    # but is derived here rather than copied from the production receipt.
    value_digest = canonical_value_digest({"type": "integer", "value": value})
    observation = {
        "memory_id": spec.memory_id,
        "revision": spec.revision,
        "spec_digest": spec.digest,
        "certificate_digest": certificate.digest,
        "coordinate": coordinate,
        "context_digest": context_digest,
        "value": value,
        "value_digest": value_digest,
        "verification_class": certificate.verification_class.value,
        "witness_digest": certificate.witness_digest,
    }
    case = {
        "request_fingerprint": _fingerprint(event),
        "spec_digest": spec.digest,
        "certificate_digest": certificate.digest,
        "coordinate": coordinate,
        "context_digest": context_digest,
    }
    return observation, work_units, case


def build_transit_oracle_evidence(
    event: HypervisorArbitrationEvent,
    effect: Mapping[str, Any],
    operating_system: Any,
) -> TransitOracleEvidence | None:
    """Build a bounded independent semantic comparison for supported Transit paths.

    Unsupported operation/resource pairs return None. Supported pairs fail
    closed: a mismatch, malformed case, or exhausted oracle budget prevents
    the caller from committing the handler effect.
    """
    if not isinstance(event, HypervisorArbitrationEvent):
        raise TransitOracleError("Transit oracle requires a typed arbitration event")
    if not isinstance(effect, Mapping):
        raise TransitOracleError("Transit oracle effect must be an object")

    if event.request.operation == _CPU_OPERATION and event.request.resource == _CPU_RESOURCE:
        expected, work_units, case = _cpu_expected_observation(event)
        oracle_ref = _CPU_ORACLE_REF
        projection_digest = _CPU_ORACLE_PROJECTION_DIGEST
    elif (
        event.request.operation == TRANSIT_STRUCTURAL_MEMORY_OPERATION
        and event.request.resource == TRANSIT_STRUCTURAL_MEMORY_RESOURCE
    ):
        expected, work_units, case = _structural_expected_observation(event, operating_system)
        oracle_ref = _STRUCTURAL_MEMORY_ORACLE_REF
        projection_digest = _STRUCTURAL_MEMORY_ORACLE_PROJECTION_DIGEST
    else:
        return None

    observed = _transit_oracle_effect_projection(oracle_ref.type_id, effect)
    equivalent = canonical_value_digest(expected) == canonical_value_digest(observed)
    evidence = TransitOracleEvidence(
        oracle=oracle_ref,
        request_fingerprint=_fingerprint(event),
        case_digest=canonical_value_digest(case),
        projection_digest=projection_digest,
        expected_observation=expected,
        observed_observation=observed,
        work_units=work_units,
        work_limit=(
            MAX_CPU_ORACLE_TICKS
            if oracle_ref == _CPU_ORACLE_REF
            else MAX_STRUCTURAL_ORACLE_WORK_UNITS
        ),
        equivalent=equivalent,
    )
    if not evidence.equivalent:
        raise TransitOracleError(
            f"{oracle_ref.type_id} disagrees with the committed backend projection"
        )
    return evidence
