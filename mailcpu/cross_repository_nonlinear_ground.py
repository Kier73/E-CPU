"""WIRE-001: import proof-qualified NCR-007 computational structure into E-CPU.

The external repository publishes a strict portable mathematical packet, not
an executable capability. This bounded bridge checks its exact receiver pin,
invokes NCR-007's independent source/ground/result verification, and derives
an E-CPU finite source law from the actual nonlinear Boolean operators. Only
a separately admitted E-CPU substrate path may execute the formed processor.

The Python dependency is optional and loaded inside the guarded import. It
must be installed from a receiver-pinned source revision, not from untrusted
packet instructions. Passive carriers do not become computational hosts.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256 as _sha256
import re

from .intention_formed_fabric import FiniteObserverLaw
from .substrate_bootstrap import BootstrapRefused, sha

_SCHEMA = "mailcpu.cross-repository-nonlinear-source.v1"
_COMMIT = re.compile(r"[0-9a-f]{40}\Z")


@dataclass(frozen=True)
class VerifiedForeignFiniteGround:
    """A finite local view of an independently decoded NCR-007 law packet."""

    source_commit: str
    packet_sha256: str
    packet_bytes: int
    foreign_law_sha256: str
    foreign_ground_sha256: str
    foreign_result_sha256: str | None
    fields: tuple[str, ...]
    source: FiniteObserverLaw

    @property
    def source_fingerprint(self) -> str:
        """Mathematics: identify source semantics, not current host or wire."""
        return self.source.fingerprint


def admit_ncr007_finite_packet(
    raw: bytes, *, receiver_expected_sha256: str, source_commit: str,
) -> VerifiedForeignFiniteGround:
    """Mathematics: requalify a source-pinned nonlinear packet and construct an exact finite Moore view.

    The upstream verifier proves the finite Boolean polynomial law and the
    source-observer Koopman equations over all 2**width states, without a
    trust decision delegated to the packet. This adapter enumerates at most
    64 source states solely as an independent E-CPU execution substrate for
    INTENT-001; it is not NCR-007's source-law construction algorithm.
    """
    sha(receiver_expected_sha256, "receiver-pinned foreign packet")
    if type(source_commit) is not str or _COMMIT.fullmatch(source_commit) is None:
        raise BootstrapRefused("foreign source must be an exact 40-hex commit pin")
    if type(raw) is not bytes or not 0 < len(raw) <= 65_535:
        raise BootstrapRefused("foreign mathematical packet exceeds bounded carrier envelope")
    observed = _sha256(raw).hexdigest()
    if observed != receiver_expected_sha256:
        raise BootstrapRefused("foreign packet differs from receiver's expected bytes")
    try:
        from navigable_compute.nonlinear_koopman_wire import decode_nonlinear
    except ImportError as exc:
        raise BootstrapRefused("receiver has no pinned NCR-007 mathematical verifier") from exc
    try:
        family, ground, result = decode_nonlinear(raw)
    except (ValueError, TypeError, OverflowError) as exc:
        raise BootstrapRefused("NCR-007 source/ground/result mathematical audit refused") from exc
    width = family.description.width
    if not 2 <= width <= 6 or len(family.operators) > 8 or \
       not 1 <= len(family.description.observers) <= 8:
        raise BootstrapRefused("foreign source cannot fit the finite E-CPU observer envelope")
    states = tuple(f"s{i}" for i in range(1 << width))
    actions = tuple(f"a{i}" for i in range(len(family.operators)))
    fields = tuple(f"observer{i}" for i in range(len(family.description.observers)))
    transitions = tuple(
        tuple(operator.apply(state) for operator in family.operators)
        for state in range(1 << width)
    )
    observations = tuple(
        tuple((family.project_observer(state) >> bit) & 1 for bit in range(len(fields)))
        for state in range(1 << width)
    )
    source = FiniteObserverLaw(states, actions, fields, transitions, observations)
    return VerifiedForeignFiniteGround(
        source_commit, observed, len(raw), family.digest, ground.digest,
        result.digest if result is not None else None, fields, source,
    )
