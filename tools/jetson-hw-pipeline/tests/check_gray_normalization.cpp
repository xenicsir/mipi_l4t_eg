// Synthetic GPU checks: extrema, constant frames, byte order and pitched rows.
// CPU access here is an oracle only; production frames stay on the GPU.
#include "eg_cuda_gray.h"
#include <cstdio>
#include <cstdint>
#include <cmath>
#include <algorithm>
#include <string>

static unsigned sample(unsigned x, unsigned y, unsigned w, unsigned bits, unsigned pattern) {
  unsigned mask = (1u << bits)-1;
  if (pattern == 1) return mask;
  if (pattern == 2) return 0;
  if (pattern == 3) return 512 + ((y*w+x)*17 % 37);
  return ((y*w+x)*17+1234) & mask;
}
static bool run(EgCudaEngine *engine, unsigned w, unsigned h, unsigned bits,
                bool be, unsigned pattern, bool normalize, bool rgba) {
  NvBufSurfaceAllocateParams p={};p.params.width=w;p.params.height=h;
  p.params.layout=NVBUF_LAYOUT_PITCH;p.params.memType=NVBUF_MEM_SURFACE_ARRAY;
  p.params.colorFormat=NVBUF_COLOR_FORMAT_GRAY16_LE;
  NvBufSurface *input=nullptr,*output=nullptr;
  if (NvBufSurfaceAllocate(&input,1,&p)) return false;
  p.params.colorFormat=rgba?NVBUF_COLOR_FORMAT_RGBA:NVBUF_COLOR_FORMAT_GRAY16_LE;
  if (NvBufSurfaceAllocate(&output,1,&p)) return false;
  input->numFilled=output->numFilled=1;
  if (NvBufSurfaceMap(input,0,0,NVBUF_MAP_WRITE)) return false;
  unsigned lo=65535,hi=0;
  for(unsigned y=0;y<h;++y) {
    auto *row=(uint8_t*)input->surfaceList[0].mappedAddr.addr[0]+y*input->surfaceList[0].pitch;
    for(unsigned x=0;x<w;++x) {
      unsigned v=sample(x,y,w,bits,pattern);lo=std::min(lo,v);hi=std::max(hi,v);
      row[2*x]=be?v>>8:v&255; row[2*x+1]=be?v&255:v>>8;
    }
  }
  if (NvBufSurfaceSyncForDevice(input,0,0)) return false;
  NvBufSurfaceUnMap(input,0,0);
  std::string error;auto *frame=eg_cuda_frame_create(engine,input,output,error);
  if (!frame) {fprintf(stderr,"%s\n",error.c_str());return false;}
  if (!eg_cuda_gray(frame,w,h,bits,be,rgba,error,normalize)) {fprintf(stderr,"%s\n",error.c_str());return false;}
  if (NvBufSurfaceMap(output,0,0,NVBUF_MAP_READ)||NvBufSurfaceSyncForCpu(output,0,0))return false;
  uint64_t errors=0;unsigned max_delta=0;
  for(unsigned y=0;y<h;++y) {
    auto *row=(uint8_t*)output->surfaceList[0].mappedAddr.addr[0]+y*output->surfaceList[0].pitch;
    for(unsigned x=0;x<w;++x) {
      unsigned v=sample(x,y,w,bits,pattern);
      if (rgba) {
        unsigned expected=normalize?(hi==lo?0:unsigned(std::nearbyint(double(v-lo)*255/(hi-lo)))):v>>(bits-8);
        unsigned delta=unsigned(std::abs(int(row[4*x])-int(expected)));max_delta=std::max(max_delta,delta);
        if (delta>(normalize?1u:0u)||row[4*x]!=row[4*x+1]||row[4*x]!=row[4*x+2]||row[4*x+3]!=255)++errors;
      } else if ((unsigned(row[2*x])|(unsigned(row[2*x+1])<<8))!=v)++errors;
    }
  }
  printf("size=%ux%u bits=%u be=%d pattern=%u normalize=%d rgba=%d pixels=%llu errors=%llu max_delta=%u\n",w,h,bits,be,pattern,normalize,rgba,(unsigned long long)w*h,(unsigned long long)errors,max_delta);
  NvBufSurfaceUnMap(output,0,0);eg_cuda_frame_destroy(frame);NvBufSurfaceDestroy(input);NvBufSurfaceDestroy(output);
  return errors==0;
}
int main() {
  std::string error;auto *engine=eg_cuda_create(error);
  if (!engine){fprintf(stderr,"%s\n",error.c_str());return 2;}
  bool okay=true;
  for(unsigned bits:{14u,16u})for(bool be:{false,true})for(unsigned pattern:{0u,1u,2u,3u})
    for(bool normalize:{false,true})okay=run(engine,513,257,bits,be,pattern,normalize,true)&&okay;
  for(bool be:{false,true}) {
    okay=run(engine,1,1,16,be,0,true,true)&&okay;
    okay=run(engine,1280,1024,16,be,3,true,true)&&okay;
    okay=run(engine,513,257,16,be,0,false,false)&&okay;
  }
  eg_cuda_release(engine);return okay?0:1;
}
