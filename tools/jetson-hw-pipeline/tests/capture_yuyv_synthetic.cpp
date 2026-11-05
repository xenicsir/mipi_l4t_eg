// CPU writes/reads here are a test oracle, not a production video path.
#include "eg_cuda_gray.h"
#include <cstdio>
#include <fstream>
#include <string>
int main(int argc,char **argv) {
  if(argc!=2)return 2;
  const unsigned w=256,h=256;
  NvBufSurfaceAllocateParams p={};p.params.width=w*2;p.params.height=h;
  p.params.layout=NVBUF_LAYOUT_PITCH;p.params.memType=NVBUF_MEM_SURFACE_ARRAY;
  p.params.colorFormat=NVBUF_COLOR_FORMAT_GRAY8;
  NvBufSurface *input=nullptr,*output=nullptr;
  if(NvBufSurfaceAllocate(&input,1,&p))return 2;
  p.params.width=w;p.params.colorFormat=NVBUF_COLOR_FORMAT_RGBA;
  if(NvBufSurfaceAllocate(&output,1,&p))return 2;
  input->numFilled=output->numFilled=1;
  if(NvBufSurfaceMap(input,0,0,NVBUF_MAP_WRITE))return 2;
  std::ofstream raw(std::string(argv[1])+"/synthetic-yuyv.bin",std::ios::binary);
  for(unsigned y=0;y<h;++y){
    auto *row=(unsigned char*)input->surfaceList[0].mappedAddr.addr[0]+y*input->surfaceList[0].pitch;
    for(unsigned x=0;x<w;x+=2){
      row[x*2]=(x+y*13)&255;row[x*2+2]=(x+1+y*13)&255;
      row[x*2+1]=(x+y*7)&255;row[x*2+3]=(x*19+y*3)&255;
    }
    raw.write((char*)row,w*2);
  }
  if(!raw || NvBufSurfaceSyncForDevice(input,0,0))return 2;
  NvBufSurfaceUnMap(input,0,0);
  std::string error;auto *engine=eg_cuda_create(error);
  auto *frame=engine?eg_cuda_frame_create(engine,input,output,error):nullptr;
  if(!frame || !eg_cuda_gray(frame,w,h,8,false,true,error,false,true)){
    fprintf(stderr,"%s\n",error.c_str());return 1;
  }
  if(NvBufSurfaceMap(output,0,0,NVBUF_MAP_READ)||NvBufSurfaceSyncForCpu(output,0,0))return 2;
  std::ofstream result(std::string(argv[1])+"/synthetic-rgba.bin",std::ios::binary);
  for(unsigned y=0;y<h;++y)result.write((char*)output->surfaceList[0].mappedAddr.addr[0]+y*output->surfaceList[0].pitch,w*4);
  NvBufSurfaceUnMap(output,0,0);eg_cuda_frame_destroy(frame);eg_cuda_release(engine);
  NvBufSurfaceDestroy(input);NvBufSurfaceDestroy(output);
  return result?0:1;
}
