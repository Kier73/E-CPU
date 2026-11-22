"""Navigation of one M3 session across observer-host and process changes."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from mailcpu.computational_objects import ComputationalObjectStore
from mailcpu.computational_session import ComputationalSessionStore
from mailcpu.continuous_session import (
    REJOIN_INPUT,
    REJOIN_OPERATION,
    REJOIN_OUTPUT,
    SessionRejoinAddress,
    SessionRejoinNavigator,
    SessionRejoinRefused,
)
from mailcpu.recovery_lineage import RecoveryLineageAuthority, RecoveryLineageCoordinator
from mailcpu.seed_commit_quorum import SeedCommitMembership
from mailcpu.substrate_bootstrap import (
    ChannelObservation,
    OperationOffer,
    ResourceObservation,
    SubstrateObservation,
)


def _sha(raw: bytes) -> str:
    """Produce one exact content digest for test evidence and session identity."""
    return hashlib.sha256(raw).hexdigest()


class PageBacking:
    """Immutable page service that survives replacement of the original store object."""

    page_size = 32

    def __init__(self) -> None:
        self.pages: dict[str, bytes] = {}

    def put_page(self, data: bytes) -> str:
        """Retain exactly one fixed-size content-addressed page."""
        if len(data) != self.page_size:
            raise ValueError("page geometry mismatch")
        key = _sha(data)
        self.pages.setdefault(key, data)
        return key

    def get_page(self, digest: str) -> bytes:
        """Resolve immutable bytes with M1's expected page interface."""
        return self.pages[digest]


def _store(tmp_path: Path, backing: PageBacking, *, session_id: str = "enduring-session") -> ComputationalSessionStore:
    """Reopen the same real authority journals and M3 storage after a simulated restart."""
    membership = SeedCommitMembership(
        session_id, 1, ("A", "B", "C"), "A", 1,
        _sha(b"session-genesis"),
    )
    authorities = {
        member: RecoveryLineageAuthority(
            membership, member, tmp_path / "authorities" / f"{session_id}-{member}.jsonl"
        )
        for member in membership.member_ids
    }
    return ComputationalSessionStore(
        tmp_path / "state",
        ComputationalObjectStore(backing, chunk_size=32),
        RecoveryLineageCoordinator(membership, authorities),
        artifact_manifest_digest=_sha(b"artifact"),
        backend_fingerprint=_sha(b"backend"),
        state_schema_id="generic.state.v1",
    )


def _resource(
    resource_id: str,
    *,
    offer: bool = False,
    expires_at: int = 50,
    operation: str = REJOIN_OPERATION,
) -> ResourceObservation:
    """Declare an observer, with execution claims kept distinct from observation."""
    return ResourceObservation(
        resource_id=resource_id,
        substrate_hint="owned-observer",
        observed_at=1,
        expires_at=expires_at,
        observer_id=f"observer.{resource_id}",
        evidence_digest=_sha(resource_id.encode()),
        offers=(
            OperationOffer(operation, REJOIN_INPUT, REJOIN_OUTPUT, 3),
        ) if offer else (),
    )


def _channel(
    channel_id: str,
    source: str,
    target: str,
    *,
    carries: tuple[str, ...] = (REJOIN_INPUT,),
    expires_at: int = 50,
    max_payload_bytes: int = 4096,
    cost: int = 1,
) -> ChannelObservation:
    """Represent only a directed observed communication edge, not a processor."""
    return ChannelObservation(
        channel_id=channel_id,
        source=source,
        target=target,
        carries=carries,
        estimated_quanta=cost,
        observed_at=1,
        expires_at=expires_at,
        evidence_digest=_sha(channel_id.encode()),
        max_payload_bytes=max_payload_bytes,
    )


def _inventory(*, endpoint: str = "edge", edge_expires_at: int = 50) -> SubstrateObservation:
    """Form a browser -> Wi-Fi -> relay -> admitted session store path."""
    return SubstrateObservation(
        resources=(
            _resource("browser"),
            _resource("wifi"),
            _resource("relay"),
            _resource(endpoint, offer=True, expires_at=edge_expires_at),
        ),
        channels=(
            _channel("radio", "browser", "wifi"),
            _channel("fiber", "wifi", "relay"),
            _channel("tls", "relay", endpoint),
        ),
    )


