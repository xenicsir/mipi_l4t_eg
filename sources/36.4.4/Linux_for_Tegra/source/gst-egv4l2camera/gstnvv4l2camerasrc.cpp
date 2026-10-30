/*
 * Copyright (c) 2019-2024, NVIDIA CORPORATION. All rights reserved.
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions
 * are met:
 *  * Redistributions of source code must retain the above copyright
 *    notice, this list of conditions and the following disclaimer.
 *  * Redistributions in binary form must reproduce the above copyright
 *    notice, this list of conditions and the following disclaimer in the
 *    documentation and/or other materials provided with the distribution.
 *  * Neither the name of NVIDIA CORPORATION nor the names of its
 *    contributors may be used to endorse or promote products derived
 *    from this software without specific prior written permission.
 *
 * THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS ``AS IS'' AND ANY
 * EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
 * IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
 * PURPOSE ARE DISCLAIMED.  IN NO EVENT SHALL THE COPYRIGHT OWNER OR
 * CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
 * EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
 * PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
 * PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY
 * OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
 * (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
 * OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
 */

/**
 * Sample pipeline
 *
 * gst-launch-1.0 egv4l2camerasrc device=/dev/video3 !
 * 'video/x-raw(memory:NVMM), format=(string)UYVY, width=(int)1920, height=(int)576, interlace-mode=interlaced, framerate=(fraction)25/1' !
 * nvdeinterlace mode=3 !
 * 'video/x-raw(memory:NVMM), format=(string)NV12' !
 * nv3dsink
 */

/* Gstreamer includes */
#include <gst/gst.h>
#include <gst/video/video.h>
#include <gst/base/gstbasesrc.h>

/* Basic I/O includes */
#include <cstring>
#include <iostream>
#include <unistd.h>

/* Library header include */
#include "nvbufsurface.h"
#include "gstnvv4l2camerasrc.hpp"
#include "gstnvv4l2camerabufferpool.h"

/* v4l2 specific includes */
#include <fcntl.h>
#include <linux/videodev2.h>
#include <sys/ioctl.h>

/* Capture caps of plugin */
#define CAPTURE_CAPS \
  "video/x-raw(memory:NVMM), " \
  "width = (int) [ 1, MAX ], " \
  "height = (int) [ 1, MAX ], " \
  "format = (string) { UYVY, YUY2, RGBA, BGRA, BGRx, GRAY16_LE }, " \
  "interlace-mode = (string) { progressive, interlaced }, " \
  "framerate = (fraction) [ 0, MAX ];"

GST_DEBUG_CATEGORY_STATIC (gst_eg_v4l2_camera_src_debug);
#define GST_CAT_DEFAULT gst_eg_v4l2_camera_src_debug

#define MAX_SEARCH_COUNT 32

enum
{
  PROP_0,
  PROP_DEVICE,
  PROP_CAPTURE_BUFFERS,
  PROP_CAPTURE_FORMAT,
  PROP_PREVIEW,
  PROP_NORMALIZE,
  PROP_CAPTURE_BITS
};

struct _GstEGV4l2Memory
{
  GstMemory mem;
  GstEgV4l2CameraSrcBuffer *nvcam_buf;
};

struct _GstEGV4l2MemoryAllocator
{
  GstAllocator parent;
  GstEgV4l2CameraSrc *owner;
};

struct _GstEGV4l2MemoryAllocatorClass
{
  GstAllocatorClass parent_class;
};

static GstStaticPadTemplate src_factory = GST_STATIC_PAD_TEMPLATE ("src",
  GST_PAD_SRC,
  GST_PAD_ALWAYS,
  GST_STATIC_CAPS (CAPTURE_CAPS)
  );

struct _GstEgV4l2CameraBufferPoolPrivate
{
  GstCaps *caps;
  GstVideoInfo info;
  GstAllocator *allocator;
  GstAllocationParams params;
  guint size;
};

typedef struct _GstEGV4l2Memory GstEGV4l2Memory;
typedef struct _GstEGV4l2MemoryAllocator GstEGV4l2MemoryAllocator;
typedef struct _GstEGV4l2MemoryAllocatorClass GstEGV4l2MemoryAllocatorClass;

GType gst_eg_memory_allocator_get_type (void);
#define GST_TYPE_NV_MEMORY_ALLOCATOR   (gst_eg_memory_allocator_get_type())

#define gst_egv4l2camera_buffer_pool_parent_class bpool_parent_class
G_DEFINE_TYPE_WITH_CODE (GstEgV4l2CameraBufferPool, gst_egv4l2camera_buffer_pool, GST_TYPE_BUFFER_POOL, G_ADD_PRIVATE(GstEgV4l2CameraBufferPool));

#define gst_eg_v4l2_camera_src_parent_class parent_class
G_DEFINE_TYPE (GstEgV4l2CameraSrc, gst_eg_v4l2_camera_src, GST_TYPE_BASE_SRC);
G_DEFINE_TYPE (GstEGV4l2MemoryAllocator, gst_eg_memory_allocator, GST_TYPE_ALLOCATOR);

#define GST_NVMEMORY_ALLOCATOR(obj) (G_TYPE_CHECK_INSTANCE_CAST((obj),GST_TYPE_NV_MEMORY_ALLOCATOR,GstEGV4l2MemoryAllocator))

static gpointer
gst_nv_memory_map (GstMemory * mem, gsize maxsize, GstMapFlags flags)
{
  GstEGV4l2Memory *nvmm_mem = (GstEGV4l2Memory *) mem;
  if (nvmm_mem == NULL) {
    GST_ERROR("%s: NULL GstEGV4l2Memory\n", __func__);
    goto error;
  }

  return (gpointer)(nvmm_mem->nvcam_buf->processed_surface
      ? nvmm_mem->nvcam_buf->processed_surface : nvmm_mem->nvcam_buf->surface);

error:
  return NULL;
}

static void
gst_nv_memory_unmap (GstMemory * mem)
{
  /* Nothing needs to be done */
}

static GstMemory *
gst_nv_memory_share (GstMemory * mem, gssize offset, gssize size)
{
  g_assert_not_reached ();
  return NULL;
}

/* In this function, plugin will allocate interlaced or progressive buffers
 * depending upon the interlaced_flag.
 * */
