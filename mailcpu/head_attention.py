"""Incremental pending-intention index over verified native session heads."""
from dataclasses import dataclass
import re

from .attention import Budget, Offer, machine_scope, plan_attention, verify_plan
from .computational_session import (
    ComputationalSessionConflictError, ComputationalSessionHead, ComputationalSessionStore,
)

_NAMESPACE = re.compile(r"[0-9a-f]{64}\Z")
_SESSION = re.compile(r"fab127\.([0-9a-f]{64})\.([0-9a-f]{6})\Z")


@dataclass(frozen=True)
class PendingHead:
    """An externally supplied pending intention bound to one observed checkpoint."""
    head: ComputationalSessionHead
    offer: Offer


class HeadAttentionIndex:
    """Retain ready intent offers only; use native FAB-014 for fair selection.

    One controller owns this volatile index. Refresh on observations/work
    arrival/completion, not by polling every address. Readiness is supplied
    by the caller, not inferred from checkpoint metadata. Neither an index
    nor a grant proves page availability or grants execution authority.
    """

    def __init__(self, namespace):
        """Bind the controller to one exact logical 127/8 namespace."""
        if type(namespace) is not str or not _NAMESPACE.fullmatch(namespace):
            raise ValueError("invalid fabric namespace")
        self.namespace = namespace
        self.epoch = 0
        self._seen = {}
        self._pending = {}

    def _identity(self, store):
        """Bind one native store to the canonical fabric namespace and machine ID."""
        if not isinstance(store, ComputationalSessionStore):
            raise TypeError("store must be a ComputationalSessionStore")
        match = _SESSION.fullmatch(store.session_id)
        if match is None or match[1] != self.namespace:
            raise ValueError("session belongs to another fabric")
        return int(match[2],16)

    def refresh(self, store, demand=None):
        """Observe an exact current head; publish or withdraw a pending intention."""
        identity = self._identity(store)
        if demand is not None and (not isinstance(demand,Budget) or not any(demand.values())):
            raise ValueError("invalid pending demand")
        head = store.observe_head()
        coordinate = (head.revision,head.checkpoint_digest,head.lineage_manifest.digest)
        prior = self._seen.get(identity)
        if prior is not None and (coordinate[0] < prior[0] or
                                  (coordinate[0] == prior[0] and coordinate != prior)):
            raise ComputationalSessionConflictError("regressing or conflicting observed head")
        entry = None if demand is None else PendingHead(
            head, Offer(machine_scope(identity),head.revision,head.checkpoint_digest,demand))
        previous = self._pending.get(identity)
        if coordinate != prior or (previous.offer if previous else None) != (entry.offer if entry else None):
            self.epoch += 1
        self._seen[identity] = coordinate
        if entry is None:
            self._pending.pop(identity,None)
        else:
            self._pending[identity] = entry
        return head

    def offers(self):
        """Expose only explicitly pending work; absent addresses are not scanned."""
        return tuple(entry.offer for entry in self._pending.values())

    def plan(self, capacity, *, limits=None, service=None):
        """Reuse the native hierarchical allocator over the current pending set."""
        return plan_attention(self.offers(),capacity,epoch=self.epoch,limits=limits,service=service)

    def verify(self, plan, capacity, *, limits=None, service=None):
        """Recompute selection against the current local epoch and pending set."""
        return verify_plan(plan,self.offers(),capacity,epoch=self.epoch,limits=limits,service=service)

    def load_grant(self, store, grant):
        """Revalidate one selected head before materializing its complete state.

        The caller must verify its plan against current inputs separately.
        Native M3 still governs successor admission and compare-and-swap.
        """
        identity = self._identity(store)
        entry = self._pending.get(identity)
        if entry is None or entry.offer != grant:
            raise ComputationalSessionConflictError("grant is no longer pending at this coordinate")
        return store.load_observed(entry.head)

    def withdraw(self, grant):
        """Retire exactly one completed/cancelled pending offer without a fleet scan."""
        if not isinstance(grant,Offer):
            raise TypeError("grant must be an Offer")
        identity = int("".join(grant.scope[:6]),16)
        entry = self._pending.get(identity)
        if entry is None or entry.offer != grant:
            raise ComputationalSessionConflictError("cannot withdraw a different pending offer")
        del self._pending[identity]
        self.epoch += 1
