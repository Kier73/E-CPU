"""MGA-001/J: exact symbolic closure of a nonlinear switching controller."""
from dataclasses import dataclass
from .substrate_bootstrap import BootstrapRefused, digest
from .switching_affine_ground import form, verify, _navigate_ordered, _apply


def _xor(mask,rows):
    result=0
    while mask:
        bit=mask&-mask
        result^=rows[bit.bit_length()-1]
        mask^=bit
    return result


def _evaluate(rows,state):
    return sum(((r&state).bit_count()&1)<<i for i,r in enumerate(rows))


def _guard(terms,bits):
    return sum((bits&t)==t for t in terms)&1


def _valid_mask(v,width):
    return type(v) is int and 0<=v<1<<width


@dataclass(frozen=True)
class SymbolicSource:
    width: int
    modulus: int
    guard_rows: tuple
    guard_terms: tuple
    controls: tuple
    actions: tuple

    def __post_init__(self):
        n,m=self.width,self.modulus
        if type(n) is not int or not 1<=n<=4096 or type(m) is not int or m<2 or m.bit_length()>4096:
            raise BootstrapRefused("invalid symbolic domain")
        if (type(self.guard_rows) is not tuple or not self.guard_rows or
                any(not _valid_mask(v,n) for v in self.guard_rows) or
                type(self.guard_terms) is not tuple or
                any(not _valid_mask(v,len(self.guard_rows)) for v in self.guard_terms) or
                tuple(sorted(set(self.guard_terms)))!=self.guard_terms):
            raise BootstrapRefused("invalid guard ANF")
        if (type(self.controls) is not tuple or len(self.controls)!=2 or
                any(type(rows) is not tuple or len(rows)!=n or any(
                    not _valid_mask(v,n) for v in rows) for rows in self.controls)):
            raise BootstrapRefused("invalid binary branch control")
        if (type(self.actions) is not tuple or len(self.actions)!=2 or
                any(type(a) is not tuple or len(a)!=3 or a[2]!=(0,0,1) or any(
                    type(row) is not tuple or len(row)!=3 or any(
                        type(v) is not int or not 0<=v<m for v in row) for row in a)
                    for a in self.actions)):
            raise BootstrapRefused("invalid affine branch action")

    @property
    def fingerprint(self):
        return digest(["mga001.symbolic-switch.v1",self.width,self.modulus,
                       self.guard_rows,self.guard_terms,self.controls,self.actions])

    def check_state(self,c,z):
        if not _valid_mask(c,self.width) or type(z) is not tuple or len(z)!=2 or any(
                type(v) is not int or not 0<=v<self.modulus for v in z):
            raise BootstrapRefused("invalid source state")

    def branch(self,c):
        if not _valid_mask(c,self.width):
            raise BootstrapRefused("invalid control state")
        return _guard(self.guard_terms,_evaluate(self.guard_rows,c))

    def step(self,c,z):
        self.check_state(c,z)
        b=self.branch(c)
        return _evaluate(self.controls[b],c),_apply(self.actions[b],z,self.modulus)


@dataclass(frozen=True)
class Closure:
    source: str
    basis: tuple
    guard_codes: tuple
    branch_codes: tuple
    ancestry: tuple


def discover(source,*,max_features=128):
    """Least invariant linear row space containing declared guard parity forms."""
    if type(source) is not SymbolicSource or type(max_features) is not int or max_features<0:
        raise BootstrapRefused("invalid closure request")
    basis=[]
    ancestry=[]
    pivots={}
    def reduce(v):
        code=0
        while v:
            p=v.bit_length()-1
            if p not in pivots:
                break
            row,mask=pivots[p]
            v^=row
            code^=mask
        return v,code
    def insert(v,kind,i,b):
        row,code=reduce(v)
        if row:
            if len(basis)>=max_features:
                raise BootstrapRefused("feature budget exhausted; closure unknown")
            pivots[row.bit_length()-1]=(row,1<<len(basis))
            basis.append(row)
            ancestry.append((kind,i,b,code))
    for i,row in enumerate(source.guard_rows):
        insert(row,"guard",i,0)
    i=0
    while i<len(basis):
        for b,rows in enumerate(source.controls):
            insert(_xor(basis[i],rows),"pullback",i,b)
        i+=1
    def encode(row):
        residual,code=reduce(row)
        if residual:
            raise BootstrapRefused("unclosed parity feature")
        return code
    result=Closure(source.fingerprint,tuple(basis),
                   tuple(encode(r) for r in source.guard_rows),
                   tuple(tuple(encode(_xor(r,rows)) for r in basis)
                         for rows in source.controls),tuple(ancestry))
    verify_closure(source,result)
    return result


