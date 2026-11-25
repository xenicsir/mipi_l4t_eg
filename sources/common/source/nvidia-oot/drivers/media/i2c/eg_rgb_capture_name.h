/* SPDX-License-Identifier: GPL-2.0 */
#ifndef EG_RGB_CAPTURE_NAME_H
#define EG_RGB_CAPTURE_NAME_H

#include <linux/version.h>
#if LINUX_VERSION_CODE >= KERNEL_VERSION(5, 10, 0) && !defined(PRISTINE_KERNEL)
#include "../platform/tegra/camera/eg_rgb_capture.h"
#endif

static inline const char *eg_rgb_capture_name(struct device *dev)
{
#if LINUX_VERSION_CODE >= KERNEL_VERSION(5, 10, 0) && !defined(PRISTINE_KERNEL)
	if (eg_rgb_capture_fourcc(dev->of_node) == V4L2_PIX_FMT_RGBA32)
		return "'AB24' (32-bit RGBA 8-8-8-8)";
#elif defined(EG_RGB888_AB24)
	/* Unmodified vendor kernels retain their native format table. */
	return "'AB24' (32-bit RGBA 8-8-8-8)";
#endif
	return "'AR24' (32-bit BGRA 8-8-8-8)";
}

#endif
