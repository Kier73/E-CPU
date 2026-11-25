"use strict";
function campaign(){
 const mod=(x,m)=>(x%m+m)%m,eq=(a,b)=>JSON.stringify(a.map(r=>r.map(String)))===JSON.stringify(b.map(r=>r.map(String))),need=(x,m)=>{if(!x)throw Error(m)};
 const q=8,m=1n<<40n,h=m/8n,I=[[1n,0n,0n],[0n,1n,0n],[0n,0n,1n]];
 const apply=(A,x)=>A.slice(0,2).map(r=>mod(r[0]*x[0]+r[1]*x[1]+r[2],m));
 const mul=(A,B)=>A.map((r,i)=>r.map((_,j)=>mod(r.reduce((s,a,k)=>s+a*B[k][j],0n),m)));
 const idx=x=>Number(x[0]%8n)+8*Number(x[1]%8n),rep=r=>[BigInt(r%8),BigInt(r>>3)];
 const raw=Array.from({length:64},(_,r)=>{const [x,y]=rep(r),A=x%2n===0n?[[1n,1n,0n],[0n,1n,1n],[0n,0n,1n]]:[[1n,1n,1n],[0n,1n,0n],[0n,0n,1n]];let B=A.map(row=>[...row]);B[0][0]+=h*x;B[0][1]+=h*y;B[0][2]=mod(B[0][2]-h*x*x-h*y*y,m);return B});
 const normalized=raw.map((A,r)=>{let [x,y]=rep(r);return A.slice(0,2).map(([a,b,c])=>[a%h,b%h,mod(c+(a-a%h)*x+(b-b%h)*y,m)]).concat([[0n,0n,1n]])});
 const key=A=>JSON.stringify(A.map(r=>r.map(String))),labels=normalized.map(key),successors=raw.map((A,r)=>idx(apply(A,rep(r))));
 function partition(keys){let ids=new Map();return keys.map(k=>{if(!ids.has(k))ids.set(k,ids.size);return ids.get(k)})}
 let classes=partition(labels),rounds=0;for(;;){let n=partition(classes.map((g,r)=>`${g},${classes[successors[r]]}`));if(n.every((v,i)=>v===classes[i]))break;classes=n;rounds++}
 let N=Math.max(...classes)+1,repr=Array.from({length:N},(_,i)=>classes.indexOf(i)),mat=repr.map(i=>normalized[i]),succ=repr.map(i=>classes[successors[i]]);
 let pairChecks=0,distinguishable=0,maxDepth=0;for(let i=0;i<64;i++)for(let j=i+1;j<64;j++){let a=i,b=j,seen=new Set(),depth=0,found=false;while(!seen.has(`${a}:${b}`)){seen.add(`${a}:${b}`);if(labels[a]!==labels[b]){found=true;maxDepth=Math.max(maxDepth,depth);break}a=successors[a];b=successors[b];depth++}need(found===(classes[i]!==classes[j]),"minimal");pairChecks++;distinguishable+=Number(found)}
 function step(x){return apply(raw[idx(x)],x)}
 function jump(x,t){let s=classes[idx(x)],seen=new Map(),path=[],prefix=[I];while(!seen.has(s)){seen.set(s,path.length);path.push(s);prefix.push(mul(mat[s],prefix[prefix.length-1]));s=succ[s]}let mu=seen.get(s),period=path.length-mu;if(t<BigInt(mu))return apply(prefix[Number(t)],x);let k=(t-BigInt(mu))/BigInt(period),tail=Number((t-BigInt(mu))%BigInt(period)),C=[I];for(let s of path.slice(mu))C.push(mul(mat[s],C[C.length-1]));let y=apply(prefix[mu],x),B=C[period];while(k){if(k&1n)y=apply(B,y);k>>=1n;if(k)B=mul(B,B)}return apply(C[tail],y)}
 let direct=0,semigroup=0,fibre=0;for(let r=0;r<64;r++)for(let j=0;j<16;j++){let x=rep(r).map((v,i)=>v+8n*BigInt((r+1)*(j+31)*(i+3))),t=BigInt((r*17+j*31)%500);need(apply(raw[r],x).every((v,i)=>v===apply(normalized[r],x)[i]),"fibre");fibre++;let y=x;for(let k=0n;k<t;k++)y=step(y);need(y.every((v,i)=>v===jump(x,t)[i]),"direct");direct++;let a=10n**70n+BigInt(r),b=10n**59n+BigInt(j);need(jump(jump(x,a),b).every((v,i)=>v===jump(x,a+b)[i]),"semigroup");semigroup++}
 return {fullStates:(m*m).toString(),declaredResidues:64,rawActionLabels:new Set(raw.map(key)).size,normalizedActionLabels:new Set(labels).size,minimalSwitchingClasses:N,refinementRounds:rounds,checkedPairs:pairChecks,distinguishable,maxDistinguishingDepth:maxDepth,fibre,direct,semigroup,classes:classes.slice(0,16),example:{coordinate:(10n**100n+123n).toString(),initial:["123456789120","98765432128"],result:jump([123456789120n,98765432128n],10n**100n+123n).map(String)}}
}
console.log(JSON.stringify(campaign(),null,2));