def verify_closure(source,ground):
    """Check exact source identities and ancestry without producer elimination."""
    if type(ground) is not Closure or ground.source!=source.fingerprint:
        raise BootstrapRefused("foreign closure")
    Q=ground.basis
    if (type(Q) is not tuple or len(Q)>source.width or any(
            not _valid_mask(v,source.width) or not v for v in Q)
            or type(ground.ancestry) is not tuple or len(ground.ancestry)!=len(Q)):
        raise BootstrapRefused("invalid closure extent")
    r=len(Q)
    def explicit(mask,rows):
        # Independent coefficient expansion.
        out=0
        for j,row in enumerate(rows):
            if (mask>>j)&1:
                out^=row
        return out
    # Independent rank check, eliminate low pivots.
    pivots={}
    for row in Q:
        v=row
        while v:
            p=v&-v
            if p not in pivots:
                pivots[p]=v
                break
            v^=pivots[p]
        if not v:
            raise BootstrapRefused("dependent closure basis")
    for j,entry in enumerate(ground.ancestry):
        if type(entry) is not tuple or len(entry)!=4:
            raise BootstrapRefused("invalid ancestry")
        kind,i,b,code=entry
        if type(i) is not int or type(b) is not int or not _valid_mask(code,j):
            raise BootstrapRefused("invalid ancestry dependency")
        if kind=="guard" and 0<=i<len(source.guard_rows) and b==0:
            row=source.guard_rows[i]
        elif kind=="pullback" and 0<=i<j and b in (0,1):
            row=explicit(Q[i],source.controls[b])
        else:
            raise BootstrapRefused("invalid ancestry source")
        if Q[j]!=row^explicit(code,Q[:j]):
            raise BootstrapRefused("incorrect ancestry identity")
    if (type(ground.guard_codes) is not tuple or len(ground.guard_codes)!=len(source.guard_rows)
            or type(ground.branch_codes) is not tuple or len(ground.branch_codes)!=2
            or any(type(codes) is not tuple or len(codes)!=r for codes in ground.branch_codes)):
        raise BootstrapRefused("invalid closure decoder shape")
    for code,row in zip(ground.guard_codes,source.guard_rows):
        if not _valid_mask(code,r) or explicit(code,Q)!=row:
            raise BootstrapRefused("guard does not factor")
    for b,codes in enumerate(ground.branch_codes):
        for code,row in zip(codes,Q):
            if not _valid_mask(code,r) or explicit(code,Q)!=explicit(row,source.controls[b]):
                raise BootstrapRefused("pullback does not close")
    return True


@dataclass(frozen=True)
class SymbolicPathLaw:
    source: SymbolicSource
    closure: Closure

    def __post_init__(self):
        verify_closure(self.source,self.closure)

    @property
    def modulus(self):
        return self.source.modulus

    @property
    def state_count(self):
        return 1<<len(self.closure.basis)

    @property
    def fingerprint(self):
        return digest(["mga001.symbolic-path.v1",self.source.fingerprint,
                       self.closure.basis,self.closure.guard_codes,self.closure.branch_codes])

    @property
    def matrices(self):
        # Lazy action catalogue: no 2**rank allocation.
        return self

    def representative(self,r):
        if not _valid_mask(r,len(self.closure.basis)):
            raise BootstrapRefused("invalid switching feature coordinate")
        return r

    def index(self,c):
        if not _valid_mask(c,self.source.width):
            raise BootstrapRefused("invalid control state")
        return _evaluate(self.closure.basis,c)

    def branch(self,r):
        self.representative(r)
        return _guard(self.source.guard_terms,_evaluate(self.closure.guard_codes,r))

    def __getitem__(self,r):
        return self.source.actions[self.branch(r)]

    def next_residue(self,r):
        return _evaluate(self.closure.branch_codes[self.branch(r)],r)

    def form_path(self,c,*,max_visits=4096):
        return form(self,self.index(c),max_visits=max_visits)

    def navigate(self,path,c,z,t):
        self.source.check_state(c,z)
        verify(self,path)
        if self.index(c)!=path.start or type(t) is not int or t<0:
            raise BootstrapRefused("invalid symbolic path coordinate")
        result=_navigate_ordered(self,path,z,t)
        branches=tuple(self.branch(r) for r in path.path)
        def run(c,seq):
            for b in seq:
                c=_evaluate(self.source.controls[b],c)
            return c
        mu=path.transient
        if t<mu:
            return run(c,branches[:t]),result
        c=run(c,branches[:mu])
        cycle=branches[mu:]
        k,tail=divmod(t-mu,path.period)
        B=tuple(1<<i for i in range(self.source.width))
        for b in cycle:
            B=tuple(_xor(row,B) for row in self.source.controls[b])
        while k:
            if k&1:
                c=_evaluate(B,c)
            k>>=1
            if k:
                B=tuple(_xor(row,B) for row in B)
        return run(c,cycle[:tail]),result
