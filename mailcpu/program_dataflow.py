"""Compile a bounded pure MailCPU program into a register dataflow DAG.

The compiler preserves exact program, initial-state, Ground, and observation
identities. It does not execute remote code or select an execution host.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import re
from typing import Any, Mapping, Sequence

from .assembler import AssemblyError, assemble
from .computation_dag import (
    ComputationDAGError,
    ComputationNode,
    NavigableComputationDAG,
)
from .interpreter import ReferenceInterpreter, compare_values
from .model import Op, Program, RunStatus
from .semantic_translation import (
    EffectClass,
    ObservationComparison,
    ObservationContract,
    ReplayClass,
    RepresentationRef,
    ResourceBound,
    TranslationContract,
    canonical_value_digest,
    compare_projected_observations,
    program_representation_ref,
)
from .structural_memory import StructuralMemoryReadReceipt
from .orbit_fabric import ContextualOrbitDataflowInput
from .virtual_layer import VirtualStructuralMemoryRef


_SCHEMA = "mailcpu.program-dataflow.v3"
_COMPILER_ID = "mailcpu.register-dataflow"
_COMPILER_VERSION = 4
_MAX_INSTRUCTIONS = 256
_MAX_CONTEXTUAL_ORBIT_INPUTS = 64
_MAX_SOURCE_BYTES = 65_536
_REGISTER = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}\Z")
_SUPPORTED = frozenset({Op.SET, Op.COPY, Op.ADD, Op.MUL, Op.COMPARE})
_GROUND_DEFINITION = {
    "identity": "mailcpu.computational-ground.register-dataflow",
    "version": 2,
    "register_domain": "strict-integers",
    "instruction_semantics": {
        "SET": "R[d] := immediate",
        "COPY": "R[d] := R[s]",
        "ADD": "R[d] := R[l] + R[r]",
        "MUL": "R[d] := R[l] * R[r]",
        "COMPARE": "R[d] := sign(R[l] - R[r])",
        "HALT": "stop at the declared terminal instruction",
    },
    "control_flow": "straight-line",
    "effects": "pure",
    "terminal_observation": ["status", "pc", "steps", "halted", "blocked", "registers"],
}
_OBSERVATION_DEFINITION = {
    "identity": "mailcpu.program.terminal-register-state",
    "version": 1,
    "fields": ["status", "pc", "steps", "halted", "blocked", "registers"],
    "comparison": "exact canonical JSON",
}
_COMPILER_DEFINITION = {
    "identity": _COMPILER_ID,
    "version": _COMPILER_VERSION,
    "algorithm": "instruction-order register-definition graph",
    "node_bound": _MAX_INSTRUCTIONS,
    "edge_bound": NavigableComputationDAG.MAX_EDGES,
    "supported_opcodes": ["SET", "COPY", "ADD", "MUL", "COMPARE", "HALT"],
    "unsupported_control_flow": ["BRANCH"],
    "unsupported_effects": ["SEND", "WAIT", "SYSCALL"],
    "initial_sources": ["inline-integer", "materialized-structural-memory-receipt", "symbolic-virtual-structural-memory-reference", "verified-contextual-orbit-predecessor"],
    "contextual_orbit_input_bound": _MAX_CONTEXTUAL_ORBIT_INPUTS,
}
_INVARIANT_DEFINITIONS = (
    {
        "id": "pure-opcode-subset",
        "statement": "Only SET, COPY, ADD, MUL, COMPARE, and terminal HALT are admitted.",
    },
    {
        "id": "straight-line-control",
        "statement": "The program contains no branch, blocking, or external-effect transition.",
    },
    {
        "id": "integer-register-algebra",
        "statement": "Every register input, immediate, and result is a strict integer.",
    },
    {
        "id": "single-definition-dataflow",
        "statement": "Every register read is bound to its latest earlier definition or an exact initial value.",
    },
    {
        "id": "terminal-observation",
        "statement": "The declared observable is the final register state and terminal HALT boundary, not the instruction trace.",
    },
    {
        "id": "contextual-orbit-predecessor",
        "statement": "A contextual-orbit input is a typed predecessor node whose selected coordinate/value and complete routed observer/read evidence are bound into the plan; no trajectory is copied or replayed.",
    },
)


class ProgramDataflowError(ValueError):
    """A program is outside the compiler subset or its structural plan is inconsistent."""


def _strict_int(value: Any, label: str, *, minimum: int | None = None) -> int:
    """Mathematics: enforce strict integer membership and an optional lower bound."""
    if type(value) is not int:
        raise ProgramDataflowError(f"{label} must be a strict integer")
    if minimum is not None and value < minimum:
        raise ProgramDataflowError(f"{label} must be greater than or equal to {minimum}")
    return value


def _canonical(value: Any) -> bytes:
    """Mathematics: encode one finite JSON value in canonical UTF-8 form."""
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ProgramDataflowError("value is outside the canonical JSON algebra") from exc


def _register(value: Any, label: str) -> str:
    """Mathematics: restrict register identifiers to the bounded Transit-safe alphabet."""
    if not isinstance(value, str) or _REGISTER.fullmatch(value) is None:
        raise ProgramDataflowError(
            f"{label} must match [A-Za-z_][A-Za-z0-9_]{{0,63}}"
        )
    return value


def _initial_value_digest(register: str, value: int) -> str:
    """Mathematics: bind one initial register name and integer value to a canonical digest."""
    return canonical_value_digest({
        "type": "initial-register",
        "register": register,
        "value": value,
    })


@dataclass(frozen=True)
class RegisterSource:
    """The final definition selected for one observable register."""

    register: str
    kind: str
    source_digest: str
    value: int | None = None
    node_id: str | None = None
    memory_reference: VirtualStructuralMemoryRef | None = None

    def __post_init__(self) -> None:
        """Mathematics: validate one final register source as inline, node-derived, or symbolically memory-addressed."""
        _register(self.register, "register source name")
        if self.kind not in {"initial", "node", "structural_memory"}:
            raise ProgramDataflowError("register source kind must be initial, node, or structural_memory")
        if not isinstance(self.source_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", self.source_digest):
            raise ProgramDataflowError("register source digest must be lowercase SHA-256")
        if self.kind == "initial":
            _strict_int(self.value, f"initial value for {self.register}")
            if self.node_id is not None or self.memory_reference is not None:
                raise ProgramDataflowError("inline initial source cannot name a node or memory reference")
        elif self.kind == "node":
            if self.value is not None or self.memory_reference is not None:
                raise ProgramDataflowError("node register source cannot embed an initial value or memory reference")
            if not isinstance(self.node_id, str) or not self.node_id:
                raise ProgramDataflowError("node register source requires a node ID")
        else:
            if self.value is not None or self.node_id is not None:
                raise ProgramDataflowError("symbolic memory source cannot embed a value or node ID")
            if not isinstance(self.memory_reference, VirtualStructuralMemoryRef):
                raise ProgramDataflowError("symbolic memory source requires a VirtualStructuralMemoryRef")
            if self.memory_reference.binding != self.register:
                raise ProgramDataflowError("symbolic memory binding must match its source register")

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize the exact final-register source identity and any pinned memory address."""
        return {
            "register": self.register,
            "kind": self.kind,
            "source_digest": self.source_digest,
            "value": self.value,
            "node_id": self.node_id,
            "memory_reference": None if self.memory_reference is None else self.memory_reference.to_dict(),
        }


