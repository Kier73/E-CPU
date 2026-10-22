"""DNS TTL decaying capacitor memory cells and `/dev/dns_latch` device driver."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any, Protocol, Sequence


class ResolverClock(Protocol):
    """Clock boundary for resolver TTL evaluation."""

    def now(self) -> float:
        """Mathematics: return the current resolver time `t∈R_{≥0}` used by TTL decay."""

        ...


class MonotonicClock:
    """Production clock backed by the host monotonic time source."""

    def now(self) -> float:
        """Mathematics: return `t := time.monotonic()`, a non-wall-clock time suitable for elapsed-duration subtraction."""

        return time.monotonic()


class LogicalClock:
    """Deterministic nondecreasing resolver clock for composition and checkpoints."""

    def __init__(self, initial: float = 0.0) -> None:
        """Mathematics: initialize logical time `t:=initial` with `t∈R_{≥0}`."""

        self._value = self._validate_time(initial)

    def now(self) -> float:
        """Mathematics: project the current logical coordinate `t` without changing state."""

        return self._value

    def advance(self, delta: float) -> float:
        """Mathematics: apply monotone transition `t' := t + Δ` for finite `Δ∈R_{≥0}` and return `t'`."""

        increment = self._validate_time(delta)
        self._value += increment
        return self._value

    def set(self, value: float) -> float:
        """Mathematics: apply only the order-preserving transition `t':=value` when `value≥t`."""

        candidate = self._validate_time(value)
        if candidate < self._value:
            raise ValueError("logical resolver clock cannot move backwards")
        self._value = candidate
        return self._value

    def snapshot(self) -> dict[str, Any]:
        """Mathematics: serialize the complete logical clock state `t` for exact restart continuation."""

        return {"kind": "logical", "value": self._value}

    @classmethod
    def from_snapshot(cls, payload: dict[str, Any]) -> "LogicalClock":
        """Mathematics: reconstruct the unique logical clock whose coordinate equals serialized `t`."""

        if payload.get("kind") != "logical":
            raise ValueError("logical resolver clock snapshot kind mismatch")
        return cls(float(payload["value"]))

    @staticmethod
    def _validate_time(value: float) -> float:
        """Mathematics: admit exactly the finite nonnegative domain `R_{≥0}∩R_finite`."""

        candidate = float(value)
        if not math.isfinite(candidate) or candidate < 0:
            raise ValueError("resolver clock time must be finite and non-negative")
        return candidate


def _clock_snapshot(clock: ResolverClock) -> dict[str, Any]:
    """Mathematics: encode only checkpointable clock states in the disjoint sum `Clock = Monotonic + Logical`."""

    if isinstance(clock, LogicalClock):
        return clock.snapshot()
    if isinstance(clock, MonotonicClock):
        return {"kind": "monotonic"}
    raise ValueError("resolver clock is not checkpointable")


def _clock_from_snapshot(payload: dict[str, Any]) -> ResolverClock:
    """Mathematics: decode the clock coproduct by its unique `kind` tag, refusing unknown state."""

    kind = payload.get("kind")
    if kind == "logical":
        return LogicalClock.from_snapshot(payload)
    if kind == "monotonic":
        return MonotonicClock()
    raise ValueError("unknown resolver clock snapshot kind")


@dataclass
class DnsRecord:
    r"""Mathematics: cached record state `\langle \text{domain}, \text{type}, \text{val}, t_0, \text{TTL}_0, \text{neg} \rangle` with linear TTL decay `\text{TTL}(t) = \max(0, \text{TTL}_0 - (t - t_0))`."""

    domain: str
    record_type: str
    value: str
    inserted_at: float
    original_ttl: int
    is_negative: bool = False

    def __post_init__(self) -> None:
        """Mathematics: admit `original_ttl∈Z_{≥0}` and finite insertion coordinate `inserted_at∈R` only."""

        if isinstance(self.original_ttl, bool) or not isinstance(self.original_ttl, int) or self.original_ttl < 0:
            raise ValueError("DNS TTL must be non-negative")
        if not math.isfinite(float(self.inserted_at)):
            raise ValueError("DNS insertion time must be finite")
        if not isinstance(self.is_negative, bool):
            raise ValueError("DNS negative-cache flag must be boolean")

    def remaining_ttl(self, now: float | None = None) -> int:
        r"""Mathematics: evaluate `TTL_remaining(t) = max(0, TTL0 - floor(max(0, t - t0)))`."""

        current_time = time.monotonic() if now is None else float(now)
        if not math.isfinite(current_time):
            raise ValueError("DNS query time must be finite")
        elapsed = max(0.0, current_time - self.inserted_at)
        return max(0, self.original_ttl - math.floor(elapsed))

    def is_alive(self, now: float | None = None) -> bool:
        r"""Mathematics: evaluate predicate `\text{remaining\_ttl}(t) > 0`."""

        return self.remaining_ttl(now) > 0


class DnsResolverSim:
    """Mathematics: recursive DNS resolver simulation with positive caching and RFC 2308 negative caching (`NXDOMAIN`)."""

    def __init__(
        self,
        server_ip: str = "8.8.8.8",
        canary_ips: Sequence[str] = ("1.1.1.1", "9.9.9.9"),
        canary_resolvers: Sequence["DnsResolverSim"] = (),
        clock: ResolverClock | None = None,
    ) -> None:
        r"""Mathematics: initialize `(C,T)` where `C : domain×type ⇀ Record` and `T.now()` supplies resolver time."""

        self.server_ip = server_ip
        self.canary_ips = list(canary_ips)
        self.canary_resolvers = tuple(canary_resolvers)
        self.clock = MonotonicClock() if clock is None else clock
        self.cache: dict[tuple[str, str], DnsRecord] = {}

    def now(self) -> float:
        """Mathematics: project resolver time `t:=T.now()` and require a finite nonnegative coordinate."""

        current_time = float(self.clock.now())
        if not math.isfinite(current_time) or current_time < 0:
            raise ValueError("resolver clock must return finite non-negative time")
        return current_time

    def insert_record(
        self,
        domain: str,
        record_type: str,
        value: str,
        ttl: int,
        is_negative: bool = False,
        now: float | None = None,
    ) -> None:
        r"""Mathematics: assign `C[(domain, type)] := \langle domain, type, value, now, ttl, is\_negative \rangle`."""

        current_time = self.now() if now is None else LogicalClock._validate_time(now)
        self.cache[(domain, record_type)] = DnsRecord(
            domain=domain,
            record_type=record_type,
            value=value,
            inserted_at=current_time,
            original_ttl=ttl,
            is_negative=is_negative,
        )

    def query(
        self,
        domain: str,
        record_type: str = "A",
        recursion_desired: bool = True,
        now: float | None = None,
    ) -> dict[str, Any]:
        """Mathematics: query cache table; if `RD=0` and record is absent or expired, return cache miss."""

        current_time = self.now() if now is None else LogicalClock._validate_time(now)
        record = self.cache.get((domain, record_type))
        if record is not None and record.is_alive(current_time):
            return {
                "status": "NXDOMAIN" if record.is_negative else "NOERROR",
                "hit": True,
                "ttl": record.remaining_ttl(current_time),
                "value": record.value,
                "rtt_ms": 1.2,  # cache hit RTT
            }

        if not recursion_desired:
            return {"status": "REFUSED", "hit": False, "ttl": 0, "rtt_ms": 35.0}

        # Simulated authoritative upstream fetch
        default_ttl = 300
        self.insert_record(domain, record_type, "192.0.2.1", default_ttl, now=current_time)
        return {
            "status": "NOERROR",
            "hit": False,
            "ttl": default_ttl,
            "value": "192.0.2.1",
            "rtt_ms": 42.5,  # recursive fetch RTT
        }

    def multi_resolver_canary_poll(self, domain: str, now: float | None = None) -> bool:
        r"""Mathematics: evaluate `\bigvee_{r \in \{self\} \cup peers} hit_r(domain)` over explicitly supplied independent resolver states."""

        resolvers = (self,) + self.canary_resolvers
        return any(
            bool(resolver.query(domain, recursion_desired=False, now=now).get("hit", False))
            for resolver in resolvers
        )


class DnsLatchDevice:
    r"""Mathematics: character device `/dev/dns_latch` exposing decaying TTL capacitor bits to user space."""

    def __init__(self, resolver: DnsResolverSim | None = None) -> None:
        """Mathematics: initialize `/dev/dns_latch` device driver bound to resolver instance."""

        self.resolver = resolver or DnsResolverSim()
        self.latches: dict[str, int] = {}  # domain -> bit (0 or 1)

    def write(self, data: bytes) -> int:
        r"""Mathematics: parse commands line-by-line: `SET <domain> <bit> <ttl>` or `LATCH <domain>`, updating resolver presence bits."""

        lines = data.decode("utf-8", errors="replace").splitlines()
        for line in lines:
            parts = line.strip().split()
            if not parts:
                continue

            cmd = parts[0].upper()
            if cmd == "SET" and len(parts) >= 3:
                domain = parts[1]
                bit = int(parts[2])
                ttl = int(parts[3]) if len(parts) >= 4 else 60
                if bit not in (0, 1):
                    raise ValueError("DNS latch bit must be 0 or 1")
                if ttl < 0:
                    raise ValueError("DNS latch TTL must be non-negative")
                self.latches[domain] = bit
                is_neg = bit == 0
                self.resolver.insert_record(domain, "A", "192.0.2.1", ttl, is_negative=is_neg)
            elif cmd == "LATCH" and len(parts) >= 2:
                domain = parts[1]
                self.resolver.query(domain, recursion_desired=True)
                self.latches[domain] = 1

        return len(data)

    def read(self, size: int = -1) -> bytes:
        r"""Mathematics: emit ASCII binary string of active latch values `b_i \in \{0, 1\}`."""

        output: list[str] = []
        for domain, bit in sorted(self.latches.items()):
            res = self.resolver.query(domain, recursion_desired=False)
            status_bit = bit if res.get("hit") else 0
            output.append(f"{domain}={status_bit}")

        result_bytes = ("\n".join(output) + "\n").encode("utf-8")
        if size < 0 or size >= len(result_bytes):
            return result_bytes
        return result_bytes[:size]

    def snapshot(self) -> dict[str, Any]:
        """Mathematics: serialize latch state and cache projection `r_s=TTL_remaining(t_s)` for checkpoint restoration."""

        snapshot_time = self.resolver.now()
        return {
            "kind": "dns_latch",
            "server_ip": self.resolver.server_ip,
            "canary_ips": list(self.resolver.canary_ips),
            "canary_resolver_count": len(self.resolver.canary_resolvers),
            "clock": _clock_snapshot(self.resolver.clock),
            "latches": dict(self.latches),
            "cache": {
                f"{domain}:{rtype}": {
                    "domain": record.domain,
                    "record_type": record.record_type,
                    "value": record.value,
                    "inserted_at": record.inserted_at,
                    "original_ttl": record.original_ttl,
                    "remaining_ttl": record.remaining_ttl(snapshot_time),
                    "is_negative": record.is_negative,
                }
                for (domain, rtype), record in self.resolver.cache.items()
            },
        }

    @classmethod
    def from_snapshot(
        cls,
        payload: dict[str, Any],
        clock: ResolverClock | None = None,
        canary_resolvers: Sequence[DnsResolverSim] = (),
    ) -> "DnsLatchDevice":
        """Mathematics: reconstruct `DnsLatchDevice` by restoring `r_s` at `t_r` and requiring explicit external canary dependencies."""

        if not isinstance(payload, dict) or payload.get("kind") not in (None, "dns_latch"):
            raise ValueError("invalid DNS latch snapshot")
        supplied_canaries = tuple(canary_resolvers)
        expected_canaries = int(payload.get("canary_resolver_count", 0))
        if expected_canaries < 0 or len(supplied_canaries) != expected_canaries:
            raise ValueError("DNS latch snapshot requires its explicit canary resolvers")
        resolver_clock = clock if clock is not None else _clock_from_snapshot(dict(payload.get("clock", {"kind": "monotonic"})))
        resolver = DnsResolverSim(
            server_ip=str(payload.get("server_ip", "8.8.8.8")),
            canary_ips=tuple(str(item) for item in payload.get("canary_ips", ("1.1.1.1", "9.9.9.9"))),
            canary_resolvers=supplied_canaries,
            clock=resolver_clock,
        )
        restore_time = resolver.now()
        raw_cache = payload.get("cache", {})
        if not isinstance(raw_cache, dict):
            raise ValueError("DNS latch cache must be a mapping")
        for item in raw_cache.values():
            if not isinstance(item, dict):
                raise ValueError("DNS latch cache record must be a mapping")
            domain = str(item["domain"])
            record_type = str(item["record_type"])
            if not domain or not record_type:
                raise ValueError("DNS latch cache identity must be non-empty")
            if "remaining_ttl" in item:
                inserted_at = restore_time
                original_ttl = int(item["remaining_ttl"])
            else:
                inserted_at = float(item["inserted_at"])
                original_ttl = int(item["original_ttl"])
            rec = DnsRecord(
                domain=domain,
                record_type=record_type,
                value=str(item["value"]),
                inserted_at=inserted_at,
                original_ttl=original_ttl,
                is_negative=bool(item.get("is_negative", False)),
            )
            if (rec.domain, rec.record_type) in resolver.cache:
                raise ValueError("duplicate DNS latch cache identity")
            resolver.cache[(rec.domain, rec.record_type)] = rec
        device = cls(resolver=resolver)
        latches: dict[str, int] = {}
        raw_latches = payload.get("latches", {})
        if not isinstance(raw_latches, dict):
            raise ValueError("DNS latch mappings must be a mapping")
        for key, value in raw_latches.items():
            bit = int(value)
            if bit not in (0, 1) or isinstance(value, bool):
                raise ValueError("DNS latch snapshot bit must be 0 or 1")
            domain = str(key)
            if not domain or not any(record.domain == domain for record in resolver.cache.values()):
                raise ValueError("DNS latch must reference a cached domain")
            latches[domain] = bit
        device.latches = latches
        return device
