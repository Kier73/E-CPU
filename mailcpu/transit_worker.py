"""Receiver-side worker for bounded MailCPU transit computations."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any, Callable, Mapping

from .classifier import HypervisorArbitrationEvent, HypervisorDomain, HypervisorExecutionResult
from .headless import HeadlessOS
from .hypervisor_transport import (
    HypervisorOperationChannel,
    HypervisorOperationResultChannel,
)
from .reliability import ReliableChannel
from .transit_compute import TransitComputeHost
from .transit_structural_memory import (
    TRANSIT_STRUCTURAL_MEMORY_OPERATION,
    TRANSIT_STRUCTURAL_MEMORY_RESOURCE,
)
from .semantic_translation import (
    SemanticTranslationError,
    build_transit_translation_evidence,
)


class TransitComputeWorker:
    """Receiver-side service for isolated, capability-gated compute jobs."""

    def __init__(
        self,
        operating_system: HeadlessOS,
        authority_pid: int,
        compute_host: TransitComputeHost | None = None,
    ) -> None:
        """Mathematics: bind worker W to receiver state S and authority a, so each request is reauthorized by G_S(a, resource)."""

        if not isinstance(operating_system, HeadlessOS):
            raise TypeError("transit worker requires a HeadlessOS receiver")
        if not isinstance(authority_pid, int) or isinstance(authority_pid, bool):
            raise TypeError("transit worker authority pid must be an integer")
        operating_system.environment.kernel._process(authority_pid)
        if compute_host is not None and not isinstance(compute_host, TransitComputeHost):
            raise TypeError("transit worker compute_host must be a TransitComputeHost")
        self.operating_system = operating_system
        self.authority_pid = authority_pid
        self.compute_host = compute_host or TransitComputeHost()

    def _authorize(self, event: HypervisorArbitrationEvent) -> HypervisorArbitrationEvent:
        """Mathematics: replace all peer-supplied grants with receiver-local capability projection G_S(a, event)."""

        return self.operating_system.hypervisor_authorize_event(self.authority_pid, event)

    def serve_once(
        self,
        request: HypervisorOperationChannel,
        response: HypervisorOperationResultChannel,
    ) -> HypervisorExecutionResult | None:
        """Mathematics: consume at most one authorized request, commit its effect to response R, then acknowledge its request frame."""

        if not isinstance(request, HypervisorOperationChannel):
            raise TypeError("transit worker request must be a HypervisorOperationChannel")
        if not isinstance(response, HypervisorOperationResultChannel):
            raise TypeError("transit worker response must be a HypervisorOperationResultChannel")
        handlers = {HypervisorDomain.CPU: self.compute_host.handle}
        # A structural-memory coordinate is classified as a read/data resource.
        # Expose the filesystem decision to the router only when the exact
        # structural-memory operation is registered; the router still performs
        # strict operation/resource dispatch and the backend rechecks authority.
        manifest = self._backend_manifest(self.compute_host)
        if (
            TRANSIT_STRUCTURAL_MEMORY_OPERATION,
            TRANSIT_STRUCTURAL_MEMORY_RESOURCE,
        ) in manifest:
            handlers[HypervisorDomain.FILESYSTEM] = self.compute_host.handle
        authorized_events: list[HypervisorArbitrationEvent] = []

        def authorize(event: HypervisorArbitrationEvent) -> HypervisorArbitrationEvent:
            """Mathematics: retain the exact receiver-authorized event e' for the effect-encoding proof boundary."""
            authorized = self._authorize(event)
            authorized_events[:] = [authorized]
            return authorized

        def encode_effect(raw_effect: Any) -> dict[str, Any]:
            """Mathematics: bind handler effect E to event identity I, decision receipt D, backend manifest M, and canonical round-trip E'=E."""
            if not authorized_events:
                raise SemanticTranslationError("Transit effect has no receiver-authorized event")
            event = authorized_events[0]
            decision = self.operating_system.hypervisor_arbitration.decision_projection_for(event.identity)
            if decision is None:
                raise SemanticTranslationError("Transit effect has no committed hypervisor decision")
            _action, domain, decision_receipt, _revision = decision
            if not isinstance(raw_effect, Mapping):
                raise SemanticTranslationError("Transit backend effects must be JSON objects")
            if "_semantic_translation" in raw_effect:
                raise SemanticTranslationError("Transit backend effect uses the reserved semantic evidence field")
            try:
                canonical_effect = json.loads(
                    json.dumps(
                        raw_effect,
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=False,
                        allow_nan=False,
                    )
                )
            except (TypeError, ValueError) as exc:
                raise SemanticTranslationError("Transit backend effect is outside canonical JSON") from exc
            evidence = build_transit_translation_evidence(
                event,
                raw_effect,
                canonical_effect,
                backend_manifest=manifest,
                decision_receipt=decision_receipt,
                domain=domain.value,
            )
            encoded = dict(canonical_effect)
            encoded["_semantic_translation"] = evidence.to_dict()
            return encoded

        return request.receive_and_reply_event(
            self.operating_system.hypervisor_arbitration,
            authorize,
            handlers,
            response,
            encode_effect,
        )

    @staticmethod
    def _backend_manifest(host: TransitComputeHost) -> tuple[tuple[str, str], ...]:
        """Mathematics: project executable handler configuration to its finite, canonical domain dom(R)."""

        registered = getattr(host, "registered_backends", None)
        if callable(registered):
            raw = registered()
        else:
            raw = (
                (
                    getattr(host, "operation_name", None),
                    getattr(host, "resource_name", None),
                ),
            )
        try:
            manifest = tuple((item[0], item[1]) for item in raw)
        except (TypeError, IndexError) as exc:
            raise ValueError("transit compute host backend manifest is invalid") from exc
        if (
            not manifest
            or any(
                not isinstance(operation, str)
                or not operation
                or not isinstance(resource, str)
                or not resource
                for operation, resource in manifest
            )
            or tuple(sorted(set(manifest))) != manifest
        ):
            raise ValueError("transit compute host backend manifest must be sorted, unique, and non-empty")
        return manifest

    def snapshot(
        self,
        request: HypervisorOperationChannel,
        response: HypervisorOperationResultChannel,
    ) -> dict[str, object]:
        """Mathematics: checkpoint OS state, backend manifest, and channel ledgers only at a quiescent boundary Q=0."""

        if not isinstance(request, HypervisorOperationChannel):
            raise TypeError("worker checkpoint requires a HypervisorOperationChannel")
        if not isinstance(response, HypervisorOperationResultChannel):
            raise TypeError("worker checkpoint requires a HypervisorOperationResultChannel")
        if request.channel.pending_sequences() or request.channel.peek() is not None or request.channel.transport.pending() != 0:
            raise ValueError("cannot checkpoint transit worker with pending request transport data")
        if response.channel.pending_sequences() or response.channel.transport.pending() != 0:
            raise ValueError("cannot checkpoint transit worker with unacknowledged response data")
        state = {
            "version": 2,
            "authority_pid": self.authority_pid,
            "compute_bounds": {
                "max_source_bytes": self.compute_host.max_source_bytes,
                "max_instructions": self.compute_host.max_instructions,
                "max_ticks": self.compute_host.max_ticks,
                "max_registers": self.compute_host.max_registers,
            },
            "backend_manifest": [list(item) for item in self._backend_manifest(self.compute_host)],
            "receiver": self.operating_system.snapshot(),
            "request_channel": request.channel.snapshot(),
            "response_channel": response.snapshot(),
        }
        canonical = json.dumps(
            state,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        return {
            "format": "mailcpu-transit-worker-checkpoint-v2",
            "digest": hashlib.sha256(canonical).hexdigest(),
            "state": state,
        }

    @classmethod
    def from_snapshot(
        cls,
        payload: Mapping[str, Any],
        request_transport: Any,
        response_transport: Any,
        compute_host_factory: Callable[[HeadlessOS, int], TransitComputeHost] | None = None,
    ) -> tuple[
        "TransitComputeWorker",
        HypervisorOperationChannel,
        HypervisorOperationResultChannel,
    ]:
        """Mathematics: restore W and its reliable cursors after reattaching a backend factory whose manifest matches checkpoint C."""

        if not isinstance(payload, Mapping):
            raise ValueError("transit worker checkpoint must be a mapping")
        if set(payload) != {"format", "digest", "state"}:
            raise ValueError("transit worker checkpoint fields are invalid")
        checkpoint_format = payload.get("format")
        if checkpoint_format == "mailcpu-transit-worker-checkpoint-v1":
            expected_version = 1
            expected_state_fields = {
                "version",
                "authority_pid",
                "compute_bounds",
                "receiver",
                "request_channel",
                "response_channel",
            }
        elif checkpoint_format == "mailcpu-transit-worker-checkpoint-v2":
            expected_version = 2
            expected_state_fields = {
                "version",
                "authority_pid",
                "compute_bounds",
                "backend_manifest",
                "receiver",
                "request_channel",
                "response_channel",
            }
        else:
            raise ValueError("unsupported transit worker checkpoint format")

        state = payload.get("state")
        if not isinstance(state, Mapping):
            raise ValueError("transit worker checkpoint state must be a mapping")
        if set(state) != expected_state_fields:
            raise ValueError("transit worker checkpoint state fields are invalid")
        version = state.get("version")
        if not isinstance(version, int) or isinstance(version, bool) or version != expected_version:
            raise ValueError("unsupported transit worker checkpoint state")
        try:
            canonical = json.dumps(
                state,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
            raw_digest = payload.get("digest")
            if not isinstance(raw_digest, str):
                raise ValueError("transit worker checkpoint digest must be text")
            supplied_digest = bytes.fromhex(raw_digest)
            expected_digest = hashlib.sha256(canonical).digest()
        except (TypeError, ValueError) as exc:
            raise ValueError("transit worker checkpoint is outside canonical JSON or digest encoding") from exc
        if len(supplied_digest) != 32 or not hmac.compare_digest(supplied_digest, expected_digest):
            raise ValueError("transit worker checkpoint digest mismatch")

        raw_receiver = state.get("receiver")
        raw_bounds = state.get("compute_bounds")
        raw_request = state.get("request_channel")
        raw_response = state.get("response_channel")
        if not all(isinstance(item, Mapping) for item in (raw_receiver, raw_bounds, raw_request, raw_response)):
            raise ValueError("transit worker checkpoint is incomplete")
        expected_bounds = {
            "max_source_bytes",
            "max_instructions",
            "max_ticks",
            "max_registers",
        }
        if set(raw_bounds) != expected_bounds:
            raise ValueError("transit worker compute bounds are invalid")
        if any(
            not isinstance(raw_bounds[key], int) or isinstance(raw_bounds[key], bool)
            for key in expected_bounds
        ):
            raise ValueError("transit worker compute bounds must be integers")
        authority_pid = state.get("authority_pid")
        if not isinstance(authority_pid, int) or isinstance(authority_pid, bool):
            raise ValueError("transit worker authority pid must be an integer")

        operating_system = HeadlessOS.from_snapshot(dict(raw_receiver))
        if compute_host_factory is None:
            host: TransitComputeHost = TransitComputeHost(
                max_source_bytes=raw_bounds["max_source_bytes"],
                max_instructions=raw_bounds["max_instructions"],
                max_ticks=raw_bounds["max_ticks"],
                max_registers=raw_bounds["max_registers"],
            )
        else:
            if not callable(compute_host_factory):
                raise TypeError("compute_host_factory must be callable")
            host = compute_host_factory(operating_system, authority_pid)
            if not isinstance(host, TransitComputeHost):
                raise TypeError("compute_host_factory must return a TransitComputeHost")
            actual_bounds = {
                "max_source_bytes": host.max_source_bytes,
                "max_instructions": host.max_instructions,
                "max_ticks": host.max_ticks,
                "max_registers": host.max_registers,
            }
            if actual_bounds != dict(raw_bounds):
                raise ValueError("restored backend compute bounds do not match checkpoint")

        if expected_version == 2:
            raw_manifest = state.get("backend_manifest")
            if not isinstance(raw_manifest, list) or not raw_manifest:
                raise ValueError("transit worker backend manifest must be a non-empty list")
            manifest_items: list[tuple[str, str]] = []
            for item in raw_manifest:
                if (
                    not isinstance(item, list)
                    or len(item) != 2
                    or not all(isinstance(part, str) and part for part in item)
                ):
                    raise ValueError("transit worker backend manifest entries must be non-empty string pairs")
                manifest_items.append((item[0], item[1]))
            expected_manifest = tuple(manifest_items)
            if tuple(sorted(set(expected_manifest))) != expected_manifest:
                raise ValueError("transit worker backend manifest must be sorted and unique")
        else:
            expected_manifest = (
                (TransitComputeHost.operation_name, TransitComputeHost.resource_name),
            )
        actual_manifest = cls._backend_manifest(host)
        if actual_manifest != expected_manifest:
            raise ValueError(
                "restored backend manifest does not match checkpoint; reattach the same operation/resource handlers"
            )

        worker = cls(operating_system, authority_pid, host)
        request_channel = HypervisorOperationChannel(
            ReliableChannel.from_snapshot(dict(raw_request), request_transport)
        )
        response_channel = HypervisorOperationResultChannel.from_snapshot(
            raw_response,
            response_transport,
        )
        return worker, request_channel, response_channel
