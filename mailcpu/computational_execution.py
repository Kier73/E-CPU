"""Mathematics: Revalidate semantic computational routes before Virtual Layer execution.

The route witness remains a non-authoritative proposal. This coordinator
re-runs local resolution, checks the selected runtime against the advertised
locus, and binds a deterministic admission context into the ordinary
Virtual Layer event before the existing Hypervisor execution ledger acts.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Any

from .classifier import HypervisorAction, HypervisorDomain, HypervisorExecutionResult
from .computational_resolver import (
    ComputationalAddress,
    ComputationalAddressResolver,
    ComputationalHostCatalogue,
    ComputationalHostLocus,
    ComputationalRouteWitness,
    ComputationalResolutionStatus,
)
from .headless import HeadlessOS
from .semantic_translation import canonical_value_digest
from .virtual_layer import VirtualLayerRuntime, virtual_layer_operator_resource

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class ComputationalExecutionAdmissionError(ValueError):
    """Mathematics: An execution-admission request or host binding is malformed."""


class ComputationalExecutionStatus(str, Enum):
    """Mathematics: Typed outcome of witness revalidation and Hypervisor handoff."""

    EXECUTED = "executed"
    REPLAYED = "replayed"
    HYPERVISOR_REFUSED = "hypervisor_refused"
    WITNESS_STALE = "witness_stale"
    HOST_MISMATCH = "host_mismatch"
    EXECUTION_FAILED = "execution_failed"


def _label(value: Any, name: str, maximum: int = 256) -> str:
    """Mathematics: Validate a bounded, non-empty execution identity label."""
    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or len(value.encode("utf-8")) > maximum
    ):
        raise ComputationalExecutionAdmissionError(
            f"{name} must be trimmed non-empty text of at most {maximum} UTF-8 bytes"
        )
    return value


def _sha256(value: Any, name: str) -> str:
    """Mathematics: Require one lowercase SHA-256 identity."""
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ComputationalExecutionAdmissionError(f"{name} must be lowercase SHA-256 hex")
    return value


@dataclass(frozen=True)
class ComputationalExecutionResult:
    """Mathematics: Auditable outcome linking one revalidated route to a Hypervisor execution result."""

    status: ComputationalExecutionStatus
    address_digest: str
    witness_digest: str
    admission_digest: str | None
    admission_receipt: str
    execution: HypervisorExecutionResult | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        """Mathematics: Enforce result-state consistency and bind every returned receipt."""
        if not isinstance(self.status, ComputationalExecutionStatus):
            object.__setattr__(self, "status", ComputationalExecutionStatus(self.status))
        _sha256(self.address_digest, "address_digest")
        _sha256(self.witness_digest, "witness_digest")
        _sha256(self.admission_receipt, "admission_receipt")
        if self.admission_digest is not None:
            _sha256(self.admission_digest, "admission_digest")
        if self.execution is not None and not isinstance(self.execution, HypervisorExecutionResult):
            raise ComputationalExecutionAdmissionError("execution must be a HypervisorExecutionResult or None")
        if self.reason is not None and not isinstance(self.reason, str):
            raise ComputationalExecutionAdmissionError("reason must be text or None")
        successful = self.status in {
            ComputationalExecutionStatus.EXECUTED,
            ComputationalExecutionStatus.REPLAYED,
        }
        if successful:
            if (
                self.execution is None
                or self.execution.action is not HypervisorAction.ALLOW
                or self.execution.domain is not HypervisorDomain.CPU
                or not self.execution.executed
            ):
                raise ComputationalExecutionAdmissionError("successful status requires an executed CPU ALLOW result")
            if self.status is ComputationalExecutionStatus.REPLAYED and not self.execution.replayed:
                raise ComputationalExecutionAdmissionError("REPLAYED status requires a replayed Hypervisor result")
            if self.status is ComputationalExecutionStatus.EXECUTED and self.execution.replayed:
                raise ComputationalExecutionAdmissionError("EXECUTED status cannot contain a replay result")
        elif self.status is ComputationalExecutionStatus.HYPERVISOR_REFUSED:
            if (
                self.execution is None
                or (
                    self.execution.action is HypervisorAction.ALLOW
                    and self.execution.domain is HypervisorDomain.CPU
                    and self.execution.executed
                )
            ):
                raise ComputationalExecutionAdmissionError("Hypervisor refusal requires a non-executed policy result")
        elif self.execution is not None and self.status in {
            ComputationalExecutionStatus.WITNESS_STALE,
            ComputationalExecutionStatus.HOST_MISMATCH,
        }:
            raise ComputationalExecutionAdmissionError("pre-execution refusal cannot contain an execution result")

    @property
    def accepted(self) -> bool:
        """Mathematics: Project completed execution as membership in the executed/replayed outcomes."""
        return self.status in {
            ComputationalExecutionStatus.EXECUTED,
            ComputationalExecutionStatus.REPLAYED,
        }

    @property
    def executed(self) -> bool:
        """Mathematics: Report only an execution explicitly committed by the Hypervisor result."""
        return self.execution is not None and self.execution.executed

    @property
    def replayed(self) -> bool:
        """Mathematics: Report whether the Hypervisor returned an exact semantic replay."""
        return self.execution is not None and self.execution.replayed

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: Serialize the route-to-execution result without issuing a new authority grant."""
        return {
            "schema": "mailcpu.computational-execution-result.v1",
            "status": self.status.value,
            "accepted": self.accepted,
            "executed": self.executed,
            "replayed": self.replayed,
            "address_digest": self.address_digest,
            "witness_digest": self.witness_digest,
            "admission_digest": self.admission_digest,
            "admission_receipt": self.admission_receipt,
            "execution": None if self.execution is None else self.execution.to_dict(),
            "reason": self.reason,
        }