static GstMemory *
gst_eg_memory_allocator_alloc (GstAllocator * allocator,
    gsize size, GstAllocationParams * params)
{
  gint ret = 0;
  std::string cuda_error;
  GstEGV4l2Memory *mem = NULL;
  GstEgV4l2CameraSrcBuffer *nvbuf = NULL;
  GstMemoryFlags flags = GST_MEMORY_FLAG_NO_SHARE;

  GST_DEBUG ("%s:\n", __func__);

  GstEGV4l2MemoryAllocator *nvmm_allocator = GST_NVMEMORY_ALLOCATOR (allocator);
  GstEgV4l2CameraSrc *self = (GstEgV4l2CameraSrc*) nvmm_allocator->owner;
  if (self == NULL) {
    GST_ERROR_OBJECT(allocator, "NULL NvV4l2CameraSrc");
    return NULL;
  }

  mem = g_slice_new0 (GstEGV4l2Memory);
  nvbuf = g_slice_new0 (GstEgV4l2CameraSrcBuffer);

  NvBufSurfaceAllocateParams param = {{0}};
  param.params.width = self->width;
  param.params.height = self->height;
  param.params.layout = NVBUF_LAYOUT_PITCH;
  param.params.memType = NVBUF_MEM_DEFAULT;
  param.params.gpuId = 0;
  param.params.colorFormat = self->surface_format;

  if (self->interlaced_flag)
  {
    GST_ERROR("interlaced stream not supported \n");
    goto error;
  }

  ret = NvBufSurfaceAllocate (&nvbuf->surface, 1,  &param);

  if (ret != 0) {
    GST_ERROR ("%s: NvBufSurfaceAllocate Failed \n", __func__);
    goto error;
  }

  if (nvbuf->surface->surfaceList[0].pitch != self->fmt->fmt.pix.bytesperline ||
      nvbuf->surface->surfaceList[0].dataSize < self->fmt->fmt.pix.sizeimage) {
    GST_ERROR_OBJECT(self, "NVMM pitch/size does not match negotiated V4L2 buffer");
    goto error;
  }
  GST_INFO_OBJECT(self, "capture surface fd=%" G_GUINT64_FORMAT " format=%u pitch=%u size=%u",
      nvbuf->surface->surfaceList[0].bufferDesc,
      nvbuf->surface->surfaceList[0].colorFormat,
      nvbuf->surface->surfaceList[0].pitch,
      nvbuf->surface->surfaceList[0].dataSize);

  nvbuf->surface->numFilled = 1;
  if (self->preview || self->byte_swap) {
    param.params.colorFormat = self->preview ? NVBUF_COLOR_FORMAT_RGBA : NVBUF_COLOR_FORMAT_GRAY16_LE;
    if (NvBufSurfaceAllocate(&nvbuf->processed_surface, 1, &param)) {
      GST_ERROR_OBJECT(self, "Cannot allocate CUDA output surface");
      goto error;
    }
    nvbuf->processed_surface->numFilled = 1;
    nvbuf->cuda_frame = eg_cuda_frame_create(self->cuda, nvbuf->surface,
                                            nvbuf->processed_surface, cuda_error);
    if (!nvbuf->cuda_frame) {
      GST_ERROR_OBJECT(self, "%s", cuda_error.c_str());
      goto error;
    }
  }

  nvbuf->surface->numFilled = 1;

  gst_memory_init (GST_MEMORY_CAST (mem), flags, allocator, NULL,
      sizeof(NvBufSurface), 0 /* Alignment */,
      0, sizeof(NvBufSurface));

  nvbuf->dmabuf_fd = nvbuf->surface->surfaceList[0].bufferDesc;

  mem->nvcam_buf = nvbuf;
  mem->nvcam_buf->dmabuf_fd = nvbuf->dmabuf_fd;

  /* Prepare empty buffers to queue to v4l2 camera device */
  mem->nvcam_buf->buffer = (struct v4l2_buffer *) g_malloc (sizeof (struct v4l2_buffer));
  if (mem->nvcam_buf->buffer == NULL)
    goto error;

  memset(mem->nvcam_buf->buffer, 0, sizeof (struct v4l2_buffer));
  mem->nvcam_buf->buffer->index = self->index;
  mem->nvcam_buf->buffer->type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
  mem->nvcam_buf->buffer->memory = V4L2_MEMORY_DMABUF;
  mem->nvcam_buf->buffer->m.fd = nvbuf->dmabuf_fd;

  self->index++;

  return GST_MEMORY_CAST (mem);

error:
  eg_cuda_frame_destroy(nvbuf->cuda_frame);
  if (nvbuf->processed_surface) NvBufSurfaceDestroy(nvbuf->processed_surface);
  if (nvbuf->surface) NvBufSurfaceDestroy(nvbuf->surface);
  GST_DEBUG ("%s: FAILED\n", __func__);
  g_slice_free (GstEgV4l2CameraSrcBuffer, nvbuf);
  g_slice_free (GstEGV4l2Memory, mem);
  return NULL;
}

/* In this function, plugin will deallocate interlaced or progressive buffers.
 * This function is called when buffer pool is set to inactive and all buffers
 * are released.
 * */
static void
gst_eg_memory_allocator_free (GstAllocator * allocator, GstMemory * mem)
{
  gint ret = 0;

  GST_DEBUG ("%s:\n", __func__);

  GstEGV4l2Memory *nv_mem = (GstEGV4l2Memory *) mem;
  if (nv_mem == NULL)
    return;

  GstEgV4l2CameraSrcBuffer *nvbuf = nv_mem->nvcam_buf;
  if (nvbuf == NULL) {
    GST_DEBUG ("%s: NULL Buffer \n", __func__);
    g_slice_free (GstEGV4l2Memory, nv_mem);
    return;
  }

  eg_cuda_frame_destroy(nvbuf->cuda_frame);
  if (nvbuf->processed_surface) NvBufSurfaceDestroy(nvbuf->processed_surface);
  ret = NvBufSurfaceDestroy (nvbuf->surface);
  if (ret != 0)
    GST_ERROR ("%s: NvBufSurfaceDestroy Failed \n", __func__);

  g_free (nv_mem->nvcam_buf->buffer);
  nv_mem->nvcam_buf->buffer = NULL;
  g_slice_free (GstEgV4l2CameraSrcBuffer, nvbuf);
  g_slice_free (GstEGV4l2Memory, nv_mem);
}

static void
gst_eg_memory_allocator_class_init (GstEGV4l2MemoryAllocatorClass * klass)
{
  GstAllocatorClass *allocator_class;
  allocator_class = (GstAllocatorClass *) klass;

  allocator_class->alloc = gst_eg_memory_allocator_alloc;
  allocator_class->free = gst_eg_memory_allocator_free;
}

static void
gst_eg_memory_allocator_init (GstEGV4l2MemoryAllocator * allocator)
{
  GstAllocator *alloc = GST_ALLOCATOR_CAST (allocator);

  alloc->mem_type = GST_NVV4L2_MEMORY_TYPE;
  alloc->mem_map = gst_nv_memory_map;
  alloc->mem_unmap = gst_nv_memory_unmap;
  alloc->mem_share = gst_nv_memory_share;

  /* default copy & is_span */
  GST_OBJECT_FLAG_SET (allocator, GST_ALLOCATOR_FLAG_CUSTOM_ALLOC);
}

