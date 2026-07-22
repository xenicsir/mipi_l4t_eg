# SPDX-License-Identifier: GPL-2.0-only
# Copyright (c) 2023-2024 NVIDIA CORPORATION & AFFILIATES. All rights reserved.

subdir-ccflags-y += -Werror

obj-m += max9295.o
obj-m += max9296.o
ifeq ($(findstring ack_src,$(NV_BUILD_KERNEL_OPTIONS)),)
obj-m += max96712.o

ifdef CONFIG_MEDIA_SUPPORT
obj-m += ar1335_common.o
obj-m += lt6911uxc.o
obj-m += nv_imx185.o
obj-m += nv_imx219.o
obj-m += nv_imx274.o
obj-m += nv_imx318.o
obj-m += nv_imx390.o
obj-m += nv_imx477.o
obj-m += nv_ov5693.o
obj-m += nv_ar0234.o
obj-m += nv_hawk_owl.o
obj-m += max929x.o
obj-m += dione_ir.o
dione_ir-y += dioneir.o tc358746_calculation.o
eg-ec-mipi-objs := eg_ec_mipi_src.o ecctrl_i2c_common.o
obj-m += eg-ec-mipi.o

# NVIDIA's own vi5_formats.h/camera_common.c report RGB888 CSI-2 as
# RGBA32 (AB24) only from L4T 35.4.1 on (see vi5_formats_mbus_fix.md in
# shared memory) -- but EG re-adds ABGR32 (AR24) alongside it on 35.4.1
# through 35.6.4 (JetPack 5.x, Ubuntu 20.04) because gst-plugins-good
# 1.16.3 there doesn't recognize the V4L2_PIX_FMT_RGBA32 fourcc at all
# (v4l2src can't produce RGBA caps, confirmed via GST_DEBUG=v4l2*:5 on
# real hardware) -- so those versions still default to AR24. This L4T
# version (JetPack 6.x+, Ubuntu 22.04+, GStreamer 1.20+) doesn't need that
# workaround: stays AB24-only, matching NVIDIA's own table. Tell
# dioneir.c/eg_ec_mipi_src.c's descriptive pixel_format sysfs strings to
# match, since LINUX_VERSION_CODE alone can't express this distinction.
ccflags-y += -DEG_RGB888_AB24
ifndef PRISTINE_KERNEL
# ilumos/microlynx need Y16/Y16_BE/Y14 negotiation support in the shared
# nvidia-oot camera framework (sensor_common.c, vi5_formats.h...), which
# can't be patched into a PRISTINE_KERNEL vendor's precompiled tegra-camera.ko.
obj-m += ilumos.o
microlynx-objs := microlynx_core.o gencp-over-i2c/libunio.o gencp-over-i2c/libunio_extras.o gencp-over-i2c/nb_timer.o gencp-over-i2c/gencp_common.o gencp-over-i2c/gencp_client.o
obj-m += microlynx.o
endif
ifdef PRISTINE_KERNEL
ccflags-y += -DPRISTINE_KERNEL
endif

endif

obj-m += pca9570.o
obj-m += virtual_i2c_mux.o
endif
