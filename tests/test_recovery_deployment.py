"""Deployment-topology schema and fail-closed multi-host placement tests."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from mailcpu import SeedCommitMembership
from mailcpu.recovery_deployment import (
    RecoveryLineageDeployment,
    RecoveryLineageDeploymentError,
    RecoveryLineageDeploymentMember,
    main,
)

GENESIS = "a" * 64


def _membership() -> SeedCommitMembership:
    """Construct the fixed three-member majority used by topology tests."""

    return SeedCommitMembership(
        "multihost-recovery",
        1,
        ("A", "B", "C"),
        "A",
        1,
        GENESIS,
    )


def _member(
    member_id: str,
    role: str,
    host_id: str,
    failure_domain: str,
    dns_name: str,
    endpoint_host: str | None,
    port: int | None,
) -> RecoveryLineageDeploymentMember:
    """Construct one member with separate persistent journal and TLS resource paths."""

    root = f"/var/lib/mailcpu/{member_id}"
    tls = f"/etc/mailcpu/{member_id}"
    return RecoveryLineageDeploymentMember(
        member_id,
        role,
        dns_name,
        host_id,
        failure_domain,
        endpoint_host,
        port,
        f"{root}/journal.jsonl",
        f"{tls}/certificate.pem",
        f"{tls}/private.key",
        f"{tls}/trust-bundle.pem",
    )


def _deployment() -> RecoveryLineageDeployment:
    """Construct a topology whose logical authorities occupy three declared host/failure domains."""

    return RecoveryLineageDeployment(
        _membership(),
        (
            _member(
                "C",
                "authority",
                "authority-c",
                "region-1/zone-c/host-c",
                "authority-c.mailcpu.test",
                "192.0.2.13",
                7443,
            ),
            _member(
                "A",
                "owner",
                "owner-a",
                "region-1/zone-a/host-a",
                "owner-a.mailcpu.test",
                None,
                None,
            ),
            _member(
                "B",
                "authority",
                "authority-b",
                "region-1/zone-b/host-b",
                "authority-b.mailcpu.test",
                "192.0.2.12",
                7443,
            ),
        ),
    )


def test_deployment_round_trip_is_canonical_and_digest_stable() -> None:
    """Mathematics: decoding the snapshot reproduces the same deployment, and digest is invariant under member-order permutation."""

    deployment = _deployment()
    restored = RecoveryLineageDeployment.from_snapshot(deployment.snapshot())

    assert restored == deployment
    assert [member.member_id for member in deployment.members] == ["A", "B", "C"]
    assert restored.digest == deployment.digest
    assert deployment.membership.quorum == 2


def test_deployment_requires_one_distinct_host_per_member() -> None:
    """Mathematics: host identity is injective over fixed membership, so no two logical authorities share a declared host."""

    deployment = _deployment()
    members = list(deployment.members)
    members[2] = replace(members[2], host_id=members[1].host_id)

    with pytest.raises(RecoveryLineageDeploymentError, match="unique host id"):
        RecoveryLineageDeployment(deployment.membership, tuple(members))


def test_deployment_requires_distinct_failure_domains() -> None:
    """Mathematics: the placement projection from members to declared failure domains must be injective."""

    deployment = _deployment()
    members = list(deployment.members)
    members[2] = replace(members[2], failure_domain=members[1].failure_domain)

    with pytest.raises(RecoveryLineageDeploymentError, match="unique failure domain"):
        RecoveryLineageDeployment(deployment.membership, tuple(members))


def test_authority_endpoints_must_not_alias_the_same_host() -> None:
    """Mathematics: authority network-address projection is injective, preventing two member identities from sharing one endpoint host."""

    deployment = _deployment()
    members = list(deployment.members)
    members[2] = replace(members[2], endpoint_host=members[1].endpoint_host)

    with pytest.raises(RecoveryLineageDeploymentError, match="distinct endpoint host"):
        RecoveryLineageDeployment(deployment.membership, tuple(members))


def test_membership_coverage_and_role_binding_are_exact() -> None:
    """Mathematics: deployment member ids equal the fixed membership set and role(member)=owner iff member is the configured owner."""

    deployment = _deployment()
    members = list(deployment.members)
    replacement = replace(members[2], member_id="D", dns_name="authority-d.mailcpu.test")
    with pytest.raises(RecoveryLineageDeploymentError, match="cover the fixed membership exactly"):
        RecoveryLineageDeployment(deployment.membership, (members[0], members[1], replacement))

    members = list(deployment.members)
    members[0] = replace(members[0], role="authority", endpoint_host="192.0.2.10", port=7443)
    with pytest.raises(RecoveryLineageDeploymentError, match="must have role 'owner'"):
        RecoveryLineageDeployment(deployment.membership, tuple(members))


def test_topology_requires_at_least_three_members_and_fixed_quorum() -> None:
    """Mathematics: a distributed owner plus two authority topology is the minimum accepted shape."""

    membership = SeedCommitMembership(
        "two-member-recovery",
        1,
        ("A", "B"),
        "A",
        1,
        GENESIS,
    )
    owner = _member(
        "A",
        "owner",
        "owner-a",
        "zone-a",
        "owner-a.mailcpu.test",
        None,
        None,
    )
    authority = _member(
        "B",
        "authority",
        "authority-b",
        "zone-b",
        "authority-b.mailcpu.test",
        "192.0.2.20",
        7443,
    )
    with pytest.raises(RecoveryLineageDeploymentError, match="at least three members"):
        RecoveryLineageDeployment(membership, (owner, authority))


def test_node_paths_must_be_absolute_and_distinct() -> None:
    """Mathematics: each member's journal and TLS resources occupy four distinct absolute path coordinates."""

    with pytest.raises(RecoveryLineageDeploymentError, match="absolute node-local path"):
        RecoveryLineageDeploymentMember(
            "B",
            "authority",
            "authority-b.mailcpu.test",
            "authority-b",
            "zone-b",
            "192.0.2.20",
            7443,
            "relative/journal.jsonl",
            "/etc/mailcpu/B/certificate.pem",
            "/etc/mailcpu/B/private.key",
            "/etc/mailcpu/B/trust.pem",
        )

    with pytest.raises(RecoveryLineageDeploymentError, match="must be distinct"):
        RecoveryLineageDeploymentMember(
            "B",
            "authority",
            "authority-b.mailcpu.test",
            "authority-b",
            "zone-b",
            "192.0.2.20",
            7443,
            "/var/lib/mailcpu/B/journal.jsonl",
            "/etc/mailcpu/B/certificate.pem",
            "/etc/mailcpu/B/private.key",
            "/etc/mailcpu/B/private.key",
        )


