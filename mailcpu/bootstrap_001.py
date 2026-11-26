"""BOOT-001: native INTERNET-007 intention inside a native M3 session.

Only locally authorized callers supply stores and read-only observation
bindings. An address, manifest or result never grants a capability. This
module adds no scheduler, credential discovery, or independent authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

from . import internet_intention_ingress as ingress
from . import internet_free_fabric as source
from .computation_dag import NavigableComputationDAG
from .computational_session import ComputationalSessionStore, ComputationalSessionSnapshot
from .continuous_session import SessionRejoinAddress

STATE_SCHEMA = "mailcpu.boot001.internet007-m3.v1"
Get = Callable[[str, str | None, int], tuple[int, Mapping[str, str], bytes]]


class BootstrapRefused(ValueError):
    """The pinned intention, session, or proposed continuation does not match."""


def _scope(store: ComputationalSessionStore, manifest: dict) -> dict:
    admitted = ingress.admit_manifest(manifest)
    if (store.artifact_manifest_digest != ingress.digest(admitted)
            or store.state_schema_id != STATE_SCHEMA):
        raise BootstrapRefused("store does not bind the approved intention and schema")
    return admitted


def _state(manifest: dict, snapshot: ComputationalSessionSnapshot) -> dict:
    raw = snapshot.state_bytes
    if len(raw) > ingress.MAX_CHECKPOINT_BYTES:
        raise BootstrapRefused("checkpoint exceeds intention budget")
    state = ingress.validate_state(manifest, source.strict_json(raw))
    if raw != ingress.canonical(state) or snapshot.revision != state["revision"] + 1:
        raise BootstrapRefused("M3 and native intention revision or encoding differs")
    return state


def initialize(store: ComputationalSessionStore, manifest: dict) -> SessionRejoinAddress:
    """Explicit owner-approved genesis; never reset or import an existing Git lineage."""
    manifest = _scope(store, manifest)
    initial = store.create_session(
        ingress.canonical(ingress.genesis(manifest)),
        transition_id="boot001.genesis", operation_id="boot001.initialize",
        input_digest=ingress.digest(manifest),
    )
    _state(manifest, initial)
    return SessionRejoinAddress.bootstrap(store)


def recover(store: ComputationalSessionStore, manifest: dict,
            address: SessionRejoinAddress) -> ComputationalSessionSnapshot:
    """Rebind an authorized local store to the stable address and M3 high-water."""
    manifest = _scope(store, manifest)
    expected = SessionRejoinAddress(store.session_id, store.artifact_manifest_digest,
                                    store.state_schema_id, store.membership.digest)
    if address != expected:
        raise BootstrapRefused("address is outside the configured recovery scope")
    snapshot = store.load_latest()
    _state(manifest, snapshot)
    return snapshot


@dataclass(frozen=True)
class Quantum:
    address_digest: str
    operation: str | None
    before_checkpoint: str
    after_checkpoint: str
    intention_revision: int
    lineage_digest: str
    complete: bool


def step(store: ComputationalSessionStore, manifest: dict, address: SessionRejoinAddress,
         *, expected_checkpoint: str, get: Get) -> Quantum:
    """Advance one pure observation; native M3 CAS owns the accepted effect.

    A lost acknowledgment requires re-observing the current high-water, not
    replaying a stale request. Physical pure reads can repeat before commit.
    The caller's binding must enforce read-only I/O and local policy.
    """
    manifest = _scope(store, manifest)
    before = recover(store, manifest, address)
    if before.checkpoint_digest != expected_checkpoint:
        raise BootstrapRefused("stale continuation; rejoin the current checkpoint")
    state = _state(manifest, before)
    dag = (ingress.graph_template(manifest) if state["revision"] == 0
           else NavigableComputationDAG.from_snapshot(state["dag"]))
    if dag.is_complete:
        return Quantum(address.fingerprint, None, before.checkpoint_digest,
                       before.checkpoint_digest, state["revision"],
                       before.lineage_manifest.digest, True)

    operation = ingress.execute_one(manifest, dag, get)
    if operation is None:
        raise BootstrapRefused("nonterminal frontier did not advance")
    successor = ingress.advance(manifest, state, dag)
    after = store.commit_state(
        ingress.canonical(successor),
        expected_revision=before.revision,
        expected_checkpoint_digest=before.checkpoint_digest,
        transition_id="boot001." + operation, operation_id="boot001.observe",
        input_digest=ingress.digest({"manifest": ingress.digest(manifest),
                                    "before": state["digest"], "node": operation}),
        logical_time=successor["revision"],
    )
    verified = _state(manifest, after)
    if verified != successor:
        raise BootstrapRefused("committed successor differs from proposed observation")
    return Quantum(address.fingerprint, operation, before.checkpoint_digest,
                   after.checkpoint_digest, verified["revision"],
                   after.lineage_manifest.digest, dag.is_complete)
