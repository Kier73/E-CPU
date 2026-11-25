"""Canonical 127/8 machine naming; recovery and authority stay in native M3."""
from dataclasses import dataclass
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .computational_session import ComputationalSessionStore
    from .continuous_session import SessionRejoinAddress

MACHINE_COUNT = 1 << 24
_PREFIX = 0x7f000000
_NAMESPACE = re.compile(r"[0-9a-f]{64}\Z")
_SESSION = re.compile(r"fab127\.([0-9a-f]{64})\.([0-9a-f]{6})\Z")


def pack_ipv4(identity: int) -> int:
    """Map every 24-bit machine coordinate to one unsigned IPv4 integer."""
    if type(identity) is not int or not 0 <= identity < MACHINE_COUNT:
        raise ValueError("invalid 24-bit machine identity")
    return _PREFIX | identity


def unpack_ipv4(address: int) -> int:
    """Invert the exact 127/8 mapping, refusing non-fabric addresses."""
    if type(address) is not int or address >> 24 != 127:
        raise ValueError("not a 127/8 address")
    return address & (MACHINE_COUNT - 1)


@dataclass(frozen=True, slots=True)
class FabricMachineAddress:
    """A potential machine in a locally selected fabric namespace, not authority."""
    namespace: str
    identity: int

    def __post_init__(self) -> None:
        """Validate the exact fabric namespace and coordinate."""
        if type(self.namespace) is not str or not _NAMESPACE.fullmatch(self.namespace):
            raise ValueError("invalid fabric namespace digest")
        pack_ipv4(self.identity)

    @property
    def ipv4(self) -> str:
        """Return canonical decimal loopback address without resolving any host."""
        value = pack_ipv4(self.identity)
        return ".".join(str((value >> shift) & 255) for shift in (24, 16, 8, 0))

    @property
    def session_id(self) -> str:
        """Stable injective M3 name, independent of host, port, revision or program."""
        return f"fab127.{self.namespace}.{self.identity:06x}"

    @classmethod
    def from_session_id(cls, session_id: str) -> "FabricMachineAddress":
        """Decode a canonical native M3 session identifier, refusing aliases."""
        match = _SESSION.fullmatch(session_id) if type(session_id) is str else None
        if match is None:
            raise ValueError("invalid fabric session identity")
        return cls(match[1], int(match[2], 16))

    @classmethod
    def from_ipv4(cls, namespace: str, address: str) -> "FabricMachineAddress":
        """Decode canonical dotted decimal, including both ends of 127/8."""
        if type(address) is not str or len(address) > 15:
            raise ValueError("invalid IPv4 address")
        parts = address.split(".")
        if len(parts) != 4 or any(not p.isascii() or not p.isdecimal() or len(p)>3 for p in parts):
            raise ValueError("invalid IPv4 address")
        nums = tuple(int(p) for p in parts)
        if any(n>255 or str(n)!=p for n,p in zip(nums,parts)):
            raise ValueError("noncanonical IPv4 address")
        value = sum(n << shift for n,shift in zip(nums,(24,16,8,0)))
        return cls(namespace, unpack_ipv4(value))

    def bind_session(self, store: "ComputationalSessionStore", expected: "SessionRejoinAddress") -> "SessionRejoinAddress":
        """Check locally trusted rejoin scope and native quorum state before attachment.

        A caller must obtain expected from its trusted admission registry, never
        from an untrusted packet. This method grants no execution permissions.
        """
        from .computational_session import ComputationalSessionStore
        from .continuous_session import SessionRejoinAddress
        if not isinstance(store, ComputationalSessionStore) or not isinstance(expected, SessionRejoinAddress):
            raise TypeError("native store and trusted rejoin address required")
        if expected.session_id != self.session_id or store.session_id != self.session_id:
            raise ValueError("machine and session identity differ")
        actual = SessionRejoinAddress.bootstrap(store)
        if actual != expected:
            raise ValueError("machine session admission scope differs")
        return actual
