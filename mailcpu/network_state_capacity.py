"""CAPACITY-002: recognize a finite in-transit network Ground before E-CPU hosting.

A ring has observer-local states H_i and one-tick in-transit slots Q_i. Sites
receive (H_i, Q_(i-1)) and emit (H_i', Q_i'). E-CPU is NOT installed in any
site: the only entry point is a receiver-owned local observation function.

Observe the four possible local inputs, not the exponential global state space;
construct the exact, synchronous global operator from checked wiring. Use the
existing E-CPU functional-graph law to navigate without replaying the network.
An optional existing E-CPU finite-transition ReLU compiler can realize the
same global operator with an independently verified neural representation.

Mathematics: for n sites, F(H,Q) has components
  (H_i',Q_i') = f_i(H_i,Q_(i-1) mod n),  i=0,...,n-1.
Checking every input of every f_i and the fixed index mapping establishes the
finite *declared snapshot* F, not the behavior of an unobserved future host.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from itertools import product
import json
import re
from typing import Callable, Sequence

from .law_certifier import Law, brent_cycle

SCHEMA = "mailcpu.network-state-capacity.v1"
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}\Z")
_MAX_SITES = 4
_ROWS = ((0, 0), (0, 1), (1, 0), (1, 1))


class NetworkCapacityRefused(ValueError):
    """Evidence or a proposed finite network transition fails its contract."""


def _canon(obj: object) -> bytes:
    """Mathematics: serialize exact identities deterministically, without float NaNs."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _hash(obj: object) -> str:
    """Mathematics: content-address finite semantic and evidence descriptions."""
    return sha256(_canon(obj)).hexdigest()


def _label(v: object, what: str) -> str:
    """Mathematics: reject ambiguous or unbounded observer/path identifiers."""
    if type(v) is not str or not _NAME.fullmatch(v):
        raise NetworkCapacityRefused(f"invalid {what}")
    return v


def _int(v: object, what: str, low: int = 0, high: int = 10**36) -> int:
    """Mathematics: require strict bounded integral coordinates."""
    if type(v) is not int or not low <= v <= high:
        raise NetworkCapacityRefused(f"invalid {what}")
    return v


def _bits(v: Sequence[int], n: int) -> tuple[int, ...]:
    """Mathematics: validate one exact Boolean state vector of length 2*n."""
    if not isinstance(v, (tuple, list)) or len(v) != 2*n or any(type(x) is not int or x not in (0,1) for x in v):
        raise NetworkCapacityRefused("invalid network state")
    return tuple(v)


def encode_state(bits: Sequence[int]) -> int:
    """Mathematics: encode Boolean state as big-endian integer for existing fgraph Law."""
    out = 0
    for bit in bits:
        _int(bit, "bit", 0, 1)
        out = (out << 1) | bit
    return out


def decode_state(value: int, sites: int) -> tuple[int, ...]:
    """Mathematics: invert the exact fixed-width binary encoding."""
    _int(value, "encoded state", 0, (1 << (2 * sites)) - 1)
    return tuple((value >> k) & 1 for k in range(2*sites-1, -1, -1))


@dataclass(frozen=True)
class UnawareSite:
    """Receiver-observed locus; callback is trusted to be invoked, not to tell the truth."""

    role: int
    host_id: str
    path_snapshot: str
    observed_at: int
    expires_at: int
    transform: Callable[[int,int], tuple[int,int]]

    def __post_init__(self) -> None:
        """Mathematics: bind an explicit role and finite observation interval."""
        _int(self.role, "site role", 0, _MAX_SITES-1)
        _label(self.host_id, "host")
        _label(self.path_snapshot, "path snapshot")
        _int(self.observed_at, "observed_at")
        _int(self.expires_at, "expires_at")
        if self.expires_at < self.observed_at or not callable(self.transform):
            raise NetworkCapacityRefused("expired or unobservable site")