def test_snapshot_refuses_unknown_fields_and_schema_versions() -> None:
    """Mathematics: the admitted topology domain contains only the exact schema-v1 field set."""

    snapshot = _deployment().snapshot()
    snapshot["unrecognized"] = True
    with pytest.raises(RecoveryLineageDeploymentError, match="fields are malformed"):
        RecoveryLineageDeployment.from_snapshot(snapshot)

    snapshot = _deployment().snapshot()
    snapshot["schema_version"] = 2
    with pytest.raises(RecoveryLineageDeploymentError, match="unsupported deployment schema"):
        RecoveryLineageDeployment.from_snapshot(snapshot)


def test_cli_reports_topology_validation_without_exposing_local_key_paths(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Mathematics: successful CLI validation returns zero and emits only a redacted deployment summary."""

    path = tmp_path / "topology.json"
    path.write_text(json.dumps(_deployment().snapshot()), encoding="utf-8")

    assert main(["--topology", str(path)]) == 0
    output = capsys.readouterr().out
    summary = json.loads(output)

    assert summary["status"] == "valid"
    assert summary["member_count"] == 3
    assert summary["strict_quorum"] == 2
    assert summary["declared_failure_domain_count"] == 3
    assert [item["member_id"] for item in summary["authorities"]] == ["B", "C"]
    assert "private_key_path" not in output
    assert "/etc/mailcpu" not in output


def test_cli_can_emit_exact_membership_snapshot(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Mathematics: the emitted authority-service membership file equals the normalized membership projection."""

    topology_path = tmp_path / "topology.json"
    membership_path = tmp_path / "membership.json"
    deployment = _deployment()
    topology_path.write_text(json.dumps(deployment.snapshot()), encoding="utf-8")

    assert main(
        ["--topology", str(topology_path), "--write-membership", str(membership_path)]
    ) == 0
    capsys.readouterr()
    assert json.loads(membership_path.read_text(encoding="utf-8")) == deployment.membership.snapshot()


def test_cli_rejects_aliased_failure_domains(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Mathematics: a topology with colliding fault-domain coordinates has a nonzero validation disposition."""

    deployment = _deployment()
    snapshot = deployment.snapshot()
    snapshot["members"][2]["failure_domain"] = snapshot["members"][1]["failure_domain"]
    path = tmp_path / "invalid-topology.json"
    path.write_text(json.dumps(snapshot), encoding="utf-8")

    assert main(["--topology", str(path)]) == 2
    assert "unique failure domain" in capsys.readouterr().out

def test_cli_rejects_non_text_member_role_without_traceback(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Mathematics: malformed member-role values map to the CLI invalid-topology disposition."""

    snapshot = _deployment().snapshot()
    snapshot["members"][1]["role"] = []
    path = tmp_path / "malformed-role.json"
    path.write_text(json.dumps(snapshot), encoding="utf-8")

    assert main(["--topology", str(path)]) == 2
    assert "member role must be non-empty trimmed text" in capsys.readouterr().out
