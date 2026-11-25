"use strict";
function campaign(){
const assert=(v,m)=>{if(!v)throw Error(m)},mod=(x,m)=>(x%m+m)%m;
const I=()=>[[1n,0n,0n],[0n,1n,0n],[0n,0n,1n]];
let multiplications=0;
function mul(a,b,m){multiplications+=27;return a.map((r,i)=>r.map((_,j)=>mod(r.reduce((s,x,k)=>s+x*b[k][j],0n),m)))}
function apply(A,x,m){return A.slice(0,2).map(r=>mod(r[0]*x[0]+r[1]*x[1]+r[2],m))}
function index(x,q){return Number(x[0]%BigInt(q))+q*Number(x[1]%BigInt(q))}
function residue(i,q){return [BigInt(i%q),BigInt(Math.floor(i/q))]}
function eq(a,b){return a.length===b.length&&a.every((x,i)=>Array.isArray(x)?eq(x,b[i]):x===b[i])}
let seed=20261125;function rand(n){seed^=seed<<13;seed^=seed>>>17;seed^=seed<<5;return(seed>>>0)%n}
function source(q,m,mode){let maps=[],N=q*q;for(let i=0;i<N;i++){let r=residue(i,q),j=mode==="cycle"?(i+1)%N:mode==="transient"?Math.min(i+1,N-1):rand(N),s=residue(j,q);let a=BigInt(1+2*rand(16)),b=BigInt(2*rand(16)),c=BigInt(2*rand(16)),d=BigInt(1+2*rand(16));if(i%2){b+=1n}else{c+=1n}let row=[[a,b,mod(s[0]-a*r[0]-b*r[1]+BigInt(q*rand(64)),m)],[c,d,mod(s[1]-c*r[0]-d*r[1]+BigInt(q*rand(64)),m)],[0n,0n,1n]];maps.push(row)}return {q,m,maps}}
function step(S,x){return apply(S.maps[index(x,S.q)],x,S.m)}
function compile(S,start){let r=start,seen=new Map(),path=[],P=[I()];while(!seen.has(r)){seen.set(r,path.length);path.push(r);P.push(mul(S.maps[r],P[P.length-1],S.m));r=index(apply(S.maps[r],residue(r,S.q),S.m),S.q)}let mu=seen.get(r),lambda=path.length-mu,C=[I()];for(let i=mu;i<path.length;i++)C.push(mul(S.maps[path[i]],C[C.length-1],S.m));return {start,path,mu,lambda,P,C}}
function verify(S,G){assert(G.path[0]===G.start&&G.path.length===G.mu+G.lambda&&G.lambda>0,"path shape");let seen=new Set(),p=I(),c=I();assert(eq(G.P[0],p)&&eq(G.C[0],c),"identity");for(let i=0;i<G.path.length;i++){let r=G.path[i];assert(!seen.has(r),"distinct");seen.add(r);let expected=i+1<G.path.length?G.path[i+1]:G.path[G.mu];assert(index(apply(S.maps[r],residue(r,S.q),S.m),S.q)===expected,"successor");p=mul(S.maps[r],p,S.m);assert(eq(p,G.P[i+1]),"prefix");if(i>=G.mu){c=mul(S.maps[r],c,S.m);assert(eq(c,G.C[i-G.mu+1]),"cycle prefix")}}return true}
function jump(S,G,x,t){assert(index(x,S.q)===G.start,"start");if(t<BigInt(G.mu))return apply(G.P[Number(t)],x,S.m);let n=t-BigInt(G.mu),k=n/BigInt(G.lambda),rem=Number(n%BigInt(G.lambda));let y=apply(G.P[G.mu],x,S.m),B=G.C[G.lambda];while(k){if(k&1n)y=apply(B,y,S.m);k>>=1n;if(k)B=mul(B,B,S.m)}return apply(G.C[rem],y,S.m)}
let direct=0,semigroup=0,huge=0,certs=0,nonlinear=0,noncommute=0,coarse=0;let examples=[];
for(let i=0;i<36;i++){let q=[2,4,8][i%3],m=BigInt(q)*(1n<<BigInt(10+i%9)),S=source(q,m,["cycle","transient","random"][Math.floor(i/3)%3]);let s0=rand(q*q),G=compile(S,s0);verify(S,G);certs++;
let x0=residue(s0,q);for(let j=0;j<18;j++){let x=x0.map(v=>v+BigInt(q*rand(Number(m)/q))),t=rand(400),y=x;for(let k=0;k<t;k++)y=step(S,y);assert(eq(y,jump(S,G,x,BigInt(t))),"direct");direct++;let u=(1n<<100n)+BigInt(rand(10000)),v=(1n<<91n)+BigInt(rand(10000));let mid=jump(S,G,x,u);let H=compile(S,index(mid,q));assert(eq(jump(S,H,mid,v),jump(S,G,x,u+v)),"semigroup");semigroup++}
let A=S.maps[0],B=S.maps[1];if(!eq(mul(A,B,m),mul(B,A,m)))noncommute++;
let z=[0n,0n],e=[1n,0n],f=[0n,1n],ef=[1n,1n],F=step(S,z),U=step(S,e),V=step(S,f),W=step(S,ef);if(W.some((v,k)=>mod(v-U[k]-V[k]+F[k],m)!==0n))nonlinear++;
if(q>2){for(let r=0;r<q*q;r++){let x=residue(r,q),y=[x[0]%2n,x[1]%2n];if(index(x,q)!==index(y,q)&&!eq(S.maps[index(x,q)],S.maps[index(y,q)])){coarse++;break}}}
}
let S=source(8,1n<<40n,"cycle"),G=compile(S,0);let before=multiplications;verify(S,G);let admission=multiplications-before;let x=[123456789120n,98765432128n],t=10n**100n+123n;before=multiplications;let y=jump(S,G,x,t);let queryMatrixMultiplications=(multiplications-before)/27;let k=t/64n,r=Number(t%64n); // independent cycle check: construct row-major return using right-to-left recurrence on each basis vector
let expected=x;for(let j=0;j<r;j++)expected=step(S,expected); // commute? remainder after cycles, cannot move before cycle without changing phase; independently compute path return using images of 0,e1,e2.
function loop(v){for(let j=0;j<64;j++)v=step(S,v);return v}
let o=loop([0n,0n]); // these basis inputs do NOT share residue 0; cannot use unit basis on switched source. use explicit fixed path instead.
function fixed(v){for(let j=0;j<64;j++)v=apply(S.maps[j],v,S.m);return v}
let w=fixed([0n,0n]),p=fixed([1n,0n]),q=fixed([0n,1n]);let R=[[mod(p[0]-w[0],S.m),mod(q[0]-w[0],S.m),w[0]],[mod(p[1]-w[1],S.m),mod(q[1]-w[1],S.m),w[1]],[0n,0n,1n]];
assert(eq(R,G.C[64]),"return map");let pow=I();while(k){if(k&1n)pow=mul(pow,R,S.m);R=mul(R,R,S.m);k>>=1n}let independent=apply(pow,x,S.m);for(let j=0;j<r;j++)independent=step(S,independent);assert(eq(y,independent),"huge independent");huge++;
let forged={...G,path:[...G.path]};[forged.path[2],forged.path[3]]=[forged.path[3],forged.path[2]];let rejected=false;try{verify(S,forged)}catch(e){rejected=true}assert(rejected,"forgery");
return {direct,semigroup,certs,nonlinear,noncommute,coarse,huge,forgeryRejected:rejected,example:{modulus:S.m.toString(),fullStates:(S.m*S.m).toString(),quotientStates:64,cycle:G.lambda,transient:G.mu,coordinate:t.toString(),initial:x.map(String),result:y.map(String),queryMatrixMultiplications,admissionMatrixMultiplications:admission/27,sourceMatrices:64}}
}
console.log(JSON.stringify(campaign(),null,2));
