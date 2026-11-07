"""Validated host/failure-domain topology for distributed recovery-lineage authorities."""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from .seed_commit_quorum import SeedCommitLedgerError, SeedCommitMembership

_SCHEMA_VERSION = 1
_MEMBER_FIELDS = frozenset(
    {
        "member_id",
        "role",
        "dns_name",
        "host_id",
        "failure_domain",
        "endpoint_host",
        "port",
        "journal_path",
        "certificate_path",
        "private_key_path",
        "trust_bundle_path",
    }
)


class RecoveryLineageDeploymentError(ValueError):
    """A recovery-lineage deployment topology is incomplete, ambiguous, or unsafe."""


def _text(value: Any, field: str) -> str:
    """Mathematics: restrict a deployment label to the non-empty trimmed string domain without NUL."""

    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or "\x00" in value
    ):
        raise RecoveryLineageDeploymentError(f"{field} must be non-empty trimmed text")
    return value


def _dns_name(value: Any, field: str) -> str:
    """Mathematics: admit only lowercase, non-wildcard DNS names whose labels satisfy the 1..63 octet bound."""

    name = _text(value, field)
    if name != name.lower() or name.endswith(".") or len(name) > 253:
        raise RecoveryLineageDeploymentError(f"{field} must be a lowercase absolute DNS name")
    labels = name.split(".")
    if len(labels) < 2 or any(
        not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
        for label in labels
    ):
        raise RecoveryLineageDeploymentError(f"{field} must be a valid multi-label DNS name")
    return name


def _endpoint_host(value: Any, field: str) -> str:
    """Mathematics: normalize an endpoint to either a canonical IP address or a validated DNS name."""

    host = _text(value, field)
    try:
        return ipaddress.ip_address(host).compressed.lower()
    except ValueError:
        return _dns_name(host, field)


def _absolute_path(value: Any, field: str) -> str:
    """Mathematics: admit a node-local path iff it is absolute in POSIX or Windows syntax and has no parent traversal."""

    path = _text(value, field)
    posix = PurePosixPath(path)
    windows = PureWindowsPath(path)
    if not (posix.is_absolute() or windows.is_absolute()):
        raise RecoveryLineageDeploymentError(f"{field} must be an absolute node-local path")
    if ".." in posix.parts or ".." in windows.parts:
        raise RecoveryLineageDeploymentError(f"{field} must not contain parent traversal")
    return path