@dataclass(frozen=True)
class NetworkProbePolicy:
    """Explicit local probing authority and complete component truth-table budget."""
    authorized_ids: frozenset[str]
    observer_id: str
    coordinate: int
    max_probe_calls: int = 32

    def __post_init__(self) -> None:
        """Mathematics: reject missing authority, unsigned remote claims and insufficient budgets."""
        _label(self.observer_id, "observer")
        _int(self.coordinate, "observation coordinate")
        _int(self.max_probe_calls, "probe quota", 1, 256)
        if not isinstance(self.authorized_ids, frozenset):
            raise NetworkCapacityRefused("authorized IDs must be explicitly supplied")
        for id_ in self.authorized_ids:
            _label(id_, "permitted host")


@dataclass(frozen=True)
class NetworkGround:
    """Exact finite component maps; host/location identities remain outside Ground."""
    tables: tuple[tuple[tuple[int,int],...],...]

    def __post_init__(self) -> None:
        """Mathematics: each of n sites has four exact Boolean input-output rows."""
        n = len(self.tables)
        if not 2 <= n <= _MAX_SITES:
            raise NetworkCapacityRefused("network site count outside declared model")
        for table in self.tables:
            if not isinstance(table, tuple) or len(table) != 4:
                raise NetworkCapacityRefused("component truth table is incomplete")
            for out in table:
                if not isinstance(out, tuple) or len(out) != 2 or any(type(x) is not int or x not in (0,1) for x in out):
                    raise NetworkCapacityRefused("invalid local transition output")

    @property
    def sites(self) -> int:
        """Mathematics: local site count determines number of host and transit registers."""
        return len(self.tables)

    @property
    def digest(self) -> str:
        """Mathematics: distinguish mathematical Ground identity from placement evidence."""
        return _hash({"schema":SCHEMA,"wiring":"directed-one-tick-ring-v1",
                      "tables":[[list(v) for v in t] for t in self.tables]})

    def step(self, state: Sequence[int]) -> tuple[int, ...]:
        """Mathematics: synchronous composition of all observed local transition relations."""
        n=self.sites
        x=_bits(state,n)
        hosts,queues=x[:n],x[n:]
        next_h=[0]*n
        next_q=[0]*n
        for i in range(n):
            a,b=self.tables[i][2*hosts[i] + queues[(i-1)%n]]
            next_h[i],next_q[i]=a,b
        return tuple(next_h+next_q)

    def tick(self, encoded: int) -> int:
        """Mathematics: compose one complete network tick in the compact integer encoding."""
        return encode_state(self.step(decode_state(encoded,self.sites)))

    def direct(self, initial: Sequence[int], steps: int) -> tuple[int,...]:
        """Mathematics: provide bounded step-by-step control, not large-time navigation."""
        _int(steps,"direct steps",0,4096)
        state=_bits(initial,self.sites)
        for _ in range(steps):
            state=self.step(state)
        return state


