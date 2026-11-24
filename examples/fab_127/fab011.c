#define _GNU_SOURCE
#include <arpa/inet.h>
#include <errno.h>
#include <inttypes.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

/* FAB-011: live, address-identified CPU contexts and atomic temporal observations. */
enum { MAX_PROGRAMS=16, MAX_INS=16, MAX_WORKERS=16, MAX_TICK=0x0fffffff };
enum { ADD, MUL, JUMP };
struct ins { uint32_t op, arg; };
struct affine { uint32_t m,b; };
struct program { struct ins code[MAX_INS]; unsigned len; struct affine prefix[MAX_INS], power[28]; };
struct shard { unsigned lo,hi; uint64_t steps; atomic_uint sweeps; };
static struct program programs[MAX_PROGRAMS]; static unsigned np, count;
static _Atomic uint64_t *states; static uint32_t *previous;
static atomic_uint stop;
static void require(int ok,const char*msg){if(!ok){fprintf(stderr,"%s\n",msg);exit(2);}}
static void syscheck(int n,const char*s){if(n<0){perror(s);exit(1);}}
static double now(void){struct timespec t;syscheck(clock_gettime(CLOCK_MONOTONIC,&t),"clock");return t.tv_sec+t.tv_nsec*1e-9;}
static uint32_t initial(unsigned id){return id*UINT32_C(2654435761)+17;}
static unsigned tick(uint64_t v){return (unsigned)(v>>36);}
static unsigned pc(uint64_t v){return (unsigned)(v>>32)&15;}
static uint64_t pack(unsigned t,unsigned p,uint32_t x){return ((uint64_t)t<<36)|((uint64_t)p<<32)|x;}
static struct affine compose(struct affine f,struct affine g){return (struct affine){f.m*g.m,f.m*g.b+f.b};}
static uint32_t apply(struct affine f,uint32_t x){return f.m*x+f.b;}
/* Loader admits only bounded straight-line affine loops with a terminal JUMP 0. */
static void load(const char *path){FILE*f=fopen(path,"r");require(f!=NULL,"cannot load program file");char line[128],op[16],arg[40],extra[2];unsigned len=0;while(fgets(line,sizeof(line),f)){
 require(strchr(line,'\n')!=NULL||feof(f),"oversized program line");int n=sscanf(line,"%15s %39s %1s",op,arg,extra);if(n<=0)continue;
 if(!strcmp(op,"END")){require(n==1&&len>=2&&programs[np].code[len-1].op==JUMP,"program must terminate in JUMP 0");programs[np++].len=len;len=0;require(np<=MAX_PROGRAMS,"too many programs");continue;}
 require(np<MAX_PROGRAMS&&len<MAX_INS&&n==2,"bad program geometry");require(!len||programs[np].code[len-1].op!=JUMP,"instructions after JUMP");char*end;errno=0;unsigned long long a=strtoull(arg,&end,10);require(arg[0]>='0'&&arg[0]<='9'&&!errno&&!*end&&a<=UINT32_MAX,"bad operand");unsigned k=!strcmp(op,"ADD")?ADD:!strcmp(op,"MUL")?MUL:!strcmp(op,"JUMP")?JUMP:99;require(k!=99&&(k!=JUMP||a==0),"unsupported instruction");programs[np].code[len++]=(struct ins){k,(uint32_t)a};
 }require(!ferror(f)&&len==0&&np>0,"incomplete program");fclose(f);
 for(unsigned j=0;j<np;j++){struct program*p=&programs[j];struct affine f0={1,0};for(unsigned i=0;i<p->len;i++){p->prefix[i]=f0;struct ins in=p->code[i];struct affine g=in.op==ADD?(struct affine){1,in.arg}:in.op==MUL?(struct affine){in.arg,0}:(struct affine){1,0};f0=compose(g,f0);}p->power[0]=f0;for(unsigned i=1;i<28;i++)p->power[i]=compose(p->power[i-1],p->power[i-1]);}
}
static uint64_t step(unsigned id,uint64_t s){struct program*p=&programs[id%np];unsigned pos=pc(s),t=tick(s);require(pos<p->len&&t<MAX_TICK,"invalid state or clock exhausted");struct ins in=p->code[pos];uint32_t x=(uint32_t)s;if(in.op==ADD)x+=in.arg;else if(in.op==MUL)x*=in.arg;return pack(t+1,in.op==JUMP?0:pos+1,x);}
/* Learn each prefix from actual interpreter observations of two calibration
 * contexts, challenge a third, and compare with the admitted static law. */
