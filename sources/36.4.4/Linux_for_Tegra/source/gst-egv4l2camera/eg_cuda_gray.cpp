#include "eg_cuda_gray.h"
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <dlfcn.h>
#include <stdexcept>

// Only the stable CUDA Driver C ABI used here is declared. No CUDA Toolkit,
// runtime compiler or CPU pixel mapping is required by the deployed plugin.
namespace cuda_abi {
using Handle = void *;
struct EglFrame {
  union { Handle array[3]; void *pitch[3]; } frame;
  unsigned width, height, depth, pitch, plane_count, channels;
  int frame_type, color_format, channel_format;
};
static_assert(sizeof(EglFrame) == 64 && offsetof(EglFrame, frame_type) == 48,
              "CUDA EGL frame ABI requires LP64");
struct Driver {
  void *library = nullptr;
  int (*init)(unsigned) = nullptr;
  int (*retain)(Handle *, int) = nullptr;
  int (*release)(int) = nullptr;
  int (*push)(Handle) = nullptr;
  int (*pop)(Handle *) = nullptr;
  int (*load)(Handle *, const void *) = nullptr;
  int (*unload)(Handle) = nullptr;
  int (*function)(Handle *, Handle, const char *) = nullptr;
  int (*register_image)(Handle *, void *, unsigned) = nullptr;
  int (*get_frame)(EglFrame *, Handle, unsigned, unsigned) = nullptr;
  int (*unregister_image)(Handle) = nullptr;
  int (*launch)(Handle, unsigned, unsigned, unsigned, unsigned, unsigned, unsigned,
                unsigned, Handle, void **, void **) = nullptr;
  int (*sync)() = nullptr;
  int (*allocate)(uint64_t *, size_t) = nullptr;
  int (*free)(uint64_t) = nullptr;
  int (*error_name)(int, const char **) = nullptr;
  template<typename T> void symbol(T &target, const char *name) {
    target = reinterpret_cast<T>(dlsym(library, name));
    if (!target) throw std::runtime_error(std::string("Missing CUDA entry: ") + name);
  }
  void open() {
    library = dlopen("libcuda.so.1", RTLD_NOW | RTLD_LOCAL);
    if (!library) throw std::runtime_error("CUDA driver library unavailable");
    symbol(init, "cuInit"); symbol(retain, "cuDevicePrimaryCtxRetain");
    symbol(release, "cuDevicePrimaryCtxRelease_v2");
    symbol(push, "cuCtxPushCurrent_v2"); symbol(pop, "cuCtxPopCurrent_v2");
    symbol(load, "cuModuleLoadData"); symbol(unload, "cuModuleUnload");
    symbol(function, "cuModuleGetFunction");
    symbol(register_image, "cuGraphicsEGLRegisterImage");
    symbol(get_frame, "cuGraphicsResourceGetMappedEglFrame");
    symbol(unregister_image, "cuGraphicsUnregisterResource");
    symbol(launch, "cuLaunchKernel"); symbol(sync, "cuCtxSynchronize");
    symbol(allocate, "cuMemAlloc_v2"); symbol(free, "cuMemFree_v2");
    symbol(error_name, "cuGetErrorName");
  }
  void check(int result, const char *operation) {
    if (!result) return;
    const char *name = nullptr;
    if (error_name) error_name(result, &name);
    throw std::runtime_error(std::string(operation) + ": " +
                             (name ? name : "CUDA error") + " (" + std::to_string(result) + ")");
  }
  ~Driver() { if (library) dlclose(library); }
};
}

