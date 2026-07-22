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
