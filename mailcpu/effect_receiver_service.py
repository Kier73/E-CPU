"""IPS-008: an authenticated process-owned Ground effect receiver.

Reuse the native E-CPU mutual-TLS adapter, SocketTransport message framing,
IPS-005 quorum verification, and IPS-007 atomic effect register. This service
does not replace the majority or synthesize authority from a TLS identity.

A PREPARE call durably freezes the receiver's *installed* old root before the
caller is allowed to advance the quorum assignment. If quorum advancement
fails, the freeze remains until an exact valid next assignment is installed.
"""
from __future__ import annotations

import socket
import ssl
import time
from typing import Any, Mapping

from .fenced_effect_receiver import (
    FencedGroundEffectReceiver, PublishedGroundEffect, EffectFencingRefused,
)
from .fenced_generated_ground import FencedGroundLineage
from .model import Message
from .mtls_transport import (
    accept_mutual_tls, connect_mutual_tls, MutualTLSTransportError,
)
from .socket_transport import SocketTransport, SocketTransportError

OWNER = "effect-ground-owner"
RECEIVER = "effect-ground-receiver"
_MAX_SECONDS = 8


class EffectReceiverServiceError(ValueError):
    """Refuse an unauthorized operation, malformed envelope or network failure."""


def _wait_message(transport: SocketTransport, address: str, timeout: float) -> Message:
    """Poll the existing E-CPU framed transport until one bounded response arrives."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        message = transport.poll(address)
        if message is not None:
            return message
        if transport.closed:
            raise EffectReceiverServiceError("effect peer disconnected before response")
        time.sleep(.005)
    raise EffectReceiverServiceError("authenticated effect RPC timed out")


class AuthenticatedGroundEffectService:
    """Receiver process owns SQLite authority, resource policy, and TLS identity."""

    def __init__(
        self,
        receiver: FencedGroundEffectReceiver,
        publisher: FencedGroundLineage,
        listener: socket.socket,
        tls_context: ssl.SSLContext,
        *,
        expected_owner_dns: str,
    ) -> None:
        """Bind only a resource-local receiver to an original Ground quorum verifier."""
        if (not isinstance(receiver, FencedGroundEffectReceiver)
                or not isinstance(publisher, FencedGroundLineage)
                or not isinstance(listener, socket.socket)
                or not isinstance(tls_context, ssl.SSLContext)
                or type(expected_owner_dns) is not str or not expected_owner_dns):
            raise EffectReceiverServiceError("effect receiver service has invalid trusted configuration")
        if publisher.plan.digest != receiver.plan_digest:
            raise EffectReceiverServiceError("receiver and verifier have different Ground plans")
        self.receiver = receiver
        self.publisher = publisher
        self.listener = listener
        self.context = tls_context
        self.expected_owner_dns = expected_owner_dns

    @property
    def address(self) -> tuple[str, int]:
        """Report the actual bound TCP listener for test and supervisor discovery."""
        host, port = self.listener.getsockname()[:2]
        return str(host), int(port)

    def _dispatch(self, request: Any) -> dict[str, Any]:
        """Apply one authenticated, typed command after local authority checks."""
        if not isinstance(request, Mapping) or set(request) != {"kind", "data"}:
            raise EffectReceiverServiceError("request schema is not exact")
        kind, data = request["kind"], request["data"]
        if not isinstance(data, Mapping):
            raise EffectReceiverServiceError("effect request data must be an object")
        if kind == "snapshot":
            if data:
                raise EffectReceiverServiceError("snapshot takes no parameters")
            return self.receiver.snapshot()
        if kind == "prepare":
            if set(data) != {"source_root", "target_host"}:
                raise EffectReceiverServiceError("handoff preparation fields invalid")
            head = self.publisher.restore_latest()
            if head.manifest.digest != data["source_root"]:
                raise EffectFencingRefused("preparation source is not current quorum root")
            return self.receiver.prepare_handoff(
                self.publisher, head, next_host=data["target_host"],
            )
        if kind == "activate":
            if set(data) != {"expected_root"}:
                raise EffectReceiverServiceError("activation fields invalid")
            head = self.publisher.restore_latest()
            if head.manifest.digest != data["expected_root"]:
                raise EffectFencingRefused("activation requires exact quorum head")
            return self.receiver.install(self.publisher, head, require_handoff=True)
        if kind == "apply":
            if set(data) != {"claim"}:
                raise EffectReceiverServiceError("effect application fields invalid")
            return self.receiver.apply(PublishedGroundEffect.from_dict(data["claim"]))
        raise EffectReceiverServiceError("unknown effect command")

    def serve_once(self, *, handshake_timeout: float = 1.0) -> bool:
        """Serve exactly one mTLS-authenticated frame and durable result response.

        Invalid TLS handshakes produce no application response; a valid owner
        gets only refusal details for an invalid command. A killed process can
        be replaced against its original durable resource database.
        """
        try:
            connection = accept_mutual_tls(
                self.listener, RECEIVER, OWNER, self.context,
                expected_peer_dns=self.expected_owner_dns,
                handshake_timeout=handshake_timeout, max_frame_size=1 << 20,
            )
        except MutualTLSTransportError:
            return False
        try:
            message = _wait_message(connection, RECEIVER, _MAX_SECONDS)
            if (message.recipient != RECEIVER or message.op != "ground.effect.request"
                    or len(message.body) != 1):
                raise EffectReceiverServiceError("wrong effect message channel")
            try:
                result = self._dispatch(message.body[0])
                response: dict[str, Any] = {"ok": True, "result": result}
            except (ValueError, TypeError, KeyError, RuntimeError, OSError) as exc:
                response = {"ok": False, "reason": str(exc)[:256]}
            connection.send(OWNER, Message(
                sender=RECEIVER, recipient=OWNER, op="ground.effect.response",
                seq=message.seq, body=(response,),
            ))
            return True
        except (EffectReceiverServiceError, SocketTransportError):
            return False
        finally:
            connection.close()


class AuthenticatedGroundEffectClient:
    """Caller pins receiver certificate DNS and uses one fresh mTLS stream per RPC."""

    def __init__(
        self, host: str, port: int, context: ssl.SSLContext, *,
        server_hostname: str, timeout: float = 3.0,
    ) -> None:
        """Require authenticated client context and bounded response deadline."""
        if (type(host) is not str or not host or type(port) is not int
                or not 1 <= port <= 65535
                or not isinstance(context, ssl.SSLContext)
                or context.verify_mode != ssl.CERT_REQUIRED
                or not context.check_hostname
                or type(server_hostname) is not str or not server_hostname
                or not isinstance(timeout, (int, float)) or timeout <= 0):
            raise EffectReceiverServiceError("invalid pinned effect receiver endpoint")
        self.host, self.port, self.context = host, port, context
        self.server_hostname, self.timeout = server_hostname, float(timeout)

    def request(self, kind: str, data: dict[str, Any]) -> dict[str, Any]:
        """Do one authenticated bounded request with no plaintext fallback."""
        try:
            channel = connect_mutual_tls(
                self.host, self.port, OWNER, RECEIVER, self.context,
                server_hostname=self.server_hostname,
                timeout=self.timeout, handshake_timeout=self.timeout,
            )
        except MutualTLSTransportError as exc:
            raise EffectReceiverServiceError("receiver mutual TLS identity refused") from exc
        try:
            channel.send(RECEIVER, Message(
                sender=OWNER, recipient=RECEIVER, op="ground.effect.request",
                seq=1, body=({"kind":kind, "data":data},),
            ))
            response = _wait_message(channel, OWNER, self.timeout)
            if (response.op != "ground.effect.response" or response.seq != 1
                    or len(response.body) != 1
                    or not isinstance(response.body[0], Mapping)
                    or set(response.body[0]) not in ({"ok","result"}, {"ok","reason"})):
                raise EffectReceiverServiceError("effect response is not a bound typed result")
            payload = response.body[0]
            if payload["ok"] is not True:
                raise EffectFencingRefused(str(payload["reason"]))
            if not isinstance(payload["result"], Mapping):
                raise EffectReceiverServiceError("effect response payload invalid")
            return dict(payload["result"])
        finally:
            channel.close()

    def prepare(self, source_root: str, target_host: str) -> dict[str, Any]:
        """Request a durable freeze of old resource writes before quorum assignment."""
        return self.request("prepare", {"source_root":source_root, "target_host":target_host})

    def activate(self, expected_root: str) -> dict[str, Any]:
        """Install an exact next quorum root, requiring a matching prior freeze."""
        return self.request("activate", {"expected_root":expected_root})

    def apply(self, claim: PublishedGroundEffect) -> dict[str, Any]:
        """Attempt one resource-side atomic write with an inert stage claim."""
        if not isinstance(claim, PublishedGroundEffect):
            raise EffectReceiverServiceError("typed published Ground claim required")
        return self.request("apply", {"claim":claim.to_dict()})

    def snapshot(self) -> dict[str, Any]:
        """Observe receiver-owned persistent authority and effect state over mTLS."""
        return self.request("snapshot", {})
