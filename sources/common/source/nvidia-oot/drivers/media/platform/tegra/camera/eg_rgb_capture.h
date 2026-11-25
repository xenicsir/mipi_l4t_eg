/* SPDX-License-Identifier: GPL-2.0 */
#ifndef EG_RGB_CAPTURE_H
#define EG_RGB_CAPTURE_H

#include <linux/of.h>
#include <linux/string.h>
#include <linux/videodev2.h>

static inline bool eg_camera_fixed_capture(const struct device_node *node)
{
	return node && (of_device_is_compatible(node, "exosens,dioneir") ||
		of_device_is_compatible(node, "xenics,dioneir") ||
		of_device_is_compatible(node, "exosens,eg-ec-mipi") ||
		of_device_is_compatible(node, "xenics,eg-ec-mipi"));
}

/* Native geometry and a fixed pixel format are separate constraints. */
static inline bool eg_camera_native_resolution(const struct device_node *node)
{
	return eg_camera_fixed_capture(node) || (node &&
		(of_device_is_compatible(node, "exosens,ilumos") ||
		 of_device_is_compatible(node, "exosens,microlynx") ||
		 of_device_is_compatible(node, "exosens,titan")));
}

/* Select the camera integration's RGB memory contract, not its CSI data type.
 * A zero result leaves the platform's format selection unrestricted.
 */
static inline u32 eg_rgb_capture_fourcc(const struct device_node *node)
{
	const char *format;

	if (!node)
		return 0;
	if (!of_property_read_string(node, "exosens,rgb-capture-format", &format)) {
		if (!strcmp(format, "AR24"))
			return V4L2_PIX_FMT_ABGR32;
		if (!strcmp(format, "AB24"))
			return V4L2_PIX_FMT_RGBA32;
	}
	if (eg_camera_fixed_capture(node))
		return V4L2_PIX_FMT_ABGR32;
	return 0;
}

#endif
