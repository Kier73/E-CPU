"""NCB-005: source-generated, reduced counterexamples to E-CPU admission.

Select an actual independently constructed NCP-002 packet rather than write
a new source trajectory. Mutate only representation-level integer coordinates
that a Python equality comparison can mistakenly treat as equal, and reduce
the resulting divergent witness by deleting irrelevant edits.

This is a narrow structural test generator, NOT a general-purpose fuzzer.
It never makes a received Ground into execution authority.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any

from test_constructed_controller_admission import _world


def canonical(value: dict[str,Any]) -> bytes:
    """Preserve exactly the NCP-002 ASCII JSON identity encoding."""
    return json.dumps(value,sort_keys=True,separators=(",",":"),
                      ensure_ascii=True,allow_nan=False).encode("ascii")


@dataclass(frozen=True)
class StateAliasEdit:
    """One altered NCP state-table cell; no source semantics are changed."""

    row: int
    factor: int
    original: int
    alias: bool|float

    def encode(self)->dict[str,Any]:
        """Describe a one-cell typed representation change, not just its value."""
        return {
            "path":["states",self.row,self.factor],
            "original_type":"int",
            "original":self.original,
            "alias_type":type(self.alias).__name__,
            "alias":self.alias,
        }


def apply_edits(base:dict[str,Any],edits:tuple[StateAliasEdit,...])->dict[str,Any]:
    """Recompute SHA so only independent semantic typing can reject the result."""
    packet=deepcopy(base)
    for edit in edits:
        if type(packet["states"][edit.row][edit.factor]) is not int:
            raise ValueError("mutation must affect a uniquely identified integer cell")
        if packet["states"][edit.row][edit.factor]!=edit.original:
            raise ValueError("edit source location mismatch")
        packet["states"][edit.row][edit.factor]=edit.alias
    packet["sha256"]=sha256(canonical({
        key:value for key,value in packet.items() if key!="sha256"
    })).hexdigest()
    return packet


def legacy_equality_would_accept(base:dict[str,Any],candidate:dict[str,Any])->bool:
    """Precisely model old Python value equality for the world.states comparison."""
    if any(candidate[key]!=base[key] for key in base if key not in ("states","sha256")):
        return False
    return candidate["states"]==base["states"]


def exact_type_oracle(candidate:dict[str,Any])->bool:
    """Independent representation invariant: ALL state indices are exact integers."""
    rows=candidate.get("states")
    return (type(rows) is list
            and all(type(row) is list
                    and all(type(x) is int for x in row)
                    for row in rows))


def generate_and_reduce_alias()->tuple[dict[str,Any],tuple[StateAliasEdit,...],dict[str,Any]]:
    """Discover and minimize a true value-equal but type-different source receipt.

    Start from three *disjoint* generated state-table cells. Remove edits as
    long as the old receiver equality would accept and the independent
    source-typing oracle would refuse. This is finite deletion minimization:
    the returned single edit cannot be reduced further without losing the
    discrepancy. No artificial input trace is supplied.
    """
    base=_world().packet()
    candidates=[]
    for i,row in enumerate(base["states"]):
        for factor,value in enumerate(row):
            if type(value) is int and value in (0,1):
                alias=bool(value) if len(candidates)%2==0 else float(value)
                candidates.append(StateAliasEdit(i,factor,value,alias))
            if len(candidates)==3:
                break
        if len(candidates)==3:
            break
    if len(candidates)!=3:
        raise AssertionError("constructed source yielded no typed alias candidates")
    chosen=tuple(candidates)
    def divergent(edits:tuple[StateAliasEdit,...])->bool:
        cand=apply_edits(base,edits)
        return legacy_equality_would_accept(base,cand) and not exact_type_oracle(cand)
    if not divergent(chosen):
        raise AssertionError("generated seed did not expose Python's typed-equality alias")
    cursor=0
    while cursor<len(chosen):
        subset=chosen[:cursor]+chosen[cursor+1:]
        if divergent(subset):
            chosen=subset
        else:
            cursor+=1
    if len(chosen)!=1 or divergent(()):
        raise AssertionError("counterexample is not deletion-minimal")
    return base,chosen,apply_edits(base,chosen)


def discover_native_input_alias(checked)->tuple[tuple[int,...],int,str]:
    """Find a certified state where factor 1 acts on integer local state 1."""
    for i,state in enumerate(checked.states):
        if checked.ranks[i]<1 or state[1]!=1:
            continue
        selected=checked.next_action(state)
        if selected.names[1]=="advance":
            return state,1,"advance"
    raise AssertionError("source-generated controller has no eligible factor-1 integer action")


def report_minimal_source_alias()->dict[str,Any]:
    """Emit a deterministic minimal counterexample for external CI review."""
    base,edits,changed=generate_and_reduce_alias()
    return {
        "schema":"mailcpu.ncb005.minimal-source-counterexample.v1",
        "base_controller_sha256":base["sha256"],
        "mutated_controller_sha256":changed["sha256"],
        "original_source_digest":sha256(canonical(base["source"])).hexdigest(),
        "seed_edits":3,
        "remaining_edits":len(edits),
        "irreducible_edit":edits[0].encode(),
        "old_value_equality":legacy_equality_would_accept(base,changed),
        "strict_source_type_oracle":exact_type_oracle(changed),
        "attack_scope":"untrusted packet state index; rehashed; no authority transported",
    }
