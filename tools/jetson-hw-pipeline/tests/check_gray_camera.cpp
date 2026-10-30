// Diagnostic only: maps camera and GPU output pixels on the CPU for comparison.
// Uses private plugin buffer layout: compile with headers matching the loaded plugin.
#include <gst/gst.h>
#include <gst/video/video.h>
#include <gst/base/gstbasesrc.h>
#include <sys/select.h>
#include "gstnvv4l2camerasrc.hpp"
#include <cstdio>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <string>
#include <cmath>
#include <algorithm>

struct MemoryLayout { GstMemory memory; GstEgV4l2CameraSrcBuffer *camera; };
struct Check {
  bool preview, big_endian, normalize;
  unsigned bits, width, height, frames = 0, corrupt = 0;
  uint64_t pixels = 0, errors = 0;
  uint16_t minimum = 65535, maximum = 0;
};

static GstPadProbeReturn check_frame(GstPad *, GstPadProbeInfo *info, gpointer arg) {
  auto &c = *static_cast<Check *>(arg);
  GstBuffer *buffer = GST_PAD_PROBE_INFO_BUFFER(info);
  if (!buffer) return GST_PAD_PROBE_OK;
  ++c.frames;
  if (GST_BUFFER_FLAG_IS_SET(buffer, GST_BUFFER_FLAG_CORRUPTED)) ++c.corrupt;
  GstMemory *memory = gst_buffer_peek_memory(buffer, 0);
  if (!memory || !gst_memory_is_type(memory, "egV4l2Memory")) {
    ++c.errors; return GST_PAD_PROBE_OK;
  }
  auto *camera = reinterpret_cast<MemoryLayout *>(memory)->camera;
  NvBufSurface *raw = camera->surface;
  NvBufSurface *out = camera->processed_surface;
  const bool processed = c.preview || c.big_endian;
  if (!raw || raw->surfaceList[0].width != c.width || raw->surfaceList[0].height != c.height ||
      raw->surfaceList[0].colorFormat != NVBUF_COLOR_FORMAT_GRAY16_LE ||
      (processed && (!out || !camera->cuda_frame || out->surfaceList[0].width != c.width ||
       out->surfaceList[0].height != c.height || out->surfaceList[0].colorFormat !=
       (c.preview ? NVBUF_COLOR_FORMAT_RGBA : NVBUF_COLOR_FORMAT_GRAY16_LE))) ||
      (!processed && (out || camera->cuda_frame))) {
    ++c.errors; return GST_PAD_PROBE_OK;
  }
  if (NvBufSurfaceMap(raw, 0, 0, NVBUF_MAP_READ)) { ++c.errors; return GST_PAD_PROBE_OK; }
  if (NvBufSurfaceSyncForCpu(raw, 0, 0)) {
    ++c.errors; NvBufSurfaceUnMap(raw, 0, 0); return GST_PAD_PROBE_OK;
  }
  if (processed) {
    if (NvBufSurfaceMap(out, 0, 0, NVBUF_MAP_READ)) {
      ++c.errors; NvBufSurfaceUnMap(raw, 0, 0); return GST_PAD_PROBE_OK;
    }
    if (NvBufSurfaceSyncForCpu(out, 0, 0)) {
      ++c.errors; NvBufSurfaceUnMap(out, 0, 0); NvBufSurfaceUnMap(raw, 0, 0); return GST_PAD_PROBE_OK;
    }
  }
  unsigned frame_min = 65535, frame_max = 0;
  if (c.preview && c.normalize) for (unsigned y = 0; y < c.height; ++y) {
    const auto *row = static_cast<const uint8_t *>(raw->surfaceList[0].mappedAddr.addr[0]) + y*raw->surfaceList[0].pitch;
    for (unsigned x = 0; x < c.width; ++x) {
      unsigned v = c.big_endian ? (row[2*x]<<8)|row[2*x+1] : row[2*x]|(row[2*x+1]<<8);
      frame_min = std::min(frame_min,v); frame_max = std::max(frame_max,v);
    }
  }
  for (unsigned y = 0; y < c.height; ++y) {
    const auto *input = static_cast<const uint8_t *>(raw->surfaceList[0].mappedAddr.addr[0]) +
                        y * raw->surfaceList[0].pitch;
    const auto *output = processed ? static_cast<const uint8_t *>(out->surfaceList[0].mappedAddr.addr[0]) +
                                    y * out->surfaceList[0].pitch : input;
    for (unsigned x = 0; x < c.width; ++x) {
      unsigned value = c.big_endian ? (input[2*x] << 8) | input[2*x+1] :
                                     input[2*x] | (input[2*x+1] << 8);
      if (value < c.minimum) c.minimum = value;
      if (value > c.maximum) c.maximum = value;
      if (c.bits == 14 && value >= 16384) ++c.errors;
      if (c.preview) {
        unsigned expected = c.normalize ? (frame_max == frame_min ? 0 :
            unsigned(std::nearbyint(double(value-frame_min)*255/(frame_max-frame_min)))) : value >> (c.bits-8);
        if (unsigned(std::abs(int(output[4*x])-int(expected))) > (c.normalize?1u:0u) ||
            output[4*x+1] != output[4*x] || output[4*x+2] != output[4*x] || output[4*x+3] != 255) ++c.errors;
      } else if ((unsigned(output[2*x]) | (unsigned(output[2*x+1]) << 8)) != value) ++c.errors;
      ++c.pixels;
    }
  }
  if (processed) NvBufSurfaceUnMap(out, 0, 0);
  NvBufSurfaceUnMap(raw, 0, 0);
  return GST_PAD_PROBE_OK;
}

