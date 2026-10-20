"""DNS TTL decaying capacitor memory cells and `/dev/dns_latch` device driver."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Sequence


@dataclass
class DnsRecord:
    r"""Mathematics: cached record state `\langle \text{domain}, \text{type}, \text{val}, t_0, \text{TTL}_0, \text{neg} \rangle` with linear TTL decay `\text{TTL}(t) = \max(0, \text{TTL}_0 - (t - t_0))`."""

    domain: str
    record_type: str
    value: str
    inserted_at: float
    original_ttl: int
    is_negative: bool = False

    def remaining_ttl(self, now: float | None = None) -> int:
        r"""Mathematics: evaluate remaining TTL `\max(0, \text{TTL}_0 - \lfloor t - t_0 \rfloor)`."""

        current_time = time.monotonic() if now is None else now
        elapsed = current_time - self.inserted_at
        return max(0, int(self.original_ttl - elapsed))

    def is_alive(self, now: float | None = None) -> bool:
        r"""Mathematics: evaluate predicate `\text{remaining\_ttl}(t) > 0`."""

        return self.remaining_ttl(now) > 0


class DnsResolverSim:
    """Mathematics: recursive DNS resolver simulation with positive caching and RFC 2308 negative caching (`NXDOMAIN`)."""

    def __init__(self, server_ip: str = "8.8.8.8", canary_ips: Sequence[str] = ("1.1.1.1", "9.9.9.9")) -> None:
        r"""Mathematics: initialize resolver cache table `C : \text{domain} \times \text{type} \rightharpoonup \text{Record}`."""

        self.server_ip = server_ip
        self.canary_ips = list(canary_ips)
        self.cache: dict[tuple[str, str], DnsRecord] = {}

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

        current_time = time.monotonic() if now is None else now
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

        current_time = time.monotonic() if now is None else now
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
        r"""Mathematics: evaluate quorum presence `\bigvee_{s \in \text{Resolvers}} \text{is\_alive}(s, domain)` across canary paths."""

        res = self.query(domain, recursion_desired=False, now=now)
        return bool(res.get("hit", False))


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
        """Mathematics: serialize driver state and latch mappings for checkpoint restoration."""

        return {
            "kind": "dns_latch",
            "latches": dict(self.latches),
            "cache": {
                f"{domain}:{rtype}": {
                    "domain": record.domain,
                    "record_type": record.record_type,
                    "value": record.value,
                    "inserted_at": record.inserted_at,
                    "original_ttl": record.original_ttl,
                    "is_negative": record.is_negative,
                }
                for (domain, rtype), record in self.resolver.cache.items()
            },
        }

    @classmethod
    def from_snapshot(cls, payload: dict[str, Any]) -> DnsLatchDevice:
        """Mathematics: reconstruct `DnsLatchDevice` from checkpoint record."""

        resolver = DnsResolverSim()
        raw_cache = payload.get("cache", {})
        for item in raw_cache.values():
            rec = DnsRecord(
                domain=str(item["domain"]),
                record_type=str(item["record_type"]),
                value=str(item["value"]),
                inserted_at=float(item["inserted_at"]),
                original_ttl=int(item["original_ttl"]),
                is_negative=bool(item.get("is_negative", False)),
            )
            resolver.cache[(rec.domain, rec.record_type)] = rec
        device = cls(resolver=resolver)
        device.latches = {str(k): int(v) for k, v in payload.get("latches", {}).items()}
        return device
