#define _GNU_SOURCE
#include <inttypes.h>
#include <pthread.h>
#include <sched.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <errno.h>

/* FAB-012: asynchronous effect journals plus navigable pure regions. */
enum { MAX_WORKERS=16, MAX_ROUNDS=8, MAX_CYCLES=1024 };
enum { MUL, ADD, SEND, RECV, BRANCH, ADD_BRANCH, XOR_BRANCH, STORE, HALT };
struct effect { uint32_t sent, received, stored; };
struct affine { uint32_t a,b; };
struct worker { unsigned lo,hi; uint64_t steps,stalls,sends,receives,stores,transitions,leaps; atomic_uint frontier; };
static unsigned n, rounds, cycles, span, pure; static int leap;
static _Atomic uint64_t *cpu;
static struct effect *journal;
static struct affine powers[4][11];
static const uint32_t multiplier[4]={5,7,0,UINT32_C(4294967295)};
static const uint32_t increment[4]={3,19,123456789,100};
static atomic_uint ready, start, done;
static void check(int v,const char*s){if(!v){fprintf(stderr,"FAIL: %s\n",s);exit(2);}}
static double now(void){struct timespec t;check(clock_gettime(CLOCK_MONOTONIC,&t)==0,"clock");return t.tv_sec+t.tv_nsec*1e-9;}
static unsigned number(const char*s){char*e;errno=0;unsigned long x=strtoul(s,&e,10);check(*s>='0'&&*s<='9'&&!*e&&!errno&&x<=UINT32_MAX,"invalid argument");return (unsigned)x;}
static uint32_t initial(unsigned id){return id*UINT32_C(2654435761)+17;}
static unsigned peer(unsigned id,unsigned r){return id^((n>>1)|(1u<< (r% (31u-__builtin_clz(n>>1)))));}
static uint64_t pack(unsigned t,unsigned p,uint32_t x){return ((uint64_t)t<<40)|((uint64_t)p<<32)|x;}
static unsigned tick(uint64_t v){return (unsigned)(v>>40);}
static unsigned pc(uint64_t v){return (unsigned)(v>>32)&255;}
static struct effect *record(unsigned r,unsigned id){return &journal[(size_t)r*n+id];}
static struct affine compose(struct affine f,struct affine g){return (struct affine){f.a*g.a,f.a*g.b+f.b};}
static uint32_t apply(struct affine f,uint32_t x){return f.a*x+f.b;}
static uint32_t prefix(unsigned id,uint32_t x,unsigned p){unsigned q=p/2,k=0,g=id&3;while(q){if(q&1)x=apply(powers[g][k],x);q>>=1;k++;}if(p&1)x*=multiplier[g];return x;}
static uint32_t branch_value(uint32_t x){return x&1?x+UINT32_C(37):x^UINT32_C(0xa5a5a5a5);}
/* Every effect field is immutable after its owning instruction publishes it.
 * The receiver observes the actual peer's send record, never a predicted value. */
