"""Crash-safe quorum-gated observation coordination."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .observation import (
    ObservationAuthorityPolicy,
    ObservationConsensus,
    ObservationDecision,
    ObservationError,
    SubstrateObservation,
    decode_substrate_observation,
)
from .reliability import ReliableChannel
from .transport import Transport
from .vm import MailCPUVirtualMachine


class GatedObservationError(ObservationError):
    """A gated observation admission, checkpoint, or crash-order invariant failed."""


def _validate_event(kind: Any, logical_time: Any) -> tuple[str, int]:
    """Mathematics: require event identity `e=(kind,t)` with `kind∈K` and `t∈Z_{≥0}`."""

    if not isinstance(kind, str) or not kind:
        raise GatedObservationError("gated event kind must be a non-empty string")
    if not isinstance(logical_time, int) or isinstance(logical_time, bool) or logical_time < 0:
        raise GatedObservationError("gated event logical_time must be a non-negative integer")
    return kind, logical_time


def _validate_sequence(sequence: Any) -> int:
    """Mathematics: require transport sequence `s∈Z_{>0}`."""

    if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence <= 0:
        raise GatedObservationError("gated evidence sequence must be positive")
    return sequence


def _canonical_state(state: Mapping[str, Any]) -> bytes:
    """Mathematics: encode state as canonical bytes `c=JSON(sort_keys,compact)(state)` for stable hashing."""

    return json.dumps(state, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _atomic_write(path: str | Path, document: Mapping[str, Any]) -> str:
    """Mathematics: publish `C=(format,digest,S)` by fsync and same-directory atomic replacement."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    state = dict(document)
    digest = hashlib.sha256(_canonical_state(state)).hexdigest()
    envelope = {"format": "mailcpu-gated-checkpoint-v1", "digest": digest, "state": state}
    temporary_path: Path | None = None
    try:
        descriptor, raw_temporary_path = tempfile.mkstemp(
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=str(destination.parent),
            text=True,
        )
        temporary_path = Path(raw_temporary_path)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(envelope, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, destination)
        temporary_path = None
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass
    return digest


@dataclass(frozen=True)
class EvidenceLink:
    """Immutable link between canonical evidence and one reliable frame."""

    source: str
    channel: str
    sequence: int
    payload: tuple[Any, ...]

    def __post_init__(self) -> None:
        """Mathematics: enforce link identity `L=(source,channel,s,payload)` with `s>0` and typed payload."""

        if not isinstance(self.source, str) or not self.source:
            raise GatedObservationError("evidence source must be non-empty")
        if not isinstance(self.channel, str) or not self.channel:
            raise GatedObservationError("evidence channel must be non-empty")
        _validate_sequence(self.sequence)
        if not isinstance(self.payload, tuple):
            raise GatedObservationError("evidence payload must be a tuple")
        observation = decode_substrate_observation(self.payload)
        if observation.source != self.source:
            raise GatedObservationError("evidence payload source does not match link")

    @property
    def event(self) -> tuple[str, int]:
        """Mathematics: derive event identity `e=(kind(O),logical_time(O))` from validated payload `O`."""

        observation = decode_substrate_observation(self.payload)
        return observation.kind, observation.logical_time

    def to_snapshot(self) -> dict[str, Any]:
        """Mathematics: serialize `L` while preserving tuple payload identity for checkpoint restore."""

        return {
            "source": self.source,
            "channel": self.channel,
            "sequence": self.sequence,
            "payload": list(self.payload),
        }

    @classmethod
    def from_snapshot(cls, payload: Mapping[str, Any]) -> "EvidenceLink":
        """Mathematics: reconstruct `L` only when source, channel, sequence, and tagged payload agree."""

        if not isinstance(payload, Mapping):
            raise GatedObservationError("evidence link snapshot must be a mapping")
        raw_payload = payload.get("payload")
        if not isinstance(raw_payload, (list, tuple)):
            raise GatedObservationError("evidence link payload must be a sequence")
        return cls(
            source=str(payload.get("source")),
            channel=str(payload.get("channel")),
            sequence=_validate_sequence(payload.get("sequence")),
            payload=tuple(raw_payload),
        )


