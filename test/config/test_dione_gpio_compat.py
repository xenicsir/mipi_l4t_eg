#!/usr/bin/env python3
"""Exercise Dione reset allocation, raw polarity and both supplier GPIO APIs."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
SHIM=r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>
#define KERNEL_VERSION(a,b,c) (((a)<<16)|((b)<<8)|(c))
#define GPIOD_ASIS 0
#define IS_ERR(p) ((intptr_t)(p)<0)
#define PTR_ERR(p) ((int)(intptr_t)(p))
struct device {};
struct device_node {};
struct gpio_desc {bool active_low;};
static struct gpio_desc pin={true};
static int can_sleep,level,api,requests,puts,request_error,dt_gpio=7;
static bool absent;
#ifdef EG_CAMERA_GPIO_DESCRIPTORS
struct camera_common_power_rail {struct gpio_desc *reset_gpiod;};
struct camera_common_pdata {struct gpio_desc *reset_gpiod;};
#else
struct camera_common_power_rail {int reset_gpio;};
struct camera_common_pdata {int reset_gpio;};
#endif
static int of_get_named_gpio(struct device_node *np,const char *name,int index)
{assert(!strcmp(name,"reset-gpios") && index==0);return dt_gpio;}
static int gpio_request(int gpio,const char *name) {assert(gpio==7);requests++;return request_error;}
static void gpio_free(int gpio) {assert(gpio==7);puts++;}
static struct gpio_desc *gpio_to_desc(int gpio) {assert(gpio==7);return &pin;}
static int gpio_cansleep(int gpio) {assert(gpio==7);return can_sleep;}
static int gpiod_cansleep(struct gpio_desc *p) {assert(p==&pin);return can_sleep;}
static struct gpio_desc *gpiod_get_optional(struct device *dev,const char *name,int flags) {
 assert(!strcmp(name,"reset") && flags==GPIOD_ASIS);requests++;
 return request_error?(struct gpio_desc *)(intptr_t)request_error:(absent?NULL:&pin);
}
static void gpiod_put(struct gpio_desc *p) {assert(p==&pin);puts++;}
static void gpio_set_value(int gpio,int v) {assert(gpio==7);api=1;level=v;}
static void gpio_set_value_cansleep(int gpio,int v) {assert(gpio==7);api=2;level=v;}
static void gpiod_set_raw_value(struct gpio_desc *p,int v) {assert(p==&pin);api=3;level=v;}
static void gpiod_set_raw_value_cansleep(struct gpio_desc *p,int v) {assert(p==&pin);api=4;level=v;}
/* A mistaken logical setter would invert the tested active-low descriptor. */
static void gpiod_set_value(struct gpio_desc *p,int v) {level=p->active_low?!v:v;}
static void gpiod_set_value_cansleep(struct gpio_desc *p,int v) {level=p->active_low?!v:v;}
'''
CASES=r'''
int main(void) {
 struct device dev;struct device_node np;
 struct camera_common_power_rail pw={0};struct camera_common_pdata pdata={0};
 dione_reset_parse(&np,&pdata);level=99;
 assert(!dione_reset_get(&dev,&pw,&pdata));assert(requests==1 && level==99);
 assert(dione_reset_present(&pw));
 for(can_sleep=0;can_sleep<2;can_sleep++)for(int value=0;value<2;value++) {
  dione_reset_set(&pw,value);assert(level==value);
#ifdef EG_CAMERA_GPIO_DESCRIPTORS
  assert(api==3+can_sleep);
#else
  assert(api==1+can_sleep);
#endif
 }
 dione_reset_put(&pw);assert(puts==1);
#ifdef EG_CAMERA_GPIO_DESCRIPTORS
 assert(!dione_reset_present(&pw));dione_reset_put(&pw);assert(puts==1);
 absent=true;assert(!dione_reset_get(&dev,&pw,&pdata));assert(!dione_reset_present(&pw));
 request_error=-517;absent=false;assert(dione_reset_get(&dev,&pw,&pdata)==-517);
 assert(!dione_reset_present(&pw));dione_reset_put(&pw);assert(puts==1);
#else
 dt_gpio=-2;dione_reset_parse(&np,&pdata);assert(!pdata.reset_gpio);
 assert(!dione_reset_get(&dev,&pw,&pdata));assert(!dione_reset_present(&pw));
 dione_reset_put(&pw);assert(puts==1);
 dt_gpio=7;dione_reset_parse(&np,&pdata);request_error=-16;
 assert(dione_reset_get(&dev,&pw,&pdata)==-16);
#endif
 return 0;
}
'''

class GPIOCompatibilityTests(unittest.TestCase):
    def test_legacy_and_descriptor_apis_preserve_physical_reset_levels(self):
        header=ROOT/'sources/common/source/nvidia-oot/drivers/media/i2c/dione_gpio_compat.h'
        for version,descriptor in [('KERNEL_VERSION(4,9,0)',False),('KERNEL_VERSION(6,8,0)',False),('KERNEL_VERSION(6,8,0)',True)]:
            with self.subTest(version=version,descriptor=descriptor),tempfile.TemporaryDirectory() as d:
                p=Path(d);(p/'test.c').write_text(SHIM+'\n#include "'+str(header)+'"\n'+CASES)
                command=['cc','-std=gnu11','-Wall','-Wextra','-Werror','-Wno-unused-function','-Wno-unused-parameter','-fsanitize=undefined','-fno-sanitize-recover=all','-DLINUX_VERSION_CODE='+version]
                if descriptor:command+=['-DEG_CAMERA_GPIO_DESCRIPTORS']
                subprocess.run(command+[str(p/'test.c'),'-o',str(p/'test')],check=True)
                subprocess.run([str(p/'test')],check=True)

if __name__=='__main__':unittest.main()
