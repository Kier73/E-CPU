/* FAB-025: one distinct private transaction application per 24-bit coordinate.
 * Compact two-process bytecode environment, explicit file/mailbox state.
 * Local file checkpoint between independent process lifetimes; not native M3.
 */
#define _POSIX_C_SOURCE 200809L
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <pthread.h>
#include <time.h>
#include <inttypes.h>

#define RECORDS 8u
#define CUT 50u
#define MAX_WORKERS 16u

typedef struct {
    uint32_t records[8], r[8], audit[4], file[4];
    uint32_t mailbox[2], pc[2], ticks[2], status[2];
} Machine;
_Static_assert(sizeof(Machine)==128,"machine geometry");
enum { RUN, WAITING, HALTED };
enum { SET, LOAD, ANDI, JZ, SUB, ADDI, JMP, ADD, XOR, MULI, LTI, JNZ, STORE, SEND, HALT, RECV, READF };
typedef struct { unsigned op,a,b; uint32_t c; } Ins;
static const Ins app[]={
    {SET,0,0,0},{SET,3,0,0},
    {LOAD,1,0,0},{ANDI,5,1,65535},{ANDI,6,1,0x80000000u},{JZ,6,0,9},
    {SUB,2,2,5},{ADDI,3,3,1},{JMP,0,0,10},{ADD,2,2,5},
    {XOR,4,4,1},{MULI,4,4,16777619u},{XOR,4,4,2},{ADDI,0,0,1},
    {LTI,6,0,RECORDS},{JNZ,6,0,2},
    {STORE,0,2,0},{STORE,1,3,0},{STORE,2,4,0},{SEND,4,0,0},{HALT,0,0,0}
};
static const Ins audit[]={
    {RECV,0,0,0},{READF,1,0,0},{READF,2,1,0},{READF,3,2,0},
    {XOR,0,0,1},{MULI,0,0,2654435761u},{ADD,0,0,2},{XOR,0,0,3},
    {STORE,3,0,0},{HALT,0,0,0}
};
static double now(void){struct timespec t; if(clock_gettime(CLOCK_MONOTONIC,&t)) abort();return t.tv_sec+t.tv_nsec*1e-9;}
static uint32_t mix(uint32_t x){x^=x>>16;x*=0x7feb352du;x^=x>>15;x*=0x846ca68bu;return x^(x>>16);}
static uint32_t record(uint32_t id,unsigned j){return mix(id ^ (0x9e3779b9u*(j+1)));}
static void step(Machine *m,unsigned p){
    if(m->status[p]==HALTED) abort();
    uint32_t *r=p?m->audit:m->r;
    unsigned pc=m->pc[p];
    if(pc>=(p?sizeof(audit)/sizeof(*audit):sizeof(app)/sizeof(*app))) abort();
    Ins i=(p?audit:app)[pc];
    if(i.op==RECV && !m->mailbox[1]){m->status[p]=WAITING;return;}
    m->status[p]=RUN; m->pc[p]++; m->ticks[p]++;
    switch(i.op){
        case SET:r[i.a]=i.c;break;
        case LOAD:if(r[i.b]>=RECORDS)abort();r[i.a]=m->records[r[i.b]];break;
        case ANDI:r[i.a]=r[i.b]&i.c;break;
        case JZ:if(!r[i.a])m->pc[p]=i.c;break;
        case JNZ:if(r[i.a])m->pc[p]=i.c;break;
        case JMP:m->pc[p]=i.c;break;
        case SUB:r[i.a]=r[i.b]-r[i.c];break;
        case ADD:r[i.a]=r[i.b]+r[i.c];break;
        case ADDI:r[i.a]=r[i.b]+i.c;break;
        case XOR:r[i.a]=r[i.b]^r[i.c];break;
        case MULI:r[i.a]=r[i.b]*i.c;break;
        case LTI:r[i.a]=r[i.b]<i.c;break;
        case STORE:m->file[i.a]=r[i.b];break;
        case READF:r[i.a]=m->file[i.b];break;
        case SEND:if(m->mailbox[1])abort();m->mailbox[0]=r[i.a];m->mailbox[1]=1;break;
        case RECV:r[i.a]=m->mailbox[0];m->mailbox[0]=m->mailbox[1]=0;break;
        case HALT:m->pc[p]=pc;m->status[p]=HALTED;break;
        default:abort();
    }
}
/* Independent high-level oracle for the transaction/application semantics. */
static int verify(const Machine *m,uint32_t id,uint64_t *checksum,uint64_t *debits){
    uint32_t balance=id, count=0, fingerprint=id^0xa5a5a5a5u;
    for(unsigned j=0;j<RECORDS;j++){
        uint32_t x=record(id,j); if(m->records[j]!=x)return 0;
        if(x>>31){balance-=x&65535u;count++;}else balance+=x&65535u;
        fingerprint=((fingerprint^x)*16777619u)^balance;
    }
    uint32_t result=(((fingerprint^balance)*2654435761u)+count)^fingerprint;
    /* Each debit takes two extra instructions over a credit. */
    uint32_t steps=2+RECORDS*11+2*count+5;
    if(m->file[0]!=balance||m->file[1]!=count||m->file[2]!=fingerprint||m->file[3]!=result||
       m->r[0]!=RECORDS||m->r[2]!=balance||m->r[3]!=count||m->r[4]!=fingerprint||
       m->audit[0]!=result||m->audit[1]!=balance||m->audit[2]!=count||m->audit[3]!=fingerprint||
       m->pc[0]!=20||m->pc[1]!=9||m->ticks[0]!=steps||m->ticks[1]!=10||
       m->status[0]!=HALTED||m->status[1]!=HALTED||m->mailbox[0]||m->mailbox[1]) return 0;
    *checksum+=result; *debits+=count; return 1;
}
typedef struct {Machine *fleet;uint32_t lo,hi;int phase;uint64_t ticks,checksum,debits,errors;} Job;
static void *work(void *ptr){
    Job *j=ptr;
    for(uint32_t id=j->lo;id<j->hi;id++){
        Machine *m=j->fleet+id;
        if(j->phase==0){
            memset(m,0,sizeof(*m));for(unsigned k=0;k<RECORDS;k++)m->records[k]=record(id,k);
            m->r[2]=id;m->r[4]=id^0xa5a5a5a5u;
            step(m,1); /* Every internal audit process waits on a private mailbox. */
            for(unsigned k=0;k<CUT;k++)step(m,0);
            if(m->ticks[0]!=CUT||m->status[0]!=RUN||m->status[1]!=WAITING||m->pc[1]!=0||m->mailbox[1])abort();
            j->ticks+=m->ticks[0];
        }else if(j->phase==1){
            if(m->ticks[0]!=CUT||m->status[0]!=RUN||m->status[1]!=WAITING||m->pc[1]!=0||m->mailbox[1]){j->errors++;continue;}
            while(m->status[0]!=HALTED && m->ticks[0]<256)step(m,0);
            if(!m->mailbox[1]){j->errors++;continue;}
            while(m->status[1]!=HALTED && m->ticks[1]<32)step(m,1);
            j->ticks+=m->ticks[0]-CUT+m->ticks[1];
        }else{
            if(!verify(m,id,&j->checksum,&j->debits))j->errors++;
            j->ticks+=(uint64_t)m->ticks[0]+m->ticks[1];
        }
    }
    return NULL;
}
static Job run(Machine *fleet,uint32_t n,unsigned workers,int phase){
    pthread_t th[MAX_WORKERS];Job jobs[MAX_WORKERS],total={0};
    for(unsigned i=0;i<workers;i++){jobs[i]=(Job){.fleet=fleet,.lo=(uint32_t)((uint64_t)n*i/workers),.hi=(uint32_t)((uint64_t)n*(i+1)/workers),.phase=phase};if(pthread_create(th+i,NULL,work,jobs+i))abort();}
    for(unsigned i=0;i<workers;i++){if(pthread_join(th[i],NULL))abort();total.ticks+=jobs[i].ticks;total.checksum+=jobs[i].checksum;total.debits+=jobs[i].debits;total.errors+=jobs[i].errors;}
    return total;
}
int main(int argc,char **argv){
    if(argc!=5){fprintf(stderr,"usage: %s init|resume|verify bits workers checkpoint\n",argv[0]);return 2;}
    int phase=!strcmp(argv[1],"init")?0:!strcmp(argv[1],"resume")?1:!strcmp(argv[1],"verify")?2:-1;
    unsigned bits=(unsigned)strtoul(argv[2],NULL,10), workers=(unsigned)strtoul(argv[3],NULL,10);
    if(phase<0||bits<1||bits>24||!workers||workers>MAX_WORKERS)return 2;
    uint32_t n=1u<<bits;size_t size=(size_t)n*sizeof(Machine);
    int fd=open(argv[4],phase==0?(O_RDWR|O_CREAT|O_EXCL):phase==1?O_RDWR:O_RDONLY,0600);
    if(fd<0){perror("open");return 1;}
    if(phase==0 && ftruncate(fd,(off_t)size)){perror("ftruncate");return 1;}
    struct stat st;if(fstat(fd,&st)||st.st_size!=(off_t)size){fprintf(stderr,"checkpoint extent differs\n");return 1;}
    Machine *fleet=mmap(NULL,size,phase==2?PROT_READ:PROT_READ|PROT_WRITE,MAP_SHARED,fd,0);
    if(fleet==MAP_FAILED){perror("mmap");return 1;}
    double t=now();Job sum=run(fleet,n,workers,phase);double elapsed=now()-t;
    if(sum.errors){fprintf(stderr,"phase %s errors=%" PRIu64 "\n",argv[1],sum.errors);return 1;}
    t=now();if(phase!=2&&(msync(fleet,size,MS_SYNC)||fsync(fd))){perror("sync");return 1;}double sync=now()-t;
    printf("{\"phase\":\"%s\",\"machines\":%u,\"internal_processes\":%u,\"workers\":%u,\"checkpoint_bytes\":%zu,\"instructions\":%" PRIu64 ",\"debit_records\":%" PRIu64 ",\"checksum\":%" PRIu64 ",\"errors\":%" PRIu64 ",\"seconds\":%.9f,\"sync_seconds\":%.9f}\n",argv[1],n,2*n,workers,size,sum.ticks,sum.debits,sum.checksum,sum.errors,elapsed,sync);
    if(munmap(fleet,size)||close(fd)){perror("close");return 1;}
    return 0;
}
