"""HFG-003: two independent GitHub Actions jobs as model observer-hosts.

Each job acquires ONLY the selected source-pinned Qwen3 layer tensors using IFS
HFR, executes through E-CPU's existing Hypervisor, and retains its output in
M1 objects. GitHub Actions artifacts transport the *Ground state*, not a VM.
No tensor payloads or pretrained weights are published in job artifacts.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import os
import re
import sys

from mailcpu.computational_objects import ComputationalObjectStore
from mailcpu.hf_model_ground import HFModelGround
from mailcpu.hf_layer_realization import _required_weights, LayerWeightGround, NativeQwen3LayerHost
from mailcpu.model_orbit_handoff import publish_layer_handoff, resume_model_orbit

REPOSITORY = "Qwen/Qwen3-0.6B"
REVISION = "167b8104f88905a951069f5f95f9776908da5f68"
IFS_REVISION = "c9716242725be65937fda1dd7b6cb778ca1def91"


class ArtifactPages:
    """Test-only transportable M1 page backing, not another state authority.

    A real deployment uses E-CPU RemotePageStore and M3 recovery lineage.
    This bounded experiment uses GitHub job artifacts as the passive carrier.
    """
    page_size = 4096

    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, identity: str) -> Path:
        if not isinstance(identity, str) or not re.fullmatch(r"[a-f0-9]{64}", identity):
            raise ValueError("invalid M1 page digest")
        return self.root / identity

    def put_page(self, data: bytes) -> str:
        if len(data) != self.page_size:
            raise ValueError("wrong M1 page size")
        identity = sha256(data).hexdigest()
        path = self._path(identity)
        if not path.exists():
            with path.open("xb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
        return identity

    def get_page(self, identity: str) -> bytes:
        data = self._path(identity).read_bytes()
        if len(data) != self.page_size or sha256(data).hexdigest() != identity:
            raise ValueError("page bytes contradict the content address")
        return data


def ground_and_weights(ifs_root: Path, *, layer: int):
    from mailcpu.hf_layer_realization import LayerWeightGround
    sys.path.insert(0, str(ifs_root))
    from experiments.external_neural_structure_reading.hub import (
        inspect_huggingface_model, fetch_selected_tensor_payloads,
    )
    nsd = inspect_huggingface_model(REPOSITORY, REVISION, license_id="apache-2.0")
    model = HFModelGround.from_nsd(nsd)
    if model.repository != REPOSITORY or model.revision != REVISION or model.family != "qwen3":
        raise RuntimeError("pinned Hugging Face Model Ground differs")
    wanted = _required_weights(model, layer)
    if len(wanted) != 11:
        raise RuntimeError("wrong selected layer tensor inventory")
    payloads, evidence = fetch_selected_tensor_payloads(
        nsd, list(wanted), max_total_bytes=64 * 1024 * 1024,
        max_tensor_bytes=16 * 1024 * 1024,
    )
    # The weight object store is receiver-local. Its tensor pages are not copied
    # to the second observer; that observer independently acquires its own layer.
    class VolatilePages:
        page_size = 4096
        def __init__(self): self.pages = {}
        def put_page(self, p):
            digest=sha256(p).hexdigest();self.pages[digest]=p;return digest
        def get_page(self, digest):return self.pages[digest]
    binding = LayerWeightGround.from_payloads(model, layer,
             ComputationalObjectStore(VolatilePages()), payloads,
             hfr_evidence=evidence)
    return model, binding, evidence


def run(*, role: str, ifs_root: Path, outgoing: Path, incoming: Path | None = None,
        external_state_head: str | None = None, external_native_receipt: str | None = None) -> dict:
    import numpy as np
    if role not in {"produce", "continue"}:
        raise ValueError("unknown observer role")
    outgoing.mkdir(parents=True, exist_ok=True)
    model, binding, evidence = ground_and_weights(ifs_root, layer=0 if role == "produce" else 1)
    state_store = ComputationalObjectStore(ArtifactPages(outgoing / "pages"))
    if role == "produce":
        points = np.arange(2 * model.configuration["hidden_size"], dtype=np.float32)
        hidden = (np.sin(points / 13) * np.float32(0.05)).reshape(2, model.configuration["hidden_size"])
        predecessor = None
    else:
        if incoming is None or external_state_head is None or external_native_receipt is None:
            raise ValueError("consumer requires incoming object and external pins")
        record = json.loads((incoming / "state.json").read_text())
        origin_store = ComputationalObjectStore(ArtifactPages(incoming / "pages"))
        hidden = resume_model_orbit(
            record, origin_store, model=model, expected_next_layer=1,
            expected_state_digest=external_state_head,
            expected_native_receipt_digest=external_native_receipt,
        )
        predecessor = record["state_digest"]
    result = NativeQwen3LayerHost(binding).execute(
        hidden, request_id="hfg003-"+role, position=0,
        output_sink=lambda tensor, receipt:publish_layer_handoff(
            binding,tensor,receipt,state_store,
            predecessor_state_digest=predecessor,
        ),
    )
    state=result.pop("portable_output")
    assert result["output_digest"] == state["output_digest"]
    assert result["dag_complete"] and result["independent_reference_checked"]
    (outgoing / "state.json").write_text(json.dumps(state, sort_keys=True, indent=2)+"\n")
    (outgoing / "receipt.json").write_text(json.dumps({
        "schema":"mailcpu.hfg003.observer-result.v1",
        "model_descriptor":model.descriptor_digest,
        "source":REPOSITORY+"@"+REVISION,
        "layer":binding.layer_index,
        "weight_snapshot":binding.snapshot.identity,
        "dag_digest":result["dag_digest"],
        "native_stage_receipts":result["stage_receipts"],
        "state_digest":state["state_digest"],
        "native_receipt_digest":state["native_receipt_digest"],
        "predecessor_state_digest":predecessor,
        "selected_tensor_bytes":sum(e["size_bytes"] for e in evidence),
        "verified_source_ranges":binding.evidence()["hfr_source_ranges_verified"],
        "independent_reference_checked":result["independent_reference_checked"],
        "final_numerical_state":state["output_digest"],
        "full_model_forward_executed":False,
        "path_native_tensor_arithmetic_proven":False,
    },sort_keys=True,indent=2)+"\n")
    return {"role":role,"source":REPOSITORY+"@"+REVISION,
            "layer":binding.layer_index, "state_digest":state["state_digest"],
            "native_receipt_digest":state["native_receipt_digest"],
            "predecessor":predecessor,
            "model_ground":model.descriptor_digest,
            "output_digest":state["output_digest"],
            "new_receivers_can_continue":binding.layer_index+1<model.configuration["num_hidden_layers"]}


def main(argv: list[str] | None = None) -> int:
    p=argparse.ArgumentParser()
    p.add_argument("role",choices=("produce","continue"))
    p.add_argument("--ifs-root",type=Path,required=True)
    p.add_argument("--outgoing",type=Path,required=True)
    p.add_argument("--incoming",type=Path)
    p.add_argument("--external-state-head")
    p.add_argument("--external-native-receipt")
    p.add_argument("--job-output",type=Path)
    args=p.parse_args(argv)
    result=run(role=args.role,ifs_root=args.ifs_root,outgoing=args.outgoing,
        incoming=args.incoming,external_state_head=args.external_state_head,
        external_native_receipt=args.external_native_receipt)
    if args.job_output:
        with args.job_output.open('a') as f:
            f.write(f"state_digest={result['state_digest']}\n")
            f.write(f"native_receipt_digest={result['native_receipt_digest']}\n")
    print(json.dumps(result,sort_keys=True))
    return 0

if __name__=="__main__":raise SystemExit(main())