def _navigator(
    inventory: SubstrateObservation,
    store: ComputationalSessionStore,
    *,
    admit_host=None,
    admit_channel=None,
    endpoint: str = "edge",
) -> SessionRejoinNavigator:
    """Bind trusted local policy and storage without granting rights from advertisements."""
    return SessionRejoinNavigator(
        inventory,
        {endpoint: store},
        admit_host=admit_host if admit_host is not None else lambda resource: resource.resource_id == endpoint,
        admit_channel=admit_channel if admit_channel is not None else lambda edge: edge.channel_id in {"radio", "fiber", "tls"},
    )


def test_bootstrap_terminate_reopen_and_rejoin_latest_quorum_state(tmp_path: Path) -> None:
    """The durable address survives original process objects and recovers the newest revision."""
    backing = PageBacking()
    store = _store(tmp_path, backing)
    initial = store.create_session(b"revision-one")
    address = SessionRejoinAddress.bootstrap(store)
    address_path = tmp_path / "rejoin.json"
    address.save(address_path)

    successor = store.commit_state(
        b"revision-two",
        expected_revision=initial.revision,
        expected_checkpoint_digest=initial.checkpoint_digest,
        transition_id="step-001",
        operation_id="runtime.step",
        input_digest=_sha(b"step-001-input"),
        logical_time=2,
    )
    assert successor.revision == 2
    del store

    restored_store = _store(tmp_path, backing)
    restored_address = SessionRejoinAddress.load(address_path)
    navigator = _navigator(_inventory(), restored_store)
    route = navigator.plan(restored_address, origin_id="browser", coordinate=3)
    assert route.channel_ids == ("radio", "fiber", "tls")
    attached = navigator.attach(restored_address, route, coordinate=3)
    assert attached.snapshot.revision == 2
    assert attached.snapshot.state_bytes == b"revision-two"
    assert attached.snapshot.checkpoint_digest == successor.checkpoint_digest
    assert attached.evidence()["lineage_digest"] == successor.lineage_manifest.digest
    assert restored_address.fingerprint == address.fingerprint


def test_non_host_carrier_and_observer_are_not_promoted_to_session_authority(tmp_path: Path) -> None:
    """A passive radio path and an observer without an admitted operation cannot host M3."""
    store = _store(tmp_path, PageBacking())
    store.create_session(b"state")
    address = SessionRejoinAddress.bootstrap(store)
    inventory = _inventory()
    with pytest.raises(SessionRejoinRefused, match="no receiver-authorized"):
        _navigator(inventory, store, admit_host=lambda resource: False).plan(
            address, origin_id="browser", coordinate=3
        )
    with pytest.raises(SessionRejoinRefused, match="no admitted communication path"):
        _navigator(inventory, store, admit_channel=lambda edge: False).plan(
            address, origin_id="browser", coordinate=3
        )


def test_lease_expiry_bad_representation_and_small_channel_refuse(tmp_path: Path) -> None:
    """Observed reachability, representation and payload bounds must all remain valid."""
    store = _store(tmp_path, PageBacking())
    store.create_session(b"state")
    address = SessionRejoinAddress.bootstrap(store)
    with pytest.raises(SessionRejoinRefused, match="no receiver-authorized"):
        _navigator(_inventory(edge_expires_at=2), store).plan(
            address, origin_id="browser", coordinate=3
        )

    inventory = _inventory()
    bad = SubstrateObservation(
        inventory.resources,
        (
            _channel("radio", "browser", "wifi", carries=("wrong.type",)),
            *inventory.channels[1:],
        ),
    )
    with pytest.raises(SessionRejoinRefused, match="no admitted communication path"):
        _navigator(bad, store).plan(address, origin_id="browser", coordinate=3)

    small = SubstrateObservation(
        inventory.resources,
        (
            _channel("radio", "browser", "wifi", max_payload_bytes=1),
            *inventory.channels[1:],
        ),
    )
    with pytest.raises(SessionRejoinRefused, match="no admitted communication path"):
        _navigator(small, store).plan(address, origin_id="browser", coordinate=3)


def test_rejoin_revalidates_route_and_refuses_stale_routing_evidence(tmp_path: Path) -> None:
    """A previously selected path cannot be silently replayed after its lease expires."""
    store = _store(tmp_path, PageBacking())
    store.create_session(b"state")
    address = SessionRejoinAddress.bootstrap(store)
    navigator = _navigator(_inventory(), store)
    route = navigator.plan(address, origin_id="browser", coordinate=3)
    with pytest.raises(SessionRejoinRefused, match="origin observation has expired"):
        navigator.attach(address, route, coordinate=51)
    with pytest.raises(SessionRejoinRefused, match="route changed"):
        navigator.attach(address, route, coordinate=4)


