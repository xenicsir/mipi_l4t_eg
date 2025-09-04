# l4t_prepare.sh script must have been executed before
. environment $@

if [[ ! -d $L4T_SRC ]]
then
   echo "Error : $L4T_SRC folder doesn't exist"
   exit
fi

sudo mkdir -p $JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/rootfs/boot/eg

KERNEL_SOURCES=kernel/kernel-*

if [[ $L4T_VERSION_MAJOR < 36 ]]
then

	TEGRA_KERNEL_OUT=$L4T_SRC/build
	KERNEL_MODULES_OUT=$L4T_SRC/modules

	pushd $L4T_SRC
	make -C $KERNEL_SOURCES ARCH=arm64 O=$TEGRA_KERNEL_OUT LOCALVERSION=-tegra CROSS_COMPILE=${TOOLCHAIN_PREFIX} tegra_defconfig
	make -C $KERNEL_SOURCES ARCH=arm64 O=$TEGRA_KERNEL_OUT LOCALVERSION=-tegra CROSS_COMPILE=${TOOLCHAIN_PREFIX} -j8 Image
	make -C $KERNEL_SOURCES ARCH=arm64 O=$TEGRA_KERNEL_OUT LOCALVERSION=-tegra CROSS_COMPILE=${TOOLCHAIN_PREFIX} -j8 dtbs
	make -C $KERNEL_SOURCES ARCH=arm64 O=$TEGRA_KERNEL_OUT LOCALVERSION=-tegra CROSS_COMPILE=${TOOLCHAIN_PREFIX} -j8 modules
	make -C $KERNEL_SOURCES ARCH=arm64 O=$TEGRA_KERNEL_OUT modules_install INSTALL_MOD_PATH=$KERNEL_MODULES_OUT
	popd

	# Copy device tree to destination dir
	cp -fv $L4T_SRC/build/arch/arm64/boot/dts/* $JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/kernel/dtb/
	cp -fv $L4T_SRC/build/arch/arm64/boot/dts/nvidia/* $JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/kernel/dtb/
if [[ $L4T_VERSION_MAJOR < 34 ]]
then
	sudo cp -fv $L4T_SRC/build/arch/arm64/boot/dts/*-eg-*.dtb* $JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/rootfs/boot/eg
	sudo cp -fv $L4T_SRC/build/arch/arm64/boot/dts/nvidia/*-eg-*.dtb* $JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/rootfs/boot/eg
else
	sudo cp -fv $L4T_SRC/build/arch/arm64/boot/dts/*-eg-*.dtb* $JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/rootfs/boot/
	sudo cp -fv $L4T_SRC/build/arch/arm64/boot/dts/nvidia/*-eg-*.dtb* $JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/rootfs/boot
fi
	# Copy modules to destination dir
	sudo rsync --exclude nvgpu.ko -iahHAXxvz --progress $L4T_SRC/modules/lib/modules/ $JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/rootfs/lib/modules

else

	TEGRA_KERNEL_OUT=$L4T_SRC/$KERNEL_SOURCES

	pushd $L4T_SRC
	export CROSS_COMPILE=${TOOLCHAIN_PREFIX}
	export KERNEL_HEADERS=$TEGRA_KERNEL_OUT
	export INSTALL_MOD_PATH=$JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/rootfs
	make -C kernel
	sudo -E make install -C kernel
	##export IGNORE_PREEMPT_RT_PRESENCE=1
	make modules
	sudo -E make modules_install
	make dtbs
	popd
	
	# Copy device tree to destination dir
	sudo cp -fv $L4T_SRC/kernel-devicetree/generic-dts/dtbs/*-eg-*.dtb* $JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/rootfs/boot/

fi

# Copy kernel Image to destination dir
cp -rfv $TEGRA_KERNEL_OUT/arch/arm64/boot/Image $JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/kernel/
sudo cp -rfv $TEGRA_KERNEL_OUT/arch/arm64/boot/Image $JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/rootfs/boot/eg
# Copy kernel Image to destination dir

echo jetson-l4t-${L4T_VERSION_EXTENDED}_eg-${GIT_TAG}-${GIT_COMMIT} > version_eg_cams
sudo mv version_eg_cams $JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/rootfs/etc/

pushd $JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/
if [[ -f ./tools/l4t_update_initrd.sh ]]
then
   sudo ./tools/l4t_update_initrd.sh
fi
popd

#-----------------------------#
# Flash to the Jetson board   #
#-----------------------------#
# For examples :
#sudo ./flash.sh jetson-xavier-nx-devkit-emmc-dione mmcblk0p1
#sudo ./flash.sh jetson-agx-orin-devkit mmcblk0p1
