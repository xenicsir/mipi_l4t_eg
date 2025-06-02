# l4t_prepare.sh script must have been executed before
. environment $@

if [[ ! -d $L4T_SRC ]]
then
   echo "Error : $L4T_SRC folder doesn't exist"
   exit
fi

mkdir -p $L4T_VERSION

sudo mkdir -p $JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/rootfs/boot/eg

pushd $L4T_SRC
TEGRA_KERNEL_OUT=$L4T_SRC/build
KERNEL_MODULES_OUT=$L4T_SRC/modules
KERNEL_SOURCES=kernel/kernel-*

# TODO if version L4T < 36
#make -C $KERNEL_SOURCES ARCH=arm64 O=$TEGRA_KERNEL_OUT LOCALVERSION=-tegra CROSS_COMPILE=${TOOLCHAIN_PREFIX} tegra_defconfig
#make -C $KERNEL_SOURCES ARCH=arm64 O=$TEGRA_KERNEL_OUT LOCALVERSION=-tegra CROSS_COMPILE=${TOOLCHAIN_PREFIX} -j8 Image
#make -C $KERNEL_SOURCES ARCH=arm64 O=$TEGRA_KERNEL_OUT LOCALVERSION=-tegra CROSS_COMPILE=${TOOLCHAIN_PREFIX} -j8 dtbs
#make -C $KERNEL_SOURCES ARCH=arm64 O=$TEGRA_KERNEL_OUT LOCALVERSION=-tegra CROSS_COMPILE=${TOOLCHAIN_PREFIX} -j8 modules
#make -C $KERNEL_SOURCES ARCH=arm64 O=$TEGRA_KERNEL_OUT modules_install INSTALL_MOD_PATH=$KERNEL_MODULES_OUT

# Copy device tree to destination dir
#sudo cp -fv $KERNEL_HEADERS/arch/arm64/boot/dts/nvidia/*-eg*.dtb* $JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/rootfs/boot/eg
# Copy modules to destination dir

#else

export CROSS_COMPILE=${TOOLCHAIN_PREFIX}
export KERNEL_HEADERS=$L4T_SRC/$KERNEL_SOURCES
#export KERNEL_OUTPUT=$TEGRA_KERNEL_OUT
export INSTALL_MOD_PATH=$JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/rootfs
##export INSTALL_MOD_PATH=$KERNEL_MODULES_OUT
make -C kernel
sudo -E make install -C kernel
##export IGNORE_PREEMPT_RT_PRESENCE=1
make modules
sudo -E make modules_install
make dtbs
#exit
# Copy device tree to destination dir
sudo cp -fv $L4T_SRC/kernel-devicetree/generic-dts/dtbs/*-eg*.dtb* $JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/rootfs/boot/

#fi

popd


# Copy kernel Image to destination dir
pushd $JETSON_DIR/${LINUX_FOR_TEGRA_DIR}
cp -rfv $KERNEL_HEADERS/arch/arm64/boot/Image kernel/
sudo cp -rfv $KERNEL_HEADERS/arch/arm64/boot/Image rootfs/boot/eg

echo jetson-l4t-${L4T_VERSION_EXTENDED}_eg-${GIT_TAG}-${GIT_COMMIT} > version_eg_cams
sudo mv version_eg_cams $JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/rootfs/etc/

if [[ -f ./tools/l4t_update_initrd.sh ]]
then
   sudo ./tools/l4t_update_initrd.sh
fi

#-----------------------------#
# Flash to the Jetson board   #
#-----------------------------#
# For examples :
#sudo ./flash.sh jetson-xavier-nx-devkit-emmc-dione mmcblk0p1
#sudo ./flash.sh jetson-agx-orin-devkit mmcblk0p1