@dataclass(frozen=True)
class NetworkObservation:
    """Finite, content-pinned local observations of sites that predate E-CPU."""
    ground: NetworkGround
    site_evidence: tuple[tuple[int,str,str,str],...]
    coordinate: int
    observer_id: str
    probe_count: int

    def __post_init__(self) -> None:
        """Mathematics: bind every evidence row to a declared exact local table."""
        if not isinstance(self.ground, NetworkGround):
            raise NetworkCapacityRefused("observation lacks a valid finite Ground")
        _label(self.observer_id, "observer identity")
        _int(self.coordinate, "observation coordinate")
        if type(self.probe_count) is not int or self.probe_count != 8 * self.ground.sites:
            raise NetworkCapacityRefused("observation count does not cover local probes")
        if not isinstance(self.site_evidence, tuple) or len(self.site_evidence) != self.ground.sites:
            raise NetworkCapacityRefused("site evidence is incomplete")
        seen = set()
        for i, value in enumerate(self.site_evidence):
            if not isinstance(value, tuple) or len(value) != 4 or value[0] != i:
                raise NetworkCapacityRefused("site evidence order or role is invalid")
            _, name, snapshot, table_hash = value
            _label(name, "host identity")
            _label(snapshot, "path snapshot")
            if name in seen or table_hash != _hash([list(y) for y in self.ground.tables[i]]):
                raise NetworkCapacityRefused("site evidence does not match the Ground")
            seen.add(name)

    @property
    def path_digest(self) -> str:
        """Mathematics: provenance varies with observer, snapshot and host placement."""
        return _hash({"schema":SCHEMA,"ground":self.ground.digest,"sites":self.site_evidence,
                      "coordinate":self.coordinate,"observer":self.observer_id,"probes":self.probe_count})

    def navigate(self, initial: Sequence[int], coordinate: int) -> "NetworkNavigationReceipt":
        """Mathematics: discover a finite orbit then reuse existing Law(fgraph) to jump."""
        t=_int(coordinate,"navigation coordinate")
        source=_bits(initial,self.ground.sites)
        x=encode_state(source)
        # All local maps are exhaustively described; this traverses only one finite orbit.
        found=brent_cycle(self.ground.tick,x,limit=1<<(2*self.ground.sites+2))
        if found is None:
            raise NetworkCapacityRefused("finite orbit cannot be reconstructed")
        mu,lam=found
        steps=mu+lam
        if steps> (1<<(2*self.ground.sites)):
            raise NetworkCapacityRefused("invalid orbit horizon")
        orbit=[]
        cur=x
        for _ in range(steps):
            orbit.append(cur)
            cur=self.ground.tick(cur)
        if cur != orbit[mu]:
            raise NetworkCapacityRefused("orbit closure is inconsistent")
        law=Law(family="fgraph",params={"orbit":tuple(orbit),"mu":mu,"lam":lam},verdict="GROUND")
        result=decode_state(law.navigate(t),self.ground.sites)
        return NetworkNavigationReceipt(self.ground.digest,self.path_digest,source,t,result,
                                        mu,lam,_hash(orbit))

    def verify_navigation(self, receipt:"NetworkNavigationReceipt") -> bool:
        """Mathematics: independently rederive path-scoped finite orbit result."""
        if not isinstance(receipt,NetworkNavigationReceipt):
            return False
        if receipt.ground_digest!=self.ground.digest or receipt.path_digest!=self.path_digest:
            return False
        try:
            expected=self.navigate(receipt.initial,receipt.coordinate)
        except (NetworkCapacityRefused,ValueError,IndexError):
            return False
        return expected == receipt


@dataclass(frozen=True)
class NetworkNavigationReceipt:
    """Immutable scoped navigation answer; equality is not host attestation."""
    ground_digest: str
    path_digest: str
    initial: tuple[int,...]
    coordinate: int
    result: tuple[int,...]
    mu: int
    lam: int
    orbit_digest: str

    def to_dict(self) -> dict[str,object]:
        """Mathematics: export exact result and period evidence."""
        return {"schema":"mailcpu.network-navigation.v1","ground_digest":self.ground_digest,
                "path_digest":self.path_digest,"initial":list(self.initial),
                "coordinate":self.coordinate,"result":list(self.result),
                "mu":self.mu,"lam":self.lam,"orbit_digest":self.orbit_digest}


def recognize_network(sites: Sequence[UnawareSite], policy: NetworkProbePolicy) -> NetworkObservation:
    """Mathematics: exhaust each 2-bit local map (4n rows), not 2^(2n) global states.

    An extra identical re-probe of each row rejects observed nondeterminism.
    A certified *snapshot* of local operations is not proof of eternal stability.
    """
    if not isinstance(sites,(tuple,list)) or not 2 <= len(sites) <= _MAX_SITES:
        raise NetworkCapacityRefused("invalid network site count")
    if len(sites)*8 > policy.max_probe_calls:
        raise NetworkCapacityRefused("insufficient local probe budget")
    ordered=sorted(sites,key=lambda s:s.role)
    if tuple(s.role for s in ordered)!=tuple(range(len(ordered))):
        raise NetworkCapacityRefused("missing or duplicate site role")
    if len({s.host_id for s in ordered})!=len(ordered):
        raise NetworkCapacityRefused("duplicate host ID")
    if any(s.host_id not in policy.authorized_ids or not s.observed_at<=policy.coordinate<=s.expires_at for s in ordered):
        raise NetworkCapacityRefused("missing local probe authority or expired site")
    tables=[];evidence=[];count=0
    for s in ordered:
        table=[]
        for bits in _ROWS:
            try:
                v=s.transform(*bits)
            except Exception as exc:
                raise NetworkCapacityRefused("local transition observation failed") from exc
            if not isinstance(v,(tuple,list)) or len(v)!=2 or any(type(z) is not int or z not in (0,1) for z in v):
                raise NetworkCapacityRefused("invalid local observation")
            table.append(tuple(v));count+=1
        # Repeat observations within the same bounded source window.
        for j,bits in enumerate(_ROWS):
            try:
                v=s.transform(*bits)
            except Exception as exc:
                raise NetworkCapacityRefused("repeat local observation failed") from exc
            if not isinstance(v,(tuple,list)) or len(v)!=2 or any(type(z) is not int or z not in (0,1) for z in v) or tuple(v)!=table[j]:
                raise NetworkCapacityRefused("local transition was not reproducible")
            count+=1
        rows=tuple(table)
        tables.append(rows)
        evidence.append((s.role,s.host_id,s.path_snapshot,_hash([list(y) for y in rows])))
    return NetworkObservation(NetworkGround(tuple(tables)),tuple(evidence),policy.coordinate,policy.observer_id,count)


