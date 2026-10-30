#ifndef EG_CUDA_GRAY_H
#define EG_CUDA_GRAY_H
#include "nvbufsurface.h"
#include <string>
struct EgCudaEngine;
struct EgCudaFrame;
EgCudaEngine *eg_cuda_create(std::string &error);
void eg_cuda_release(EgCudaEngine *engine);
EgCudaFrame *eg_cuda_frame_create(EgCudaEngine *engine, NvBufSurface *input,
                                  NvBufSurface *output, std::string &error);
void eg_cuda_frame_destroy(EgCudaFrame *frame);
bool eg_cuda_gray(EgCudaFrame *frame, unsigned width, unsigned height,
                  unsigned valid_bits, bool byte_swap, bool rgba, std::string &error,
                  bool normalize = false);
#endif