@dataclass(frozen=True)
class ProgramDataflowMetrics:
    """Structural work/depth profile; these are not measured speedup figures."""

    work_units: int
    dependency_edges: int
    critical_path_nodes: int
    max_frontier_width: int
    theoretical_parallelism: float
    graph_description_bytes: int
    topology_candidate: str
    recommendation_basis: str = "structural-frontier-only"

    def __post_init__(self) -> None:
        """Mathematics: validate the non-negative work/depth profile and its topology label."""
        for name in (
            "work_units",
            "dependency_edges",
            "critical_path_nodes",
            "max_frontier_width",
            "graph_description_bytes",
        ):
            _strict_int(getattr(self, name), name, minimum=0)
        if not isinstance(self.theoretical_parallelism, (int, float)) or not math.isfinite(
            self.theoretical_parallelism
        ) or self.theoretical_parallelism < 0:
            raise ProgramDataflowError("theoretical_parallelism must be finite and non-negative")
        if self.topology_candidate not in {"sequential", "dataflow"}:
            raise ProgramDataflowError("unknown topology candidate")
        if self.recommendation_basis != "structural-frontier-only":
            raise ProgramDataflowError("unsupported recommendation basis")

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize each structural work and frontier metric without unit conversion."""
        return {
            "work_units": self.work_units,
            "dependency_edges": self.dependency_edges,
            "critical_path_nodes": self.critical_path_nodes,
            "max_frontier_width": self.max_frontier_width,
            "theoretical_parallelism": self.theoretical_parallelism,
            "graph_description_bytes": self.graph_description_bytes,
            "topology_candidate": self.topology_candidate,
            "recommendation_basis": self.recommendation_basis,
        }


@dataclass(frozen=True)
class CompiledMailCPUDataflow:
    """Identity-bound atlas and dependency graph compiled from one MailCPU program."""

    source_bytes_ref: RepresentationRef | None
    source_size_bytes: int | None
    program_ref: RepresentationRef
    initial_state_ref: RepresentationRef
    computational_ground: RepresentationRef
    dataflow_representation: RepresentationRef
    observation: ObservationContract
    translation: TranslationContract
    context_digest: str
    initial_registers: tuple[tuple[str, int], ...]
    structural_memory_reads: tuple[tuple[str, StructuralMemoryReadReceipt], ...]
    structural_memory_refs: tuple[tuple[str, VirtualStructuralMemoryRef], ...]
    nodes: tuple[ComputationNode, ...]
    final_register_sources: tuple[RegisterSource, ...]
    frontiers: tuple[tuple[str, ...], ...]
    metrics: ProgramDataflowMetrics
    contextual_orbit_inputs: tuple[tuple[str, ContextualOrbitDataflowInput], ...] = ()

    def __post_init__(self) -> None:
        """Mathematics: revalidate atlas identities, immutable inputs, graph topology, and translation bindings."""
        if self.source_bytes_ref is None:
            if self.source_size_bytes is not None:
                raise ProgramDataflowError("source byte length requires a source representation")
        else:
            if type(self.source_size_bytes) is not int or self.source_size_bytes < 0:
                raise ProgramDataflowError("source byte length must be a non-negative integer")
        for name in (
            "program_ref",
            "initial_state_ref",
            "computational_ground",
            "dataflow_representation",
        ):
            if not isinstance(getattr(self, name), RepresentationRef):
                raise ProgramDataflowError(f"{name} must be a RepresentationRef")
        if not isinstance(self.observation, ObservationContract):
            raise ProgramDataflowError("observation must be an ObservationContract")
        if not isinstance(self.translation, TranslationContract):
            raise ProgramDataflowError("translation must be a TranslationContract")
        if not re.fullmatch(r"[0-9a-f]{64}", self.context_digest):
            raise ProgramDataflowError("context_digest must be lowercase SHA-256")
        registers = tuple(self.initial_registers)
        if registers != tuple(sorted(registers)) or len({key for key, _ in registers}) != len(registers):
            raise ProgramDataflowError("initial registers must be uniquely sorted")
        for name, value in registers:
            _register(name, "initial register")
            _strict_int(value, f"initial register {name}")
        receipts = tuple(self.structural_memory_reads)
        if receipts != tuple(sorted(receipts, key=lambda item: item[0])):
            raise ProgramDataflowError("structural-memory receipts must be sorted by register")
        for name, receipt in receipts:
            _register(name, "structural-memory register")
            if not isinstance(receipt, StructuralMemoryReadReceipt):
                raise ProgramDataflowError("structural-memory inputs must be typed read receipts")
        references = tuple(self.structural_memory_refs)
        if references != tuple(sorted(references, key=lambda item: item[0])):
            raise ProgramDataflowError("symbolic Structural Memory references must be sorted by register")
        for name, reference in references:
            _register(name, "symbolic Structural Memory register")
            if not isinstance(reference, VirtualStructuralMemoryRef) or reference.binding != name:
                raise ProgramDataflowError("symbolic Structural Memory references must be typed and bound to their register")
        orbit_inputs = tuple(self.contextual_orbit_inputs)
        if orbit_inputs != tuple(sorted(orbit_inputs, key=lambda item: item[0])):
            raise ProgramDataflowError("contextual-orbit inputs must be sorted by register")
        if len(orbit_inputs) > _MAX_CONTEXTUAL_ORBIT_INPUTS:
            raise ProgramDataflowError("contextual-orbit inputs exceed the compiler bound")
        for name, predecessor in orbit_inputs:
            _register(name, "contextual-orbit register")
            if not isinstance(predecessor, ContextualOrbitDataflowInput):
                raise ProgramDataflowError("contextual-orbit inputs must be typed verified predecessors")
        supplied_names = [name for name, _ in registers] + [name for name, _ in receipts] + [name for name, _ in references] + [name for name, _ in orbit_inputs]
        if len(supplied_names) != len(set(supplied_names)):
            raise ProgramDataflowError("registers cannot be supplied by multiple inline, Structural Memory, or contextual-orbit sources: " + ", ".join(sorted(set(supplied_names))))
        object.__setattr__(self, "structural_memory_refs", references)
        object.__setattr__(self, "contextual_orbit_inputs", orbit_inputs)
        initial_state_payload = {
            "registers": {
                **dict(registers),
                **{name: receipt.value for name, receipt in receipts},
            },
            "structural_memory_receipts": {
                name: receipt.to_dict() for name, receipt in receipts
            },
            "structural_memory_refs": {
                name: reference.to_dict() for name, reference in references
            },
            "contextual_orbit_inputs": {
                name: predecessor.to_dict() for name, predecessor in orbit_inputs
            },
        }
        if canonical_value_digest(initial_state_payload) != self.initial_state_ref.content_digest:
            raise ProgramDataflowError("initial-state representation does not identify its inline, receipt, symbolic, and contextual-orbit inputs")
        nodes = tuple(self.nodes)
        if not nodes or any(not isinstance(item, ComputationNode) for item in nodes):
            raise ProgramDataflowError("dataflow plan requires typed computation nodes")
        object.__setattr__(self, "nodes", nodes)
        sources = tuple(self.final_register_sources)
        if sources != tuple(sorted(sources, key=lambda item: item.register)):
            raise ProgramDataflowError("final register sources must be uniquely sorted")
        if len({item.register for item in sources}) != len(sources):
            raise ProgramDataflowError("final register sources must be unique")
        object.__setattr__(self, "final_register_sources", sources)
        layers = tuple(tuple(layer) for layer in self.frontiers)
        if not layers or any(not layer for layer in layers):
            raise ProgramDataflowError("dataflow frontiers must be non-empty")
        if any(layer != tuple(sorted(layer)) for layer in layers):
            raise ProgramDataflowError("frontier node IDs must be deterministically sorted")
        object.__setattr__(self, "frontiers", layers)
        if not isinstance(self.metrics, ProgramDataflowMetrics):
            raise ProgramDataflowError("metrics must be ProgramDataflowMetrics")
        graph = self.graph()
        target_payload = {
            "schema": "mailcpu.program-dataflow-graph.v3",
            "program": self.program_ref.to_dict(),
            "initial_state": self.initial_state_ref.to_dict(),
            "computational_ground": self.computational_ground.to_dict(),
            "context_digest": self.context_digest,
            "structural_memory_refs": [[name, reference.to_dict()] for name, reference in self.structural_memory_refs],
            "contextual_orbit_inputs": [[name, predecessor.to_dict()] for name, predecessor in self.contextual_orbit_inputs],
            "nodes": [node.to_dict() for node in self.nodes],
            "final_register_sources": [item.to_dict() for item in self.final_register_sources],
            "frontiers": [list(item) for item in self.frontiers],
        }
        if canonical_value_digest(target_payload) != self.dataflow_representation.content_digest:
            raise ProgramDataflowError("dataflow representation does not identify the compiled atlas")
        if self.translation.source != self.program_ref or self.translation.target != self.dataflow_representation:
            raise ProgramDataflowError("translation contract does not bind the exact program and dataflow representations")
        if self.translation.context_digest != self.context_digest or self.translation.observation != self.observation:
            raise ProgramDataflowError("translation contract context or observation differs from the compiled plan")
        if _derive_frontiers(self.nodes) != self.frontiers:
            raise ProgramDataflowError("declared ready frontiers do not match the dependency graph")

    @property
    def initial_values(self) -> dict[str, int]:
        """Mathematics: return materialized initial values; symbolic references require receiver-side resolution."""
        if self.structural_memory_refs:
            names = ", ".join(name for name, _ in self.structural_memory_refs)
            raise ProgramDataflowError(
                "symbolic Structural Memory inputs are not materialized; receiver resolution is required for: " + names
            )
        if self.contextual_orbit_inputs:
            names = ", ".join(name for name, _ in self.contextual_orbit_inputs)
            raise ProgramDataflowError(
                "contextual-orbit inputs must remain typed predecessor nodes; use dataflow evaluation to consume: " + names
            )
        values = dict(self.initial_registers)
        for register, receipt in self.structural_memory_reads:
            if register in values:
                raise ProgramDataflowError(
                    f"register {register!r} is supplied by both inline state and Structural Memory"
                )
            values[register] = receipt.value
        return values

    def resolved_initial_values(self, resolved: Mapping[str, int]) -> dict[str, int]:
        """Mathematics: join exact receiver-resolved symbolic inputs with inline and receipt-backed initial state."""
        values = dict(self.initial_registers)
        values.update({name: receipt.value for name, receipt in self.structural_memory_reads})
        if not isinstance(resolved, Mapping):
            raise ProgramDataflowError("resolved symbolic initial values must be a mapping")
        memory_names = {name for name, _ in self.structural_memory_refs}
        orbit_inputs = dict(self.contextual_orbit_inputs)
        supplied = memory_names | set(orbit_inputs)
        if set(resolved) != supplied:
            raise ProgramDataflowError("resolved predecessor register set differs from the compiled Structural Memory and contextual-orbit inputs")
        for name, value in resolved.items():
            _register(name, "resolved predecessor register")
            resolved_value = _strict_int(value, f"resolved predecessor value for {name}")
            predecessor = orbit_inputs.get(name)
            if predecessor is not None and resolved_value != predecessor.value:
                raise ProgramDataflowError("resolved contextual-orbit register differs from its typed predecessor projection")
            values[name] = resolved_value
        return values

    @property
    def digest(self) -> str:
        """Mathematics: identify the complete compilation atlas and declared translation."""
        return canonical_value_digest(self.to_dict())

    def graph(self) -> NavigableComputationDAG:
        """Mathematics: rebuild a fresh mutable DAG from the immutable compiled node set."""
        try:
            return NavigableComputationDAG(
                self.nodes,
                max_nodes=max(1, len(self.nodes)),
            )
        except ComputationDAGError as exc:
            raise ProgramDataflowError(f"compiled dependency graph is invalid: {exc}") from exc

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize every representation, receipt, node, invariant-bearing edge, and frontier."""
        return {
            "schema": _SCHEMA,
            "source_bytes": None if self.source_bytes_ref is None else {
                "representation": self.source_bytes_ref.to_dict(),
                "size_bytes": self.source_size_bytes,
            },
            "program": self.program_ref.to_dict(),
            "initial_state": self.initial_state_ref.to_dict(),
            "computational_ground": self.computational_ground.to_dict(),
            "dataflow_representation": self.dataflow_representation.to_dict(),
            "observation": self.observation.to_dict(),
            "translation": self.translation.to_dict(),
            "context_digest": self.context_digest,
            "initial_registers": [[name, value] for name, value in self.initial_registers],
            "structural_memory_reads": [
                [name, receipt.to_dict()]
                for name, receipt in self.structural_memory_reads
            ],
            "structural_memory_refs": [
                [name, reference.to_dict()]
                for name, reference in self.structural_memory_refs
            ],
            "contextual_orbit_inputs": [
                [name, predecessor.to_dict()]
                for name, predecessor in self.contextual_orbit_inputs
            ],
            "nodes": [node.to_dict() for node in self.nodes],
            "final_register_sources": [item.to_dict() for item in self.final_register_sources],
            "frontiers": [list(layer) for layer in self.frontiers],
            "metrics": self.metrics.to_dict(),
        }


