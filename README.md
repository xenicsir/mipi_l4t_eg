# Exosens cameras MIPI CSI-2 driver for NVIDIA Jetson boards

This document describes how to build and install the MIPI drivers for different Jetson SOM (System On Module) and carrier boards, based on Nvidia BSP (L4T, Linux For Tegra).

It also gives some hints to help integrating the drivers on other L4T versions and other carrier boards.

The MIPI_deployment.xlsx sheet presents an overview of the supported cameras/SOM/carrier boards/L4T versions.

## Prerequisites for cross-compiling

### Host PC

* Recommended OS is Ubuntu 20.04 LTS or Ubuntu 22.04 LTS
* Git is needed to clone this repository

## Building and installing MIPI drivers on supported SOM / carrier boards

### Jetson Nano
Supported L4T versions :
L4T_VERSION=32.7.1, 32.7.4

#### 1/ Preparing the L4T environment
This section is for developers needing to rebuild the drivers or flash the board with the Nvidia flash.sh script.

<pre>
./l4t_prepare.sh $L4T_VERSION nano
./l4t_copy_sources.sh $L4T_VERSION nano
</pre>

#### 2/ Flashing the board
- Flash the Nano devkit kit following instructions, for example for L4R R32.7.1 : https://developer.nvidia.com/embedded/jetpack-sdk-461

Or

