"use strict";
function campaign(){
const need=(x,m)=>{if(!x)throw Error(m)},par=x=>{let p=0;while(x){p^=1;x&=x-1n}return p},xorRows=(mask,rows)=>{let v=0n;for(let i=0;mask;i++,mask>>=1n)if(mask&1n)v^=rows[i];return v},evalRows=(rows,x)=>rows.reduce((v,r,i)=>v|(BigInt(par(r&x))<<BigInt(i)),0n);
const n=128, m=1n<<40n, high=((1n<<128n)-1n)^7n;
const features=[0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa8n|1n,0xccccccccccccccccccccccccccccccc8n|2n,0xf0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0n|4n];
const id=Array.from({length:n},(_,i)=>1n<<BigInt(i));
// Conjugate small control transitions by triangular change of coordinates.
// Update the hidden coordinates by rotation and shear; compensate low rows.
const rows=[0,1].map(branch=>{let Q=[features[1],features[2],features[0]^(branch?features[1]:0n)];let R=id.slice();for(let i=3;i<n;i++)R[i]=id[3+(i-3+1)%(n-3)]^(i===3?features[branch]:0n);for(let i=0;i<3;i++)R[i]=Q[i]^xorRows(features[i]&high,R);return R});
const matrices=[[[1n,1n,0n],[0n,1n,1n],[0n,0n,1n]],[[1n,0n,2n],[1n,1n,0n],[0n,0n,1n]]];
const basis=[], pivots=new Map();function reduce(v){let code=0n;while(v){let p=v.toString(2).length-1;if(!pivots.has(p))break;let [r,c]=pivots.get(p);v^=r;code^=c}return [v,code]}
function insert(v){let [r]=reduce(v);if(r){pivots.set(r.toString(2).length-1,[r,1n<<BigInt(basis.length)]);basis.push(r)}}
insert(features[0]);insert(features[1]);let pulls=0;for(let i=0;i<basis.length;i++)for(let R of rows){insert(xorRows(basis[i],R));pulls++}
function code(v){let [r,c]=reduce(v);need(r===0n,"closure");return c}
const codes=rows.map(R=>basis.map(b=>code(xorRows(b,R)))),guard=[code(features[0]),code(features[1])];
for(let b=0;b<2;b++)for(let i=0;i<basis.length;i++)need(xorRows(codes[b][i],basis)===xorRows(basis[i],rows[b]),"certificate");
const select=(z,g)=>par(z&g[0])&par(z&g[1]);
const branch=c=>select(c,features), gbranch=z=>select(z,guard);
const I=[[1n,0n,0n],[0n,1n,0n],[0n,0n,1n]],mul=(A,B)=>A.map(r=>B[0].map((_,j)=>r.reduce((s,x,k)=>s+x*B[k][j],0n)%m)),apply=(A,z)=>A.slice(0,2).map(r=>(r[0]*z[0]+r[1]*z[1]+r[2])%m);
const compose=(A,B)=>A.map(r=>xorRows(r,B));
const eq=(a,b)=>a.every((v,i)=>v===b[i]);
function step(c,z){let b=branch(c);return [evalRows(rows[b],c),apply(matrices[b],z)]}
function form(c){let z=evalRows(basis,c),path=[],seen=new Map();while(!seen.has(z)){seen.set(z,path.length);let b=gbranch(z);path.push(b);z=evalRows(codes[b],z)}return {path,mu:seen.get(z),lambda:path.length-seen.get(z)}}
function jump(c,z,t){let {path,mu,lambda}=form(c);function run(seq){for(let b of seq){c=evalRows(rows[b],c);z=apply(matrices[b],z)}}if(t<BigInt(mu)){run(path.slice(0,Number(t)));return[c,z]}run(path.slice(0,mu));let cyc=path.slice(mu),k=(t-BigInt(mu))/BigInt(lambda),rem=Number((t-BigInt(mu))%BigInt(lambda));let B=id,C=I;for(let b of cyc){B=compose(rows[b],B);C=mul(matrices[b],C)}while(k){if(k&1n){c=evalRows(B,c);z=apply(C,z)}k>>=1n;if(k){B=compose(B,B);C=mul(C,C)}}run(cyc.slice(0,rem));return[c,z]}
let seed=20261125;function rnd(){seed^=seed<<13;seed^=seed>>>17;seed^=seed<<5;return BigInt(seed>>>0)}
let direct=0,semigroup=0,closure=0,paths=new Set(),maxPath=0;
for(let i=0;i<128;i++){let c=(rnd()<<96n)|(rnd()<<64n)|(rnd()<<32n)|rnd(),z=[rnd(),rnd()],t=i*3%113;let q=evalRows(basis,c),b=branch(c);need(b===gbranch(q),"guard");need(evalRows(basis,evalRows(rows[b],c))===evalRows(codes[b],q),"projection");closure++;let f=form(c);paths.add(f.path.join(",")+":"+f.mu);maxPath=Math.max(maxPath,f.path.length);let a=c,p=z;for(let j=0;j<t;j++)[a,p]=step(a,p);let [x,y]=jump(c,z,BigInt(t));need(a===x&&eq(p,y),"direct");direct++;let u=10n**40n+BigInt(i),v=10n**31n+BigInt(i*5);let [mid,w]=jump(c,z,u),[end,e]=jump(mid,w,v),[final,fz]=jump(c,z,u+v);need(end===final&&eq(e,fz),"semigroup");semigroup++}
let rejected=false;try{let [r]=reduce(1n<<127n);need(r===0n,"outside closure")}catch(e){rejected=true}need(rejected,"negative");
let witness=null;for(let i=0;i<8&&!witness;i++)for(let j=i+1;j<8;j++){let x=BigInt(i),y=BigInt(j);if((evalRows(features.slice(0,2),x)===evalRows(features.slice(0,2),y))&&branch(evalRows(rows[branch(x)],x))!==branch(evalRows(rows[branch(y)],y))){witness=[i,j];break}}
let t=10n**100n+123n,c=7n,z=[123456789120n,98765432128n],[out,p]=jump(c,z,t);
return {controlBits:n,physicalStateBits:n+80,guardFeatures:2,closedFeatures:basis.length,pullbacks:pulls,quotientStates:2**basis.length,direct,semigroup,closure,distinctPaths:paths.size,maxPath,insufficientGuardWitness:witness,unclosedFeatureRejected:rejected,huge:{coordinate:t.toString(),control:out.toString(16),payload:p.map(String),initialControl:c.toString(),initialPayload:z.map(String)}}
}
console.log(JSON.stringify(campaign(),null,2));
