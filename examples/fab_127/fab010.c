#define _GNU_SOURCE
#include <arpa/inet.h>
#include <errno.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/resource.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

/* FAB-010: one stateful virtual CPU per loopback identity, plus time view. */
enum { N=1<<24, BATCH=32, MAX_WORKERS=16 };
enum { ADD, XOR, MUL, SEND, RECV, BRANCH, HALT, JUMP };
struct instruction { unsigned op,arg; };
static const struct instruction programs[3][8]={
 {{ADD,7},{SEND,0},{RECV,0},{XOR,0},{MUL,3},{BRANCH,7},{ADD,1},{HALT,0}},
 {{XOR,0x5a5a5a5a},{SEND,0},{RECV,0},{XOR,0},{ADD,19},{BRANCH,7},{ADD,1},{HALT,0}},
 {{MUL,5},{ADD,3},{JUMP,0}}
};
/* XOR opcode with argument zero uses r1; nonzero uses immediate. */
struct cpu { uint32_t r0,r1,pc,steps,program,halted; };
struct mailbox { uint32_t value; atomic_uint state; };
struct task { unsigned lo,hi,kind; uint64_t steps,sends,receives,branches,checksum,packets; };
static struct cpu *cpus, *secondary; static struct mailbox *mail; static uint64_t *trace;
static unsigned count=N; static pthread_barrier_t barrier;
static void require(int b,const char*s){if(!b){fprintf(stderr,"%s\n",s);exit(2);}}
static void sys(int v,const char*s){if(v<0){perror(s);exit(1);}}
static double now(void){struct timespec t;sys(clock_gettime(CLOCK_MONOTONIC,&t),"clock");return t.tv_sec+t.tv_nsec*1e-9;}
static uint32_t initial(unsigned id){return id*UINT32_C(2654435761)+17;}
static unsigned peer(unsigned id){return id^((count>>1)|1);}
static void execute(struct cpu*c,unsigned id,struct task*w){
 if(c->halted)return;
 require(c->program<3&&c->pc<(c->program==2?3u:8u),"bad program counter");
 struct instruction ins=programs[c->program][c->pc];
 switch(ins.op){
 case ADD:c->r0+=ins.arg;break;
 case XOR:c->r0^=ins.arg?ins.arg:c->r1;break;
 case MUL:c->r0*=ins.arg;break;
 case SEND:{struct mailbox*m=&mail[peer(id)];unsigned empty=0;
  if(!atomic_compare_exchange_strong(&m->state,&empty,1))return;
  m->value=c->r0;atomic_store_explicit(&m->state,2,memory_order_release);w->sends++;break;}
 case RECV:{struct mailbox*m=&mail[id];if(atomic_load_explicit(&m->state,memory_order_acquire)!=2)return;
  c->r1=m->value;atomic_store_explicit(&m->state,0,memory_order_release);w->receives++;break;}
 case BRANCH:if(c->r0&128){c->pc=ins.arg;c->steps++;w->steps++;w->branches++;return;}break;
 case HALT:c->halted=1;c->steps++;w->steps++;return;
 case JUMP:c->pc=ins.arg;c->steps++;w->steps++;return;
 default:require(0,"unknown instruction");
 }c->pc++;c->steps++;w->steps++;
}
/* Every address event is observed from the actual kernel destination metadata.
 * Batch sends are bounded, source-checked, unique, and fail on missing results. */
struct channel {int rx,tx;struct sockaddr_in dst,src;};
static struct channel open_channel(void){struct channel c={.dst={.sin_family=AF_INET},.src={.sin_family=AF_INET,.sin_addr.s_addr=htonl(0x7f000001)}};int one=1,buf=1<<20;struct timeval timeout={.tv_sec=3};
 c.rx=socket(AF_INET,SOCK_DGRAM,0);sys(c.rx,"rx");c.tx=socket(AF_INET,SOCK_DGRAM,0);sys(c.tx,"tx");
 sys(setsockopt(c.rx,SOL_SOCKET,SO_BINDTODEVICE,"lo",3),"lo");sys(setsockopt(c.rx,IPPROTO_IP,IP_PKTINFO,&one,sizeof(one)),"pktinfo");sys(setsockopt(c.rx,SOL_SOCKET,SO_RCVBUF,&buf,sizeof(buf)),"rcvbuf");sys(setsockopt(c.rx,SOL_SOCKET,SO_RCVTIMEO,&timeout,sizeof(timeout)),"timeout");sys(setsockopt(c.tx,SOL_SOCKET,SO_BROADCAST,&one,sizeof(one)),"broadcast");
 sys(bind(c.rx,(void*)&c.dst,sizeof(c.dst)),"rx bind");sys(bind(c.tx,(void*)&c.src,sizeof(c.src)),"tx bind");socklen_t n=sizeof(c.dst);sys(getsockname(c.rx,(void*)&c.dst,&n),"rx port");n=sizeof(c.src);sys(getsockname(c.tx,(void*)&c.src,&n),"tx port");return c;}
