/** Deployable Cloudflare Worker / Durable Object adapter.
 * Explicit deployment and credentials required; not deployed by this PR.
 * Needs ROOM_TOKEN, INTENTION_SHA256 and BOOTSTRAP_HEAD configured as trusted
 * secrets / environment values. Remote requests cannot supply those pins. */
import { DurableObject } from 'cloudflare:workers';
import { advanceDurable } from './room_core.mjs';

export class PortableRoom extends DurableObject {
  constructor(ctx, env) { super(ctx, env); }
  async advance(capsule, expectedHead) {
    return advanceDurable(this.ctx.storage, capsule, expectedHead,
      {intention:this.env.INTENTION_SHA256,bootstrap:this.env.BOOTSTRAP_HEAD});
  }
  async snapshot() { return (await this.ctx.storage.get('capsule')) ?? null; }
}

function tokenEqual(a,b) {
  if(typeof a !== 'string' || typeof b !== 'string' || b.length < 32 || a.length !== b.length) return false;
  let diff=0; for(let i=0;i<a.length;i++) diff|=a.charCodeAt(i)^b.charCodeAt(i);return diff===0;
}
export default {
  async fetch(request,env) {
    const u=new URL(request.url);
    if(!tokenEqual(request.headers.get('authorization'),`Bearer ${env.ROOM_TOKEN}`)) return new Response('forbidden',{status:403});
    if(!env.ROOMS || !/^[0-9a-f]{64}$/.test(env.INTENTION_SHA256 || '') ||
      !/^[0-9a-f]{64}$/.test(env.BOOTSTRAP_HEAD || '')) return new Response('unconfigured',{status:503});
    const stub=env.ROOMS.getByName('room001');
    try {
      if(u.pathname==='/snapshot' && request.method==='GET') return Response.json(await stub.snapshot());
      if(u.pathname==='/advance' && request.method==='POST') {
        if(Number(request.headers.get('content-length')) > 16384) return new Response('oversized',{status:413});
        const raw=await request.text();
        if(raw.length > 16384) return new Response('oversized',{status:413});
        const body=JSON.parse(raw);
        if(body===null||typeof body!=='object'||Object.keys(body).sort().join(',')!=='capsule,expected_head') throw Error('request fields');
        return Response.json(await stub.advance(body.capsule,body.expected_head));
      }
    } catch(e) {return Response.json({status:'refused',reason:String(e).slice(0,240)},{status:409});}
    return new Response('not found',{status:404});
  }
};
