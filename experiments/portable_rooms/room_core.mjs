/** ROOM-001: strict, portable content identity and DO-style storage admission.
 *  No remote advertisement or digest is a permission. Caller must authenticate
 *  at its own ingress; this code additionally requires receiver-controlled pins.
 */
const ZERO = '0'.repeat(64);
const MAX_COORD = 1_000_000_000_000_000;
const INTENT = 'ecpu.room001.intention.v1';
const RECEIPT = 'ecpu.room001.receipt.v1';
const CAPSULE = 'ecpu.room001.capsule.v1';
const ROOMS = ['github-actions', 'durable-object', 'browser-wasm'];
const METHODS = ['python-native-affine', 'js-event-affine', 'wasm-affine'];

function fail(reason) { throw Error(`ROOM-001 refused: ${reason}`); }
function exactKeys(x, keys) {
  return x !== null && typeof x === 'object' && !Array.isArray(x) &&
    Object.keys(x).sort().join(',') === [...keys].sort().join(',');
}
export function canonical(value) {
  if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']';
  if (value !== null && typeof value === 'object')
    return '{' + Object.keys(value).sort().map(k => JSON.stringify(k) + ':' + canonical(value[k])).join(',') + '}';
  if (value === null || typeof value === 'string' || typeof value === 'boolean') return JSON.stringify(value);
  if (typeof value === 'number' && Number.isSafeInteger(value)) return String(value);
  return fail('noncanonical numeric or exotic value');
}
export async function digest(value) {
  const raw = new TextEncoder().encode(canonical(value));
  const hash = new Uint8Array(await crypto.subtle.digest('SHA-256', raw));
  return Array.from(hash, c => c.toString(16).padStart(2, '0')).join('');
}
export function checkIntent(i) {
  if (!exactKeys(i, ['schema', 'request_id', 'ground', 'coordinate', 'projection']) ||
      i.schema !== INTENT || i.request_id !== 'room001-portable-intention' ||
      i.projection !== 'value') fail('intent contract');
  const g = i.ground;
  if (!exactKeys(g, ['family', 'a', 'c', 'modulus', 'seed']) || g.family !== 'affine_mod' ||
      !Number.isSafeInteger(g.modulus) || g.modulus < 2 || g.modulus > 65521 ||
      !['a','c','seed'].every(k => Number.isSafeInteger(g[k]) && g[k] >= 0 && g[k] < g.modulus) ||
      !Number.isSafeInteger(i.coordinate) || i.coordinate < 0 || i.coordinate > MAX_COORD) fail('Ground bounds');
}
export function affine(i) {
  checkIntent(i);
  const {a,c,seed,modulus} = i.ground;
  const mod = BigInt(modulus);
  let p=1n,q=0n,mul=BigInt(a),add=BigInt(c),t=BigInt(i.coordinate);
  while(t) {
    if(t & 1n) {p=p*mul%mod; q=(q*mul+add)%mod;}
    add=add*(mul+1n)%mod;mul=mul*mul%mod;t>>=1n;
  }
  return Number((p*BigInt(seed)+q)%mod);
}
export async function verifyCapsule(c, pins = {}) {
  if(!exactKeys(c,['schema','intention','receipts']) || c.schema !== CAPSULE) fail('capsule schema');
  checkIntent(c.intention);
  const root = await digest(c.intention);
  if (pins.intention && pins.intention !== root) fail('external intention pin');
  if(!Array.isArray(c.receipts) || c.receipts.length < 1 || c.receipts.length > 3) fail('chain length');
  let previous=ZERO;
  for (let n=0;n<c.receipts.length;n++) {
    const r=c.receipts[n];
    if (!exactKeys(r,['schema','generation','predecessor','intention_digest','room','method','value','status','digest']) ||
       r.schema !== RECEIPT || r.generation !== n+1 || r.room !== ROOMS[n] || r.method !== METHODS[n] ||
       r.predecessor !== previous || r.intention_digest !== root || r.status !== 'finite-ground-checked' ||
       !Number.isSafeInteger(r.value) || r.value !== affine(c.intention)) fail('receipt semantic chain');
    const copy={...r};delete copy.digest;
    if (await digest(copy) !== r.digest) fail('receipt content hash');
    previous=r.digest;
  }
  if(pins.head && pins.head !== previous) fail('external head pin / rollback');
  if(pins.generation && pins.generation !== c.receipts.length) fail('generation pin');
  return previous;
}
export async function append(c, room, method) {
  const head=await verifyCapsule(c);
  if (c.receipts.length > 2 || room !== ROOMS[c.receipts.length] || method !== METHODS[c.receipts.length]) fail('unsupported role/order');
  const value=affine(c.intention);
  const record={schema:RECEIPT, generation:c.receipts.length+1, predecessor:head,
                intention_digest:await digest(c.intention), room, method, value,
                status:'finite-ground-checked'};
  record.digest=await digest(record);
  const output={schema:CAPSULE,intention:c.intention,receipts:[...c.receipts,record]};
  await verifyCapsule(output);
  return output;
}
/** Only a real DO storage.transaction provides concurrent transactional admission.
 * The local adapter intentionally runs a single writer for a test demonstration. */
export async function advanceDurable(storage, submittedCapsule, expectedHead, trusted) {
  if (!/^[0-9a-f]{64}$/.test(trusted.intention) || !/^[0-9a-f]{64}$/.test(trusted.bootstrap)) fail('missing receiver pins');
  if (!/^[0-9a-f]{64}$/.test(expectedHead)) fail('missing current high-water');
  return storage.transaction(async tx => {
    const stored=await tx.get('capsule');
    const old=stored ?? submittedCapsule;
    const head=await verifyCapsule(old,{intention:trusted.intention});
    if (stored === undefined || stored === null) {
      if (head !== trusted.bootstrap || old.receipts.length !== 1) fail('unauthorized bootstrap');
    } else if (canonical(old) !== canonical(submittedCapsule)) fail('conflicting replay / stale capsule');
    if (expectedHead !== head) fail('stale current-head challenge');
    if (old.receipts.length !== 1) fail('DO stage already committed');
    const next=await append(old,'durable-object','js-event-affine');
    await tx.put('capsule',next);
    return next;
  });
}
