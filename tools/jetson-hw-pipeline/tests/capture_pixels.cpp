// Diagnostic capture only: CPU pixel mapping must never enter the production source.
// The private buffer layout is guarded by the exact plugin binary fingerprint.
#include <gst/gst.h>
#include <gst/video/video.h>
#include <gst/base/gstbasesrc.h>
#include <sys/select.h>
#include "gstnvv4l2camerasrc.hpp"
#include <cstdio>
#include <cstring>
#include <fstream>
#include <stdexcept>
#include <string>
#ifndef EG_PIXEL_PLUGIN_SHA
#error Build this checker alongside the plugin with --pixel-checker
#endif
struct MemoryLayout { GstMemory memory; GstEgV4l2CameraSrcBuffer *camera; };
struct State {
  std::string directory, format;
  unsigned width, height, seen=0, saved=0, errors=0, rendered=0, output_seen=0, warmup_corrupt=0;
  bool gray, processed;
};
static void dump(NvBufSurface *surface, const std::string &path,
                 unsigned width_bytes, unsigned height) {
  if (!surface || surface->surfaceList[0].height < height ||
      surface->surfaceList[0].pitch < width_bytes)
    throw std::runtime_error("Invalid diagnostic surface dimensions");
  if (NvBufSurfaceMap(surface,0,0,NVBUF_MAP_READ)) throw std::runtime_error("Surface map failed");
  try {
    if (NvBufSurfaceSyncForCpu(surface,0,0)) throw std::runtime_error("Surface CPU sync failed");
    std::ofstream file(path,std::ios::binary);
    auto &s=surface->surfaceList[0];
    for (unsigned y=0;y<height;++y)
      file.write(static_cast<char*>(s.mappedAddr.addr[0])+y*s.pitch,width_bytes);
    if (!file) throw std::runtime_error("Cannot write diagnostic frame");
  } catch (...) { NvBufSurfaceUnMap(surface,0,0); throw; }
  NvBufSurfaceUnMap(surface,0,0);
}
static GstPadProbeReturn capture(GstPad*, GstPadProbeInfo *info, gpointer data) {
  auto &s=*static_cast<State*>(data);auto *buffer=GST_PAD_PROBE_INFO_BUFFER(info);
  if (!buffer) return GST_PAD_PROBE_OK;
  ++s.seen;
  if (s.seen<=5) {
    if (GST_BUFFER_FLAG_IS_SET(buffer,GST_BUFFER_FLAG_CORRUPTED)) ++s.warmup_corrupt;
    return GST_PAD_PROBE_OK;
  }
  if (GST_BUFFER_FLAG_IS_SET(buffer,GST_BUFFER_FLAG_CORRUPTED)) {++s.errors;return GST_PAD_PROBE_OK;}
  try {
    auto *memory=gst_buffer_peek_memory(buffer,0);
    if (!memory || !gst_memory_is_type(memory,"egV4l2Memory")) throw std::runtime_error("Unexpected allocator");
    auto *camera=reinterpret_cast<MemoryLayout*>(memory)->camera;
    auto *raw=camera->surface;auto *out=s.processed?camera->processed_surface:raw;
    NvBufSurfaceColorFormat expected=s.processed || s.format=="AB24"?NVBUF_COLOR_FORMAT_RGBA:
        s.format=="AR24"?NVBUF_COLOR_FORMAT_BGRx:NVBUF_COLOR_FORMAT_YUYV;
    if (!out || out->surfaceList[0].width!=s.width || out->surfaceList[0].height!=s.height ||
        out->surfaceList[0].colorFormat!=expected) throw std::runtime_error("Wrong NVMM pixel layout");
    unsigned input_bpp=s.gray||s.format=="YUYV"?2:4;
    std::string stem=s.directory+"/frame-"+std::to_string(s.saved);
    dump(raw,stem+"-capture.bin",s.width*input_bpp,s.height);
    dump(out,stem+"-output.bin",s.width*(s.processed?4:input_bpp),s.height);
    ++s.saved;
  } catch (const std::exception &e) {fprintf(stderr,"%s\n",e.what());++s.errors;}
  return GST_PAD_PROBE_OK;
}
static GstPadProbeReturn render_capture(GstPad*, GstPadProbeInfo *info, gpointer data) {
  auto &s=*static_cast<State*>(data);auto *buffer=GST_PAD_PROBE_INFO_BUFFER(info);
  if (!buffer || ++s.output_seen<=5) return GST_PAD_PROBE_OK;
  GstMapInfo map=GST_MAP_INFO_INIT;
  if(!gst_buffer_map(buffer,&map,GST_MAP_READ)){++s.errors;return GST_PAD_PROBE_OK;}
  try {
    if(map.size<sizeof(NvBufSurface))throw std::runtime_error("Missing output NvBufSurface");
    auto *surface=reinterpret_cast<NvBufSurface*>(map.data);
    if(surface->surfaceList[0].colorFormat!=NVBUF_COLOR_FORMAT_RGBA)throw std::runtime_error("Expected RGBA diagnostic output");
    dump(surface,s.directory+"/frame-"+std::to_string(s.rendered)+"-display.bin",s.width*4,s.height);
    ++s.rendered;
  }catch(const std::exception &e){fprintf(stderr,"%s\n",e.what());++s.errors;}
  gst_buffer_unmap(buffer,&map);return GST_PAD_PROBE_OK;
}
int main(int argc,char **argv) {
  gst_init(&argc,&argv);
  if (argc!=7 && argc!=8) {fprintf(stderr,"Usage: %s DEVICE FORMAT WIDTH HEIGHT fixed|normalized OUTPUT_DIRECTORY\n",argv[0]);return 2;}
  const std::string fmt=argv[2];bool gray=fmt=="Y16"||fmt=="Y14"||fmt=="Y16_BE";
  if (!gray && fmt!="AR24" && fmt!="AB24" && fmt!="YUYV") return 2;
  unsigned w=strtoul(argv[3],nullptr,10),h=strtoul(argv[4],nullptr,10);
  if (!w||!h||w>16384||h>16384) return 2;
  if (strcmp(argv[5],"fixed") && strcmp(argv[5],"normalized")) return 2;
  auto *factory=gst_element_factory_find("egv4l2camerasrc");
  auto *feature=factory?gst_plugin_feature_load(GST_PLUGIN_FEATURE(factory)):nullptr;
  auto *plugin=feature?gst_plugin_feature_get_plugin(feature):nullptr;
  const char *filename=plugin?gst_plugin_get_filename(plugin):nullptr;
  gchar *bytes=nullptr;gsize length=0;
  if (!filename||!g_file_get_contents(filename,&bytes,&length,nullptr)) {fprintf(stderr,"Cannot identify loaded plugin\n");return 2;}
  gchar *sha=g_compute_checksum_for_data(G_CHECKSUM_SHA256,reinterpret_cast<guchar*>(bytes),length);g_free(bytes);
  bool match=!strcmp(sha,EG_PIXEL_PLUGIN_SHA);g_free(sha);
  if (plugin) gst_object_unref(plugin);
  if (feature) gst_object_unref(feature);
  if (factory) gst_object_unref(factory);
  if(!match){fprintf(stderr,"Pixel checker/plugin fingerprint mismatch; rebuild with --pixel-checker\n");return 2;}
  GError *error=nullptr;
  std::string description="egv4l2camerasrc name=src ! capsfilter name=caps";
  const std::string vic_output=argc==8?argv[7]:"NV12";
  if(vic_output!="NV12" && vic_output!="RGBA" && vic_output!="CUDA") return 2;
  if(fmt=="AR24"||(fmt=="YUYV"&&vic_output!="CUDA")) {
    description+=" ! nvvidconv compute-hw=2 ! video/x-raw(memory:NVMM),format="+vic_output;
    if(vic_output=="NV12") description+=" ! nvvidconv compute-hw=2 ! video/x-raw(memory:NVMM),format=RGBA";
  }
  description+=" ! fakesink name=out sync=false";
  auto *pipeline=gst_parse_launch(description.c_str(),&error);
  if(!pipeline||error){fprintf(stderr,"Cannot create pipeline\n");return 2;}
  auto *src=gst_bin_get_by_name(GST_BIN(pipeline),"src");
  g_object_set(src,"device",argv[1],"num-buffers",8,nullptr);
  bool processed=gray||(fmt=="YUYV"&&vic_output=="CUDA");
  if(processed)g_object_set(src,"capture-format",argv[2],"preview",TRUE,"normalize",!strcmp(argv[5],"normalized"),nullptr);
  const char *output=processed||fmt=="AB24"?"RGBA":fmt=="AR24"?"BGRx":"YUY2";
  auto *caps=gst_caps_new_simple("video/x-raw","format",G_TYPE_STRING,output,
      "width",G_TYPE_INT,int(w),"height",G_TYPE_INT,int(h),nullptr);
  gst_caps_set_features(caps,0,gst_caps_features_new("memory:NVMM",nullptr));
  auto *filter=gst_bin_get_by_name(GST_BIN(pipeline),"caps");g_object_set(filter,"caps",caps,nullptr);
  gst_caps_unref(caps);gst_object_unref(filter);
  State state{argv[6],fmt,w,h,0,0,0,0,0,0,gray,processed};
  auto *pad=gst_element_get_static_pad(src,"src");gst_pad_add_probe(pad,GST_PAD_PROBE_TYPE_BUFFER,capture,&state,nullptr);
  auto *sink=gst_bin_get_by_name(GST_BIN(pipeline),"out");auto *sink_pad=gst_element_get_static_pad(sink,"sink");
  gst_pad_add_probe(sink_pad,GST_PAD_PROBE_TYPE_BUFFER,render_capture,&state,nullptr);
  auto *bus=gst_element_get_bus(pipeline);bool okay=gst_element_set_state(pipeline,GST_STATE_PLAYING)!=GST_STATE_CHANGE_FAILURE;
  auto *message=okay?gst_bus_timed_pop_filtered(bus,8*GST_SECOND,GstMessageType(GST_MESSAGE_ERROR|GST_MESSAGE_EOS)):nullptr;
  if(!message||GST_MESSAGE_TYPE(message)==GST_MESSAGE_ERROR){
    okay=false;if(message){gchar *debug=nullptr;gst_message_parse_error(message,&error,&debug);fprintf(stderr,"%s (%s)\n",error->message,debug?debug:"");g_error_free(error);g_free(debug);}
  }
  gst_element_set_state(pipeline,GST_STATE_NULL);
  okay=okay&&state.saved==3&&state.rendered==3&&state.errors==0;
  std::ofstream meta(std::string(argv[6])+"/capture.json");
  meta<<"{\"warmup_frames\":5,\"warmup_corrupt\":"<<state.warmup_corrupt<<",\"frames\":"<<state.saved<<",\"errors\":"<<state.errors<<",\"width\":"<<w<<",\"height\":"<<h
      <<",\"format\":\""<<fmt<<"\",\"output_format\":\""<<output<<"\",\"plugin_sha256\":\""<<EG_PIXEL_PLUGIN_SHA<<"\"}\n";
  printf("frames=%u errors=%u\n",state.saved,state.errors);
  if(message) gst_message_unref(message);
  gst_object_unref(bus);gst_object_unref(sink_pad);gst_object_unref(sink);gst_object_unref(pad);gst_object_unref(src);gst_object_unref(pipeline);
  return okay&&meta?0:1;
}
