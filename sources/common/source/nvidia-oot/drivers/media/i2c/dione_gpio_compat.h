/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef DIONE_GPIO_COMPAT_H
#define DIONE_GPIO_COMPAT_H

/* camera_common.h changed to GPIO descriptors in L4T 39.2.2 without a Linux
 * version change. The version-specific Kbuild selects that supplier API.
 * Callers include the Linux GPIO APIs and camera_common types first.
 */
static inline bool dione_reset_present(struct camera_common_power_rail *pw)
{
#ifdef EG_CAMERA_GPIO_DESCRIPTORS
	return pw->reset_gpiod != NULL;
#else
	return pw->reset_gpio != 0;
#endif
}

static inline void dione_reset_set(struct camera_common_power_rail *pw, int value)
{
#ifdef EG_CAMERA_GPIO_DESCRIPTORS
	/* reva already selects physical polarity; do not apply DT active-low again. */
	if (gpiod_cansleep(pw->reset_gpiod))
		gpiod_set_raw_value_cansleep(pw->reset_gpiod, value);
	else
		gpiod_set_raw_value(pw->reset_gpiod, value);
#else
#if LINUX_VERSION_CODE >= KERNEL_VERSION(6, 0, 0)
	bool can_sleep = gpiod_cansleep(gpio_to_desc(pw->reset_gpio));
#else
	bool can_sleep = gpio_cansleep(pw->reset_gpio);
#endif
	if (can_sleep)
		gpio_set_value_cansleep(pw->reset_gpio, value);
	else
		gpio_set_value(pw->reset_gpio, value);
#endif
}

static inline int dione_reset_get(struct device *dev,
	struct camera_common_power_rail *pw, struct camera_common_pdata *pdata)
{
#ifdef EG_CAMERA_GPIO_DESCRIPTORS
	int err;

	(void)pdata;
	/* Preserve the pre-existing direction/level, as gpio_request() did. */
	pw->reset_gpiod = gpiod_get_optional(dev, "reset", GPIOD_ASIS);
	if (IS_ERR(pw->reset_gpiod)) {
		err = PTR_ERR(pw->reset_gpiod);
		pw->reset_gpiod = NULL;
		return err;
	}
	return 0;
#else
	(void)dev;
	pw->reset_gpio = pdata->reset_gpio;
	return pw->reset_gpio ? gpio_request(pw->reset_gpio, "cam_reset_gpio") : 0;
#endif
}

static inline void dione_reset_put(struct camera_common_power_rail *pw)
{
	if (!dione_reset_present(pw))
		return;
#ifdef EG_CAMERA_GPIO_DESCRIPTORS
	gpiod_put(pw->reset_gpiod);
	pw->reset_gpiod = NULL;
#else
	gpio_free(pw->reset_gpio);
#endif
}

static inline void dione_reset_parse(struct device_node *np,
	struct camera_common_pdata *pdata)
{
#ifdef EG_CAMERA_GPIO_DESCRIPTORS
	/* Acquired by power_get, including optional-pin and deferred-probe handling. */
	(void)np;
	(void)pdata;
#else
	int gpio = of_get_named_gpio(np, "reset-gpios", 0);

	pdata->reset_gpio = gpio < 0 ? 0 : gpio;
#endif
}
#endif
