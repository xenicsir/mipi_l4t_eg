<!-- TOC start (generated with https://github.com/derlin/bitdowntoc) -->

- [Exosens cameras MIPI CSI-2 driver for NVIDIA Jetson boards](#exosens-cameras-mipi-csi-2-driver-for-nvidia-jetson-boards)
   * [Prerequisites for cross-compiling <a name="Prerequisites"></a>](#prerequisites-for-cross-compiling)
      + [Host PC](#host-pc)
   * [Building and installing MIPI drivers on supported L4T versions / SoM / carrier boards](#building-and-installing-mipi-drivers-on-supported-l4t-versions-som-carrier-boards)
      + [Supported L4T versions, SOM and carrier boards](#supported-l4t-versions-som-and-carrier-boards)
      + [Building the L4T environment](#building-the-l4t-environment)
      + [Building MIPI drivers for specific carrier boards](#building-mipi-drivers-for-specific-carrier-boards)
      + [Installing and configuring the MIPI drivers on the board](#installing-and-configuring-the-mipi-drivers-on-the-board)
         - [Package installation](#package-installation)
         - [Configuring a camera port on non specific (Nvidia generic) carrier boards](#configuring-a-camera-port-on-non-specific-nvidia-generic-carrier-boards)
         - [Configuring a camera port on Forecr Orin NX/Nano DSBOARD-ORNXS carrier board](#configuring-a-camera-port-on-forecr-orin-nxnano-dsboard-ornxs-carrier-board)
   * [Notes about Linux boot and device trees](#notes-about-linux-boot-and-device-trees)
      + [Linux boot](#linux-boot)
      + [Orin NX/Nano devkit devicetree issue](#orin-nxnano-devkit-devicetree-issue)
   * [Hints to help integrating the drivers on other L4T versions and other SoM/carrier boards](#hints-to-help-integrating-the-drivers-on-other-l4t-versions-and-other-somcarrier-boards)
      + [Getting the L4T archives files](#getting-the-l4t-archives-files)
      + [Porting kernel patches to a new L4T version](#porting-kernel-patches-to-a-new-l4t-version)
      + [Creating camera device trees for a new SoM / carrier board](#creating-camera-device-trees-for-a-new-som-carrier-board)
      + [Integrating specific vendor files/patches](#integrating-specific-vendor-filespatches)

<!-- TOC end -->

<!-- TOC --><a name="exosens-cameras-mipi-csi-2-driver-for-nvidia-jetson-boards"></a>
# Exosens cameras MIPI CSI-2 driver for NVIDIA Jetson boards

This document describes how to build and install the MIPI drivers for different Jetson SoM (System On Module) and carrier boards, based on Nvidia BSP (L4T, Linux For Tegra).

It also gives some hints to help integrating the drivers on other L4T versions and other carrier boards.

The [MIPI_deployment](https://github.com/xenicsir/mipi_l4t_eg/blob/main/MIPI_deployment.xlsx) sheet presents an overview of the supported cameras/SoM/carrier boards/L4T versions.

<!-- TOC --><a name="prerequisites-for-cross-compiling"></a>
## Prerequisites for cross-compiling <a name="Prerequisites"></a>

<!-- TOC --><a name="host-pc"></a>
### Host PC

* Recommended OS is Ubuntu 20.04 LTS, 22.04 LTS or 24.04 LTS, depending on L4T version. 22.04 LTS is the one currently used.

<!-- TOC --><a name="building-and-installing-mipi-drivers-on-supported-l4t-versions-som-carrier-boards"></a>
## Building and installing MIPI drivers on supported L4T versions / SoM / carrier boards

<!-- TOC --><a name="supported-l4t-versions-som-and-carrier-boards"></a>
### Supported L4T versions, SOM and carrier boards
Refer to the [MIPI_deployment](https://github.com/xenicsir/mipi_l4t_eg/blob/main/MIPI_deployment.xlsx) sheet.
For the rest of the document, $L4T_VERSION refers to the L4T version to build. For example :
L4T_VERSION=35.5.0

<!-- TOC --><a name="building-the-l4t-environment"></a>
### Building the L4T environment
This section is for developers needing to rebuild the drivers.

- Prepare the environment, build the kernel, modules, device trees :
<pre>
./l4t_prepare.sh $L4T_VERSION
./l4t_copy_sources.sh $L4T_VERSION
./l4t_build.sh $L4T_VERSION
</pre>

- Generate the jetson-l4t-$L4T_VERSION-eg-cams_X.Y.Z_arm64.deb package including the MIPI drivers :
<pre>
./l4t_gen_delivery_package.sh $L4T_VERSION generic
</pre>
X.Y.Z is the driver version taken automatically from the git tag. So to use this script, a git checkout must be made on the correct tag.
It it possible to force the version number with the following command : 
<pre>
./l4t_gen_delivery_package.sh $L4T_VERSION generic X.Y.Z
</pre>
The package is generated in the $L4T_VERSION folder.

<!-- TOC --><a name="building-mipi-drivers-for-specific-carrier-boards"></a>
### Building MIPI drivers for specific carrier boards
Some carrier boards need specific device trees and/or kernel patches. So a specific build has to be done, adding a parameter to the building scripts. The boards needing a specific build are tagged "Specific build" in the [MIPI_deployment](https://github.com/xenicsir/mipi_l4t_eg/blob/main/MIPI_deployment.xlsx) sheet.
Specific carried boards parameter values are :
SPECIFIC_CARRIER_BOARD=forecr

Then, the scripts execution is : 
./l4t_prepare.sh $L4T_VERSION $SPECIFIC_CARRIER_BOARD
./l4t_copy_sources.sh $L4T_VERSION $SPECIFIC_CARRIER_BOARD
./l4t_build.sh $L4T_VERSION $SPECIFIC_CARRIER_BOARD
./l4t_gen_delivery_package.sh $L4T_VERSION $SPECIFIC_CARRIER_BOARD

Note : for the *forecr* specicific board, L4T versions 36.x, the kernel Image is built but not used, because some modules need the original kernel. So an EG kernel patch about I2C timeout is missing. This impacts EngineCore cameras (MicroCube, SmartIR640, Crius1280) control protocole (doesn't manage correctly an error timeout) but doesn't impact video streaming.

<!-- TOC --><a name="installing-and-configuring-the-mipi-drivers-on-the-board"></a>
### Installing and configuring the MIPI drivers on the board
<!-- TOC --><a name="package-installation"></a>
#### Package installation

Note : if a 1.x.x $L4T_VERSION is already installed on the target, uninstall it. The packages names have changed with version 2.x.x, so there would be some warnings due to common files conflicts without previous uninstallation.

Install the jetson-l4t-$L4T_VERSION-eg-cams_X.Y.Z_arm64.deb package on the Jetson board. It was delivered (refer to the [MIPI_deployment](https://github.com/xenicsir/mipi_l4t_eg/blob/main/MIPI_deployment.xlsx) sheet) or locally built previously :
<pre>
sudo dpkg -i jetson-l4t-$L4T_VERSION-eg-cams_X.Y.Z_arm64.deb
</pre>

<!-- TOC --><a name="configuring-a-camera-port-on-non-specific-nvidia-generic-carrier-boards"></a>
#### Configuring a camera port on non specific (Nvidia generic) carrier boards
Note on port numbers :
- it depends on the carrier board, but there are generally 2 camera ports on Jetson boards : "cam0" and "cam1"
- for the AGX Orin Auvidea X230D board, port 0 is printed "CD" on the PCB, and port 1 is "AB".
- in Linux, when a video device is registered (camera detected), a /dev/videoX device appears. The X number is not the camera port number, but the number of the camera device, in the order it has been registered.

After installing the MIPI driver package for the first time, both ports are configured by default for Dione cameras.

To change the configuration, use this command, <ins>then reboot</ins> : 
<pre>
eg_dt_camera_config_set.sh $CAMPORT_NUMBER_0 $CAM_TYPE $CAMPORT_NUMBER_1 $CAM_TYPE
</pre>
With CAMPORT_NUMBER_0 = 0 or CAMPORT_NUMBER_0 = 1
With CAM_TYPE = Dione, MicroCube640, SmartIR640 or Crius1280
Note : if a port is not set in the command line, the port is configured for Dione


To get the ports configuration (after a "set" command <ins>and</ins> a reboot), use this command : 
<pre>
eg_dt_camera_config_get.sh
</pre>

Note : for some boards wiht multiple camera ports, it is possible to mix Exosens cameras and some sensors originally supported by the Jetson boards (IMX219 and/or IMX477). Consult the support team if this is needed.

<!-- TOC --><a name="configuring-a-camera-port-on-forecr-orin-nxnano-dsboard-ornxs-carrier-board"></a>
#### Configuring a camera port on Forecr Orin NX/Nano DSBOARD-ORNXS carrier board
There are 2 camera ports on the DSBOARD-ORNXS carrier board. They are not marked, but let's use the same names as for the Jetson Orin NX/Nano devkit, "CAM0" and "CAM1".

After installing the forecr MIPI driver package for the first time, both ports are configured by default for Dione cameras.

To change the configuration, use this command, <ins>then reboot</ins> : 
<pre>
sudo python /opt/nvidia/jetson-io/config-by-hardware.py -n $COMMAND
</pre>
Note : the jetson-io scripts have been patched

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
        MENU LABEL Custom Header Config: <CSI Exosens Cameras for DSBOARD-ORNXS> <CSI Exosens Cameras. CAM1:EC_1_lane>
        LINUX /boot/Image
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


<!-- TOC --><a name="notes-about-linux-boot-and-device-trees"></a>
## Notes about Linux boot and device trees

<!-- TOC --><a name="linux-boot"></a>
### Linux boot
The /boot/extlinux/extlinux.conf contains the data for the Linux boot. 
A "JetsonIO" entry is added at first package installation, and is set as default one.

Here is an example from the Orin NX : 
<pre>
DEFAULT JetsonIO
[...]
LABEL JetsonIO
        MENU LABEL Custom Header Config: <CSI Exosens Cameras. CAM0:EC_1_lane> <CSI Exosens Cameras. CAM1:EC_1_lane>
        LINUX /boot/eg/Image
        FDT /boot/dtb/kernel_tegra234-p3768-0000+p3767-0000-nv.dtb
        INITRD /boot/initrd
        APPEND [...]
        OVERLAYS /boot/tegra234-p3767-camera-p3768-eg-cams-dione.dtbo,/boot/tegra234-p3767-camera-p3768-eg-cam0-ec-1-lane.dtbo
		[...]
</pre>

Description :
- LINUX line :
   - using the /boot/eg/Image is not mandatory for video streaming to be functional for 36.x L4T version
   - customer can add their own patches in the dedicated kernel source folder
   - consult the support team for more information
Note : for the *forecr* specicific board, L4T versions 36.x, the /boot/eg/Image is not used, because some modules need the original kernel. So an EG kernel patch about I2C timeout is missing. This impacts EngineCore cameras (MicroCube, SmartIR640, Crius1280) control protocole (doesn't manage correctly an error timeout) but doesn't impact video streaming.
- FDT line : native devicetree file
- OVERLAYS : list of overlay files to apply

<!-- TOC --><a name="orin-nxnano-devkit-devicetree-issue"></a>
### Orin NX/Nano devkit devicetree issue
There is a CSI diff pair swap on Jetson Orin Nano devkit :
https://nvidia-jetson.piveral.com/jetson-orin-nano/csi-diff-pair-polarity-swap-on-nvidia-jetson-orin-nano-dev-board/
<pre>
lane_polarity = "6"; 
</pre>
has been added in this devicetree overlay as a workaround for that issue : tegra234-p3767-camera-common-eg-cams-dione.dtsi

To port the devicetree on a custom carrier board embedding the Orin NX/Nano, this lane polarity parameter may have to be removed.


<!-- TOC --><a name="hints-to-help-integrating-the-drivers-on-other-l4t-versions-and-other-somcarrier-boards"></a>
## Hints to help integrating the drivers on other L4T versions and other SoM/carrier boards

Here are some informations about how to create MIPI drivers for a new L4T version and new SoM/carrier boards.
Basically, take example on the existing environment.

<!-- TOC --><a name="getting-the-l4t-archives-files"></a>
### Getting the L4T archives files

* First check the compatibility of the L4T_VERSION with the SoM target : https://developer.nvidia.com/embedded/jetson-linux-archive

* modify the *environment* file and add a new entry. For example the L4T version 36.4.4, generic (for all boards) and forecr (specific carrier board) : 
<pre>
36.4.4)
   case "$module" in
   generic|forecr)
      JETSON_PUBLIC_SOURCES=public_sources.tbz2
      JETSON_PUBLIC_SOURCES_URL=https://developer.nvidia.com/downloads/embedded/l4t/r36_release_v4.4/sources/${JETSON_PUBLIC_SOURCES}
      JETSON_TOOCHAIN_ARCHIVE=aarch64--glibc--stable-2022.08-1.tar.bz2
      JETSON_TOOCHAIN_ARCHIVE_URL=https://developer.nvidia.com/downloads/embedded/l4t/r36_release_v3.0/toolchain/$JETSON_TOOCHAIN_ARCHIVE
      TOOLCHAIN_DIR=aarch64--glibc--stable-2022.08-1
      TOOLCHAIN_PREFIX=$JETSON_DIR/$TOOLCHAIN_DIR/$TOOLCHAIN_DIR/bin/aarch64-buildroot-linux-gnu-
      L4T_RELEASE_PACKAGE=jetson_linux_r36.4.4_aarch64.tbz2
      L4T_RELEASE_PACKAGE_URL=https://developer.nvidia.com/downloads/embedded/l4t/r36_release_v4.4/release/${L4T_RELEASE_PACKAGE}
      SAMPLE_FS_PACKAGE=tegra_linux_sample-root-filesystem_r36.4.4_aarch64.tbz2
      SAMPLE_FS_PACKAGE_URL=https://developer.nvidia.com/downloads/embedded/l4t/r36_release_v4.4/release/${SAMPLE_FS_PACKAGE}
      ;;
   *)
      echo "Incorrect $module module"
      exit
      ;;
   esac
   ;;
</pre>

<!-- TOC --><a name="porting-kernel-patches-to-a-new-l4t-version"></a>
### Porting kernel patches to a new L4T version
The *source/$L4T_VERSION/Linux_for_Tegra* folder contains the customized files specific to a L4T version needed to build the MIPI drivers.

If the need is only to implement a new $L4T_VERSION_NEW version :
* create the *source/$L4T_VERSION_NEW/Linux_for_Tegra* folder, port and adapt the content from another *source/$L4T_VERSION/Linux_for_Tegra* folder
* create the *source/$L4T_VERSION_NEW_common/Linux_for_Tegra* folder with the correcponding links to hadware and nvidia-oot paths (in sources/common/source)

Note : the *l4t_copy_sources.sh* script is in charge of copying customized files to the original L4T build environment.

<!-- TOC --><a name="creating-camera-device-trees-for-a-new-som-carrier-board"></a>
### Creating camera device trees for a new SoM / carrier board

Device tree source files are in the *sources/common/source/hardware_36+/nvidia/t23x/nv-public/overlay* folder.
Let's say the SoM ID is tegra234-pXXXX :
* create the tegra234-pXXXX-camera-common-eg-cams-dione.dtsi, based on the native tegra234-pXXXX-camera dts files provided by Nvidia and tegra234-p3767-camera-common-eg-cams-dione.dtsi as an example
* based on tegra234-p3767-camera-p3768-eg-cam*.dts files, create all needed overlay files : tegra234-pXXX-camera-eg-cams-dione, tegra234-pXXX-camera-eg-cam0-ec-1-lane, tegra234-pXXX-camera-eg-cam0-ec-2-lanes, , tegra234-pXXX-camera-eg-cam1-ec-1-lane, tegra234-pXXX-camera-eg-cam1-ec-2-lanes, etc..
* add the tegra234-pXXX-camera-eg-cams-*.dtbo files in the corresponding Makefile : sources/36.x.x/Linux_for_Tegra/source/hardware/nvidia/t23x/nv-public/overlay/Makefile
* if the carrier board has specificities over native Nvidia carrier boards (for example a different cam_i2c_mux gpio), one specific tegra234-pXXX-camera-$SPECIFIC_BOARD-eg-cams-dione devicetree has to be created. For example : sources/common/source/hardware_36+/nvidia/t23x/nv-public/overlay/tegra234-p3767-camera-dsboard-ornxs-eg-cams-dione.dts

<!-- TOC --><a name="integrating-specific-vendor-filespatches"></a>
### Integrating specific vendor files/patches
Some carrier board vendors provide specific patches. They need to be imported from the *sources/$L4T_VERSION/Linux_for_Tegra_$SPECIFIC* folder.

For example, the "*./l4t_copy_sources.sh 36.4.3 forecr*" command uses *sources/36.4.3/Linux_for_Tegra* and *sources/36.4.3/Linux_for_Tegra_forecr*, which contains files collected from Forecr (https://github.com/forecr/forecr_xavier_kernel/tree/JetPack-6.2.1).

Note : the *l4t_copy_sources.sh* script only copies files. If the developer wants to apply patch files, the script needs to be modified.







