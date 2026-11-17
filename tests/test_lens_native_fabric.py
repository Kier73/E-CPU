"""LENS-002: receiver-owned native contract, portable witnesses and refusals."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from mailcpu.law_certifier import Law
from mailcpu.lens_ground import recover_lens_law, transform
from mailcpu.lens_native_fabric import (
    LensNativeDispatcher, LensNativeReceipt, LensNativeRefused,
    independent_lens_value, verify_lens_native_receipt,
)
from mailcpu.federated_native_worker import serve_native
from mailcpu.structural_memory import StructuralMemoryRegistry


ORIGIN = (1 << 40) + 23


def _samples(n: int = 512) -> list[int]:
    """Return the exact finite Gray orbit of a 64-bit affine counter."""
    return [transform((ORIGIN + i) % (1 << 64), "gray.encode") for i in range(n)]


def _proposal(indices=(0, 1, 2, 7, 17, 31, 58, 77)):
    """Create a compact proposal using the original certificate machinery."""
    trace = _samples()
    law = recover_lens_law(trace[:56], trace[56:96])
    assert law.family == "lens64"
    registry = StructuralMemoryRegistry(admission_policy=lambda item: True)
    return registry.propose(
        "native-lens-probe", law, {t: trace[t] for t in indices},
        context={"source": "native-lens-tests"},
    )


class _LocalBoundEndpoint:
    """SAB-005 worker equivalent without authentication; transport is tested separately."""

    host_id = "test-receiver"
    separate_process_per_exchange = False

    def __init__(self, tmp_path: Path, allowed_specs: frozenset[str], *, authorize: bool = True) -> None:
        self.tmp_path = tmp_path
        self.allowed_specs = allowed_specs
        self.authorize = authorize
        self.calls = 0

    def exchange(self, request, *, max_bytes):
        """Apply the receiver's actual local whitelist and Hypervisor adapter."""
        self.calls += 1
        return serve_native(
            dict(request), host_id=self.host_id, directory=self.tmp_path,
            allowed=frozenset({"lens64.navigate"}),
            approved_lens_grounds=self.allowed_specs,
            native_authority=self.authorize,
        )


def test_native_receiver_verifies_exact_ground_and_records_audit(tmp_path: Path) -> None:
    """One portable witness set is rechecked by a distinct receiver-local Hypervisor."""
    proposal = _proposal()
    endpoint = _LocalBoundEndpoint(tmp_path, frozenset({proposal.spec.digest}))
    dispatcher = LensNativeDispatcher(endpoint, approved_specs=frozenset({proposal.spec.digest}))
    coordinate = (1 << 50) + 91
    receipt = dispatcher.navigate(proposal, coordinate, request_id="proof-1")
    expected = independent_lens_value(proposal, coordinate)
    assert verify_lens_native_receipt(receipt, proposal) == expected
    assert receipt.reply["result"]["value"] == expected
    assert receipt.reply["result"]["spec_digest"] == proposal.spec.digest
    assert len(receipt.reply["result"]["hypervisor_receipt_digest"]) == 64
    assert endpoint.calls == 1
    assert list((tmp_path / "native-receipts").glob("*.json"))
    repeat = dispatcher.navigate(proposal, coordinate, request_id="proof-1")
    assert repeat.request == receipt.request
    assert repeat.reply["result"] == receipt.reply["result"]


def test_unpermitted_ground_never_reaches_endpoint(tmp_path: Path) -> None:
    """Caller policy refuses a different spec before any remote exchange."""
    proposal = _proposal()
    endpoint = _LocalBoundEndpoint(tmp_path, frozenset({proposal.spec.digest}))
    dispatcher = LensNativeDispatcher(endpoint, approved_specs=frozenset({"0" * 64}))
    with pytest.raises(LensNativeRefused, match="local policy"):
        dispatcher.navigate(proposal, 7, request_id="unpermitted")
    assert endpoint.calls == 0


def test_receiver_owned_ground_permission_cannot_be_self_advertised(tmp_path: Path) -> None:
    """A caller's local permit does not replace a receiver's exact allow-set."""
    proposal = _proposal()
    endpoint = _LocalBoundEndpoint(tmp_path, frozenset({"f" * 64}))
    dispatcher = LensNativeDispatcher(endpoint, approved_specs=frozenset({proposal.spec.digest}))
    with pytest.raises(LensNativeRefused, match="endpoint refused"):
        dispatcher.navigate(proposal, 81, request_id="receiver-deny")
    assert endpoint.calls == 1


