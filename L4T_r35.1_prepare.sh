JETSON_DIR=$(pwd)

LINUX_FOR_TEGRA_DIR=Linux_for_Tegra
JETSON_PUBLIC_SOURCES=public_sources.tbz2
JETSON_TOOCHAIN_ARCHIVE=aarch64--glibc--stable-final.tar.gz
TOOLCHAIN_DIR=l4t-gcc
TOOLCHAIN_PREFIX=$JETSON_DIR/$TOOLCHAIN_DIR/bin/aarch64-buildroot-linux-gnu-

#----------------------#
# Get the Nvidia SDK   #
#----------------------#
cd ${JETSON_DIR}
L4T_RELEASE_PACKAGE=jetson_linux_r35.1.0_aarch64.tbz2
SAMPLE_FS_PACKAGE=tegra_linux_sample-root-filesystem_r35.1.0_aarch64.tbz2

if [[ ! -f ${L4T_RELEASE_PACKAGE} ]]
then
   wget https://developer.nvidia.com/embedded/l4t/r35_release_v1.0/release/${L4T_RELEASE_PACKAGE}
fi
if [[ ! -f ${SAMPLE_FS_PACKAGE} ]]
then
   wget https://developer.nvidia.com/embedded/l4t/r35_release_v1.0/release/${SAMPLE_FS_PACKAGE}
fi
if [[ ! -f ${JETSON_PUBLIC_SOURCES} ]]
then
   wget https://developer.nvidia.com/embedded/l4t/r35_release_v1.0/sources/${JETSON_PUBLIC_SOURCES}
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
   wget https://developer.nvidia.com/embedded/jetson-linux/bootlin-toolchain-gcc-93 -O ${JETSON_TOOCHAIN_ARCHIVE}
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
echo bootloader > .gitignore
echo kernel >> .gitignore
echo generate_capsule >> .gitignore
echo nv_tegra >> .gitignore
echo nv_tools >> .gitignore
echo rootfs >> .gitignore
echo source >> .gitignore
echo tools >> .gitignore
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

