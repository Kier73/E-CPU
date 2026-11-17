"""LENS-002: authenticated-endpoint bridge for an admitted lens64 Ground.

The endpoint is supplied and identity-pinned by a caller (mTLS in the native
integration test). This module neither grants receiver authority nor executes
remote source. The receiver independently rechecks the portable Structural
Memory proposal and runs its local Virtual Layer Hypervisor operator.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping

from .lens_ground import MODULUS, backward_frames
from .runtime_qualification import (
    REQUEST_KIND, QualificationEndpoint, QualificationRefused,
    _check_response, affine_expected, canonical, digest,
)
from .structural_memory import (
    StructuralMemoryProposal, StructuralMemoryVerifier, StructuralNavigator,
    StructuralMemoryError, StructuralMemoryRefused,
)

KIND = "mailcpu.lens-native-fabric.v1"
MAX_FRAME = 8192
MAX_COORDINATE = 10**18
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")


class LensNativeRefused(ValueError):
    """An observation, host identity, proof, permit or frame was rejected."""


def _proposal(proposal: StructuralMemoryProposal) -> StructuralMemoryProposal:
    """Mathematics: reserialize, reconstruct and replay every finite witness."""
    if not isinstance(proposal, StructuralMemoryProposal):
        raise LensNativeRefused("a typed Structural Memory proposal is required")
    try:
        original = StructuralMemoryProposal.from_dict(proposal.to_dict())
        if original.spec.family != "lens64":
            raise LensNativeRefused("native fabric requires a lens64 Ground")
        StructuralMemoryVerifier().verify_proposal(original)
    except (StructuralMemoryError, StructuralMemoryRefused, ValueError, TypeError) as exc:
        raise LensNativeRefused("lens proposal failed independent witness verification") from exc
    return original


def independent_lens_value(proposal: StructuralMemoryProposal, coordinate: int) -> int:
    """Mathematics: recompute P^-1(F(t)) using a distinct affine composition oracle."""
    item = _proposal(proposal)
    if type(coordinate) is not int or not 0 <= coordinate <= MAX_COORDINATE:
        raise LensNativeRefused("native lens coordinate exceeds budget")
    try:
        value, _ = StructuralNavigator().read(
            item.spec, item.certificate, coordinate, context=item.spec.context,
        )
        p = item.spec.parameters
        independent = backward_frames(
            affine_expected(p["a"], p["c"], MODULUS, p["x0"], coordinate),
            p["frames"],
        )
    except (StructuralMemoryError, StructuralMemoryRefused, ValueError, TypeError) as exc:
        raise LensNativeRefused("native lens coordinate or Ground cannot be evaluated") from exc
    if independent != value:
        raise LensNativeRefused("independent affine oracle disagrees with Structural Memory")
    return value


@dataclass(frozen=True)
class LensNativeReceipt:
    """A content-bound request/reply pair; authentication depends on its transport."""

    proposal_id: str
    request: dict[str, Any]
    reply: dict[str, Any]

    @property
    def fingerprint(self) -> str:
        """Mathematics: hash the exact semantic identity and canonical wire transcript."""
        return digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize the full request/reply witness without omitting fields."""
        return {
            "schema": KIND, "proposal_id": self.proposal_id,
            "request": self.request, "reply": self.reply,
        }


