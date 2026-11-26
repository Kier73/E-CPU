"""MGA-001/G: coalescent dependency-qualified action instructions."""
from __future__ import annotations
from collections import Counter
from dataclasses import dataclass
from itertools import combinations

from .affine_vocabulary import AffineVocabulary
from .affine_verification_ground import AffineVerificationGround, _coordinate
from .substrate_bootstrap import BootstrapRefused, digest

SCHEMA="mailcpu.mga001.coalescent-affine.v1"


def _order(r):
    return ((r[0]|r[1]).bit_count(),r)


def _canonical(rules):
    return tuple(sorted(set(rules),key=_order))


def contribution(basis,rules):
    """Packet is a proof description, not a trusted sender or a grant."""
    body={"schema":SCHEMA,"basis":basis.snapshot()["digest"],
          "rules":[list(r) for r in _canonical(rules)]}
    return {**body,"digest":digest(body)}


@dataclass(frozen=True)
class CoalescentVocabulary:
    """Immutable union of proof descriptions; semantic actions are checked."""
    checked: AffineVocabulary

    def __post_init__(self):
        if type(self.checked) is not AffineVocabulary or self.checked.rules!=_canonical(self.checked.rules):
            raise BootstrapRefused("canonical checked vocabulary required")

    @classmethod
    def empty(cls,basis):
        return cls(AffineVocabulary(basis,()))

    @property
    def basis(self):
        return self.checked.basis

    @property
    def rules(self):
        return self.checked.rules

    @property
    def law(self):
        return self.checked.law

    def packet(self):
        return contribution(self.basis,self.rules)

    def ingest(self,packets):
        """Atomic pure union. Dependencies may arrive in any order in one batch."""
        incoming=set(self.rules)
        pin=self.basis.snapshot()["digest"]
        for packet in packets:
            if type(packet) is not dict or set(packet)!={"schema","basis","rules","digest"}:
                raise BootstrapRefused("invalid contribution")
            body={k:v for k,v in packet.items() if k!="digest"}
            if packet["schema"]!=SCHEMA or packet["basis"]!=pin or packet["digest"]!=digest(body):
                raise BootstrapRefused("foreign or altered contribution")
            if type(packet["rules"]) is not list or any(
                    type(r) is not list or len(r)!=4 or any(type(v) is not int for v in r)
                    for r in packet["rules"]):
                raise BootstrapRefused("invalid contribution rule")
            incoming.update(tuple(r) for r in packet["rules"])
        # Ascending result popcount is a topological order because masks
        # are positive and disjoint. The native vocabulary independently
        # checks every coefficient and dependency, including alternative proofs.
        return type(self)(AffineVocabulary(self.basis,_canonical(incoming)))

    def _maps(self):
        maps={1<<i:row[1] for i,row in enumerate(self.basis.rows)}
        maps.update((a|b,(p,q)) for a,b,p,q in self.rules)
        return maps

    def recipe(self,t):
        """Largest-first disjoint mask cover, not a minimum-cover claim."""
        t=_coordinate(t)
        return _recipe(t,self._maps())

    def advance(self,x,t):
        if type(x) is not int or not 0<=x<self.basis.m:
            raise BootstrapRefused("state outside domain")
        maps=self._maps()
        for k in _recipe(_coordinate(t),maps):
            p,q=maps[k]
            x=(p*x+q)%self.basis.m
        return x

    def expected(self,orbit,t):
        if (orbit.a,orbit.c,orbit.m)!=self.law:
            raise BootstrapRefused("verification Ground law mismatch")
        return orbit.value(t,self.advance(orbit.x0,t))

    def learn(self,coordinates,*,max_rules=128,max_pair_visits=2_000_000):
        """Learn new cross-contributor actions; original instance is unchanged."""
        if any(type(v) is not int or v<0 for v in (max_rules,max_pair_visits)):
            raise BootstrapRefused("invalid learning budget")
        coords=tuple(_coordinate(t) for t in coordinates)
        maps=self._maps()
        added=[]
        visits=0
        reason="RULE_BUDGET"
        for _ in range(max_rules):
            recipes=[_recipe(t,maps) for t in coords]
            required=sum(len(r)*(len(r)-1)//2 for r in recipes)
            if visits+required>max_pair_visits:
                reason="DISCOVERY_BUDGET"
                break
            counts=Counter((a,b) for r in recipes for a,b in combinations(sorted(r),2)
                           if a|b not in maps)
            visits+=required
            if not counts:
                reason="NO_PAIR"
                break
            a,b=min(counts,key=lambda k:(-counts[k],k))
            if counts[a,b]<=4:
                reason="NO_POSITIVE_GAIN"
                break
            p,q=maps[a]
            r,s=maps[b]
            value=(p*r%self.basis.m,(p*s+q)%self.basis.m)
            maps[a|b]=value
            added.append((a,b,*value))
        packet=contribution(self.basis,added)
        result=self.ingest([packet])
        return result,packet,{"rules":len(added),"pair_visits":visits,"stop":reason}

    def profile(self,coordinates):
        coords=tuple(_coordinate(t) for t in coordinates)
        maps=self._maps()
        q=sum(len(_recipe(t,maps)) for t in coords)
        prep=500+4*len(self.rules)
        return {"rules":len(self.rules),"applications":q,"preparation":prep,
                "total":prep+q,"mask_visits":len(coords)*len(maps)}


def _recipe(t,maps):
    remainder=t
    out=[]
    for key in sorted(maps,key=lambda k:(-k.bit_count(),k)):
        if remainder&key==key:
            out.append(key)
            remainder^=key
    if remainder:
        raise BootstrapRefused("incomplete exponent recipe")
    # Independently establish exact disjoint cover of the requested exponent.
    union=0
    for k in out:
        if union&k:
            raise BootstrapRefused("overlapping exponent recipe")
        union|=k
    if union!=t:
        raise BootstrapRefused("recipe exponent differs")
    return tuple(out)
