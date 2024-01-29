# L4T_r35.1_prepare.sh script must have been executed before
. environment $@
mkdir -p $L4T_VERSION
pushd $L4T_VERSION

pushd $JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/source/public
JETSON_KERNEL_SOURCES=$(pwd)
TEGRA_KERNEL_OUT=$JETSON_KERNEL_SOURCES/build
KERNEL_MODULES_OUT=$JETSON_KERNEL_SOURCES/modules
KERNEL_SOURCES=kernel/kernel-*
make -C $KERNEL_SOURCES ARCH=arm64 O=$TEGRA_KERNEL_OUT LOCALVERSION=-tegra CROSS_COMPILE=${TOOLCHAIN_PREFIX} tegra_defconfig
make -C $KERNEL_SOURCES ARCH=arm64 O=$TEGRA_KERNEL_OUT LOCALVERSION=-tegra CROSS_COMPILE=${TOOLCHAIN_PREFIX} -j8 Image
make -C $KERNEL_SOURCES ARCH=arm64 O=$TEGRA_KERNEL_OUT LOCALVERSION=-tegra CROSS_COMPILE=${TOOLCHAIN_PREFIX} -j8 dtbs
make -C $KERNEL_SOURCES ARCH=arm64 O=$TEGRA_KERNEL_OUT LOCALVERSION=-tegra CROSS_COMPILE=${TOOLCHAIN_PREFIX} -j8 modules
make -C $KERNEL_SOURCES ARCH=arm64 O=$TEGRA_KERNEL_OUT modules_install INSTALL_MOD_PATH=$KERNEL_MODULES_OUT
popd

# Copy kernel Image to destination dir
pushd $JETSON_DIR/${LINUX_FOR_TEGRA_DIR}
cp -rfv $JETSON_KERNEL_SOURCES/build/arch/arm64/boot/Image kernel/
# Copy device tree to destination dir
cp -fv $JETSON_KERNEL_SOURCES/build/arch/arm64/boot/dts/* kernel/dtb/
cp -fv $JETSON_KERNEL_SOURCES/build/arch/arm64/boot/dts/nvidia/* kernel/dtb/
# Copy modules to destination dir
sudo rsync -iahHAXxvz --progress $JETSON_KERNEL_SOURCES/modules/lib/modules/ rootfs/lib/modules

#-----------------------------#
# Flash to the Jetson board   #
#-----------------------------#
# For example :
#sudo ./flash.sh jetson-xavier-nx-devkit-emmc-dione mmcblk0p1