class ComputationalExecutionAdmissionCoordinator:
    """Mathematics: Revalidate a local route witness and hand its workload to the existing Hypervisor path."""

    def __init__(
        self,
        operating_system: HeadlessOS,
        resolver: ComputationalAddressResolver | None = None,
        *,
        timing_probe: Any | None = None,
    ) -> None:
        """Mathematics: Bind the coordinator to one receiver-local OS, semantic resolver, and optional timing observer."""
        if not isinstance(operating_system, HeadlessOS):
            raise ComputationalExecutionAdmissionError("execution admission requires a HeadlessOS")
        if resolver is not None and not isinstance(resolver, ComputationalAddressResolver):
            raise ComputationalExecutionAdmissionError("resolver must be a ComputationalAddressResolver")
        if timing_probe is not None and not callable(getattr(timing_probe, "measure", None)):
            raise ComputationalExecutionAdmissionError("timing_probe must expose a measure context manager")
        self.operating_system = operating_system
        self.resolver = resolver or ComputationalAddressResolver()
        self.timing_probe = timing_probe

    def _journal(self):
        """Mathematics: Resolve the kernel journal used by the existing Hypervisor audit trail."""
        try:
            journal = self.operating_system.environment.kernel.journal
        except AttributeError as exc:
            raise ComputationalExecutionAdmissionError("operating system has no kernel journal") from exc
        if not callable(getattr(journal, "append", None)):
            raise ComputationalExecutionAdmissionError("operating system journal is invalid")
        return journal

    def _refuse(
        self,
        address: ComputationalAddress,
        witness: ComputationalRouteWitness,
        *,
        source: str,
        channel: str,
        sequence: int,
        status: ComputationalExecutionStatus,
        reason: str,
    ) -> ComputationalExecutionResult:
        """Mathematics: Journal one fail-closed refusal without preparing an operator event."""
        receipt = self._journal().append(
            "computational.execution.refuse",
            {
                "source": source,
                "channel": channel,
                "sequence": sequence,
                "status": status.value,
                "reason": reason,
                "address_digest": address.digest,
                "witness_digest": witness.digest,
            },
        ).digest
        return ComputationalExecutionResult(
            status=status,
            address_digest=address.digest,
            witness_digest=witness.digest,
            admission_digest=None,
            admission_receipt=receipt,
            reason=reason,
        )

    @staticmethod
    def _runtime_matches(
        address: ComputationalAddress,
        witness: ComputationalRouteWitness,
        locus: ComputationalHostLocus,
        runtime: VirtualLayerRuntime,
    ) -> tuple[bool, str]:
        """Mathematics: Verify that the concrete node-local runtime matches its selected declarative locus."""
        if not isinstance(runtime, VirtualLayerRuntime):
            return False, "selected host runtime is not a VirtualLayerRuntime"
        if locus.runtime_binding is not runtime:
            return False, "runtime object is not the exact receiver-local runtime bound to this host locus"
        if (
            locus.implementation_fingerprint is None
            or witness.implementation_fingerprint is None
            or locus.implementation_fingerprint != witness.implementation_fingerprint
        ):
            return False, "execution requires a matching explicit host implementation fingerprint pin"
        if runtime.node_id != witness.node_id or runtime.node_id != locus.node_id:
            return False, "runtime placement differs from the selected logical-host locus"
        try:
            spec, handler = runtime.registry.resolve(address.operator_id, witness.operator_version)
        except Exception as exc:
            return False, f"selected runtime cannot resolve the exact operator: {type(exc).__name__}: {exc}"
        if handler is None or not callable(handler):
            return False, "selected runtime has no bound local operator implementation"
        if locus.handler_binding is not handler:
            return False, "runtime operator handler is not the exact handler bound to this host locus"
        if (
            spec.digest != address.operator_contract_digest
            or spec.digest != locus.operator_spec.digest
            or spec.digest != witness.operator_contract_digest
            or not spec.replay_safe
        ):
            return False, "selected runtime operator contract differs from the addressed pure contract"
        if set(runtime.substrates & set(spec.substrates)) != set(locus.substrates):
            return False, "runtime substrate capability differs from the advertised locus"
        for name in ("virtual_capacity", "max_energy", "max_bytes", "max_virtual_ticks"):
            if getattr(runtime, name) != getattr(locus, name):
                return False, f"runtime {name} differs from the advertised locus"
        reference = address.workload.operator_ref(address.operator_id)
        if reference.preferred_substrate is not None:
            expected_substrate = reference.preferred_substrate
        else:
            expected_substrate = next(
                (item for item in spec.substrates if item in runtime.substrates),
                None,
            )
        if expected_substrate is None or expected_substrate != witness.substrate:
            return False, "runtime substrate selection differs from the route witness"
        expected_resource = virtual_layer_operator_resource(address.operator_id, witness.operator_version)
        if witness.resource != expected_resource:
            return False, "route witness resource differs from the exact operator resource"
        return True, ""

    @staticmethod
    def _admission_context(
        address: ComputationalAddress,
        witness: ComputationalRouteWitness,
    ) -> dict[str, Any]:
        """Mathematics: Construct deterministic execution metadata whose digest will enter the Hypervisor event fingerprint."""
        context: dict[str, Any] = {
            "schema": "mailcpu.computational-execution-admission.v1",
            "address_digest": address.digest,
            "witness_digest": witness.digest,
            "catalogue_digest": witness.catalogue_digest,
            "authority_digest": witness.authority_digest,
            "system_ground_digest": witness.system_ground_digest,
            "computational_ground_fingerprint": witness.computational_ground_fingerprint,
            "program_fingerprint": witness.program_fingerprint,
            "implementation_fingerprint": witness.implementation_fingerprint,
            "host_id": witness.host_id,
            "node_id": witness.node_id,
            "operator_id": witness.operator_id,
            "operator_version": witness.operator_version,
            "operator_contract_digest": witness.operator_contract_digest,
            "input_digest": witness.input_digest,
            "state_digest": witness.state_digest,
            "logical_time": witness.logical_time,
            "observation_kind": witness.observation_kind,
            "substrate": witness.substrate,
        }
        context["admission_digest"] = canonical_value_digest(context)
        return context

    def execute(
        self,
        address: ComputationalAddress,
        witness: ComputationalRouteWitness,
        catalogue: ComputationalHostCatalogue,
        runtime: VirtualLayerRuntime,
        *,
        source: str,
        channel: str,
        sequence: int,
    ) -> ComputationalExecutionResult:
        """Mathematics: Re-resolve the exact witness, then delegate execution to the ordinary Virtual Layer and Hypervisor."""
        if not isinstance(address, ComputationalAddress):
            raise ComputationalExecutionAdmissionError("execute requires a ComputationalAddress")
        if not isinstance(witness, ComputationalRouteWitness):
            raise ComputationalExecutionAdmissionError("execute requires a ComputationalRouteWitness")
        if not isinstance(catalogue, ComputationalHostCatalogue):
            raise ComputationalExecutionAdmissionError("execute requires a ComputationalHostCatalogue")
        source = _label(source, "source")
        channel = _label(channel, "channel")
        if type(sequence) is not int or sequence < 1:
            raise ComputationalExecutionAdmissionError("sequence must be a positive strict integer")

        try:
            if self.timing_probe is None:
                resolution = self.resolver.resolve(address, catalogue, self.operating_system)
            else:
                with self.timing_probe.measure("receiver_witness_revalidation", correlation_id=address.digest):
                    resolution = self.resolver.resolve(address, catalogue, self.operating_system)
        except Exception as exc:
            return self._refuse(
                address, witness, source=source, channel=channel, sequence=sequence,
                status=ComputationalExecutionStatus.WITNESS_STALE,
                reason=f"live semantic resolution failed: {type(exc).__name__}: {exc}",
            )
        if (
            resolution.status is not ComputationalResolutionStatus.FOUND
            or resolution.witness is None
            or witness.address_digest != address.digest
            or resolution.witness.digest != witness.digest
        ):
            return self._refuse(
                address, witness, source=source, channel=channel, sequence=sequence,
                status=ComputationalExecutionStatus.WITNESS_STALE,
                reason="fresh receiver-local resolution did not reproduce the exact supplied route witness",
            )

        if self.timing_probe is None:
            matches = tuple(
                item for item in catalogue.loci
                if item.host_id == witness.host_id
                and item.operator_spec.operator_id == address.operator_id
                and item.operator_spec.version == witness.operator_version
            )
            runtime_matches, runtime_reason = self._runtime_matches(address, witness, matches[0], runtime) if len(matches) == 1 else (False, "selected host locus is absent or ambiguous")
        else:
            with self.timing_probe.measure("receiver_host_binding_validation", correlation_id=address.digest):
                matches = tuple(
                    item for item in catalogue.loci
                    if item.host_id == witness.host_id
                    and item.operator_spec.operator_id == address.operator_id
                    and item.operator_spec.version == witness.operator_version
                )
                runtime_matches, runtime_reason = self._runtime_matches(address, witness, matches[0], runtime) if len(matches) == 1 else (False, "selected host locus is absent or ambiguous")
        if len(matches) != 1:
            return self._refuse(
                address, witness, source=source, channel=channel, sequence=sequence,
                status=ComputationalExecutionStatus.HOST_MISMATCH,
                reason="selected logical host locus is absent or ambiguous in the live catalogue",
            )
        locus = matches[0]
        if not runtime_matches:
            return self._refuse(
                address, witness, source=source, channel=channel, sequence=sequence,
                status=ComputationalExecutionStatus.HOST_MISMATCH,
                reason=runtime_reason,
            )

        context = self._admission_context(address, witness)
        try:
            self._journal().append(
                "computational.execution.revalidated",
                {
                    "source": source,
                    "channel": channel,
                    "sequence": sequence,
                    "admission_context": context,
                },
            )
        except Exception as exc:
            return self._refuse(
                address, witness, source=source, channel=channel, sequence=sequence,
                status=ComputationalExecutionStatus.EXECUTION_FAILED,
                reason=f"could not record execution revalidation: {type(exc).__name__}: {exc}",
            )

        try:
            execution = runtime.execute_operator(
                self.operating_system,
                locus.authority_pid,
                source,
                channel,
                sequence,
                address.workload.logical_time,
                address.workload,
                address.operator_id,
                computational_admission=context,
            )
        except Exception as exc:
            receipt = self._journal().append(
                "computational.execution.failure",
                {
                    "source": source,
                    "channel": channel,
                    "sequence": sequence,
                    "address_digest": address.digest,
                    "witness_digest": witness.digest,
                    "admission_digest": context["admission_digest"],
                    "error": f"{type(exc).__name__}: {exc}",
                },
            ).digest
            return ComputationalExecutionResult(
                status=ComputationalExecutionStatus.EXECUTION_FAILED,
                address_digest=address.digest,
                witness_digest=witness.digest,
                admission_digest=context["admission_digest"],
                admission_receipt=receipt,
                reason=f"{type(exc).__name__}: {exc}",
            )

        if (
            execution.action is not HypervisorAction.ALLOW
            or execution.domain is not HypervisorDomain.CPU
            or not execution.executed
        ):
            receipt = self._journal().append(
                "computational.execution.hypervisor_refused",
                {
                    "source": source,
                    "channel": channel,
                    "sequence": sequence,
                    "address_digest": address.digest,
                    "witness_digest": witness.digest,
                    "admission_digest": context["admission_digest"],
                    "execution": execution.to_dict(),
                },
            ).digest
            return ComputationalExecutionResult(
                status=ComputationalExecutionStatus.HYPERVISOR_REFUSED,
                address_digest=address.digest,
                witness_digest=witness.digest,
                admission_digest=context["admission_digest"],
                admission_receipt=receipt,
                execution=execution,
                reason="the existing Hypervisor did not authorize a CPU operator effect",
            )

        receipt = self._journal().append(
            "computational.execution.complete",
            {
                "source": source,
                "channel": channel,
                "sequence": sequence,
                "address_digest": address.digest,
                "witness_digest": witness.digest,
                "admission_digest": context["admission_digest"],
                "execution": execution.to_dict(),
            },
        ).digest
        status = (
            ComputationalExecutionStatus.REPLAYED
            if execution.replayed
            else ComputationalExecutionStatus.EXECUTED
        )
        return ComputationalExecutionResult(
            status=status,
            address_digest=address.digest,
            witness_digest=witness.digest,
            admission_digest=context["admission_digest"],
            admission_receipt=receipt,
            execution=execution,
        )