@dataclass(frozen=True)
class RecoveryLineageDeploymentMember:
    """One logical authority bound to one declared host, failure domain, journal, and TLS identity."""

    member_id: str
    role: str
    dns_name: str
    host_id: str
    failure_domain: str
    endpoint_host: str | None
    port: int | None
    journal_path: str
    certificate_path: str
    private_key_path: str
    trust_bundle_path: str

    def __post_init__(self) -> None:
        """Mathematics: enforce role-specific endpoint shape and a one-to-one mapping from identity to persistent host resources."""

        _text(self.member_id, "member id")
        if self.role not in {"owner", "authority"}:
            raise RecoveryLineageDeploymentError("member role must be 'owner' or 'authority'")
        _dns_name(self.dns_name, "TLS DNS identity")
        host_id = _text(self.host_id, "host id")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", host_id):
            raise RecoveryLineageDeploymentError("host id contains unsupported characters")
        _text(self.failure_domain, "failure domain")
        _absolute_path(self.journal_path, "journal path")
        _absolute_path(self.certificate_path, "certificate path")
        _absolute_path(self.private_key_path, "private key path")
        _absolute_path(self.trust_bundle_path, "trust bundle path")
        resource_paths = {
            self.journal_path.casefold(),
            self.certificate_path.casefold(),
            self.private_key_path.casefold(),
            self.trust_bundle_path.casefold(),
        }
        if len(resource_paths) != 4:
            raise RecoveryLineageDeploymentError("journal and TLS resource paths must be distinct per member")
        if self.role == "owner":
            if self.endpoint_host is not None or self.port is not None:
                raise RecoveryLineageDeploymentError("owner member must not declare an authority service endpoint")
        else:
            if self.endpoint_host is None:
                raise RecoveryLineageDeploymentError("authority member requires an endpoint host")
            _endpoint_host(self.endpoint_host, "authority endpoint host")
            if (
                not isinstance(self.port, int)
                or isinstance(self.port, bool)
                or not 1 <= self.port <= 65535
            ):
                raise RecoveryLineageDeploymentError("authority port must be an integer from 1 through 65535")

    def snapshot(self) -> dict[str, object]:
        """Mathematics: project the member identity tuple into its exact schema-v1 JSON record."""

        return {
            "member_id": self.member_id,
            "role": self.role,
            "dns_name": self.dns_name,
            "host_id": self.host_id,
            "failure_domain": self.failure_domain,
            "endpoint_host": self.endpoint_host,
            "port": self.port,
            "journal_path": self.journal_path,
            "certificate_path": self.certificate_path,
            "private_key_path": self.private_key_path,
            "trust_bundle_path": self.trust_bundle_path,
        }

    @classmethod
    def from_snapshot(cls, payload: Mapping[str, Any]) -> "RecoveryLineageDeploymentMember":
        """Mathematics: reconstruct a member iff its field domain equals the schema-v1 member field set."""

        if not isinstance(payload, Mapping) or set(payload) != _MEMBER_FIELDS:
            raise RecoveryLineageDeploymentError("deployment member fields are malformed")
        try:
            return cls(
                payload["member_id"],
                payload["role"],
                payload["dns_name"],
                payload["host_id"],
                payload["failure_domain"],
                payload["endpoint_host"],
                payload["port"],
                payload["journal_path"],
                payload["certificate_path"],
                payload["private_key_path"],
                payload["trust_bundle_path"],
            )
        except (KeyError, TypeError) as exc:
            raise RecoveryLineageDeploymentError("deployment member fields are invalid") from exc