static GstFlowReturn gst_egv4l2camera_buffer_pool_acquire_buffer (
    GstBufferPool *bpool, GstBuffer **buffer,
    GstBufferPoolAcquireParams *params)
{
  GstFlowReturn ret = GST_FLOW_OK;
  GstMemory *mem = NULL;
  GstEGV4l2Memory *nv_mem = NULL;
  struct v4l2_buffer tmp_v4l2_buf;
  gint r = 0, i = 0;

  GST_DEBUG_OBJECT (bpool, "acquire_buffer");

  g_return_val_if_fail (GST_IS_BUFFER_POOL (bpool), GST_FLOW_ERROR);

  GstEgV4l2CameraBufferPool *pool = GST_NVV4L2CAMERA_BUFFER_POOL (bpool);
  GstEgV4l2CameraBufferPoolPrivate *priv = pool->priv;
  if (!priv) {
    GST_ERROR_OBJECT(pool, "NULL GstEgV4l2CameraBufferPoolPrivate");
    return GST_FLOW_ERROR;
  }

  GstEGV4l2MemoryAllocator *nvmm_allocator = GST_NVMEMORY_ALLOCATOR (priv->allocator);
  if (!nvmm_allocator) {
    GST_ERROR_OBJECT(pool, "NULL GstEGV4l2MemoryAllocator");
    return GST_FLOW_ERROR;
  }

  GstEgV4l2CameraSrc *src = (GstEgV4l2CameraSrc*) nvmm_allocator->owner;
  if (!src) {
    GST_ERROR_OBJECT(pool, "NULL GstEgV4l2CameraSrc");
    return GST_FLOW_ERROR;
  }

  /* Acquire a reusable buffer wrapper before dequeuing the camera frame. */
  ret = GST_BUFFER_POOL_CLASS (bpool_parent_class)->acquire_buffer (bpool, buffer, params);
  if (ret != GST_FLOW_OK)
    return ret;

  mem = gst_buffer_peek_memory (*buffer, 0);
  if (!mem) {
    goto no_memblk;
  }

  /* Setting timeout value of select to 5, this can be configured as required */
  src->tv.tv_sec = DEQUE_TIMEOUT;
  src->tv.tv_usec = 0;
  FD_ZERO(&(src->read_set));
  FD_SET(pool->video_fd, &(src->read_set));

  /* select the ready descriptor */
  r = select(pool->video_fd + 1, &(src->read_set), NULL, NULL, &(src->tv));
  if (0 == r) {
    goto timeout_error;
  }

  if (-1 == r) {
    goto select_error;
  }

  nv_mem = (GstEGV4l2Memory *) mem;
  memset(nv_mem->nvcam_buf->buffer, 0, sizeof (struct v4l2_buffer));
  nv_mem->nvcam_buf->buffer->type        = V4L2_BUF_TYPE_VIDEO_CAPTURE;
  nv_mem->nvcam_buf->buffer->memory      = V4L2_MEMORY_DMABUF;
  if (-1 == ioctl(pool->video_fd, VIDIOC_DQBUF, nv_mem->nvcam_buf->buffer))
    goto dqbuf_error;

  /* Search the buffer which driver returned */
  if (nv_mem->nvcam_buf->buffer->m.fd != nv_mem->nvcam_buf->dmabuf_fd) {
    memcpy (&tmp_v4l2_buf, nv_mem->nvcam_buf->buffer, sizeof (struct v4l2_buffer));
    for (i = 0; i < MAX_SEARCH_COUNT; i ++) {
      if (tmp_v4l2_buf.m.fd == nv_mem->nvcam_buf->dmabuf_fd)
        break;

      GST_WARNING_OBJECT(pool, "Search camera output buffer. Driver out fd: %d camera buffer fd: %d", tmp_v4l2_buf.m.fd, nv_mem->nvcam_buf->dmabuf_fd);

      GST_BUFFER_POOL_CLASS (bpool_parent_class)->release_buffer (bpool, *buffer);
      ret = GST_BUFFER_POOL_CLASS (bpool_parent_class)->acquire_buffer (bpool, buffer, params);
      if (ret != GST_FLOW_OK)
        return ret;

      mem = gst_buffer_peek_memory (*buffer, 0);
      if (!mem) {
        goto no_memblk;
      }
      nv_mem = (GstEGV4l2Memory *) mem;
    }
    if (i == MAX_SEARCH_COUNT) {
      goto no_buffer;
    }
    memcpy (nv_mem->nvcam_buf->buffer, &tmp_v4l2_buf, sizeof (struct v4l2_buffer));
  }

  if (nv_mem->nvcam_buf->cuda_frame) {
    std::string cuda_error;
    if (!eg_cuda_gray(nv_mem->nvcam_buf->cuda_frame, src->width, src->height,
                      src->capture_bits, src->byte_swap, src->preview, cuda_error, src->normalize)) {
      GST_ELEMENT_ERROR(src, RESOURCE, FAILED, ("CUDA grayscale processing failed"),
                        ("%s", cuda_error.c_str()));
      gst_buffer_unref(*buffer);
      *buffer = NULL;
      return GST_FLOW_ERROR;
    }
  }

  GST_BUFFER_OFFSET(*buffer) = nv_mem->nvcam_buf->buffer->sequence;
  if (nv_mem->nvcam_buf->buffer->flags & V4L2_BUF_FLAG_ERROR)
    GST_BUFFER_FLAG_SET(*buffer, GST_BUFFER_FLAG_CORRUPTED);
  else
    GST_BUFFER_FLAG_UNSET(*buffer, GST_BUFFER_FLAG_CORRUPTED);

  return ret;

no_memblk:
  {
    GST_ERROR_OBJECT(pool, "No memory block");
    ret = GST_FLOW_ERROR;
    return ret;
  }
dqbuf_error:
  {
    GST_ERROR_OBJECT(pool, "VIDIOC_DQBUF failed");
    src->stop_requested = TRUE;
    gst_buffer_unref(*buffer);
    *buffer = NULL;
    return GST_FLOW_ERROR;
  }
timeout_error:
  {
    GST_ERROR_OBJECT(pool, "Timeout Error");
    src->stop_requested = TRUE;
    gst_buffer_unref(*buffer);
    *buffer = NULL;
    return GST_FLOW_ERROR;
  }
select_error:
  {
    perror ("select");
    GST_ERROR_OBJECT(pool, "Select Error");
    src->stop_requested = TRUE;
    gst_buffer_unref(*buffer);
    *buffer = NULL;
    return GST_FLOW_ERROR;
  }
no_buffer:
  {
    GST_ERROR_OBJECT(pool, "Not found buffer which driver returned");
    ret = GST_FLOW_ERROR;
    return ret;
  }
}

static GstFlowReturn
gst_egv4l2camera_buffer_pool_alloc_buffer (GstBufferPool *bpool,
    GstBuffer **buffer, GstBufferPoolAcquireParams *params)
{
  GstBuffer *buf = NULL;
  GstMemory *mem = NULL;

  GST_DEBUG_OBJECT (bpool, "alloc_buffer");

  g_return_val_if_fail (GST_IS_BUFFER_POOL (bpool), GST_FLOW_ERROR);

  GstEgV4l2CameraBufferPool *pool = GST_NVV4L2CAMERA_BUFFER_POOL (bpool);
  GstEgV4l2CameraBufferPoolPrivate *priv = pool->priv;
  if (priv == NULL) {
    *buffer = NULL;
    return GST_FLOW_ERROR;
  }

  if (!g_strcmp0(priv->allocator->mem_type, GST_NVV4L2_MEMORY_TYPE)) {
    mem = gst_eg_memory_allocator_alloc (priv->allocator, priv->size,
                                   &priv->params);
    g_return_val_if_fail (mem, GST_FLOW_ERROR);

    buf = gst_buffer_new ();
    g_return_val_if_fail (buf, GST_FLOW_ERROR);

    gst_buffer_append_memory (buf, mem);
  } else {
    buf = gst_buffer_new_allocate (priv->allocator, priv->size,
                                   &priv->params);

    g_return_val_if_fail (buf, GST_FLOW_ERROR);
  }

  *buffer = buf;
  return GST_FLOW_OK;
}

static void
gst_egv4l2camera_buffer_pool_finalize (GObject *object)
{
  GstEgV4l2CameraBufferPool *pool = GST_NVV4L2CAMERA_BUFFER_POOL (object);
  GstEgV4l2CameraBufferPoolPrivate *priv = pool->priv;

  if (priv) {
    if (priv->caps)
      gst_caps_unref (priv->caps);
    priv->caps = NULL;

    if (priv->allocator)
      gst_object_unref (priv->allocator);
    priv->allocator = NULL;
  }

  G_OBJECT_CLASS (bpool_parent_class)->finalize (object);
}