// Equivalent pixel operation, with independent input/output pitches:
//   value = input16[y][x]; if (swap) value = byteswap16(value);
//   if (rgba) { level = min(value >> (valid_bits - 8), 255); output = (level,level,level,255); }
//   else output16 = value;
// PTX is JIT-compiled by the installed driver. No frame data returns to the CPU.
static const char gray_ptx[] = R"ptx(
.version 7.0
.target sm_53
.address_size 64
.visible .entry eg_gray(
 .param .u64 src, .param .u64 dst,
 .param .u32 sp, .param .u32 dp, .param .u32 w, .param .u32 h,
 .param .u32 shift, .param .u32 swap, .param .u32 rgba,
 .param .u64 range, .param .u32 normalize)
{
 .reg .pred %p<7>;
 .reg .b32 %r<32>;
 .reg .b64 %rd<12>;
 .reg .f32 %f<5>;
 ld.param.u64 %rd0, [src]; ld.param.u64 %rd1, [dst];
 ld.param.u32 %r0, [sp]; ld.param.u32 %r1, [dp];
 ld.param.u32 %r2, [w]; ld.param.u32 %r3, [h];
 ld.param.u32 %r4, [shift]; ld.param.u32 %r5, [swap]; ld.param.u32 %r6, [rgba];
 mov.u32 %r7, %ctaid.x; mov.u32 %r8, %ntid.x; mov.u32 %r9, %tid.x;
 mad.lo.u32 %r10, %r7, %r8, %r9;
 mov.u32 %r7, %ctaid.y; mov.u32 %r8, %ntid.y; mov.u32 %r9, %tid.y;
 mad.lo.u32 %r11, %r7, %r8, %r9;
 setp.ge.u32 %p0, %r10, %r2; setp.ge.u32 %p1, %r11, %r3;
 or.pred %p0, %p0, %p1; @%p0 bra done;
 mul.wide.u32 %rd2, %r11, %r0;
 mad.wide.u32 %rd3, %r10, 2, %rd2; add.u64 %rd3, %rd0, %rd3;
 ld.global.u16 %r12, [%rd3];
 shr.u32 %r13, %r12, 8; shl.b32 %r14, %r12, 8;
 or.b32 %r13, %r13, %r14; and.b32 %r13, %r13, 65535;
 setp.ne.u32 %p2, %r5, 0; selp.b32 %r12, %r13, %r12, %p2;
 mul.wide.u32 %rd4, %r11, %r1;
 setp.ne.u32 %p3, %r6, 0; @!%p3 bra raw;
 mad.wide.u32 %rd5, %r10, 4, %rd4; add.u64 %rd5, %rd1, %rd5;
 ld.param.u32 %r20, [normalize]; setp.eq.u32 %p4, %r20, 0;
 @%p4 bra fixed_range;
 ld.param.u64 %rd9, [range];
 ld.global.u32 %r21, [%rd9]; ld.global.u32 %r22, [%rd9+4];
 sub.u32 %r23, %r22, %r21; mov.u32 %r15, 0;
 setp.eq.u32 %p5, %r23, 0; @%p5 bra store_rgba;
 sub.u32 %r24, %r12, %r21;
 cvt.rn.f32.u32 %f0, %r24; cvt.rn.f32.u32 %f1, %r23;
 mov.f32 %f2, 0f437f0000;
 div.rn.f32 %f3, %f2, %f1; mul.rn.f32 %f4, %f0, %f3;
 cvt.rni.u32.f32 %r15, %f4; min.u32 %r15, %r15, 255;
 bra store_rgba;
fixed_range:
 shr.u32 %r15, %r12, %r4; min.u32 %r15, %r15, 255;
store_rgba:
 mul.lo.u32 %r16, %r15, 65793; or.b32 %r16, %r16, 0xff000000;
 st.global.u32 [%rd5], %r16; bra done;
raw:
 mad.wide.u32 %rd5, %r10, 2, %rd4; add.u64 %rd5, %rd1, %rd5;
 st.global.u16 [%rd5], %r12;
done:
 ret;
}
.visible .entry eg_range_init(.param .u64 range)
{
 .reg .b64 %rd; .reg .b32 %lo, %hi;
 ld.param.u64 %rd, [range]; mov.u32 %lo, 65535; mov.u32 %hi, 0;
 st.global.u32 [%rd], %lo; st.global.u32 [%rd+4], %hi;
 ret;
}
// 64 blocks, 256 threads per block; only two global atomics per block.
.visible .entry eg_range_reduce(
 .param .u64 src, .param .u64 range, .param .u32 pitch,
 .param .u32 width, .param .u32 height, .param .u32 swap)
{
 .shared .align 4 .b8 values[2048];
 .reg .pred %p<5>; .reg .b32 %r<30>; .reg .b64 %rd<8>;
 ld.param.u64 %rd0, [src]; ld.param.u64 %rd1, [range];
 ld.param.u32 %r0, [pitch]; ld.param.u32 %r1, [width];
 ld.param.u32 %r2, [height]; ld.param.u32 %r3, [swap];
 mov.u32 %r4, %tid.x; mov.u32 %r5, %ctaid.x;
 mad.lo.u32 %r6, %r5, 256, %r4; mul.lo.u32 %r7, %r1, %r2;
 mov.u32 %r8, 65535; mov.u32 %r9, 0;
scan:
 setp.ge.u32 %p0, %r6, %r7; @%p0 bra shared_reduce;
 div.u32 %r10, %r6, %r1; mul.lo.u32 %r11, %r10, %r1;
 sub.u32 %r11, %r6, %r11;
 mul.wide.u32 %rd2, %r10, %r0; mad.wide.u32 %rd3, %r11, 2, %rd2;
 add.u64 %rd3, %rd0, %rd3; ld.global.u16 %r12, [%rd3];
 shr.u32 %r13, %r12, 8; shl.b32 %r14, %r12, 8;
 or.b32 %r13, %r13, %r14; and.b32 %r13, %r13, 65535;
 setp.ne.u32 %p1, %r3, 0; selp.b32 %r12, %r13, %r12, %p1;
 min.u32 %r8, %r8, %r12; max.u32 %r9, %r9, %r12;
 add.u32 %r6, %r6, 16384; bra scan;
shared_reduce:
 mov.u32 %r15, values; mad.lo.u32 %r16, %r4, 4, %r15;
 st.shared.u32 [%r16], %r8; st.shared.u32 [%r16+1024], %r9;
 bar.sync 0; mov.u32 %r17, 128;
reduce_step:
 setp.ge.u32 %p2, %r4, %r17; @%p2 bra next_step;
 mad.lo.u32 %r18, %r17, 4, %r16;
 ld.shared.u32 %r19, [%r18]; ld.shared.u32 %r20, [%r18+1024];
 min.u32 %r8, %r8, %r19; max.u32 %r9, %r9, %r20;
 st.shared.u32 [%r16], %r8; st.shared.u32 [%r16+1024], %r9;
next_step:
 bar.sync 0; shr.u32 %r17, %r17, 1;
 setp.ne.u32 %p3, %r17, 0; @%p3 bra reduce_step;
 setp.ne.u32 %p4, %r4, 0; @%p4 bra reduce_done;
 atom.global.min.u32 %r21, [%rd1], %r8;
 atom.global.max.u32 %r22, [%rd1+4], %r9;
reduce_done:
 ret;
}
)ptx";

