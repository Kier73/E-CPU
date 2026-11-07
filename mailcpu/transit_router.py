"""Exact operation/resource router for heterogeneous transit execution backends."""

from __future__ import annotations

from typing import Any, Callable, Mapping

from .classifier import HypervisorArbitrationEvent
from .transit_compute import TransitComputeHost


class TransitBackendRouterError(ValueError):
    """Mathematics: refuse an operation unless its exact (operation,resource) key has one unambiguous registered handler."""


class TransitBackendRouter(TransitComputeHost):
    """Route one authorized CPU-domain request to a typed operation backend."""

    def __init__(self, compute_host: TransitComputeHost | None = None) -> None:
        """Mathematics: initialize backend relation R={(op,resource)↦handler} with the bounded scalar MailCPU host."""

        selected = compute_host or TransitComputeHost()
        if not isinstance(selected, TransitComputeHost):
            raise TypeError("backend router compute_host must be a TransitComputeHost")
        super().__init__(
            max_source_bytes=selected.max_source_bytes,
            max_instructions=selected.max_instructions,
            max_ticks=selected.max_ticks,
            max_registers=selected.max_registers,
        )
        self._handlers: dict[tuple[str, str], Callable[[HypervisorArbitrationEvent], Any]] = {}
        self._implementation_fingerprints: dict[tuple[str, str], str | None] = {}
        self.register_backend(selected)

    def register(
        self,
        operation: str,
        resource: str,
        handler: Callable[[HypervisorArbitrationEvent], Any],
        *,
        implementation_fingerprint: str | None = None,
    ) -> None:
        """Mathematics: extend partial function R only when key k=(operation,resource) is nonempty, callable, and not already defined."""

        if not isinstance(operation, str) or not operation:
            raise TransitBackendRouterError("backend operation name must be non-empty")
        if not isinstance(resource, str) or not resource:
            raise TransitBackendRouterError("backend resource name must be non-empty")
        if not callable(handler):
            raise TransitBackendRouterError("backend handler must be callable")
        if implementation_fingerprint is not None and (
            not isinstance(implementation_fingerprint, str)
            or len(implementation_fingerprint) != 64
            or any(character not in "0123456789abcdef" for character in implementation_fingerprint)
        ):
            raise TransitBackendRouterError(
                "backend implementation fingerprint must be a lowercase SHA-256 digest"
            )
        key = (operation, resource)
        if key in self._handlers:
            raise TransitBackendRouterError(f"backend already registered for {key!r}")
        self._handlers[key] = handler
        self._implementation_fingerprints[key] = implementation_fingerprint

    def register_backend(self, backend: Any) -> None:
        """Mathematics: project backend b to key (b.operation_name,b.resource_name) and handler b.handle."""

        operation = getattr(backend, "operation_name", None)
        resource = getattr(backend, "resource_name", None)
        handler = getattr(backend, "handle", None)
        implementation_fingerprint = getattr(backend, "implementation_fingerprint", None)
        if callable(implementation_fingerprint):
            implementation_fingerprint = implementation_fingerprint()
        self.register(
            operation,
            resource,
            handler,
            implementation_fingerprint=implementation_fingerprint,
        )

    def handle(self, event: HypervisorArbitrationEvent) -> Any:
        """Mathematics: evaluate H(event)=R[(event.request.operation,event.request.resource)](event), refusing unknown query algebras."""

        if not isinstance(event, HypervisorArbitrationEvent):
            raise TransitBackendRouterError("backend router requires a typed arbitration event")
        key = (event.request.operation, event.request.resource)
        handler = self._handlers.get(key)
        if handler is None:
            raise TransitBackendRouterError(f"no backend registered for {key!r}")
        return handler(event)

    def registered_backends(self) -> tuple[tuple[str, str], ...]:
        """Mathematics: expose the finite domain dom(R) in deterministic key order without exposing handler internals."""

        return tuple(sorted(self._handlers))

    def registered_backend_implementations(
        self,
    ) -> tuple[tuple[str, str, str | None], ...]:
        """Mathematics: Expose each dispatch key with its optional concrete source fingerprint."""

        return tuple(
            (operation, resource, self._implementation_fingerprints[(operation, resource)])
            for operation, resource in sorted(self._handlers)
        )