static void
gst_egv4l2camera_buffer_pool_free_buffer (GstBufferPool *bpool,
        GstBuffer *buffer)
{
  GstEgV4l2CameraBufferPool *pool = GST_NVV4L2CAMERA_BUFFER_POOL (bpool);
  GST_DEBUG_OBJECT (pool, "free_buffer");
  GST_BUFFER_POOL_CLASS (bpool_parent_class)->free_buffer (bpool, buffer);
}

static void gst_egv4l2camera_buffer_pool_init (GstEgV4l2CameraBufferPool *pool)
{
  GstEgV4l2CameraBufferPool *self = GST_NVV4L2CAMERA_BUFFER_POOL (pool);
  pool->priv = (GstEgV4l2CameraBufferPoolPrivate *) gst_egv4l2camera_buffer_pool_get_instance_private (self);

  memset (pool->priv, 0, sizeof(GstEgV4l2CameraBufferPoolPrivate));

  pool->priv->allocator = (GstAllocator *) g_object_new (
            gst_eg_memory_allocator_get_type (), NULL);

  gst_allocation_params_init (&pool->priv->params);

  GST_DEBUG_OBJECT (pool, "created");
}

GstBufferPool * gst_egv4l2camera_buffer_pool_new (void)
{
  GstEgV4l2CameraBufferPool *pool;
  pool = (GstEgV4l2CameraBufferPool *) g_object_new (GST_TYPE_NVV4L2CAMERA_BUFFER_POOL, NULL);
  if (!pool)
    GST_DEBUG ("NULL GstEgV4l2CameraBufferPool\n");

  return GST_BUFFER_POOL (pool);
}

static void gst_egv4l2camera_buffer_pool_release_buffer (GstBufferPool *bpool,
        GstBuffer *buffer)
{
  GstMemory *mem = NULL;
  GstEGV4l2Memory *nv_mem = NULL;

  g_return_if_fail (GST_IS_BUFFER_POOL (bpool));

  GST_DEBUG_OBJECT (bpool, "release_buffer");

  GstEgV4l2CameraBufferPool *pool = GST_NVV4L2CAMERA_BUFFER_POOL (bpool);

  mem = gst_buffer_peek_memory (buffer, 0);

  nv_mem = (GstEGV4l2Memory *) mem;
  if (nv_mem && (nv_mem->nvcam_buf->buffer != NULL)) {
    if(-1 == ioctl(pool->video_fd, VIDIOC_QBUF, nv_mem->nvcam_buf->buffer))
      GST_ERROR_OBJECT(pool, "VIDIOC_QBUF failed :%s", g_strerror (errno));
  }

  GST_BUFFER_POOL_CLASS (bpool_parent_class)->release_buffer (bpool, buffer);
}

static gboolean
gst_egv4l2camera_buffer_pool_set_config (GstBufferPool *bpool, GstStructure *config)
{
  GstCaps *caps = NULL;
  GstAllocator *allocator = NULL;
  GstAllocationParams params = { (GstMemoryFlags)0, 0, 0, 0, };
  GstVideoInfo info = {0};
  guint size = 0;

  g_return_val_if_fail (GST_IS_BUFFER_POOL (bpool), FALSE);
  g_return_val_if_fail (config != NULL, FALSE);

  GstEgV4l2CameraBufferPool *pool = GST_NVV4L2CAMERA_BUFFER_POOL (bpool);
  GstEgV4l2CameraBufferPoolPrivate *priv = pool->priv;
  if (priv == NULL) {
    GST_ERROR("No pool initialized\n");
    return FALSE;
  }

  GST_OBJECT_LOCK (pool);

  if (!gst_buffer_pool_config_get_params (config, &caps, &size, NULL, NULL))
    goto wrong_config;

  if (caps == NULL)
    goto no_caps;

  if (!gst_video_info_from_caps (&info, caps))
    goto wrong_video_caps;

  priv->info = info;
  priv->size = size;

  if (!priv->size)
    priv->size = info.size;

  if (priv->caps)
    gst_caps_unref (priv->caps);
  priv->caps = gst_caps_ref (caps);

  if (!gst_buffer_pool_config_get_allocator (config, &allocator, &params))
    goto wrong_config;

  if (allocator) {
    // Update user provided allocator
    if (priv->allocator)
      gst_object_unref (priv->allocator);
    if ((priv->allocator = allocator))
      gst_object_ref (allocator);

    priv->params = params;
  }

  if (!allocator) {
    // Allocator is not set, use private allocator.
    gst_buffer_pool_config_set_allocator (config, priv->allocator,
                                          &priv->params);
  }

  GST_OBJECT_UNLOCK (pool);

  return GST_BUFFER_POOL_CLASS (bpool_parent_class)->set_config (bpool, config);

  /* ERRORS */
wrong_config:
  {
    GST_OBJECT_UNLOCK (pool);
    GST_WARNING_OBJECT (pool, "invalid config");
    return FALSE;
  }
no_caps:
  {
    GST_OBJECT_UNLOCK (pool);
    GST_WARNING_OBJECT (pool, "no caps in config");
    return FALSE;
  }
wrong_video_caps:
  {
    GST_OBJECT_UNLOCK (pool);
    GST_WARNING_OBJECT (pool,
        "failed getting video info from caps %" GST_PTR_FORMAT, caps);
    return FALSE;
  }
}

static gboolean
gst_egv4l2camera_buffer_pool_start (GstBufferPool *bpool)
{
  GstEgV4l2CameraBufferPool *pool = GST_NVV4L2CAMERA_BUFFER_POOL (bpool);

  GST_DEBUG_OBJECT (pool, "start");

  return GST_BUFFER_POOL_CLASS (bpool_parent_class)->start (bpool);
}

static gboolean gst_egv4l2camera_buffer_pool_stop (GstBufferPool *bpool)
{
  GstEgV4l2CameraBufferPool *pool = GST_NVV4L2CAMERA_BUFFER_POOL (bpool);

  GST_DEBUG_OBJECT (pool, "stop");

  return GST_BUFFER_POOL_CLASS (bpool_parent_class)->stop (bpool);
}

static void
gst_egv4l2camera_buffer_pool_class_init (GstEgV4l2CameraBufferPoolClass *klass)
{

  GObjectClass *gobject_class = (GObjectClass *) klass;
  GstBufferPoolClass *gstbufferpool_class = (GstBufferPoolClass *) klass;

  gobject_class->finalize = gst_egv4l2camera_buffer_pool_finalize;
  gstbufferpool_class->start = gst_egv4l2camera_buffer_pool_start;
  gstbufferpool_class->stop = gst_egv4l2camera_buffer_pool_stop;
  gstbufferpool_class->set_config = gst_egv4l2camera_buffer_pool_set_config;
  gstbufferpool_class->alloc_buffer = gst_egv4l2camera_buffer_pool_alloc_buffer;
  gstbufferpool_class->free_buffer = gst_egv4l2camera_buffer_pool_free_buffer;
  gstbufferpool_class->acquire_buffer = gst_egv4l2camera_buffer_pool_acquire_buffer;
  gstbufferpool_class->release_buffer = gst_egv4l2camera_buffer_pool_release_buffer;

  GST_DEBUG_CATEGORY_INIT (gst_eg_v4l2_camera_src_debug, "nvv4l2camerapool", 0,
        "nvv4l2camera buffer pool object");
}

static void gst_eg_v4l2_camera_src_set_property (GObject * object, guint prop_id,
    const GValue * value, GParamSpec * pspec);