static int step(unsigned id,uint64_t s,struct worker*w){unsigned t=tick(s),r=t/span,p=t%span,phase=pc(s);uint32_t x=(uint32_t)s;unsigned next;
 if(phase==HALT)return 0;
 check(r<rounds,"clock range");struct effect*e=record(r,id);
 if(leap&&phase==MUL&&p==0){x=prefix(id,x,pure);atomic_store_explicit(&cpu[id],pack(t+pure,SEND,x),memory_order_release);w->steps+=pure;w->transitions++;w->leaps++;return 1;}
 switch(phase){
 case MUL: x*=multiplier[id&3];next=ADD;break;
 case ADD: x+=increment[id&3];next=p+1==pure?SEND:MUL;break;
 case SEND: e->sent=x;w->sends++;next=RECV;break;
 case RECV:{unsigned other=peer(id,r);uint64_t published=atomic_load_explicit(&cpu[other],memory_order_acquire);if(tick(published)<r*span+pure+1){w->stalls++;return 0;}e->received=record(r,other)->sent;x^=e->received;w->receives++;next=BRANCH;break;}
 case BRANCH:next=(x&1)?ADD_BRANCH:XOR_BRANCH;break;
 case ADD_BRANCH:x+=37;next=STORE;break;
 case XOR_BRANCH:x^=UINT32_C(0xa5a5a5a5);next=STORE;break;
 case STORE:e->stored=x;w->stores++;next=r+1==rounds?HALT:MUL;break;
 default:check(0,"unknown opcode");return 0;
 }
 atomic_store_explicit(&cpu[id],pack(t+1,next,x),memory_order_release);w->steps++;w->transitions++;return 1;
}
static void *run(void*arg){struct worker*w=arg;atomic_fetch_add_explicit(&ready,1,memory_order_release);while(!atomic_load_explicit(&start,memory_order_acquire))sched_yield();unsigned remaining=w->hi-w->lo;while(remaining){unsigned active=0,frontier=rounds*span;for(unsigned id=w->lo;id<w->hi;id++){uint64_t s=atomic_load_explicit(&cpu[id],memory_order_relaxed);if(pc(s)!=HALT){step(id,s,w);active++;}if(tick(s)<frontier)frontier=tick(s);}atomic_store_explicit(&w->frontier,frontier,memory_order_release);remaining=active;if(active)sched_yield();}atomic_fetch_add_explicit(&done,1,memory_order_release);return NULL;}
/* Snapshot clock is the publication frontier. History never consults a later
 * record. STORE is a versioned memory cell, visible only after publication. */