@dataclass
class GatedObservationCoordinator:
    """Coordinates typed evidence, explicit quorum finalization, and crash-safe VM application."""

    vm: MailCPUVirtualMachine
    policy: ObservationAuthorityPolicy
    channels: dict[str, ReliableChannel]
    target_pid: int
    register_prefix: str
    consensus: ObservationConsensus = field(init=False)
    _links: dict[tuple[str, int], dict[str, EvidenceLink]] = field(init=False, default_factory=dict)
    _consumed: dict[tuple[str, int], set[str]] = field(init=False, default_factory=dict)
    _consume_intents: dict[tuple[str, int], dict[str, EvidenceLink]] = field(init=False, default_factory=dict)
    _apply_intents: dict[tuple[str, int], EvidenceLink] = field(init=False, default_factory=dict)
    _applied: dict[tuple[str, int], EvidenceLink] = field(init=False, default_factory=dict)
    _representatives: dict[tuple[str, int], EvidenceLink] = field(init=False, default_factory=dict)

    def __post_init__(self) -> None:
        """Mathematics: bind `A` policy sources to receiver channels and target VM `p` without changing any substrate state."""

        if not isinstance(self.vm, MailCPUVirtualMachine):
            raise GatedObservationError("gated coordinator requires MailCPUVirtualMachine")
        if not isinstance(self.policy, ObservationAuthorityPolicy):
            raise GatedObservationError("gated coordinator requires ObservationAuthorityPolicy")
        if not isinstance(self.target_pid, int) or isinstance(self.target_pid, bool) or self.target_pid <= 0:
            raise GatedObservationError("gated target pid must be positive")
        if self.target_pid not in self.vm.scheduler.tasks:
            raise GatedObservationError("gated target pid is not a VM task")
        if not isinstance(self.register_prefix, str) or not self.register_prefix or any(
            character.isspace() or character == "\x00" for character in self.register_prefix
        ):
            raise GatedObservationError("gated register prefix must be non-empty and whitespace-free")
        if set(self.channels) != set(self.policy.allowed_sources):
            raise GatedObservationError("gated channels must exactly match policy sources")
        for source, channel in self.channels.items():
            if not isinstance(channel, ReliableChannel):
                raise GatedObservationError("gated channel map contains a non-reliable channel")
            if channel.peer != source:
                raise GatedObservationError("gated channel peer does not match policy source")
        self.consensus = ObservationConsensus(self.policy)

    def ingest_available(self) -> tuple[EvidenceLink, ...]:
        """Mathematics: perform `peek→decode→policy ingest`, draining only already-consumed retransmissions while preserving new event frames."""

        admitted: list[EvidenceLink] = []
        for source in sorted(self.channels):
            channel = self.channels[source]
            while True:
                peeked = channel.peek()
                if peeked is None:
                    break
                sequence, payload = peeked
                observation = decode_substrate_observation(payload)
                if observation.source != source:
                    raise GatedObservationError("gated payload source does not match channel policy source")
                if observation.kind != self.policy.kind:
                    raise GatedObservationError("gated payload kind does not match authority policy")
                event = observation.kind, observation.logical_time
                existing = self._links.setdefault(event, {}).get(source)
                candidate = EvidenceLink(source, channel.channel, sequence, payload)
                if existing is None:
                    self.consensus.ingest(observation)
                    self._links[event][source] = candidate
                    admitted.append(candidate)
                    break
                if existing != candidate:
                    raise GatedObservationError("source has multiple transport links for one logical event")
                if source not in self._consumed.get(event, set()):
                    break
                duplicate = channel.receive()
                if duplicate is not None and duplicate != (sequence, payload):
                    raise GatedObservationError("retransmitted frame changed during duplicate cleanup")
        return tuple(admitted)

    def status(self, kind: str, logical_time: int) -> ObservationDecision:
        """Mathematics: expose consensus decision `δ(e)` without modifying evidence, VM, or channels."""

        return self.consensus.status(kind, logical_time)

    def finalize_event(self, kind: str, logical_time: int) -> ObservationDecision:
        """Mathematics: explicitly close event `e`, selecting the deterministic winning representative only on quorum."""

        event = _validate_event(kind, logical_time)
        decision = self.consensus.finalize(*event)
        if decision.status == "AUTHORIZED":
            authorized = self.consensus.authorized_observation(*event)
            if authorized is None:
                raise GatedObservationError("authorized consensus lacks representative observation")
            link = self._links.get(event, {}).get(authorized.source)
            if link is None:
                raise GatedObservationError("authorized observation lacks transport evidence link")
            self._representatives[event] = link
        return decision

    def _link_for(self, event: tuple[str, int], source: str) -> EvidenceLink:
        """Mathematics: resolve unique evidence link `L(e,source)` from the admitted event relation."""

        try:
            return self._links[event][source]
        except KeyError as exc:
            raise GatedObservationError("event lacks requested source evidence link") from exc

    def _consume_source(self, event: tuple[str, int], source: str, checkpoint_path: str | Path) -> None:
        """Mathematics: persist intent, consume/ACK `F_s`, then persist `consumed[source]=1`, recovering absent frames as completed intents."""

        if source in self._consumed.setdefault(event, set()):
            return
        link = self._link_for(event, source)
        pending_intent = self._consume_intents.setdefault(event, {}).get(source)
        recovering_intent = pending_intent is not None
        if pending_intent is not None and pending_intent != link:
            raise GatedObservationError("consume intent conflicts with evidence link")
        self._consume_intents[event][source] = link
        self.save_checkpoint(checkpoint_path)
        channel = self.channels[source]
        peeked = channel.peek()
        if peeked is not None:
            if peeked != (link.sequence, link.payload):
                raise GatedObservationError("reliable frame differs from evidence link during consume")
            channel.receive()
        elif not recovering_intent:
            raise GatedObservationError("evidence frame disappeared before a persisted consume intent")
        self._consumed[event].add(source)
        del self._consume_intents[event][source]
        self.save_checkpoint(checkpoint_path)

    def _apply_representative(self, event: tuple[str, int], checkpoint_path: str | Path) -> None:
        """Mathematics: persist apply intent, apply `π(O*)` idempotently, then persist durable receipt marker before consumption."""

        link = self._representatives.get(event)
        if link is None:
            raise GatedObservationError("authorized event lacks representative link")
        if event in self._applied:
            return
        pending_intent = self._apply_intents.get(event)
        if pending_intent is not None and pending_intent != link:
            raise GatedObservationError("apply intent conflicts with representative link")
        self._apply_intents[event] = link
        self.save_checkpoint(checkpoint_path)
        observation = decode_substrate_observation(link.payload)
        applied = self.vm.apply_substrate_observation(
            self.target_pid,
            observation,
            link.sequence,
            self.register_prefix,
        )
        if not isinstance(applied, bool):
            raise GatedObservationError("VM substrate application did not return idempotence result")
        self._applied[event] = link
        del self._apply_intents[event]
        self.save_checkpoint(checkpoint_path)

    def commit_event(self, kind: str, logical_time: int, checkpoint_path: str | Path) -> ObservationDecision:
        """Mathematics: execute ordered commit `save→nonrep consume→apply→save→rep consume→save` for authorized event `e`."""

        event = _validate_event(kind, logical_time)
        decision = self.consensus.status(*event)
        if decision.status != "AUTHORIZED":
            raise GatedObservationError("only AUTHORIZED events may commit")
        representative = self._representatives.get(event)
        if representative is None:
            raise GatedObservationError("authorized event has no representative link")
        self.save_checkpoint(checkpoint_path)
        for source in sorted(self._links.get(event, {})):
            if source != representative.source:
                self._consume_source(event, source, checkpoint_path)
        self._apply_representative(event, checkpoint_path)
        self._consume_source(event, representative.source, checkpoint_path)
        return self.consensus.status(*event)

    def process_acks(self, sender_channels: Mapping[str, ReliableChannel]) -> dict[str, tuple[int, ...]]:
        r"""Mathematics: apply sender transition `P_s := P_s \ ACKS_s` for explicitly supplied sender channels."""

        acknowledged: dict[str, tuple[int, ...]] = {}
        for source, channel in sorted(sender_channels.items()):
            if source not in self.policy.allowed_sources:
                raise GatedObservationError("sender ACK channel source is not authorized")
            acknowledged[source] = channel.process_ack()
        return acknowledged

    def snapshot(self) -> dict[str, Any]:
        """Mathematics: serialize policy, channels, evidence links, decisions, intents, and receipt markers as one state product."""

        return {
            "version": 1,
            "target_pid": self.target_pid,
            "register_prefix": self.register_prefix,
            "policy_consensus": self.consensus.snapshot(),
            "channels": {source: channel.snapshot() for source, channel in sorted(self.channels.items())},
            "links": [
                {"kind": kind, "logical_time": logical_time, "sources": [link.to_snapshot() for _, link in sorted(links.items())]}
                for (kind, logical_time), links in sorted(self._links.items())
            ],
            "consumed": [
                {"kind": kind, "logical_time": logical_time, "sources": sorted(sources)}
                for (kind, logical_time), sources in sorted(self._consumed.items())
            ],
            "consume_intents": [
                {
                    "kind": kind,
                    "logical_time": logical_time,
                    "links": [link.to_snapshot() for _, link in sorted(links.items())],
                }
                for (kind, logical_time), links in sorted(self._consume_intents.items())
            ],
            "apply_intents": [
                {"kind": kind, "logical_time": logical_time, "link": link.to_snapshot()}
                for (kind, logical_time), link in sorted(self._apply_intents.items())
            ],
            "applied": [
                {"kind": kind, "logical_time": logical_time, "link": link.to_snapshot()}
                for (kind, logical_time), link in sorted(self._applied.items())
            ],
            "representatives": [
                {"kind": kind, "logical_time": logical_time, "link": link.to_snapshot()}
                for (kind, logical_time), link in sorted(self._representatives.items())
            ],
        }

    def save_checkpoint(self, path: str | Path) -> str:
        """Mathematics: atomically publish combined state `C=(VM.snapshot,coordinator.snapshot)` with SHA-256 identity."""

        return _atomic_write(path, {"vm": self.vm.snapshot(), "coordinator": self.snapshot()})

    @classmethod
    def from_snapshot(
        cls,
        payload: Mapping[str, Any],
        vm: MailCPUVirtualMachine,
        transports: Mapping[str, Transport],
    ) -> "GatedObservationCoordinator":
        """Mathematics: reconstruct gated state only when policy, channel routes, links, intents, and receipts are mutually consistent."""

        if not isinstance(payload, Mapping) or int(payload.get("version", 1)) != 1:
            raise GatedObservationError("unsupported gated coordinator snapshot version")
        raw_consensus = payload.get("policy_consensus")
        if not isinstance(raw_consensus, Mapping):
            raise GatedObservationError("gated snapshot lacks consensus state")
        consensus = ObservationConsensus.from_snapshot(raw_consensus)
        raw_channels = payload.get("channels")
        if not isinstance(raw_channels, Mapping):
            raise GatedObservationError("gated snapshot channels must be a mapping")
        channels: dict[str, ReliableChannel] = {}
        for source, raw_channel in raw_channels.items():
            source_name = str(source)
            if source_name not in transports:
                raise GatedObservationError("gated snapshot lacks transport for source")
            channels[source_name] = ReliableChannel.from_snapshot(dict(raw_channel), transports[source_name])
        coordinator = cls(
            vm,
            consensus.policy,
            channels,
            int(payload["target_pid"]),
            str(payload.get("register_prefix", "substrate")),
        )
        coordinator.consensus = consensus
        raw_links = payload.get("links", ())
        if not isinstance(raw_links, (list, tuple)):
            raise GatedObservationError("gated snapshot links must be a sequence")
        for raw_event in raw_links:
            if not isinstance(raw_event, Mapping):
                raise GatedObservationError("gated snapshot link event must be a mapping")
            event = _validate_event(raw_event.get("kind"), int(raw_event.get("logical_time")))
            if event[0] != coordinator.policy.kind:
                raise GatedObservationError("gated link kind does not match policy")
            raw_link_items = raw_event.get("sources", ())
            if not isinstance(raw_link_items, (list, tuple)):
                raise GatedObservationError("gated event links must be a sequence")
            links: dict[str, EvidenceLink] = {}
            for raw_link in raw_link_items:
                link = EvidenceLink.from_snapshot(raw_link)
                if link.event != event or link.source in links:
                    raise GatedObservationError("gated link event or source identity mismatch")
                if link.source not in coordinator.channels or link.channel != coordinator.channels[link.source].channel:
                    raise GatedObservationError("gated link channel does not match restored channel")
                links[link.source] = link
            coordinator._links[event] = links
        raw_consumed = payload.get("consumed", ())
        if not isinstance(raw_consumed, (list, tuple)):
            raise GatedObservationError("gated consumed state must be a sequence")
        for raw_item in raw_consumed:
            event = _validate_event(raw_item.get("kind"), int(raw_item.get("logical_time")))
            sources = tuple(raw_item.get("sources", ()))
            if len(set(sources)) != len(sources) or any(source not in coordinator._links.get(event, {}) for source in sources):
                raise GatedObservationError("gated consumed source does not have evidence link")
            coordinator._consumed[event] = set(sources)

        def load_link_map(raw_items: Any, label: str) -> dict[tuple[str, int], dict[str, EvidenceLink]]:
            """Mathematics: decode event-indexed link map `M[e][s]=L` with unique keys and matching evidence."""

            if not isinstance(raw_items, (list, tuple)):
                raise GatedObservationError(f"gated {label} state must be a sequence")
            result: dict[tuple[str, int], dict[str, EvidenceLink]] = {}
            for raw_item in raw_items:
                event = _validate_event(raw_item.get("kind"), int(raw_item.get("logical_time")))
                if event in result:
                    raise GatedObservationError(f"duplicate gated {label} event")
                raw_link_values = raw_item.get("links")
                if not isinstance(raw_link_values, (list, tuple)):
                    raise GatedObservationError(f"gated {label} links must be a sequence")
                decoded: dict[str, EvidenceLink] = {}
                for raw_link in raw_link_values:
                    link = EvidenceLink.from_snapshot(raw_link)
                    if link.event != event or link.source in decoded or link != coordinator._links.get(event, {}).get(link.source):
                        raise GatedObservationError(f"gated {label} link mismatch")
                    decoded[link.source] = link
                result[event] = decoded
            return result

        coordinator._consume_intents = load_link_map(payload.get("consume_intents", ()), "consume intent")

        def load_single_links(raw_items: Any, label: str) -> dict[tuple[str, int], EvidenceLink]:
            """Mathematics: decode event-indexed singleton link map `M[e]=L` with unique event keys."""

            if not isinstance(raw_items, (list, tuple)):
                raise GatedObservationError(f"gated {label} state must be a sequence")
            result: dict[tuple[str, int], EvidenceLink] = {}
            for raw_item in raw_items:
                event = _validate_event(raw_item.get("kind"), int(raw_item.get("logical_time")))
                if event in result:
                    raise GatedObservationError(f"duplicate gated {label} event")
                link = EvidenceLink.from_snapshot(raw_item.get("link", {}))
                if link.event != event or link != coordinator._links.get(event, {}).get(link.source):
                    raise GatedObservationError(f"gated {label} link mismatch")
                result[event] = link
            return result

        coordinator._apply_intents = load_single_links(payload.get("apply_intents", ()), "apply intent")
        coordinator._applied = load_single_links(payload.get("applied", ()), "applied")
        coordinator._representatives = load_single_links(payload.get("representatives", ()), "representative")
        for event, links in coordinator._consume_intents.items():
            if set(links) & coordinator._consumed.get(event, set()):
                raise GatedObservationError("consume intent cannot name an already consumed source")
        for event, link in coordinator._apply_intents.items():
            if coordinator._representatives.get(event) != link:
                raise GatedObservationError("apply intent does not match representative")
        for event, link in coordinator._applied.items():
            if coordinator._representatives.get(event) != link:
                raise GatedObservationError("applied receipt does not match representative")
        evidence_events = set(coordinator.consensus._evidence)
        link_events = set(coordinator._links)
        if evidence_events != link_events:
            raise GatedObservationError("consensus evidence and transport links describe different events")
        for event, evidence in coordinator.consensus._evidence.items():
            links = coordinator._links[event]
            if set(evidence) != set(links):
                raise GatedObservationError("consensus evidence and transport links describe different sources")
            for source, payload_value in evidence.items():
                if links[source].payload != payload_value:
                    raise GatedObservationError("consensus evidence payload differs from transport link")
        for event, link in coordinator._representatives.items():
            decision = coordinator.consensus.status(*event)
            if decision.status != "AUTHORIZED":
                raise GatedObservationError("representative exists without authorized consensus")
        for event, status in coordinator.consensus._finalized.items():
            if status == "AUTHORIZED" and event not in coordinator._representatives:
                raise GatedObservationError("authorized consensus lacks representative link")

        def validate_live_frame(event: tuple[str, int], source: str, link: EvidenceLink) -> None:
            """Mathematics: require `F_s=L(e,s)` unless a persisted consume intent proves an in-flight receive."""

            if source in coordinator._consumed.get(event, set()):
                return
            peeked = coordinator.channels[source].peek()
            if peeked is None:
                if source not in coordinator._consume_intents.get(event, {}):
                    raise GatedObservationError("unconsumed evidence frame is absent without recovery intent")
                return
            if peeked != (link.sequence, link.payload):
                raise GatedObservationError("live reliable frame differs from restored evidence link")

        for event, links in coordinator._links.items():
            for source, link in links.items():
                validate_live_frame(event, source, link)
        return coordinator