static void gst_eg_v4l2_camera_src_get_property (GObject * object, guint prop_id,
    GValue * value, GParamSpec * pspec);
static void gst_eg_v4l2_camera_src_finalize (GObject *object);

/* GObject vmethod implementations */

static GstCaps * gst_eg_v4l2_camera_fixate (GstBaseSrc *src, GstCaps *caps)
{
  GstStructure *structure = NULL;
  gboolean ret = TRUE;

  g_return_val_if_fail (GST_IS_CAPS (caps), NULL);

  caps = gst_caps_make_writable (caps);

  structure = gst_caps_get_structure (caps, 0);
  if (structure == NULL) {
    GST_ERROR_OBJECT (src, "Invalid caps structure");
    return NULL;
  }

  /* Default fixated to progressive mode */
  ret = gst_structure_fixate_field_nearest_int (structure, "width", 1920);
  ret = gst_structure_fixate_field_nearest_int (structure, "height", 1080);
  // Use the capture interval reported by V4L2; zero means unknown/variable.
  // Explicit caller caps remain fixed. This does not change the camera rate.
  auto *self = GST_NVV4L2CAMERASRC(src);
  struct v4l2_streamparm streamparm = {};
  streamparm.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
  gint fps_n = 0, fps_d = 1;
  if (self->video_fd >= 0 && ioctl(self->video_fd, VIDIOC_G_PARM, &streamparm) == 0) {
    const auto &interval = streamparm.parm.capture.timeperframe;
    if (interval.numerator && interval.denominator &&
        interval.numerator <= G_MAXINT && interval.denominator <= G_MAXINT) {
      fps_n = interval.denominator;
      fps_d = interval.numerator;
    }
  }
  ret = gst_structure_fixate_field_nearest_fraction(structure, "framerate", fps_n, fps_d);

  if (!ret)
    GST_WARNING_OBJECT (src, "Unable to fixate caps structure");

  caps = GST_BASE_SRC_CLASS (gst_eg_v4l2_camera_src_parent_class)->fixate (src, caps);

  return caps;
}

static GstCaps *gst_eg_v4l2_camera_get_caps(GstBaseSrc *base, GstCaps *filter)
{
  auto *src = GST_NVV4L2CAMERASRC(base);
  GstCaps *caps = gst_caps_make_writable(gst_pad_get_pad_template_caps(GST_BASE_SRC_PAD(base)));
  if (src->preview || g_ascii_strcasecmp(src->capture_format, "auto"))
    gst_structure_set(gst_caps_get_structure(caps, 0), "format", G_TYPE_STRING,
                      src->preview ? "RGBA" : "GRAY16_LE", NULL);
  if (filter) {
    GstCaps *intersection = gst_caps_intersect_full(filter, caps, GST_CAPS_INTERSECT_FIRST);
    gst_caps_unref(caps);
    caps = intersection;
  }
  return caps;
}