@dataclass(frozen=True)
class RecoveryLineageDeployment:
    """A fixed-membership deployment plan with an explicit distinct-host quorum topology."""

    membership: SeedCommitMembership
    members: tuple[RecoveryLineageDeploymentMember, ...]

    def __post_init__(self) -> None:
        """Mathematics: require at least three members, exact membership coverage, and injective host, DNS, and failure-domain coordinates."""

        if not isinstance(self.membership, SeedCommitMembership):
            raise RecoveryLineageDeploymentError("deployment requires a validated fixed membership")
        if not isinstance(self.members, (list, tuple)):
            raise RecoveryLineageDeploymentError("deployment members must be a finite sequence")
        members = tuple(self.members)
        if len(members) < 3:
            raise RecoveryLineageDeploymentError("multi-host recovery topology requires at least three members")
        if any(not isinstance(member, RecoveryLineageDeploymentMember) for member in members):
            raise RecoveryLineageDeploymentError("deployment members must be typed member records")
        member_ids = tuple(member.member_id for member in members)
        if len(set(member_ids)) != len(member_ids):
            raise RecoveryLineageDeploymentError("deployment member ids must be unique")
        if set(member_ids) != set(self.membership.member_ids):
            raise RecoveryLineageDeploymentError("deployment members must cover the fixed membership exactly")
        for member in members:
            expected_role = "owner" if member.member_id == self.membership.owner_id else "authority"
            if member.role != expected_role:
                raise RecoveryLineageDeploymentError(
                    f"member {member.member_id!r} must have role {expected_role!r}"
                )
        for field, values in (
            ("host id", [member.host_id.casefold() for member in members]),
            ("failure domain", [member.failure_domain.casefold() for member in members]),
            ("TLS DNS identity", [member.dns_name for member in members]),
        ):
            if len(set(values)) != len(values):
                raise RecoveryLineageDeploymentError(f"each member must have a unique {field}")
        endpoints = [
            _endpoint_host(member.endpoint_host, "authority endpoint host")
            for member in members
            if member.role == "authority"
        ]
        if len(set(endpoints)) != len(endpoints):
            raise RecoveryLineageDeploymentError("each authority must have a distinct endpoint host")
        object.__setattr__(
            self,
            "members",
            tuple(sorted(members, key=lambda member: member.member_id)),
        )

    def snapshot(self) -> dict[str, object]:
        """Mathematics: serialize the canonical pair of fixed membership and sorted host-bound member records."""

        return {
            "schema_version": _SCHEMA_VERSION,
            "membership": self.membership.snapshot(),
            "members": [member.snapshot() for member in self.members],
        }

    @property
    def digest(self) -> str:
        """Mathematics: identify a deployment plan by SHA-256 of its canonical schema-v1 JSON projection."""

        canonical = json.dumps(
            self.snapshot(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    @classmethod
    def from_snapshot(cls, payload: Mapping[str, Any]) -> "RecoveryLineageDeployment":
        """Mathematics: invert the topology projection only for exact fields and a validated fixed-membership snapshot."""

        if not isinstance(payload, Mapping) or set(payload) != {
            "schema_version",
            "membership",
            "members",
        }:
            raise RecoveryLineageDeploymentError("deployment snapshot fields are malformed")
        if payload.get("schema_version") != _SCHEMA_VERSION or isinstance(
            payload.get("schema_version"), bool
        ):
            raise RecoveryLineageDeploymentError("unsupported deployment schema version")
        raw_members = payload.get("members")
        if not isinstance(raw_members, (list, tuple)):
            raise RecoveryLineageDeploymentError("deployment member list is malformed")
        try:
            membership = SeedCommitMembership.from_snapshot(payload["membership"])
            members = tuple(
                RecoveryLineageDeploymentMember.from_snapshot(member)
                for member in raw_members
            )
            return cls(membership, members)
        except (KeyError, TypeError, SeedCommitLedgerError) as exc:
            if isinstance(exc, RecoveryLineageDeploymentError):
                raise
            raise RecoveryLineageDeploymentError("deployment snapshot is invalid") from exc


def build_parser() -> argparse.ArgumentParser:
    """Mathematics: define the single required topology-file argument for deterministic deployment validation."""

    parser = argparse.ArgumentParser(
        description="Validate a fixed-membership, multi-host recovery-lineage deployment topology."
    )
    parser.add_argument("--topology", type=Path, required=True)
    parser.add_argument(
        "--write-membership",
        type=Path,
        help="write the normalized fixed-membership snapshot for authority services",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Mathematics: return zero iff the topology file parses and satisfies every host, quorum, identity, and path constraint."""

    arguments = build_parser().parse_args(argv)
    try:
        payload = json.loads(arguments.topology.read_text(encoding="utf-8"))
        deployment = RecoveryLineageDeployment.from_snapshot(payload)
    except (OSError, UnicodeError, json.JSONDecodeError, RecoveryLineageDeploymentError) as exc:
        print(f"invalid recovery-lineage topology: {exc}")
        return 2

    if arguments.write_membership is not None:
        try:
            arguments.write_membership.write_text(
                json.dumps(deployment.membership.snapshot(), sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            print(f"could not write membership snapshot: {exc}")
            return 2

    authorities = [
        {
            "member_id": member.member_id,
            "dns_name": member.dns_name,
            "endpoint_host": member.endpoint_host,
            "port": member.port,
        }
        for member in deployment.members
        if member.role == "authority"
    ]
    summary = {
        "status": "valid",
        "topology_digest": deployment.digest,
        "membership_digest": deployment.membership.digest,
        "member_count": len(deployment.members),
        "strict_quorum": deployment.membership.quorum,
        "declared_failure_domain_count": len(
            {member.failure_domain for member in deployment.members}
        ),
        "authorities": authorities,
    }
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
    return 0