static unsigned form(void){unsigned steps=0;for(unsigned j=0;j<np;j++){struct program*p=&programs[j];uint64_t zero=pack(0,0,0),one=pack(0,0,1),held=pack(0,0,UINT32_C(0xdeadbeef));
 for(unsigned r=0;r<=p->len;r++){struct affine seen={(uint32_t)one-(uint32_t)zero,(uint32_t)zero};struct affine declared=r==p->len?p->power[0]:p->prefix[r];unsigned phase=r%p->len;
  require(seen.m==declared.m&&seen.b==declared.b&&apply(seen,UINT32_C(0xdeadbeef))==(uint32_t)held&&pc(zero)==phase&&pc(one)==phase&&pc(held)==phase&&tick(zero)==r&&tick(one)==r&&tick(held)==r,"observed prefix contradicts admitted law");
  if(r==p->len){p->power[0]=seen;break;}p->prefix[r]=seen;zero=step(j,zero);one=step(j,one);held=step(j,held);steps+=3;
 }for(unsigned k=1;k<28;k++)p->power[k]=compose(p->power[k-1],p->power[k-1]);}return steps;}
static uint64_t navigate(unsigned id,unsigned t){struct program*p=&programs[id%np];unsigned q=t/p->len,r=t%p->len,k=0;uint32_t x=initial(id);while(q){if(q&1)x=apply(p->power[k],x);q>>=1;k++;}return pack(t,r,apply(p->prefix[r],x));}
static void *worker(void*arg){struct shard*w=arg;do{for(unsigned i=w->lo;i<w->hi;i++){uint64_t s=atomic_load_explicit(&states[i],memory_order_relaxed);atomic_store_explicit(&states[i],step(i,s),memory_order_release);}w->steps+=w->hi-w->lo;atomic_fetch_add_explicit(&w->sweeps,1,memory_order_release);}while(!atomic_load_explicit(&stop,memory_order_acquire));return NULL;}
struct observer {uint64_t checksum,advanced,unchanged;unsigned min,max;};
static void check_snapshot(unsigned id,struct observer*o){uint64_t s=atomic_load_explicit(&states[id],memory_order_acquire);unsigned t=tick(s);require(t&&s==navigate(id,t),"live state disagrees with temporal Ground");require(t>=previous[id],"clock regressed");if(t>previous[id])o->advanced++;else o->unchanged++;previous[id]=t;if(t<o->min)o->min=t;if(t>o->max)o->max=t;o->checksum+=(uint32_t)s;}
/* Native sample observations use the actual destination metadata, not request bytes. */
static void native_samples(unsigned epoch){int rx=socket(AF_INET,SOCK_DGRAM,0),tx=socket(AF_INET,SOCK_DGRAM,0),one=1;syscheck(rx,"rx");syscheck(tx,"tx");struct timeval timeout={.tv_sec=2};syscheck(setsockopt(rx,SOL_SOCKET,SO_BINDTODEVICE,"lo",3),"lo");syscheck(setsockopt(rx,IPPROTO_IP,IP_PKTINFO,&one,sizeof(one)),"pktinfo");syscheck(setsockopt(rx,SOL_SOCKET,SO_RCVTIMEO,&timeout,sizeof(timeout)),"timeout");syscheck(setsockopt(tx,SOL_SOCKET,SO_BROADCAST,&one,sizeof(one)),"broadcast");struct sockaddr_in dst={.sin_family=AF_INET},src={.sin_family=AF_INET,.sin_addr.s_addr=htonl(0x7f000001)};syscheck(bind(rx,(void*)&dst,sizeof(dst)),"bind rx");syscheck(bind(tx,(void*)&src,sizeof(src)),"bind tx");socklen_t len=sizeof(dst);syscheck(getsockname(rx,(void*)&dst,&len),"rx name");len=sizeof(src);syscheck(getsockname(tx,(void*)&src,&len),"tx name");struct observer o={.min=UINT32_MAX};unsigned n=count<4096?count:4096, cursor=0;
 for(unsigned k=0;k<n;k++){unsigned id;if(k==0)id=0;else if(k==1)id=count-1;else{do{id=(UINT32_C(2654435761)*(cursor++)+epoch*17)&(count-1);}while(id==0||id==count-1);}dst.sin_addr.s_addr=htonl(0x7f000000|id);require(sendto(tx,"",0,0,(void*)&dst,sizeof(dst))==0,"native sample send failed");unsigned char b;struct sockaddr_in peer={0};union{struct cmsghdr a;char b[CMSG_SPACE(sizeof(struct in_pktinfo))];}ctl;struct iovec io={&b,1};struct msghdr msg={.msg_name=&peer,.msg_namelen=sizeof(peer),.msg_iov=&io,.msg_iovlen=1,.msg_control=ctl.b,.msg_controllen=sizeof(ctl.b)};require(recvmsg(rx,&msg,0)==0&&!(msg.msg_flags&(MSG_TRUNC|MSG_CTRUNC))&&peer.sin_addr.s_addr==src.sin_addr.s_addr&&peer.sin_port==src.sin_port,"invalid native observation");unsigned found=0,actual=0;for(struct cmsghdr*h=CMSG_FIRSTHDR(&msg);h;h=CMSG_NXTHDR(&msg,h))if(h->cmsg_level==IPPROTO_IP&&h->cmsg_type==IP_PKTINFO){actual=ntohl(((struct in_pktinfo*)CMSG_DATA(h))->ipi_addr.s_addr);found++;}require(found==1&&actual==(0x7f000000|id),"native coordinate mismatch");check_snapshot(actual&0xffffff,&o);}
 close(rx);close(tx);printf("native epoch=%u observations=%u advanced=%"PRIu64" min_tick=%u max_tick=%u\n",epoch,n,o.advanced,o.min,o.max);fflush(stdout);
}
static uint64_t epoch(unsigned e,unsigned workers,int native){pthread_t ids[MAX_WORKERS];struct shard sh[MAX_WORKERS]={0};atomic_store(&stop,0);double start=now();for(unsigned i=0;i<workers;i++){unsigned slot=e==1?i:workers-1-i;sh[i].lo=(uint64_t)count*slot/workers;sh[i].hi=(uint64_t)count*(slot+1)/workers;atomic_init(&sh[i].sweeps,0);require(!pthread_create(&ids[i],NULL,worker,&sh[i]),"worker creation");}for(unsigned i=0;i<workers;i++)while(!atomic_load_explicit(&sh[i].sweeps,memory_order_acquire))sched_yield();
 for(unsigned pass=0;pass<2;pass++){struct observer o={.min=UINT32_MAX};double b=now();for(unsigned k=0;k<count;k++){unsigned id=(5*k+3+pass*17)&(count-1);check_snapshot(id,&o);}printf("live epoch=%u pass=%u observations=%u advanced=%"PRIu64" unchanged=%"PRIu64" min_tick=%u max_tick=%u checksum=%"PRIu64" seconds=%.6f\n",e,pass,count,o.advanced,o.unchanged,o.min,o.max,o.checksum,now()-b);fflush(stdout);require(o.advanced>0,"no execution progress observed");if(pass==0){unsigned target[MAX_WORKERS];for(unsigned i=0;i<workers;i++)target[i]=atomic_load_explicit(&sh[i].sweeps,memory_order_acquire)+2;for(unsigned i=0;i<workers;i++)while(atomic_load_explicit(&sh[i].sweeps,memory_order_acquire)<target[i])sched_yield();}}
 if(native)native_samples(e);
 atomic_store_explicit(&stop,1,memory_order_release);uint64_t steps=0;for(unsigned i=0;i<workers;i++){require(!pthread_join(ids[i],NULL),"worker join");steps+=sh[i].steps;}printf("epoch=%u workers=%u executed=%"PRIu64" seconds=%.6f\n",e,workers,steps,now()-start);fflush(stdout);return steps;}
