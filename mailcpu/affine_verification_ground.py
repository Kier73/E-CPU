"""MGA-001/E: independently admitted radix laws for amortized exact verification.

The compiled object retains transition *maps*, not observed answers.
A restored untrusted table is fully checked before it can verify any query.
"""
from __future__ import annotations

from dataclasses import dataclass

from .substrate_bootstrap import BootstrapRefused, digest, canonical
from .runtime_qualification import affine_expected

SCHEMA = "mailcpu.mga001.affine-verification-ground.v1"
MAX_BITS = 63


def _shape(width):
    if type(width) is not int or not 1 <= width <= 8:
        raise BootstrapRefused("radix width outside supported range 1..8")
    return tuple(1 << min(width, MAX_BITS-j) for j in range(0, MAX_BITS, width))


def _law(a, c, m):
    if type(m) is not int or not 2 <= m <= 2**31-1 or any(
            type(v) is not int or not 0 <= v < m for v in (a, c)):
        raise BootstrapRefused("invalid affine law")


def _coordinate(t):
    if type(t) is not int or not 0 <= t < 1 << MAX_BITS:
        raise BootstrapRefused("invalid exponent coordinate")
    return t


def _apply(pair, x, m):
    return (pair[0]*x + pair[1]) % m


def _compose(left, right, m):
    # left after right
    return ((left[0]*right[0]) % m, (left[0]*right[1]+left[1]) % m)


def cold_multiplications(t):
    """The native binary affine_expected loop: two squares, two per set bit,
    and one final application. Counts modular multiplications, not wall time."""
    t = _coordinate(t)
    return 2*t.bit_length() + 2*t.bit_count() + 1


def warm_multiplications(t, width):
    _shape(width)
    t = _coordinate(t)
    count = 0
    while t:
        count += int(bool(t & ((1 << width)-1)))
        t >>= width
    return count


def preparation_multiplications(width):
    """Producer + independent admission; count every map composition."""
    sizes = _shape(width)
    # Producer: successive digit maps and width squarings between rows.
    # Checker: successive digit maps and one composition between rows.
    produce = 2*(sum(s-1 for s in sizes) + width*(len(sizes)-1))
    admit = 2*(sum(s-1 for s in sizes) + len(sizes)-1)
    return produce, admit


def profile(coordinates, width):
    """Exact arithmetic-count model for the supplied forecast, including cold."""
    coords = tuple(_coordinate(t) for t in coordinates)
    produce, admit = preparation_multiplications(width)
    warm = sum(warm_multiplications(t, width) for t in coords)
    return {"width": width, "entries": sum(_shape(width)),
            "producer": produce, "admission": admit, "queries": warm,
            "total": produce+admit+warm,
            "cold": sum(cold_multiplications(t) for t in coords)}


def select_width(coordinates, *, max_entries=2048):
    """Compare the cold baseline and all supported bounded radix widths."""
    coords = tuple(_coordinate(t) for t in coordinates)
    if type(max_entries) is not int or max_entries < 0:
        raise BootstrapRefused("invalid table entry budget")
    cold = sum(cold_multiplications(t) for t in coords)
    candidates = [profile(coords, w) for w in range(1,9) if sum(_shape(w)) <= max_entries]
    best = min(candidates, key=lambda p:(p["total"],p["entries"],p["width"]), default=None)
    return {"selected": best["width"] if best and best["total"] < cold else None,
            "cold": cold, "candidates": candidates}


@dataclass(frozen=True)
class AffineVerificationGround:
    """Immutable exact action basis; construction always independently audits."""
    a: int
    c: int
    m: int
    width: int
    rows: tuple

    def __post_init__(self):
        _law(self.a, self.c, self.m)
        sizes = _shape(self.width)
        if type(self.rows) is not tuple or len(self.rows) != len(sizes):
            raise BootstrapRefused("invalid radix row count")
        base = (self.a, self.c)
        for index, (size, row) in enumerate(zip(sizes, self.rows)):
            if type(row) is not tuple or len(row) != size:
                raise BootstrapRefused("invalid radix digit count")
            if any(type(p) is not tuple or len(p) != 2 or any(
                    type(v) is not int or not 0 <= v < self.m for v in p) for p in row):
                raise BootstrapRefused("invalid radix coefficients")
            if row[0] != (1,0):
                raise BootstrapRefused("invalid radix identity")
            # Independent check uses right composition and row boundary,
            # not the producer's squaring algorithm.
            for d in range(1, size):
                p,q = row[d-1]
                a,c = base
                if row[d] != ((p*a)%self.m, (p*c+q)%self.m):
                    raise BootstrapRefused("radix digit law differs")
            if index+1 < len(sizes):
                p,q = row[-1]
                a,c = base
                base = ((p*a)%self.m, (p*c+q)%self.m)

    @classmethod
    def form(cls, a, c, m, width=4):
        _law(a,c,m)
        sizes = _shape(width)
        rows = []
        base = (a,c)
        for i,size in enumerate(sizes):
            row = [(1,0)]
            for _ in range(1,size):
                row.append(_compose(base,row[-1],m))
            rows.append(tuple(row))
            if i+1 < len(sizes):
                for _ in range(width):
                    base = _compose(base,base,m)
        return cls(a,c,m,width,tuple(rows))

    def snapshot(self):
        body = {"schema": SCHEMA,"law":[self.a,self.c,self.m],"width":self.width,
                "rows":[[list(p) for p in row] for row in self.rows]}
        return {**body,"digest":digest(body)}

    @classmethod
    def restore(cls, raw, *, law):
        """Digest is integrity only; arithmetic audit is mandatory on restore."""
        if type(raw) is not dict or set(raw) != {"schema","law","width","rows","digest"}:
            raise BootstrapRefused("invalid radix snapshot")
        body = {k:v for k,v in raw.items() if k != "digest"}
        if raw["schema"] != SCHEMA or raw["law"] != list(law) or digest(body) != raw["digest"]:
            raise BootstrapRefused("radix snapshot identity mismatch")
        sizes = _shape(raw["width"])
        rows = raw["rows"]
        if type(rows) is not list or len(rows) != len(sizes) or any(
                type(r) is not list or len(r) != s for r,s in zip(rows,sizes)):
            raise BootstrapRefused("invalid radix snapshot extent")
        if any(type(p) is not list for r in rows for p in r):
            raise BootstrapRefused("invalid radix snapshot coefficients")
        return cls(*law,raw["width"],tuple(tuple(tuple(p) for p in r) for r in rows))

    def advance(self, x, t):
        """Apply admitted digit maps to ANY input, including unseen states."""
        t = _coordinate(t)
        if type(x) is not int or not 0 <= x < self.m:
            raise BootstrapRefused("state outside affine domain")
        mask = (1 << self.width)-1
        for row in self.rows:
            d = t & mask
            if d:
                x = _apply(row[d],x,self.m)
            t >>= self.width
            if not t:
                break
        return x

    def expected(self, orbit, t):
        if (orbit.a,orbit.c,orbit.m) != (self.a,self.c,self.m):
            raise BootstrapRefused("verification Ground law mismatch")
        return orbit.value(t,self.advance(orbit.x0,t))
