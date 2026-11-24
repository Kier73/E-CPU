#define _GNU_SOURCE
#include <arpa/inet.h>
#include <linux/filter.h>
#include <sys/epoll.h>
#include <sys/socket.h>
#include <sys/wait.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <errno.h>

/* FAB-009: 256 affine lanes x 256 initial states x 256 logical times. */
#define NET SKF_NET_OFF
#define MAX_CODE 512
struct code { struct sock_filter i[MAX_CODE]; unsigned n; };
static void fail(const char *s){perror(s);exit(1);}
static void require(int b,const char *s){if(!b){fprintf(stderr,"%s\n",s);exit(2);}}
static void ck(int v,const char*s){if(v<0)fail(s);}
static double now(void){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return t.tv_sec+t.tv_nsec*1e-9;}
static void emit(struct code*c,unsigned op,unsigned k){require(c->n<MAX_CODE,"program overflow");c->i[c->n++]=(struct sock_filter)BPF_STMT(op,k);}
static void jeq(struct code*c,unsigned k,unsigned jt,unsigned jf){c->i[c->n++]=(struct sock_filter)BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K,k,jt,jf);}
static void loadbyte(struct code*c,int n){emit(c,BPF_LD|BPF_B|BPF_ABS,(uint32_t)(NET+n));}
static void ld(struct code*c,unsigned n){emit(c,BPF_LD|BPF_MEM,n);}
static void lx(struct code*c,unsigned n){emit(c,BPF_LDX|BPF_MEM,n);}
static void st(struct code*c,unsigned n){emit(c,BPF_ST,n);}
static void alu(struct code*c,unsigned op,unsigned k){emit(c,BPF_ALU|op|BPF_K,k);}
static void alux(struct code*c,unsigned op){emit(c,BPF_ALU|op|BPF_X,0);}
/* Memory slots: 0 multiplier, 1 increment, 2 current state, 3 logical time. */
static struct code compile(int jump,int length,unsigned increment){struct code c={0};
 if(length){emit(&c,BPF_LD|BPF_W|BPF_LEN,0);jeq(&c,263,1,0);emit(&c,BPF_RET|BPF_K,0);loadbyte(&c,16);jeq(&c,127,1,0);emit(&c,BPF_RET|BPF_K,0);}
 loadbyte(&c,17);st(&c,0);loadbyte(&c,18);st(&c,2);
 emit(&c,BPF_LD|BPF_IMM,increment);st(&c,1);
 if(!jump){ld(&c,2);lx(&c,0);alux(&c,BPF_MUL);alu(&c,BPF_ADD,increment);alu(&c,BPF_AND,255);}
 else {loadbyte(&c,19);st(&c,3);
  for(unsigned bit=0;bit<8;bit++){
   ld(&c,3);alu(&c,BPF_AND,1u<<bit);jeq(&c,0,7,0);
   ld(&c,2);lx(&c,0);alux(&c,BPF_MUL);lx(&c,1);alux(&c,BPF_ADD);alu(&c,BPF_AND,255);st(&c,2);
   if(bit!=7){/* (m,c)^2 = (m*m, c*(m+1)) */
    ld(&c,0);alu(&c,BPF_ADD,1);lx(&c,1);alux(&c,BPF_MUL);alu(&c,BPF_AND,255);st(&c,1);
    ld(&c,0);lx(&c,0);alux(&c,BPF_MUL);alu(&c,BPF_AND,255);st(&c,0);
   }
  }ld(&c,2);
 }
 if(length)alu(&c,BPF_ADD,8);
 emit(&c,BPF_RET|BPF_A,0);return c;
}
static void attach(int fd,struct code*c,int opt){struct sock_fprog p={.len=c->n,.filter=c->i};ck(setsockopt(fd,SOL_SOCKET,opt,&p,sizeof(p)),"attach cBPF");}
static struct code guard(unsigned size){struct code c={0};emit(&c,BPF_LD|BPF_W|BPF_LEN,0);jeq(&c,size+8,1,0);emit(&c,BPF_RET|BPF_K,0);loadbyte(&c,16);jeq(&c,127,1,0);emit(&c,BPF_RET|BPF_K,0);emit(&c,BPF_RET|BPF_K,size+8);return c;}
struct group {int fd[256],tx,ep,n;struct sockaddr_in dst,src;};
static struct group open_group(int jump,int length,unsigned increment){struct group g={.n=length?1:256};int one=1;g.ep=epoll_create1(EPOLL_CLOEXEC);ck(g.ep,"epoll");g.dst.sin_family=AF_INET;struct code c=compile(jump,length,increment),gate=guard(0);
 for(int i=0;i<g.n;i++){int s=socket(AF_INET,SOCK_DGRAM|SOCK_CLOEXEC,0);ck(s,"socket");g.fd[i]=s;
  ck(setsockopt(s,SOL_SOCKET,SO_BINDTODEVICE,"lo",3),"bind device");ck(setsockopt(s,IPPROTO_IP,IP_PKTINFO,&one,sizeof(one)),"pktinfo");
  if(!length)ck(setsockopt(s,SOL_SOCKET,SO_REUSEPORT,&one,sizeof(one)),"reuseport");
  ck(bind(s,(void*)&g.dst,sizeof(g.dst)),"bind");socklen_t n=sizeof(g.dst);ck(getsockname(s,(void*)&g.dst,&n),"getsockname");
  attach(s,length?&c:&gate,SO_ATTACH_FILTER);struct epoll_event ev={.events=EPOLLIN,.data.u32=i};ck(epoll_ctl(g.ep,EPOLL_CTL_ADD,s,&ev),"epoll add");
 }if(!length)attach(g.fd[0],&c,SO_ATTACH_REUSEPORT_CBPF);
 g.tx=socket(AF_INET,SOCK_DGRAM|SOCK_CLOEXEC,0);ck(g.tx,"tx");ck(setsockopt(g.tx,SOL_SOCKET,SO_BROADCAST,&one,sizeof(one)),"broadcast");g.src.sin_family=AF_INET;g.src.sin_addr.s_addr=htonl(0x7f000001);ck(bind(g.tx,(void*)&g.src,sizeof(g.src)),"bind tx");socklen_t n=sizeof(g.src);ck(getsockname(g.tx,(void*)&g.src,&n),"tx identity");return g;
}
static void close_group(struct group*g){for(int i=0;i<g->n;i++)close(g->fd[i]);close(g->tx);close(g->ep);}
static void send_coordinate(struct group*g,unsigned coordinate){
 g->dst.sin_addr.s_addr=htonl(0x7f000000|coordinate);unsigned char data[255]={0};size_t size=g->n==1?255:0;
 require(sendto(g->tx,data,size,0,(void*)&g->dst,sizeof(g->dst))==(ssize_t)size,"send failure");
}
static unsigned receive_coordinate(struct group*g,unsigned*coordinate){
 struct epoll_event event;int n=epoll_wait(g->ep,&event,1,1000);require(n==1,"missing path observation");unsigned idx=event.data.u32;
 unsigned char data[255];struct sockaddr_in peer={0};union{struct cmsghdr align;char buf[CMSG_SPACE(sizeof(struct in_pktinfo))];}control;struct iovec iov={data,sizeof(data)};struct msghdr msg={.msg_name=&peer,.msg_namelen=sizeof(peer),.msg_iov=&iov,.msg_iovlen=1,.msg_control=control.buf,.msg_controllen=sizeof(control.buf)};
 ssize_t got=recvmsg(g->fd[idx],&msg,0);require(got>=0&&!(msg.msg_flags&(MSG_TRUNC|MSG_CTRUNC)),"invalid delivery");require(peer.sin_addr.s_addr==g->src.sin_addr.s_addr&&peer.sin_port==g->src.sin_port,"peer mismatch");unsigned actual=0,found=0;for(struct cmsghdr*h=CMSG_FIRSTHDR(&msg);h;h=CMSG_NXTHDR(&msg,h))if(h->cmsg_level==IPPROTO_IP&&h->cmsg_type==IP_PKTINFO){actual=ntohl(((struct in_pktinfo*)CMSG_DATA(h))->ipi_addr.s_addr);found++;}require(found==1&&(actual>>24)==127,"coordinate mismatch");require(g->n==1||got==0,"nonempty route result");for(ssize_t i=0;i<got;i++)require(data[i]==0,"nonzero result payload");*coordinate=actual&0xffffff;return g->n==1?(unsigned)got:idx;
}
static unsigned observe(struct group*g,unsigned coordinate){unsigned actual;send_coordinate(g,coordinate);unsigned result=receive_coordinate(g,&actual);require(actual==coordinate,"coordinate mismatch");struct epoll_event ev;require(epoll_wait(g->ep,&ev,1,0)==0,"duplicate observation");return result;}
static void worker(unsigned begin,unsigned end,int length,unsigned states,unsigned times,int batch,unsigned increment,unsigned seed){struct group g=open_group(1,length,increment),edge={0};int use_edge=!length&&end==256&&states==256&&times==256;if(use_edge)edge=open_group(1,1,increment);unsigned count=0;uint64_t sum=0;double start=now();
 if(!batch){for(unsigned a=begin;a<end;a++)for(unsigned x=0;x<states;x++){unsigned expected=x;for(unsigned t=0;t<times;t++){unsigned coordinate=(a<<16)|(x<<8)|t;unsigned actual=observe(use_edge&&coordinate==0xffffff?&edge:&g,coordinate);if(actual!=expected){fprintf(stderr,"mismatch %06x got=%u want=%u\n",coordinate,actual,expected);exit(4);}sum+=actual;count++;expected=(a*expected+seed)&255;}}}
 else {for(unsigned x=0;x<states;x++){unsigned expected[256];for(unsigned a=begin;a<end;a++)expected[a]=x;
  for(unsigned t=0;t<times;t++){
   unsigned pending=0;unsigned char seen[256]={0};
   for(unsigned a=begin;a<end;a++){unsigned coord=(a<<16)|(x<<8)|t;if(use_edge&&coord==0xffffff){unsigned actual=observe(&edge,coord);require(actual==expected[a],"broadcast result mismatch");sum+=actual;count++;seen[a]=1;}else{send_coordinate(&g,coord);pending++;}}
   for(unsigned i=0;i<pending;i++){unsigned coord;unsigned actual=receive_coordinate(&g,&coord);unsigned a=coord>>16;require(a>=begin&&a<end&&(coord&0xffff)==((x<<8)|t)&&!seen[a],"duplicate/out-of-batch observation");require(actual==expected[a],"parallel result mismatch");seen[a]=1;sum+=actual;count++;}
   struct epoll_event ev;require(epoll_wait(g.ep,&ev,1,0)==0,"unexpected queued observation");
   for(unsigned a=begin;a<end;a++){require(seen[a],"missing lane result");expected[a]=(a*expected[a]+seed)&255;}
  }
 }}
 printf("lanes=%u:%u states=%u times=%u count=%u seconds=%.6f sum=%llu encoding=%s\n",begin,end,states,times,count,now()-start,(unsigned long long)sum,length?"length":"path");fflush(stdout);close_group(&g);if(use_edge)close_group(&edge);
}
static unsigned recognize(unsigned seed){
 struct group primitive=open_group(0,0,seed);unsigned increment=observe(&primitive,0),probes=1;
 for(unsigned a=0;a<256;a++){unsigned c=observe(&primitive,a<<16),v=observe(&primitive,(a<<16)|256);unsigned m=(v-c)&255;require(m==a&&c==increment,"affine family mismatch");for(unsigned x=17;x<=255;x+=238){require(observe(&primitive,(a<<16)|(x<<8))==((m*x+c)&255),"withheld probe mismatch");}probes+=4;}
 close_group(&primitive);printf("formation=%u lanes=256 increment=%u native_jump_instructions=%u\n",probes,increment,compile(1,0,increment).n);fflush(stdout);return increment;
}
static void samples(unsigned increment){
 struct group g=open_group(1,0,increment),edge=open_group(1,1,increment);unsigned state=127;
 for(unsigned i=0;i<1026;i++){state=(1664525u*state+1013904223u);unsigned coord=i==0?0:i==1?0xffffff:state&0xffffff;unsigned y=observe(coord==0xffffff?&edge:&g,coord);printf("sample=%06x result=%u\n",coord,y);}
 close_group(&g);close_group(&edge);
}
int main(int argc,char**argv){
 if(argc>1&&!strcmp(argv[1],"--samples")){unsigned seed=argc>2?atoi(argv[2]):1;require(seed<=255,"invalid seed");samples(recognize(seed));return 0;}
 unsigned workers=argc>1?atoi(argv[1]):4,states=argc>2?atoi(argv[2]):256,times=argc>3?atoi(argv[3]):256,seed=argc>6?atoi(argv[6]):1;int length=argc>4?atoi(argv[4]):0,batch=argc>5?atoi(argv[5]):0;require(workers>=1&&workers<=16&&states>=1&&states<=256&&times>=1&&times<=256&&seed<=255&&(length==0||length==1)&&(batch==0||batch==1),"bad domain");
 unsigned increment=recognize(seed);double start=now();for(unsigned i=0;i<workers;i++){pid_t p=fork();ck(p,"fork");if(p==0){worker(256*i/workers,256*(i+1)/workers,length,states,times,batch,increment,seed);_exit(0);}}int good=1;for(unsigned i=0;i<workers;i++){int status;ck(wait(&status),"wait");if(!WIFEXITED(status)||WEXITSTATUS(status)!=0)good=0;}printf("total_seconds=%.6f workers=%u complete=%d batch=%d\n",now()-start,workers,good,batch);return good?0:1;
}
