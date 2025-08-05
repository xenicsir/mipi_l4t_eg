<!-- TOC start (generated with https://github.com/derlin/bitdowntoc) -->

- [Exosens cameras MIPI CSI-2 driver for NVIDIA Jetson boards](#exosens-cameras-mipi-csi-2-driver-for-nvidia-jetson-boards)
   * [Prerequisites for cross-compiling <a name="Prerequisites"></a>](#prerequisites-for-cross-compiling)
      + [Host PC](#host-pc)
   * [Building and installing MIPI drivers on supported SoM / carrier boards](#building-and-installing-mipi-drivers-on-supported-som-carrier-boards)
      + [Jetson Nano SoM / Jetson Nano devkit](#jetson-nano-som-jetson-nano-devkit)
         - [Preparing the L4T environment](#preparing-the-l4t-environment)
         - [Flashing the board](#flashing-the-board)
         - [Building the L4T environment](#building-the-l4t-environment)
         - [Installing the MIPI drivers on the board](#installing-the-mipi-drivers-on-the-board)
            * [Package installation](#package-installation)
            * [Linux boot](#linux-boot)
         - [Configuring a camera port](#configuring-a-camera-port)
      + [Jetson Xavier NX 16GB (no SD) SoM / Jetson Xavier NX devkit](#jetson-xavier-nx-16gb-no-sd-som-jetson-xavier-nx-devkit)
         - [Preparing the L4T environment](#preparing-the-l4t-environment-1)
         - [Flashing the board](#flashing-the-board-1)
         - [Building the L4T environment](#building-the-l4t-environment-1)
         - [Installing the MIPI drivers on the board](#installing-the-mipi-drivers-on-the-board-1)
            * [Package installation](#package-installation-1)
            * [Linux boot](#linux-boot-1)
         - [Configuring a camera port](#configuring-a-camera-port-1)
      + [Jetson AGX Orin SoM / Auvidea X230D kit](#jetson-agx-orin-som-auvidea-x230d-kit)
         - [Preparing the L4T environment](#preparing-the-l4t-environment-2)
         - [Flashing the board](#flashing-the-board-2)
         - [Building the L4T environment](#building-the-l4t-environment-2)
         - [Installing the MIPI drivers on the board](#installing-the-mipi-drivers-on-the-board-2)
            * [Package installation](#package-installation-2)
            * [Linux boot](#linux-boot-2)
         - [Configuring a camera port](#configuring-a-camera-port-2)
      + [Jetson Orin NX or Nano SoM / Jetson Orin Nano devkit](#jetson-orin-nx-or-nano-som-jetson-orin-nano-devkit)
         - [Preparing the L4T environment](#preparing-the-l4t-environment-3)
         - [Flashing the board](#flashing-the-board-3)
         - [Building the L4T environment](#building-the-l4t-environment-3)
         - [Installing the MIPI drivers on the board](#installing-the-mipi-drivers-on-the-board-3)
            * [Package installation](#package-installation-3)
            * [Linux boot](#linux-boot-3)
         - [Configuring a camera port](#configuring-a-camera-port-3)
            * [Exosens cameras](#exosens-cameras)
            * [Other cameras](#other-cameras)
      + [Jetson Orin NX or Nano SoM / Forecr DSBOARD-ORNXS](#jetson-orin-nx-or-nano-som-forecr-dsboard-ornxs)
         - [Preparing the L4T environment](#preparing-the-l4t-environment-4)
         - [Flashing the board](#flashing-the-board-4)
         - [Building the L4T environment](#building-the-l4t-environment-4)
         - [Installing the MIPI drivers on the board](#installing-the-mipi-drivers-on-the-board-4)
            * [Package installation](#package-installation-4)
            * [Linux boot](#linux-boot-4)
         - [Configuring a camera port](#configuring-a-camera-port-4)
            * [Exosens cameras](#exosens-cameras-1)
            * [Other cameras](#other-cameras-1)
   * [Hints to help integrating the drivers on other L4T versions and other SoM/carrier boards <a name="hints"></a>](#hints-to-help-integrating-the-drivers-on-other-l4t-versions-and-other-somcarrier-boards)
      + [Getting the L4T archives files](#getting-the-l4t-archives-files)
      + [Porting kernel patches to a new L4T version](#porting-kernel-patches-to-a-new-l4t-version)
      + [Creating a camera device tree for a new SoM / carrier board](#creating-a-camera-device-tree-for-a-new-som-carrier-board)
      + [Integrating carrier boards with vendor specific files/patches](#integrating-carrier-boards-with-vendor-specific-filespatches)

<!-- TOC end -->

<!-- TOC --><a name="exosens-cameras-mipi-csi-2-driver-for-nvidia-jetson-boards"></a>
# Exosens cameras MIPI CSI-2 driver for NVIDIA Jetson boards

This document describes how to build and install the MIPI drivers for different Jetson SoM (System On Module) and carrier boards, based on Nvidia BSP (L4T, Linux For Tegra).

It also gives some hints to help integrating the drivers on other L4T versions and other carrier boards.

The **MIPI_deployment.xlsx** sheet presents an overview of the supported cameras/SoM/carrier boards/L4T versions.

<!-- TOC --><a name="prerequisites-for-cross-compiling"></a>
## Prerequisites for cross-compiling <a name="Prerequisites"></a>

<!-- TOC --><a name="host-pc"></a>
### Host PC

* Recommended OS is Ubuntu 20.04 LTS, 22.04 LTS or 22.04 LTS, depending on L4T version.
* Git is needed to clone this repository

<!-- TOC --><a name="building-and-installing-mipi-drivers-on-supported-som-carrier-boards"></a>
## Building and installing MIPI drivers on supported SoM / carrier boards

<!-- TOC --><a name="jetson-nano-som-jetson-nano-devkit"></a>
### Jetson Nano SoM / Jetson Nano devkit
Supported L4T versions :
L4T_VERSION=32.7.1, 32.7.4  
SOM_BOARD=nano

<!-- TOC --><a name="preparing-the-l4t-environment"></a>
#### Preparing the L4T environment
This section is for developers needing to rebuild the drivers or flash the board with the Nvidia flash.sh script.

<pre>
./l4t_prepare.sh $L4T_VERSION $SOM_BOARD
./l4t_copy_sources.sh $L4T_VERSION $SOM_BOARD
</pre>

<!-- TOC --><a name="flashing-the-board"></a>
#### Flashing the board
- Flash the Nano devkit kit following instructions, for example for L4R R32.7.1 : https://developer.nvidia.com/embedded/jetpack-sdk-461

Or

- Enter recovery mode by following the instructions in one of the guides:  
   [Quick Start Guide L4T 35.3.1](https://docs.nvidia.com/jetson/archives/r35.3.1/DeveloperGuide/text/IN/QuickStart.html) (NVIDIA Jetson Orin Nano, Orin NX, Xavier NX and AGX Xavier)
   [Quick Start Guide L4T 32.7.3](https://docs.nvidia.com/jetson/archives/l4t-archived/l4t-3273/index.html#page/Tegra%20Linux%20Driver%20Package%20Development%20Guide/quick_start.html) (NVIDIA Jetson Nano, TX2, Xavier NX and AGX Xavier)
- use the L4T flash script :
<pre>
cd $L4T_VERSION/Linux_for_Tegra_$SOM_BOARD
sudo ./flash.sh jetson-nano-devkit mmcblk0p1
</pre>

<!-- TOC --><a name="building-the-l4t-environment"></a>
#### Building the L4T environment
This section is for developers needing to rebuild the drivers.

- Build :
<pre>
./l4t_build.sh $L4T_VERSION $SOM_BOARD
</pre>

- Generate the jetson-l4t-$L4T_VERSION-$SOM_BOARD-eg-cams_X.Y.Z_arm64.deb package including the MIPI drivers :
<pre>
./l4t_gen_delivery_package.sh $L4T_VERSION $SOM_BOARD
</pre>
X.Y.Z is the driver version taken automatically from the git tag. So to use this script, a git checkout must be made on the correct tag.
It it possible to force the version with the following command : 
<pre>
./l4t_gen_delivery_package.sh $L4T_VERSION $SOM_BOARD X.Y.Z
</pre>
The package is generated in the $L4T_VERSION folder.

<!-- TOC --><a name="installing-the-mipi-drivers-on-the-board"></a>
#### Installing the MIPI drivers on the board
<!-- TOC --><a name="package-installation"></a>
##### Package installation

Install the jetson-l4t-$L4T_VERSION-$SOM_BOARD-eg-cams_X.Y.Z_arm64.deb package on the Jetson board. It was delivered or locally built previously :
<pre>
sudo dpkg -i jetson-l4t-$L4T_VERSION-$SOM_BOARD-eg-cams_X.Y.Z_arm64.deb
</pre>

<!-- TOC --><a name="linux-boot"></a>
##### Linux boot

Make the board boot with the patched kernel and use MIPI cameras device tree.  
The devicetree file to use depends on the Jetson SoM version and the carrier board.  
Check the original device tree file name. For example : 
<pre>
$ sudo dmesg |grep dts
[    0.212290] DTS File Name: /dvs/git/dirty/git-master_linux/kernel/kernel-4.9/arch/arm64/boot/dts/../../../../../../hardware/nvidia/platform/t210/porg/kernel-dts/tegra210-p3448-0000-p3449-0000-b00.dts
</pre>
Here the devicetree file name is tegra210-p3448-0000-p3449-0000-b00. Then create a new entry accordingly in /boot/extlinux/extlinux.conf and make it default :
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
Notes :
- the APPEND line may change from an L4T version to another. Base it on the primary entry
- Using the /boot/eg/Image is not mandatory for video streaming to be functional
- customer can add their own patches in the dedicated kernel source folder

Finally, reboot the Jetson board.

<!-- TOC --><a name="configuring-a-camera-port"></a>
#### Configuring a camera port
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

<!-- TOC --><a name="jetson-xavier-nx-16gb-no-sd-som-jetson-xavier-nx-devkit"></a>
### Jetson Xavier NX 16GB (no SD) SoM / Jetson Xavier NX devkit
Supported L4T versions :
L4T_VERSION=35.1, 35.3.1, 35.4.1 or 35.5.0  
SOM_BOARD=xavier

<!-- TOC --><a name="preparing-the-l4t-environment-1"></a>
#### Preparing the L4T environment
This section is for developers needing to rebuild the drivers or flash the board with the Nvidia flash.sh script.

<pre>
./l4t_prepare.sh $L4T_VERSION $SOM_BOARD
./l4t_copy_sources.sh $L4T_VERSION $SOM_BOARD
</pre>

<!-- TOC --><a name="flashing-the-board-1"></a>
#### Flashing the board
- Flash the Xavier devkit kit following these instructions https://docs.nvidia.com/sdk-manager/install-with-sdkm-jetson/index.html

Or

- Enter recovery mode by following the instructions in one of the guides:  
   [Quick Start Guide L4T 35.3.1](https://docs.nvidia.com/jetson/archives/r35.3.1/DeveloperGuide/text/IN/QuickStart.html) (NVIDIA Jetson Orin Nano, Orin NX, Xavier NX and AGX Xavier)  
   [Quick Start Guide L4T 32.7.3](https://docs.nvidia.com/jetson/archives/l4t-archived/l4t-3273/index.html#page/Tegra%20Linux%20Driver%20Package%20Development%20Guide/quick_start.html) (NVIDIA Jetson Nano, TX2, Xavier NX and AGX Xavier)
- use the L4T flash script :
<pre>
cd $L4T_VERSION/Linux_for_Tegra_xavier
sudo ./flash.sh jetson-xavier-devkit-emmc mmcblk0p1
</pre>

<!-- TOC --><a name="building-the-l4t-environment-1"></a>
#### Building the L4T environment
This section is for developers needing to rebuild the drivers.

- Build :
<pre>
./l4t_build.sh $L4T_VERSION $SOM_BOARD
</pre>

- Generate the jetson-l4t-$L4T_VERSION-$SOM_BOARD-eg-cams_X.Y.Z_arm64.deb package including the MIPI drivers :
<pre>
./l4t_gen_delivery_package.sh $L4T_VERSION $SOM_BOARD
</pre>
X.Y.Z is the driver version taken automatically from the git tag. So to use this script, a git checkout must be made on the correct tag.
It it possible to force the version with the following command : 
<pre>
./l4t_gen_delivery_package.sh $L4T_VERSION $SOM_BOARD X.Y.Z
</pre>
The package is generated in the $L4T_VERSION folder.

<!-- TOC --><a name="installing-the-mipi-drivers-on-the-board-1"></a>
#### Installing the MIPI drivers on the board
<!-- TOC --><a name="package-installation-1"></a>
##### Package installation
Install the jetson-l4t-$L4T_VERSION-$SOM_BOARD-eg-cams_X.Y.Z_arm64.deb package on the Jetson board. It was delivered or locally built previously :
<pre>
sudo dpkg -i jetson-l4t-$L4T_VERSION-$SOM_BOARD-eg-cams_X.Y.Z_arm64.deb
</pre>

<!-- TOC --><a name="linux-boot-1"></a>
##### Linux boot
Make the board boot with the patched kernel and use MIPI cameras device tree.  
The devicetree file to use depends on the Jetson SoM version and the carrier board.  
Check the original device tree file name. For example : 
<pre>
$ sudo dmesg |grep dts
[    0.006884] DTS File Name: /dvs/git/dirty/git-master_linux/kernel/kernel-5.10/arch/arm64/boot/dts/../../../../../../hardware/nvidia/platform/t19x/jakku/kernel-dts/tegra194-p3668-0001-p3509-0000.dts
</pre>
Here the devicetree file name is tegra194-p3668-0001-p3509-0000. Then create a new entry accordingly in /boot/extlinux/extlinux.conf and make it default :
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
Notes :
- the APPEND line may change from an L4T version to another. Base it on the primary entry
- Using the /boot/eg/Image is not mandatory for video streaming to be functional
- customer can add their own patches in the dedicated kernel source folder

Finally, reboot the Jetson board.

<!-- TOC --><a name="configuring-a-camera-port-1"></a>
#### Configuring a camera port
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

<!-- TOC --><a name="jetson-agx-orin-som-auvidea-x230d-kit"></a>
### Jetson AGX Orin SoM / Auvidea X230D kit
Supported L4T versions :
L4T_VERSION=35.3.1, 35.4.1 or 35.5.0  
SOM_BOARD=auvidea_X230D

IMPORTANT NOTE : for Auvidea X230D kit, the L4T environment must be built AFTER flashing the board, when using the flash.sh script. Unless the screen will not work.

<!-- TOC --><a name="preparing-the-l4t-environment-2"></a>
#### Preparing the L4T environment
This section is for developers needing to rebuild the drivers or flash the board with the Nvidia flash.sh script.

<pre>
./l4t_prepare.sh $L4T_VERSION $SOM_BOARD
./l4t_copy_sources.sh $L4T_VERSION $SOM_BOARD
</pre>

<!-- TOC --><a name="flashing-the-board-2"></a>
#### Flashing the board
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

<!-- TOC --><a name="building-the-l4t-environment-2"></a>
#### Building the L4T environment
This section is for developers needing to rebuild the drivers.

- Build :
<pre>
./l4t_build.sh $L4T_VERSION $SOM_BOARD
</pre>

- Generate the jetson-l4t-$L4T_VERSION-auvidea-x230d-eg-cams_X.Y.Z_arm64.deb package including the MIPI drivers :
<pre>
./l4t_gen_delivery_package.sh $L4T_VERSION $SOM_BOARD
</pre>
X.Y.Z is the driver version taken automatically from the git tag. So to use this script, a git checkout must be made on the correct tag.
It it possible to force the version with the following command : 
<pre>
./l4t_gen_delivery_package.sh $L4T_VERSION $SOM_BOARD X.Y.Z
</pre>
The package is generated in the $L4T_VERSION folder.

<!-- TOC --><a name="installing-the-mipi-drivers-on-the-board-2"></a>
#### Installing the MIPI drivers on the board
<!-- TOC --><a name="package-installation-2"></a>
##### Package installation

Install the jetson-l4t-$L4T_VERSION-auvidea-x230d-eg-cams_X.Y.Z_arm64.deb package on the Jetson board. It was delivered or locally built previously :
<pre>
sudo dpkg -i jetson-l4t-$L4T_VERSION-auvidea-x230d-eg-cams_X.Y.Z_arm64.deb
</pre>

<!-- TOC --><a name="linux-boot-2"></a>
##### Linux boot

Make the board boot with the patched kernel and use MIPI cameras device tree.  
The devicetree file to use depends on the Jetson SoM version and the carrier board.  
Check the original device tree file name. For example : 
<pre>
$ sudo dmesg |grep dts
[    0.003491] DTS File Name: source/public/kernel/kernel-5.10/arch/arm64/boot/dts/../../../../../../hardware/nvidia/platform/t23x/concord/kernel-dts/tegra234-p3701-0004-p3737-0000-auvidea.dts
</pre>
Here the devicetree file name is tegra234-p3701-0004-p3737-0000-auvidea. Then create a new entry accordingly in /boot/extlinux/extlinux.conf and make it default :
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
Notes :
- the APPEND line may change from an L4T version to another. Base it on the primary entry
- Using the /boot/eg/Image is not mandatory for video streaming to be functional
- customer can add their own patches in the dedicated kernel source folder

Finally, reboot the Jetson board.

<!-- TOC --><a name="configuring-a-camera-port-2"></a>
#### Configuring a camera port
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


<!-- TOC --><a name="jetson-orin-nx-or-nano-som-jetson-orin-nano-devkit"></a>
### Jetson Orin NX or Nano SoM / Jetson Orin Nano devkit
Supported L4T versions :
L4T_VERSION=36.4, 36.4.3 or 36.4.4  
SOM_BOARD=orin_nx

Note : the SoM/board name here is orin_nx, but it is also supported by Orin Nano, as it shares the same SoM base and the same carrier board.

<!-- TOC --><a name="preparing-the-l4t-environment-3"></a>
#### Preparing the L4T environment
This section is for developers needing to rebuild the drivers.

<pre>
./l4t_prepare.sh $L4T_VERSION $SOM_BOARD
./l4t_copy_sources.sh $L4T_VERSION $SOM_BOARD
</pre>

<!-- TOC --><a name="flashing-the-board-3"></a>
#### Flashing the board

Install JetPack 6 :  
https://developer.nvidia.com/embedded/jetpack-sdk-62  
https://www.waveshare.com/wiki/JETSON-ORIN-NX-16G-DEV-KIT

<!-- TOC --><a name="building-the-l4t-environment-3"></a>
#### Building the L4T environment
This section is for developers needing to rebuild the drivers.

- Build :
<pre>
./l4t_build.sh $L4T_VERSION $SOM_BOARD
</pre>

- Generate the jetson-l4t-$L4T_VERSION-orin-nx-eg-cams_X.Y.Z_arm64.deb package including the MIPI drivers :
<pre>
./l4t_gen_delivery_package.sh $L4T_VERSION $SOM_BOARD
</pre>
X.Y.Z is the driver version taken automatically from the git tag. So to use this script, a git checkout must be made on the correct tag.
It it possible to force the version with the following command : 
<pre>
./l4t_gen_delivery_package.sh $L4T_VERSION $SOM_BOARD X.Y.Z
</pre>
The package is generated in the $L4T_VERSION folder.

<!-- TOC --><a name="installing-the-mipi-drivers-on-the-board-3"></a>
#### Installing the MIPI drivers on the board
<!-- TOC --><a name="package-installation-3"></a>
##### Package installation

Install the jetson-l4t-$L4T_VERSION-orin-nx-eg-cams_X.Y.Z_arm64.deb package on the Jetson board. It was delivered or locally built previously :
<pre>
sudo dpkg --force-overwrite -i jetson-l4t-$L4T_VERSION-orin-nx-eg-cams_X.Y.Z_arm64.deb
</pre>

<!-- TOC --><a name="linux-boot-3"></a>
##### Linux boot

After the first package installation, a new JetsonIO label is automatically created in /boot/extlinux/extlinux.conf, and the system will boot on it.  
<pre>
[...]
LABEL JetsonIO
        MENU LABEL Custom Header Config: CSI Exosens Cameras
        LINUX /boot/eg/Image
        FDT [...]
        INITRD /boot/initrd
        APPEND [...]
        OVERLAYS /boot/tegra234-p3767-camera-p3768-eg-cams-dione.dtbo
[...]
</pre>
Notes : 
- by default, there is no need to modify it
- using the /boot/eg/Image is not mandatory for video streaming to be functional
- customer can add their own patches in the dedicated kernel source folder

Finally, reboot the Jetson board.

<!-- TOC --><a name="configuring-a-camera-port-3"></a>
#### Configuring a camera port
There are 2 camera ports on the Jetson Orin NX/Nano devkit, "CAM0" and "CAM1".

After installing the MIPI driver package for the first time, both ports are configured by default for Dione cameras.

To change the configuration, use this command, <ins>then reboot</ins> : 
<pre>
sudo python /opt/nvidia/jetson-io/config-by-hardware.py -n $COMMAND
</pre>
Note : the jetson-io scripts have been patched

<!-- TOC --><a name="exosens-cameras"></a>
##### Exosens cameras
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

<span>***IMPORTANT NOTE : CSI diff pair swap on Jetson Orin Nano devkit***</span>
https://nvidia-jetson.piveral.com/jetson-orin-nano/csi-diff-pair-polarity-swap-on-nvidia-jetson-orin-nano-dev-board/
<pre>
lane_polarity = "6"; 
</pre>
has been added in this devicetree overlay as a workaround for that issue : tegra234-p3767-camera-common-eg-cams-dione.dtsi

To port the devicetree on a custom carrier board embedding the Orin NX/Nano, this lane polarity parameter may have to be removed.

<!-- TOC --><a name="other-cameras"></a>
##### Other cameras
Jetson L4T supports IMX219 and IMX477 cameras. Device tree overlays are provided to offer the possibility to mix IMX219/477 and Exosens cameras on both CAM0 and CAM1 ports. IMX219/477 device trees were ported as is, a basic video streaming test was done with IMX219.

| IMX219    |          |                                                                                                |                                                                                                                                                                          |
|-----------|----------|------------------------------------------------------|------------------------------------------------------------------------------------------------------------------|
| **CAM0**  | **CAM1** | **config-by-hardware.py -n $COMMAND**                | **OVERLAYS in /boot/extlinux/extlinux.conf**                                                                     |
| x         |          | 2="Exosens Cameras" 2="Exosens Cameras. CAM0:imx219" | /boot/tegra234-p3767-camera-p3768-eg-cams-dione.dtbo,/boot/tegra234-p3767-camera-p3768-eg-cam0-imx219.dtbo       |
|           | x        | 2="Exosens Cameras" 2="Exosens Cameras. CAM1:imx219" | /boot/tegra234-p3767-camera-p3768-eg-cams-dione.dtbo,/boot/tegra234-p3767-camera-p3768-eg-cam1-imx219.dtbo       |

| IMX477    |          |                                                                                                |                                                                                                                                                                          |
|-----------|----------|--------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------|
| **CAM0**  | **CAM1** | **config-by-hardware.py -n $COMMAND**                        | **OVERLAYS in /boot/extlinux/extlinux.conf**                                                                        |
| x         |          | 2="Exosens Cameras" 2="Exosens Cameras. CAM0:imx477"         | /boot/tegra234-p3767-camera-p3768-eg-cams-dione.dtbo,/boot/tegra234-p3767-camera-p3768-eg-cam0-imx477.dtbo          |
| x 4 lanes |          | 2="Exosens Cameras" 2="Exosens Cameras. CAM0:imx477-4-lanes" | /boot/tegra234-p3767-camera-p3768-eg-cams-dione.dtbo,/boot/tegra234-p3767-camera-p3768-eg-cam0-imx477-4-lanes.dtbo  |
|           | x        | 2="Exosens Cameras" 2="Exosens Cameras. CAM1:imx477"         | /boot/tegra234-p3767-camera-p3768-eg-cams-dione.dtbo,/boot/tegra234-p3767-camera-p3768-eg-cam1-imx477.dtbo          |

For example, configure Dione on CAM0 port and IMX219 on CAM1 : 
<pre>
sudo python /opt/nvidia/jetson-io/config-by-hardware.py -n 2="Exosens Cameras" 2="Exosens Cameras. CAM1:imx219"
</pre>
For example, configure IMX477 on CAM0 and MicroCube640 on CAM1 : 
<pre>
sudo python /opt/nvidia/jetson-io/config-by-hardware.py -n 2="Exosens Cameras" 2="Exosens Cameras. CAM0:imx477" 2="Exosens Cameras. CAM1:EC_1_lane"
</pre>

<!-- TOC --><a name="jetson-orin-nx-or-nano-som-forecr-dsboard-ornxs"></a>
### Jetson Orin NX or Nano SoM / Forecr DSBOARD-ORNXS
https://www.forecr.io/products/dsboard-ornxs

Supported L4T versions :
L4T_VERSION=36.4, 36.4.3 or 36.4.4  
SOM_BOARD=dsboard_ornxs

<!-- TOC --><a name="preparing-the-l4t-environment-4"></a>
#### Preparing the L4T environment
This section is for developers needing to rebuild the drivers.

<pre>
./l4t_prepare.sh $L4T_VERSION $SOM_BOARD
./l4t_copy_sources.sh $L4T_VERSION $SOM_BOARD
</pre>

<!-- TOC --><a name="flashing-the-board-4"></a>
#### Flashing the board

Install JetPack 6 : 
https://www.forecr.io/blogs/installation/jetpack-6-x-installation-for-dsboard-ornxs

<!-- TOC --><a name="building-the-l4t-environment-4"></a>
#### Building the L4T environment
This section is for developers needing to rebuild the drivers.

- Build :
<pre>
./l4t_build.sh $L4T_VERSION $SOM_BOARD
</pre>

- Generate the jetson-l4t-$L4T_VERSION-dsboard-ornxs-eg-cams_X.Y.Z_arm64.deb package including the MIPI drivers :
<pre>
./l4t_gen_delivery_package.sh $L4T_VERSION $SOM_BOARD
</pre>
X.Y.Z is the driver version taken automatically from the git tag. So to use this script, a git checkout must be made on the correct tag.
It it possible to force the version with the following command : 
<pre>
./l4t_gen_delivery_package.sh $L4T_VERSION $SOM_BOARD X.Y.Z
</pre>
The package is generated in the $L4T_VERSION folder.

<!-- TOC --><a name="installing-the-mipi-drivers-on-the-board-4"></a>
#### Installing the MIPI drivers on the board
<!-- TOC --><a name="package-installation-4"></a>
##### Package installation

Install the jetson-l4t-$L4T_VERSION-dsboard-ornxs-eg-cams_X.Y.Z_arm64.deb package on the Jetson board. It was delivered or locally built previously :
<pre>
sudo dpkg --force-overwrite -i jetson-l4t-$L4T_VERSION-dsboard-ornxs-eg-cams_X.Y.Z_arm64.deb
</pre>

<!-- TOC --><a name="linux-boot-4"></a>
##### Linux boot

After the first package installation, a new JetsonIO label is automatically created in /boot/extlinux/extlinux.conf, and the system will boot on it.  
<pre>
[...]
LABEL JetsonIO
        MENU LABEL Custom Header Config: CSI Exosens Cameras for DSBOARD-ORNXS
        LINUX /boot/eg/Image
        FDT [...]
        INITRD /boot/initrd
        APPEND [...]
        OVERLAYS /boot/tegra234-p3767-camera-dsboard-ornxs-eg-cams-dione.dtbo
[...]
</pre>
Notes : 
- by default, there is no need to modify it
- using the /boot/eg/Image is not mandatory for video streaming to be functional
- customer can add their own patches in the dedicated kernel source folder

Finally, reboot the Jetson board.

<!-- TOC --><a name="configuring-a-camera-port-4"></a>
#### Configuring a camera port
There are 2 camera ports on the DSBOARD-ORNXS carrier board. They are not marked, but let's use the same names as for the Jetson Orin NX/Nano devkit, "CAM0" and "CAM1".

After installing the MIPI driver package for the first time, both ports are configured by default for Dione cameras.

To change the configuration, use this command, <ins>then reboot</ins> : 
<pre>
sudo python /opt/nvidia/jetson-io/config-by-hardware.py -n $COMMAND
</pre>
Note : the jetson-io scripts have been patched

<!-- TOC --><a name="exosens-cameras-1"></a>
##### Exosens cameras
Here are the different values for $COMMAND, depending on camera types and ports, and the corresponding OVERLAYS entry in the /boot/extlinux/extlinux.conf file : 

| Dione     |          | MicroCube640 |          | Crius1280/SmartIR640 |          |                                                                                                |                                                                                                                                                                          |
|-----------|----------|--------------|----------|----------------------|----------|------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **CAM0**  | **CAM1** | **CAM0**     | **CAM1** | **CAM0**             | **CAM1** | **config-by-hardware.py -n $COMMAND**                                                          | **OVERLAYS in /boot/extlinux/extlinux.conf**                                                                                                                             |
| x         | x        |              |          |                      |          | 2="Exosens Cameras for DSBOARD-ORNXS"                                                                            | /boot/tegra234-p3767-camera-dsboard-ornxs-eg-cams-dione.dtbo                                                                                                                     |
| x         |          |              | x        |                      |          | 2="Exosens Cameras for DSBOARD-ORNXS" 2="Exosens Cameras. CAM1:EC_1_lane"                                        | /boot/tegra234-p3767-camera-dsboard-ornxs-eg-cams-dione.dtbo,/boot/tegra234-p3767-camera-p3768-eg-cam1-ec-1-lane.dtbo                                                            |
| x         |          |              |          |                      | x        | 2="Exosens Cameras for DSBOARD-ORNXS" 2="Exosens Cameras. CAM1:EC_2_lanes"                                       | /boot/tegra234-p3767-camera-dsboard-ornxs-eg-cams-dione.dtbo,/boot/tegra234-p3767-camera-p3768-eg-cam1-ec-2-lane2.dtbo                                                           |
|           | x        | x            |          |                      |          | 2="Exosens Cameras for DSBOARD-ORNXS" 2="Exosens Cameras. CAM0:EC_1_lane"                                        | /boot/tegra234-p3767-camera-dsboard-ornxs-eg-cams-dione.dtbo,/boot/tegra234-p3767-camera-p3768-eg-cam0-ec-1-lane.dtbo                                                            |
|           | x        |              |          | x                    |          | 2="Exosens Cameras for DSBOARD-ORNXS" 2="Exosens Cameras. CAM0:EC_2_lanes"                                       | /boot/tegra234-p3767-camera-dsboard-ornxs-eg-cams-dione.dtbo,/boot/tegra234-p3767-camera-p3768-eg-cam0-ec-2-lanes.dtbo                                                           |
|           |          | x            | x        |                      |          | 2="Exosens Cameras for DSBOARD-ORNXS" 2="Exosens Cameras. CAM0:EC_1_lane"  2="Exosens Cameras. CAM1:EC_1_lane"   | /boot/tegra234-p3767-camera-dsboard-ornxs-eg-cams-dione.dtbo,/boot/tegra234-p3767-camera-p3768-eg-cam0-ec-1-lane.dtbo,/boot/tegra234-p3767-camera-p3768-eg-cam1-ec-1-lane.dtbo   |
|           |          | x            |          |                      | x        | 2="Exosens Cameras for DSBOARD-ORNXS" 2="Exosens Cameras. CAM0:EC_1_lane"  2="Exosens Cameras. CAM1:EC_2_lanes"  | /boot/tegra234-p3767-camera-dsboard-ornxs-eg-cams-dione.dtbo,/boot/tegra234-p3767-camera-p3768-eg-cam0-ec-1-lane.dtbo,/boot/tegra234-p3767-camera-p3768-eg-cam1-ec-2-lanes.dtbo  |
|           |          |              | x        | x                    |          | 2="Exosens Cameras for DSBOARD-ORNXS" 2="Exosens Cameras. CAM0:EC_2_lanes" 2="Exosens Cameras. CAM1:EC_1_lane"   | /boot/tegra234-p3767-camera-dsboard-ornxs-eg-cams-dione.dtbo,/boot/tegra234-p3767-camera-p3768-eg-cam0-ec-2-lanes.dtbo,/boot/tegra234-p3767-camera-p3768-eg-cam1-ec-1-lane.dtbo  |
|           |          |              | x        |                      | x        | 2="Exosens Cameras for DSBOARD-ORNXS" 2="Exosens Cameras. CAM0:EC_2_lanes" 2="Exosens Cameras. CAM1:EC_2_lanes"  | /boot/tegra234-p3767-camera-dsboard-ornxs-eg-cams-dione.dtbo,/boot/tegra234-p3767-camera-p3768-eg-cam0-ec-2-lanes.dtbo,/boot/tegra234-p3767-camera-p3768-eg-cam1-ec-2-lanes.dtbo |

For example, configure Dione on CAM0 port and MicroCube640 on CAM1 : 
<pre>
sudo python /opt/nvidia/jetson-io/config-by-hardware.py -n 2="Exosens Cameras for DSBOARD-ORNXS" 2="Exosens Cameras. CAM1:EC_1_lane" 
</pre>
For example, configure MicroCube640 on CAM0 port and Crius1280 on CAM1 :
<pre>
sudo python /opt/nvidia/jetson-io/config-by-hardware.py -n 2="Exosens Cameras for DSBOARD-ORNXS" 2="Exosens Cameras. CAM0:EC_1_lane"  2="Exosens Cameras. CAM1:EC_2_lanes"
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
        <b>OVERLAYS /boot/tegra234-p3767-camera-dsboard-ornxs-eg-cams-dione.dtbo,/boot/tegra234-p3767-camera-p3768-eg-cam1-ec-1-lane.dtbo</b>
[...]
</pre>

For example, MicroCube640 on CAM0 port and Crius1280 on CAM1 :
<pre>
[...]
    OVERLAYS /boot/tegra234-p3767-camera-dsboard-ornxs-eg-cams-dione.dtbo,/boot/tegra234-p3767-camera-p3768-eg-cam0-ec-1-lane.dtbo,/boot/tegra234-p3767-camera-p3768-eg-cam1-ec-2-lanes.dtbo
[...]
</pre>

<span>***IMPORTANT NOTE : CSI diff pair swap on Jetson Orin Nano devkit***</span>
https://nvidia-jetson.piveral.com/jetson-orin-nano/csi-diff-pair-polarity-swap-on-nvidia-jetson-orin-nano-dev-board/
<pre>
lane_polarity = "6"; 
</pre>
has been added in this devicetree overlay as a workaround for that issue : tegra234-p3767-camera-common-eg-cams-dione.dtsi

To port the devicetree on a custom carrier board embedding the Orin NX/Nano, this lane polarity parameter may have to be removed.

<!-- TOC --><a name="other-cameras-1"></a>
##### Other cameras
Jetson L4T supports IMX219 and IMX477 cameras. Device tree overlays are provided to offer the possibility to mix IMX219/477 and Exosens cameras on both CAM0 and CAM1 ports. IMX219/477 device trees were ported as is, a basic video streaming test was done with IMX219.

| IMX219    |          |                                                                                                |                                                                                                                                                                          |
|-----------|----------|------------------------------------------------------|------------------------------------------------------------------------------------------------------------------|
| **CAM0**  | **CAM1** | **config-by-hardware.py -n $COMMAND**                | **OVERLAYS in /boot/extlinux/extlinux.conf**                                                                     |
| x         |          | 2="Exosens Cameras for DSBOARD-ORNXS" 2="Exosens Cameras. CAM0:imx219" | /boot/tegra234-p3767-camera-dsboard-ornxs-eg-cams-dione.dtbo,/boot/tegra234-p3767-camera-p3768-eg-cam0-imx219.dtbo       |
|           | x        | 2="Exosens Cameras for DSBOARD-ORNXS" 2="Exosens Cameras. CAM1:imx219" | /boot/tegra234-p3767-camera-dsboard-ornxs-eg-cams-dione.dtbo,/boot/tegra234-p3767-camera-p3768-eg-cam1-imx219.dtbo       |

| IMX477    |          |                                                                                                |                                                                                                                                                                          |
|-----------|----------|--------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------|
| **CAM0**  | **CAM1** | **config-by-hardware.py -n $COMMAND**                        | **OVERLAYS in /boot/extlinux/extlinux.conf**                                                                        |
| x         |          | 2="Exosens Cameras for DSBOARD-ORNXS" 2="Exosens Cameras. CAM0:imx477"         | /boot/tegra234-p3767-camera-dsboard-ornxs-eg-cams-dione.dtbo,/boot/tegra234-p3767-camera-p3768-eg-cam0-imx477.dtbo          |
| x 4 lanes |          | 2="Exosens Cameras for DSBOARD-ORNXS" 2="Exosens Cameras. CAM0:imx477-4-lanes" | /boot/tegra234-p3767-camera-dsboard-ornxs-eg-cams-dione.dtbo,/boot/tegra234-p3767-camera-p3768-eg-cam0-imx477-4-lanes.dtbo  |
|           | x        | 2="Exosens Cameras for DSBOARD-ORNXS" 2="Exosens Cameras. CAM1:imx477"         | /boot/tegra234-p3767-camera-dsboard-ornxs-eg-cams-dione.dtbo,/boot/tegra234-p3767-camera-p3768-eg-cam1-imx477.dtbo          |

For example, configure Dione on CAM0 port and IMX219 on CAM1 : 
<pre>
sudo python /opt/nvidia/jetson-io/config-by-hardware.py -n 2="Exosens Cameras for DSBOARD-ORNXS" 2="Exosens Cameras. CAM1:imx219"
</pre>
For example, configure IMX477 on CAM0 and MicroCube640 on CAM1 : 
<pre>
sudo python /opt/nvidia/jetson-io/config-by-hardware.py -n 2="Exosens Cameras for DSBOARD-ORNXS" 2="Exosens Cameras. CAM0:imx477" 2="Exosens Cameras. CAM1:EC_1_lane"
</pre>

<!-- TOC --><a name="hints-to-help-integrating-the-drivers-on-other-l4t-versions-and-other-somcarrier-boards"></a>
## Hints to help integrating the drivers on other L4T versions and other SoM/carrier boards <a name="hints"></a>

Adding a new L4T version and support new SoM/carrier board consist of :
<!-- TOC --><a name="getting-the-l4t-archives-files"></a>
### Getting the L4T archives files

* First check the compatibility of L4T_VERSION with the SoM target : https://developer.nvidia.com/embedded/jetson-linux-archive

* modify the *environment* file and add a new entry. For example the L4T version 35.3.1 for Xavier NX and AGX Orin/Auvidea X320D : 
<pre>
35.3.1)
   case "${2}" in
   xavier|auvidea_X230D)
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
      echo "Incorrect board. $1 is compatible with xavier or auvidea_X230D"
      exit
      ;;
   esac
   ;;
</pre>


<!-- TOC --><a name="porting-kernel-patches-to-a-new-l4t-version"></a>
### Porting kernel patches to a new L4T version
The *source/$L4T_VERSION/Linux_for_Tegra* folder contains the customized files specific to a L4T version needed to build the MIPI drivers.

If the need is only to implement a new $L4T_VERSION_NEW version :
* create the *source/$L4T_VERSION_NEW/Linux_for_Tegra* folder, port and adapt the content of an other *source/$L4T_VERSION/Linux_for_Tegra* folder
* the *source/common* should be kept unchanged, except if there was an important Linux kernel update changing some kernel APIs. In this last case, some modifications may be needed in drivers code (*sources/common/Linux_for_Tegra/source/public/kernel/nvidia/drivers/media/i2c/*)

Note : the *l4t_copy_sources.sh* script is in charge of copying customized files to the original L4T build environment.

<!-- TOC --><a name="creating-a-camera-device-tree-for-a-new-som-carrier-board"></a>
### Creating a camera device tree for a new SoM / carrier board
Device tree source files are in the *sources/common/Linux_for_Tegra/source/public/hardware/nvidia/platform* folder.
To create a new devicetree for the MIPI cameras, here are the steps : 
* find out the one related to the new SoM, check the *FDT* entry in the */boot/extlinux/extlinux.conf* on the target board. For example on Jetson Xavier NX 16GB : 
<pre>
   FDT /boot/dtb/kernel_tegra194-p3668-0001-p3509-0000.dtb
</pre>
The device tree source file is *source/public/hardware/nvidia/platform/t19x/jakku/kernel-dts/tegra194-p3668-0001-p3509-0000.dts*
* for example, if the new board devicetree file is *kernel_tegra194-p2888-0001-p2822-0000.dtb*, the corresponding devicetree source file is *source/public/hardware/nvidia/platform/t19x/galen/kernel-dts/tegra194-p2888-0001-p2822-0000.dts*
* so the new MIPI devicetree source file to create has to be called *sources/common/Linux_for_Tegra/source/public/hardware/nvidia/platform/t19x/galen/kernel-dts/tegra194-p2888-0001-p2822-0000-eg-cams.dts*
* some devicetree overlay files have to be created, with this name patterns : 
    * *sources/common/Linux_for_Tegra/source/public/hardware/nvidia/platform/t19x/galen/kernel-dts/tegra194-p2888-0001-p2822-0000-eg-$CUSTOM_NAME-dione.dts*
    * *sources/common/Linux_for_Tegra/source/public/hardware/nvidia/platform/t19x/galen/kernel-dts/tegra194-p2888-0001-p2822-0000-eg-$CUSTOM_NAME-ec-1-lane.dts*
    * *sources/common/Linux_for_Tegra/source/public/hardware/nvidia/platform/t19x/galen/kernel-dts/tegra194-p2888-0001-p2822-0000-eg-$CUSTOM_NAME-ec-2-lanes.dts*
    * CUSTOM_NAME could be the board name and the camera port name, for example *my_board_camera_port_0*
* the *./sources/common/Linux_for_Tegra/rootfs/usr/bin/eg_dt_camera_config_set.sh* script is in charge to apply the devicetree overlays, it must be adapted to support the new overlay files
* the *./sources/common/Linux_for_Tegra/rootfs/usr/bin/eg_dt_camera_config_get.sh* script must also be adapted
    
To create new devicetree files, take example on the MIPI devicetree files for Jetson Xavier NX 16GB. Here is the description of them : 
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


<!-- TOC --><a name="integrating-carrier-boards-with-vendor-specific-filespatches"></a>
### Integrating carrier boards with vendor specific files/patches
Some board vendors provide specific files and/or patches. They need to be applied from the *sources/$L4T_VERSION/Linux_for_Tegra_$NEW_BOARD* folder.

Let's take an example :
* the "*./l4t_copy_sources.sh 35.5.0 agx_orin_devkit*" command would use only *sources/35.5.0/Linux_for_Tegra*, because the AGC Orin devkit is the native carrier board from NVIDIA. **Note that this command has no effect, as this Nvidia devkit is currently not supported.**
* the "*./l4t_copy_sources.sh 35.5.0 auvidea_X230D*" command uses *sources/35.5.0/Linux_for_Tegra* and *sources/35.5.0/Linux_for_Tegra_agx_orin_auvidea_X230D*, which contains files provided from Auvidea.

For a new "vendor_board" board : 
* create the *sources/35.5.0/Linux_for_Tegra_vendor_board* and put specific files in it
* use build scripts with *vendor_board* argument. For example : "./l4t_copy_sources.sh $L4T_VERSION vendor_board"

Note : the *l4t_copy_sources.sh* script only copies files. If the developer wants to apply patches, the script needs to be modified.







