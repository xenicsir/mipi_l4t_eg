#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <linux/videodev2.h>
#include <poll.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>

static volatile sig_atomic_t interrupted;
static int marker=-1;
static int kmsg=-1;
static uint64_t now_ns(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC,&t); return (uint64_t)t.tv_sec*1000000000ULL+t.tv_nsec; }
static void on_signal(int sig) { interrupted=sig; }
static void event(const char *name) {
    uint64_t t=now_ns();
    printf("{\"event\":\"%s\",\"mono_ns\":%"PRIu64",\"pid\":%d}\n",name,t,getpid());
    if(marker>=0) dprintf(marker,"capture_audit %s pid=%d mono_ns=%"PRIu64"\n",name,getpid(),t);
    if(kmsg>=0) dprintf(kmsg,"<6>eg_capture_audit %s pid=%d mono_ns=%"PRIu64"\n",name,getpid(),t);
}
static int call(int fd,unsigned long op,void *arg) {
    int rc; do { rc=ioctl(fd,op,arg); } while(rc<0&&errno==EINTR&&!interrupted); return rc;
}
struct mapping { void *p; size_t length; };
int main(int argc,char **argv) {
    if(argc<6) { fprintf(stderr,"usage: %s DEVICE VALID_FRAMES BUFFERS HOLD_MS OUTPUT [TRACE_MARKER|-] [REQUEUE_LAST=1]\n",argv[0]); return 64; }
    unsigned int want=strtoul(argv[2],0,10), requested=strtoul(argv[3],0,10), hold=strtoul(argv[4],0,10);
    int requeue=argc<8?1:atoi(argv[7]);
    if(!want||want>10000||requested<2||requested>64||hold>5000) return 64;
    setvbuf(stdout,NULL,_IOLBF,0);
    signal(SIGINT,on_signal);signal(SIGTERM,on_signal);
    kmsg=open("/dev/kmsg",O_WRONLY|O_CLOEXEC|O_NONBLOCK);
    if(argc>6&&strcmp(argv[6],"-")) { marker=open(argv[6],O_WRONLY|O_CLOEXEC); if(marker<0){perror("trace marker");return 1;} }
    int fd=-1,streaming=0,rc=1; unsigned int mapped=0,good=0,bad=0,total=0;
    FILE *out=NULL; struct mapping *maps=NULL; unsigned char *saved=NULL;
    unsigned int image_bytes=0;
    fd=open(argv[1],O_RDWR|O_NONBLOCK|O_CLOEXEC); if(fd<0){perror("open device");goto done;}
    struct v4l2_format fmt={.type=V4L2_BUF_TYPE_VIDEO_CAPTURE};
    if(call(fd,VIDIOC_G_FMT,&fmt)<0){perror("G_FMT");goto done;}
    printf("{\"event\":\"format\",\"width\":%u,\"height\":%u,\"fourcc\":%u,\"stride\":%u,\"sizeimage\":%u}\n",
        fmt.fmt.pix.width,fmt.fmt.pix.height,fmt.fmt.pix.pixelformat,fmt.fmt.pix.bytesperline,fmt.fmt.pix.sizeimage);
    image_bytes=fmt.fmt.pix.sizeimage;
    if(!image_bytes||(uint64_t)want*image_bytes>512ULL*1024*1024){fprintf(stderr,"Capture exceeds RAM budget\n");goto done;}
    saved=malloc((size_t)want*image_bytes);if(!saved){perror("frame storage");goto done;}
    out=fopen(argv[5],"wb");if(!out){perror("output");goto done;}
    struct v4l2_requestbuffers req={.count=requested,.type=V4L2_BUF_TYPE_VIDEO_CAPTURE,.memory=V4L2_MEMORY_MMAP};
    if(call(fd,VIDIOC_REQBUFS,&req)<0){perror("REQBUFS");goto done;}
    if(req.count<2||req.count>64){fprintf(stderr,"Unexpected buffer count %u\n",req.count);goto done;}
    printf("{\"event\":\"buffers\",\"requested\":%u,\"allocated\":%u,\"valid_frames_requested\":%u,\"hold_ms\":%u,\"requeue_last\":%d}\n",requested,req.count,want,hold,requeue);
    maps=calloc(req.count,sizeof(*maps));if(!maps){perror("calloc");goto done;}
    for(unsigned int i=0;i<req.count;i++) {
        struct v4l2_buffer b={.type=req.type,.memory=req.memory,.index=i};
        if(call(fd,VIDIOC_QUERYBUF,&b)<0){perror("QUERYBUF");goto done;}
        maps[i].length=b.length;maps[i].p=mmap(NULL,b.length,PROT_READ|PROT_WRITE,MAP_SHARED,fd,b.m.offset);
        if(maps[i].p==MAP_FAILED){perror("mmap");goto done;}mapped++;
        if(call(fd,VIDIOC_QBUF,&b)<0){perror("QBUF");goto done;}
    }
    enum v4l2_buf_type type=V4L2_BUF_TYPE_VIDEO_CAPTURE;
    event("streamon_enter");
    if(call(fd,VIDIOC_STREAMON,&type)<0){perror("STREAMON");goto done;}
    streaming=1;event("streamon_return");
    while(good<want&&!interrupted&&total<want+64) {
        struct pollfd p={.fd=fd,.events=POLLIN|POLLPRI};
        int n=poll(&p,1,2000);
        if(n<0&&errno==EINTR)continue;
        if(n<=0){fprintf(stderr,"Capture poll timeout/error: %d errno=%d\n",n,errno);goto done;}
        struct v4l2_buffer b={.type=type,.memory=V4L2_MEMORY_MMAP};
        if(call(fd,VIDIOC_DQBUF,&b)<0){if(errno==EAGAIN)continue;perror("DQBUF");goto done;}
        uint64_t dq=now_ns();total++;
        if(b.index>=req.count||b.bytesused>maps[b.index].length){fprintf(stderr,"Invalid returned buffer geometry\n");goto done;}
        const unsigned char *data=maps[b.index].p;
        int error=!!(b.flags&V4L2_BUF_FLAG_ERROR);
        printf("{\"event\":\"dqbuf\",\"mono_ns\":%"PRIu64",\"ordinal\":%u,\"index\":%u,\"sequence\":%u,\"flags\":%u,\"error\":%d,\"bytesused\":%u,\"timestamp_sec\":%ld,\"timestamp_usec\":%ld,\"output_ordinal\":%u}\n",
            dq,total,b.index,b.sequence,b.flags,error,b.bytesused,(long)b.timestamp.tv_sec,(long)b.timestamp.tv_usec,error?0:good+1);
        if(error)bad++;
        else {
            if(b.bytesused!=fmt.fmt.pix.sizeimage){fprintf(stderr,"Unexpected payload size\n");goto done;}
            /* Copy while the buffer belongs to userspace; hash/write after STOP. */
            memcpy(saved+(size_t)good*image_bytes,data,b.bytesused);
            good++;
        }
        if(good<want||requeue)if(call(fd,VIDIOC_QBUF,&b)<0){perror("requeue");goto done;}
    }
    if(good!=want){fprintf(stderr,"Requested valid count not reached\n");goto done;}
    event("last_requested_frame_saved");
    if(hold){event("hold_enter");struct timespec pause={.tv_sec=hold/1000,.tv_nsec=(hold%1000)*1000000};nanosleep(&pause,NULL);event("hold_return");}
    rc=bad?2:0;
done:
    if(streaming){
        enum v4l2_buf_type type=V4L2_BUF_TYPE_VIDEO_CAPTURE;event("streamoff_enter");
        if(call(fd,VIDIOC_STREAMOFF,&type)<0){perror("STREAMOFF");rc=1;}
        event("streamoff_return");
        struct v4l2_buffer b={.type=type,.memory=V4L2_MEMORY_MMAP};errno=0;
        int ret=ioctl(fd,VIDIOC_DQBUF,&b);int err=errno;
        printf("{\"event\":\"post_streamoff_dqbuf\",\"returncode\":%d,\"errno\":%d}\n",ret,err);
        if(ret==0)rc=1;
    }
    for(unsigned int i=0;i<mapped;i++)munmap(maps[i].p,maps[i].length);
    free(maps);if(fd>=0)close(fd);
    if(saved&&out)for(unsigned int i=0;i<good;i++){
        const unsigned char *data=saved+(size_t)i*image_bytes;uint64_t hash=14695981039346656037ULL;
        for(unsigned int j=0;j<image_bytes;j++){hash^=data[j];hash*=1099511628211ULL;}
        printf("{\"event\":\"saved_frame\",\"output_ordinal\":%u,\"fnv1a64\":\"%016"PRIx64"\"}\n",i+1,hash);
        if(fwrite(data,1,image_bytes,out)!=image_bytes){perror("write output");rc=1;break;}
    }
    free(saved);if(out&&fclose(out)!=0)rc=1;
    printf("{\"event\":\"summary\",\"valid_frames\":%u,\"dequeues\":%u,\"error_buffers\":%u,\"signal\":%d,\"returncode\":%d}\n",good,total,bad,interrupted,rc);
    event("closed");if(marker>=0)close(marker);if(kmsg>=0)close(kmsg);return rc;
}
