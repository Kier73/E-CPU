"""Bind persistent VGI session quanta to receiver-local fabric execution hosts.

The operator carries a bounded M7 transfer bundle in a normal semantic workload.
The receiver admits M1 pages, verifies the M3 checkpoint against its own
recovery-lineage view, then advances through the already-admitted M4 pure
transition backend. The Virtual Layer/Hypervisor supplies local host authority;
the VGI session supplies revision CAS and exact operation replay.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections.abc import Mapping
from typing import Any

from .computational_session import ComputationalSessionCheckpoint
from .vgi_session import VGISessionError, VGISessionTransferBundle, VGIPersistentSession
from .virtual_layer import OperatorRegistry, OperatorSpec, VirtualLayerWorkload


VGI_FABRIC_QUANTUM_OPERATOR = "vgi.signal8.session_quantum"
VGI_FABRIC_QUANTUM_VERSION = 1
VGI_FABRIC_INPUT_SCHEMA = "mailcpu.fabric.vgi-quantum-input.v1"
VGI_FABRIC_RESULT_SCHEMA = "mailcpu.fabric.vgi-quantum-result.v1"


class VGIFabricOperatorError(ValueError):
    """Mathematics: Reject a VGI fabric quantum whose portable context or session CAS base is invalid."""


def _canonical_bytes(value: Any) -> bytes:
    """Mathematics: Encode one finite transfer coordinate using canonical compact JSON."""
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise VGIFabricOperatorError("VGI fabric input is outside canonical JSON") from exc


def vgi_fabric_quantum_operator_spec(*, max_input_bytes: int = 4_194_304) -> OperatorSpec:
    """Mathematics: Declare one bounded pure result contract for M7 transfer admission and M4 session advancement."""
    return OperatorSpec(
        operator_id=VGI_FABRIC_QUANTUM_OPERATOR,
        version=VGI_FABRIC_QUANTUM_VERSION,
        description="Verify and continue one portable VGI Signal8 session quantum",
        input_kind="object",
        output_kind="object",
        substrates=("cpu",),
        required_rights=frozenset({"compute"}),
        base_energy=16,
        energy_per_byte=1,
        max_input_bytes=max_input_bytes,
        max_output_bytes=16_384,
        deterministic=True,
        effect_mode="pure",
    )


class VGIFabricSessionOperator:
    """Mathematics: Receiver-local adapter from a typed fabric workload into one persistent VGI session transition."""

    def __init__(
        self,
        session: VGIPersistentSession,
        *,
        max_input_bytes: int = 4_194_304,
    ) -> None:
        """Mathematics: Bind one admitted receiver-local VGI runtime and a finite transfer-input ceiling."""
        if not isinstance(session, VGIPersistentSession):
            raise TypeError("session must be a VGIPersistentSession")
        if type(max_input_bytes) is not int or max_input_bytes < 1024:
            raise VGIFabricOperatorError("max_input_bytes must be an integer of at least 1024")
        self.session = session
        self.spec = vgi_fabric_quantum_operator_spec(max_input_bytes=max_input_bytes)
        self.max_input_bytes = max_input_bytes
        self._lock = threading.RLock()
        self._last_measurement: dict[str, int | float | str] = {}

    def register(self, registry: OperatorRegistry) -> None:
        """Mathematics: Bind the declarative VGI quantum contract to this host's local session handler."""
        if not isinstance(registry, OperatorRegistry):
            raise TypeError("registry must be an OperatorRegistry")
        registry.register(self.spec, self.execute)

    @property
    def last_measurement(self) -> dict[str, int | float | str]:
        """Mathematics: Return a detached measurement record for the most recently admitted VGI quantum."""
        with self._lock:
            return dict(self._last_measurement)

    def execute(self, value: Any, workload: VirtualLayerWorkload) -> dict[str, object]:
        """Mathematics: Import a portable M7 session when absent and CAS-commit one bounded M4 quantum at this receiver."""
        started = time.perf_counter()
        if not isinstance(workload, VirtualLayerWorkload):
            raise VGIFabricOperatorError("VGI fabric execution requires a typed VirtualLayerWorkload")
        if not isinstance(value, Mapping) or set(value) != {"schema", "transfer", "quantum_steps"}:
            raise VGIFabricOperatorError("VGI fabric input fields are invalid")
        if value["schema"] != VGI_FABRIC_INPUT_SCHEMA:
            raise VGIFabricOperatorError("VGI fabric input schema is unsupported")
        quantum_steps = value["quantum_steps"]
        if type(quantum_steps) is not int or not 1 <= quantum_steps <= self.session.max_quantum_steps:
            raise VGIFabricOperatorError("quantum_steps exceeds the receiver's admitted VGI quantum bound")
        try:
            encoded_input_size = len(_canonical_bytes(dict(value)))
        except VGIFabricOperatorError:
            raise
        if encoded_input_size > self.max_input_bytes:
            raise VGIFabricOperatorError("VGI fabric transfer exceeds the operator input bound")
        decode_started = time.perf_counter()
        try:
            transfer = VGISessionTransferBundle.from_dict(
                value["transfer"],
                max_state_bytes=self.session.max_state_bytes,
            )
        except VGISessionError as exc:
            raise VGIFabricOperatorError(f"VGI transfer admission failed: {exc}") from exc
        bundle_decode_ms = (time.perf_counter() - decode_started) * 1000.0
        if _canonical_bytes(transfer.descriptor) != _canonical_bytes(self.session.descriptor.to_dict()):
            raise VGIFabricOperatorError("transferred VGI descriptor differs from the receiver's admitted interpretation")
        try:
            base = ComputationalSessionCheckpoint.from_dict(
                transfer.session_export["checkpoint"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise VGIFabricOperatorError("VGI transfer does not contain a valid M3 checkpoint base") from exc

        operation_payload = {
            "schema": VGI_FABRIC_INPUT_SCHEMA,
            "workload_id": workload.workload_id,
            "workload_digest": workload.digest,
            "session_id": base.session_id,
            "descriptor_digest": self.session.descriptor.descriptor_digest,
            "transfer_bundle_digest": transfer.bundle_digest,
            "base_revision": base.revision,
            "base_checkpoint_digest": base.checkpoint_digest,
            "quantum_steps": quantum_steps,
        }
        operation_id = "fabric-vgi:" + hashlib.sha256(_canonical_bytes(operation_payload)).hexdigest()

        import_started = time.perf_counter()
        with self._lock:
            imported = False
            try:
                current = self.session.load()
            except VGISessionError:
                try:
                    current = self.session.restore_transfer(transfer)
                    imported = True
                except VGISessionError as exc:
                    raise VGIFabricOperatorError(f"receiver could not import M1 pages and verify M3 lineage: {exc}") from exc

            if current.session.checkpoint.session_id != base.session_id:
                raise VGIFabricOperatorError("receiver session identity differs from the transferred M3 session")
            if current.descriptor_digest != self.session.descriptor.descriptor_digest:
                raise VGIFabricOperatorError("receiver session interpretation differs from the transfer descriptor")
            if current.revision == base.revision:
                if current.checkpoint_digest != base.checkpoint_digest:
                    raise VGIFabricOperatorError("receiver M3 session is not at the transfer's exact CAS base")
            elif not (
                current.revision == base.revision + 1
                and current.session.checkpoint.operation_id == operation_id
                and current.session.checkpoint.predecessor_checkpoint_digest == base.checkpoint_digest
            ):
                raise VGIFabricOperatorError("receiver session has advanced beyond or diverged from this semantic quantum")

            import_and_lineage_ms = (time.perf_counter() - import_started) * 1000.0
            quantum_started = time.perf_counter()
            try:
                result = self.session.advance(
                    quantum_steps,
                    operation_id=operation_id,
                    logical_time=base.logical_time + 1,
                    expected_revision=base.revision,
                    expected_checkpoint_digest=base.checkpoint_digest,
                )
            except VGISessionError as exc:
                raise VGIFabricOperatorError(f"receiver VGI quantum did not commit: {exc}") from exc
            quantum_commit_ms = (time.perf_counter() - quantum_started) * 1000.0
            measured_total_ms = (time.perf_counter() - started) * 1000.0
            transfer_bytes = len(_canonical_bytes(transfer.to_dict()))
            self._last_measurement = {
                "transfer_bundle_bytes": transfer_bytes,
                "state_bytes": len(transfer.state_bytes),
                "bundle_decode_ms": bundle_decode_ms,
                "m1_import_and_m3_verification_ms": import_and_lineage_ms if imported else 0.0,
                "m4_quantum_m1_persist_and_m3_commit_ms": quantum_commit_ms,
                "handler_total_ms": measured_total_ms,
                "imported_on_this_call": imported,
            }

            return {
                "schema": VGI_FABRIC_RESULT_SCHEMA,
                "session_id": result.session.checkpoint.session_id,
                "descriptor_digest": result.descriptor_digest,
                "ground_fingerprint": self.session.descriptor.ground_fingerprint,
                "task_digest": self.session.descriptor.task_digest,
                "program_fingerprint": self.session.descriptor.program_fingerprint,
                "interpretation_fingerprint": self.session.descriptor.interpretation_fingerprint,
                "implementation_fingerprint": self.session.descriptor.implementation_fingerprint,
                "revision": result.revision,
                "checkpoint_digest": result.checkpoint_digest,
                "lineage_digest": result.session.lineage_manifest.digest,
                "logical_time": result.session.checkpoint.logical_time,
                "backend_fingerprint": result.session.checkpoint.backend_fingerprint,
                "state_schema_id": result.session.checkpoint.state_schema_id,
                "artifact_manifest_digest": result.session.checkpoint.artifact_manifest_digest,
                "predecessor_checkpoint_digest": result.session.checkpoint.predecessor_checkpoint_digest,
                "operation_id": operation_id,
                "replayed": result.replayed,
                "status": result.status,
                "total_steps": result.total_steps,
                "last_quantum_steps": result.last_quantum_steps,
                "final_pc": result.execution.final_pc,
                "output_count": len(result.execution.outputs),
                "measurement": dict(self._last_measurement),
            }