static uint64_t navigate(unsigned id,unsigned t,uint32_t *memory){unsigned r=t/span,p=t%span;check(t<=rounds*span,"uncommitted/outside history");uint32_t anchor=r?record(r-1,id)->stored:initial(id);*memory=r?anchor:0;if(r==rounds)return pack(t,HALT,anchor);unsigned phase;uint32_t x;
 if(p<=pure){x=prefix(id,anchor,p);phase=p==pure?SEND:(p&1?ADD:MUL);}
 else {struct effect*e=record(r,id);x=e->sent;check(x==prefix(id,anchor,pure),"send differs from pure Ground");phase=RECV;if(p>=pure+2){check(e->received==record(r,peer(id,r))->sent,"receive differs from committed sender");x^=e->received;phase=BRANCH;if(p>=pure+3){phase=x&1?ADD_BRANCH:XOR_BRANCH;if(p>=pure+4){x=branch_value(x);phase=STORE;}}}}
 return pack(t,phase,x);
}
/* Independent literal oracle: no power table, no navigator, no scheduler. */
static uint32_t replay_pure(unsigned id,uint32_t x,unsigned p){for(unsigned j=0;j<p;j++){if(j&1)x+=increment[id&3];else x*=multiplier[id&3];}return x;}
static uint64_t verify_all(void){uint32_t *anchor=malloc((size_t)n*4),*sent=malloc((size_t)n*4);check(anchor&&sent,"oracle allocation");for(unsigned id=0;id<n;id++)anchor[id]=initial(id);uint64_t checksum=0;for(unsigned r=0;r<rounds;r++){for(unsigned id=0;id<n;id++){sent[id]=replay_pure(id,anchor[id],pure);check(sent[id]==record(r,id)->sent,"oracle send mismatch");}for(unsigned id=0;id<n;id++){struct effect*e=record(r,id);uint32_t received=sent[peer(id,r)],x=sent[id]^received;check(e->received==received,"oracle receive mismatch");if(x%2)x+=37;else x^=UINT32_C(0xa5a5a5a5);check(x==e->stored,"oracle store mismatch");anchor[id]=x;}}for(unsigned id=0;id<n;id++){check(atomic_load(&cpu[id])==pack(rounds*span,HALT,anchor[id]),"oracle final mismatch");checksum+=anchor[id];}free(anchor);free(sent);return checksum;}
static uint32_t history_one(unsigned id,unsigned t){unsigned r=t/span,p=t%span;uint32_t anchor=r?record(r-1,id)->stored:initial(id),x=anchor,mem=0;unsigned phase=HALT;if(r<rounds){x=replay_pure(id,anchor,p<pure?p:pure);phase=p==pure?SEND:(p&1?ADD:MUL);if(p>pure)phase=RECV;if(p>=pure+2){x^=record(r,id)->received;phase=BRANCH;}if(p>=pure+3)phase=x%2?ADD_BRANCH:XOR_BRANCH;if(p>=pure+4){if(x%2)x+=37;else x^=UINT32_C(0xa5a5a5a5);phase=STORE;}}check(navigate(id,t,&mem)==pack(t,phase,x)&&mem==(r?anchor:0),"historical observation mismatch");return x;}
static uint64_t history(void){uint64_t sum=0;for(unsigned k=0;k<n;k++){unsigned id=(5*k+3)&(n-1),t=(unsigned)(((uint64_t)(id^UINT32_C(0x91a2b3))*UINT32_C(2654435761))%(rounds*span+1));sum+=history_one(id,t);}return sum;}
/* A history request is admitted only relative to an acquired publication. */
static int observe_history(unsigned id,unsigned requested,uint64_t publication,uint64_t*out,uint32_t*mem){if(requested>tick(publication))return 0;*out=navigate(id,requested,mem);return 1;}
int main(int argc,char**argv){check(argc==5||(argc==6&&(!strcmp(argv[5],"tamper")||!strcmp(argv[5],"leap"))),"usage: fab012 bits workers rounds pure_pairs [tamper|leap]");leap=argc==6&&!strcmp(argv[5],"leap");unsigned bits=number(argv[1]),workers=number(argv[2]);rounds=number(argv[3]);cycles=number(argv[4]);check(bits>=4&&bits<=24&&workers>=1&&workers<=MAX_WORKERS&&rounds>=1&&rounds<=MAX_ROUNDS&&cycles>=1&&cycles<=MAX_CYCLES,"bad geometry");n=1u<<bits;pure=2*cycles;span=pure+5;check((uint64_t)rounds*span<1u<<24,"clock overflow");cpu=malloc((size_t)n*sizeof(*cpu));journal=calloc((size_t)n*rounds,sizeof(*journal));check(cpu&&journal&&atomic_is_lock_free(cpu),"allocation/atomic width");for(unsigned id=0;id<n;id++)atomic_init(&cpu[id],pack(0,MUL,initial(id)));for(unsigned g=0;g<4;g++){powers[g][0]=(struct affine){multiplier[g],increment[g]};for(unsigned k=1;k<11;k++)powers[g][k]=compose(powers[g][k-1],powers[g][k-1]);for(unsigned p=0;p<=pure;p++)check(prefix(g,initial(g),p)==replay_pure(g,initial(g),p),"prefix calibration mismatch");}
 printf("machines=%u rounds=%u pure_instructions=%u state_bytes=%zu journal_bytes=%zu mode=%s\n",n,rounds,pure,(size_t)n*sizeof(*cpu),(size_t)n*rounds*sizeof(*journal),leap?"leap":"literal");fflush(stdout);pthread_t threads[MAX_WORKERS];struct worker w[MAX_WORKERS]={0};for(unsigned i=0;i<workers;i++){w[i].lo=(uint64_t)n*i/workers;w[i].hi=(uint64_t)n*(i+1)/workers;atomic_init(&w[i].frontier,0);check(!pthread_create(&threads[i],NULL,run,&w[i]),"worker creation");}while(atomic_load_explicit(&ready,memory_order_acquire)!=workers)sched_yield();double begin=now();atomic_store_explicit(&start,1,memory_order_release);uint64_t during=0,observations=0,seen_effects=0,live_history=0,refusals=0;for(unsigned pass=0;pass<3;pass++){if(pass){unsigned target=(pass-1)*span+pure+2; if(target>rounds*span)target=rounds*span;for(unsigned i=0;i<workers;i++)while(atomic_load_explicit(&w[i].frontier,memory_order_acquire)<target)sched_yield();}uint64_t active=0,effects=0;unsigned min=UINT32_MAX,max=0;double t0=now();for(unsigned k=0;k<n;k++){unsigned id=(5*k+3+pass*17)&(n-1);uint64_t s=atomic_load_explicit(&cpu[id],memory_order_acquire);unsigned t=tick(s);uint32_t memory;uint64_t observed;check(observe_history(id,t,s,&observed,&memory)&&observed==s,"live state mismatch");if(pass==1){unsigned past=(unsigned)(((uint64_t)id*2654435761u)%(t+1));check(observe_history(id,past,s,&observed,&memory)&&((uint32_t)observed)==history_one(id,past),"live historical mismatch");live_history++;check(!observe_history(id,t+1,s,&observed,&memory),"future coordinate admitted");refusals++;}if(t&&t<rounds*span)active++;if(t>=pure+1)effects++;if(t<min)min=t;if(t>max)max=t;}during+=active;observations+=n;seen_effects+=effects;printf("scan=%u observations=%u moving=%"PRIu64" effect_visible=%"PRIu64" min_tick=%u max_tick=%u seconds=%.6f\n",pass,n,active,effects,min,max,now()-t0);fflush(stdout);}uint64_t steps=0,stalls=0,sends=0,receives=0,stores=0,transitions=0,leaps=0;for(unsigned i=0;i<workers;i++){check(!pthread_join(threads[i],NULL),"worker join");steps+=w[i].steps;stalls+=w[i].stalls;sends+=w[i].sends;receives+=w[i].receives;stores+=w[i].stores;transitions+=w[i].transitions;leaps+=w[i].leaps;}check(atomic_load(&done)==workers,"unfinished workers");double elapsed=now()-begin;check(steps==(uint64_t)n*rounds*span&&sends==(uint64_t)n*rounds&&receives==sends&&stores==sends,"effect accounting mismatch");check(transitions==steps-leaps*(pure-1)&&leaps==(leap?(uint64_t)n*rounds:0),"transition accounting mismatch");if(argc==6&&!strcmp(argv[5],"tamper"))record(rounds-1,n-1)->received^=1;double t0=now();uint64_t sum=verify_all();double oracle=now()-t0;t0=now();uint64_t historic=history();double hist=now()-t0;printf("final machines=%u instructions=%"PRIu64" transitions=%"PRIu64" leaps=%"PRIu64" sends=%"PRIu64" receives=%"PRIu64" stores=%"PRIu64" stalls=%"PRIu64" live_observations=%"PRIu64" moving_observations=%"PRIu64" effect_visible=%"PRIu64" live_history=%"PRIu64" future_refusals=%"PRIu64" history=%u checksum=%"PRIu64" history_checksum=%"PRIu64" execution_seconds=%.6f oracle_seconds=%.6f history_seconds=%.6f\n",n,steps,transitions,leaps,sends,receives,stores,stalls,observations,during,seen_effects,live_history,refusals,n,sum,historic,elapsed,oracle,hist);unsigned cursor=0;for(unsigned k=0;k<(n<64?n:64);k++){unsigned id;if(k==0)id=0;else if(k==1)id=n-1;else{do{id=(UINT32_C(2654435761)*(cursor++))&(n-1);}while(id==0||id==n-1);}for(unsigned r=0;r<rounds;r++){struct effect*e=record(r,id);uint32_t anchor=r?record(r-1,id)->stored:initial(id);printf("sample id=%u round=%u peer=%u anchor=%u sent=%u received=%u stored=%u\n",id,r,peer(id,r),anchor,e->sent,e->received,e->stored);}}free(journal);free(cpu);return 0;}
