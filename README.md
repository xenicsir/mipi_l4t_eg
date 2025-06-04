# Exosens cameras MIPI CSI-2 driver for NVIDIA Jetson boards

This document describes how to build and install the MIPI drivers for different Jetson SOM (System On Module) and carrier boards, based on Nvidia BSP (L4T, Linux For Tegra).

It also gives some hints to help integrating the drivers on other L4T versions and other carrier boards.

The MIPI_deployment.xlsx sheet presents an overview of the supported cameras/SOM/carrier boards/L4T versions.

## Prerequisites for cross-compiling

### Host PC

* Recommended OS is Ubuntu 20.04 LTS or Ubuntu 22.04 LTS
* Git is needed to clone this repository

## Building and installing MIPI drivers on supported SOM / carrier boards

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






