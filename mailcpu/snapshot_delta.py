"""Exact canonical JSON snapshot deltas; native checkpoint bytes remain authoritative."""
from dataclasses import dataclass
from hashlib import sha256
import json
import re

MAX_BYTES = 4_194_304
_HEX = re.compile(r'[0-9a-f]{64}\Z')


def _canonical(value):
    """Encode exactly the native canonical JSON representation."""
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode('utf-8')


def _decode(raw, limit):
    """Require canonical bounded JSON bytes, including unambiguous object keys."""
    if type(raw) is not bytes or len(raw)>limit:
        raise ValueError('invalid snapshot byte size')
    try:
        value=json.loads(raw)
        if _canonical(value)!=raw:
            raise ValueError('noncanonical snapshot bytes')
    except (ValueError,TypeError,RecursionError,UnicodeError) as exc:
        raise ValueError('invalid canonical snapshot') from exc
    return value


def _same(a,b):
    """Distinguish JSON types and representations, even equal Python numbers."""
    return type(a) is type(b) and a==b and _canonical(a)==_canonical(b)


def _span(a,b,equal):
    """Find disjoint equal prefix and suffix lengths."""
    common=min(len(a),len(b)); p=0; s=0
    while p<common and equal(a[p],b[p]): p+=1
    while s<common-p and equal(a[len(a)-1-s],b[len(b)-1-s]): s+=1
    return p,s


def _string_edits(a,b):
    """Describe separated equal-length mutations without copying intervening bytes."""
    edits=[]; start=end=None
    for i,(x,y) in enumerate(zip(a,b)):
        if x==y: continue
        if start is None: start=i
        elif i-end>16:
            edits.append([start,b[start:end]])
            if len(edits)>4096: return None
            start=i
        end=i+1
    if start is not None: edits.append([start,b[start:end]])
    return [4,edits]


def _diff(a,b,depth=0):
    """Describe changed fields and sequence spans; fall back to exact replacement."""
    if _same(a,b): return None
    direct=[0,b]
    if depth>=64: return direct
    if type(a) is dict and type(b) is dict:
        changes={k:_diff(a[k],v,depth+1) if k in a else [0,v] for k,v in b.items()}
        edit=[1,sorted(a.keys()-b.keys()),{k:v for k,v in changes.items() if v is not None}]
    elif type(a) is list and type(b) is list:
        p,s=_span(a,b,_same)
        edit=[2,p,s,b[p:len(b)-s]]
    elif type(a) is str and type(b) is str:
        p,s=_span(a,b,lambda x,y:x==y)
        edit=[3,p,s,b[p:len(b)-s]]
        if len(a)==len(b):
            multi=_string_edits(a,b)
            if multi is not None and len(_canonical(multi))<len(_canonical(edit)):
                edit=multi
    else: return direct
    return edit if len(_canonical(edit))<len(_canonical(direct)) else direct


def _apply(a,patch,depth=0):
    """Apply strict typed edits without evaluating code or referencing another base."""
    if patch is None: return a
    if depth>64 or type(patch) is not list or not patch or type(patch[0]) is not int:
        raise ValueError('invalid delta operation')
    op=patch[0]
    if op==0 and len(patch)==2: return patch[1]
    if op==1 and len(patch)==3 and type(a) is dict:
        removed,changes=patch[1:]
        if (type(removed) is not list or any(type(k) is not str for k in removed)
                or len(set(removed))!=len(removed) or type(changes) is not dict
                or not set(removed)<=a.keys() or set(removed)&changes.keys()):
            raise ValueError('invalid object delta')
        out={k:v for k,v in a.items() if k not in removed}
        for k,p in changes.items():
            if k not in a and (type(p) is not list or len(p)!=2 or p[0]!=0):
                raise ValueError('new field must be an exact replacement')
            out[k]=_apply(a.get(k),p,depth+1)
        return out
    if op in (2,3) and len(patch)==4 and type(a) is (list if op==2 else str):
        p,s,middle=patch[1:]
        if (type(p) is not int or type(s) is not int or p<0 or s<0 or p+s>len(a)
                or type(middle) is not type(a)):
            raise ValueError('invalid sequence delta')
        return a[:p]+middle+(a[len(a)-s:] if s else a[:0])
    if op==4 and len(patch)==2 and type(a) is str and type(patch[1]) is list and len(patch[1])<=4097:
        out=[]; end=0
        for entry in patch[1]:
            if type(entry) is not list or len(entry)!=2:
                raise ValueError('invalid string mutation')
            offset,value=entry
            if (type(offset) is not int or offset<end or type(value) is not str or not value
                    or offset+len(value)>len(a)):
                raise ValueError('invalid string mutation')
            out.extend((a[end:offset],value)); end=offset+len(value)
        out.append(a[end:])
        return ''.join(out)
    raise ValueError('invalid delta operation')


@dataclass(frozen=True,slots=True)
class SnapshotDelta:
    """Pinned base and exact target identity; a representation, not an admission proof."""
    base_digest: str
    target_digest: str
    target_size: int
    patch: bytes

    def __post_init__(self):
        """Validate metadata and bounded patch bytes."""
        if any(type(d) is not str or not _HEX.fullmatch(d) for d in (self.base_digest,self.target_digest)):
            raise ValueError('invalid snapshot digest')
        if type(self.target_size) is not int or not 0<self.target_size<=MAX_BYTES:
            raise ValueError('invalid target size')
        if type(self.patch) is not bytes or len(self.patch)>MAX_BYTES+16:
            raise ValueError('invalid patch size')

    @property
    def encoded_size(self):
        """Count patch bytes plus two binary SHA-256 identities and uint64 length."""
        return len(self.patch)+72

    def reconstruct(self,base):
        """Reconstruct exact bytes or refuse missing, substituted, or altered information."""
        a=_decode(base,MAX_BYTES)
        if sha256(base).hexdigest()!=self.base_digest:
            raise ValueError('base identity differs')
        p=_decode(self.patch,MAX_BYTES+16)
        try: result=_canonical(_apply(a,p))
        except (TypeError,ValueError,RecursionError,UnicodeError) as exc:
            raise ValueError('invalid structural patch') from exc
        if len(result)!=self.target_size or sha256(result).hexdigest()!=self.target_digest:
            raise ValueError('target identity differs')
        return result


def form_snapshot_delta(base,target):
    """Form a one-hop structural description; verify reconstruction before returning."""
    a,b=_decode(base,MAX_BYTES),_decode(target,MAX_BYTES)
    patch=_canonical(_diff(a,b))
    delta=SnapshotDelta(sha256(base).hexdigest(),sha256(target).hexdigest(),len(target),patch)
    if delta.reconstruct(base)!=target:
        raise ValueError('snapshot delta failed exact verification')
    return delta
