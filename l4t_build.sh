# L4T_r35.1_prepare.sh script must have been executed before
. environment $@

if [[ ! -d $JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/source/public ]]
then
   echo "Error : $JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/source/public folder doesn't exist"
   exit
fi

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
#exit

# Copy kernel Image to destination dir
pushd $JETSON_DIR/${LINUX_FOR_TEGRA_DIR}
sudo mkdir -p rootfs/boot/eg
cp -rfv $JETSON_KERNEL_SOURCES/build/arch/arm64/boot/Image kernel/
sudo cp -rfv $JETSON_KERNEL_SOURCES/build/arch/arm64/boot/Image rootfs/boot/eg
# Copy device tree to destination dir
cp -fv $JETSON_KERNEL_SOURCES/build/arch/arm64/boot/dts/* kernel/dtb/
cp -fv $JETSON_KERNEL_SOURCES/build/arch/arm64/boot/dts/nvidia/* kernel/dtb/
sudo cp -fv $JETSON_KERNEL_SOURCES/build/arch/arm64/boot/dts/nvidia/*-eg*.dtb* rootfs/boot/eg
# Copy modules to destination dir
sudo rsync --exclude nvgpu.ko -iahHAXxvz --progress $JETSON_KERNEL_SOURCES/modules/lib/modules/ rootfs/lib/modules

echo jetson-l4t-${L4T_VERSION_EXTENDED}_eg-${GIT_TAG}-${GIT_COMMIT} > version_eg_cams
sudo mv version_eg_cams $JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/rootfs/etc/

#-----------------------------#
# Flash to the Jetson board   #
#-----------------------------#
# For examples :
#sudo ./flash.sh jetson-xavier-nx-devkit-emmc-dione mmcblk0p1
#sudo ./flash.sh jetson-agx-orin-devkit mmcblk0p1
