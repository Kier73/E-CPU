# ROOM-001 — Three portable computational rooms

**Status:** Direct local implementation; hosted GitHub CI required for native E-CPU cross-check. Cloudflare deployment and live browser execution are not claimed.

Full concept and environmental matrix: [PORTABLE_ROOM_REALIZATION.md](../../docs/PORTABLE_ROOM_REALIZATION.md).

## What's built

An immutable E-CPU SAB-008-compatible finite affine intention is carried through:

1. **Python construction** (`build_runner.py`), optional/CI-required native `mailcpu.ground_native_realization` cross-check, content-addressed generation-1 receipt;
2. **Cloudflare Durable Object API adapter** (`worker.mjs`), authorization check at HTTP ingress, exact source and initial head pins, transactional compare-and-commit; its local test adapter (`local_worker_cli.mjs`) persists a single-writer JSON state file, **not** a real Cloudflare transaction;
3. **WebAssembly realization** (`browser/affine.wasm`), compiled from the 38-bit-coordinate capable `affine.c` using `clang --target=wasm32`, run in Node WebAssembly for the automated test. `browser/index.html` and `browser/verify.mjs` provide a browser-compatible independent verifier;
4. **Python independent audit** (`audit.py`) verifies each receipt, semantic result, predecessor, current generation and externally supplied trusted head. Offline recovery asks no original host.

The test intention is `x(t+1)=(17*x(t)+29) mod 65521`, `x(0)=5`, logical coordinate `1,000,000,000,137`, observed value **64,379**. Host-specific location is absent from the intention identity.

## Reproduce locally

Requires Python 3.11+, Node 20+ and a WebAssembly runtime in Node. The checked-in `browser/affine.wasm` already contains a prebuilt WASM module. To regenerate it requires Clang with wasm32 support:

```sh
clang --target=wasm32 -O2 -nostdlib -Wl,--no-entry \
  -Wl,--export=affine_at -Wl,--strip-all \
  -o experiments/portable_rooms/browser/affine.wasm \
  experiments/portable_rooms/affine.c
```

From repository root:

```sh
python -m unittest discover -s experiments/portable_rooms -p 'test_*.py' -v
python experiments/portable_rooms/build_runner.py --out /tmp/room001-1
node experiments/portable_rooms/local_worker_cli.mjs /tmp/room001-1 /tmp/room001-2
node experiments/portable_rooms/wasm_receiver_cli.mjs /tmp/room001-2 /tmp/room001-3
python experiments/portable_rooms/audit.py \
  --capsule /tmp/room001-3/capsule.json \
  --policy /tmp/room001-3/policy.json --require-native
```

`--require-native` refuses outside an E-CPU checkout with `mailcpu` installed. The GitHub workflow enforces it, alongside the repository's native SAB-008 test suite.

`browser/index.html` is an optional manual harness. To run it, copy the **stage-2** `capsule.json` and `policy.json` as `browser/capsule.json` and `browser/trusted-policy.json`, and serve the browser folder through a local HTTP server that serves `.wasm` as `application/wasm`. **This co-hosted policy is only a demo input**: real receivers must obtain root/high-water trust from outside the content being evaluated. Do not put actual deployment secrets in this directory.

## Deployable Worker adapter

`worker.mjs` uses the Cloudflare `cloudflare:workers` Durable Object base class and a `getByName('room001')` object binding. `wrangler.example.jsonc` is a **configuration example**, not a deployed or preauthorized service. An owner must explicitly provision the Cloudflare account and bind:

- `ROOM_TOKEN` — high-entropy secret for ingress authentication;
- `INTENTION_SHA256` — root pin, supplied by the receiver's trusted deployment policy;
- `BOOTSTRAP_HEAD` — exact independently pinned generation-1 head.

The service checks the bearer token before accepting `/advance` or `/snapshot`. Its storage transaction admits only the exact generation-1 checkpoint and rejects stale head challenges and conflicting replay. No untrusted URLs, arbitrary code, or packages are executed. Before production use it needs workerd/local runtime integration tests, Access/rate-limiting and operator-controlled secure provisioning.

## Evidence and what is *not* proved

The Python/JS/WASM result equality checks a finite mathematical relation and receipt chain. It does not independently establish the authenticity of an arbitrary Internet publication, Cloudflare-origin persistence, quantum computation, or continuous execution without triggers. The supervisor-provided final policy is a high-water demonstration, **not an external trusted quorum**. The database, file, and content identity are different objects.

Host capabilities and permissions stay receiver-owned; compare [SAB-001](../../docs/SUBSTRATE_ADAPTIVE_BOOTSTRAP.md), [SAB-008](../../docs/GROUND_NATIVE_REALIZATION_SAB008.md) and [Recovery Lineage](../../docs/RECOVERY_LINEAGE.md).
