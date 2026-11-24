"""Durable mailbox-driven attention over exact committed session coordinates."""
from dataclasses import dataclass
from hashlib import sha256
import json
import re

from .attention import Budget, Offer, machine_scope, plan_attention
from .model import Message

_HEX = re.compile(r'[0-9a-f]{64}\Z')
_MAX_INPUT = 65536


def _digest(raw):
    """Identify exact canonical information."""
    return sha256(raw).hexdigest()


@dataclass(frozen=True)
class WakeEvent:
    """One receiver-admitted intention pinned to a native predecessor and contract."""
    namespace: str
    identity: int
    revision: int
    checkpoint: str
    contract: str
    payload: bytes
    demand: Budget

    def __post_init__(self):
        """Reject invalid coordinates, unbounded payloads and empty work."""
        if any(type(v) is not str or not _HEX.fullmatch(v) for v in (self.namespace,self.checkpoint,self.contract)):
            raise ValueError('invalid wake digest')
        if type(self.identity) is not int or not 0 <= self.identity < 2**24:
            raise ValueError('invalid wake identity')
        if type(self.revision) is not int or not 1 <= self.revision < 2**63:
            raise ValueError('invalid wake revision')
        if type(self.payload) is not bytes or len(self.payload)>_MAX_INPUT:
            raise ValueError('invalid wake input')
        if not isinstance(self.demand,Budget) or not any(self.demand.values()):
            raise ValueError('invalid wake demand')

    @property
    def session_id(self):
        """Resolve the canonical fabric session name."""
        return f'fab127.{self.namespace}.{self.identity:06x}'

    def canonical(self):
        """Encode the exact versioned wake intention."""
        return json.dumps([1,self.namespace,self.identity,self.revision,self.checkpoint,
                           self.contract,self.payload.hex(),self.demand.values()],
                          separators=(',',':'),allow_nan=False).encode('ascii')

    @property
    def event_id(self):
        """Derive stable operation identity from all intention fields."""
        return _digest(self.canonical())

    @classmethod
    def decode(cls, raw):
        """Reconstruct only exact canonical wire values."""
        if type(raw) is not bytes or len(raw)>2*_MAX_INPUT+1024:
            raise ValueError('invalid wake wire extent')
        try:
            row=json.loads(raw)
            if type(row) is not list or len(row)!=8 or type(row[0]) is not int or row[0]!=1:
                raise ValueError('invalid wake schema')
            if type(row[6]) is not str or type(row[7]) is not list or len(row[7])!=4:
                raise ValueError('invalid wake fields')
            event=cls(*row[1:6],bytes.fromhex(row[6]),Budget(*row[7]))
            if event.canonical()!=raw:
                raise ValueError('noncanonical wake')
            return event
        except (TypeError,ValueError,UnicodeError,RecursionError) as exc:
            raise ValueError('invalid wake record') from exc


class WakeController:
    """Single-owner bounded epochs over a receiver-controlled durable mailbox.

    The trusted resolver supplies (native session store, transition adapter).
    A deterministic follow-up function may form the next intent for that same
    machine from its exact successor. It must have no external side effects.
    A mailbox record is not capability or proof of native runnable state.
    """
    def __init__(self, namespace, mailbox, resolve, followup=None):
        """Bind one namespace, local mailbox owner and admitted resolver."""
        if type(namespace) is not str or not _HEX.fullmatch(namespace):
            raise ValueError('invalid wake namespace')
        self.namespace=namespace
        self.mailbox=mailbox
        self.resolve=resolve
        self.followup=followup
        self.addr='wake:'+namespace

    def publish(self,event):
        """Retain an exact admitted intention; duplicate publication is a no-op."""
        if not isinstance(event,WakeEvent) or event.namespace!=self.namespace:
            raise ValueError('foreign wake')
        return self.mailbox.send_once(self.addr,Message(sender=self.mailbox.node_id,
            op='fabric.wake.v1',addr=event.session_id,body=(event.canonical().decode('ascii'),)),
            operation_id='wake:'+event.event_id)

    def _decode(self,message):
        """Check route and local producer binding before interpreting a message."""
        if (message.sender!=self.mailbox.node_id or message.recipient!=self.addr
                or message.op!='fabric.wake.v1' or type(message.body) is not tuple
                or len(message.body)!=1 or type(message.body[0]) is not str):
            raise ValueError('invalid wake envelope')
        event=WakeEvent.decode(message.body[0].encode('ascii'))
        if event.namespace!=self.namespace or message.addr!=event.session_id:
            raise ValueError('wake route differs')
        return event

    @staticmethod
    def _eligible(event,head):
        """Classify exact predecessor or immediate retry; never rebase stale work."""
        return ((head.revision==event.revision and head.checkpoint_digest==event.checkpoint)
                or (head.revision==event.revision+1
                    and head.checkpoint.predecessor_checkpoint_digest==event.checkpoint
                    and head.checkpoint.operation_id==event.event_id))

    def run_epoch(self,capacity,*,epoch,service=None):
        """Select pending machine work, commit, publish deterministic child, then acknowledge.

        Inspect pending messages only, one FIFO event per machine. Stale events
        stay pending for explicit receiver reconciliation. No fleet polling.
        Single owner must prevent unrelated writers between commit and ack.
        """
        candidates={}; seen=set(); stale=[]; offers=[]
        messages=self.mailbox.list(self.addr)
        for message in messages:
            event=self._decode(message)
            if event.identity in seen: continue
            seen.add(event.identity)
            store,adapter=self.resolve(event.identity)
            if store.session_id!=event.session_id or adapter.session_store is not store or adapter.contract.digest!=event.contract:
                raise ValueError('wake resolver scope or contract differs')
            head=store.observe_head()
            if not self._eligible(event,head):
                stale.append(event.event_id); continue
            scope=machine_scope(event.identity)
            evidence=_digest((event.event_id+head.checkpoint_digest).encode('ascii'))
            offer=Offer(scope,head.revision,evidence,event.demand)
            candidates[scope]=(message,event,store,adapter)
            offers.append(offer)
        plan=plan_attention(offers,capacity,epoch=epoch,service=service)
        completed=[]
        for grant in plan.grants:
            message,event,store,adapter=candidates[grant.scope]
            head=store.observe_head()
            if (not self._eligible(event,head) or head.revision!=grant.revision
                    or _digest((event.event_id+head.checkpoint_digest).encode('ascii'))!=grant.evidence):
                stale.append(event.event_id); continue
            result=adapter.apply(event.payload,operation_id=event.event_id,
                expected_revision=event.revision,expected_checkpoint_digest=event.checkpoint)
            if (result.revision!=event.revision+1 or result.checkpoint.operation_id!=event.event_id
                    or result.checkpoint.predecessor_checkpoint_digest!=event.checkpoint):
                raise ValueError('wake successor differs')
            if self.followup is not None:
                child=self.followup(event,result)
                if child is not None:
                    if (not isinstance(child,WakeEvent) or child.namespace!=self.namespace
                            or child.identity!=event.identity or child.revision!=result.revision
                            or child.checkpoint!=result.checkpoint_digest or child.contract!=event.contract):
                        raise ValueError('follow-up must name the exact same-machine successor')
                    self.publish(child)
            if not self.mailbox.consume(message,operation_id='ack:'+event.event_id):
                raise ValueError('wake acknowledgement lost ownership')
            completed.append((event.event_id,result.checkpoint_digest,result.replayed))
        return {'pending_at_observation':len(messages),'observed_machines':len(seen),
                'selected':len(plan.grants),'completed':tuple(completed),'stale':tuple(stale)}