- Enter recovery mode by following the instructions in one of the guides:

   [Quick Start Guide L4T 35.3.1](https://docs.nvidia.com/jetson/archives/r35.3.1/DeveloperGuide/text/IN/QuickStart.html) (NVIDIA Jetson Orin Nano, Orin NX, Xavier NX and AGX Xavier)

   [Quick Start Guide L4T 32.7.3](https://docs.nvidia.com/jetson/archives/l4t-archived/l4t-3273/index.html#page/Tegra%20Linux%20Driver%20Package%20Development%20Guide/quick_start.html) (NVIDIA Jetson Nano, TX2, Xavier NX and AGX Xavier)
- use the L4T flash script :
<pre>
cd $L4T_VERSION/Linux_for_Tegra_nano
sudo ./flash.sh jetson-nano-devkit mmcblk0p1
</pre>

#### 3/ Building the L4T environment
This section is for developers needing to rebuild the drivers.

- Build :
<pre>
./l4t_build.sh $L4T_VERSION nano
</pre>

- Generate the jetson-l4t-$L4T_VERSION-nano-eg-cams_X.Y.Z_arm64.deb package including the MIPI drivers :
<pre>
./l4t_gen_delivery_package.sh $L4T_VERSION nano
</pre>
X.Y.Z is the driver version taken automatically from the git tag. So to use this script, a git checkout must be made on the correct tag.
It it possible to force the version with the following command : 
<pre>
./l4t_gen_delivery_package.sh $L4T_VERSION nano X.Y.Z
</pre>
The package is generated in the $L4T_VERSION folder.

#### 4/ Installing the MIPI drivers on the board
- install the jetson-l4t-$L4T_VERSION-nano-eg-cams_X.Y.Z_arm64.deb package on the Jetson board. It was delivered or locally built previously :
<pre>
sudo dpkg -i jetson-l4t-$L4T_VERSION-nano-eg-cams_X.Y.Z_arm64.deb
</pre>
- make the board boot with the patched kernel and use MIPI cameras device tree

The DT file to use depends on the Jetson SOM version and the carrier board.

Check the original device tree file name. For example : 
<pre>
$ sudo dmesg |grep dts
[    0.212290] DTS File Name: /dvs/git/dirty/git-master_linux/kernel/kernel-4.9/arch/arm64/boot/dts/../../../../../../hardware/nvidia/platform/t210/porg/kernel-dts/tegra210-p3448-0000-p3449-0000-b00.dts
</pre>
Here the DT file name is tegra210-p3448-0000-p3449-0000-b00. Then create a new entry accordingly in /boot/extlinux/extlinux.conf and make it default :
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
Note : the APPEND line may change from an L4T version to another. Base it on the primary entry. 
- reboot the Jetson board

#### 5/ Configuring a camera port to support a camera
There are 2 camera ports on the Jetson Nano 2GB Developer Kit, "cam0" and "cam1".

After installing the MIPI driver package for the first time, both ports are configured by default for Dione cameras.

To change the configuration, use this command, <ins>then reboot</ins> : 
<pre>
eg_dt_camera_config_set.sh $CAMPORT_NUMBER $CAM_TYPE
</pre>
With CAMPORT_NUMBER = 0 or 1

With CAM_TYPE = Dione, MicroCube640, SmartIR640 or Crius1280

To get the ports configuration (<ins>after a reboot</ins>, when the set command was used), use this command : 
<pre>
eg_dt_camera_config_get.sh
</pre>

### Jetson Xavier NX 16GB (no SD) / Jetson Xavier NX devkit
Supported L4T versions :
L4T_VERSION=35.1, 35.3.1, 35.4.1 or 35.5.0

#### 1/ Preparing the L4T environment
This section is for developers needing to rebuild the drivers or flash the board with the Nvidia flash.sh script.

<pre>
./l4t_prepare.sh $L4T_VERSION xavier_nx
./l4t_copy_sources.sh $L4T_VERSION xavier_nx
</pre>

#### 2/ Flashing the board
- Flash the Xavier devkit kit following these instructions https://docs.nvidia.com/sdk-manager/install-with-sdkm-jetson/index.html

Or

- Enter recovery mode by following the instructions in one of the guides:

   [Quick Start Guide L4T 35.3.1](https://docs.nvidia.com/jetson/archives/r35.3.1/DeveloperGuide/text/IN/QuickStart.html) (NVIDIA Jetson Orin Nano, Orin NX, Xavier NX and AGX Xavier)

   [Quick Start Guide L4T 32.7.3](https://docs.nvidia.com/jetson/archives/l4t-archived/l4t-3273/index.html#page/Tegra%20Linux%20Driver%20Package%20Development%20Guide/quick_start.html) (NVIDIA Jetson Nano, TX2, Xavier NX and AGX Xavier)
- use the L4T flash script :
<pre>
cd $L4T_VERSION/Linux_for_Tegra_xavier_nx
sudo ./flash.sh jetson-xavier-nx-devkit-emmc mmcblk0p1
</pre>

#### 3/ Building the L4T environment
This section is for developers needing to rebuild the drivers.

- Build :
<pre>
./l4t_build.sh $L4T_VERSION xavier_nx
</pre>

- Generate the jetson-l4t-$L4T_VERSION-xavier-nx-eg-cams_X.Y.Z_arm64.deb package including the MIPI drivers :
<pre>
./l4t_gen_delivery_package.sh $L4T_VERSION xavier_nx
</pre>
X.Y.Z is the driver version taken automatically from the git tag. So to use this script, a git checkout must be made on the correct tag.
It it possible to force the version with the following command : 
<pre>
./l4t_gen_delivery_package.sh $L4T_VERSION xavier_nx X.Y.Z
</pre>
The package is generated in the $L4T_VERSION folder.

#### 4/ Installing the MIPI drivers on the board
- install the jetson-l4t-$L4T_VERSION-xavier-nx-eg-cams_X.Y.Z_arm64.deb package on the Jetson board. It was delivered or locally built previously :
<pre>
sudo dpkg -i jetson-l4t-$L4T_VERSION-xavier-nx-eg-cams_X.Y.Z_arm64.deb
</pre>

- make the board boot with the patched kernel and use MIPI cameras device tree

The DT file to use depends on the Jetson SOM version and the carrier board.

Check the original device tree file name. For example : 
<pre>
$ sudo dmesg |grep dts
[    0.006884] DTS File Name: /dvs/git/dirty/git-master_linux/kernel/kernel-5.10/arch/arm64/boot/dts/../../../../../../hardware/nvidia/platform/t19x/jakku/kernel-dts/tegra194-p3668-0001-p3509-0000.dts
</pre>
Here the DT file name is tegra194-p3668-0001-p3509-0000. Then create a new entry accordingly in /boot/extlinux/extlinux.conf and make it default :
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
Note : the APPEND line may change from an L4T version to another. Base it on the primary entry. 
- reboot the Jetson board

#### 5/ Configuring a camera port to support a camera
There are 2 camera ports on the Jetson Xavier NX devkit, "cam0" and "cam1".

After installing the MIPI driver package for the first time, both ports are configured by default for Dione cameras.

To change the configuration, use this command, <ins>then reboot</ins> : 
<pre>
eg_dt_camera_config_set.sh $CAMPORT_NUMBER $CAM_TYPE
</pre>
With CAMPORT_NUMBER = 0 or 1

With CAM_TYPE = Dione, MicroCube640, SmartIR640 or Crius1280

To get the ports configuration (<ins>after a reboot</ins>, when the set command was used), use this command : 
<pre>
eg_dt_camera_config_get.sh
</pre>

### Jetson AGX Orin / Auvidea X230D kit
Supported L4T versions :
L4T_VERSION=35.3.1, 35.4.1 or 35.5.0

IMPORTANT NOTE : for Auvidea X230D kit, the L4T environment must be built AFTER flashing the board, when using the flash.sh script. Unless the screen will not work.

#### 1/ Preparing the L4T environment
This section is for developers needing to rebuild the drivers or flash the board with the Nvidia flash.sh script.

<pre>
./l4t_prepare.sh $L4T_VERSION agx_orin_auvidea_X230D
./l4t_copy_sources.sh $L4T_VERSION agx_orin_auvidea_X230D
</pre>

#### 2/ Flashing the board
Only if using L4T_VERSION 35.3.1, it is possible to flash the Auvidea X230D kit following the instructions in the SW Setup Guide https://auvidea.eu/download/Software. Use JetPack 5.1.1.

Or 

- Enter recovery mode by following the instructions of the guide:

   [Quick Start Guide L4T 35.3.1](https://docs.nvidia.com/jetson/archives/r35.3.1/DeveloperGuide/text/IN/QuickStart.html) (NVIDIA Jetson Orin Nano, Orin NX, Xavier NX and AGX Xavier)
- use the L4T flash script :
IMPORTANT : this has to be done before "Building the L4T environment". When l4t_build.sh is done, the flashing doesn't work (the board doesn't start).
<pre>
cd $L4T_VERSION/Linux_for_Tegra_auvidea_X230D
sudo ./flash.sh jetson-agx-orin-devkit mmcblk0p1
</pre>

#### 3/ Building the L4T environment
This section is for developers needing to rebuild the drivers.

- Build :
<pre>
./l4t_build.sh $L4T_VERSION agx_orin_auvidea_X230D
</pre>

- Generate the jetson-l4t-$L4T_VERSION-auvidea-x230d-eg-cams_X.Y.Z_arm64.deb package including the MIPI drivers :
<pre>
./l4t_gen_delivery_package.sh $L4T_VERSION agx_orin_auvidea_X230D
</pre>
X.Y.Z is the driver version taken automatically from the git tag. So to use this script, a git checkout must be made on the correct tag.
It it possible to force the version with the following command : 
<pre>
./l4t_gen_delivery_package.sh $L4T_VERSION agx_orin_auvidea_X230D X.Y.Z
</pre>
The package is generated in the $L4T_VERSION folder.

#### 4/ Installing the MIPI drivers on the board
- install the jetson-l4t-$L4T_VERSION-auvidea-x230d-eg-cams_X.Y.Z_arm64.deb package on the Jetson board. It was delivered or locally built previously :
<pre>
sudo dpkg -i jetson-l4t-$L4T_VERSION-auvidea-x230d-eg-cams_X.Y.Z_arm64.deb
</pre>
- make the board boot with the patched kernel and use MIPI cameras device tree

The DT file to use depends on the Jetson SOM version and the carrier board.

Check the original device tree file name. For example : 
<pre>
$ sudo dmesg |grep dts
[    0.003491] DTS File Name: source/public/kernel/kernel-5.10/arch/arm64/boot/dts/../../../../../../hardware/nvidia/platform/t23x/concord/kernel-dts/tegra234-p3701-0004-p3737-0000-auvidea.dts
</pre>
Here the DT file name is tegra234-p3701-0004-p3737-0000-auvidea. Then create a new entry accordingly in /boot/extlinux/extlinux.conf and make it default :
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
Note : the APPEND line may change from an L4T version to another. Base it on the primary entry. 
- reboot the Jetson board

#### 5/ Configuring a camera port to support a camera
There are 2 camera ports on the Auvidea X230D kit, "AB" and "CD".

After installing the MIPI driver package for the first time, both ports are configured by default for Dione cameras.

To change the configuration, use this command, <ins>then reboot</ins> : 
<pre>
eg_dt_camera_config_set.sh $CAMPORT_NUMBER $CAM_TYPE
</pre>
With CAMPORT_NUMBER = AB or CD

With CAM_TYPE = Dione, MicroCube640, SmartIR640 or Crius1280

To get the ports configuration (<ins>after a reboot</ins>, when the set command was used), use this command : 
<pre>
eg_dt_camera_config_get.sh
</pre>


### Jetson Orin NX
Supported L4T versions :
L4T_VERSION=36.4.3

#### 1/ Preparing the L4T environment
This section is for developers needing to rebuild the drivers or flash the board with the Nvidia flash.sh script.

<pre>
./l4t_prepare.sh $L4T_VERSION orin_nx
./l4t_copy_sources.sh $L4T_VERSION orin_nx
</pre>

#### 2/ Flashing the board

Install JetPack 6 : 
https://developer.nvidia.com/embedded/jetpack-sdk-62
https://www.waveshare.com/wiki/JETSON-ORIN-NX-16G-DEV-KIT

#### 3/ Building the L4T environment
This section is for developers needing to rebuild the drivers.

- Build :
<pre>
./l4t_build.sh $L4T_VERSION orin_nx
</pre>

- Generate the jetson-l4t-$L4T_VERSION-orin-nx-eg-cams_X.Y.Z_arm64.deb package including the MIPI drivers :
<pre>
./l4t_gen_delivery_package.sh $L4T_VERSION orin_nx
</pre>
X.Y.Z is the driver version taken automatically from the git tag. So to use this script, a git checkout must be made on the correct tag.
It it possible to force the version with the following command : 
<pre>
./l4t_gen_delivery_package.sh $L4T_VERSION orin_nx X.Y.Z
</pre>
The package is generated in the $L4T_VERSION folder.

#### 4/ Installing the MIPI drivers on the board
- install the jetson-l4t-$L4T_VERSION-orin-nx-eg-cams_X.Y.Z_arm64.deb package on the Jetson board. It was delivered or locally built previously :
<pre>
sudo dpkg --force-overwrite -i jetson-l4t-$L4T_VERSION-orin-nx-eg-cams_X.Y.Z_arm64.deb
</pre>
- reboot the Jetson board

#### 5/ Configuring a camera port to support a camera
There are 2 camera ports on the Jetson Orin NX devkit, "CAM0" and "CAM1".

<span style="color:red">***Currently, only the CAM1 port works.***</span>

After installing the MIPI driver package for the first time, both ports are configured by default for Dione cameras.

To change the configuration, use this command, <ins>then reboot</ins> : 
<pre>
sudo python /opt/nvidia/jetson-io/config-by-hardware.py -n $COMMAND
</pre>
Note : the jetson-io scripts have been patched

Here are the different values for $COMMAND, depending on camera types and ports, and the corresponding OVERLAYS entry in the /boot/extlinux/extlinux.conf file : 

| Dione     |          | MicroCube640 |          | Crius1280/SmartIR640 |          |                                                                                                |                                                                                                                                                                          |
|-----------|----------|--------------|----------|----------------------|----------|------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **CAM0**  | **CAM1** | **CAM0**     | **CAM1** | **CAM0**             | **CAM1** | **config-by-hardware.py -n $COMMAND**                                                          | **OVERLAYS in /boot/extlinux/extlinux.conf**                                                                                                                             |
| x         | x        |              |          |                      |          | 2="Exosens Cameras"                                                                            | /boot/tegra234-p3767-camera-p3768-eg-cams-dione.dtbo                                                                                                                     |
| x         |          |              | x        |                      |          | 2="Exosens Cameras" 2="Exosens Cameras. CAM1:EC_1_lane"                                        | /boot/tegra234-p3767-camera-p3768-eg-cams-dione.dtbo,/boot/tegra234-p3767-camera-p3768-eg-cam1-ec-1-lane.dtbo                                                            |
| x         |          |              |          |                      | x        | 2="Exosens Cameras" 2="Exosens Cameras. CAM1:EC_2_lanes"                                       | /boot/tegra234-p3767-camera-p3768-eg-cams-dione.dtbo,/boot/tegra234-p3767-camera-p3768-eg-cam1-ec-2-lane2.dtbo                                                           |
|           | x        | x            |          |                      |          | 2="Exosens Cameras" 2="Exosens Cameras. CAM0:EC_1_lane"                                        | /boot/tegra234-p3767-camera-p3768-eg-cams-dione.dtbo,/boot/tegra234-p3767-camera-p3768-eg-cam0-ec-1-lane.dtbo                                                            |
|           | x        |              |          | x                    |          | 2="Exosens Cameras" 2="Exosens Cameras. CAM0:EC_2_lanes"                                       | /boot/tegra234-p3767-camera-p3768-eg-cams-dione.dtbo,/boot/tegra234-p3767-camera-p3768-eg-cam0-ec-2-lanes.dtbo                                                           |
|           |          | x            | x        |                      |          | 2="Exosens Cameras" 2="Exosens Cameras. CAM0:EC_1_lane"  2="Exosens Cameras. CAM1:EC_1_lane"   | /boot/tegra234-p3767-camera-p3768-eg-cams-dione.dtbo,/boot/tegra234-p3767-camera-p3768-eg-cam0-ec-1-lane.dtbo,/boot/tegra234-p3767-camera-p3768-eg-cam1-ec-1-lane.dtbo   |
|           |          | x            |          |                      | x        | 2="Exosens Cameras" 2="Exosens Cameras. CAM0:EC_1_lane"  2="Exosens Cameras. CAM1:EC_2_lanes"  | /boot/tegra234-p3767-camera-p3768-eg-cams-dione.dtbo,/boot/tegra234-p3767-camera-p3768-eg-cam0-ec-1-lane.dtbo,/boot/tegra234-p3767-camera-p3768-eg-cam1-ec-2-lanes.dtbo  |
|           |          |              | x        | x                    |          | 2="Exosens Cameras" 2="Exosens Cameras. CAM0:EC_2_lanes" 2="Exosens Cameras. CAM1:EC_1_lane"   | /boot/tegra234-p3767-camera-p3768-eg-cams-dione.dtbo,/boot/tegra234-p3767-camera-p3768-eg-cam0-ec-2-lanes.dtbo,/boot/tegra234-p3767-camera-p3768-eg-cam1-ec-1-lane.dtbo  |
|           |          |              | x        |                      | x        | 2="Exosens Cameras" 2="Exosens Cameras. CAM0:EC_2_lanes" 2="Exosens Cameras. CAM1:EC_2_lanes"  | /boot/tegra234-p3767-camera-p3768-eg-cams-dione.dtbo,/boot/tegra234-p3767-camera-p3768-eg-cam0-ec-2-lanes.dtbo,/boot/tegra234-p3767-camera-p3768-eg-cam1-ec-2-lanes.dtbo |

For example, configure Dione on CAM0 port and MicroCube640 on CAM1 : 
<pre>
sudo python /opt/nvidia/jetson-io/config-by-hardware.py -n 2="Exosens Cameras" 2="Exosens Cameras. CAM1:EC_1_lane" 
</pre>
For example, configure MicroCube640 on CAM0 port and Crius1280 on CAM1 :
<pre>
sudo python /opt/nvidia/jetson-io/config-by-hardware.py -n 2="Exosens Cameras" 2="Exosens Cameras. CAM0:EC_1_lane"  2="Exosens Cameras. CAM1:EC_2_lanes"
</pre>

To check the ports configuration, open the /boot/extlinux/extlinux.conf file, JetsonIO label part, OVERLAYS entry.

For example, Dione on CAM0 port and MicroCube640 on CAM1 : 
<pre>
[...]
LABEL JetsonIO
        MENU LABEL Custom Header Config: <CSI Exosens Cameras> <CSI Exosens Cameras. CAM1:EC_1_lane>
        LINUX /boot/eg/Image
        FDT /boot/dtb/kernel_tegra234-p3768-0000+p3767-0000-nv.dtb
        INITRD /boot/initrd
        APPEND ${cbootargs} root=PARTUUID=fb79911a-6ada-43b3-b983-0ec29fc92323 rw rootwait rootfstype=ext4 mminit_loglevel=4 console=ttyTCU0,115200 firmware_class.path=/etc/firmware fbcon=map:0 nospectre_bhb video=efifb:off console=tty0 nv-auto-config
        <b>OVERLAYS /boot/tegra234-p3767-camera-p3768-eg-cams-dione.dtbo,/boot/tegra234-p3767-camera-p3768-eg-cam1-ec-1-lane.dtbo</b>
[...]
</pre>

For example, MicroCube640 on CAM0 port and Crius1280 on CAM1 :
<pre>
[...]
    OVERLAYS /boot/tegra234-p3767-camera-p3768-eg-cams-dione.dtbo,/boot/tegra234-p3767-camera-p3768-eg-cam0-ec-1-lane.dtbo,/boot/tegra234-p3767-camera-p3768-eg-cam1-ec-2-lanes.dtbo
[...]
</pre>

## Hints to help integrating the drivers on other L4T versions and other SOM/carrier boards

Adding a new L4T version and support new SOM/carrier board consist of :
### Getting the L4T archives files

* First check the compatibility of L4T_VERSION with the SOM target : https://developer.nvidia.com/embedded/jetson-linux-archive

* modify the *environment* file and add a new entry. For example the L4T version 35.3.1 for Xavier NX and AGX Orin/Auvidea X320D : 
<pre>
35.3.1)
   case "${2}" in
   xavier_nx|agx_orin_auvidea_X230D)
      JETSON_PUBLIC_SOURCES=public_sources.tbz2
      JETSON_PUBLIC_SOURCES_URL=https://developer.nvidia.com/downloads/embedded/l4t/r35_release_v3.1/sources/${JETSON_PUBLIC_SOURCES}
      JETSON_TOOCHAIN_ARCHIVE=aarch64--glibc--stable-final.tar.gz
      JETSON_TOOCHAIN_ARCHIVE_URL=https://developer.nvidia.com/embedded/jetson-linux/bootlin-toolchain-gcc-93
      TOOLCHAIN_DIR=l4t-gcc
      TOOLCHAIN_PREFIX=$JETSON_DIR/$TOOLCHAIN_DIR/bin/aarch64-buildroot-linux-gnu-
      L4T_RELEASE_PACKAGE=jetson_linux_r35.3.1_aarch64.tbz2
      L4T_RELEASE_PACKAGE_URL=https://developer.nvidia.com/downloads/embedded/l4t/r35_release_v3.1/release/${L4T_RELEASE_PACKAGE}
      SAMPLE_FS_PACKAGE=tegra_linux_sample-root-filesystem_r35.3.1_aarch64.tbz2
      SAMPLE_FS_PACKAGE_URL=https://developer.nvidia.com/downloads/embedded/l4t/r35_release_v3.1/release/${SAMPLE_FS_PACKAGE}
      ;;
   *)
      echo "Incorrect board. $1 is compatible with xavier_nx or agx_orin_auvidea_X230D"
      exit
      ;;
   esac
   ;;
</pre>


### Porting kernel patches to a new L4T version
The *source/$L4T_VERSION/Linux_for_Tegra* folder contains the customized files specific to a L4T version needed to build the MIPI drivers.

If the need is only to implement a new $L4T_VERSION_NEW version :
* create the *source/$L4T_VERSION_NEW/Linux_for_Tegra* folder, port and adapt the content of an other *source/$L4T_VERSION/Linux_for_Tegra* folder
* the *source/common* should be kept unchanged, except if there was an important Linux kernel update changing some kernel APIs. In this last case, some modifications may be needed in drivers code (*sources/common/Linux_for_Tegra/source/public/kernel/nvidia/drivers/media/i2c/*)

Note : the *l4t_copy_sources.sh* script is in charge of copying customized files to the original L4T build environment.

### Creating a camera device tree for a new SOM / carrier board
Device tree source files are in the *sources/common/Linux_for_Tegra/source/public/hardware/nvidia/platform* folder.
To create a new DT for the MIPI cameras, here are the steps : 
* find out the one related to the new SOM, check the *FDT* entry in the */boot/extlinux/extlinux.conf* on the target board. For example on Jetson Xavier NX 16GB : 
<pre>
   FDT /boot/dtb/kernel_tegra194-p3668-0001-p3509-0000.dtb
</pre>
The device tree source file is *source/public/hardware/nvidia/platform/t19x/jakku/kernel-dts/tegra194-p3668-0001-p3509-0000.dts*
* for example, if the new board DT file is *kernel_tegra194-p2888-0001-p2822-0000.dtb*, the corresponding DT source file is *source/public/hardware/nvidia/platform/t19x/galen/kernel-dts/tegra194-p2888-0001-p2822-0000.dts*
* so the new MIPI DT source file to create has to be called *sources/common/Linux_for_Tegra/source/public/hardware/nvidia/platform/t19x/galen/kernel-dts/tegra194-p2888-0001-p2822-0000-eg-cams.dts*
* some DT overlay files have to be created, with this name patterns : 
    * *sources/common/Linux_for_Tegra/source/public/hardware/nvidia/platform/t19x/galen/kernel-dts/tegra194-p2888-0001-p2822-0000-eg-$CUSTOM_NAME-dione.dts*
    * *sources/common/Linux_for_Tegra/source/public/hardware/nvidia/platform/t19x/galen/kernel-dts/tegra194-p2888-0001-p2822-0000-eg-$CUSTOM_NAME-ec-1-lane.dts*
    * *sources/common/Linux_for_Tegra/source/public/hardware/nvidia/platform/t19x/galen/kernel-dts/tegra194-p2888-0001-p2822-0000-eg-$CUSTOM_NAME-ec-2-lanes.dts*
    * CUSTOM_NAME could be the board name and the camera port name, for example *my_board_camera_port_0*
* the *./sources/common/Linux_for_Tegra/rootfs/usr/bin/eg_dt_camera_config_set.sh* script is in charge to apply the DT overlays, it must be adapted to support the new overlay files
* the *./sources/common/Linux_for_Tegra/rootfs/usr/bin/eg_dt_camera_config_get.sh* script must also be adapted
    
To create new DT files, take example on the MIPI DT files for Jetson Xavier NX 16GB. Here is the description of them : 
* *t19x/jakku/kernel-dts/tegra194-p3668-0000-p3509-0000-eg-cams.dts*
    * root device tree file to compile
    * Compilation is added in *sources/$L4T_VERSION/Linux_for_Tegra/source/public/hardware/nvidia/platform/t19x/jakku/kernel-dts/Makefile*
* *t19x/jakku/kernel-dts/common/tegra194-p3509-0000-a00-eg-cams.dtsi*
    * intermediate file included in tegra194-p3668-0000-p3509-0000-eg-cams.dts
* *t19x/jakku/kernel-dts/common/tegra194-camera-jakku-eg-cams.dtsi*
    * intermediate file included in tegra194-p3509-0000-a00-eg-cams.dtsi
* *t19x/jakku/kernel-dts/common/tegra194-camera-eg-cams.dtsi*
    * this is the device tree file with MIPI cameras configuration
    * For a new target, I2C and CSI nodes names may differ, but the nodes content should remain the same. Check other cameras device trees to adapt.
* *t19x/jakku/kernel-dts/tegra194-p3668-all-p3509-0000-eg-cam0-dione.dts*
    * overlay to configure a Dione camera on cam0 port
    * Compilation is added in *sources/$L4T_VERSION/Linux_for_Tegra/source/public/hardware/nvidia/platform/t19x/jakku/kernel-dts/Makefile*
    * It is applied by the "eg_dt_camera_config_set.sh 0 Dione" command
* *t19x/jakku/kernel-dts/tegra194-p3668-all-p3509-0000-eg-cam0-ec-1-lane.dts*
    * overlay to configure an EngineCore 1 MIPI lane camera on cam0 port
    * Compilation is added in *sources/$L4T_VERSION/Linux_for_Tegra/source/public/hardware/nvidia/platform/t19x/jakku/kernel-dts/Makefile*
    * It is applied by the "eg_dt_camera_config_set.sh 0 MicroCube640" command.
* *t19x/jakku/kernel-dts/tegra194-p3668-all-p3509-0000-eg-cam0-ec-2-lanes.dts*
    * overlay to configure an EngineCore 2 MIPI lane camera on cam0 port
    * Compilation is added in *sources/$L4T_VERSION/Linux_for_Tegra/source/public/hardware/nvidia/platform/t19x/jakku/kernel-dts/Makefile*
    * It is applied by the "eg_dt_camera_config_set.sh 0 Crius1280 (or SmartIR640)" command.
* *t19x/jakku/kernel-dts/tegra194-p3668-all-p3509-0000-eg-cam1-dione.dts*
    * overlay to configure a Dione camera on cam1 port
    * Compilation is added in *sources/$L4T_VERSION/Linux_for_Tegra/source/public/hardware/nvidia/platform/t19x/jakku/kernel-dts/Makefile*
    * It is applied by the "eg_dt_camera_config_set.sh 1 Dione" command
* *t19x/jakku/kernel-dts/tegra194-p3668-all-p3509-0000-eg-cam1-ec-1-lane.dts*
    * overlay to configure an EngineCore 1 MIPI lane camera on cam1 port
    * Compilation is added in *sources/$L4T_VERSION/Linux_for_Tegra/source/public/hardware/nvidia/platform/t19x/jakku/kernel-dts/Makefile*
    * It is applied by the "eg_dt_camera_config_set.sh 1 MicroCube640" command.
* *t19x/jakku/kernel-dts/tegra194-p3668-all-p3509-0000-eg-cam1-ec-2-lanes.dts*
    * overlay to configure an EngineCore 2 MIPI lane camera on cam1 port
    * Compilation is added in *sources/$L4T_VERSION/Linux_for_Tegra/source/public/hardware/nvidia/platform/t19x/jakku/kernel-dts/Makefile*
    * It is applied by the "eg_dt_camera_config_set.sh 1 Crius1280 (or SmartIR640)" command.


### Integrating carrier boards with vendor specific files/patches
Some board vendors provide specific files and/or patches. They need to be applied from the *sources/$L4T_VERSION/Linux_for_Tegra_$NEW_BOARD* folder.

Let's take an example :
* the "*./l4t_copy_sources.sh 35.5.0 agx_orin_devkit*" command would use only *sources/35.5.0/Linux_for_Tegra*, because the AGC Orin devkit is the native carrier board from NVIDIA. **Note that this command has no effect, as this Nvidia devkit is currently not supported.**
* the "*./l4t_copy_sources.sh 35.5.0 agx_orin_auvidea_X230D*" command uses *sources/35.5.0/Linux_for_Tegra* and *sources/35.5.0/Linux_for_Tegra_agx_orin_auvidea_X230D*, which contains files provided from Auvidea.

For a new "vendor_board" board : 
* create the *sources/35.5.0/Linux_for_Tegra_vendor_board* and put specific files in it
* use build scripts with *vendor_board* argument. For example : "./l4t_copy_sources.sh $L4T_VERSION vendor_board"

Note : the *l4t_copy_sources.sh* script only copies files. If the developer wants to apply patches, the script needs to be modified.