struct EgCudaEngine {
  cuda_abi::Driver api;
  cuda_abi::Handle context = nullptr, module = nullptr, kernel = nullptr;
  cuda_abi::Handle range_init = nullptr, range_reduce = nullptr;
  std::atomic<unsigned> references{1};
  bool retained = false;
};
struct ContextGuard {
  EgCudaEngine *engine;
  explicit ContextGuard(EgCudaEngine *e) : engine(e) { e->api.check(e->api.push(e->context), "cuCtxPushCurrent"); }
  ~ContextGuard() { cuda_abi::Handle previous; engine->api.pop(&previous); }
};
struct EgCudaFrame {
  EgCudaEngine *engine;
  NvBufSurface *input = nullptr, *output = nullptr;
  cuda_abi::Handle in_resource = nullptr, out_resource = nullptr;
  cuda_abi::EglFrame in_frame{}, out_frame{};
  bool input_mapped = false, output_mapped = false;
  uint64_t range = 0;
  explicit EgCudaFrame(EgCudaEngine *e) : engine(e) { ++e->references; }
};

EgCudaEngine *eg_cuda_create(std::string &error) {
  auto *e = new EgCudaEngine();
  try {
    e->api.open(); e->api.check(e->api.init(0), "cuInit");
    e->api.check(e->api.retain(&e->context, 0), "cuDevicePrimaryCtxRetain");
    e->retained = true;
    ContextGuard guard(e);
    e->api.check(e->api.load(&e->module, gray_ptx), "cuModuleLoadData");
    e->api.check(e->api.function(&e->kernel, e->module, "eg_gray"), "cuModuleGetFunction");
    e->api.check(e->api.function(&e->range_init, e->module, "eg_range_init"), "cuModuleGetFunction(range init)");
    e->api.check(e->api.function(&e->range_reduce, e->module, "eg_range_reduce"), "cuModuleGetFunction(range reduce)");
    return e;
  } catch (const std::exception &ex) { error = ex.what(); eg_cuda_release(e); return nullptr; }
}
void eg_cuda_release(EgCudaEngine *e) {
  if (!e || --e->references) return;
  if (e->retained) {
    try { ContextGuard guard(e); if (e->module) e->api.unload(e->module); } catch (...) {}
    e->api.release(0);
  }
  delete e;
}
EgCudaFrame *eg_cuda_frame_create(EgCudaEngine *e, NvBufSurface *input,
                                  NvBufSurface *output, std::string &error) {
  auto *f = new EgCudaFrame(e); f->input = input; f->output = output;
  try {
    ContextGuard guard(e);
    if (NvBufSurfaceMapEglImage(input, 0)) throw std::runtime_error("Cannot export input EGL image");
    f->input_mapped = true;
    if (NvBufSurfaceMapEglImage(output, 0)) throw std::runtime_error("Cannot export output EGL image");
    f->output_mapped = true;
    e->api.check(e->api.register_image(&f->in_resource, input->surfaceList[0].mappedAddr.eglImage, 1), "cuGraphicsEGLRegisterImage(input)");
    e->api.check(e->api.register_image(&f->out_resource, output->surfaceList[0].mappedAddr.eglImage, 2), "cuGraphicsEGLRegisterImage(output)");
    e->api.check(e->api.get_frame(&f->in_frame, f->in_resource, 0, 0), "cuGraphicsResourceGetMappedEglFrame(input)");
    e->api.check(e->api.get_frame(&f->out_frame, f->out_resource, 0, 0), "cuGraphicsResourceGetMappedEglFrame(output)");
    for (auto *frame : {&f->in_frame, &f->out_frame})
      if (frame->frame_type != 1 || frame->plane_count != 1 || !frame->frame.pitch[0])
        throw std::runtime_error("Expected a single-plane pitch-linear CUDA surface");
    if (output->surfaceList[0].colorFormat == NVBUF_COLOR_FORMAT_RGBA)
      e->api.check(e->api.allocate(&f->range, 8), "cuMemAlloc(range)");
    return f;
  } catch (const std::exception &ex) { error = ex.what(); eg_cuda_frame_destroy(f); return nullptr; }
}
void eg_cuda_frame_destroy(EgCudaFrame *f) {
  if (!f) return;
  auto *e = f->engine;
  try {
    ContextGuard guard(e);
    if (f->range) e->api.free(f->range);
    if (f->in_resource) e->api.unregister_image(f->in_resource);
    if (f->out_resource) e->api.unregister_image(f->out_resource);
  } catch (...) {}
  if (f->input_mapped) NvBufSurfaceUnMapEglImage(f->input, 0);
  if (f->output_mapped) NvBufSurfaceUnMapEglImage(f->output, 0);
  delete f; eg_cuda_release(e);
}
bool eg_cuda_gray(EgCudaFrame *f, unsigned width, unsigned height,
                  unsigned valid_bits, bool byte_swap, bool rgba, std::string &error, bool normalize) {
  try {
    if (valid_bits < 8 || valid_bits > 16 || width > f->in_frame.width ||
        width > f->out_frame.width || height > f->in_frame.height || height > f->out_frame.height ||
        f->in_frame.pitch < width * 2 || f->out_frame.pitch < width * (rgba ? 4 : 2))
      throw std::runtime_error("Invalid CUDA grayscale dimensions or precision");
    auto *e = f->engine; ContextGuard guard(e);
    uint64_t input = reinterpret_cast<uint64_t>(f->in_frame.frame.pitch[0]);
    uint64_t output = reinterpret_cast<uint64_t>(f->out_frame.frame.pitch[0]);
    unsigned shift = valid_bits - 8, swap = byte_swap, rgba_flag = rgba;
    unsigned normalized = rgba && normalize;
    if (normalized) {
      if (!f->range) throw std::runtime_error("Missing GPU normalization workspace");
      void *init_args[] = {&f->range};
      e->api.check(e->api.launch(e->range_init, 1, 1, 1, 1, 1, 1, 0, nullptr, init_args, nullptr), "cuLaunchKernel(range init)");
      void *reduce_args[] = {&input, &f->range, &f->in_frame.pitch, &width, &height, &swap};
      e->api.check(e->api.launch(e->range_reduce, 64, 1, 1, 256, 1, 1, 0, nullptr, reduce_args, nullptr), "cuLaunchKernel(range reduce)");
    }
    void *arguments[] = {&input, &output, &f->in_frame.pitch, &f->out_frame.pitch,
                         &width, &height, &shift, &swap, &rgba_flag, &f->range, &normalized};
    e->api.check(e->api.launch(e->kernel, (width+15)/16, (height+15)/16, 1,
                              16, 16, 1, 0, nullptr, arguments, nullptr), "cuLaunchKernel");
    e->api.check(e->api.sync(), "cuCtxSynchronize");
    return true;
  } catch (const std::exception &ex) { error = ex.what(); return false; }
}