static void send_address(struct channel*c,unsigned id){c->dst.sin_addr.s_addr=htonl(0x7f000000|id);ssize_t r;do{r=sendto(c->tx,"",0,0,(void*)&c->dst,sizeof(c->dst));}while(r<0&&errno==EINTR);if(r<0){fprintf(stderr,"send coordinate %06x: %s\n",id,strerror(errno));exit(1);}require(r==0,"send size");}
static unsigned receive_address(struct channel*c){unsigned char data;struct sockaddr_in src={0};union{struct cmsghdr align;char data[CMSG_SPACE(sizeof(struct in_pktinfo))];}ctl;struct iovec iov={&data,1};struct msghdr m={.msg_name=&src,.msg_namelen=sizeof(src),.msg_iov=&iov,.msg_iovlen=1,.msg_control=ctl.data,.msg_controllen=sizeof(ctl.data)};
 ssize_t n=recvmsg(c->rx,&m,0);if(n<0){perror("receive coordinate");exit(1);}require(n==0&&!(m.msg_flags&(MSG_TRUNC|MSG_CTRUNC))&&src.sin_addr.s_addr==c->src.sin_addr.s_addr&&src.sin_port==c->src.sin_port,"invalid envelope");unsigned addr=0,found=0;for(struct cmsghdr*h=CMSG_FIRSTHDR(&m);h;h=CMSG_NXTHDR(&m,h))if(h->cmsg_level==IPPROTO_IP&&h->cmsg_type==IP_PKTINFO){addr=ntohl(((struct in_pktinfo*)CMSG_DATA(h))->ipi_addr.s_addr);found++;}require(found==1&&(addr>>24)==127,"bad destination");return addr&0xffffff;}
/* F(x)=5x+3 over Z/2^32. The CPU's three instruction phases remain distinct. */
static uint64_t navigate(unsigned t){uint32_t x=12345,a=5,b=3;unsigned q=t/3;while(q){if(q&1)x=a*x+b;b=b*(a+1);a=a*a;q>>=1;}if(t%3)x*=5;if(t%3==2)x+=3;return ((uint64_t)(t%3)<<32)|x;}
static void *address_worker(void*arg){struct task*w=arg;struct channel c=open_channel();for(unsigned start=w->lo;start<w->hi;start+=BATCH){unsigned n=w->hi-start<BATCH?w->hi-start:BATCH;uint32_t seen=0;
 for(unsigned i=0;i<n;i++){unsigned k=start+i;unsigned id=w->kind==0?k:(5*k+3)&(count-1);send_address(&c,id);}
 for(unsigned i=0;i<n;i++){unsigned id=receive_address(&c);unsigned k=w->kind==0?id:((id-3)*UINT32_C(3435973837))&(count-1);require(k>=start&&k<start+n&&!(seen&(1u<<(k-start))),"duplicate or wrong batch");seen|=1u<<(k-start);w->packets++;
 if(w->kind==0){struct cpu*m=&cpus[id];require(m->steps==0&&m->pc==0,"CPU activated twice");execute(m,id,w);require(m->steps==1,"CPU not activated");}
 else{uint64_t observed=navigate(id);require(observed==trace[id],"motion register/PC mismatch");w->checksum+=(uint32_t)observed;}
 }require(seen==(n==32?UINT32_MAX:(1u<<n)-1),"incomplete batch");}
 struct timeval timeout={0,1000};sys(setsockopt(c.rx,SOL_SOCKET,SO_RCVTIMEO,&timeout,sizeof(timeout)),"final timeout");unsigned char junk;require(recv(c.rx,&junk,1,0)<0&&(errno==EAGAIN||errno==EWOULDBLOCK),"unexpected queue tail");close(c.rx);close(c.tx);return NULL;}