@dataclass(frozen=True)
class DataflowExecutionReport:
    """Result of bounded local evaluation of a compiled DAG, with a restorable DAG snapshot."""

    plan_digest: str
    status: str
    pc: int
    steps: int
    halted: bool
    blocked: bool
    registers: tuple[tuple[str, int], ...]
    committed_node_ids: tuple[str, ...]
    executed_frontiers: tuple[tuple[str, ...], ...]
    _dag_snapshot_json: str
    resolved_initial_registers: tuple[tuple[str, int], ...] = ()

    def __post_init__(self) -> None:
        """Mathematics: validate terminal execution status, register values, and the retained DAG snapshot."""
        if not re.fullmatch(r"[0-9a-f]{64}", self.plan_digest):
            raise ProgramDataflowError("report plan_digest must be lowercase SHA-256")
        if self.status != RunStatus.HALTED.value or self.halted is not True or self.blocked is not False:
            raise ProgramDataflowError("dataflow report must describe a terminal HALT")
        _strict_int(self.pc, "program counter", minimum=0)
        _strict_int(self.steps, "step count", minimum=1)
        registers = tuple(self.registers)
        if registers != tuple(sorted(registers)) or len({name for name, _ in registers}) != len(registers):
            raise ProgramDataflowError("reported registers must be uniquely sorted")
        for name, value in registers:
            _register(name, "reported register")
            _strict_int(value, f"reported register {name}")
        if json.loads(self._dag_snapshot_json).get("format") != NavigableComputationDAG.FORMAT:
            raise ProgramDataflowError("report DAG snapshot has an unsupported format")
        resolved = tuple(self.resolved_initial_registers)
        if resolved != tuple(sorted(resolved)) or len({name for name, _ in resolved}) != len(resolved):
            raise ProgramDataflowError("resolved initial registers must be uniquely sorted")
        for name, value in resolved:
            _register(name, "resolved initial register")
            _strict_int(value, f"resolved initial register {name}")
        object.__setattr__(self, "resolved_initial_registers", resolved)

    @property
    def observation(self) -> dict[str, Any]:
        """Mathematics: project the exact terminal observation into a detached mapping."""
        return {
            "status": self.status,
            "pc": self.pc,
            "steps": self.steps,
            "halted": self.halted,
            "blocked": self.blocked,
            "registers": {name: value for name, value in self.registers},
        }

    @property
    def dag_snapshot(self) -> dict[str, Any]:
        """Mathematics: restore a detached checkpoint projection of the committed computation frontier."""
        return json.loads(self._dag_snapshot_json)

    @property
    def dag_snapshot_digest(self) -> str:
        """Mathematics: identify the complete content-addressed DAG snapshot."""
        return canonical_value_digest(self.dag_snapshot)

    @property
    def digest(self) -> str:
        """Mathematics: bind the plan, terminal observation, commits, frontiers, and DAG snapshot digest."""
        return canonical_value_digest({
            "plan_digest": self.plan_digest,
            "observation": self.observation,
            "committed_node_ids": list(self.committed_node_ids),
            "executed_frontiers": [list(item) for item in self.executed_frontiers],
            "resolved_initial_registers": [[name, value] for name, value in self.resolved_initial_registers],
            "dag_snapshot_digest": self.dag_snapshot_digest,
        })

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize the execution report and snapshot identity without embedding mutable state."""
        return {
            "schema": "mailcpu.program-dataflow-execution.v2",
            "plan_digest": self.plan_digest,
            "status": self.status,
            "pc": self.pc,
            "steps": self.steps,
            "halted": self.halted,
            "blocked": self.blocked,
            "registers": {name: value for name, value in self.registers},
            "committed_node_ids": list(self.committed_node_ids),
            "executed_frontiers": [list(item) for item in self.executed_frontiers],
            "resolved_initial_registers": [[name, value] for name, value in self.resolved_initial_registers],
            "dag_snapshot_digest": self.dag_snapshot_digest,
            "digest": self.digest,
        }


def _instruction_registers(instruction: Any) -> tuple[str, ...]:
    """Mathematics: project one supported instruction to its ordered register operands."""
    op, args = instruction.op, instruction.args
    if op is Op.SET:
        return (args[0],)
    if op is Op.COPY:
        return (args[0], args[1])
    if op in {Op.ADD, Op.MUL, Op.COMPARE}:
        return (args[0], args[1], args[2])
    if op is Op.HALT:
        return ()
    raise ProgramDataflowError(f"opcode {op.value} is outside the pure dataflow compiler subset")


def _derive_frontiers(nodes: Sequence[ComputationNode]) -> tuple[tuple[str, ...], ...]:
    """Mathematics: compute deterministic longest-dependency layers for an acyclic instruction graph."""
    depths: dict[str, int] = {}
    for node in nodes:
        missing = set(node.dependencies) - set(depths)
        if missing:
            raise ProgramDataflowError(
                f"node {node.node_id!r} has dependencies outside the earlier instruction prefix"
            )
        depths[node.node_id] = 0 if not node.dependencies else 1 + max(
            depths[item] for item in node.dependencies
        )
    layers: dict[int, list[str]] = {}
    for node_id, depth in depths.items():
        layers.setdefault(depth, []).append(node_id)
    return tuple(tuple(sorted(layers[index])) for index in sorted(layers))


class MailCPUDataflowCompiler:
    """Compile the pure straight-line MailCPU subset into an identity-bound DAG."""

    def __init__(
        self,
        *,
        max_source_bytes: int = _MAX_SOURCE_BYTES,
        max_instructions: int = _MAX_INSTRUCTIONS,
    ) -> None:
        """Mathematics: establish finite source-byte and instruction-node admission bounds."""
        _strict_int(max_source_bytes, "max_source_bytes", minimum=1)
        _strict_int(max_instructions, "max_instructions", minimum=1)
        if max_source_bytes > _MAX_SOURCE_BYTES:
            raise ProgramDataflowError(f"max_source_bytes exceeds {_MAX_SOURCE_BYTES}")
        if max_instructions > _MAX_INSTRUCTIONS:
            raise ProgramDataflowError(f"max_instructions exceeds {_MAX_INSTRUCTIONS}")
        self.max_source_bytes = max_source_bytes
        self.max_instructions = max_instructions

    def compile_bytes(
        self,
        source: bytes,
        *,
        initial_registers: Mapping[str, int] | None = None,
        structural_memory_reads: Mapping[str, StructuralMemoryReadReceipt] | None = None,
        structural_memory_refs: Mapping[str, VirtualStructuralMemoryRef] | None = None,
        contextual_orbit_inputs: Mapping[str, ContextualOrbitDataflowInput] | None = None,
    ) -> CompiledMailCPUDataflow:
        """Mathematics: compile exact UTF-8 bytes with materialized receipts or symbolic receiver-resolved memory inputs."""
        if not isinstance(source, bytes):
            raise ProgramDataflowError("source must be bytes")
        if len(source) > self.max_source_bytes:
            raise ProgramDataflowError("assembly source exceeds max_source_bytes")
        try:
            text = source.decode("utf-8", errors="strict")
            program = assemble(text)
        except (UnicodeDecodeError, AssemblyError, TypeError, ValueError) as exc:
            raise ProgramDataflowError(f"assembly bytes could not be compiled: {exc}") from exc
        source_ref = RepresentationRef(
            "mailcpu.assembly.utf8",
            1,
            hashlib.sha256(source).hexdigest(),
        )
        return self._compile(
            program,
            initial_registers=initial_registers,
            structural_memory_reads=structural_memory_reads,
            structural_memory_refs=structural_memory_refs,
            contextual_orbit_inputs=contextual_orbit_inputs,
            source_bytes_ref=source_ref,
            source_size_bytes=len(source),
        )

    def compile_program(
        self,
        program: Program,
        *,
        initial_registers: Mapping[str, int] | None = None,
        structural_memory_reads: Mapping[str, StructuralMemoryReadReceipt] | None = None,
        structural_memory_refs: Mapping[str, VirtualStructuralMemoryRef] | None = None,
        contextual_orbit_inputs: Mapping[str, ContextualOrbitDataflowInput] | None = None,
    ) -> CompiledMailCPUDataflow:
        """Mathematics: compile a validated Program with inline, receipt-backed, or symbolic initial register state."""
        if not isinstance(program, Program):
            raise ProgramDataflowError("compile_program requires a validated Program")
        return self._compile(
            program,
            initial_registers=initial_registers,
            structural_memory_reads=structural_memory_reads,
            structural_memory_refs=structural_memory_refs,
            contextual_orbit_inputs=contextual_orbit_inputs,
            source_bytes_ref=None,
            source_size_bytes=None,
        )

    def _compile(
        self,
        program: Program,
        *,
        initial_registers: Mapping[str, int] | None,
        structural_memory_reads: Mapping[str, StructuralMemoryReadReceipt] | None,
        structural_memory_refs: Mapping[str, VirtualStructuralMemoryRef] | None,
        contextual_orbit_inputs: Mapping[str, ContextualOrbitDataflowInput] | None,
        source_bytes_ref: RepresentationRef | None,
        source_size_bytes: int | None,
    ) -> CompiledMailCPUDataflow:
        """Mathematics: construct the exact SSA-like register-definition graph for the admitted program."""
        if not isinstance(program, Program):
            raise ProgramDataflowError("compiler requires a validated Program")
        instructions = tuple(program.instructions)
        if not instructions or len(instructions) > self.max_instructions:
            raise ProgramDataflowError("program is empty or exceeds max_instructions")
        if instructions[-1].op is not Op.HALT:
            raise ProgramDataflowError("the final instruction must be HALT")
        if sum(item.op is Op.HALT for item in instructions) != 1:
            raise ProgramDataflowError("program must contain exactly one terminal HALT")
        for instruction in instructions[:-1]:
            if instruction.op not in _SUPPORTED:
                raise ProgramDataflowError(
                    f"opcode {instruction.op.value} is outside the pure straight-line subset"
                )
        if any(item.op is not Op.HALT for item in instructions[-1:]):
            raise ProgramDataflowError("HALT must be the final instruction")

        supplied: dict[str, int] = {}
        if initial_registers is not None:
            if not isinstance(initial_registers, Mapping):
                raise ProgramDataflowError("initial_registers must be a mapping")
            for name, value in initial_registers.items():
                register = _register(name, "initial register")
                supplied[register] = _strict_int(value, f"initial register {register}")
        receipts: dict[str, StructuralMemoryReadReceipt] = {}
        if structural_memory_reads is not None:
            if not isinstance(structural_memory_reads, Mapping):
                raise ProgramDataflowError("structural_memory_reads must be a mapping")
            for name, receipt in structural_memory_reads.items():
                register = _register(name, "Structural Memory register")
                if not isinstance(receipt, StructuralMemoryReadReceipt):
                    raise ProgramDataflowError(
                        f"Structural Memory input {register!r} must be a typed read receipt"
                    )
                expected_value_digest = canonical_value_digest({
                    "type": "integer",
                    "value": receipt.value,
                })
                if receipt.value_digest != expected_value_digest:
                    raise ProgramDataflowError(
                        f"Structural Memory receipt for {register!r} has an inconsistent value digest"
                    )
                receipts[register] = receipt
        references: dict[str, VirtualStructuralMemoryRef] = {}
        if structural_memory_refs is not None:
            if not isinstance(structural_memory_refs, Mapping):
                raise ProgramDataflowError("structural_memory_refs must be a mapping")
            for name, reference in structural_memory_refs.items():
                register = _register(name, "symbolic Structural Memory register")
                if not isinstance(reference, VirtualStructuralMemoryRef):
                    raise ProgramDataflowError(f"symbolic Structural Memory input {register!r} must be a VirtualStructuralMemoryRef")
                # The program register is the canonical binding at compile time.
                references[register] = VirtualStructuralMemoryRef(
                    binding=register,
                    memory_id=reference.memory_id,
                    revision=reference.revision,
                    context=reference.context,
                    coordinate=reference.coordinate,
                    spec_digest=reference.spec_digest,
                    certificate_digest=reference.certificate_digest,
                )
        orbit_inputs: dict[str, ContextualOrbitDataflowInput] = {}
        if contextual_orbit_inputs is not None:
            if not isinstance(contextual_orbit_inputs, Mapping):
                raise ProgramDataflowError("contextual_orbit_inputs must be a mapping")
            if len(contextual_orbit_inputs) > _MAX_CONTEXTUAL_ORBIT_INPUTS:
                raise ProgramDataflowError("contextual-orbit inputs exceed the compiler bound")
            for name, predecessor in contextual_orbit_inputs.items():
                register = _register(name, "contextual-orbit register")
                if not isinstance(predecessor, ContextualOrbitDataflowInput):
                    raise ProgramDataflowError(f"contextual-orbit input {register!r} must be a typed verified predecessor")
                orbit_inputs[register] = predecessor
        supplied_sets = [set(supplied), set(receipts), set(references), set(orbit_inputs)]
        overlap = set().union(*(left & right for index, left in enumerate(supplied_sets) for right in supplied_sets[index + 1:]))
        if overlap:
            raise ProgramDataflowError(
                "registers cannot be supplied by more than one inline, Structural Memory receipt/reference, or contextual-orbit source: "
                + ", ".join(sorted(overlap))
            )

        initial_values = dict(supplied)
        initial_values.update({name: receipt.value for name, receipt in receipts.items()})
        initial_receipt_dicts = {
            name: receipt.to_dict()
            for name, receipt in sorted(receipts.items())
        }
        initial_reference_dicts = {
            name: reference.to_dict()
            for name, reference in sorted(references.items())
        }
        initial_orbit_input_dicts = {
            name: predecessor.to_dict()
            for name, predecessor in sorted(orbit_inputs.items())
        }
        initial_state_payload = {
            "registers": dict(sorted(initial_values.items())),
            "structural_memory_receipts": initial_receipt_dicts,
            "structural_memory_refs": initial_reference_dicts,
            "contextual_orbit_inputs": initial_orbit_input_dicts,
        }
        program_ref = program_representation_ref(program)
        initial_state_ref = RepresentationRef.from_payload(
            "mailcpu.initial-register-state",
            3,
            initial_state_payload,
        )
        ground_ref = RepresentationRef.from_payload(
            "mailcpu.computational-ground.register-dataflow",
            2,
            _GROUND_DEFINITION,
        )
        observation = ObservationContract.from_definition(
            "mailcpu.terminal-register-state",
            1,
            _OBSERVATION_DEFINITION,
        )
        compiler_ref = RepresentationRef.from_payload(
            "mailcpu.compiler.program-dataflow",
            _COMPILER_VERSION,
            _COMPILER_DEFINITION,
        )
        context_digest = canonical_value_digest({
            "compiler": compiler_ref.to_dict(),
            "program": program_ref.to_dict(),
            "initial_state": initial_state_ref.to_dict(),
            "computational_ground": ground_ref.to_dict(),
            "observation": observation.to_dict(),
            "source_bytes": None if source_bytes_ref is None else {
                "representation": source_bytes_ref.to_dict(),
                "size_bytes": source_size_bytes,
            },
        })

        receipt_digests = {
            name: receipt.value_digest
            for name, receipt in receipts.items()
        }
        reference_digests = {
            name: canonical_value_digest(reference.to_dict())
            for name, reference in references.items()
        }
        definitions: dict[str, str] = {}
        contextual_orbit_source_ids = {
            register: f"orbit-input-{register}" for register in orbit_inputs
        }
        touched: set[str] = set(initial_values) | set(references) | set(orbit_inputs)
        consumed_references: set[str] = set()
        consumed_contextual_orbit_inputs: set[str] = set()
        nodes: list[ComputationNode] = []
        instruction_nodes: list[str] = []
        for register, predecessor in sorted(orbit_inputs.items()):
            source_node_id = contextual_orbit_source_ids[register]
            source_node = ComputationNode(
                node_id=source_node_id,
                revision=1,
                operation="mailcpu.dataflow.contextual_orbit_input",
                resource="/mailcpu/program/dataflow",
                context_digest=context_digest,
                dependencies=(),
                payload={
                    "kind": "mailcpu.register-dataflow.contextual-orbit-input",
                    "register": register,
                    "field": predecessor.field,
                    "source_digest": predecessor.digest,
                    "request_digest": predecessor.request.digest,
                    "receipt_digest": predecessor.receipt.digest,
                },
            )
            nodes.append(source_node)
            definitions[register] = source_node_id

        def initial_operand(register: str) -> dict[str, Any]:
            """Mathematics: bind one read to an exact inline value, materialized receipt, or symbolic receiver-local memory address."""
            reference = references.get(register)
            if reference is not None:
                consumed_references.add(register)
                return {
                    "kind": "structural_memory",
                    "register": register,
                    "reference": reference.to_dict(),
                    "source_digest": reference_digests[register],
                }
            value = initial_values.get(register, 0)
            source_digest = receipt_digests.get(
                register,
                _initial_value_digest(register, value),
            )
            return {
                "kind": "initial",
                "register": register,
                "value": value,
                "source_digest": source_digest,
            }

        def register_operand(register: str, pc: int) -> tuple[dict[str, Any], str | None]:
            """Mathematics: resolve a register read to its latest prior definition or initial source."""
            touched.add(register)
            producer = definitions.get(register)
            if producer is None:
                return initial_operand(register), None
            if contextual_orbit_source_ids.get(register) == producer:
                consumed_contextual_orbit_inputs.add(register)
            return {
                "kind": "dependency",
                "register": register,
                "node_id": producer,
            }, producer

        for pc, instruction in enumerate(instructions[:-1]):
            op, args = instruction.op, instruction.args
            destination = _register(args[0], f"destination at pc {pc}")
            touched.add(destination)
            if op is Op.SET:
                operands = [{"kind": "literal", "value": _strict_int(args[1], f"SET at pc {pc}")}]
            elif op is Op.COPY:
                source_register = _register(args[1], f"COPY source at pc {pc}")
                operand, _ = register_operand(source_register, pc)
                operands = [operand]
            elif op in {Op.ADD, Op.MUL, Op.COMPARE}:
                left, left_dependency = register_operand(_register(args[1], f"left operand at pc {pc}"), pc)
                right, right_dependency = register_operand(_register(args[2], f"right operand at pc {pc}"), pc)
                operands = [left, right]
            else:
                raise ProgramDataflowError(f"opcode {op.value} is not admitted")

            dependencies = tuple(dict.fromkeys(
                item["node_id"]
                for item in operands
                if item["kind"] == "dependency"
            ))
            node_id = f"pc-{pc:06d}"
            payload = {
                "kind": "mailcpu.register-dataflow.instruction",
                "pc": pc,
                "opcode": op.value,
                "destination": destination,
                "operands": operands,
            }
            node = ComputationNode(
                node_id=node_id,
                revision=1,
                operation=f"mailcpu.dataflow.{op.value.lower()}",
                resource="/mailcpu/program/dataflow",
                context_digest=context_digest,
                dependencies=dependencies,
                payload=payload,
            )
            nodes.append(node)
            instruction_nodes.append(node_id)
            definitions[destination] = node_id

        unused_references = set(references) - consumed_references
        if unused_references:
            raise ProgramDataflowError(
                "symbolic Structural Memory references must be consumed by an admitted instruction: "
                + ", ".join(sorted(unused_references))
            )
        unused_orbit_inputs = set(orbit_inputs) - consumed_contextual_orbit_inputs
        if unused_orbit_inputs:
            raise ProgramDataflowError(
                "contextual-orbit predecessor inputs must be consumed by an admitted instruction: "
                + ", ".join(sorted(unused_orbit_inputs))
            )

        halt_pc = len(instructions) - 1
        halt_id = f"pc-{halt_pc:06d}"
        halt_node = ComputationNode(
            node_id=halt_id,
            revision=1,
            operation="mailcpu.dataflow.halt",
            resource="/mailcpu/program/dataflow",
            context_digest=context_digest,
            dependencies=tuple(instruction_nodes),
            payload={
                "kind": "mailcpu.register-dataflow.terminal",
                "pc": halt_pc,
                "opcode": Op.HALT.value,
                "instruction_count": len(instructions),
            },
        )
        nodes.append(halt_node)

        final_sources: list[RegisterSource] = []
        for register in sorted(touched):
            producer = definitions.get(register)
            if producer is not None:
                producer_node = next(item for item in nodes if item.node_id == producer)
                final_sources.append(RegisterSource(
                    register,
                    "node",
                    producer_node.digest,
                    node_id=producer,
                ))
            elif register in references:
                final_sources.append(RegisterSource(
                    register,
                    "structural_memory",
                    reference_digests[register],
                    memory_reference=references[register],
                ))
            else:
                value = initial_values.get(register, 0)
                final_sources.append(RegisterSource(
                    register,
                    "initial",
                    receipt_digests.get(register, _initial_value_digest(register, value)),
                    value=value,
                ))

        try:
            graph = NavigableComputationDAG(
                tuple(nodes),
                max_nodes=max(1, len(nodes)),
            )
        except ComputationDAGError as exc:
            raise ProgramDataflowError(f"compiled graph exceeds DAG constraints: {exc}") from exc
        frontiers = _derive_frontiers(tuple(nodes))
        if tuple(node.node_id for node in graph.nodes) != tuple(sorted(node.node_id for node in nodes)):
            raise ProgramDataflowError("compiled graph identity ordering is inconsistent")

        target_payload = {
            "schema": "mailcpu.program-dataflow-graph.v3",
            "program": program_ref.to_dict(),
            "initial_state": initial_state_ref.to_dict(),
            "computational_ground": ground_ref.to_dict(),
            "context_digest": context_digest,
            "structural_memory_refs": [[name, reference.to_dict()] for name, reference in sorted(references.items())],
            "contextual_orbit_inputs": [[name, predecessor.to_dict()] for name, predecessor in sorted(orbit_inputs.items())],
            "nodes": [node.to_dict() for node in nodes],
            "final_register_sources": [item.to_dict() for item in final_sources],
            "frontiers": [list(item) for item in frontiers],
        }
        dataflow_ref = RepresentationRef.from_payload(
            "mailcpu.program.dataflow-graph",
            3,
            target_payload,
        )
        invariant_refs = tuple(
            RepresentationRef.from_payload(
                "mailcpu.compiler.invariant",
                1,
                definition,
            )
            for definition in _INVARIANT_DEFINITIONS
        )
        translation = TranslationContract(
            contract_id="mailcpu-program-to-register-dataflow",
            revision=1,
            source=program_ref,
            target=dataflow_ref,
            mapping=compiler_ref,
            observation=observation,
            context_digest=context_digest,
            precondition_digests=(
                initial_state_ref.content_digest,
                ground_ref.content_digest,
            ),
            invariant_digests=tuple(item.content_digest for item in invariant_refs),
            resource_bounds=(
                ResourceBound("instructions", len(instructions), "nodes"),
                ResourceBound("dependency_edges", sum(len(item.dependencies) for item in nodes), "edges"),
                ResourceBound("source_bytes", source_size_bytes or 0, "bytes"),
            ),
            effect_class=EffectClass.PURE,
            replay_class=ReplayClass.DETERMINISTIC,
        )
        edge_count = sum(len(item.dependencies) for item in nodes)
        work_units = len(nodes)
        critical_path = len(frontiers)
        max_width = max(len(item) for item in frontiers)
        parallelism = work_units / critical_path if critical_path else 0.0
        metrics = ProgramDataflowMetrics(
            work_units=work_units,
            dependency_edges=edge_count,
            critical_path_nodes=critical_path,
            max_frontier_width=max_width,
            theoretical_parallelism=parallelism,
            graph_description_bytes=len(_canonical(target_payload)),
            topology_candidate="dataflow" if max_width > 1 else "sequential",
        )
        return CompiledMailCPUDataflow(
            source_bytes_ref=source_bytes_ref,
            source_size_bytes=source_size_bytes,
            program_ref=program_ref,
            initial_state_ref=initial_state_ref,
            computational_ground=ground_ref,
            dataflow_representation=dataflow_ref,
            observation=observation,
            translation=translation,
            context_digest=context_digest,
            initial_registers=tuple(sorted(supplied.items())),
            structural_memory_reads=tuple(sorted(receipts.items())),
            structural_memory_refs=tuple(sorted(references.items())),
            nodes=tuple(nodes),
            final_register_sources=tuple(final_sources),
            frontiers=frontiers,
            metrics=metrics,
            contextual_orbit_inputs=tuple(sorted(orbit_inputs.items())),
        )


def evaluate_dataflow(
    plan: CompiledMailCPUDataflow,
    *,
    max_work_units: int | None = None,
    timing_probe: Any | None = None,
) -> DataflowExecutionReport:
    """Mathematics: evaluate independent ready-frontier nodes and commit exact results to the DAG."""
    if not isinstance(plan, CompiledMailCPUDataflow):
        raise ProgramDataflowError("evaluate_dataflow requires a CompiledMailCPUDataflow")
    if timing_probe is not None and not callable(getattr(timing_probe, "measure", None)):
        raise ProgramDataflowError("timing_probe must expose a callable measure context manager")
    if plan.structural_memory_refs:
        raise ProgramDataflowError("local dataflow evaluation cannot resolve symbolic Structural Memory; use receiver-authorized operation-native execution")
    limit = len(plan.nodes) if max_work_units is None else _strict_int(
        max_work_units, "max_work_units", minimum=1
    )
    if len(plan.nodes) > limit:
        raise ProgramDataflowError("compiled graph exceeds max_work_units")
    graph = plan.graph()
    node_by_id = {node.node_id: node for node in plan.nodes}
    executed_frontiers: list[tuple[str, ...]] = []
    committed: list[str] = []
    orbit_inputs = dict(plan.contextual_orbit_inputs)
    resolved_initial_registers = {name: predecessor.value for name, predecessor in orbit_inputs.items()}

    for expected_frontier in plan.frontiers:
        ready = tuple(node.node_id for node in graph.ready_nodes())
        if ready != expected_frontier:
            raise ProgramDataflowError(
                "live DAG readiness differs from the compiler-derived frontier"
            )
        pending_results: list[tuple[str, dict[str, Any]]] = []
        for node_id in expected_frontier:
            node = node_by_id[node_id]
            payload = node.payload
            if payload.get("kind") == "mailcpu.register-dataflow.contextual-orbit-input":
                register = payload.get("register")
                predecessor = orbit_inputs.get(register)
                if (
                    not isinstance(register, str)
                    or predecessor is None
                    or payload.get("source_digest") != predecessor.digest
                    or payload.get("field") != predecessor.field
                ):
                    raise ProgramDataflowError("contextual-orbit predecessor node differs from the compiled typed input")
                result = {
                    "register": register,
                    "value": predecessor.value,
                    "contextual_orbit_input": predecessor.to_dict(),
                    "predecessor_digest": predecessor.digest,
                    "selected_coordinate": predecessor.selected_coordinate,
                    "selected_value": predecessor.selected_value,
                    "receipt_digest": predecessor.receipt.digest,
                }
            elif payload.get("opcode") == Op.HALT.value:
                result = {
                    "status": RunStatus.HALTED.value,
                    "pc": payload["pc"],
                    "steps": payload["instruction_count"],
                    "halted": True,
                    "blocked": False,
                }
            else:
                operands: list[int] = []
                for operand in payload["operands"]:
                    kind = operand["kind"]
                    if kind in {"literal", "initial"}:
                        value = operand["value"]
                    elif kind == "dependency":
                        dependency_result = graph.result(operand["node_id"])
                        value = dependency_result.get("value")
                    else:
                        raise ProgramDataflowError(f"unknown operand source kind {kind!r}")
                    operands.append(_strict_int(value, f"operand for node {node_id}"))
                opcode = payload["opcode"]
                if opcode in {Op.SET.value, Op.COPY.value}:
                    value = operands[0]
                elif opcode == Op.ADD.value:
                    value = operands[0] + operands[1]
                elif opcode == Op.MUL.value:
                    if timing_probe is None:
                        value = operands[0] * operands[1]
                    else:
                        with timing_probe.measure("local_compute", correlation_id=plan.digest):
                            value = operands[0] * operands[1]
                elif opcode == Op.COMPARE.value:
                    value = compare_values(operands[0], operands[1])
                else:
                    raise ProgramDataflowError(f"unsupported compiled opcode {opcode!r}")
                result = {
                    "register": payload["destination"],
                    "value": _strict_int(value, f"result for node {node_id}"),
                }
            pending_results.append((node_id, result))

        for node_id, result in pending_results:
            graph.commit(node_id, result)
            committed.append(node_id)
        executed_frontiers.append(expected_frontier)

    halt = graph.result(plan.nodes[-1].node_id)
    if halt.get("status") != RunStatus.HALTED.value:
        raise ProgramDataflowError("terminal node did not commit a HALTED result")
    result_registers: dict[str, int] = {}
    for source in plan.final_register_sources:
        if source.kind == "initial":
            value = source.value
        elif source.kind == "structural_memory":
            raise ProgramDataflowError("local dataflow evaluation cannot materialize a symbolic Structural Memory final register")
        else:
            value = graph.result(source.node_id or "").get("value")
        result_registers[source.register] = _strict_int(
            value,
            f"final register {source.register}",
        )
    snapshot = graph.snapshot()
    snapshot_json = _canonical(snapshot).decode("utf-8")
    return DataflowExecutionReport(
        plan_digest=plan.digest,
        status=RunStatus.HALTED.value,
        pc=halt["pc"],
        steps=halt["steps"],
        halted=True,
        blocked=False,
        registers=tuple(sorted(result_registers.items())),
        committed_node_ids=tuple(committed),
        executed_frontiers=tuple(executed_frontiers),
        _dag_snapshot_json=snapshot_json,
        resolved_initial_registers=tuple(sorted(resolved_initial_registers.items())),
    )


def compare_dataflow_with_reference(
    plan: CompiledMailCPUDataflow,
    report: DataflowExecutionReport,
    program: Program,
) -> ObservationComparison:
    """Mathematics: compare the compiled terminal result with the reference interpreter under one contract."""
    if not isinstance(plan, CompiledMailCPUDataflow):
        raise ProgramDataflowError("comparison requires a compiled plan")
    if not isinstance(report, DataflowExecutionReport) or report.plan_digest != plan.digest:
        raise ProgramDataflowError("execution report does not belong to this compiled plan")
    if not isinstance(program, Program) or program_representation_ref(program) != plan.program_ref:
        raise ProgramDataflowError("reference Program identity differs from the compiled source")
    restored = NavigableComputationDAG.from_snapshot(report.dag_snapshot)
    expected_graph = plan.graph()
    if restored.digest != expected_graph.digest or not restored.is_complete:
        raise ProgramDataflowError("execution DAG snapshot is incomplete or belongs to another plan")

    if plan.structural_memory_refs or plan.contextual_orbit_inputs:
        resolved = dict(report.resolved_initial_registers)
        initial_values = plan.resolved_initial_values(resolved)
    else:
        if report.resolved_initial_registers:
            raise ProgramDataflowError("execution report contains unexpected receiver-resolved initial registers")
        initial_values = plan.initial_values
    reference = ReferenceInterpreter(program).run(
        initial_registers=initial_values,
        max_steps=len(plan.nodes),
    )
    if reference.status is not RunStatus.HALTED:
        raise ProgramDataflowError("reference interpreter did not reach the declared terminal HALT")
    expected_observation = {
        "status": reference.status.value,
        "pc": reference.state.pc,
        "steps": reference.state.steps,
        "halted": reference.state.halted,
        "blocked": reference.state.blocked,
        "registers": dict(sorted(reference.state.registers.items())),
    }
    return compare_projected_observations(
        plan.translation,
        case_payload={
            "plan_digest": plan.digest,
            "program": plan.program_ref.to_dict(),
            "initial_state": plan.initial_state_ref.to_dict(),
        },
        source_observation=expected_observation,
        target_observation=report.observation,
    )


def verify_dataflow_compilation(
    compiler: MailCPUDataflowCompiler,
    program: Program,
    plan: CompiledMailCPUDataflow,
    *,
    source_bytes: bytes | None = None,
) -> bool:
    """Mathematics: recompile and compare exact identities, requiring original bytes for byte-origin plans."""
    if not isinstance(compiler, MailCPUDataflowCompiler):
        raise ProgramDataflowError("verification requires a MailCPUDataflowCompiler")
    if not isinstance(plan, CompiledMailCPUDataflow):
        raise ProgramDataflowError("verification requires a CompiledMailCPUDataflow")
    if program_representation_ref(program) != plan.program_ref:
        return False
    if plan.source_bytes_ref is None:
        if source_bytes is not None:
            return False
        candidate = compiler.compile_program(
            program,
            initial_registers=dict(plan.initial_registers),
            structural_memory_reads=dict(plan.structural_memory_reads),
            structural_memory_refs=dict(plan.structural_memory_refs),
            contextual_orbit_inputs=dict(plan.contextual_orbit_inputs),
        )
    else:
        if not isinstance(source_bytes, bytes):
            return False
        candidate = compiler.compile_bytes(
            source_bytes,
            initial_registers=dict(plan.initial_registers),
            structural_memory_reads=dict(plan.structural_memory_reads),
            structural_memory_refs=dict(plan.structural_memory_refs),
            contextual_orbit_inputs=dict(plan.contextual_orbit_inputs),
        )
    return candidate.digest == plan.digest


__all__ = [
    "CompiledMailCPUDataflow",
    "DataflowExecutionReport",
    "MailCPUDataflowCompiler",
    "ProgramDataflowError",
    "ProgramDataflowMetrics",
    "RegisterSource",
    "compare_dataflow_with_reference",
    "evaluate_dataflow",
    "verify_dataflow_compilation",
]
