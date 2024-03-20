#!/bin/bash

. environment $@

cd $JETSON_DIR

KERNEL_VERSION=$(ls $JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/rootfs/lib/modules/)
PACKAGE_NAME=eg_nvidia_l4t_${L4T_VERSION}
sudo rm -rf ${PACKAGE_NAME}*

INSTALL_DIR=${PACKAGE_NAME}/usr
mkdir -p $INSTALL_DIR/
sudo rsync -iahHAXxvz --progress $ROOT_DIR/sources/common/${LINUX_FOR_TEGRA_DIR}/rootfs/usr/ ${INSTALL_DIR}/

INSTALL_DIR=${PACKAGE_NAME}/etc
mkdir -p $INSTALL_DIR/
sudo rsync -iahHAXxvz --progress $JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/rootfs/etc/version_eg_cams ${INSTALL_DIR}/

INSTALL_DIR=${PACKAGE_NAME}/opt/eg
mkdir -p $INSTALL_DIR/
sudo rsync -iahHAXxvz --progress $ROOT_DIR/sources/common/${LINUX_FOR_TEGRA_DIR}/rootfs/opt/eg/ ${INSTALL_DIR}/

INSTALL_DIR=${PACKAGE_NAME}/boot/eg
mkdir -p $INSTALL_DIR
sudo rsync -iahHAXxvz --progress $JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/rootfs/boot/eg/* ${INSTALL_DIR}/

DRIVER_DIR=kernel/drivers/media/i2c
INSTALL_DIR=${PACKAGE_NAME}/lib/modules/${KERNEL_VERSION}/${DRIVER_DIR}
mkdir -p $INSTALL_DIR
file=$JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/rootfs/lib/modules/${KERNEL_VERSION}/${DRIVER_DIR}/dione_ir.ko
if [[ -f $file ]]
then
   sudo rsync -iahHAXxvz --progress $file ${INSTALL_DIR}/
fi
file=$JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/rootfs/lib/modules/${KERNEL_VERSION}/${DRIVER_DIR}/eg-ec-mipi.ko
if [[ -f $file ]]
then
   sudo rsync -iahHAXxvz --progress $file ${INSTALL_DIR}/
fi

rm -f /tmp/postinst
tee -a /tmp/postinst > /dev/null <<EOT
depmod
EOT
rm -f /tmp/postrm
tee -a /tmp/postrm > /dev/null <<EOT
depmod
EOT

if [[ x${2} = x ]]
then
	PACKAGE_VERSION="$GIT_VERSION"
else
	PACKAGE_VERSION="$2"
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