static void *step_worker(void*arg){struct task*w=arg;for(unsigned tick=1;tick<8;tick++){for(unsigned id=w->lo;id<w->hi;id++)execute(&cpus[id],id,w);int r=pthread_barrier_wait(&barrier);require(r==0||r==PTHREAD_BARRIER_SERIAL_THREAD,"barrier");}return NULL;}
static uint32_t first(unsigned id){return id&1?initial(id)^UINT32_C(0x5a5a5a5a):initial(id)+7;}
static void *verify_worker(void*arg){struct task*w=arg;for(unsigned id=w->lo;id<w->hi;id++){uint32_t v=first(id)^first(peer(id));v=id&1?v+19:v*3;unsigned branch=(v&128)!=0;if(!branch)v++;struct cpu*c=&cpus[id];require(c->halted==1&&c->pc==7&&c->steps==8-branch&&c->program==(id&1)&&c->r0==v&&c->r1==first(peer(id))&&atomic_load(&mail[id].state)==0,"CPU state mismatch");w->checksum+=v;}return NULL;}
static void *secondary_worker(void*arg){struct task*w=arg;for(unsigned id=w->lo;id<w->hi;id++){
 struct cpu*c=&secondary[id];c->r0=initial(id);c->program=2;
 for(unsigned i=0;i<9;i++)execute(c,id,w);
 uint32_t expected=((initial(id)*5u+3u)*5u+3u)*5u+3u;
 require(c->r0==expected&&c->r1==0&&c->pc==0&&c->steps==9&&!c->halted&&c->program==2,"secondary process mismatch");w->checksum+=c->r0;
 }return NULL;}
static struct task totals(unsigned workers,void*(*fn)(void*),unsigned kind){pthread_t threads[MAX_WORKERS];struct task tasks[MAX_WORKERS]={0},total={0};for(unsigned i=0;i<workers;i++){tasks[i].lo=count*i/workers;tasks[i].hi=count*(i+1)/workers;tasks[i].kind=kind;require(!pthread_create(&threads[i],NULL,fn,&tasks[i]),"pthread create");}for(unsigned i=0;i<workers;i++){require(!pthread_join(threads[i],NULL),"pthread join");total.steps+=tasks[i].steps;total.sends+=tasks[i].sends;total.receives+=tasks[i].receives;total.branches+=tasks[i].branches;total.checksum+=tasks[i].checksum;total.packets+=tasks[i].packets;}return total;}
static void selftest(void){
 count=4;mail=calloc(count,sizeof(*mail));require(mail!=NULL,"selftest mailbox");for(unsigned i=0;i<count;i++)atomic_init(&mail[i].state,0);
 struct cpu sender={.pc=1,.program=0},receiver={.pc=2,.program=0};struct task stats={0};unsigned target=peer(0);
 execute(&receiver,target,&stats);require(receiver.pc==2&&receiver.steps==0&&stats.receives==0,"empty receive advanced");
 execute(&sender,0,&stats);require(sender.pc==2&&sender.steps==1&&stats.sends==1,"zero send failed");
 struct cpu blocked={.pc=1,.program=0,.r0=9};execute(&blocked,0,&stats);require(blocked.pc==1&&blocked.steps==0&&stats.sends==1,"full mailbox overwritten");
 execute(&receiver,target,&stats);require(receiver.pc==3&&receiver.r1==0&&stats.receives==1,"zero receive failed");
 execute(&blocked,0,&stats);require(blocked.pc==2&&blocked.steps==1&&stats.sends==2,"send failed after vacancy");
 struct cpu again={.pc=2,.program=0};execute(&again,target,&stats);require(again.r1==9&&again.pc==3&&stats.receives==2,"second delivery failed");
 require(atomic_load(&mail[target].state)==0,"mailbox not empty");free(mail);puts("mailbox selftest passed");}
