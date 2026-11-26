"""EC-LLM-002: networked pretrained attention subspace challenge.

Independent Transformers reference; NOT native E-CPU inference. Requires
torch and transformers plus authorized access to pinned public weights.
"""
import argparse
import json
import time
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

MODEL = "Qwen/Qwen3-0.6B"
REVISION = "167b8104f88905a951069f5f95f9776908da5f68"

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="ec-llm-002.json")
    args = parser.parse_args()
    torch.set_num_threads(2)
    tok = AutoTokenizer.from_pretrained(MODEL, revision=REVISION)
    model = AutoModelForCausalLM.from_pretrained(MODEL, revision=REVISION, torch_dtype=torch.float32, attn_implementation="eager").eval()
    # Probe learned post-Q/K-normalization, pre-RoPE coordinates. These are
    # deliberately NOT claimed to be the final causal cache or full attention.
    head = model.model.layers[0].self_attn
    qs, ks = [], []
    handles = [head.q_norm.register_forward_hook(lambda m,i,o: qs.append(o.detach().double())),
               head.k_norm.register_forward_hook(lambda m,i,o: ks.append(o.detach().double()))]
    prompts = [
        "The river flows through a valley, carrying sediment toward the sea. Explain the process.",
        "Write a short Python function for computing the greatest common divisor of two integers.",
        "A researcher measures a system twice and obtains different values. What could explain this?",
        "Summarize the difference between a necessary and a sufficient condition in mathematics.",
        "The train leaves the station at noon. A passenger changes their plans after a delay.",
        "Explain why a distributed system must distinguish message delivery from durable commitment.",
    ]
    start = time.perf_counter()
    with torch.inference_mode():
        for prompt in prompts:
            model(**tok(prompt, return_tensors="pt"), use_cache=False)
    for h in handles: h.remove()
    train = torch.cat([q.reshape(-1,q.shape[-1]) for q in qs[:3]])
    testq = torch.cat([q.reshape(-1,q.shape[-1]) for q in qs[3:]])
    testk = torch.cat([k.reshape(-1,k.shape[-1]) for k in ks[3:]])
    _, _, vh = torch.linalg.svd(train, full_matrices=True)
    dim = train.shape[-1]
    scores = testq @ testk.T / dim**0.5
    rows = []
    for rank in sorted(set([dim//8,dim//4,dim//2,3*dim//4,dim])):
        U = vh[:rank].T
        qp, kp = testq@U, testk@U
        approx = qp@kp.T / dim**0.5
        bound = (testq-qp@U.T).norm(dim=-1)[:,None]*(testk-kp@U.T).norm(dim=-1)[None,:]/dim**0.5
        error = (scores-approx).abs()
        assert torch.all(error <= bound+1e-9)
        rows.append({"rank":rank,"max_error":float(error.max()),"mean_bound":float(bound.mean()),
                     "max_bound":float(bound.max())})
    report={"model":MODEL,"revision":REVISION,"scope":"layer zero pre-RoPE normalized Q/K cross-score probe, not actual causal attention or token equivalence",
            "train_prompts":3,"heldout_prompts":3,"query_count":len(testq),"key_count":len(testk),"rows":rows,"elapsed_seconds":time.perf_counter()-start}
    with open(args.output,"w") as f: json.dump(report,f,indent=2)
    print(json.dumps(report,indent=2))

if __name__ == "__main__":
    main()