def test_receiver_hypervisor_revocation_fails_closed(tmp_path: Path) -> None:
    """A pinned Ground cannot bypass a receiver lacking native execute rights."""
    proposal = _proposal()
    endpoint = _LocalBoundEndpoint(tmp_path, frozenset({proposal.spec.digest}), authorize=False)
    dispatcher = LensNativeDispatcher(endpoint, approved_specs=frozenset({proposal.spec.digest}))
    with pytest.raises(LensNativeRefused, match="endpoint refused"):
        dispatcher.navigate(proposal, 42, request_id="revoked")
    assert endpoint.calls == 1
    assert not list((tmp_path / "native-receipts").glob("*.json"))


def test_replayed_nonce_may_not_change_input(tmp_path: Path) -> None:
    """A recorded native nonce fences a later inconsistent request."""
    proposal = _proposal()
    endpoint = _LocalBoundEndpoint(tmp_path, frozenset({proposal.spec.digest}))
    dispatcher = LensNativeDispatcher(endpoint, approved_specs=frozenset({proposal.spec.digest}))
    receipt = dispatcher.navigate(proposal, 3, request_id="semantic-op")
    conflicting = deepcopy(receipt.request)
    conflicting["payload"]["coordinate"] = 4
    with pytest.raises(ValueError, match="conflicting native replay"):
        endpoint.exchange(conflicting, max_bytes=8192)


def test_tampered_native_receipt_is_not_accepted(tmp_path: Path) -> None:
    """A remote claimed value, certificate or Hypervisor hash cannot replace a check."""
    proposal = _proposal()
    endpoint = _LocalBoundEndpoint(tmp_path, frozenset({proposal.spec.digest}))
    receipt = LensNativeDispatcher(
        endpoint, approved_specs=frozenset({proposal.spec.digest}),
    ).navigate(proposal, 67, request_id="tamper-check")
    for broken in (
        {**receipt.reply["result"], "value": receipt.reply["result"]["value"] ^ 1},
        {**receipt.reply["result"], "certificate_digest": "0" * 64},
        {**receipt.reply["result"], "hypervisor_receipt_digest": "bad"},
    ):
        changed = LensNativeReceipt(
            receipt.proposal_id, receipt.request, {**receipt.reply, "result": broken},
        )
        with pytest.raises(LensNativeRefused):
            verify_lens_native_receipt(changed, proposal)


def test_prefix_horizon_checked_before_remote_operation(tmp_path: Path) -> None:
    """An escaped prefix coordinate is refused without contacting a receiver."""
    baseline = _proposal()
    samples = _samples()
    law = Law("lens64", params=baseline.spec.parameters, order=1,
              verdict="PREFIX-GROUND", first_bad=20)
    registry = StructuralMemoryRegistry(admission_policy=lambda item: True)
    witnesses = {t: samples[t] for t in (0, 1, 3, 9, 19)}
    witnesses[20] = samples[20] ^ 1
    proposal = registry.propose("prefix-native", law, witnesses)
    endpoint = _LocalBoundEndpoint(tmp_path, frozenset({proposal.spec.digest}))
    dispatcher = LensNativeDispatcher(endpoint, approved_specs=frozenset({proposal.spec.digest}))
    with pytest.raises(LensNativeRefused, match="coordinate or Ground"):
        dispatcher.navigate(proposal, 20, request_id="beyond")
    assert endpoint.calls == 0
    assert verify_lens_native_receipt(
        dispatcher.navigate(proposal, 19, request_id="within"), proposal,
    ) == samples[19]


def test_oversized_certificate_cannot_be_hidden_in_native_frame(tmp_path: Path) -> None:
    """A finite but oversized witness set is rejected before native transport."""
    proposal = _proposal(indices=tuple(range(400)))
    endpoint = _LocalBoundEndpoint(tmp_path, frozenset({proposal.spec.digest}))
    dispatcher = LensNativeDispatcher(endpoint, approved_specs=frozenset({proposal.spec.digest}))
    with pytest.raises(LensNativeRefused, match="wire frame"):
        dispatcher.navigate(proposal, 75, request_id="too-large")
    assert endpoint.calls == 0
