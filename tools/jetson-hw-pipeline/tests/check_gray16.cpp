// Synthetic Y16_LE GPU conversion check; no camera is opened.
// Odd dimensions and a full-range pattern exercise row pitch and quantization.
#include "eg_cuda_gray.h"
#include <cstdio>
#include <cstdint>
#include <cstring>
int main() {
 const unsigned w=513,h=257;
 NvBufSurfaceAllocateParams p={};p.params.width=w;p.params.height=h;
 p.params.layout=NVBUF_LAYOUT_PITCH;p.params.memType=NVBUF_MEM_SURFACE_ARRAY;
 p.params.colorFormat=NVBUF_COLOR_FORMAT_GRAY16_LE;
 NvBufSurface *input=nullptr,*output=nullptr;
 if(NvBufSurfaceAllocate(&input,1,&p))return 2;
 p.params.colorFormat=NVBUF_COLOR_FORMAT_RGBA;
 if(NvBufSurfaceAllocate(&output,1,&p))return 3;
 input->numFilled=output->numFilled=1;
 if(NvBufSurfaceMap(input,0,0,NVBUF_MAP_WRITE))return 4;
 for(unsigned y=0;y<h;y++){
  auto *row=(uint16_t*)((uint8_t*)input->surfaceList[0].mappedAddr.addr[0]+y*input->surfaceList[0].pitch);
  for(unsigned x=0;x<w;x++)row[x]=(uint16_t)((y*w+x)*17+1234);
 }
 if(NvBufSurfaceSyncForDevice(input,0,0))return 5;
 NvBufSurfaceUnMap(input,0,0);
 std::string error;auto *engine=eg_cuda_create(error);
 if(!engine){fprintf(stderr,"engine: %s\n",error.c_str());return 6;}
 auto *frame=eg_cuda_frame_create(engine,input,output,error);
 if(!frame){fprintf(stderr,"frame: %s\n",error.c_str());return 7;}
 if(!eg_cuda_gray(frame,w,h,16,false,true,error)){fprintf(stderr,"convert: %s\n",error.c_str());return 8;}
 if(NvBufSurfaceMap(output,0,0,NVBUF_MAP_READ))return 9;
 if(NvBufSurfaceSyncForCpu(output,0,0))return 10;
 unsigned errors=0;
 for(unsigned y=0;y<h;y++){
  auto *row=(uint8_t*)output->surfaceList[0].mappedAddr.addr[0]+y*output->surfaceList[0].pitch;
  for(unsigned x=0;x<w;x++){
   unsigned expected=(uint16_t)((y*w+x)*17+1234)>>8;
   if(row[x*4]!=expected||row[x*4+1]!=expected||row[x*4+2]!=expected||row[x*4+3]!=255)errors++;
  }
 }
 printf("GPU Y16_LE -> RGBA width=%u height=%u pitch=%u/%u pixels=%u errors=%u\n",w,h,input->surfaceList[0].pitch,output->surfaceList[0].pitch,w*h,errors);
 NvBufSurfaceUnMap(output,0,0);eg_cuda_frame_destroy(frame);eg_cuda_release(engine);
 NvBufSurfaceDestroy(input);NvBufSurfaceDestroy(output);
 return errors?1:0;
}
