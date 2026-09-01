# SPDX-License-Identifier: GPL-2.0-only
# SPDX-FileCopyrightText: Copyright (c) 2023-2025, NVIDIA CORPORATION & AFFILIATES.  All rights reserved.

DTC_FLAGS += -@
DTC_CPP_FLAGS += -DEG_CSI_22PIN

# Propagate PRISTINE_KERNEL (exported by l4t_environment.sh from
# vendors.<v>.pristine_kernel) to the device tree preprocessor, the same way
# EG_CSI_22PIN is passed above.
#
# The overlays that react to it are shared by both Connect Tech build variants
# and must NOT hardcode `#define PRISTINE_KERNEL`: on the pristine variant the
# vendor's precompiled kernel cannot negotiate Y16, so those modes are dropped
# and the remaining ones renumbered; on the source-built variant Y16 works and
# the modes must stay as they are. Same .dts, two results, decided by the build.
ifdef PRISTINE_KERNEL
DTC_CPP_FLAGS += -DPRISTINE_KERNEL
endif

old-dtb := $(dtb-y)
old-dtbo := $(dtbo-y)
dtb-y :=
dtbo-y :=
makefile-path := t23x/nv-public/overlay

dtbo-y += tegra-optee.dtbo
dtbo-y += tegra234-android.dtbo
# Build Kdump DTBOs for Android
ifeq ($(CONFIG_TEGRA_SYSTEM_TYPE_ACK),y)
dtbo-y += tegra234-android-kdump.dtbo
dtbo-y += tegra234-android-crash-kernel.dtbo
dtbo-y += tegra234-android-dummy-overlay.dtbo
endif
dtbo-y += tegra234-audio-overlay.dtbo
dtbo-y += tegra234-carveouts.dtbo
dtbo-y += tegra234-dcb-p3767-0000-hdmi.dtbo
dtbo-y += tegra234-p3737-0000+p3701-0000-pcie-no-tra.dtbo
dtbo-y += tegra234-p3737-0000+p3701-0000-as-p3701-0004.dtbo
dtbo-y += tegra234-p3737-0000+p3701-0000-as-p3767-0000.dtbo
dtbo-y += tegra234-p3737-0000+p3701-0000-as-p3767-0001.dtbo
dtbo-y += tegra234-p3737-0000+p3701-0000-as-p3767-0003.dtbo
dtbo-y += tegra234-p3737-0000+p3701-0000-as-p3767-0004.dtbo
dtbo-y += tegra234-p3737-0000+p3701-0000-dynamic.dtbo
dtbo-y += tegra234-p3768-0000+p3767-0000-dynamic.dtbo
dtbo-y += tegra234-p3737-0000+p3701-0000-audio-adafruit-uda1334a.dtbo
dtbo-y += tegra234-p3737-0000+p3701-0000-audio-adafruit-sph0645lm4h.dtbo
dtbo-y += tegra234-p3737-0000+p3701-0000-audio-fe-pi.dtbo
dtbo-y += tegra234-p3737-0000+p3701-0000-audio-respeaker-4-mic-array.dtbo
dtbo-y += tegra234-p3737-0000+p3701-0000-audio-respeaker-4-mic-lin-array.dtbo
dtbo-y += tegra234-p3737-0000+p3701-0000-csi.dtbo
dtbo-y += tegra234-p3737-0000+p3701-0000-hdr40.dtbo
dtbo-y += tegra234-p3737-0000+p3701-0000-m2ke.dtbo
dtbo-y += tegra234-p3767-0000+p3509-a02-audio-adafruit-sph0645lm4h.dtbo
dtbo-y += tegra234-p3767-0000+p3509-a02-audio-adafruit-uda1334a.dtbo
dtbo-y += tegra234-p3767-0000+p3509-a02-audio-fe-pi.dtbo
dtbo-y += tegra234-p3767-0000+p3509-a02-audio-respeaker-4-mic-array.dtbo
dtbo-y += tegra234-p3767-0000+p3509-a02-audio-respeaker-4-mic-lin-array.dtbo
dtbo-y += tegra234-p3767-0000+p3509-a02-csi.dtbo
dtbo-y += tegra234-p3767-0000+p3509-a02-hdr40.dtbo
dtbo-y += tegra234-p3767-0000+p3509-a02-m2ke.dtbo
dtbo-y += tegra234-p3767-0000+p3768-0000-csi.dtbo
dtbo-y += tegra234-p3971-0000+p3701-0008-camera-dual-imx274-overlay.dtbo
dtbo-y += tegra234-p3971-0000+p3701-0008-camera-p3762-a00-overlay.dtbo
dtbo-y += tegra234-p3737-camera-dual-imx274-overlay.dtbo
dtbo-y += tegra234-p3737-camera-e3331-overlay.dtbo
dtbo-y += tegra234-p3737-camera-e3333-overlay.dtbo
dtbo-y += tegra234-p3737-camera-imx185-overlay.dtbo
dtbo-y += tegra234-p3737-camera-p3762-a00-overlay.dtbo
dtbo-y += tegra234-p3740-camera-p3783-a00-overlay.dtbo
dtbo-y += tegra234-p3767-camera-p3768-imx219-dual.dtbo
dtbo-y += tegra234-p3767-camera-p3768-imx477-dual.dtbo
dtbo-y += tegra234-p3767-camera-p3768-imx477-dual-4lane.dtbo
dtbo-y += tegra234-p3767-camera-p3768-imx477-imx219.dtbo
dtbo-y += tegra234-p3737-camera-eCAM130A-overlay.dtbo
dtbo-y += tegra234-p3737-camera-dual-hawk-ar0234-e3653-overlay.dtbo
dtbo-y += tegra234-p3737-camera-imx390-addr-0x21-overlay.dtbo
dtbo-y += tegra234-p3737-camera-imx390-overlay.dtbo
dtbo-y += tegra234-p3737-camera-p3762-a00-1Hawk-overlay.dtbo
dtbo-y += tegra234-p3737-camera-p3762-a00-2Hawk-overlay.dtbo
dtbo-y += tegra234-p3737-camera-p3762-a00-3Hawk-3Owl-overlay.dtbo
dtbo-y += tegra234-p3737-camera-p3762-a00-4Hawk-overlay.dtbo
dtbo-y += tegra234-p3737-camera-p3762-a00-4Owl-overlay.dtbo
dtbo-y += tegra234-p3767-camera-p3768-imx219-C.dtbo
dtbo-y += tegra234-p3767-camera-p3768-imx219-A.dtbo
dtbo-y += tegra234-p3767-camera-p3768-imx219-imx477.dtbo
dtbo-y += tegra234-p3740-0002+p3701-0008-hdr20.dtbo
dtbo-y += tegra234-p3740-0002+p3701-0008-m2ke.dtbo
dtbo-y += tegra234-p3740-0002+p3701-0008-m2kb.dtbo
dtbo-y += tegra234-p3767-camera-p3768-imx477-C.dtbo
dtbo-y += tegra234-p3767-camera-p3768-imx477-A.dtbo
dtbo-y += tegra234-p3740-0002-p3701-0008-csi.dtbo