static unsigned number(const char*s){char*e;errno=0;unsigned long n=strtoul(s,&e,10);require(*s>='0'&&*s<='9'&&!errno&&!*e&&n<=UINT32_MAX,"invalid integer argument");return (unsigned)n;}
int main(int argc,char**argv){require(argc==5||argc==6,"usage: fab011 programs.txt bits workers replacement_workers [native]");unsigned bits=number(argv[2]),w=number(argv[3]),r=number(argv[4]);require(bits>=4&&bits<=24&&w>=1&&w<=MAX_WORKERS&&r>=1&&r<=MAX_WORKERS,"bad geometry");require(argc==5||!strcmp(argv[5],"native"),"unknown mode");count=1u<<bits;load(argv[1]);unsigned formation_steps=form();states=malloc((size_t)count*sizeof(*states));previous=calloc(count,sizeof(*previous));require(states&&previous,"allocation failed");require(atomic_is_lock_free(&states[0]),"64-bit snapshots not lock-free");for(unsigned i=0;i<count;i++)atomic_init(&states[i],pack(0,0,initial(i)));
 /* Independently replay each program at early instruction times before admitting navigation. */
 for(unsigned id=0;id<np;id++){uint64_t s=pack(0,0,initial(id));for(unsigned t=0;t<4096;t++){require(s==navigate(id,t),"formation contradiction");s=step(id,s);}}
 printf("machines=%u programs=%u state_bytes=%zu observer_bytes=%zu\n",count,np,(size_t)count*sizeof(*states),(size_t)count*sizeof(*previous));printf("formation programs=%u probe_instructions=%u heldout_contexts=%u\n",np,formation_steps,np);fflush(stdout);uint64_t executed=epoch(1,w,argc==6);executed+=epoch(2,r,argc==6);uint64_t total=0;struct observer o={.min=UINT32_MAX};for(unsigned id=0;id<count;id++){check_snapshot(id,&o);total+=tick(atomic_load(&states[id]));}require(total==executed,"instruction accounting mismatch");unsigned cursor=0;for(unsigned k=0;k<64&&k<count;k++){unsigned id;if(k==0)id=0;else if(k==1)id=count-1;else{do{id=(UINT32_C(2654435761)*(cursor++))&(count-1);}while(id==0||id==count-1);}uint64_t s=atomic_load(&states[id]);printf("sample id=%u tick=%u pc=%u register=%u\n",id,tick(s),pc(s),(uint32_t)s);}printf("final machines=%u total_instructions=%"PRIu64" checksum=%"PRIu64" min_tick=%u max_tick=%u\n",count,total,o.checksum,o.min,o.max);free(previous);free(states);return 0;}
