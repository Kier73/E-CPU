/* FAB-027: immutable shard successors of the FAB-025 compact machines. */
#define main fab025_original_main
#include "fab025.c"
#undef main

int main(int argc,char **argv){
    if(argc!=7){fprintf(stderr,"usage: %s init|advance|verify lo hi input output fail\n",argv[0]);return 2;}
    unsigned long lo=strtoul(argv[2],NULL,10),hi=strtoul(argv[3],NULL,10);
    int init=!strcmp(argv[1],"init"),advance=!strcmp(argv[1],"advance"),check=!strcmp(argv[1],"verify"),fail=atoi(argv[6]);
    if((init+advance+check)!=1||lo>=hi||hi>(1u<<24)|| (fail&&!advance))return 2;
    size_t size=(hi-lo)*sizeof(Machine); int in=-1,out=-1;Machine *src=NULL,*dst=NULL;
    struct stat st;
    if(!init){in=open(argv[4],O_RDONLY);if(in<0||fstat(in,&st)||st.st_size!=(off_t)size)return 3;
        src=mmap(NULL,size,PROT_READ,MAP_SHARED,in,0);if(src==MAP_FAILED)return 3;}
    if(!check){out=open(argv[5],O_RDWR|O_CREAT|O_EXCL,0600);if(out<0||ftruncate(out,(off_t)size))return 3;
        dst=mmap(NULL,size,PROT_READ|PROT_WRITE,MAP_SHARED,out,0);if(dst==MAP_FAILED)return 3;}
    uint64_t ticks=0,checksum=0,debits=0;double start=now();
    for(uint32_t id=(uint32_t)lo;id<hi;id++){
        size_t k=id-lo;
        if(check){if(!verify(src+k,id,&checksum,&debits))return 4;ticks+=src[k].ticks[0]+src[k].ticks[1];continue;}
        Machine *m=dst+k;
        if(init){memset(m,0,sizeof(*m));for(unsigned j=0;j<RECORDS;j++)m->records[j]=record(id,j);
            m->r[2]=id;m->r[4]=id^0xa5a5a5a5u;step(m,1);for(unsigned j=0;j<CUT;j++)step(m,0);
            if(m->status[0]!=RUN||m->status[1]!=WAITING||m->ticks[0]!=CUT)return 4;
            ticks+=CUT;
        }else{
            *m=src[k];if(m->ticks[0]!=CUT||m->status[0]!=RUN||m->status[1]!=WAITING||m->pc[1]!=0||m->mailbox[1])return 4;
            while(m->status[0]!=HALTED&&m->ticks[0]<256)step(m,0);
            if(!m->mailbox[1])return 4;
            while(m->status[1]!=HALTED&&m->ticks[1]<32)step(m,1);
            if(!verify(m,id,&checksum,&debits))return 4;
            ticks+=m->ticks[0]-CUT+m->ticks[1];
            /* A real process exits with a partially modified staging mapping.
             * The original input is mapped read-only and never altered. */
            if(fail&&k+1==(hi-lo)/2)_exit(17);
        }
    }
    double execution=now()-start;start=now();
    if(dst&&(msync(dst,size,MS_SYNC)||fsync(out)))return 5;
    double sync=now()-start;
    printf("{\"lo\":%lu,\"hi\":%lu,\"instructions\":%" PRIu64 ",\"checksum\":%" PRIu64 ",\"debits\":%" PRIu64 ",\"seconds\":%.9f,\"sync_seconds\":%.9f}\n",lo,hi,ticks,checksum,debits,execution,sync);
    if(src){munmap(src,size);close(in);}if(dst){munmap(dst,size);close(out);}return 0;
}