def recheck_network(observation: NetworkObservation, sites: Sequence[UnawareSite], policy: NetworkProbePolicy) -> bool:
    """Mathematics: refuse changed path snapshots, tables, observation policy or host identity."""
    other=recognize_network(sites,policy)
    return other.ground==observation.ground and other.path_digest==observation.path_digest


def build_neural_realization(observation:NetworkObservation):
    """Mathematics: compile exact local Boolean transition contracts into existing E-CPU ReLU.

    This is an optional *neural realization*, not a learned law, model-granted
    authority, or physical network execution. The original local Ground is
    the independent oracle; exhaustive global comparison is required for admission.
    """
    from .transition_space import (BooleanConstant,BooleanInput,BooleanNot,BooleanAnd,
                                   BooleanXor,BooleanSelect,FiniteTransitionProgram,
                                   compile_live_compositional_transition_program)
    n=observation.ground.sites
    names=tuple(f"h{i}" for i in range(n))+tuple(f"q{i}" for i in range(n))

    def expr(values, x, y):
        """Mathematics: express one observed 2-input Boolean table using a short exact AST."""
        if values==(0,0,0,0):return BooleanConstant(0)
        if values==(1,1,1,1):return BooleanConstant(1)
        if values==(0,0,1,1):return x
        if values==(0,1,0,1):return y
        if values==(1,1,0,0):return BooleanNot(x)
        if values==(1,0,1,0):return BooleanNot(y)
        if values==(0,1,1,0):return BooleanXor(x,y)
        if values==(1,0,0,1):return BooleanNot(BooleanXor(x,y))
        if values==(0,0,0,1):return BooleanAnd(x,y)
        if values==(1,1,1,0):return BooleanNot(BooleanAnd(x,y))
        # Shannon decomposition covers all remaining two-input functions.
        return BooleanSelect(x,
                             BooleanSelect(y,BooleanConstant(values[3]),BooleanConstant(values[2])),
                             BooleanSelect(y,BooleanConstant(values[1]),BooleanConstant(values[0])))

    h_out=[];q_out=[]
    for i,table in enumerate(observation.ground.tables):
        x=BooleanInput(f"h{i}")
        y=BooleanInput(f"q{(i-1)%n}")
        h_out.append(expr(tuple(v[0] for v in table),x,y))
        q_out.append(expr(tuple(v[1] for v in table),x,y))
    program=FiniteTransitionProgram("network-capacity-composed-v1",names,
        tuple(f"next_h{i}" for i in range(n))+tuple(f"next_q{i}" for i in range(n)),tuple(h_out+q_out))
    model=compile_live_compositional_transition_program(program)
    if model.program_digest != program.digest:
        raise NetworkCapacityRefused("neural model does not bind the exact derived program")
    global_states=1<<(2*n)
    for state_id in range(global_states):
        state=decode_state(state_id,n)
        expected=observation.ground.step(state)
        if tuple(program.evaluate(state))!=expected or tuple(model.predict(state))!=expected:
            raise NetworkCapacityRefused("neural realization is not exactly equivalent to recognized Ground")
    return {"program_digest":program.digest,"model_digest":model.digest,
            "ground_digest":observation.ground.digest,"global_rows_verified":global_states,
            "architecture":model.architecture,"parameter_count":model.parameter_count}