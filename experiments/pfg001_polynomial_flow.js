"use strict";
// PFG-001: exact finite Boolean observable recurrence; research-only.
function experiment(){
  const assert=(v,m)=>{if(!v)throw Error(m)};
  const bit=i=>1n<<BigInt(i);
  const xor=(s,m)=>{if(s.has(m))s.delete(m);else s.add(m)};
  const add=(a,b)=>{const s=new Set(a);for(const m of b)xor(s,m);return s};
  const degree=m=>{let d=0;while(m){m&=m-1n;d++}return d};
  const same=(a,b)=>a.size===b.size&&[...a].every(x=>b.has(x));
  const poly=(...m)=>new Set(m);
  const terms=m=>{const a=[];while(m){let b=m&-m;a.push(b.toString(2).length-1);m^=b}return a};
  const evalp=(p,x)=>{let b=0;for(const m of p)if((m&x)===m)b^=1;return b};
  const pull=(p,F,budget)=>{let out=poly();for(const m of p){let a=poly(0n);for(const i of terms(m)){let b=poly();for(const u of a)for(const v of F[i]){if(++budget.work>budget.limit)throw Error("work budget");xor(b,u|v)}a=b;if(a.size>budget.terms)throw Error("term budget")}out=add(out,a);if(out.size>budget.terms)throw Error("term budget")}return out};
  // Independent checker: expand each source monomial by depth-first enumeration,
  // then sort and count equal coefficient occurrences instead of set toggling.
  const checkedPull=(p,F,budget)=>{let raw=[];for(const m of p){const ids=terms(m);function visit(j,v){if(++budget.work>budget.limit)throw Error("checker work budget");if(j===ids.length){raw.push(v);return}for(const u of F[ids[j]])visit(j+1,v|u)}visit(0,0n)}raw.sort((a,b)=>a<b?-1:a>b?1:0);let out=poly();for(let i=0;i<raw.length;){let j=i+1;while(j<raw.length&&raw[j]===raw[i])j++;if((j-i)%2)out.add(raw[i]);i=j}return out};
  const pivot=s=>{let p=-1n;for(const x of s)if(x>p)p=x;return p};
  function form(F,h,maxRank=256,limit=20000000){
    const budget={work:0,limit,terms:20000}, seq=[], rows=new Map();let p=h;
    for(let k=0;k<=maxRank;k++){
      let v=new Set(p), c=bit(k);
      while(v.size){let z=rows.get(pivot(v));if(!z)break;v=add(v,z.v);c^=z.c}
      if(!v.size)return {seq,relation:c,work:budget.work};
      if(k===maxRank)throw Error("rank budget");
      rows.set(pivot(v),{v,c});seq.push(p);p=pull(p,F,budget);
    }
  }
  function verify(F,h,g,limit=20000000){
    assert(g.seq.length>0 && same(g.seq[0],h),"wrong observer");
    const b={work:0,limit},r=g.seq.length;
    assert(g.relation>=bit(r)&&g.relation<bit(r+1),"wrong degree");
    for(let i=1;i<r;i++)assert(same(checkedPull(g.seq[i-1],F,b),g.seq[i]),"false ancestry");
    let rhs=poly();for(let i=0;i<r;i++)if(g.relation&bit(i))rhs=add(rhs,g.seq[i]);
    assert(same(checkedPull(g.seq[r-1],F,b),rhs),"false recurrence");
    // Independent low-pivot elimination proves least scalar recurrence.
    const rows=new Map();
    for(let p of g.seq){let v=new Set(p);while(v.size){let z=[...v].reduce((a,b)=>a<b?a:b);if(!rows.has(z)){rows.set(z,v);break}v=add(v,rows.get(z))}assert(v.size,"dependent ancestry")}
    return b.work;
  }
  function remainder(t,g){
    assert(typeof t==="bigint"&&t>=0n,"invalid time");
    const r=g.seq.length, top=bit(r);let count=0;
    function mul(a,b){let out=0n;while(b){count++;if(b&1n)out^=a;b>>=1n;a<<=1n;if(a&top)a^=g.relation}return out}
    let a=1n,x=r===1?g.relation^top:2n;
    while(t){if(t&1n)a=mul(a,x);t>>=1n;if(t)x=mul(x,x)}
    return {a,count};
  }
  function observe(g,state,t){const {a,count}=remainder(t,g);let out=0;for(let i=0;i<g.seq.length;i++)if(a&bit(i))out^=evalp(g.seq[i],state);return {out,count}}
  function source(a,b,ta,tb){
    const F=[];for(let i=0;i<a-1;i++)F.push(poly(bit(i+1)));
    F.push(poly(...ta.map(bit)));for(let i=0;i<b-1;i++)F.push(poly(bit(a+i+1)));
    F.push(poly(...tb.map(i=>bit(a+i))));F.push(poly(bit(a+b),bit(0)|bit(a)));
    return F;
  }
  function lfsr(x,n,taps){let v=0n;for(const i of taps)v^=(x>>BigInt(i))&1n;return (x>>1n)|(v<<BigInt(n-1))}
  function period(n,taps){let x=1n,t=0;do{x=lfsr(x,n,taps);t++;assert(t<=2**n,"bad cycle")}while(x!==1n);return t}
  function direct(x,y,z,t,a,b,ta,tb){for(let i=0;i<t;i++){z^=Number((x&1n)&(y&1n));x=lfsr(x,a,ta);y=lfsr(y,b,tb)}return z}
  const pack=(x,y,z,a,b)=>x|(y<<BigInt(a))|(BigInt(z)<<BigInt(a+b));
  let report={};
  const a=11,b=13,ta=[0,2],tb=[0,1,3,4],F=source(a,b,ta,tb),h=poly(bit(a+b));
  const p=period(a,ta),q=period(b,tb);assert(p===2047&&q===8191,"nonprimitive fixture");
  const g=form(F,h), checked=verify(F,h,g);
  let seed=341n;function rand(){seed=(1664525n*seed+1013904223n)&0xffffffffn;return seed}
  let maxCount=0;
  for(let i=0;i<192;i++){const x=rand()%2048n,y=rand()%8192n,z=Number(rand()&1n),t=Number(rand()%2000n);let got=observe(g,pack(x,y,z,a,b),BigInt(t));assert(got.out===direct(x,y,z,t,a,b,ta,tb),"replay mismatch");maxCount=Math.max(maxCount,got.count)}
  const huge=BigInt(p*q)*10n**100n+1234n;
  for(let i=0;i<64;i++){const x=rand()%2047n+1n,y=rand()%8191n+1n,z=Number(rand()&1n);assert(observe(g,pack(x,y,z,a,b),huge).out===direct(x,y,z,1234,a,b,ta,tb),"huge mismatch")}
  const small=source(2,3,[0,1],[0,1]),sg=form(small,poly(bit(5)));verify(small,poly(bit(5)),sg);
  let exhaustive=0;
  for(let x=0n;x<64n;x++)for(let t=0;t<43;t++){assert(observe(sg,x,BigInt(t)).out===direct(x&3n,(x>>2n)&7n,Number(x>>5n),t,2,3,[0,1],[0,1]),"small mismatch");exhaustive++}
  let tamper=false;try{verify(F,h,{...g,relation:g.relation^1n})}catch(e){tamper=true}assert(tamper,"tampered recurrence admitted");
  const counter=n=>Array.from({length:n},(_,i)=>poly(bit(i),bit(i)-1n));
  const ranks=[];for(let n=2;n<=7;n++){let f=counter(n),o=poly(bit(n-1)),c=form(f,o,128);verify(f,o,c);assert(c.seq.length===2**(n-1)+1,"counter rank mismatch");ranks.push([n,c.seq.length])}
  let refused=false;try{form(counter(8),poly(bit(7)),32)}catch(e){assert(e.message==="rank budget","unexpected refusal");refused=true}assert(refused,"rank cap ignored");
  report={source_bits:a+b+1,source_states:(1n<<BigInt(a+b+1)).toString(),joint_period:p*q,rank:g.seq.length,max_degree:Math.max(...g.seq.flatMap(p=>[...p].map(degree))),total_basis_terms:g.seq.reduce((s,p)=>s+p.size,0),compile_products:g.work,checker_visits:checked,moderate_checks:192,exhaustive_small_checks:exhaustive,huge_checks:64,huge_coordinate:huge.toString(),huge_remainder_inner_iterations:remainder(huge,g).count,max_moderate_remainder_iterations:maxCount,coefficient_tamper_refused:tamper,counter_ranks:ranks,counter_budget_refused:refused};
  return report;
}
console.log(JSON.stringify(experiment(), null, 2));
