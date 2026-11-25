"""MGA-001/F: workload-discovered affine action vocabulary."""
from __future__ import annotations
from collections import Counter
from dataclasses import dataclass
from itertools import combinations

from .affine_verification_ground import AffineVerificationGround, cold_multiplications, _coordinate
from .substrate_bootstrap import BootstrapRefused, digest

SCHEMA="mailcpu.mga001.affine-vocabulary.v1"


def _atoms(t):
    t=_coordinate(t)
    return {1<<i for i in range(t.bit_length()) if t>>i&1}


def _rewrite(parts,a,b):
    if a in parts and b in parts:
        parts.difference_update((a,b))
        parts.add(a|b)


def discover(coordinates, *, max_rules=128, max_pair_visits=2_000_000,
             forecast_repetitions=1):
    """Select repeated pairs; charge construction and checking, meter search separately."""
    if any(type(v) is not int or v<0 for v in (max_rules,max_pair_visits)) or type(
            forecast_repetitions) is not int or forecast_repetitions<1:
        raise BootstrapRefused("invalid discovery budget")
    parts=[_atoms(t) for t in coordinates]
    initial=sum(map(len,parts))
    rules=[]
    visits=0
    reason="RULE_BUDGET"
    while len(rules)<max_rules:
        required=sum(len(p)*(len(p)-1)//2 for p in parts)
        if visits+required>max_pair_visits:
            reason="DISCOVERY_BUDGET"
            break
        freq=Counter(pair for p in parts for pair in combinations(sorted(p),2))
        visits+=required
        if not freq:
            reason="NO_PAIR"
            break
        a,b=min(freq,key=lambda p:(-freq[p],p))
        if freq[a,b]*forecast_repetitions<=4:
            reason="NO_POSITIVE_GAIN"
            break
        rules.append((a,b))
        for p in parts:
            _rewrite(p,a,b)
    return tuple(rules), {"pair_visits":visits,"training_atoms":initial,
                         "training_remaining":sum(map(len,parts)),
                         "rules":len(rules),"stop":reason}


@dataclass(frozen=True)
class AffineVocabulary:
    """Immutable checked action DAG rooted in the existing binary basis."""
    basis: AffineVerificationGround
    rules: tuple

    def __post_init__(self):
        if type(self.basis) is not AffineVerificationGround or self.basis.width!=1:
            raise BootstrapRefused("admitted binary basis required")
        if type(self.rules) is not tuple:
            raise BootstrapRefused("immutable rules required")
        known={1<<i:row[1] for i,row in enumerate(self.basis.rows)}
        for entry in self.rules:
            if type(entry) is not tuple or len(entry)!=4:
                raise BootstrapRefused("invalid rule shape")
            a,b,p,q=entry
            if any(type(v) is not int for v in entry) or not (
                    a in known and b in known and a<b and not a&b and
                    0<=p<self.basis.m and 0<=q<self.basis.m):
                raise BootstrapRefused("invalid rule dependency or coefficients")
            u,v=known[a]
            r,s=known[b]
            # Receiver checks reverse composition, independent of producer order.
            if (p,q)!=(r*u%self.basis.m,(r*v+s)%self.basis.m):
                raise BootstrapRefused("rule action does not follow from dependencies")
            if a|b in known and known[a|b]!=(p,q):
                raise BootstrapRefused("conflicting instruction")
            known[a|b]=(p,q)

    @classmethod
    def form(cls,basis,pairs):
        if type(basis) is not AffineVerificationGround or basis.width!=1:
            raise BootstrapRefused("admitted binary basis required")
        known={1<<i:row[1] for i,row in enumerate(basis.rows)}
        rules=[]
        for a,b in pairs:
            if not (type(a) is int and type(b) is int and a in known and b in known
                    and a<b and not a&b):
                raise BootstrapRefused("unknown or overlapping rule")
            p,q=known[a]
            r,s=known[b]
            v=(p*r%basis.m,(p*s+q)%basis.m)
            known[a|b]=v
            rules.append((a,b,*v))
        return cls(basis,tuple(rules))

    @property
    def law(self):
        return self.basis.a,self.basis.c,self.basis.m

    def snapshot(self):
        body={"schema":SCHEMA,"basis":self.basis.snapshot(),"rules":[list(r) for r in self.rules]}
        return {**body,"digest":digest(body)}

    @classmethod
    def restore(cls,raw,*,law):
        if type(raw) is not dict or set(raw)!={"schema","basis","rules","digest"}:
            raise BootstrapRefused("invalid vocabulary snapshot")
        body={k:v for k,v in raw.items() if k!="digest"}
        if raw["schema"]!=SCHEMA or digest(body)!=raw["digest"] or type(raw["rules"]) is not list or any(
                type(r) is not list for r in raw["rules"]):
            raise BootstrapRefused("invalid vocabulary identity")
        basis=AffineVerificationGround.restore(raw["basis"],law=law)
        return cls(basis,tuple(tuple(r) for r in raw["rules"]))

    def recipe(self,t):
        parts=_atoms(t)
        for a,b,_,_ in self.rules:
            _rewrite(parts,a,b)
        combined=0
        for p in parts:
            if combined&p:
                raise BootstrapRefused("overlapping recipe")
            combined|=p
        if combined!=t:
            raise BootstrapRefused("incomplete recipe")
        return tuple(sorted(parts))

    def advance(self,x,t):
        if type(x) is not int or not 0<=x<self.basis.m:
            raise BootstrapRefused("state outside domain")
        maps={1<<i:row[1] for i,row in enumerate(self.basis.rows)}
        maps.update((a|b,(p,q)) for a,b,p,q in self.rules)
        for key in self.recipe(t):
            p,q=maps[key]
            x=(p*x+q)%self.basis.m
        return x

    def expected(self,orbit,t):
        if (orbit.a,orbit.c,orbit.m)!=self.law:
            raise BootstrapRefused("verification Ground law mismatch")
        return orbit.value(t,self.advance(orbit.x0,t))

    def profile(self,coordinates):
        coords=tuple(_coordinate(t) for t in coordinates)
        count=sum(len(self.recipe(t)) for t in coords)
        prep=500+4*len(self.rules)
        return {"rules":len(self.rules),"preparation":prep,"queries":count,
                "total":prep+count,"binary_total":500+sum(t.bit_count() for t in coords),
                "cold":sum(cold_multiplications(t) for t in coords),
                "recipe_rule_visits":len(coords)*len(self.rules)}
