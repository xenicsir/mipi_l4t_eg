. environment $@
mkdir -p $L4T_VERSION
pushd $L4T_VERSION

#----------------------#
# Get the Nvidia SDK   #
#----------------------#
cd ${JETSON_DIR}

if [[ ! -f ${L4T_RELEASE_PACKAGE} ]]
then
   wget $L4T_RELEASE_PACKAGE_URL
fi
if [[ ! -f ${SAMPLE_FS_PACKAGE} ]]
then
   wget $SAMPLE_FS_PACKAGE_URL
fi
if [[ ! -f ${JETSON_PUBLIC_SOURCES} ]]
then
   wget $JETSON_PUBLIC_SOURCES_URL
fi
if [[ ! -d $LINUX_FOR_TEGRA_DIR ]]
then
   tar xvf ${L4T_RELEASE_PACKAGE}
   cd ${JETSON_DIR}/${LINUX_FOR_TEGRA_DIR}/rootfs/
   sudo tar xpvf ../../${SAMPLE_FS_PACKAGE}
   cd ..
   sudo ./apply_binaries.sh
fi

# Get toolchain
if [[ ! -f ${JETSON_TOOCHAIN_ARCHIVE} ]]
then
   cd $JETSON_DIR
   wget $JETSON_TOOCHAIN_ARCHIVE_URL -O ${JETSON_TOOCHAIN_ARCHIVE}
fi
if [[ ! -d $JETSON_DIR/$TOOLCHAIN_DIR ]]
then
   mkdir $JETSON_DIR/$TOOLCHAIN_DIR
   cd $JETSON_DIR/$TOOLCHAIN_DIR
   tar xvf ../$JETSON_TOOCHAIN_ARCHIVE
fi

# Decompress Linux sources
cd $JETSON_DIR
tar xvf ${JETSON_PUBLIC_SOURCES}
cd $JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/source/public
mkdir build
mkdir modules
tar -xvf kernel_src.tbz2

cd $JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/
echo generate_capsule > .gitignore
echo nv_tegra >> .gitignore
echo nv_tools >> .gitignore
echo rootfs >> .gitignore
echo source >> .gitignore
git init
git add * .gitignore
git commit -m "Initial state"
cd $JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/source/public/kernel
git init
git add *
git commit -m "Initial state"
cd $JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/source/public/hardware
git init
git add *
git commit -m "Initial state"


# At this step, the Jetson filesystem would be ready to be flashed if no modification has to be made to the Linux kernel.
# For example :
#sudo ./flash.sh jetson-xavier-nx-devkit-emmc mmcblk0p1

