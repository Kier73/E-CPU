"""Real E-CPU receiver: replay a VGI similarity effect from native StructuralMemory.

The original receiver admits one mathematically checked VGI record under an
E-CPU revision. A recovered receiver opens only the checkpointed native registry
and a separately trusted identity pin. No external catalogue or record file is
required after the committed checkpoint; the hypervisor owns effect replay.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
HELPERS = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT), str(HELPERS)]

import vgi_similarity_continuity_worker as base  # noqa: E402
from mailcpu import (  # noqa: E402
    Capability, HypervisorOperationChannel, HypervisorOperationResultChannel,
    ReliabilityPolicy, ReliableChannel, TransitBackendRouter, TransitComputeSession,
    TransitComputeWorker,
)
from mailcpu.vgi_similarity_native_memory import (  # noqa: E402
    NATIVE_DOMAIN, NativeSimilarityCatalogue, NativeSimilarityPin,
    admit_native_similarity_revision,
)
from mailcpu.transit_vgi_similarity import TransitVGISimilarityHost  # noqa: E402

MEMORY_ID = "similarity-transit-native-ground"
PROVENANCE = "host-provisioned-similarity-native-recovery"
PIN_NAME = "trusted-native-revision.json"


class CountingNativeSimilarityHost(TransitVGISimilarityHost):
    """Use the normal E-CPU operator, but resolve its record by native revision."""

    def __init__(self, operating_system, authority_pid: int, root: Path):
        root = Path(root)
        current = operating_system.structural_memory.active_version(MEMORY_ID)
        if current is None:
            # The first receiver is explicitly provisioned before accepting
            # any operation; this is not authority supplied by a peer request.
            manifest = json.loads((root / "trusted-pins.json").read_text(encoding="utf-8"))
            if set(manifest) != {"schema", "memory_sha256", "graph_fingerprint"} or manifest["schema"] != "vgi.similarity.test-pins.v1":
                raise ValueError("native receiver provisioning identity is malformed")
            payload = (root / "admitted-basis.json").read_bytes()
            pin = admit_native_similarity_revision(
                operating_system.structural_memory, payload,
                memory_id=MEMORY_ID, expected_revision=0,
                expected_memory_sha256=manifest["memory_sha256"],
                expected_graph_fingerprint=manifest["graph_fingerprint"],
                provenance_label=PROVENANCE,
            )
            base.write_json_durable(root / PIN_NAME, pin.to_dict())
        else:
            # No mathematical record is read from the filesystem on recovery.
            # The exact version and record are retrieved from HeadlessOS's
            # journal-verified structural-memory snapshot instead.
            pin_data = json.loads((root / PIN_NAME).read_text(encoding="utf-8"))
            pin = NativeSimilarityPin(**pin_data)
            if pin.memory_id != MEMORY_ID or pin.revision != 1:
                raise ValueError("native restored identity is not the committed revision")
        catalogue = NativeSimilarityCatalogue(operating_system, authority_pid, pin)
        super().__init__(operating_system, authority_pid, catalogue, node_id=base.NODE_ID)
        self.calls = 0
        self.native_pin = pin

    def handle(self, event):
        self.calls += 1
        return super().handle(event)


def make_native_session(request_transport, response_transport, root: Path):
    """Re-use E-CPU's Transit worker and reliable channels, adding read rights."""
    operating_system, _envelope = base.configure_receiver()
    # Host configuration is not received over Transit and is never in the
    # checkpoint; only this trusted setup permits this special memory domain.
    operating_system.structural_memory.admission_policy = lambda proposal: (
        proposal.spec.domain == NATIVE_DOMAIN
        and proposal.spec.context.get("provenance_label") == PROVENANCE
    )
    pid = operating_system.environment.kernel.spawn(
        "vgi-native-similarity-transit-worker",
        capabilities=(
            Capability("/virtual-layer/operators", frozenset({"compute"})),
            Capability("/structural-memory/read", frozenset({"read"})),
        ),
        parent_pid=operating_system.environment.init_pid,
    )
    host = CountingNativeSimilarityHost(operating_system, pid, root)
    router = TransitBackendRouter()
    router.register_backend(host)
    policy = ReliabilityPolicy(lease_ticks=1, max_attempts=5, window_size=8)
    request = HypervisorOperationChannel(ReliableChannel(
        request_transport, "worker", "worker", base.CHANNEL, policy, peer="client",
    ))
    response = HypervisorOperationResultChannel(ReliableChannel(
        response_transport, "worker", "client", base.CHANNEL + ".result", policy,
        peer="client",
    ), "client", base.CHANNEL)
    return TransitComputeSession(
        TransitComputeWorker(operating_system, pid, router), request, response,
    ), host


# Reuse the existing quorum-sealed prepare/kill/restore cut and channels. Their
# identities and effects remain E-CPU-owned; only the receiver-local backend
# reconstruction changes to use the native journalled revision.


