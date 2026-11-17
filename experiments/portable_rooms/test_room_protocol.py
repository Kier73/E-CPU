"""ROOM-001: process separation, independent verification and adversarial controls."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from room_protocol import (RoomRefused, canonical, check_intent, digest, intention,
                           make_capsule, receipt, value_at, verify_capsule)
from audit import audit


def run(*args: str, timeout: int = 20) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=HERE, capture_output=True, text=True, timeout=timeout)


class PortableRoomsTest(unittest.TestCase):
    def test_distant_navigation_matches_literal_short_orbit(self):
        g = intention()
        x = g['ground']['seed']
        for t in range(100):
            g['coordinate'] = t
            self.assertEqual(value_at(g), x)
            x = (17 * x + 29) % 65521
        self.assertEqual(value_at(intention()), 64379)

    def test_schema_and_strict_integer_domains(self):
        for new in [True, -1, 10**16, 5.25, None]:
            i = intention(); i['coordinate'] = new
            with self.assertRaises(RoomRefused): check_intent(i)
        i = intention(); i['ground']['modulus'] = 65522
        with self.assertRaises(RoomRefused): check_intent(i)

    def test_canonical_root_independent_key_order(self):
        i = intention()
        self.assertEqual(digest(i), digest(json.loads(json.dumps(i, sort_keys=False))))
        self.assertEqual(digest(i), '415b386b6ed1e9ef0a0b45f74ef22eb608fc7804f9430011f0877aa0714eb235')
        c = make_capsule(i)
        self.assertEqual(verify_capsule(c, expected_intention=digest(i), expected_generation=1), c['receipts'][0]['digest'])

    def test_tampered_receipt_and_self_consistent_false_result_are_refused(self):
        c = make_capsule(intention())
        c['receipts'][0]['value'] += 1
        with self.assertRaises(RoomRefused): verify_capsule(c)
        c['receipts'][0]['digest'] = digest({k:v for k,v in c['receipts'][0].items() if k!='digest'})
        with self.assertRaises(RoomRefused): verify_capsule(c)

    def test_forged_root_and_snapshot_rollback_are_refused(self):
        first = make_capsule(intention())
        pol = {'schema':'ecpu.room001.external-policy.v1',
               'intention_digest':digest(first['intention']),
               'expected_head':'a'*64, 'generation':3, 'wasm_sha256':'b'*64}
        with self.assertRaises(RoomRefused): audit(first,pol)
        tampered = copy.deepcopy(first)
        tampered['intention']['ground']['c'] += 1
        with self.assertRaises(RoomRefused): verify_capsule(tampered,expected_intention=pol['intention_digest'])

    def test_full_three_process_handoff_and_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            stage = [Path(tmp)/f'stage{i}' for i in range(1,4)]
            cmds=[ [sys.executable,str(HERE/'build_runner.py'),'--out',str(stage[0])],
                   ['node',str(HERE/'local_worker_cli.mjs'),str(stage[0]),str(stage[1])],
                   ['node',str(HERE/'wasm_receiver_cli.mjs'),str(stage[1]),str(stage[2])]]
            pid_seen = []
            for cmd in cmds:
                r = run(*cmd)
                self.assertEqual(r.returncode, 0, r.stderr)
                pid_seen.append(json.loads(r.stdout).get('pid'))
            self.assertNotEqual(pid_seen[1],pid_seen[2])
            c = json.loads((stage[2]/'capsule.json').read_text())
            p = json.loads((stage[2]/'policy.json').read_text())
            self.assertEqual([x['room'] for x in c['receipts']], ['github-actions','durable-object','browser-wasm'])
            self.assertEqual(audit(c,p)['new_source_calls'],0)
            self.assertEqual(audit(c,p)['result'],64379)
            # The restart-like attempt must not replace the single durable commit.
            r = run('node',str(HERE/'local_worker_cli.mjs'),str(stage[0]),str(stage[1]))
            self.assertNotEqual(r.returncode,0)
            self.assertIn('refused',r.stderr.lower())
            # Corrupting a retained byte under the original policy cannot succeed.
            c2 = copy.deepcopy(c); c2['receipts'][2]['digest']='0'*64
            with self.assertRaises(RoomRefused): audit(c2,p)
            c2 = copy.deepcopy(c); c2['receipts']=c2['receipts'][:2]
            with self.assertRaises(RoomRefused): audit(c2,p)
            # A separate receiver process verifies without source calls.
            r = run(sys.executable,str(HERE/'audit.py'), '--capsule',str(stage[2]/'capsule.json'),
                    '--policy',str(stage[2]/'policy.json'))
            self.assertEqual(r.returncode,0,r.stderr)
            self.assertEqual(json.loads(r.stdout)['generation'],3)

    def test_wasm_executable_is_pinned_and_corrupt_bytes_refuse(self):
        with tempfile.TemporaryDirectory() as tmp:
            stage=[Path(tmp)/f's{i}' for i in range(1,3)]
            for cmd in ([sys.executable,str(HERE/'build_runner.py'),'--out',str(stage[0])],
                        ['node',str(HERE/'local_worker_cli.mjs'),str(stage[0]),str(stage[1])]):
                r = run(*cmd)
                self.assertEqual(r.returncode,0,r.stderr)
            # ES module verified in Node's actual WebAssembly runtime.
            module = (HERE/'browser'/'verify.mjs').as_uri()
            wasm = (HERE/'browser'/'affine.wasm').as_posix()
            cap=(stage[1]/'capsule.json').as_posix()
            pol=(stage[1]/'policy.json').as_posix()
            script = f'''
import fs from 'node:fs/promises';
import {{verifyAndRealize}} from '{module}';
const c=JSON.parse(await fs.readFile({json.dumps(cap)},'utf8'));
const p=JSON.parse(await fs.readFile({json.dumps(pol)},'utf8'));
const b=await fs.readFile({json.dumps(wasm)});
try{{await verifyAndRealize(c,p,Buffer.concat([b,Buffer.from([0])]));process.exit(1);}}
catch(e){{if(!String(e).includes('untrusted executable bytes'))throw e;}}
const v=await verifyAndRealize(c,p,b);
if(v.result!==64379||v.generation!==3)throw Error('bad independent wasm output');
console.log('ok');'''
            res=run('node','--input-type=module','-e',script)
            self.assertEqual(res.returncode,0,res.stderr)
            self.assertEqual(res.stdout.strip(),'ok')

    def test_durable_mock_needs_bootstrap_and_current_head_pins(self):
        mod=(HERE/'room_core.mjs').as_uri()
        script=f'''
import {{advanceDurable}} from '{mod}';
let called=false;
const storage={{async transaction(f){{called=true;return f({{async get(){{return null}},async put(){{}}}});}}}};
try{{await advanceDurable(storage,{{}},'0'.repeat(64),{{intention:'0'.repeat(64),bootstrap:'invalid'}});process.exit(1);}}
catch(e){{if(!String(e).includes('missing receiver pins'))throw e;}}
if(called)throw Error('untrusted storage reached');
console.log('refused');'''
        r=run('node','--input-type=module','-e',script)
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(r.stdout.strip(),'refused')

    def test_native_sab008_equivalence(self):
        try:
            from build_runner import native_crosscheck
            import mailcpu
        except ImportError:
            self.skipTest('Native E-CPU installed only in repo CI')
        self.assertEqual(len(native_crosscheck(intention())),64)

if __name__=='__main__':unittest.main()