def test_rejoin_address_integrity_and_cross_session_scope(tmp_path: Path) -> None:
    """A corrupted locator or another session's membership cannot select this M3 lineage."""
    store = _store(tmp_path, PageBacking())
    store.create_session(b"state")
    address = SessionRejoinAddress.bootstrap(store)
    payload = address.to_dict()
    payload["session_id"] = "different-session"
    with pytest.raises(SessionRejoinRefused, match="digest mismatch"):
        SessionRejoinAddress.from_dict(payload)
    forged = SessionRejoinAddress(
        "different-session", address.artifact_manifest_digest,
        address.state_schema_id, address.membership_digest,
    )
    with pytest.raises(SessionRejoinRefused, match="no receiver-authorized"):
        _navigator(_inventory(), store).plan(forged, origin_id="browser", coordinate=3)


def test_only_literal_true_from_local_admission_is_accepted(tmp_path: Path) -> None:
    """Truthiness, route hashes and supplied operation offers never grant authority."""
    store = _store(tmp_path, PageBacking())
    store.create_session(b"state")
    address = SessionRejoinAddress.bootstrap(store)
    with pytest.raises(SessionRejoinRefused, match="no receiver-authorized"):
        _navigator(_inventory(), store, admit_host=lambda resource: 1).plan(
            address, origin_id="browser", coordinate=3
        )
    with pytest.raises(SessionRejoinRefused, match="no admitted communication path"):
        _navigator(_inventory(), store, admit_channel=lambda edge: "allowed").plan(
            address, origin_id="browser", coordinate=3
        )


def test_route_selects_cheapest_admitted_host_with_stable_tie_break(tmp_path: Path) -> None:
    """Selection is deterministic and observes host operations as well as channel costs."""
    store = _store(tmp_path, PageBacking())
    store.create_session(b"state")
    address = SessionRejoinAddress.bootstrap(store)
    inventory = SubstrateObservation(
        resources=(_resource("browser"), _resource("edge", offer=True)),
        channels=(
            _channel("zeta", "browser", "edge", cost=1),
            _channel("alpha", "browser", "edge", cost=1),
        ),
    )
    navigator = SessionRejoinNavigator(
        inventory, {"edge": store},
        admit_host=lambda resource: True,
        admit_channel=lambda channel: True,
    )
    route = navigator.plan(address, origin_id="browser", coordinate=3)
    assert route.channel_ids == ("alpha",)
    assert route.total_quanta == 4


def test_rejoin_remains_stable_across_repeated_host_process_replacements(tmp_path: Path) -> None:
    """Each fresh owner process resolves a new committed high-water under the same address."""
    backing = PageBacking()
    address_path = tmp_path / "persistent-address.json"
    seen_revisions: list[int] = []
    expected_address_digest: str | None = None

    for revision in range(1, 13):
        # Recreate M3 authority objects and journal readers every time. No
        # previous ComputationalSessionStore or navigator instance is reused.
        store = _store(tmp_path, backing)
        if revision == 1:
            state = store.create_session(b"revision-1")
            address = SessionRejoinAddress.bootstrap(store)
            expected_address_digest = address.fingerprint
            address.save(address_path)
        else:
            previous = store.load_latest()
            state = store.commit_state(
                f"revision-{revision}".encode(),
                expected_revision=previous.revision,
                expected_checkpoint_digest=previous.checkpoint_digest,
                transition_id=f"step-{revision:03d}",
                operation_id="runtime.step",
                input_digest=_sha(f"input-{revision}".encode()),
                logical_time=revision,
            )
            address = SessionRejoinAddress.load(address_path)
        navigator = _navigator(_inventory(), store)
        route = navigator.plan(address, origin_id="browser", coordinate=revision)
        attached = navigator.attach(address, route, coordinate=revision)
        assert attached.snapshot.state_bytes == f"revision-{revision}".encode()
        assert attached.snapshot.checkpoint_digest == state.checkpoint_digest
        assert address.fingerprint == expected_address_digest
        seen_revisions.append(attached.snapshot.revision)
        del navigator
        del store

    assert seen_revisions == list(range(1, 13))