def verify_lens_native_receipt(
    receipt: LensNativeReceipt, proposal: StructuralMemoryProposal,
) -> int:
    """Mathematics: recheck exact framing, nonces, Ground identity and two value oracles."""
    item = _proposal(proposal)
    if not isinstance(receipt, LensNativeReceipt) or receipt.proposal_id != item.proposal_id:
        raise LensNativeRefused("native receipt proposal identity mismatch")
    request, reply = receipt.request, receipt.reply
    if (not isinstance(request, dict) or set(request) != {"kind", "host", "nonce", "operation", "payload"}
            or request["kind"] != REQUEST_KIND or request["operation"] != "lens64.navigate"
            or not isinstance(request["payload"], dict)
            or set(request["payload"]) != {"proposal", "coordinate"}
            or request["payload"]["proposal"] != item.to_dict()
            or not isinstance(reply, dict)):
        raise LensNativeRefused("native lens request transcript is malformed")
    coordinate = request["payload"]["coordinate"]
    value = independent_lens_value(item, coordinate)
    try:
        _check_response(request, reply)
    except (QualificationRefused, KeyError, ValueError, TypeError) as exc:
        raise LensNativeRefused("native reply identity or framing invalid") from exc
    expected = {"value", "spec_digest", "certificate_digest", "hypervisor_receipt_digest"}
    result = reply.get("result")
    if (reply.get("ok") is not True or not isinstance(result, dict)
            or set(result) != expected or type(result["value"]) is not int
            or result["value"] != value
            or result["spec_digest"] != item.spec.digest
            or result["certificate_digest"] != item.certificate.digest
            or type(result["hypervisor_receipt_digest"]) is not str
            or _HEX.fullmatch(result["hypervisor_receipt_digest"]) is None):
        raise LensNativeRefused("remote Hypervisor result does not reproduce the pinned Ground")
    return value


class LensNativeDispatcher:
    """Request a typed Ground read through one locally permitted, pinned endpoint."""

    def __init__(
        self, endpoint: QualificationEndpoint, *,
        approved_specs: frozenset[str], max_frame: int = MAX_FRAME,
    ) -> None:
        """Mathematics: restrict candidate semantic identities to a finite local allow-set."""
        if (not hasattr(endpoint, "host_id")
                or type(endpoint.host_id) is not str or _ID.fullmatch(endpoint.host_id) is None
                or not isinstance(approved_specs, frozenset) or not approved_specs
                or len(approved_specs) > 32 or any(type(d) is not str or _HEX.fullmatch(d) is None
                                                  for d in approved_specs)
                or type(max_frame) is not int or not 1024 <= max_frame <= MAX_FRAME):
            raise LensNativeRefused("unbound or excessively permissive lens endpoint")
        self.endpoint = endpoint
        self.approved_specs = approved_specs
        self.max_frame = max_frame

    def navigate(
        self, proposal: StructuralMemoryProposal, coordinate: int, *,
        request_id: str,
    ) -> LensNativeReceipt:
        """Mathematics: validate intent, exchange one frame, independently recheck result."""
        item = _proposal(proposal)
        if item.spec.digest not in self.approved_specs:
            raise LensNativeRefused("local policy does not permit this exact lens Ground")
        if type(request_id) is not str or _ID.fullmatch(request_id) is None:
            raise LensNativeRefused("native request identity is invalid")
        expected = independent_lens_value(item, coordinate)
        request = {
            "kind": REQUEST_KIND, "host": self.endpoint.host_id,
            "nonce": digest({
                "kind": KIND, "request": request_id,
                "host": self.endpoint.host_id,
                "proposal_id": item.proposal_id, "coordinate": coordinate,
            })[:32],
            "operation": "lens64.navigate",
            "payload": {"proposal": item.to_dict(), "coordinate": coordinate},
        }
        if len(canonical(request)) + 1 > self.max_frame:
            raise LensNativeRefused("serialized Ground exceeds bound of native wire frame")
        try:
            response = self.endpoint.exchange(request, max_bytes=self.max_frame)
        except (QualificationRefused, OSError, TimeoutError, ValueError) as exc:
            raise LensNativeRefused("authenticated lens endpoint refused this request") from exc
        if not isinstance(response, Mapping):
            raise LensNativeRefused("endpoint returned a non-object reply")
        record = LensNativeReceipt(item.proposal_id, request, dict(response))
        if verify_lens_native_receipt(record, item) != expected:
            raise LensNativeRefused("native lens realization disagrees with local observation")
        return record
