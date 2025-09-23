#!/bin/bash

. environment $@

if [[ ! -d $JETSON_DIR ]]
then
   echo "Error : $JETSON_DIR folder doesn't exist"
   exit
fi

cd $JETSON_DIR

KERNEL_VERSION=$(ls $JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/rootfs/lib/modules/)
PACKAGE_NAME=jetson-l4t-${L4T_VERSION_EXTENDED}-eg-cams
sudo rm -rf ${PACKAGE_NAME}

INSTALL_DIR=${PACKAGE_NAME}/usr
mkdir -p $INSTALL_DIR/
sudo rsync -iahHAXxvz --progress $ROOT_DIR/sources/common/Linux_for_Tegra/rootfs/usr/ ${INSTALL_DIR}/

INSTALL_DIR=${PACKAGE_NAME}/etc
mkdir -p $INSTALL_DIR/
sudo rsync -iahHAXxvz --progress $JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/rootfs/etc/version_eg_cams ${INSTALL_DIR}/

INSTALL_DIR=${PACKAGE_NAME}/opt/eg
mkdir -p $INSTALL_DIR/
sudo rsync -iahHAXxvz --progress $ROOT_DIR/sources/common/Linux_for_Tegra/rootfs/opt/eg/ ${INSTALL_DIR}/

INSTALL_DIR=${PACKAGE_NAME}/opt/nvidia
folder=$ROOT_DIR/sources/$L4T_VERSION/Linux_for_Tegra/rootfs/opt/nvidia/
if [[ -d $folder ]]
then
	mkdir -p $INSTALL_DIR/
	sudo rsync -iahHAXxvz --progress $ROOT_DIR/sources/$L4T_VERSION/Linux_for_Tegra/rootfs/opt/nvidia/ ${INSTALL_DIR}/
fi

INSTALL_DIR=${PACKAGE_NAME}/boot/eg
mkdir -p $INSTALL_DIR		
sudo rsync -iahHAXxvz --progress $JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/rootfs/boot/eg/* ${INSTALL_DIR}/

file=$JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/rootfs/boot/*-eg-*.dtb*
ls $file
if [[ $? == 0 ]]
then
	INSTALL_DIR=${PACKAGE_NAME}/boot/
	sudo rsync -iahHAXxvz --progress $file ${INSTALL_DIR}/
fi

if [[ $L4T_VERSION_MAJOR < 36 ]]
then
	DRIVER_DIR=kernel/drivers/media/i2c
else
	DRIVER_DIR=updates/drivers/media/i2c
fi
INSTALL_DIR=${PACKAGE_NAME}/lib/modules/${KERNEL_VERSION}/${DRIVER_DIR}
file=$JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/rootfs/lib/modules/${KERNEL_VERSION}/${DRIVER_DIR}/dione_ir.ko
if [[ -f $file ]]
then
   mkdir -p $INSTALL_DIR
   sudo rsync -iahHAXxvz --progress $file ${INSTALL_DIR}/
fi
file=$JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/rootfs/lib/modules/${KERNEL_VERSION}/${DRIVER_DIR}/eg-ec-mipi.ko
if [[ -f $file ]]
then
   mkdir -p $INSTALL_DIR
   sudo rsync -iahHAXxvz --progress $file ${INSTALL_DIR}/
fi

file=$JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/rootfs/lib/modules/${KERNEL_VERSION}/${DRIVER_DIR}/nv_imx219.ko
if [[ -f $file ]]
then
   mkdir -p $INSTALL_DIR
   sudo rsync -iahHAXxvz --progress $file ${INSTALL_DIR}/
fi
file=$JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/rootfs/lib/modules/${KERNEL_VERSION}/${DRIVER_DIR}/nv_imx477.ko
if [[ -f $file ]]
then
   mkdir -p $INSTALL_DIR
   sudo rsync -iahHAXxvz --progress $file ${INSTALL_DIR}/
fi

DRIVER_DIR=updates/drivers/video/tegra/camera
INSTALL_DIR=${PACKAGE_NAME}/lib/modules/${KERNEL_VERSION}/${DRIVER_DIR}
file=$JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/rootfs/lib/modules/${KERNEL_VERSION}/${DRIVER_DIR}/tegra_camera_platform.ko
if [[ -f $file ]]
then
   mkdir -p $INSTALL_DIR
   sudo rsync -iahHAXxvz --progress $file ${INSTALL_DIR}/
fi

DRIVER_DIR=updates/drivers/media/platform/tegra/camera
INSTALL_DIR=${PACKAGE_NAME}/lib/modules/${KERNEL_VERSION}/${DRIVER_DIR}
file=$JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/rootfs/lib/modules/${KERNEL_VERSION}/${DRIVER_DIR}/tegra-camera.ko
if [[ -f $file ]]
then
   mkdir -p $INSTALL_DIR
   sudo rsync -iahHAXxvz --progress $file ${INSTALL_DIR}/
fi

DRIVER_DIR=updates/drivers/video/tegra/host/nvcsi
INSTALL_DIR=${PACKAGE_NAME}/lib/modules/${KERNEL_VERSION}/${DRIVER_DIR}
file=$JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/rootfs/lib/modules/${KERNEL_VERSION}/${DRIVER_DIR}/nvhost-nvcsi-t194.ko
if [[ -f $file ]]
then
   mkdir -p $INSTALL_DIR
   sudo rsync -iahHAXxvz --progress $file ${INSTALL_DIR}/
fi

rm -f /tmp/postinst

tee -a /tmp/postinst > /dev/null <<EOT
depmod
grep DEFAULT /boot/extlinux/extlinux.conf | grep JetsonIO > /dev/null
if [ \$? -ne 0 ]
then
   python /opt/nvidia/jetson-io/config-by-hardware.py -n 2="Exosens Cameras"
fi
EOT

rm -f /tmp/postrm
tee -a /tmp/postrm > /dev/null <<EOT
depmod
EOT

if [[ x${3} = x ]]
then
   # Automatic tag version
   PACKAGE_VERSION="$GIT_TAG"
else
   # Manual version
   PACKAGE_VERSION="$3"
fi
echo PACKAGE_VERSION ${PACKAGE_VERSION}

# if fpm is not installed : https://fpm.readthedocs.io/en/v1.15.0/installation.html
fpm -v ${PACKAGE_VERSION} -C ${PACKAGE_NAME} \
   -a arm64 \
   -s dir \
   -t deb \
   -n ${PACKAGE_NAME} \
   --after-install /tmp/postinst \
   --after-remove /tmp/postrm \
   --description "Xenics Exosens MIPI camera package" \
   .
