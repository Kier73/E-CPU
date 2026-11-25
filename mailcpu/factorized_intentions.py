"""Exact pure intention factorization with independent consumer coordinates."""
from dataclasses import dataclass
from hashlib import sha256
import struct
from types import MappingProxyType

from .shared_result_bank import PureContract

MAX_NODES = 65536
MAX_BYTES = 32 * 1024 * 1024
MAX_RESULT_BYTES = 128 * 1024 * 1024


def _frame(parts):
    """Injectively encode an ordered sequence of byte strings."""
    return b''.join(struct.pack('!I', len(p)) + p for p in parts)


def _hash(raw):
    """Return a canonical content identity."""
    return sha256(raw).hexdigest()


def _name(value):
    """Check bounded nonempty identifiers."""
    if type(value) is not str or not 1 <= len(value.encode('utf-8')) <= 256:
        raise ValueError('invalid name')


@dataclass(frozen=True)
class Binding:
    """Receiver-selected pure semantics and independent checker."""
    contract: PureContract
    produce: object
    verify: object

    def __post_init__(self):
        """Refuse unqualified binding shapes."""
        if not isinstance(self.contract, PureContract) or not callable(self.produce) or not callable(self.verify):
            raise ValueError('invalid binding')


@dataclass(frozen=True)
class Node:
    """One pure operation with exact payload and ordered dependency positions."""
    name: str
    binding: str
    payload: bytes
    deps: tuple = ()

    def __post_init__(self):
        """Check the immutable node shape, retaining repeated dependency positions."""
        _name(self.name); _name(self.binding)
        if type(self.payload) is not bytes or len(self.payload) > 4*1024*1024 or type(self.deps) is not tuple or len(self.deps)>256:
            raise ValueError('invalid node payload or dependencies')
        for d in self.deps:
            _name(d)


@dataclass(frozen=True)
class Intention:
    """Independent workflow identity, topologically ordered nodes and selected outputs."""
    name: str
    nodes: tuple
    outputs: tuple

    def __post_init__(self):
        """Validate every declared node, even if it is outside the requested cone."""
        _name(self.name)
        if type(self.nodes) is not tuple or not 1 <= len(self.nodes)<=256 or type(self.outputs) is not tuple or not self.outputs:
            raise ValueError('invalid intention geometry')
        seen=set()
        for n in self.nodes:
            if not isinstance(n,Node) or n.name in seen or any(d not in seen for d in n.deps):
                raise ValueError('non-topological or duplicate node')
            seen.add(n.name)
        if len(set(self.outputs))!=len(self.outputs) or any(o not in seen for o in self.outputs):
            raise ValueError('invalid outputs')


@dataclass(frozen=True)
class Work:
    """One structural equivalence class, excluding consumer-specific identity."""
    key: str
    binding: str
    contract: str
    payload: bytes
    deps: tuple


def _work(node, binding, deps):
    """Bind structure to exact ordered predecessor classes and semantic contract."""
    contract=binding.contract.digest
    key=_hash(_frame([b'fabric.pure-structure.v1',node.binding.encode('utf-8'),bytes.fromhex(contract),node.payload,*map(bytes.fromhex,deps)]))
    return Work(key,node.binding,contract,node.payload,deps)


@dataclass(frozen=True)
class Plan:
    """Detached structural work graph and original consumer-to-class mapping."""
    work: tuple
    members: tuple
    outputs: tuple

    def affected(self,key):
        """Return all requested workflows whose live cone contains this class."""
        return tuple(sorted({w for w,_,k in self.members if k==key}))


def _live(intent):
    """Select the transitive dependency cone of requested outputs only."""
    nodes={n.name:n for n in intent.nodes}; live=set(); todo=list(intent.outputs)
    while todo:
        name=todo.pop()
        if name in live: continue
        live.add(name); todo.extend(nodes[name].deps)
    return live


def _validate(intentions,bindings):
    """Bound the family before formation and require explicit pure bindings."""
    if not intentions or len({i.name for i in intentions})!=len(intentions):
        raise ValueError('empty or duplicate workflow family')
    if sum(len(i.nodes) for i in intentions)>MAX_NODES or sum(len(n.payload) for i in intentions for n in i.nodes)>MAX_BYTES:
        raise ValueError('family extent exceeded')
    for i in intentions:
        for n in i.nodes:
            if not isinstance(bindings.get(n.binding),Binding):
                raise ValueError('missing pure binding')