static gboolean gst_eg_v4l2_camera_set_caps (GstBaseSrc *base, GstCaps *caps)
{
  GstVideoInfo info = {0};
  std::string cuda_error;
  GstCaps *old = NULL;
  GstStructure *config = NULL;
  GstEGV4l2MemoryAllocator *allocator = NULL;
  GstStructure *structure = NULL;
  enum v4l2_buf_type buf_type;

  GstEgV4l2CameraSrc *src = GST_NVV4L2CAMERASRC (base);

  GST_DEBUG_OBJECT (src, "Received caps %" GST_PTR_FORMAT, caps);

  if (!gst_video_info_from_caps (&info, caps))
  {
    GST_ERROR_OBJECT (src, "Invalid caps");
    return FALSE;
  }

  structure = gst_caps_get_structure (caps, 0);
  if (structure == NULL) {
    GST_ERROR_OBJECT (src, "Invalid caps structure");
    return FALSE;
  }

  if (gst_structure_has_field (structure, "interlace-mode")) {
    /* interlace-mode field present with incaps */
    if (!g_strcmp0 (gst_structure_get_string (structure, "interlace-mode"), "interlaced"))
    {
      src->interlaced_flag = TRUE;
      GST_DEBUG_OBJECT (src, "interlace-mode set to interlaced mode\n");
    }
    else
    {
      src->interlaced_flag = FALSE;
      GST_DEBUG_OBJECT (src, "interlace-mode set to progressive mode\n");
    }
  } else {
    GST_DEBUG_OBJECT (src, "interlace-mode field not present in sink caps, setting to progressive mode\n");
    src->interlaced_flag = FALSE;
  }

  src->pixel_format = GST_VIDEO_INFO_FORMAT(&info);
  src->byte_swap = FALSE;
  src->capture_bits = 16;
  if (src->preview || src->pixel_format == GST_VIDEO_FORMAT_GRAY16_LE) {
    if (src->preview && src->pixel_format != GST_VIDEO_FORMAT_RGBA) {
      GST_ERROR_OBJECT(src, "Grayscale preview requires RGBA output caps");
      return FALSE;
    }
    if (!g_ascii_strcasecmp(src->capture_format, "Y14"))
      src->capture_fourcc = V4L2_PIX_FMT_Y14;
    else if (!g_ascii_strcasecmp(src->capture_format, "Y16_BE"))
      src->capture_fourcc = V4L2_PIX_FMT_Y16_BE;
    else if (!g_ascii_strcasecmp(src->capture_format, "Y16"))
      src->capture_fourcc = V4L2_PIX_FMT_Y16;
    else if (!g_ascii_strcasecmp(src->capture_format, "auto")) {
      guint32 current = src->fmt->fmt.pix.pixelformat;
      if (current == V4L2_PIX_FMT_Y14 || current == V4L2_PIX_FMT_Y16_BE || current == V4L2_PIX_FMT_Y16)
        src->capture_fourcc = current;
      else {
        GST_ERROR_OBJECT(src, "Select the camera's grayscale format before capture");
        return FALSE;
      }
    } else {
      GST_ERROR_OBJECT(src, "Unsupported capture-format: %s", src->capture_format);
      return FALSE;
    }
    src->surface_format = NVBUF_COLOR_FORMAT_GRAY16_LE;
    src->bytes_per_pixel = 2;
    src->capture_bits = src->capture_fourcc == V4L2_PIX_FMT_Y14 ? 14 : 16;
    src->byte_swap = src->capture_fourcc == V4L2_PIX_FMT_Y16_BE;
  } else {
    if (g_ascii_strcasecmp(src->capture_format, "auto")) {
      GST_ERROR_OBJECT(src, "capture-format overrides require grayscale or preview caps");
      return FALSE;
    }
    switch (src->pixel_format) {
      case GST_VIDEO_FORMAT_YUY2:
        src->capture_fourcc = V4L2_PIX_FMT_YUYV;
        src->surface_format = NVBUF_COLOR_FORMAT_YUYV;
        src->bytes_per_pixel = 2;
        break;
      case GST_VIDEO_FORMAT_UYVY:
        src->capture_fourcc = V4L2_PIX_FMT_UYVY;
        src->surface_format = NVBUF_COLOR_FORMAT_UYVY;
        src->bytes_per_pixel = 2;
        break;
      case GST_VIDEO_FORMAT_RGBA:
        src->capture_fourcc = V4L2_PIX_FMT_RGBA32; /* AB24: R,G,B,A bytes */
        src->surface_format = NVBUF_COLOR_FORMAT_RGBA;
        src->bytes_per_pixel = 4;
        break;
      case GST_VIDEO_FORMAT_BGRA:
      case GST_VIDEO_FORMAT_BGRx:
        src->capture_fourcc = V4L2_PIX_FMT_ABGR32; /* AR24: B,G,R,A bytes */
        src->surface_format = src->pixel_format == GST_VIDEO_FORMAT_BGRA
            ? NVBUF_COLOR_FORMAT_BGRA : NVBUF_COLOR_FORMAT_BGRx;
        src->bytes_per_pixel = 4;
        break;
      default:
        GST_ERROR_OBJECT(src, "Unsupported pixel format");
        return FALSE;
    }
  }

  src->width  = info.width;
  /* height is divided by 2 for setting the format with VIDIOC_S_FMT,
   * as driver expects height of top and bottom field
   * */
  if (src->interlaced_flag)
    src->height = info.height / 2;
  else
    src->height = info.height;
  src->fps_n  = info.fps_n;
  src->fps_d  = info.fps_d;

  if ((old = src->outcaps) != caps)
  {
    if (caps)
      src->outcaps = gst_caps_copy (caps);
    else
      src->outcaps = NULL;
    if (old)
      gst_caps_unref (old);
  }

   /* VIDIOC_S_FMT IOCTL on v4l2 device */
   src->fmt->fmt.pix.width = src->width;
   src->fmt->fmt.pix.height = src->height;
   src->fmt->fmt.pix.pixelformat = src->capture_fourcc;
   src->fmt->fmt.pix.bytesperline = src->width * src->bytes_per_pixel;
   if (-1 == ioctl(src->video_fd, VIDIOC_S_FMT, src->fmt)) {
    GST_ERROR_OBJECT(src, "VIDIOC_S_FMT on %s device", src->videodev);
    goto fmt_error;
   }

  if (src->fmt->fmt.pix.width != (guint)src->width ||
      src->fmt->fmt.pix.height != (guint)src->height ||
      src->fmt->fmt.pix.pixelformat != src->capture_fourcc) {
    GST_ERROR_OBJECT(src, "Driver changed the requested size or pixel format");
    goto fmt_error;
  }
  GST_INFO_OBJECT(src, "V4L2 format=%c%c%c%c stride=%u size=%u",
      src->fmt->fmt.pix.pixelformat & 255, (src->fmt->fmt.pix.pixelformat >> 8) & 255,
      (src->fmt->fmt.pix.pixelformat >> 16) & 255, (src->fmt->fmt.pix.pixelformat >> 24) & 255,
      src->fmt->fmt.pix.bytesperline, src->fmt->fmt.pix.sizeimage);

  if ((src->preview || src->byte_swap) && !src->cuda) {
    src->cuda = eg_cuda_create(cuda_error);
    if (!src->cuda) {
      GST_ERROR_OBJECT(src, "%s", cuda_error.c_str());
      goto fmt_error;
    }
  }

  if (src->preview)
    g_print("egv4l2camerasrc: pixel processing: %s on GPU to RGBA; captured values unchanged\n",
        src->normalize ? "per-frame min/max normalization" : "fixed-range grayscale scaling");
  else if (src->byte_swap)
    g_print("egv4l2camerasrc: pixel processing: GPU byte-order conversion to little-endian; numeric values unchanged\n");
  else
    g_print("egv4l2camerasrc: pixel processing: none in the capture source\n");

  /* Requesting buffers for camera */
  src->req = (struct v4l2_requestbuffers *) g_malloc (sizeof (struct v4l2_requestbuffers));
  if (src->req == NULL) {
    goto fmt_error;
  }

  memset(src->req, 0, sizeof(struct v4l2_requestbuffers));
  src->req->count = src->cap_buf;
  src->req->type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
  src->req->memory = V4L2_MEMORY_DMABUF;

  if (-1 == ioctl(src->video_fd, VIDIOC_REQBUFS, src->req))
    goto req_error;


  if (src->pool) {
    gst_object_unref (src->pool);
    src->pool = NULL;
  }
  src->pool = gst_egv4l2camera_buffer_pool_new ();
  if (!src->pool)
    goto buffer_pool_new_failed;

  ((GstEgV4l2CameraBufferPool *)src->pool)->video_fd = src->video_fd;

  allocator = (GstEGV4l2MemoryAllocator *) g_object_new (gst_eg_memory_allocator_get_type (), NULL);
  if (!allocator) {
    GST_ERROR_OBJECT(src->pool, "Failed to create GstEGV4l2MemoryAllocator");
    if (gst_buffer_pool_is_active (src->pool)) {
      gst_buffer_pool_set_active (src->pool, FALSE);
    }
    gst_object_unref (src->pool);
    src->pool = NULL;
    g_free (src->fmt);
    src->fmt = NULL;
    g_free (src->req);
    src->req = NULL;
    return FALSE;
  }

  allocator->owner = src;
  config = gst_buffer_pool_get_config (src->pool);
  gst_buffer_pool_config_set_allocator (config, GST_ALLOCATOR (allocator), NULL);

  gst_buffer_pool_config_set_params (config, src->outcaps, sizeof(NvBufSurface), src->cap_buf, src->cap_buf);

  gst_buffer_pool_set_config (src->pool, config);

  if (allocator)
    gst_object_unref (allocator);

  gst_buffer_pool_set_active (src->pool, TRUE);

  buf_type = V4L2_BUF_TYPE_VIDEO_CAPTURE;

  /* VIDIOC_STREAMON IOCTL on v4l2 camera device */
  if(-1 == ioctl(src->video_fd, VIDIOC_STREAMON, &buf_type))
  {
    goto streamon_error;
  }

  /* clear the read descriptor set */
  FD_ZERO(&(src->read_set));

  /* set src->video_fd in read_set */
  FD_SET(src->video_fd, &(src->read_set));

  /* Setting timeout value of select to 5, this can be configured as required */
  src->tv = (struct timeval){ 0 };
  src->tv.tv_sec = DEQUE_TIMEOUT;

  return TRUE;

fmt_error:
  {
    g_free (src->fmt);
    src->fmt= NULL;
    return FALSE;
  }
req_error:
  {
    GST_ERROR_OBJECT(src, "VIDIOC_REQBUFS on %s device", src->videodev);
    goto cleanup;
  }
buffer_pool_new_failed:
  {
    GST_ERROR_OBJECT(src, "Buffer pool creation on %s device", src->videodev);
    goto cleanup;
  }
streamon_error:
  {
    GST_ERROR_OBJECT(src, "VIDIOC_STREAMON on %s device", src->videodev);
    if (gst_buffer_pool_is_active (src->pool)) {
      gst_buffer_pool_set_active (src->pool, FALSE);
    }
    gst_object_unref (src->pool);
    src->pool = NULL;
  }
cleanup:
  {
    g_free (src->fmt);
    src->fmt = NULL;
    g_free (src->req);
    src->req = NULL;
    return FALSE;
  }
}