def restore_native_then_new(root: Path, result_path: Path) -> None:
    """First replay the exact committed effect; then execute a *new* intent."""
    import time
    req_listener, resp_listener, req_port, resp_port = base.open_server_sockets()
    print(json.dumps({"pid": os.getpid(), "mode": "restore",
                      "request_port": req_port, "response_port": resp_port}), flush=True)
    req_t, resp_t = base.accept_worker_transports(req_listener, resp_listener)
    bundle = base.make_store(root).load_latest()
    if bundle.manifest.capture_cut != "after_execution_commit":
        raise AssertionError("restored receiver lacks the quorum-sealed committed cut")
    hosts: list[CountingNativeSimilarityHost] = []
    session = bundle.restore_receiver_session(
        req_t, resp_t,
        compute_host_factory=lambda os_, pid: base.restored_router(os_, pid, root, hosts),
    )
    if len(hosts) != 1 or hosts[0].calls != 0:
        raise AssertionError("backend already entered during recovery")
    original = base.serve_next(session)
    if not original.replayed or not original.executed or hosts[0].calls:
        raise AssertionError("previously committed effect did not replay without computation")
    original_effect = original.effect
    original_native = original_effect["result"]["native_structural_memory"]
    if original_native["revision"] != 1:
        raise AssertionError("replayed effect lost the exact native revision")
    # A genuine *different* request must be executed from checkpointed memory,
    # not returned from the old ledger. Forbid new basis search explicitly.
    from vgi.similarity_blocks import CertifiedSimilarityBlocks
    old_discover = CertifiedSimilarityBlocks.__dict__["discover"]
    try:
        CertifiedSimilarityBlocks.discover = classmethod(
            lambda cls, *args, **kwargs: (_ for _ in ()).throw(
                AssertionError("a recovered observer must reuse its verified basis")))
        new = base.serve_next(session, timeout=45.0)
    finally:
        CertifiedSimilarityBlocks.discover = old_discover
    if new.replayed or not new.executed or hosts[0].calls != 1:
        raise AssertionError("fresh intent was not executed exactly once")
    new_effect = new.effect
    new_native = new_effect["result"]["native_structural_memory"]
    if (new_native["revision"] != original_native["revision"]
        or new_native["spec_digest"] != original_native["spec_digest"]
        or new_native["certificate_digest"] != original_native["certificate_digest"]):
        raise AssertionError("fresh navigation changed the restored mathematical Ground")
    os_ = session.worker.operating_system
    journal = os_.environment.kernel.journal.snapshot()
    native_reads = sum(r["kind"] == "structural_memory.read_revision" for r in journal)
    if native_reads != 2:
        raise AssertionError("replay must not reread, and fresh execution must read once")
    result = {
        "pid": os.getpid(), "stage": "replayed_then_fresh",
        "replayed": original.replayed,
        "backend_calls_at_replay": 0,
        "backend_calls_after_fresh": hosts[0].calls,
        "bundle_generation": bundle.generation,
        "bundle_manifest_digest": bundle.manifest.digest,
        "effect_digest": base._digest(original_effect),
        "navigation_effect_digest": original_effect["result"]["effect_digest"],
        "native_read_receipt_id": original_native["index_read_receipt"]["receipt_id"],
        "fresh_effect_digest": new_effect["result"]["effect_digest"],
        "fresh_navigation_result": new_effect["result"]["navigation"]["inner"]["result"]["values"],
        "fresh_native_read_receipt_id": new_native["index_read_receipt"]["receipt_id"],
        "memory_sha256": original_effect["result"]["computation_ground"]["memory_sha256"],
        "graph_fingerprint": original_effect["result"]["computation_ground"]["graph_fingerprint"],
        "native_read_record_count": native_reads,
        "execution_ledger_entries": len(os_.hypervisor_arbitration.snapshot()["executions"]),
        "commit_record_count": sum(r["kind"] == "hypervisor.execution.commit" for r in journal),
        "replay_record_count": sum(r["kind"] == "hypervisor.execution.replay" for r in journal),
        "journal_valid": os_.environment.kernel.journal.verify(),
    }
    base.write_json_durable(result_path, result)
    deadline = time.monotonic() + 20
    while session.response.channel.pending_sequences() and time.monotonic() < deadline:
        session.response.channel.process_ack()
        time.sleep(.005)
    if session.response.channel.pending_sequences():
        raise TimeoutError("fresh similarity response did not receive an acknowledgement")
    req_t.close()
    resp_t.close()

base.CountingTransitVGISimilarityHost = CountingNativeSimilarityHost
base.make_session = make_native_session
base.restore = restore_native_then_new

if __name__ == "__main__":
    raise SystemExit(base.main(sys.argv[1:]))