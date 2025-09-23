. environment $@

mkdir -p $JETSON_DIR

if [[ ! -d $ARCHIVE_DIR/$L4T_VERSION ]]
then
   mkdir -p $ARCHIVE_DIR/$L4T_VERSION
fi

#----------------------#
# Get the Nvidia SDK   #
#----------------------#
cd ${JETSON_DIR}

if [[ ! -f $ARCHIVE_DIR/$L4T_VERSION/${L4T_RELEASE_PACKAGE} ]]
then
   wget $L4T_RELEASE_PACKAGE_URL -O $ARCHIVE_DIR/$L4T_VERSION/${L4T_RELEASE_PACKAGE}
fi
if [[ ! -f $ARCHIVE_DIR/$L4T_VERSION/${SAMPLE_FS_PACKAGE} ]]
then
   wget $SAMPLE_FS_PACKAGE_URL -O $ARCHIVE_DIR/$L4T_VERSION/${SAMPLE_FS_PACKAGE}
fi
if [[ ! -f $ARCHIVE_DIR/$L4T_VERSION/${JETSON_PUBLIC_SOURCES} ]]
then
   wget $JETSON_PUBLIC_SOURCES_URL -O $ARCHIVE_DIR/$L4T_VERSION/${JETSON_PUBLIC_SOURCES}
fi
if [[ ! -d $LINUX_FOR_TEGRA_DIR ]]
then
   sudo rm -rf tmp_$LINUX_FOR_TEGRA_DIR
   mkdir tmp_$LINUX_FOR_TEGRA_DIR
   cd tmp_$LINUX_FOR_TEGRA_DIR
   tar xvf $ARCHIVE_DIR/$L4T_VERSION/${L4T_RELEASE_PACKAGE}
   sudo mv Linux_for_Tegra ../$LINUX_FOR_TEGRA_DIR
   cd ${JETSON_DIR}/${LINUX_FOR_TEGRA_DIR}/rootfs/
   sudo tar xpvf $ARCHIVE_DIR/$L4T_VERSION/${SAMPLE_FS_PACKAGE}
   cd ..
   sudo ./apply_binaries.sh
fi

# Get toolchain
cd $JETSON_DIR
if [[ ! -f $ARCHIVE_DIR/$L4T_VERSION/${JETSON_TOOCHAIN_ARCHIVE} ]]
then
   wget $JETSON_TOOCHAIN_ARCHIVE_URL -O $ARCHIVE_DIR/$L4T_VERSION/${JETSON_TOOCHAIN_ARCHIVE}
fi
if [[ ! -d $JETSON_DIR/$TOOLCHAIN_DIR ]]
then
   mkdir $JETSON_DIR/$TOOLCHAIN_DIR
   cd $JETSON_DIR/$TOOLCHAIN_DIR
   tar xvf $ARCHIVE_DIR/$L4T_VERSION/$JETSON_TOOCHAIN_ARCHIVE
fi

# Decompress Linux sources
cd $JETSON_DIR
sudo rm -rf tmp_$LINUX_FOR_TEGRA_DIR
mkdir tmp_$LINUX_FOR_TEGRA_DIR
cd tmp_$LINUX_FOR_TEGRA_DIR
tar xvf $ARCHIVE_DIR/$L4T_VERSION/${JETSON_PUBLIC_SOURCES}
rsync -iahHAXxvz --progress Linux_for_Tegra/* ../${LINUX_FOR_TEGRA_DIR}/

cd $ROOT_DIR
. environment $@
cd $L4T_SRC
mkdir build
mkdir modules

tar -xvf kernel_src.tbz2
if [[ -f kernel_oot_modules_src.tbz2 ]]
then
   tar -xvf kernel_oot_modules_src.tbz2
fi
if [[ -f nvidia_kernel_display_driver_source.tbz2 ]]
then
   tar -xvf nvidia_kernel_display_driver_source.tbz2
fi
#if [[ -f generic_rt_build.sh ]]
#then
#   ./generic_rt_build.sh "enable"
#fi

# Backup the original Linux_for_tegra folder
#if [[ ! -d $JETSON_DIR/Linux_for_Tegra.orig ]]
#then
#   sudo rsync -iahHAXxvz --progress $JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/ $JETSON_DIR/Linux_for_Tegra.orig
#fi

# Create de tegra_config file if it doesn't exist
#KERNEL_SRC_DIR=$(ls -d $L4T_SRC/kernel/kernel-*)
#if [ ! -f ${KERNEL_SRC_DIR}/arch/arm64/configs/tegra_defconfig ]
#then
#   ln -s defconfig ${KERNEL_SRC_DIR}/arch/arm64/configs/tegra_defconfig 
#fi

#************************************************************************
# Create local git repos for convenient source changes identification
#************************************************************************

cd $JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/
echo generate_capsule > .gitignore
echo nv_tegra >> .gitignore
echo nv_tools >> .gitignore
echo rootfs >> .gitignore
echo source >> .gitignore
echo kernel >> .gitignore
git init
git add * .gitignore
git commit -m "Initial state"

if [[ -d $L4T_SRC/kernel ]]
then
   cd $L4T_SRC/kernel
   echo *.o >> .gitignore
   echo *.cmd >> .gitignore
   echo *.ko >> .gitignore
   echo *.mod* >> .gitignore
   echo *.d >> .gitignore
   echo *.order >> .gitignore
   echo *.dtb* >> .gitignore
   echo *.a >> .gitignore
   echo *.cpio >> .gitignore
   echo Module.symvers >> .gitignore
   git init
   git add *
   git commit -m "Initial state"
fi

if [[ -d $L4T_SRC/hardware ]]
then
   cd $L4T_SRC/hardware
   git init
   git add *
   git commit -m "Initial state"
fi

if [[ -d $L4T_SRC/nvidia-oot ]]
then
   cd $L4T_SRC/nvidia-oot
   echo *.o >> .gitignore
   echo *.cmd >> .gitignore
   echo *.ko >> .gitignore
   echo *.mod* >> .gitignore
   echo *.d >> .gitignore
   echo *.order >> .gitignore
   echo *.dtb* >> .gitignore
   echo Module.symvers >> .gitignore
   git init
   git add *
   git commit -m "Initial state"
fi

#************************************************************************
# End of git repos
#************************************************************************

sudo rm -rf $JETSON_DIR/tmp_$LINUX_FOR_TEGRA_DIR

# At this step, the Jetson filesystem would be ready to be flashed if no modification has to be made to the Linux kernel.
# For example :
#sudo ./flash.sh jetson-xavier-nx-devkit-emmc mmcblk0p1

