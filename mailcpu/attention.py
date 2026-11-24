"""Sparse, deterministic, advisory resource allocation for recursive E-CPU scopes."""
from dataclasses import dataclass, field
from hashlib import sha256
import heapq
import json
import re

Scope = tuple[str, ...]
_HEX = frozenset('0123456789abcdef')
_LABEL = re.compile(r'[A-Za-z0-9_-]{1,64}\Z')
_DIGEST = re.compile(r'[0-9a-f]{64}\Z')


def _scope(scope: Scope, leaf: bool = False) -> None:
    if type(scope) is not tuple or len(scope) > 38 or (leaf and len(scope) < 6):
        raise ValueError('invalid scope length or type')
    for i, label in enumerate(scope):
        if type(label) is not str or (i < 6 and (len(label) != 1 or label not in _HEX)) or (i >= 6 and not _LABEL.fullmatch(label)):
            raise ValueError('invalid scope label')


def machine_scope(identity: int, *path: str) -> Scope:
    """Name one of 2^24 identities and an optional recursive process path."""
    if type(identity) is not int or not 0 <= identity < 2**24:
        raise ValueError('invalid 24-bit machine identity')
    scope = tuple(f'{identity:06x}') + path
    _scope(scope, True)
    return scope


@dataclass(frozen=True)
class Budget:
    """Separate integer quanta, resident mappings, communication and observation units."""
    quanta: int = 0
    pages: int = 0
    messages: int = 0
    observations: int = 0

    def __post_init__(self):
        """Reject negative, noninteger or unbounded resource counts."""
        if any(type(x) is not int or not 0 <= x < 2**63 for x in self.values()):
            raise ValueError('invalid budget')

    def values(self):
        """Return the four dimensions in canonical order."""
        return (self.quanta, self.pages, self.messages, self.observations)

    def fits(self, capacity):
        """Componentwise resource admission predicate."""
        return all(a <= b for a, b in zip(self.values(), capacity.values()))

    def plus(self, other):
        """Add independent resource reservations."""
        return Budget(*(a+b for a,b in zip(self.values(), other.values())))

    def minus(self, other):
        """Subtract a grant, rejecting underflow."""
        return Budget(*(a-b for a,b in zip(self.values(), other.values())))

    def meet(self, other):
        """Intersect two independent capacity constraints."""
        return Budget(*(min(a,b) for a,b in zip(self.values(), other.values())))


@dataclass(frozen=True)
class Offer:
    """One observed work leaf; evidence is an identity, not a permission."""
    scope: Scope
    revision: int
    evidence: str
    demand: Budget
    ready: bool = True

    def __post_init__(self):
        """Require a bounded scope, revision, evidence and nonempty demand."""
        _scope(self.scope, True)
        if type(self.revision) is not int or self.revision < 1 or type(self.evidence) is not str or not _DIGEST.fullmatch(self.evidence):
            raise ValueError('invalid observation identity')
        if not isinstance(self.demand, Budget) or not any(self.demand.values()) or type(self.ready) is not bool:
            raise ValueError('invalid demand or readiness')


@dataclass(frozen=True)
class Plan:
    """Immutable advisory grants bound to exact planning inputs and epoch."""
    epoch: int
    input_digest: str
    grants: tuple[Offer, ...]
    spent: Budget
    active_nodes: int
    node_visits: int

    @property
    def authoritative(self):
        """Resource planning never authorizes execution or grants capabilities."""
        return False


@dataclass
class _Node:
    children: dict = field(default_factory=dict)
    queue: list = field(default_factory=list)
    offer: Offer | None = None
    used: Budget = field(default_factory=Budget)
    limit: Budget | None = None
    prefix: Scope = ()


def _inputs(offers, capacity, epoch, limits, service):
    if type(epoch) is not int or epoch < 0 or not isinstance(capacity, Budget):
        raise ValueError('invalid epoch or capacity')
    offers = tuple(offers)
    if any(not isinstance(o, Offer) for o in offers):
        raise ValueError('invalid offer')
    offers = tuple(sorted(offers, key=lambda o: o.scope))
    # Sorted adjacency detects both duplicate and ancestor/descendant leaves.
    for a,b in zip(offers, offers[1:]):
        if b.scope[:len(a.scope)] == a.scope:
            raise ValueError('offers must be distinct, prefix-free work leaves')
    limits, service = dict(limits or {}), dict(service or {})
    for key,value in limits.items():
        _scope(key)
        if not isinstance(value, Budget):
            raise ValueError('invalid subtree limit')
    for key,value in service.items():
        _scope(key)
        if type(value) is not int or value < 0:
            raise ValueError('invalid service history')
    payload = [epoch, capacity.values(), [[o.scope,o.revision,o.evidence,o.demand.values(),o.ready] for o in offers],
               [[k,v.values()] for k,v in sorted(limits.items())], sorted(service.items())]
    digest = sha256(json.dumps(payload, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    return offers,limits,service,digest


def plan_attention(offers, capacity: Budget, *, epoch: int, limits=None, service=None) -> Plan:
    """Select ready, whole demands by least-served subtree with stable ties.

    Build only active prefixes. Within a plan budgets decrease monotonically;
    an infeasible branch can be retired until the next observation epoch.
    Service history is supplied by the caller from actual completed grants.
    """
    offers,limits,service,digest = _inputs(offers, capacity, epoch, limits, service)
    root = _Node(limit=limits.get(()))
    nodes = 1
    for offer in offers:
        if not offer.ready:
            continue
        node = root
        for i,label in enumerate(offer.scope):
            if label not in node.children:
                prefix = offer.scope[:i+1]
                child = _Node(prefix=prefix, limit=limits.get(prefix))
                node.children[label] = child
                heapq.heappush(node.queue, (service.get(prefix,0), label))
                nodes += 1
            node = node.children[label]
        node.offer = offer
    visits = 0

    def choose(node, remaining):
        """Traverse one feasible least-served branch and debit its path."""
        nonlocal visits
        visits += 1
        if node.limit is not None:
            remaining = remaining.meet(node.limit.minus(node.used))
        if not any(remaining.values()):
            return None
        if node.offer is not None:
            offer = node.offer
            node.offer = None
            if offer.demand.fits(remaining):
                node.used = node.used.plus(offer.demand)
                return offer
        while node.queue:
            served,label = heapq.heappop(node.queue)
            child = node.children[label]
            offer = choose(child, remaining)
            if offer is not None:
                node.used = node.used.plus(offer.demand)
                if child.queue or child.offer is not None:
                    heapq.heappush(node.queue, (served+1,label))
                return offer
        return None

    grants = []
    while True:
        grant = choose(root, capacity.minus(root.used))
        if grant is None:
            break
        grants.append(grant)
    return Plan(epoch,digest,tuple(grants),root.used,nodes,visits)


def verify_plan(plan: Plan, offers, capacity: Budget, *, epoch: int, limits=None, service=None) -> bool:
    """Recompute exact selection under current inputs; reject stale or altered plans."""
    return isinstance(plan, Plan) and plan == plan_attention(offers,capacity,epoch=epoch,limits=limits,service=service)