int main(int argc, char **argv) {
  gst_init(&argc, &argv);
  if ((argc != 6 && argc != 7) || (strcmp(argv[2], "Y14") && strcmp(argv[2], "Y16") && strcmp(argv[2], "Y16_BE")) ||
      (strcmp(argv[5], "raw") && strcmp(argv[5], "preview"))) {
    fprintf(stderr, "Usage: %s /dev/videoN Y14|Y16|Y16_BE width height raw|preview [normalized|fixed]\n", argv[0]); return 2;
  }
  if (argc == 7 && strcmp(argv[6], "normalized") && strcmp(argv[6], "fixed")) return 2;
  const bool normalize = argc == 7 && !strcmp(argv[6], "normalized");
  const unsigned width = strtoul(argv[3], nullptr, 10), height = strtoul(argv[4], nullptr, 10);
  if (!width || !height || width > 16384 || height > 16384) return 2;
  const bool preview = !strcmp(argv[5], "preview"), be = !strcmp(argv[2], "Y16_BE");
  const unsigned bits = !strcmp(argv[2], "Y14") ? 14 : 16;
  GError *error = nullptr;
  GstElement *pipeline = gst_parse_launch(
      "egv4l2camerasrc name=src ! capsfilter name=caps ! fakesink sync=false", &error);
  if (!pipeline || error) { fprintf(stderr, "Pipeline: %s\n", error ? error->message : "failed"); return 2; }
  GstElement *src = gst_bin_get_by_name(GST_BIN(pipeline), "src");
  GstElement *filter = gst_bin_get_by_name(GST_BIN(pipeline), "caps");
  g_object_set(src, "device", argv[1], "capture-format", argv[2], "preview", preview,
               "normalize", normalize, "num-buffers", 30, nullptr);
  GstCaps *caps = gst_caps_new_simple("video/x-raw", "format", G_TYPE_STRING,
      preview ? "RGBA" : "GRAY16_LE", "width", G_TYPE_INT, int(width), "height", G_TYPE_INT, int(height), nullptr);
  gst_caps_set_features(caps, 0, gst_caps_features_new("memory:NVMM", nullptr));
  g_object_set(filter, "caps", caps, nullptr); gst_caps_unref(caps); gst_object_unref(filter);
  GstPad *pad = gst_element_get_static_pad(src, "src");
  Check check{preview, be, normalize, bits, width, height};
  gst_pad_add_probe(pad, GST_PAD_PROBE_TYPE_BUFFER, check_frame, &check, nullptr);
  GstBus *bus = gst_element_get_bus(pipeline);
  bool okay = true;
  for (unsigned cycle = 0; cycle < 2; ++cycle) {
    check = Check{preview, be, normalize, bits, width, height};
    if (gst_element_set_state(pipeline, GST_STATE_PLAYING) == GST_STATE_CHANGE_FAILURE) { okay = false; break; }
    GstMessage *message = gst_bus_timed_pop_filtered(bus, 10*GST_SECOND,
        GstMessageType(GST_MESSAGE_ERROR | GST_MESSAGE_EOS));
    if (!message || GST_MESSAGE_TYPE(message) == GST_MESSAGE_ERROR) {
      if (message) {
        gchar *debug = nullptr; gst_message_parse_error(message, &error, &debug);
        fprintf(stderr, "%s (%s)\n", error->message, debug ? debug : "");
        g_error_free(error); g_free(debug);
      }
      okay = false;
    }
    gst_element_set_state(pipeline, GST_STATE_NULL);
    printf("cycle=%u format=%s mode=%s frames=%u pixels=%llu errors=%llu corrupt=%u min=%u max=%u\n",
        cycle, argv[2], argv[5], check.frames, (unsigned long long)check.pixels,
        (unsigned long long)check.errors, check.corrupt, check.minimum, check.maximum);
    okay = okay && check.frames == 30 && check.pixels == uint64_t(width)*height*30 && !check.errors && !check.corrupt;
    if (message) gst_message_unref(message);
    if (!okay) break;
    if (!cycle) g_usleep(3000000);
  }
  gst_object_unref(pad); gst_object_unref(src); gst_object_unref(bus); gst_object_unref(pipeline);
  return okay ? 0 : 1;
}