def load_gated_checkpoint(
    path: str | Path,
    transports: Mapping[str, Transport],
) -> GatedObservationCoordinator:
    """Mathematics: verify `SHA256(state)=digest`, restore VM and coordinator, and return one continuation product."""

    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GatedObservationError(str(exc)) from exc
    if not isinstance(document, dict) or document.get("format") != "mailcpu-gated-checkpoint-v1":
        raise GatedObservationError("unsupported gated checkpoint format")
    state = document.get("state")
    if not isinstance(state, dict):
        raise GatedObservationError("gated checkpoint state must be an object")
    expected = hashlib.sha256(_canonical_state(state)).hexdigest()
    if document.get("digest") != expected:
        raise GatedObservationError("gated checkpoint digest mismatch")
    try:
        vm_payload = state.get("vm")
        coordinator_payload = state.get("coordinator")
        if not isinstance(vm_payload, dict) or not isinstance(coordinator_payload, dict):
            raise GatedObservationError("gated checkpoint lacks VM or coordinator state")
        vm = MailCPUVirtualMachine.from_snapshot(vm_payload)
        return GatedObservationCoordinator.from_snapshot(coordinator_payload, vm, transports)
    except GatedObservationError:
        raise
    except (KeyError, TypeError, ValueError, OSError) as exc:
        raise GatedObservationError(str(exc)) from exc