static gboolean gst_eg_v4l2_camera_start (GstBaseSrc * src_base)
{
  /* TODO, move this opening code to gst_eg_v4l2_camera_change_state */
  GstEgV4l2CameraSrc *src = (GstEgV4l2CameraSrc *) src_base;
  src->index = 0;
  src->stop_requested = FALSE;
  src->unlock_requested = FALSE;

  /* open the device */
  src->video_fd = open (src->videodev, O_RDWR /* | O_NONBLOCK */ );

  if (src->video_fd < 0)
    goto open_error;
  else
  {
    /* VIDIOC_QUERYCAP IOCTL on v4l2 device */
    src->caps = (struct v4l2_capability *) g_malloc (sizeof (struct v4l2_capability));
    if (src->caps == NULL)
    {
      GST_ERROR_OBJECT(src, "Caps allocation failed");
      return FALSE;
    }
    memset(src->caps, 0, sizeof(struct v4l2_capability));
    if (-1 == ioctl(src->video_fd, VIDIOC_QUERYCAP, src->caps))
      goto caps_error;

    if(!(src->caps->capabilities & V4L2_CAP_VIDEO_CAPTURE))
    {
      goto caps_error;
    }
    if (!(src->caps->capabilities & V4L2_CAP_STREAMING))
    {
      goto caps_error;
    }

    /* VIDIOC_G_FMT IOCTL on v4l2 device */
    src->fmt = (struct v4l2_format *) g_malloc (sizeof (struct v4l2_format));
    if (src->fmt == NULL) {
      GST_ERROR_OBJECT(src, "Format allocation failed");
      g_free (src->caps);
      src->caps = NULL;
      return FALSE;
    }
    memset(src->fmt, 0, sizeof(struct v4l2_format));

    src->fmt->type = V4L2_BUF_TYPE_VIDEO_CAPTURE;

    if (-1 == ioctl(src->video_fd, VIDIOC_G_FMT, src->fmt))
    {
      goto gfmt_error;
    }

    /* NOTE: src->fmt->fmt.pix.field should provide enum v4l2_field value
             for top & bottom field order for captured buffer which later
             can be used to set BUFFER_FLAG_TFF on output gst buffers. */
    src->field_order = src->fmt->fmt.pix.field;

    return TRUE;
  }
open_error:
  {
    GST_ERROR_OBJECT(src, "Opening %s device", src->videodev);
    return FALSE;
  }
caps_error:
  {
    GST_ERROR_OBJECT(src, "VIDIOC_QUERYCAP on %s device", src->videodev);
    g_free (src->caps);
    src->caps = NULL;
    return FALSE;
  }
gfmt_error:
  {
    GST_ERROR_OBJECT(src, "VIDIOC_G_FMT on %s device", src->videodev);
    g_free (src->caps);
    src->caps = NULL;
    g_free (src->fmt);
    src->fmt = NULL;
    return FALSE;
  }
}

static gboolean gst_eg_v4l2_camera_unlock (GstBaseSrc *src)
{
  GstEgV4l2CameraSrc *self = (GstEgV4l2CameraSrc *) src;
  self->unlock_requested = TRUE;
  if (self->pool)
    gst_buffer_pool_set_flushing (self->pool, TRUE);

  return TRUE;
}

static gboolean gst_eg_v4l2_camera_unlock_stop (GstBaseSrc *src)
{
  GstEgV4l2CameraSrc *self = (GstEgV4l2CameraSrc *) src;
  if (self->pool)
    gst_buffer_pool_set_flushing (self->pool, FALSE);

  self->unlock_requested = FALSE;

  return TRUE;
}

static gboolean gst_eg_v4l2_camera_stop (GstBaseSrc * src_base)
{
  GstEgV4l2CameraSrc *src = (GstEgV4l2CameraSrc *) src_base;

  enum v4l2_buf_type buf_type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
  src->stop_requested = TRUE;

  GST_DEBUG_OBJECT (src_base, "%s:\n", __func__);

  if(-1 == ioctl(src->video_fd, VIDIOC_STREAMOFF, &buf_type))
    g_print ("VIDIOC_STREAMOFF Ioctl Failed \n");

  if (src->pool) {
    if (gst_buffer_pool_is_active (src->pool))
      gst_buffer_pool_set_active (src->pool, false);

    gst_object_unref (src->pool);
    src->pool = NULL;
  }
  if (src->video_fd >= 0 ) {
    close (src->video_fd);
    src->video_fd = -1;
  }

  if (src->req) {
    g_free (src->req);
    src->req = NULL;
  }
  if (src->caps) {
    g_free (src->caps);
    src->caps = NULL;
  }
  if (src->fmt) {
    g_free (src->fmt);
    src->fmt = NULL;
  }
  if (src->outcaps) {
    gst_caps_unref (src->outcaps);
    src->outcaps = NULL;
  }
  eg_cuda_release(src->cuda);
  src->cuda = NULL;
  return TRUE;
}

static GstFlowReturn
gst_eg_v4l2_camera_create (GstBaseSrc * src_base,
    guint64 offset, guint size, GstBuffer ** buf)
{
  GstEgV4l2CameraSrc *self = GST_NVV4L2CAMERASRC (src_base);
  GstFlowReturn ret = GST_FLOW_OK;

  if (self->stop_requested || self->unlock_requested)
    return GST_FLOW_EOS;

  ret = gst_buffer_pool_acquire_buffer (self->pool, buf, NULL);
  if (ret != GST_FLOW_OK)
    return ret;

  /* NOTE: Capture driver need to provide top/bottom field order based
           on frame number.
           Accordingly, BUFFER_FLAG_TFF needs to be set on gst buffer */
  if (self->field_order == V4L2_FIELD_SEQ_TB)
    GST_BUFFER_FLAG_SET (*buf, GST_VIDEO_BUFFER_FLAG_TFF);

  return ret;
}

/* initialize the egv4l2camerasrc's class */
static void
gst_eg_v4l2_camera_src_class_init (GstEgV4l2CameraSrcClass * klass)
{
  GObjectClass *gobject_class;
  GstElementClass *gstelement_class;
  GstBaseSrcClass *base_src_class;

  gobject_class    = (GObjectClass *) klass;
  gstelement_class = (GstElementClass *) klass;
  base_src_class   = (GstBaseSrcClass*) klass;

  gobject_class->set_property = gst_eg_v4l2_camera_src_set_property;
  gobject_class->get_property = gst_eg_v4l2_camera_src_get_property;
  gobject_class->finalize     = gst_eg_v4l2_camera_src_finalize;

  base_src_class->get_caps    = GST_DEBUG_FUNCPTR (gst_eg_v4l2_camera_get_caps);
  base_src_class->set_caps    = GST_DEBUG_FUNCPTR (gst_eg_v4l2_camera_set_caps);
  base_src_class->fixate      = GST_DEBUG_FUNCPTR (gst_eg_v4l2_camera_fixate);
  base_src_class->start       = GST_DEBUG_FUNCPTR (gst_eg_v4l2_camera_start);
  base_src_class->stop        = GST_DEBUG_FUNCPTR (gst_eg_v4l2_camera_stop);
  base_src_class->create      = GST_DEBUG_FUNCPTR (gst_eg_v4l2_camera_create);
  base_src_class->unlock      = GST_DEBUG_FUNCPTR (gst_eg_v4l2_camera_unlock);
  base_src_class->unlock_stop = GST_DEBUG_FUNCPTR (gst_eg_v4l2_camera_unlock_stop);

  g_object_class_install_property (gobject_class, PROP_DEVICE,
      g_param_spec_string ("device", "Device", "Device location, default = /dev/video0",
          DEFAULT_PROP_DEVICE, (GParamFlags) (G_PARAM_READWRITE | G_PARAM_STATIC_STRINGS)));

  g_object_class_install_property (gobject_class, PROP_CAPTURE_BUFFERS,
      g_param_spec_uint ("cap-buffers", "capture-buffers",
          "number of capture buffers",
          2, MAX_BUFFERS, MIN_BUFFERS, (GParamFlags) G_PARAM_READWRITE));

  g_object_class_install_property(gobject_class, PROP_CAPTURE_FORMAT,
      g_param_spec_string("capture-format", "Grayscale capture format",
          "auto, Y16, Y14 (right-aligned), or Y16_BE; NVMM grayscale output is little endian",
          "auto", (GParamFlags)(G_PARAM_READWRITE | GST_PARAM_MUTABLE_READY)));
  g_object_class_install_property(gobject_class, PROP_PREVIEW,
      g_param_spec_boolean("preview", "GPU grayscale preview",
          "Convert grayscale capture to full-range RGBA on CUDA; raw capture remains unchanged",
          FALSE, (GParamFlags)(G_PARAM_READWRITE | GST_PARAM_MUTABLE_READY)));
  g_object_class_install_property(gobject_class, PROP_NORMALIZE,
      g_param_spec_boolean("normalize", "Adaptive grayscale preview",
          "Normalize each preview frame using GPU min/max; false uses the full declared range. Raw output is unchanged.",
          FALSE, (GParamFlags)(G_PARAM_READWRITE | G_PARAM_STATIC_STRINGS)));
  g_object_class_install_property(gobject_class, PROP_CAPTURE_BITS,
      g_param_spec_uint("capture-bits", "Capture precision", "Valid grayscale bits before preview",
                       8, 16, 16, (GParamFlags)G_PARAM_READABLE));

  gst_element_class_set_details_simple(gstelement_class,
    "NvV4l2CameraSrc",
    "Video/Capture",
    "Nvidia V4l2 Camera Source",
    "Ashwin Deshpande <ashwind@nvidia.com>");

  gst_element_class_add_pad_template (gstelement_class,
      gst_static_pad_template_get (&src_factory));
}

