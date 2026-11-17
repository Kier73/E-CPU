"""Bounded integer tensor tiles realized through the existing E-GPU/SIMT path.

A dispatch callback may use a local authorized E-GPU host or the existing
Transit/reliable-channel transport. Every depth chunk is one semantic operation;
the caller must allocate a distinct operation identity for each new chunk.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any, Callable, Mapping, Sequence

from .transit_simt import TransitSIMTHost


class TensorStreamError(ValueError):
    """Mathematics: reject invalid tensor shapes, budgets, arithmetic, and path receipts."""


def _digest(value: Any) -> str:
    """Mathematics: commit a JSON-representable observation to its canonical SHA-256 projection."""

    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")).hexdigest()


def _positive(value: Any, label: str) -> int:
    """Mathematics: admit only positive integral extents, not Boolean surrogates."""

    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise TensorStreamError(f"{label} must be a positive integer")
    return value


def _integers(values: Any, count: int, label: str, bits: int) -> list[int]:
    """Mathematics: enforce exact row-major cardinality and bounded integer membership."""

    if not isinstance(values, (list, tuple)) or len(values) != count:
        raise TensorStreamError(f"{label} must contain exactly {count} integer cells")
    for value in values:
        if not isinstance(value, int) or isinstance(value, bool):
            raise TensorStreamError(f"{label} cells must be integers")
        if value.bit_length() > bits:
            raise TensorStreamError(f"{label} cell exceeds SIMT integer bound")
    return list(values)


def compile_matmul_tile(
    payload: Mapping[str, Any], simt_host: TransitSIMTHost,
) -> tuple[int, dict[str, list[int]], list[list[Any]], int]:
    """Mathematics: map a row-major (r,c,k) tile to r*c lanes of k exact multiply-accumulates.

    The compiler never evaluates the dot products; it produces a bounded
    transition description consumed by TransitSIMTHost on the admitted host.
    """

    if not isinstance(payload, Mapping) or set(payload) != {
        "method", "shape", "left", "right", "accumulate", "max_steps",
    } or payload.get("method") != "tensor.matmul.tile":
        raise TensorStreamError("tensor tile payload fields or method are invalid")
    if not isinstance(simt_host, TransitSIMTHost):
        raise TypeError("tensor tile compiler requires a TransitSIMTHost")
    shape = payload["shape"]
    if not isinstance(shape, (tuple, list)) or len(shape) != 3:
        raise TensorStreamError("tensor tile shape must be [rows, cols, depth]")
    rows, cols, depth = (
        _positive(shape[0], "tile rows"),
        _positive(shape[1], "tile cols"),
        _positive(shape[2], "tile depth"),
    )
    lanes = rows * cols
    if lanes > simt_host.max_lanes:
        raise TensorStreamError("tensor tile exceeds SIMT lane bound")
    if (2 * depth + 1) * lanes > simt_host.max_input_elements:
        raise TensorStreamError("tensor tile exceeds SIMT input-element bound")
    instruction_count = 3 * depth + 3
    if instruction_count > simt_host.max_instructions:
        raise TensorStreamError("tensor tile exceeds SIMT instruction bound")
    budget = _positive(payload["max_steps"], "tensor tile step budget")
    if not instruction_count <= budget <= simt_host.max_steps:
        raise TensorStreamError("tensor tile step budget is outside SIMT bounds")

    bits = simt_host.max_integer_bits
    left = _integers(payload["left"], rows * depth, "left tile", bits)
    right = _integers(payload["right"], depth * cols, "right tile", bits)
    accumulate = _integers(payload["accumulate"], lanes, "accumulation tile", bits)

    inputs: dict[str, list[int]] = {"acc": accumulate}
    program: list[list[Any]] = [["load", "total", "acc"]]
    for k in range(depth):
        inputs[f"a{k}"] = [left[row * depth + k] for row in range(rows) for _ in range(cols)]
        inputs[f"b{k}"] = [right[k * cols + col] for _ in range(rows) for col in range(cols)]
        program.extend((
            ["load", "a", f"a{k}"],
            ["load", "b", f"b{k}"],
            ["mac", "total", "total", "a", "b"],
        ))
    program.extend((["store", "result", "total"], ["halt"]))
    return lanes, inputs, program, budget


def _matrix(
    values: Any, label: str, bits: int, max_elements: int,
) -> list[list[int]]:
    """Mathematics: admit one finite nonempty rectangular bounded integer matrix."""

    if not isinstance(values, (list, tuple)) or not values:
        raise TensorStreamError(f"{label} must be a non-empty row-major matrix")
    if not isinstance(values[0], (list, tuple)) or not values[0]:
        raise TensorStreamError(f"{label} requires non-empty rows")
    width = len(values[0])
    if len(values) * width > max_elements:
        raise TensorStreamError(f"{label} exceeds matrix element bound")
    return [_integers(row, width, f"{label} row", bits) for row in values]


def _verified_tile(
    response: Any, payload: Mapping[str, Any], bits: int, verify_semantics: bool,
) -> tuple[list[int], str]:
    """Mathematics: validate a returned E-GPU route receipt and optionally its independent dot-product oracle."""

    fields = {
        "host_id", "method", "capability", "capabilities", "route",
        "result_digest", "result", "receipt_digest",
    }
    if not isinstance(response, Mapping) or set(response) != fields:
        raise TensorStreamError("tensor tile response does not have an E-GPU receipt")
    if response["method"] != "tensor.matmul.tile" or response["capability"] != "simt.execute":
        raise TensorStreamError("tensor tile response used a different operation capability")
    if response["capabilities"] != ["simt.execute"]:
        raise TensorStreamError("tensor tile response capability sequence is invalid")
    route = response["route"]
    if (not isinstance(route, list) or len(route) < 3
            or any(not isinstance(p, str) or not p for p in route)):
        raise TensorStreamError("tensor tile response route is invalid")
    if not isinstance(response["host_id"], str) or not response["host_id"]:
        raise TensorStreamError("tensor tile host identity is invalid")
    result = response["result"]
    state_fields = ("lanes", "steps", "registers", "outputs", "mask_trace", "barriers")
    if not isinstance(result, Mapping) or set(result) != set(state_fields) | {"state_digest"}:
        raise TensorStreamError("tensor tile SIMT state fields are invalid")
    if result["state_digest"] != _digest({key: result[key] for key in state_fields}):
        raise TensorStreamError("tensor tile SIMT state digest mismatch")
    if response["result_digest"] != _digest(result):
        raise TensorStreamError("tensor tile result digest mismatch")
    receipt = {key: response[key] for key in fields - {"result", "receipt_digest"}}
    if response["receipt_digest"] != _digest(receipt):
        raise TensorStreamError("tensor tile receipt digest mismatch")
    rows, cols, depth = payload["shape"]
    if result["lanes"] != rows * cols or result["steps"] != 3 * depth + 3:
        raise TensorStreamError("tensor tile lane or instruction count mismatch")
    outputs = result["outputs"]
    if not isinstance(outputs, Mapping) or set(outputs) != {"result"}:
        raise TensorStreamError("tensor tile output name is invalid")
    cells = _integers(outputs["result"], rows * cols, "tensor result", bits)
    if verify_semantics:
        expected = list(payload["accumulate"])
        left, right = payload["left"], payload["right"]
        for k in range(depth):
            for row in range(rows):
                for col in range(cols):
                    i = row * cols + col
                    expected[i] += left[row * depth + k] * right[k * cols + col]
                    if expected[i].bit_length() > bits:
                        raise TensorStreamError("tensor oracle intermediate exceeds SIMT integer bound")
        if cells != expected:
            raise TensorStreamError("tensor tile fails independent integer oracle")
    return cells, response["receipt_digest"]


def execute_tiled_matmul(
    left: Sequence[Sequence[int]],
    right: Sequence[Sequence[int]],
    dispatch: Callable[[dict[str, Any]], Mapping[str, Any]],
    *,
    tile_rows: int = 8,
    tile_cols: int = 8,
    chunk_depth: int = 16,
    simt_host: TransitSIMTHost | None = None,
    max_matrix_elements: int = 1_048_576,
    max_work_units: int = 65_536,
    verify_semantics: bool = True,
    checkpoint: Mapping[str, Any] | None = None,
    checkpoint_sink: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Mathematics: realize C=A*B as a stream of bounded, receipt-verified SIMT tile transitions.

    Each output tile is independent; its depth chunks form an ordered chain
    whose next request carries the previous admitted accumulation. The dispatch
    callback must assign a fresh semantic operation identity per new request
    and use the same identity when retransmitting that request. Callback
    transport and authorization are external and remain authoritative.

    A checkpoint records a verified prefix, bound to this exact matrix and
    tiling plan. Recovery independently rechecks each retained receipt before
    skipping its dispatch. The sink owns durable atomic persistence; a failure
    before persistence may repeat the current pure operation. Neither restored
    receipts nor their hashes grant permission to dispatch remaining work.
    """

    if not callable(dispatch):
        raise TypeError("tensor dispatch must be callable")
    if not isinstance(verify_semantics, bool):
        raise TensorStreamError("verify_semantics must be Boolean")
    if checkpoint_sink is not None and not callable(checkpoint_sink):
        raise TypeError("tensor checkpoint sink must be callable")
    if not verify_semantics and (checkpoint is not None or checkpoint_sink is not None):
        raise TensorStreamError("tensor recovery requires independent semantic verification")
    host = simt_host or TransitSIMTHost()
    _positive(max_matrix_elements, "matrix element bound")
    _positive(max_work_units, "tensor work-unit bound")
    tile_rows = _positive(tile_rows, "tile rows")
    tile_cols = _positive(tile_cols, "tile cols")
    chunk_depth = _positive(chunk_depth, "chunk depth")
    if tile_rows * tile_cols > host.max_lanes:
        raise TensorStreamError("configured tile exceeds SIMT lane bound")
    if (2 * chunk_depth + 1) * tile_rows * tile_cols > host.max_input_elements:
        raise TensorStreamError("configured tile exceeds SIMT input-element bound")
    if 3 * chunk_depth + 3 > min(host.max_steps, host.max_instructions):
        raise TensorStreamError("configured chunk exceeds SIMT program bound")

    a = _matrix(left, "left matrix", host.max_integer_bits, max_matrix_elements)
    b = _matrix(right, "right matrix", host.max_integer_bits, max_matrix_elements)
    m, k, n = len(a), len(a[0]), len(b[0])
    if len(b) != k:
        raise TensorStreamError("tensor contraction dimensions do not match")
    if m * n > max_matrix_elements:
        raise TensorStreamError("tensor result exceeds matrix element bound")

    work_units = (
        ((m + tile_rows - 1) // tile_rows)
        * ((n + tile_cols - 1) // tile_cols)
        * ((k + chunk_depth - 1) // chunk_depth)
    )
    if work_units > max_work_units:
        raise TensorStreamError("tensor plan exceeds work-unit bound")
    plan_digest = _digest({
        "schema": "mailcpu.tensor-matmul-plan.v1", "left": a, "right": b,
        "tile_rows": tile_rows, "tile_cols": tile_cols, "chunk_depth": chunk_depth,
    })
    completed: list[dict[str, Any]] = []
    if checkpoint is not None:
        if not isinstance(checkpoint, Mapping) or set(checkpoint) != {
            "schema", "plan_digest", "tiles", "checkpoint_digest",
        }:
            raise TensorStreamError("tensor checkpoint fields are invalid")
        saved = deepcopy(dict(checkpoint))
        if (saved["schema"] != "mailcpu.tensor-matmul-checkpoint.v1"
                or saved["plan_digest"] != plan_digest):
            raise TensorStreamError("tensor checkpoint belongs to a different plan")
        if saved["checkpoint_digest"] != _digest({
            key: value for key, value in saved.items() if key != "checkpoint_digest"
        }):
            raise TensorStreamError("tensor checkpoint digest mismatch")
        if not isinstance(saved["tiles"], list) or len(saved["tiles"]) > work_units:
            raise TensorStreamError("tensor checkpoint prefix exceeds plan")
        completed = saved["tiles"]
    output = [[0 for _ in range(n)] for _ in range(m)]
    receipt_digests: list[str] = []
    for row_offset in range(0, m, tile_rows):
        rows = min(tile_rows, m - row_offset)
        for col_offset in range(0, n, tile_cols):
            cols = min(tile_cols, n - col_offset)
            accum = [0] * (rows * cols)
            for depth_offset in range(0, k, chunk_depth):
                depth = min(chunk_depth, k - depth_offset)
                tile_left = [
                    a[row][depth_offset + step]
                    for row in range(row_offset, row_offset + rows)
                    for step in range(depth)
                ]
                tile_right = [
                    b[depth_offset + step][col]
                    for step in range(depth)
                    for col in range(col_offset, col_offset + cols)
                ]
                payload = {
                    "method": "tensor.matmul.tile",
                    "shape": [rows, cols, depth],
                    "left": tile_left,
                    "right": tile_right,
                    "accumulate": accum,
                    "max_steps": 3 * depth + 3,
                }
                # Verify the generated request under the same SIMT resource contract.
                compile_matmul_tile(payload, host)
                index = len(receipt_digests)
                payload_digest = _digest(payload)
                if index < len(completed):
                    tile = completed[index]
                    if (not isinstance(tile, dict)
                            or set(tile) != {"payload_digest", "response"}
                            or tile["payload_digest"] != payload_digest):
                        raise TensorStreamError("tensor checkpoint tile does not bind ordered request")
                    response = tile["response"]
                else:
                    # The callback must not alter the verifier's mathematical intention.
                    response = deepcopy(dispatch(deepcopy(payload)))
                accum, receipt_digest = _verified_tile(
                    response, payload, host.max_integer_bits, verify_semantics,
                )
                receipt_digests.append(receipt_digest)
                if index == len(completed) and checkpoint_sink is not None:
                    completed.append({"payload_digest": payload_digest, "response": response})
                    progress = {
                        "schema": "mailcpu.tensor-matmul-checkpoint.v1",
                        "plan_digest": plan_digest, "tiles": completed,
                    }
                    checkpoint_sink(deepcopy({**progress, "checkpoint_digest": _digest(progress)}))
            for dr in range(rows):
                for dc in range(cols):
                    output[row_offset + dr][col_offset + dc] = accum[dr * cols + dc]

    result_digest = _digest(output)
    evidence = {
        "shape": [m, n],
        "work_units": work_units,
        "result_digest": result_digest,
        "tile_receipt_digests": receipt_digests,
        "verification": "independent-integer-oracle" if verify_semantics else "receipt-integrity-only",
    }
    return {
        **evidence, "values": output, "execution_digest": _digest(evidence),
    }