dtbo-y += tegra234-p3767-camera-p3768-eg-cams-dione.dtbo
dtbo-y += tegra234-p3767-camera-p3768-eg-cams-disable-imx219.dtbo
dtbo-y += tegra234-p3767-camera-p3768-eg-cam1-ec-1-lane.dtbo
dtbo-y += tegra234-p3767-camera-p3768-eg-cam0-ec-1-lane.dtbo
dtbo-y += tegra234-p3767-camera-p3768-eg-cam1-ec-2-lanes.dtbo
dtbo-y += tegra234-p3767-camera-p3768-eg-cam0-ec-2-lanes.dtbo
dtbo-y += tegra234-p3767-camera-p3768-eg-cam0-imx219.dtbo
dtbo-y += tegra234-p3767-camera-p3768-eg-cam1-imx219.dtbo
dtbo-y += tegra234-p3767-camera-p3768-eg-cam0-imx477.dtbo
dtbo-y += tegra234-p3767-camera-p3768-eg-cam0-imx477-4-lanes.dtbo
dtbo-y += tegra234-p3767-camera-p3768-eg-cam1-imx477.dtbo
ifndef PRISTINE_KERNEL
# ilumos/microlynx need Y16/Y16_BE/Y14 negotiation support in the shared
# nvidia-oot camera framework, which can't be patched into a PRISTINE_KERNEL
# vendor's precompiled tegra-camera.ko (see drivers/media/i2c/Makefile).
dtbo-y += tegra234-p3767-camera-p3768-eg-cam0-ilumos.dtbo
dtbo-y += tegra234-p3767-camera-p3768-eg-cam1-ilumos.dtbo
dtbo-y += tegra234-p3767-camera-p3768-eg-cam0-microlynx.dtbo
dtbo-y += tegra234-p3767-camera-p3768-eg-cam1-microlynx.dtbo
endif
dtbo-y += tegra234-p3767-camera-dsboard-ornxs-eg-cams-dione.dtbo
dtbo-y += tegra234-p3767-camera-eg-cams-dione-cam0-lane-swap.dtbo