/* initialize the new element
 * instantiate pads and add them to element
 * set pad calback functions
 * initialize instance structure
 */
static void
gst_eg_v4l2_camera_src_init (GstEgV4l2CameraSrc * src)
{
  src->cap_buf = MIN_BUFFERS;
  src->capture_format = g_strdup("auto");
  src->preview = FALSE;
  src->normalize = FALSE;
  src->byte_swap = FALSE;
  src->capture_bits = 16;
  src->cuda = NULL;
  src->width = 1920;
  src->height = 1080;
  src->fps_n = 30;
  src->fps_d = 1;
  src->field_order = V4L2_FIELD_NONE;
  src->stop_requested = FALSE;
  src->unlock_requested = FALSE;
  src->outcaps = NULL;
  src->caps = NULL;
  src->fmt = NULL;
  src->req = NULL;
  src->field_order = 0;
  src->interlaced_flag = 0;
  src->videodev = g_strdup (DEFAULT_PROP_DEVICE);
  src->video_fd = -1;

  gst_base_src_set_live (GST_BASE_SRC (src), TRUE);
  gst_base_src_set_format (GST_BASE_SRC (src), GST_FORMAT_TIME);
  gst_base_src_set_do_timestamp (GST_BASE_SRC (src), TRUE);
}

static void
gst_eg_v4l2_camera_src_finalize (GObject *object)
{
  GstEgV4l2CameraSrc *src= GST_NVV4L2CAMERASRC (object);
  GST_DEBUG_OBJECT (src, "finalize");

  if(src->videodev) {
    g_free (src->videodev);
    src->videodev = NULL;
  }

  g_free(src->capture_format);
  src->capture_format = NULL;
  eg_cuda_release(src->cuda);
  src->cuda = NULL;
  G_OBJECT_CLASS (parent_class)->finalize (object);
}

static void
gst_eg_v4l2_camera_src_set_property (GObject * object, guint prop_id,
    const GValue * value, GParamSpec * pspec)
{
  GstEgV4l2CameraSrc *src = GST_NVV4L2CAMERASRC (object);

  switch (prop_id)
  {
    case PROP_DEVICE: {
      g_free (src->videodev);
      src->videodev = g_value_dup_string (value);
    }
      break;

    case PROP_CAPTURE_BUFFERS: {
      src->cap_buf = g_value_get_uint (value);
    }
      break;

    case PROP_CAPTURE_FORMAT:
      if (GST_STATE(src) > GST_STATE_READY) { GST_WARNING_OBJECT(src, "Stop capture before changing capture-format"); break; }
      g_free(src->capture_format);
      src->capture_format = g_value_dup_string(value);
      if (!src->capture_format) src->capture_format = g_strdup("auto");
      break;
    case PROP_NORMALIZE:
      if (GST_STATE(src) > GST_STATE_READY) { GST_WARNING_OBJECT(src, "Stop capture before changing normalization"); break; }
      src->normalize = g_value_get_boolean(value);
      break;
    case PROP_PREVIEW:
      if (GST_STATE(src) > GST_STATE_READY) { GST_WARNING_OBJECT(src, "Stop capture before changing preview"); break; }
      src->preview = g_value_get_boolean(value);
      break;
    default:
      G_OBJECT_WARN_INVALID_PROPERTY_ID (object, prop_id, pspec);
      break;
  }
}

static void
gst_eg_v4l2_camera_src_get_property (GObject * object, guint prop_id,
    GValue * value, GParamSpec * pspec)
{
  GstEgV4l2CameraSrc *src = GST_NVV4L2CAMERASRC (object);

  switch (prop_id)
  {
    case PROP_DEVICE:
      g_value_set_string (value, src->videodev);
      break;

    case PROP_CAPTURE_BUFFERS:
      g_value_set_uint (value, src->cap_buf);
      break;

    case PROP_CAPTURE_FORMAT: g_value_set_string(value, src->capture_format); break;
    case PROP_NORMALIZE: g_value_set_boolean(value, src->normalize); break;
    case PROP_PREVIEW: g_value_set_boolean(value, src->preview); break;
    case PROP_CAPTURE_BITS: g_value_set_uint(value, src->capture_bits); break;
    default:
      G_OBJECT_WARN_INVALID_PROPERTY_ID (object, prop_id, pspec);
      break;
  }
}

/* GstElement vmethod implementations */

/* entry point to initialize the plug-in
 * initialize the plug-in itself
 * register the element factories and other features
 */
static gboolean
egv4l2camerasrc_init (GstPlugin * egv4l2camerasrc)
{
  /* debug category for fltering log messages
   *
   * exchange the string 'Template egv4l2camerasrc' with your description
   */
  GST_DEBUG_CATEGORY_INIT (gst_eg_v4l2_camera_src_debug, "egv4l2camerasrc",
    0, "egv4l2camerasrc");

  return gst_element_register (egv4l2camerasrc, "egv4l2camerasrc", GST_RANK_PRIMARY,
    GST_TYPE_NVV4L2CAMERASRC);
}

/* PACKAGE: this is usually set by autotools depending on some _INIT macro
 * in configure.ac and then written into and defined in config.h, but we can
 * just set it ourselves here in case someone doesn't use autotools to
 * compile this code. GST_PLUGIN_DEFINE needs PACKAGE to be defined.
 */
#ifndef PACKAGE
#define PACKAGE "egv4l2camerasrc"
#endif

/* gstreamer looks for this structure to register egv4l2camerasrc
 *
 * exchange the string 'Template egv4l2camerasrc' with your egv4l2camerasrc description
 */
GST_PLUGIN_DEFINE (
  GST_VERSION_MAJOR,
  GST_VERSION_MINOR,
  egv4l2camerasrc,
  "Nvidia v4l2 Source Component",
  egv4l2camerasrc_init,
  "1.14.5",
  "Proprietary",
  "NvV4l2CameraSrc",
  "http://nvidia.com/"
)
