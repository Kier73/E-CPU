"""MGA-001/H: exact navigation of residue-switched noncommuting affine layers.

The joint residue determines the itinerary. Composition is ordered; neither
commutativity nor a global affine law is assumed.
"""
from dataclasses import dataclass
from .affine_orbit import _matrix_multiply
from .substrate_bootstrap import BootstrapRefused, digest

IDENTITY=((1,0,0),(0,1,0),(0,0,1))


def _product(a,b,m):
    # Reuse native exact affine matrix multiplication, reduce in the ring.
    return tuple(tuple(x%m for x in row) for row in
                 _matrix_multiply(a,b,max_bits=2*m.bit_length()+2))


def _apply(a,x,m):
    return tuple((row[0]*x[0]+row[1]*x[1]+row[2])%m for row in a[:2])


@dataclass(frozen=True)
class SwitchingLaw:
    modulus: int
    residue_modulus: int
    matrices: tuple

    def __post_init__(self):
        m,q=self.modulus,self.residue_modulus
        if (type(m) is not int or type(q) is not int or not 2<=q<=64
                or m<q or m%q or m.bit_length()>4096):
            raise BootstrapRefused("invalid residue quotient or modulus")
        if type(self.matrices) is not tuple or len(self.matrices)!=q*q:
            raise BootstrapRefused("complete joint-residue source required")
        for a in self.matrices:
            if (type(a) is not tuple or len(a)!=3 or any(
                    type(r) is not tuple or len(r)!=3 or any(
                        type(v) is not int or not 0<=v<m for v in r) for r in a)
                    or a[2]!=(0,0,1)):
                raise BootstrapRefused("invalid homogeneous affine matrix")

    @property
    def fingerprint(self):
        return digest(["mga001.switching.v1",self.modulus,self.residue_modulus,self.matrices])

    def index(self,x):
        if type(x) is not tuple or len(x)!=2 or any(
                type(v) is not int or not 0<=v<self.modulus for v in x):
            raise BootstrapRefused("invalid physical state")
        q=self.residue_modulus
        return x[0]%q+q*(x[1]%q)

    def representative(self,r):
        q=self.residue_modulus
        if type(r) is not int or not 0<=r<q*q:
            raise BootstrapRefused("invalid residue")
        return (r%q,r//q)

    def next_residue(self,r):
        return self.index(_apply(self.matrices[r],self.representative(r),self.modulus))

    def step(self,x):
        return _apply(self.matrices[self.index(x)],x,self.modulus)


@dataclass(frozen=True)
class PathGround:
    source: str
    start: int
    path: tuple
    transient: int
    prefix: tuple
    cycle_prefix: tuple

    @property
    def period(self):
        return len(self.path)-self.transient


def form(law,start,*,max_visits=None):
    law.representative(start)
    if max_visits is None:
        max_visits=law.residue_modulus**2
    if type(max_visits) is not int or max_visits<1:
        raise BootstrapRefused("invalid path budget")
    r=start
    path=[]
    seen={}
    prefix=[IDENTITY]
    m=law.modulus
    while r not in seen:
        if len(path)>=max_visits:
            raise BootstrapRefused("path budget exhausted; quotient not resolved")
        seen[r]=len(path)
        path.append(r)
        prefix.append(_product(law.matrices[r],prefix[-1],m))
        r=law.next_residue(r)
    mu=seen[r]
    cycle=[IDENTITY]
    for r in path[mu:]:
        cycle.append(_product(law.matrices[r],cycle[-1],m))
    result=PathGround(law.fingerprint,start,tuple(path),mu,tuple(prefix),tuple(cycle))
    verify(law,result)
    return result


def verify(law,ground):
    """Independent ordered path check using direct affine action on 0,e1,e2.

    No producer matrix multiply, trajectory search or physical-state enumeration.
    The three affine probe images determine a homogeneous 2D map over Z/MZ.
    """
    if type(ground) is not PathGround or ground.source!=law.fingerprint:
        raise BootstrapRefused("foreign path Ground")
    path=ground.path
    mu=ground.transient
    if (type(path) is not tuple or not path or path[0]!=ground.start
            or any(type(r) is not int or not 0<=r<law.residue_modulus**2 for r in path)
            or len(set(path))!=len(path) or type(mu) is not int or not 0<=mu<len(path)
            or type(ground.prefix) is not tuple or len(ground.prefix)!=len(path)+1
            or type(ground.cycle_prefix) is not tuple or len(ground.cycle_prefix)!=len(path)-mu+1):
        raise BootstrapRefused("invalid path shape")
    m=law.modulus
    probes=((0,0),(1,0),(0,1))
    p=probes
    c=probes
    def recover(images):
        o,e,f=images
        return tuple(((e[i]-o[i])%m,(f[i]-o[i])%m,o[i]) for i in range(2))+((0,0,1),)
    def strict_matrix(a,expected):
        return (type(a) is tuple and len(a)==3 and all(type(row) is tuple and len(row)==3
                and all(type(v) is int for v in row) for row in a) and a==expected)
    if not strict_matrix(ground.prefix[0],IDENTITY) or not strict_matrix(ground.cycle_prefix[0],IDENTITY):
        raise BootstrapRefused("path identity differs")
    for i,r in enumerate(path):
        successor=path[i+1] if i+1<len(path) else path[mu]
        if law.next_residue(r)!=successor:
            raise BootstrapRefused("incorrect joint-residue successor")
        a=law.matrices[r]
        p=tuple(_apply(a,x,m) for x in p)
        if not strict_matrix(ground.prefix[i+1],recover(p)):
            raise BootstrapRefused("incorrect ordered prefix")
        if i>=mu:
            c=tuple(_apply(a,x,m) for x in c)
            if not strict_matrix(ground.cycle_prefix[i-mu+1],recover(c)):
                raise BootstrapRefused("incorrect ordered return prefix")
    return True


def navigate(law,ground,x,t):
    """Verify supplied Ground and navigate transient + repeated return map + tail."""
    verify(law,ground)
    if law.index(x)!=ground.start or type(t) is not int or t<0:
        raise BootstrapRefused("invalid navigation coordinate or source residue")
    m=law.modulus
    mu=ground.transient
    if t<mu:
        return _apply(ground.prefix[t],x,m)
    count,tail=divmod(t-mu,ground.period)
    y=_apply(ground.prefix[mu],x,m)
    b=ground.cycle_prefix[-1]
    while count:
        if count&1:
            y=_apply(b,y,m)
        count>>=1
        if count:
            b=_product(b,b,m)
    return _apply(ground.cycle_prefix[tail],y,m)
