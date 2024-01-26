#!/bin/bash

if [[ x$1 == x ]]
then
   Please specify the target configuration. E.g. jetson-xavier-nx-devkit-dione
   exit
fi

JETSON_DIR=$(pwd)
LINUX_FOR_TEGRA_DIR=Linux_for_Tegra

pushd ${JETSON_DIR}/${LINUX_FOR_TEGRA_DIR}
sudo ./flash.sh --no-flash $1 mmcblk0p1
sudo mv ${JETSON_DIR}/${LINUX_FOR_TEGRA_DIR}/bootloader/system.img $JETSON_DIR
sudo mv ${JETSON_DIR}/${LINUX_FOR_TEGRA_DIR}/rootfs ${JETSON_DIR}/${LINUX_FOR_TEGRA_DIR}/source $JETSON_DIR
mkdir rootfs
popd
tar --exclude=".git" -czvf ${LINUX_FOR_TEGRA_DIR}_$1.tar.gz ${LINUX_FOR_TEGRA_DIR}

sudo mv $JETSON_DIR/system.img ${JETSON_DIR}/${LINUX_FOR_TEGRA_DIR}/bootloader/
sudo mv $JETSON_DIR/rootfs source ${JETSON_DIR}/${LINUX_FOR_TEGRA_DIR}/

# To flash it to the board :
#tar xvf Linux_for_Tegra.tar.gz
#cd Linux_for_Tegra
#sudo ./bootloader/mksparse  -v --fillpattern=0 bootloader/system.img.raw bootloader/system.img
#sudo NO_ROOTFS=1 NO_RECOVERY_IMG=1 ./flash.sh -r --no-systemimg jetson-xavier-nx-devkit-emmc-dione mmcblk0p1
