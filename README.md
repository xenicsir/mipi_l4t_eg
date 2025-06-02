# Exosens cameras MIPI CSI-2 driver for NVIDIA Jetson boards

This document describes how to build and install the MIPI drivers for different Jetson SOM (System On Module) and carrier boards, based on Nvidia BSP (L4T, Linux For Tegra).

It also gives some hints to help integrating the drivers on other L4T versions and other carrier boards.

The MIPI_deployment.xlsx sheet presents an overview of the supported cameras/SOM/carrier boards/L4T versions.

## Prerequisites for cross-compiling

### Host PC

* Recommended OS is Ubuntu 20.04 LTS or Ubuntu 22.04 LTS
* Git is needed to clone this repository

## Building and installing MIPI drivers on supported SOM / carrier boards

### Jetson Orin NX 16 GB / Waveshare devkit
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







