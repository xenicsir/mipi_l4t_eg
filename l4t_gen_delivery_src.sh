#!/bin/bash
. environment $@

if [[ x${3} = x ]]
then
   # Automatic tag version
   PACKAGE_VERSION="$GIT_TAG"
else
   # Manual version
   PACKAGE_VERSION="$3"
fi
echo PACKAGE_VERSION ${PACKAGE_VERSION}

PACKAGE_DIR=jetson-l4t-${L4T_VERSION_EXTENDED}-eg-cams-src
echo PACKAGE_DIR ${PACKAGE_DIR}

sudo rm -rf ${JETSON_DIR}/${PACKAGE_DIR}
mkdir -p ${JETSON_DIR}/${PACKAGE_DIR}/Linux_for_Tegra

sudo rsync -iahHAXxvz --progress $ROOT_DIR/sources/common/Linux_for_Tegra/ ${JETSON_DIR}/${PACKAGE_DIR}/Linux_for_Tegra/
sudo rsync -iahHAXxvz --progress $ROOT_DIR/sources/$L4T_VERSION/Linux_for_Tegra/ ${JETSON_DIR}/${PACKAGE_DIR}/Linux_for_Tegra/
if [[ x$2 != x ]]
then
   if [[ -d sources/${L4T_VERSION}/$LINUX_FOR_TEGRA_DIR ]]
   then
      sudo rsync -iahHAXxvz --progress sources/${L4T_VERSION}/$LINUX_FOR_TEGRA_DIR/ ${JETSON_DIR}/${PACKAGE_DIR}/Linux_for_Tegra/
   fi
fi
cd ${JETSON_DIR}/${PACKAGE_DIR}
tar cvzf Linux_for_Tegra.tar.gz Linux_for_Tegra
sudo rm -rf Linux_for_Tegra

echo "Usage :" > ${JETSON_DIR}/${PACKAGE_DIR}/README.txt
echo >> ${JETSON_DIR}/${PACKAGE_DIR}/README.txt
echo "Merge sources from Linux_for_Tegra.tar.gz to Nvidia Linux_for_Tegra folder" >> ${JETSON_DIR}/${PACKAGE_DIR}/README.txt

exit

cd ${JETSON_DIR}
tar cvzf ${PACKAGE_DIR}.tar.gz ${PACKAGE_DIR}

PACKAGE_DIR=eg_nvidia_l4t_${L4T_VERSION_EXTENDED}_${PACKAGE_VERSION}_patch
echo PACKAGE_DIR ${PACKAGE_DIR}

sudo rm -rf ${JETSON_DIR}/${PACKAGE_DIR}
mkdir -p ${JETSON_DIR}/${PACKAGE_DIR}

cd ${JETSON_DIR}/${LINUX_FOR_TEGRA_DIR}/source/public/kernel
git ls-files -o --exclude-standard --full-name --exclude "cscope.*" | xargs git add -N
git diff > ${JETSON_DIR}/${PACKAGE_DIR}/kernel.patch

cd ${JETSON_DIR}/${LINUX_FOR_TEGRA_DIR}/source/public/hardware
git ls-files -o --exclude-standard --full-name --exclude "cscope.*" | xargs git add -N
git diff > ${JETSON_DIR}/${PACKAGE_DIR}/device_tree.patch

echo "Usage :" > ${JETSON_DIR}/${PACKAGE_DIR}/README.txt
echo >> ${JETSON_DIR}/${PACKAGE_DIR}/README.txt
echo "Apply patches :" >> ${JETSON_DIR}/${PACKAGE_DIR}/README.txt
echo "Kernel patch in Linux_for_Tegra/source/public/kernel" >> ${JETSON_DIR}/${PACKAGE_DIR}/README.txt
echo "patch -p1 < kernel.patch" >> ${JETSON_DIR}/${PACKAGE_DIR}/README.txt
echo "Device Tree patch in Linux_for_Tegra/source/public/hardware" >> ${JETSON_DIR}/${PACKAGE_DIR}/README.txt
echo "patch -p1 < device_tree.patch" >> ${JETSON_DIR}/${PACKAGE_DIR}/README.txt

cd ${JETSON_DIR}
tar cvzf ${PACKAGE_DIR}.tar.gz ${PACKAGE_DIR}