dtbo-y += tegra234-p3737-camera-eg-cams-dione.dtbo
dtbo-y += tegra234-p3737-camera-eg-cams-disable-imx219.dtbo
dtbo-y += tegra234-p3737-camera-eg-cam0-ec-1-lane.dtbo
dtbo-y += tegra234-p3737-camera-eg-cam0-ec-2-lanes.dtbo
dtbo-y += tegra234-p3737-camera-eg-cam0-ec-imx219.dtbo
dtbo-y += tegra234-p3737-camera-eg-cam1-ec-1-lane.dtbo
dtbo-y += tegra234-p3737-camera-eg-cam1-ec-2-lanes.dtbo
dtbo-y += tegra234-p3737-camera-eg-cam1-ec-imx219.dtbo
dtbo-y += tegra234-p3737-camera-eg-cam2-ec-1-lane.dtbo
dtbo-y += tegra234-p3737-camera-eg-cam2-ec-2-lanes.dtbo
dtbo-y += tegra234-p3737-camera-eg-cam2-ec-imx219.dtbo
dtbo-y += tegra234-p3737-camera-eg-cam3-ec-1-lane.dtbo
dtbo-y += tegra234-p3737-camera-eg-cam3-ec-2-lanes.dtbo
dtbo-y += tegra234-p3737-camera-eg-cam3-ec-imx219.dtbo
dtbo-y += tegra234-p3737-camera-eg-cam0-microlynx.dtbo
dtbo-y += tegra234-p3737-camera-eg-cam1-microlynx.dtbo
dtbo-y += tegra234-p3737-camera-eg-cam2-microlynx.dtbo
dtbo-y += tegra234-p3737-camera-eg-cam3-microlynx.dtbo
dtbo-y += tegra234-p3737-camera-eg-cam0-ilumos.dtbo
dtbo-y += tegra234-p3737-camera-eg-cam1-ilumos.dtbo
dtbo-y += tegra234-p3737-camera-eg-cam2-ilumos.dtbo
dtbo-y += tegra234-p3737-camera-eg-cam3-ilumos.dtbo


ifneq ($(dtb-y),)
dtb-y := $(addprefix $(makefile-path)/,$(dtb-y))
endif
ifneq ($(dtbo-y),)
dtbo-y := $(addprefix $(makefile-path)/,$(dtbo-y))
endif

dtb-y += $(old-dtb)
dtbo-y += $(old-dtbo)
