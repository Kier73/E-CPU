"""Execute source-structural intentions through the existing E-CPU Virtual Layer.

This supplies a receiver-owned pure operator handler. It binds the immutable
external *description*, never source weights, to the existing Hypervisor-
authorized VirtualLayerRuntime. A new host must independently reconstruct
the description and bind the same approved handler.
"""
from __future__ import annotations
from typing import Any, Mapping

from .external_virtual_structure import (
    SourceStructure, StructureRefused, compile_virtual_read,
)
from .virtual_layer import OperatorRegistry, OperatorSpec

OPERATOR_ID = "external.structure.interpret"
VERSION = 1


def register_virtual_structure(registry: OperatorRegistry,
                               source: SourceStructure) -> OperatorSpec:
    """Admit a pure source-relative VL operator without model payload I/O."""
    if not isinstance(registry, OperatorRegistry) or not isinstance(source, SourceStructure):
        raise StructureRefused("native E-CPU VL registration requires admitted source Ground")
    def interpret(value: Any, workload: Any) -> dict:
        """One receiver-owned semantic translation from source coordinates."""
        if (not isinstance(value, Mapping)
            or set(value) != {"source_head", "operation", "arguments"}
            or value["source_head"] != source.ground_digest
            or not isinstance(value["arguments"], Mapping)):
            raise StructureRefused("operator input differs from admitted external source")
        result = compile_virtual_read(source, value["operation"], value["arguments"])
        return result.to_dict()
    spec = OperatorSpec(
        operator_id=OPERATOR_ID, version=VERSION,
        description="Interpret an admitted externally hosted model source structure by virtual coordinate",
        input_kind="object", output_kind="object", substrates=("cpu",),
        required_rights=frozenset({"compute"}),
        base_energy=1, energy_per_byte=1,
        max_input_bytes=4096, max_output_bytes=262144,
        deterministic=True, effect_mode="pure",
    )
    registry.register(spec, interpret)
    return spec
