/** Local deterministic contract emulation, NOT a workerd or Cloudflare run. */
import fs from 'node:fs/promises';
import path from 'node:path';
import {advanceDurable,verifyCapsule} from './room_core.mjs';
const [inDir,outDir]=process.argv.slice(2);
if(!inDir||!outDir) throw Error('usage: node local_worker_cli.mjs INPUT_DIR OUTPUT_DIR');
await fs.mkdir(outDir,{recursive:true});
const cap=JSON.parse(await fs.readFile(path.join(inDir,'capsule.json'),'utf8'));
const pol=JSON.parse(await fs.readFile(path.join(inDir,'policy.json'),'utf8'));
const statePath=path.join(outDir,'durable-store.json');
let data={}; try{data=JSON.parse(await fs.readFile(statePath,'utf8'));}catch(e){if(e.code!=='ENOENT')throw e;}
const adapter={
 async transaction(fn) {
   const staging=structuredClone(data);
   const storage={async get(k){return staging[k];},async put(k,v){staging[k]=structuredClone(v);}};
   const result=await fn(storage);
   const tmp=statePath+'.tmp';await fs.writeFile(tmp,JSON.stringify(staging));await fs.rename(tmp,statePath);
   data=staging;return result;
 }
};
const newCap=await advanceDurable(adapter,cap,pol.expected_head,{intention:pol.intention_digest,bootstrap:pol.expected_head});
const head=await verifyCapsule(newCap,{intention:pol.intention_digest,generation:2});
const next={...pol,expected_head:head,generation:2};
await fs.writeFile(path.join(outDir,'capsule.json'),JSON.stringify(newCap,null,2)+'\n');
await fs.writeFile(path.join(outDir,'policy.json'),JSON.stringify(next,null,2)+'\n');
console.log(JSON.stringify({status:'durable-object-contract-simulator',generation:2,head,pid:process.pid}));