static void probe(const char*arg){char*end;errno=0;unsigned long value=strtoul(arg,&end,10);require(!errno&&*arg&&!*end&&value<N,"invalid temporal coordinate");struct channel c=open_channel();send_address(&c,(unsigned)value);unsigned t=receive_address(&c);require(t==value,"probe address mismatch");uint64_t observed=navigate(t);printf("coordinate=%u pc=%u register=%u\n",t,(unsigned)(observed>>32),(uint32_t)observed);close(c.rx);close(c.tx);}
int main(int argc,char**argv){if(argc==2&&!strcmp(argv[1],"--selftest")){selftest();return 0;}if(argc==3&&!strcmp(argv[1],"--probe")){probe(argv[2]);return 0;}unsigned bits=argc>1?atoi(argv[1]):24,workers=argc>2?atoi(argv[2]):4;require(bits>=2&&bits<=24&&workers>=1&&workers<=MAX_WORKERS,"invalid configuration");count=1u<<bits;
 cpus=calloc(count,sizeof(*cpus));mail=calloc(count,sizeof(*mail));require(cpus&&mail,"state allocation");for(unsigned id=0;id<count;id++){cpus[id].r0=initial(id);cpus[id].program=id&1;atomic_init(&mail[id].state,0);}double t=now();struct task active=totals(workers,address_worker,0);double ingress=now()-t;require(active.steps==count&&active.packets==count,"activation coverage");printf("activation CPUs=%u packets=%llu seconds=%.6f\n",count,(unsigned long long)active.packets,ingress);fflush(stdout);
 require(!pthread_barrier_init(&barrier,NULL,workers),"barrier init");t=now();struct task run=totals(workers,step_worker,0);double execution=now()-t;pthread_barrier_destroy(&barrier);t=now();struct task verified=totals(workers,verify_worker,0);double check=now()-t;require(run.sends==count&&run.receives==count&&run.steps+active.steps==8ull*count-run.branches,"execution accounting");printf("machines=%u halted=%u instructions=%llu sends=%llu receives=%llu taken_branches=%llu checksum=%llu execution_seconds=%.6f verification_seconds=%.6f state_bytes=%zu\n",count,count,(unsigned long long)(run.steps+active.steps),(unsigned long long)run.sends,(unsigned long long)run.receives,(unsigned long long)run.branches,(unsigned long long)verified.checksum,execution,check,(sizeof(*cpus)+sizeof(*mail))*count);fflush(stdout);
 secondary=calloc(count,sizeof(*secondary));require(secondary!=NULL,"secondary context allocation");t=now();struct task contexts=totals(workers,secondary_worker,0);double secondary_time=now()-t;require(contexts.steps==9ull*count,"secondary execution accounting");struct task preserved=totals(workers,verify_worker,0);require(preserved.checksum==verified.checksum,"primary context changed");printf("secondary_contexts=%u secondary_instructions=%llu secondary_checksum=%llu primary_preserved=%u secondary_seconds=%.6f retained_state_bytes=%zu\n",count,(unsigned long long)contexts.steps,(unsigned long long)contexts.checksum,count,secondary_time,(sizeof(*cpus)+sizeof(*secondary)+sizeof(*mail))*count);fflush(stdout);
 trace=malloc((size_t)count*sizeof(*trace));require(trace!=NULL,"trace allocation");struct cpu motion={.r0=12345,.program=2};struct task ref={0};t=now();for(unsigned i=0;i<count;i++){trace[i]=((uint64_t)motion.pc<<32)|motion.r0;require(motion.pc==i%3&&motion.steps==i,"motion phase");execute(&motion,0,&ref);}double replay=now()-t;t=now();struct task observed=totals(workers,address_worker,1);double elapsed=now()-t;require(observed.packets==count,"motion coverage");struct rusage usage;sys(getrusage(RUSAGE_SELF,&usage),"resource usage");printf("motion_positions=%u packets=%llu checksum=%llu reference_seconds=%.6f navigation_seconds=%.6f peak_rss_kib=%ld\n",count,(unsigned long long)observed.packets,(unsigned long long)observed.checksum,replay,elapsed,usage.ru_maxrss);free(trace);struct task final=totals(workers,verify_worker,0);require(final.checksum==verified.checksum,"motion changed primary context");free(secondary);free(cpus);free(mail);return 0;}
