/* FAB-028: adaptive weighted forest resolution over the full coordinate space. */
#define _POSIX_C_SOURCE 200809L
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <pthread.h>
#include <time.h>
#include <inttypes.h>
typedef struct {uint32_t parent,weight;} Node;
_Static_assert(sizeof(Node)==8,"node geometry");
static double now(void){struct timespec t;if(clock_gettime(CLOCK_MONOTONIC,&t))abort();return t.tv_sec+t.tv_nsec*1e-9;}
static uint32_t mix(uint32_t x){x^=x>>16;x*=0x7feb352du;x^=x>>15;x*=0x846ca68bu;return x^(x>>16);}
static uint32_t coord(uint32_t i,uint32_t mask){return (5u*i+3u)&mask;}
static Node *map_file(const char *path,size_t bytes,int create,int *fd){
    *fd=open(path,create?O_RDWR|O_CREAT|O_EXCL:O_RDONLY,0600);struct stat st;
    if(*fd<0||(create&&ftruncate(*fd,(off_t)bytes))||fstat(*fd,&st)||st.st_size!=(off_t)bytes){perror(path);exit(3);}
    Node *p=mmap(NULL,bytes,create?PROT_READ|PROT_WRITE:PROT_READ,MAP_SHARED,*fd,0);if(p==MAP_FAILED){perror("mmap");exit(3);}return p;
}
typedef struct {const Node *src;Node *dst;uint32_t lo,hi,n;int fail;uint64_t active,unresolved;} Job;
static void *advance(void *ptr){
    Job *j=ptr;
    for(uint32_t i=j->lo;i<j->hi;i++){
        Node x=j->src[i];if(x.parent>=j->n)abort();
        if(x.parent!=3){Node y=j->src[x.parent];if(y.parent>=j->n||UINT32_MAX-x.weight<y.weight)abort();x=(Node){y.parent,x.weight+y.weight};j->active++;}
        j->dst[i]=x;j->unresolved+=x.parent!=3;
        if(j->fail&&i==j->lo+(j->hi-j->lo)/2)_exit(17);
    }return NULL;
}
int main(int argc,char **argv){
    if(argc!=7){fprintf(stderr,"usage: %s init|step|verify bits workers input output fail\n",argv[0]);return 2;}
    unsigned bits=(unsigned)strtoul(argv[2],NULL,10),workers=(unsigned)strtoul(argv[3],NULL,10);
    int init=!strcmp(argv[1],"init"),step=!strcmp(argv[1],"step"),verify=!strcmp(argv[1],"verify"),fail=atoi(argv[6]);
    if(init+step+verify!=1||bits<4||bits>24||workers<1||workers>16||(fail&&!step))return 2;
    uint32_t n=1u<<bits,mask=n-1;size_t bytes=(size_t)n*sizeof(Node);int fi=-1,fo=-1;Node *src=NULL,*dst=NULL;
    if(!init)src=map_file(argv[4],bytes,0,&fi);
    if(!verify)dst=map_file(argv[5],bytes,1,&fo);
    uint64_t active=0,unresolved=0,sum=0;uint32_t max=0;double t=now();
    if(init){
        /* Long backbone plus irregular branches, deliberately permuted physical coordinates. */
        for(uint32_t i=0;i<n;i++){
            uint32_t h=mix(i^0x96a5e713u),p=0;
            if(i>=4)p=(i%4==0)?i-4:4*(h%(i/4+1));
            if(p>=i&&i)p=i-1;
            dst[coord(i,mask)]=(Node){coord(p,mask),i?1+h%15:0};
            unresolved+=p!=0;
        }
    }else if(step){
        pthread_t th[16];Job jobs[16];
        for(unsigned w=0;w<workers;w++){
            jobs[w]=(Job){.src=src,.dst=dst,.lo=(uint32_t)((uint64_t)n*w/workers),.hi=(uint32_t)((uint64_t)n*(w+1)/workers),.n=n,.fail=fail&&w==0};
            if(pthread_create(th+w,NULL,advance,jobs+w))abort();}
        for(unsigned w=0;w<workers;w++){if(pthread_join(th[w],NULL))abort();active+=jobs[w].active;unresolved+=jobs[w].unresolved;}
    }else{
        /* Independent topological dynamic program on original edge records.
         * Does not use pointer jumping, nor the generator's weight formula. */
        dst=map_file(argv[5],bytes,0,&fo);
        uint32_t *dist=calloc(n,sizeof(*dist));uint8_t *seen=calloc(n,1);if(!dist||!seen)return 3;
        for(uint32_t i=0;i<n;i++){
            uint32_t id=coord(i,mask);Node x=src[id];
            if(x.parent>=n||(i==0?(x.parent!=id||x.weight!=0):(!seen[x.parent]||!x.weight)))return 4;
            if(UINT32_MAX-dist[x.parent]<x.weight)return 4;
            dist[id]=dist[x.parent]+x.weight;seen[id]=1;
            if(dst[id].parent!=3||dst[id].weight!=dist[id])return 4;
            sum+=dist[id];if(dist[id]>max)max=dist[id];
        }free(dist);free(seen);
    }
    double execution=now()-t;t=now();if(!verify&&(msync(dst,bytes,MS_SYNC)||fsync(fo)))return 5;
    printf("{\"nodes\":%u,\"active\":%" PRIu64 ",\"unresolved\":%" PRIu64 ",\"distance_sum\":%" PRIu64 ",\"max_distance\":%u,\"seconds\":%.9f,\"sync_seconds\":%.9f}\n",n,active,unresolved,sum,max,execution,now()-t);
    if(src){munmap(src,bytes);close(fi);}if(dst){munmap(dst,bytes);close(fo);}return 0;
}
