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

sudo rm -rf $JETSON_DIR/tmp_$LINUX_FOR_TEGRA_DIR

# At this step, the Jetson filesystem would be ready to be flashed if no modification has to be made to the Linux kernel.
# For example :
#sudo ./flash.sh jetson-xavier-nx-devkit-emmc mmcblk0p1

