To build the environment from scratch :
======================================
<pre>
./l4t_prepare.sh $L4T_VERSION
./l4t_copy_sources.sh $L4T_VERSION
./l4t_build.sh $L4T_VERSION
</pre>

To generate a "light" image (3.5GB) for flashing :
=================================================
<pre>
./l4t_gen_delivery_image.sh $L4T_VERSION jetson-xavier-nx-devkit-emmc-dione
</pre>

To flash it to the board :
<pre>
tar xvf Linux_for_Tegra.tar.gz
cd Linux_for_Tegra
sudo ./bootloader/mksparse  -v --fillpattern=0 bootloader/system.img.raw bootloader/system.img
sudo NO_ROOTFS=1 NO_RECOVERY_IMG=1 ./flash.sh -r --no-systemimg jetson-xavier-nx-devkit-emmc-dione mmcblk0p1
</pre>

To generate a SD card image :
=============================
<pre>
cd Linux_for_Tegra/tools
./jetson-disk-image-creator.sh -o sd-blob.img -b jetson-xavier-nx-devkit
</pre>

To generate a debian package to install on an official nvidia distribution :
============================================================================
<pre>
./l4t_gen_delivery_package.sh $L4T_VERSION
</pre>

Auvidea X230D kit for Jetson AGX Orin :
=======================================
L4T_VERSION=35.3.1

## Building the l4t_eg environment
This section is for developers needing to rebuild the drivers. Skip the "Flashing with sdkmanager" section.

If you don't need to build the drivers and received a "jetson-l4t-$L4T_VERSION-eg-cams_$DRIVERVERSION_arm64.deb" package, go to the "Flashing with sdkmanager" section.

- flash the image before building the drivers :
<pre>
./l4t_prepare.sh $L4T_VERSION
./l4t_copy_sources.sh $L4T_VERSION auvidea_X230D
cd $L4T_VERSION/Linux_for_Tegra
sudo ./flash.sh jetson-agx-orin-devkit mmcblk0p1
</pre>

- build it :
<pre>
./l4t_build.sh $L4T_VERSION
</pre>

- generate the jetson-l4t-$L4T_VERSION-eg-cams_$DRIVERVERSION_arm64.deb package :
<pre>
./l4t_gen_delivery_package.sh $L4T_VERSION
</pre>

## Flashing with sdkmanager
Flash the Auvidea X230D kit following the instructions in the SW Setup Guide https://auvidea.eu/download/Software. Use the JetPack 5.1.1 version.

## Install the camera drivers on the board
- install the jetson-l4t-$L4T_VERSION-eg-cams_$DRIVERVERSION_arm64.deb package on the Jetson board. It was delivered or locally built previously :
<pre>
sudo dpkg -i jetson-l4t-$L4T_VERSION-eg-cams_$DRIVERVERSION_arm64.deb
</pre>
- edit the /boot/extlinux/extlinux.conf file, create a new entry and make it default  :
<pre>
DEFAULT eg-cams
[...]
LABEL eg-cams
      MENU LABEL eg-cams kernel
      LINUX /boot/eg/Image
      FDT /boot/eg/tegra234-p3701-0004-p3737-0000-eg-cams-auvidea.dtb
      INITRD /boot/initrd
      APPEND ${cbootargs} root=/dev/mmcblk0p1 rw rootwait rootfstype=ext4 mminit_loglevel=4 console=ttyTCU0,115200 console=ttyAMA0,115200 console=tty0 firmware_class.path=/etc/firmware fbcon=map:0 net.ifnames=0
[...]
</pre>
- reboot the Jetson board



