Jetson Nano 2GB Developer Kit :
===============================
L4T_VERSION=32.7.1, 32.7.4

## 1/ Preparing the L4T environment
This section is for developers needing to rebuild the drivers or flash the board with the Nvidia flash.sh script.

<pre>
./l4t_prepare.sh $L4T_VERSION nano
./l4t_copy_sources.sh $L4T_VERSION nano
</pre>

## 2/ Flashing the board
- Flash the Nano devkit kit following instructions, for example for L4R R32.7.1 : https://developer.nvidia.com/embedded/jetpack-sdk-461

Or

- use the L4T flash script :
<pre>
cd $L4T_VERSION/Linux_for_Tegra_nano
sudo ./flash.sh jetson-nano-devkit mmcblk0p1
</pre>

## 3/ Building the L4T environment
This section is for developers needing to rebuild the drivers.

- Build :
<pre>
./l4t_build.sh $L4T_VERSION nano
</pre>

- Generate the jetson-l4t-$L4T_VERSION-nano-eg-cams_X.Y.Z_arm64.deb package :
<pre>
./l4t_gen_delivery_package.sh $L4T_VERSION nano
</pre>
X.Y.Z is the driver version taken automatically from the git tag. So to use this script, a git checkout must be made on the correct tag.
The package is generated in the $L4T_VERSION folder.

## 4/ Installing the camera drivers on the board
- install the jetson-l4t-$L4T_VERSION-nano-eg-cams_X.Y.Z_arm64.deb package on the Jetson board. It was delivered or locally built previously :
<pre>
sudo dpkg -i jetson-l4t-$L4T_VERSION-nano-eg-cams_X.Y.Z_arm64.deb
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

## 1/ Preparing the L4T environment
This section is for developers needing to rebuild the drivers or flash the board with the Nvidia flash.sh script.

<pre>
./l4t_prepare.sh $L4T_VERSION xavier
./l4t_copy_sources.sh $L4T_VERSION xavier
</pre>

## 2/ Flashing the board
- Flash the Xavier devkit kit following these instructions https://docs.nvidia.com/sdk-manager/install-with-sdkm-jetson/index.html

Or

- use the L4T flash script :
<pre>
cd $L4T_VERSION/Linux_for_Tegra_xavier
sudo ./flash.sh jetson-xavier-nx-devkit-emmc mmcblk0p1
</pre>

## 3/ Building the L4T environment
This section is for developers needing to rebuild the drivers.

- Build :
<pre>
./l4t_build.sh $L4T_VERSION xavier
</pre>

- Generate the jetson-l4t-$L4T_VERSION-xavier-eg-cams_X.Y.Z_arm64.deb package :
<pre>
./l4t_gen_delivery_package.sh $L4T_VERSION xavier
</pre>
X.Y.Z is the driver version taken automatically from the git tag. So to use this script, a git checkout must be made on the correct tag.
The package is generated in the $L4T_VERSION folder.

## 4/ Installing the camera drivers on the board
- install the jetson-l4t-$L4T_VERSION-xavier-eg-cams_X.Y.Z_arm64.deb package on the Jetson board. It was delivered or locally built previously :
<pre>
sudo dpkg -i jetson-l4t-$L4T_VERSION-xavier-eg-cams_X.Y.Z_arm64.deb
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

IMPORTANT NOTE : for Auvidea X230D kit, the L4T environment must be built AFTER flashing the board, when using the flash.sh script. Unless the screen will not work.

## 1/ Preparing the L4T environment
This section is for developers needing to rebuild the drivers or flash the board with the Nvidia flash.sh script.

<pre>
./l4t_prepare.sh $L4T_VERSION auvidea_X230D
./l4t_copy_sources.sh $L4T_VERSION auvidea_X230D
</pre>

## 2/ Flashing the board
Only if using L4T_VERSION 35.3.1, it is possible to flash the Auvidea X230D kit following the instructions in the SW Setup Guide https://auvidea.eu/download/Software. Use JetPack 5.1.1.

Or 

- use the L4T flash script :
<pre>
cd $L4T_VERSION/Linux_for_Tegra_auvidea_X230D
sudo ./flash.sh jetson-agx-orin-devkit mmcblk0p1
</pre>

## 3/ Building the L4T environment
This section is for developers needing to rebuild the drivers.

- Build :
<pre>
./l4t_build.sh $L4T_VERSION auvidea_X230D
</pre>

- Generate the jetson-l4t-$L4T_VERSION-auvidea-x230d-eg-cams_X.Y.Z_arm64.deb package :
<pre>
./l4t_gen_delivery_package.sh $L4T_VERSION auvidea_X230D
</pre>
X.Y.Z is the driver version taken automatically from the git tag. So to use this script, a git checkout must be made on the correct tag.
The package is generated in the $L4T_VERSION folder.

## 4/ Installing the camera drivers on the board
- install the jetson-l4t-$L4T_VERSION-auvidea-x230d-eg-cams_X.Y.Z_arm64.deb package on the Jetson board. It was delivered or locally built previously :
<pre>
sudo dpkg -i jetson-l4t-$L4T_VERSION-auvidea-x230d-eg-cams_X.Y.Z_arm64.deb
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

