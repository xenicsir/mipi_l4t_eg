# SPDX-FileCopyrightText: Copyright (c) 2023-2025, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: GPL-2.0-only
#
# This program is free software; you can redistribute it and/or modify it
# under the terms and conditions of the GNU General Public License,
# version 2, as published by the Free Software Foundation.
#
# This program is distributed in the hope it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for
# more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.

subdir-ccflags-y += -Werror
ifneq ($(NV_BUILD_SYSTEM_TYPE),embedded-linux)
obj-m += max9295.o
obj-m += max9296.o
ifndef CONFIG_TEGRA_SYSTEM_TYPE_ACK
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
obj-m += ilumos.o
microlynx-objs := microlynx_core.o gencp-over-i2c/libunio.o gencp-over-i2c/libunio_extras.o gencp-over-i2c/nb_timer.o gencp-over-i2c/gencp_common.o gencp-over-i2c/gencp_client.o
obj-m += microlynx.o

endif

obj-m += pca9570.o
obj-m += virtual_i2c_mux.o
endif
endif
