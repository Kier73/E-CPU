"""MGA-001/I: discover exact fibre-restricted switching quotient.

Uses native INTENT-001 minimal future-observer machines and MGA-001/H
ordered return maps. All action identities are exact on their source fibres.
"""
from dataclasses import dataclass, field

from .intention_formed_fabric import FiniteObserverLaw, form_observer_machine, verify_formed_machine
from .switching_affine_ground import SwitchingLaw, form, navigate, verify
from .substrate_bootstrap import BootstrapRefused, digest


def normalize(law,r):
    """Canonical affine representative on the residue fibre of r."""
    if type(law) is not SwitchingLaw:
        raise BootstrapRefused("declared switching law required")
    x,y=law.representative(r)
    h=law.modulus//law.residue_modulus
    m=law.modulus
    rows=[]
    for a,b,c in law.matrices[r][:2]:
        u,v=a%h,b%h
        rows.append((u,v,(c+(a-u)*x+(b-v)*y)%m))
    return tuple(rows)+((0,0,1),)


def verify_fibre(law,r,candidate):
    """Exact equality on every lift; check generator differences and anchor."""
    x,y=law.representative(r)
    m,q=law.modulus,law.residue_modulus
    if (type(candidate) is not tuple or len(candidate)!=3 or
            any(type(row) is not tuple or len(row)!=3 or any(
                type(v) is not int or not 0<=v<m for v in row) for row in candidate)
            or candidate[2]!=(0,0,1)):
        raise BootstrapRefused("invalid candidate affine action")
    for original,altered in zip(law.matrices[r][:2],candidate[:2]):
        a,b,c=(u-v for u,v in zip(original,altered))
        if q*a%m or q*b%m or (a*x+b*y+c)%m:
            raise BootstrapRefused("action differs on source fibre")
    return True


@dataclass(frozen=True)
class FormedSwitchingLaw:
    """Receiver-formed action-labelled quotient, not a new physical state."""
    source: SwitchingLaw
    observer: FiniteObserverLaw=field(init=False)
    machine: object=field(init=False)
    matrices: tuple=field(init=False)

    def __post_init__(self):
        law=self.source
        if type(law) is not SwitchingLaw:
            raise BootstrapRefused("declared switching source required")
        # Native INTENT-001 currently admits at most 64 source states.
        if law.state_count>64:
            raise BootstrapRefused("native observer source extent exceeded")
        actions=tuple(normalize(law,r) for r in range(law.state_count))
        for r,a in enumerate(actions):
            verify_fibre(law,r,a)
        # Use exact matrix equality, not a digest as the observation label.
        catalogue=tuple(sorted(set(actions)))
        indices={a:i for i,a in enumerate(catalogue)}
        observer=FiniteObserverLaw(
            tuple(f"residue-{r}" for r in range(law.state_count)),
            ("step",),("matrix",),
            tuple((law.next_residue(r),) for r in range(law.state_count)),
            tuple((indices[a],) for a in actions))
        machine=form_observer_machine(observer,("matrix",))
        verify_formed_machine(observer,machine)
        matrices=tuple(catalogue[row[0]] for row in machine.outputs)
        for r in range(law.state_count):
            g=machine.state_groups[r]
            verify_fibre(law,r,matrices[g])
            if machine.transitions[g][0]!=machine.state_groups[law.next_residue(r)]:
                raise BootstrapRefused("formed transition differs from source")
        object.__setattr__(self,"observer",observer)
        object.__setattr__(self,"machine",machine)
        object.__setattr__(self,"matrices",matrices)

    @property
    def modulus(self):
        return self.source.modulus

    @property
    def state_count(self):
        return len(self.matrices)

    @property
    def fingerprint(self):
        return digest(["mga001.formed-switching.v1",self.source.fingerprint,
                       self.machine.fingerprint,self.matrices])

    def index(self,x):
        return self.machine.state_groups[self.source.index(x)]

    def representative(self,r):
        if type(r) is not int or not 0<=r<self.state_count:
            raise BootstrapRefused("invalid quotient state")
        return self.source.representative(self.machine.groups[r][0])

    def next_residue(self,r):
        self.representative(r)
        return self.machine.transitions[r][0]

    def form_path(self,x,*,max_visits=None):
        return form(self,self.index(x),max_visits=max_visits)

    def navigate(self,ground,x,t):
        return navigate(self,ground,x,t)
