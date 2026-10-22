"""Hypervisor authority for admitting checkpointable system seed envelopes."""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
from typing import Any, Mapping

from .journal import EventJournal
from .seed import SeedEnvelopeError, SeedInputReceipt, SystemIdentity, SystemSeedEnvelope


class SeedAdmissionError(SeedEnvelopeError):
    """A seed admission checkpoint or result is malformed."""


def _digest(value: Any, label: str) -> str:
    """Mathematics: restrict `value` to the hexadecimal image `D={0,...,f}^{64}` of SHA-256."""

    if not isinstance(value, str) or len(value) != 64:
        raise SeedAdmissionError(f"{label} must be a 64-character SHA-256 digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise SeedAdmissionError(f"{label} must be hexadecimal") from exc
    return value


def _frontier_digest(envelope: SystemSeedEnvelope) -> str:
    """Mathematics: compute `d(F)=SHA256(JSON_sort(F))` for the finite input frontier `F`."""

    canonical = json.dumps(
        envelope.snapshot()["input_frontier"],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _frontier_projection(frontier: tuple[SeedInputReceipt, ...]) -> dict[str, SeedInputReceipt]:
    """Mathematics: project receipt set `F` to its per-source maximal frontier `π(F)[s]=argmax_q sequence(q)` ."""

    projection: dict[str, SeedInputReceipt] = {}
    for receipt in frontier:
        previous = projection.get(receipt.source)
        if previous is None or receipt.sequence > previous.sequence:
            projection[receipt.source] = receipt
    return projection


def _frontier_advances(
    previous: tuple[SeedInputReceipt, ...],
    candidate: tuple[SeedInputReceipt, ...],
) -> tuple[bool, str | None]:
    """Mathematics: require `∀s∈π(F₀), q₁(s)≥q₀(s)` and equal sequence implies equal digest."""

    old_projection = _frontier_projection(previous)
    new_projection = _frontier_projection(candidate)
    changed = False
    for source, old_receipt in old_projection.items():
        new_receipt = new_projection.get(source)
        if new_receipt is None:
            return False, f"frontier removed source {source!r}"
        if new_receipt.sequence < old_receipt.sequence:
            return False, f"frontier regressed source {source!r}"
        if new_receipt.sequence == old_receipt.sequence and new_receipt.digest != old_receipt.digest:
            return False, f"frontier changed digest at {source!r}:{old_receipt.sequence}"
        changed = changed or new_receipt.sequence > old_receipt.sequence
    changed = changed or set(new_projection) != set(old_projection)
    return changed, None


@dataclass(frozen=True)
class SeedAdmissionResult:
    """One journaled seed admission outcome `A=(I,f,dΣ,dF,r,accepted,replayed,reason)`."""

    identity: SystemIdentity
    fingerprint: str
    state_digest: str
    frontier_digest: str
    admission_receipt: str
    accepted: bool
    replayed: bool
    reason: str | None = None

    def __post_init__(self) -> None:
        """Mathematics: validate every result identity and digest before it enters the replay ledger."""

        if not isinstance(self.identity, SystemIdentity):
            raise SeedAdmissionError("seed admission result identity is invalid")
        _digest(self.fingerprint, "seed admission fingerprint")
        _digest(self.state_digest, "seed admission state digest")
        _digest(self.frontier_digest, "seed admission frontier digest")
        _digest(self.admission_receipt, "seed admission receipt")
        if not isinstance(self.accepted, bool) or not isinstance(self.replayed, bool):
            raise SeedAdmissionError("seed admission result flags are invalid")
        if self.reason is not None and (not isinstance(self.reason, str) or not self.reason):
            raise SeedAdmissionError("seed admission result reason is invalid")

    def to_dict(self) -> dict[str, object]:
        """Mathematics: project result `A` into a checkpointable JSON record without losing admission identity."""

        return {
            "identity": self.identity.snapshot(),
            "fingerprint": self.fingerprint,
            "state_digest": self.state_digest,
            "frontier_digest": self.frontier_digest,
            "admission_receipt": self.admission_receipt,
            "accepted": self.accepted,
            "replayed": False,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "SeedAdmissionResult":
        """Mathematics: reconstruct `A` from a complete typed checkpoint record and reset transient replay state."""

        if not isinstance(payload, Mapping) or not isinstance(payload.get("identity"), Mapping):
            raise SeedAdmissionError("seed admission result snapshot is incomplete")
        return cls(
            SystemIdentity.from_snapshot(payload["identity"]),
            payload.get("fingerprint"),
            payload.get("state_digest"),
            payload.get("frontier_digest"),
            payload.get("admission_receipt"),
            payload.get("accepted"),
            False,
            None if payload.get("reason") is None else str(payload.get("reason")),
        )


class HypervisorSeedAdmissionCoordinator:
    """Checkpointed Hypervisor authority for monotone, replayable system-seed admission."""

    def __init__(self, journal: EventJournal | None = None) -> None:
        """Mathematics: initialize registry `R=∅` and fingerprint ledger `L=∅` over one journal chain `H`."""

        self.journal = journal or EventJournal()
        if not isinstance(self.journal, EventJournal):
            raise SeedAdmissionError("seed admission requires an EventJournal")
        self._systems: dict[str, SystemSeedEnvelope] = {}
        self._seen: dict[str, SeedAdmissionResult] = {}

    @staticmethod
    def _fingerprint(envelope: SystemSeedEnvelope) -> str:
        """Mathematics: calculate candidate identity `f(E)=SHA256(bytes(E))` independently of journal position."""

        return hashlib.sha256(envelope.to_bytes()).hexdigest()

    @staticmethod
    def _result_projection(envelope: SystemSeedEnvelope, fingerprint: str) -> dict[str, object]:
        """Mathematics: project audit identity `P(E)=(I,f,dΣ,dF,k)` without copying mutable host state."""

        return {
            "system_id": envelope.identity.system_id,
            "incarnation": envelope.identity.incarnation,
            "fingerprint": fingerprint,
            "state_digest": envelope.state_digest,
            "frontier_digest": _frontier_digest(envelope),
            "coordinate": envelope.seed.coordinate,
        }

    def _finish(
        self,
        envelope: SystemSeedEnvelope,
        fingerprint: str,
        *,
        accepted: bool,
        reason: str | None,
    ) -> SeedAdmissionResult:
        """Mathematics: append one receipt `r=H_{n}` and bind it to exactly one candidate fingerprint."""

        kind = "hypervisor.seed.admit" if accepted else "hypervisor.seed.refuse"
        payload = self._result_projection(envelope, fingerprint)
        payload["accepted"] = accepted
        if reason is not None:
            payload["reason"] = reason
        receipt = self.journal.append(kind, payload).digest
        result = SeedAdmissionResult(
            envelope.identity,
            fingerprint,
            envelope.state_digest,
            str(payload["frontier_digest"]),
            receipt,
            accepted,
            False,
            reason,
        )
        self._seen[fingerprint] = result
        return result

    def _refuse(
        self,
        envelope: SystemSeedEnvelope,
        fingerprint: str,
        reason: str,
    ) -> SeedAdmissionResult:
        """Mathematics: record `¬admit(E)` while preserving registry `R` exactly."""

        return self._finish(envelope, fingerprint, accepted=False, reason=reason)

    def _validate_candidate(self, envelope: SystemSeedEnvelope) -> str | None:
        """Mathematics: require `decode(snapshot(E)).restore(I)` before registry mutation, returning only refusal text."""

        try:
            validated = type(envelope.seed).from_snapshot(envelope.seed.snapshot())
            validated.restore()
        except (SeedEnvelopeError, KeyError, TypeError, ValueError, OSError, OverflowError) as exc:
            return f"seed restore refused: {type(exc).__name__}: {exc}"
        return None

    def admit(self, envelope: SystemSeedEnvelope) -> SeedAdmissionResult:
        """Mathematics: apply monotone admission `R[s]:=E` only after shadow restore and replay by `f(E)`."""

        if not isinstance(envelope, SystemSeedEnvelope):
            raise SeedAdmissionError("seed admission requires a SystemSeedEnvelope")
        fingerprint = self._fingerprint(envelope)
        previous_result = self._seen.get(fingerprint)
        if previous_result is not None:
            self.journal.append(
                "hypervisor.seed.replay",
                {
                    "system_id": envelope.identity.system_id,
                    "incarnation": envelope.identity.incarnation,
                    "fingerprint": fingerprint,
                    "admission_receipt": previous_result.admission_receipt,
                    "accepted": previous_result.accepted,
                },
            )
            return replace(previous_result, replayed=True)

        current = self._systems.get(envelope.identity.system_id)
        if current is not None:
            current_identity = current.identity
            if envelope.identity.incarnation < current_identity.incarnation:
                return self._refuse(envelope, fingerprint, "stale system incarnation")
            if envelope.identity.incarnation == current_identity.incarnation:
                if envelope.seed.origin_digest != current.seed.origin_digest:
                    return self._refuse(envelope, fingerprint, "same-incarnation seed origin conflict")
                frontier_changed, frontier_error = _frontier_advances(current.input_frontier, envelope.input_frontier)
                if frontier_error is not None:
                    return self._refuse(envelope, fingerprint, frontier_error)
                if envelope.seed.coordinate < current.seed.coordinate:
                    return self._refuse(envelope, fingerprint, "same-incarnation seed coordinate regressed")
                if envelope.seed.coordinate == current.seed.coordinate and envelope.state_digest != current.state_digest:
                    return self._refuse(envelope, fingerprint, "same-coordinate state digest conflict")
                if frontier_changed and envelope.seed.coordinate <= current.seed.coordinate:
                    return self._refuse(envelope, fingerprint, "frontier advanced without virtual-time advance")

        restore_error = self._validate_candidate(envelope)
        if restore_error is not None:
            return self._refuse(envelope, fingerprint, restore_error)
        result = self._finish(envelope, fingerprint, accepted=True, reason=None)
        self._systems[envelope.identity.system_id] = envelope
        return result

    def current(self, system_id: str) -> SystemSeedEnvelope | None:
        """Mathematics: project registry `R[system_id]` without exposing a mutable envelope or registry map."""

        if not isinstance(system_id, str) or not system_id:
            raise SeedAdmissionError("system id must be a non-empty string")
        return self._systems.get(system_id)

    def systems(self) -> tuple[SystemSeedEnvelope, ...]:
        """Mathematics: expose ordered registry projection `sort(R.values())` as immutable envelope references."""

        return tuple(self._systems[key] for key in sorted(self._systems))

    def snapshot(self) -> dict[str, object]:
        """Mathematics: serialize registry `R` and replay ledger `L` as finite sorted checkpoint products."""

        return {
            "version": 1,
            "systems": [
                {
                    "system_id": system_id,
                    "envelope": envelope.snapshot(),
                }
                for system_id, envelope in sorted(self._systems.items())
            ],
            "seen": [
                {
                    "fingerprint": fingerprint,
                    "result": result.to_dict(),
                }
                for fingerprint, result in sorted(self._seen.items())
            ],
        }

    @classmethod
    def from_snapshot(
        cls,
        payload: Mapping[str, Any],
        journal: EventJournal,
    ) -> "HypervisorSeedAdmissionCoordinator":
        """Mathematics: reconstruct `R,L` only when all stored envelopes restore and every fingerprint/result identity agrees."""

        if not isinstance(payload, Mapping) or int(payload.get("version", 1)) != 1:
            raise SeedAdmissionError("unsupported seed admission snapshot")
        coordinator = cls(journal)
        for raw in payload.get("systems", ()):
            if not isinstance(raw, Mapping) or not isinstance(raw.get("envelope"), Mapping):
                raise SeedAdmissionError("seed admission system snapshot is incomplete")
            envelope = SystemSeedEnvelope.from_snapshot(raw["envelope"])
            system_id = str(raw.get("system_id", ""))
            if system_id != envelope.identity.system_id or system_id in coordinator._systems:
                raise SeedAdmissionError("seed admission system identity is inconsistent")
            restore_error = coordinator._validate_candidate(envelope)
            if restore_error is not None:
                raise SeedAdmissionError(restore_error)
            coordinator._systems[system_id] = envelope
        for raw in payload.get("seen", ()):
            if not isinstance(raw, Mapping) or not isinstance(raw.get("result"), Mapping):
                raise SeedAdmissionError("seed admission replay snapshot is incomplete")
            fingerprint = _digest(raw.get("fingerprint"), "seed admission replay fingerprint")
            if fingerprint in coordinator._seen:
                raise SeedAdmissionError("duplicate seed admission replay fingerprint")
            result = SeedAdmissionResult.from_dict(raw["result"])
            if result.fingerprint != fingerprint:
                raise SeedAdmissionError("seed admission replay fingerprint mismatch")
            coordinator._seen[fingerprint] = result
        return coordinator
