Jetson Nano 2GB Developer Kit :
===============================
L4T_VERSION=32.7.1, 32.7.4

## Preparing the L4T environment
This section is for developers needing to rebuild the drivers.

<pre>
./l4t_prepare.sh $L4T_VERSION nano
./l4t_copy_sources.sh $L4T_VERSION nano
</pre>

## Flashing the board
Flash the Nano devkit kit following instructions, for example for L4R R32.7.1 : https://developer.nvidia.com/embedded/jetpack-sdk-461
Or use the L4T flash script :
<pre>
cd $L4T_VERSION/Linux_for_Tegra_nano.src
sudo ./flash.sh jetson-nano-devkit mmcblk0p1
</pre>

## Building the L4T environment
This section is for developers needing to rebuild the drivers.

- Build :
<pre>
./l4t_build.sh $L4T_VERSION xavier
</pre>

- Generate the jetson-l4t-$L4T_VERSION-nano-eg-cams_$DRIVERVERSION_arm64.deb package :
<pre>
./l4t_gen_delivery_package.sh $L4T_VERSION nano $DRIVERVERSION
</pre>

## Installing the camera drivers on the board
- install the jetson-l4t-$L4T_VERSION-nano-eg-cams_$DRIVERVERSION_arm64.deb package on the Jetson board. It was delivered or locally built previously :
<pre>
sudo dpkg -i jetson-l4t-$L4T_VERSION-nano-eg-cams_$DRIVERVERSION_arm64.deb
</pre>
- edit the /boot/extlinux/extlinux.conf file, create a new entry and make it default  :
<pre>
DEFAULT eg-cams
[...]
LABEL eg-cams
      MENU LABEL eg-cams kernel
      LINUX /boot/eg/Image
      FDT /boot/eg/tegra210-p3448-0000-p3449-0000-b00-eg-cams.dtb
      INITRD /boot/initrd
      APPEND ${cbootargs} quiet root=/dev/mmcblk0p1 rw rootwait rootfstype=ext4 console=ttyS0,115200n8 console=tty0 fbcon=map:0 net.ifnames=0 nv-auto-config
[...]
</pre>
Note : the APPEND line may change from a L4T version to another
- reboot the Jetson board

Jetson Xavier NX 16GB commercial (no SD) for Jetson Xavier NX devkit :
======================================================================
L4T_VERSION=35.1, 35.3.1, 35.4.1 or 35.5.0

## Building the L4T environment
This section is for developers needing to rebuild the drivers. Skip the "Flashing with sdkmanager" section.

If you don't need to build the drivers and received a "jetson-l4t-$L4T_VERSION-xavier-eg-cams_$DRIVERVERSION_arm64.deb" package, go to the "Flashing with sdkmanager" section.

- flash the image before building the drivers :
<pre>
./l4t_prepare.sh $L4T_VERSION xavier
./l4t_copy_sources.sh $L4T_VERSION xavier
cd $L4T_VERSION/Linux_for_Tegra_xavier.src
sudo ./flash.sh jetson-xavier-nx-devkit-emmc mmcblk0p1
</pre>

- build it :
<pre>
./l4t_build.sh $L4T_VERSION xavier
</pre>

- generate the jetson-l4t-$L4T_VERSION-xavier-eg-cams_$DRIVERVERSION_arm64.deb package :
<pre>
./l4t_gen_delivery_package.sh $L4T_VERSION xavier $DRIVERVERSION
</pre>

## Flashing with sdkmanager
Flash the Xavier devkit kit following these instructions https://docs.nvidia.com/sdk-manager/install-with-sdkm-jetson/index.html

## Install the camera drivers on the board
- install the jetson-l4t-$L4T_VERSION-xavier-eg-cams_$DRIVERVERSION_arm64.deb package on the Jetson board. It was delivered or locally built previously :
<pre>
sudo dpkg -i jetson-l4t-$L4T_VERSION-xavier-eg-cams_$DRIVERVERSION_arm64.deb
</pre>
- edit the /boot/extlinux/extlinux.conf file, create a new entry and make it default  :
<pre>
DEFAULT eg-cams
[...]
LABEL eg-cams
      MENU LABEL eg-cams kernel
      LINUX /boot/eg/Image
      FDT /boot/eg/tegra194-p3668-0001-p3509-0000-eg-cams.dtb
      INITRD /boot/initrd
      APPEND ${cbootargs} root=/dev/mmcblk0p1 rw rootwait rootfstype=ext4 console=ttyTCU0,115200n8 console=tty0 fbcon=map:0 net.ifnames=0 video=efifb:off
[...]
</pre>
Note : the APPEND line may change from a L4T version to another
- reboot the Jetson board


Jetson AGX Orin for Auvidea X230D kit :
=======================================
L4T_VERSION=35.1, 35.3.1, 35.4.1 or 35.5.0

## Building the L4T environment
This section is for developers needing to rebuild the drivers. Skip the "Flashing with sdkmanager" section.

If you don't need to build the drivers and received a "jetson-l4t-$L4T_VERSION-auvidea-x230d-eg-cams_$DRIVERVERSION_arm64.deb" package, go to the "Flashing with sdkmanager" section.

- flash the image before building the drivers :
<pre>
./l4t_prepare.sh $L4T_VERSION auvidea_X230D
./l4t_copy_sources.sh $L4T_VERSION auvidea_X230D
cd $L4T_VERSION/Linux_for_Tegra_auvidea_X230D.src
sudo ./flash.sh jetson-agx-orin-devkit mmcblk0p1
</pre>

- build it :
<pre>
./l4t_build.sh $L4T_VERSION auvidea_X230D
</pre>

- generate the jetson-l4t-$L4T_VERSION-auvidea-x230d-eg-cams_$DRIVERVERSION_arm64.deb package :
<pre>
./l4t_gen_delivery_package.sh $L4T_VERSION auvidea_X230D $DRIVERVERSION
</pre>

## Flashing with sdkmanager
Flash the Auvidea X230D kit following the instructions in the SW Setup Guide https://auvidea.eu/download/Software.
Use the JetPack 5.1.1 for L4T_VERSION 35.3.1 and JetPack 5.1.2 for L4T_VERSION 35.4.1.

## Install the camera drivers on the board
- install the jetson-l4t-$L4T_VERSION-auvidea-x230d-eg-cams_$DRIVERVERSION_arm64.deb package on the Jetson board. It was delivered or locally built previously :
<pre>
sudo dpkg -i jetson-l4t-$L4T_VERSION-auvidea-x230d-eg-cams_$DRIVERVERSION_arm64.deb
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
Note : the APPEND line may change from a L4T version to another
- reboot the Jetson board