def factorize(intentions,bindings):
    """Intern identical live pure subgraphs in one topological pass."""
    intentions=tuple(intentions); _validate(intentions,bindings)
    unique={}; members=[]; outputs=[]
    for i in intentions:
        live=_live(i); keys={}
        for n in i.nodes:
            if n.name not in live: continue
            w=_work(n,bindings[n.binding],tuple(keys[d] for d in n.deps))
            if unique.setdefault(w.key,w)!=w:
                raise ValueError('structural digest collision')
            keys[n.name]=w.key; members.append((i.name,n.name,w.key))
        outputs.extend((i.name,o,keys[o]) for o in i.outputs)
    return Plan(tuple(unique.values()),tuple(members),tuple(outputs))


def verify_plan(intentions,bindings,plan):
    """Replay source coverage and each class identity, independent of producer grouping."""
    intentions=tuple(intentions); _validate(intentions,bindings)
    if not isinstance(plan,Plan): raise ValueError('invalid plan')
    if len(plan.work)>MAX_NODES or len(plan.members)>MAX_NODES or len(plan.outputs)>MAX_NODES:
        raise ValueError('plan extent exceeded')
    table={}
    for w in plan.work:
        if not isinstance(w,Work) or w.key in table or any(d not in table for d in w.deps):
            raise ValueError('invalid work topology')
        table[w.key]=w
    members={(i,n):k for i,n,k in plan.members}
    if len(members)!=len(plan.members): raise ValueError('duplicate member')
    expected=set(); outputs=[]; used=set()
    for i in intentions:
        live=_live(i)
        for n in i.nodes:
            if n.name not in live: continue
            label=(i.name,n.name); expected.add(label)
            if label not in members or any((i.name,d) not in members for d in n.deps):
                raise ValueError('missing live member')
            w=_work(n,bindings[n.binding],tuple(members[i.name,d] for d in n.deps))
            if members[label]!=w.key or table.get(w.key)!=w:
                raise ValueError('invalid member equivalence')
            used.add(w.key)
        outputs.extend((i.name,o,members[i.name,o]) for o in i.outputs)
    if set(members)!=expected or used!=set(table) or tuple(outputs)!=plan.outputs:
        raise ValueError('inexact coverage')
    return True


def execute(intentions,bindings,plan,bank=None):
    """Verify structure, realize each class once, then project original identities.

    Persist only classes shared by multiple live nodes. All distinct classes
    still receive an independent result check. No consumer commit is implied.
    """
    verify_plan(intentions,bindings,plan)
    counts={}
    for _,_,key in plan.members: counts[key]=counts.get(key,0)+1
    values={}; producers=checks=retained=0
    for w in plan.work:
        b=bindings[w.binding]
        parts=[w.payload,*(values[d] for d in w.deps)]
        if sum(4+len(p) for p in parts)>b.contract.max_input:
            raise ValueError('work input exceeds contract')
        source=_frame(parts)
        if bank is not None and counts[w.key]>1:
            before=(bank.produced,bank.checked)
            value=bank.resolve(b.contract,source,b.produce,b.verify)
            producers+=bank.produced-before[0]; checks+=bank.checked-before[1]
        else:
            value=b.produce(source); producers+=1; checks+=1
            if type(value) is not bytes or len(value)>b.contract.max_result or b.verify(source,value) is not True:
                raise ValueError('pure result verification refused')
        retained+=len(value)
        if retained>MAX_RESULT_BYTES: raise ValueError('aggregate result extent exceeded')
        values[w.key]=value
    return MappingProxyType({(i,n):values[k] for i,n,k in plan.members}), {'classes':len(plan.work),'producers':producers,'checks':checks}


def unpack_source(raw):
    """Decode a bounded framed source, retaining ordered positions exactly."""
    parts=[]; p=0
    while p<len(raw):
        if p+4>len(raw): raise ValueError('truncated frame')
        n=struct.unpack_from('!I',raw,p)[0]; p+=4
        if n>len(raw)-p: raise ValueError('truncated frame')
        parts.append(raw[p:p+n]); p+=n
    return tuple(parts)
