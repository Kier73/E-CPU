"""Integrity-bound checkpoint composition for a navigable Transit computation."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from .classifier import HypervisorArbitrationEvent
from .evidence_path_resolver import (
    EvidencePathCatalogue,
    EvidencePathRequest,
    EvidencePathResolver,
    EvidencePathResult,
    EvidencePathStatus,
)
from .headless import HeadlessOS
from .hypervisor_transport import (
    HypervisorOperationChannel,
    HypervisorOperationResultChannel,
)
from .reliability import ReliableChannel
from .semantic_translation import RepresentationRef
from .transit_compute import TransitComputeHost
from .transit_session import TransitComputeSession


class NavigableComputationCheckpointError(ValueError):
    """A combined computation checkpoint is malformed, inconsistent, or not recoverable."""


@dataclass(frozen=True)
class RestoredNavigableComputation:
    """Restored protocol, receiver, route, and retry identities at one verified cut."""

    session: TransitComputeSession
    request_client: HypervisorOperationChannel
    response_client: HypervisorOperationResultChannel
    catalogue: EvidencePathCatalogue
    route_request: EvidencePathRequest
    route_result: Mapping[str, Any]
    retry_event: HypervisorArbitrationEvent


class NavigableComputationCheckpoint:
    """Bind receiver/session state, requester cursors, route evidence, and retry identity."""

    FORMAT = "mailcpu-navigable-computation-checkpoint-v1"
    _STATE_FIELDS_V1 = frozenset({
        "version",
        "session",
        "client_request_channel",
        "client_response_channel",
        "catalogue",
        "route_request",
        "route_result",
        "retry_event",
    })
    _STATE_FIELDS_V2 = _STATE_FIELDS_V1 | {"capture_mode"}

    @staticmethod
    def _canonical(value: Any) -> bytes:
        """Encode a value as deterministic UTF-8 JSON for checkpoint hashing."""
        try:
            return json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise NavigableComputationCheckpointError(
                "navigable computation checkpoint is outside canonical JSON"
            ) from exc

    @classmethod
    def capture(
        cls,
        session: TransitComputeSession,
        request_client: HypervisorOperationChannel,
        response_client: HypervisorOperationResultChannel,
        catalogue: EvidencePathCatalogue,
        route_request: EvidencePathRequest,
        route_result: Any,
        retry_event: HypervisorArbitrationEvent,
        *,
        allow_inflight: bool = False,
    ) -> dict[str, Any]:
        """Capture all durable route and Transit ledgers at a quiescent, fully resolved cut."""
        if not isinstance(session, TransitComputeSession):
            raise NavigableComputationCheckpointError("checkpoint requires a TransitComputeSession")
        if not isinstance(request_client, HypervisorOperationChannel):
            raise NavigableComputationCheckpointError("checkpoint requires a client operation channel")
        if not isinstance(response_client, HypervisorOperationResultChannel):
            raise NavigableComputationCheckpointError("checkpoint requires a client result channel")
        if not isinstance(catalogue, EvidencePathCatalogue):
            raise NavigableComputationCheckpointError("checkpoint requires an EvidencePathCatalogue")
        if not isinstance(route_request, EvidencePathRequest):
            raise NavigableComputationCheckpointError("checkpoint requires an EvidencePathRequest")
        if not isinstance(retry_event, HypervisorArbitrationEvent):
            raise NavigableComputationCheckpointError("checkpoint requires a typed retry event")
        if not isinstance(route_result, EvidencePathResult):
            raise NavigableComputationCheckpointError("checkpoint route result must be an EvidencePathResult")

        route_projection = route_result.to_dict()
        if (
            route_result.status is not EvidencePathStatus.FOUND
            or route_result.authoritative is not False
            or route_result.request_digest != route_request.digest
            or route_result.catalogue_digest != catalogue.digest
        ):
            raise NavigableComputationCheckpointError(
                "checkpoint route result must be FOUND and bound to the exact request and catalogue"
            )
        if not isinstance(allow_inflight, bool):
            raise NavigableComputationCheckpointError("allow_inflight must be a boolean")
        if not allow_inflight and session.phase != "idle":
            raise NavigableComputationCheckpointError(
                "cannot checkpoint a navigable computation with an active Transit phase"
            )

        client_request = request_client.channel
        client_response = response_client.channel
        if not allow_inflight:
            if (
                client_request.pending_sequences()
                or client_request.peek() is not None
                or client_request.transport.pending() != 0
            ):
                raise NavigableComputationCheckpointError(
                    "cannot checkpoint with pending client request transport data"
                )
            if (
                client_response.pending_sequences()
                or client_response.peek() is not None
                or client_response.transport.pending() != 0
            ):
                raise NavigableComputationCheckpointError(
                    "cannot checkpoint with unacknowledged client result transport data"
                )
        if (
            retry_event.source != client_request.source
            or retry_event.channel != client_request.channel
            or response_client.operation_source != retry_event.source
            or response_client.operation_channel != retry_event.channel
        ):
            raise NavigableComputationCheckpointError(
                "retry event identity does not match the checkpointed client channels"
            )

        state = {
            "version": 2 if allow_inflight else 1,
            "session": session.snapshot(allow_inflight=allow_inflight),
            "client_request_channel": client_request.snapshot(),
            "client_response_channel": response_client.snapshot(),
            "catalogue": catalogue.to_dict(),
            "route_request": route_request.to_dict(),
            "route_result": route_projection,
            "retry_event": retry_event.to_dict(),
        }
        if allow_inflight:
            state["capture_mode"] = "inflight"
        digest = hashlib.sha256(cls._canonical(state)).hexdigest()
        return {
            "format": cls.FORMAT,
            "digest": digest,
            "state": state,
        }

    @classmethod
    def restore(
        cls,
        payload: Mapping[str, Any],
        *,
        client_request_transport: Any,
        client_response_transport: Any,
        worker_request_transport: Any,
        worker_response_transport: Any,
        compute_host_factory: Callable[[HeadlessOS, int], TransitComputeHost] | None = None,
    ) -> RestoredNavigableComputation:
        """Verify and restore the complete cut, then recompute the saved route before exposing it."""
        if (
            not isinstance(payload, Mapping)
            or set(payload) != {"format", "digest", "state"}
            or payload.get("format") != cls.FORMAT
        ):
            raise NavigableComputationCheckpointError(
                "navigable computation checkpoint format or fields are invalid"
            )
        state = payload.get("state")
        if not isinstance(state, Mapping) or type(state.get("version")) is not int:
            raise NavigableComputationCheckpointError(
                "navigable computation checkpoint state schema is invalid"
            )
        state_version = state.get("version")
        if state_version == 1:
            schema_valid = set(state) == cls._STATE_FIELDS_V1
        elif state_version == 2:
            schema_valid = (
                set(state) == cls._STATE_FIELDS_V2
                and state.get("capture_mode") == "inflight"
            )
        else:
            schema_valid = False
        if not schema_valid:
            raise NavigableComputationCheckpointError(
                "navigable computation checkpoint state schema is invalid"
            )

        expected_digest = hashlib.sha256(cls._canonical(state)).digest()
        try:
            supplied_digest = bytes.fromhex(payload.get("digest", ""))
        except (TypeError, ValueError) as exc:
            raise NavigableComputationCheckpointError(
                "navigable computation checkpoint digest encoding is invalid"
            ) from exc
        if len(supplied_digest) != 32 or not hmac.compare_digest(
            supplied_digest,
            expected_digest,
        ):
            raise NavigableComputationCheckpointError(
                "navigable computation checkpoint digest mismatch"
            )

        supplied_transports = (
            ("client request", client_request_transport),
            ("client result", client_response_transport),
            ("worker request", worker_request_transport),
            ("worker result", worker_response_transport),
        )
        for label, transport in supplied_transports:
            pending = getattr(transport, "pending", None)
            if not callable(pending):
                raise NavigableComputationCheckpointError(
                    f"replacement {label} transport must expose pending()"
                )
            if pending() != 0:
                raise NavigableComputationCheckpointError(
                    f"cannot restore over a non-empty {label} transport"
                )

        try:
            catalogue_payload = state["catalogue"]
            request_payload = state["route_request"]
            route_projection = state["route_result"]
            raw_retry_event = state["retry_event"]
            client_request_state = state["client_request_channel"]
            client_response_state = state["client_response_channel"]
            session_state = state["session"]
            if not all(
                isinstance(item, Mapping)
                for item in (
                    catalogue_payload,
                    request_payload,
                    route_projection,
                    raw_retry_event,
                    client_request_state,
                    client_response_state,
                    session_state,
                )
            ):
                raise NavigableComputationCheckpointError(
                    "navigable computation checkpoint child state must contain objects"
                )

            catalogue = EvidencePathCatalogue.from_dict(catalogue_payload)
            route_request = EvidencePathRequest.from_dict(request_payload)
            retry_event = HypervisorArbitrationEvent.from_dict(raw_retry_event)
            session = TransitComputeSession.from_snapshot(
                session_state,
                worker_request_transport,
                worker_response_transport,
                compute_host_factory=compute_host_factory,
            )
            request_client = HypervisorOperationChannel(
                ReliableChannel.from_snapshot(
                    client_request_state,
                    client_request_transport,
                )
            )
            response_client = HypervisorOperationResultChannel.from_snapshot(
                client_response_state,
                client_response_transport,
            )
        except NavigableComputationCheckpointError:
            raise
        except Exception as exc:
            raise NavigableComputationCheckpointError(
                f"navigable computation checkpoint restore failed: {type(exc).__name__}: {exc}"
            ) from exc

        if (
            retry_event.source != request_client.channel.source
            or retry_event.channel != request_client.channel.channel
            or response_client.operation_source != retry_event.source
            or response_client.operation_channel != retry_event.channel
            or request_client.channel.peer != session.request.channel.source
            or request_client.channel.channel != session.request.channel.channel
            or response_client.channel.peer != session.response.channel.source
            or response_client.channel.channel != session.response.channel.channel
        ):
            raise NavigableComputationCheckpointError(
                "restored client and worker channel identities do not form one computation path"
            )

        # The saved retry must be the exact request representation that the
        # restored receiver would authorize now, not merely an event with a
        # similar operation name or payload.
        authorized_retry = session.worker.operating_system.hypervisor_authorize_event(
            session.worker.authority_pid,
            retry_event,
        )
        retry_ref = RepresentationRef.from_payload(
            "mailcpu.transit.authorized-event",
            1,
            authorized_retry.to_dict(),
        )
        if (
            route_request.target != retry_ref
            and not any(edge.source == retry_ref for edge in catalogue.edges)
        ):
            raise NavigableComputationCheckpointError(
                "retry event is neither the saved route target nor a source representation in the catalogue"
            )

        # Re-run the resolver against the restored receiver's live capability
        # table. A saved FOUND projection is not trusted as a substitute for
        # reconstruction or re-evaluation.
        try:
            route = EvidencePathResolver().resolve(
                catalogue,
                route_request,
                session.worker.operating_system,
                session.worker.authority_pid,
            )
        except Exception as exc:
            raise NavigableComputationCheckpointError(
                f"restored route resolution failed: {type(exc).__name__}: {exc}"
            ) from exc
        if route.status is not EvidencePathStatus.FOUND or route.to_dict() != dict(route_projection):
            raise NavigableComputationCheckpointError(
                "restored route does not reproduce the saved route projection"
            )

        return RestoredNavigableComputation(
            session=session,
            request_client=request_client,
            response_client=response_client,
            catalogue=catalogue,
            route_request=route_request,
            route_result=route.to_dict(),
            retry_event=retry_event,
        )
