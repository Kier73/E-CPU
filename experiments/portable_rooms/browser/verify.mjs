/** Independent WebAssembly receiver. Works in a browser via fetch or in Node
 * with supplied binary bytes; does not import the edge/WASM producer code. */
const SCHEMA='ecpu.room001.intention.v1', RC='ecpu.room001.receipt.v1', CC='ecpu.room001.capsule.v1';
const rooms=['github-actions','durable-object','browser-wasm'];
const methods=['python-native-affine','js-event-affine','wasm-affine'];
const fail=s=>{throw Error('wasm receiver refused: '+s)};
function canonical(x) {
 if(Array.isArray(x))return '['+x.map(canonical).join(',')+']';
 if(x!==null && typeof x==='object')return '{'+Object.keys(x).sort().map(k=>JSON.stringify(k)+':'+canonical(x[k])).join(',')+'}';
 if(typeof x==='number'&&!Number.isSafeInteger(x))fail('unsafe number');
 if(!['string','number','boolean'].includes(typeof x)&&x!==null)fail('unexpected value');
 return JSON.stringify(x);
}
async function hashRaw(raw){return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',raw)),x=>x.toString(16).padStart(2,'0')).join('')}
async function hash(x){return hashRaw(new TextEncoder().encode(canonical(x)));}
function keys(o,arr){return !!o && typeof o==='object'&&!Array.isArray(o)&&Object.keys(o).sort().join(',')===[...arr].sort().join(',')}
export async function verifyAndRealize(cap,policy,wasmBytes) {
 const buf=wasmBytes instanceof Uint8Array?wasmBytes:new Uint8Array(wasmBytes);
 if(!/^[0-9a-f]{64}$/.test(policy.wasm_sha256 || '') ||await hashRaw(buf)!==policy.wasm_sha256)fail('untrusted executable bytes');
 if(!keys(cap,['schema','intention','receipts'])||cap.schema!==CC)fail('capsule');
 const i=cap.intention,g=i?.ground;
 if(!keys(i,['schema','request_id','ground','coordinate','projection'])||i.schema!==SCHEMA||i.projection!=='value'||i.request_id!=='room001-portable-intention'||
   !keys(g,['family','a','c','modulus','seed'])||g.family!=='affine_mod'||!
   Number.isSafeInteger(i.coordinate)||i.coordinate<0||i.coordinate>1e15||
   !Number.isSafeInteger(g.modulus)||g.modulus<2||g.modulus>65521||
   !['a','c','seed'].every(k=>Number.isSafeInteger(g[k])&&g[k]>=0&&g[k]<g.modulus))fail('Ground/intent');
 const root=await hash(i);
 if(root!==policy.intention_digest)fail('intention pin');
 const w=await WebAssembly.instantiate(buf,{});
 const wasm=w.instance.exports.affine_at;
 if(typeof wasm!=='function')fail('missing native WASM export');
 const result=wasm(g.a,g.c,g.modulus,g.seed,BigInt(i.coordinate));
 if(!Number.isSafeInteger(result)||result<0||result>=g.modulus)fail('invalid wasm result');
 if(!Array.isArray(cap.receipts)||cap.receipts.length!==2)fail('must follow committed DO room');
 let predecessor='0'.repeat(64);
 for(let j=0;j<2;j++){
   const r=cap.receipts[j];
   if(!keys(r,['schema','generation','predecessor','intention_digest','room','method','value','status','digest'])||
     r.schema!==RC||r.generation!==j+1||r.room!==rooms[j]||r.method!==methods[j]||
     r.status!=='finite-ground-checked'||r.value!==result||r.intention_digest!==root||r.predecessor!==predecessor)fail('input evidence');
   const copy={...r};delete copy.digest;
   if(await hash(copy)!==r.digest)fail('content identity');
   predecessor=r.digest;
 }
 if(policy.expected_head!==predecessor||policy.generation!==2)fail('stale external head');
 const r={schema:RC,generation:3,predecessor,intention_digest:root,room:rooms[2],
          method:methods[2],value:result,status:'finite-ground-checked'};
 r.digest=await hash(r);
 return {capsule:{schema:CC,intention:i,receipts:[...cap.receipts,r]},
         head:r.digest,generation:3, result};
}
