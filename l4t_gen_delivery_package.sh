#!/bin/bash

. environment $@

if [[ ! -d $JETSON_DIR ]]
then
   echo "Error : $JETSON_DIR folder doesn't exist"
   exit
fi

cd $JETSON_DIR

KERNEL_VERSION=$(ls $JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/rootfs/lib/modules/)
PACKAGE_NAME=jetson-l4t-${L4T_VERSION_EXTENDED}-eg-cams
sudo rm -rf ${PACKAGE_NAME}

INSTALL_DIR=${PACKAGE_NAME}/usr
mkdir -p $INSTALL_DIR/
sudo rsync -iahHAXxvz --progress $ROOT_DIR/sources/common/Linux_for_Tegra/rootfs/usr/ ${INSTALL_DIR}/

INSTALL_DIR=${PACKAGE_NAME}/etc
mkdir -p $INSTALL_DIR/
sudo rsync -iahHAXxvz --progress $JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/rootfs/etc/version_eg_cams ${INSTALL_DIR}/

INSTALL_DIR=${PACKAGE_NAME}/opt/eg
mkdir -p $INSTALL_DIR/
sudo rsync -iahHAXxvz --progress $ROOT_DIR/sources/common/Linux_for_Tegra/rootfs/opt/eg/ ${INSTALL_DIR}/

INSTALL_DIR=${PACKAGE_NAME}/opt/nvidia/jetson-io/
folder=$ROOT_DIR/sources/$L4T_VERSION/Linux_for_Tegra/rootfs/opt/nvidia/jetson-io/
if [[ -d $folder ]]
then
	mkdir -p $INSTALL_DIR/
	sudo rsync -iahHAXxvz --progress $ROOT_DIR/sources/$L4T_VERSION/Linux_for_Tegra/rootfs/opt/nvidia/jetson-io/ ${INSTALL_DIR}/
fi

INSTALL_DIR=${PACKAGE_NAME}/opt/nvidia/jetson-io/
folder=$ROOT_DIR/sources/$L4T_VERSION/Linux_for_Tegra_$2/rootfs/opt/nvidia/jetson-io/
if [[ -d $folder ]]
then
	mkdir -p $INSTALL_DIR/
	sudo rsync -iahHAXxvz --progress $ROOT_DIR/sources/$L4T_VERSION/Linux_for_Tegra_$2/rootfs/opt/nvidia/jetson-io/ ${INSTALL_DIR}/
fi

INSTALL_DIR=${PACKAGE_NAME}/boot/eg
mkdir -p $INSTALL_DIR		
sudo rsync -iahHAXxvz --progress $JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/rootfs/boot/eg/* ${INSTALL_DIR}/

file=$JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/rootfs/boot/*-eg-*.dtb*
ls $file
if [[ $? == 0 ]]
then
	INSTALL_DIR=${PACKAGE_NAME}/boot/
	sudo rsync -iahHAXxvz --progress $file ${INSTALL_DIR}/
fi

if [[ $L4T_VERSION_MAJOR < 36 ]]
then
	DRIVER_DIR=kernel/drivers/media/i2c
else
	DRIVER_DIR=updates/drivers/media/i2c
fi
INSTALL_DIR=${PACKAGE_NAME}/lib/modules/${KERNEL_VERSION}/${DRIVER_DIR}
file=$JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/rootfs/lib/modules/${KERNEL_VERSION}/${DRIVER_DIR}/dione_ir.ko
if [[ -f $file ]]
then
   mkdir -p $INSTALL_DIR
   sudo rsync -iahHAXxvz --progress $file ${INSTALL_DIR}/
fi
file=$JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/rootfs/lib/modules/${KERNEL_VERSION}/${DRIVER_DIR}/eg-ec-mipi.ko
if [[ -f $file ]]
then
   mkdir -p $INSTALL_DIR
   sudo rsync -iahHAXxvz --progress $file ${INSTALL_DIR}/
fi

file=$JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/rootfs/lib/modules/${KERNEL_VERSION}/${DRIVER_DIR}/nv_imx219.ko
if [[ -f $file ]]
then
   mkdir -p $INSTALL_DIR
   sudo rsync -iahHAXxvz --progress $file ${INSTALL_DIR}/
fi
file=$JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/rootfs/lib/modules/${KERNEL_VERSION}/${DRIVER_DIR}/nv_imx477.ko
if [[ -f $file ]]
then
   mkdir -p $INSTALL_DIR
   sudo rsync -iahHAXxvz --progress $file ${INSTALL_DIR}/
fi

DRIVER_DIR=updates/drivers/video/tegra/camera
INSTALL_DIR=${PACKAGE_NAME}/lib/modules/${KERNEL_VERSION}/${DRIVER_DIR}
file=$JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/rootfs/lib/modules/${KERNEL_VERSION}/${DRIVER_DIR}/tegra_camera_platform.ko
if [[ -f $file ]]
then
   mkdir -p $INSTALL_DIR
   sudo rsync -iahHAXxvz --progress $file ${INSTALL_DIR}/
fi

DRIVER_DIR=updates/drivers/media/platform/tegra/camera
INSTALL_DIR=${PACKAGE_NAME}/lib/modules/${KERNEL_VERSION}/${DRIVER_DIR}
file=$JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/rootfs/lib/modules/${KERNEL_VERSION}/${DRIVER_DIR}/tegra-camera.ko
if [[ -f $file ]]
then
   mkdir -p $INSTALL_DIR
   sudo rsync -iahHAXxvz --progress $file ${INSTALL_DIR}/
fi

DRIVER_DIR=updates/drivers/video/tegra/host/nvcsi
INSTALL_DIR=${PACKAGE_NAME}/lib/modules/${KERNEL_VERSION}/${DRIVER_DIR}
file=$JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/rootfs/lib/modules/${KERNEL_VERSION}/${DRIVER_DIR}/nvhost-nvcsi-t194.ko
if [[ -f $file ]]
then
   mkdir -p $INSTALL_DIR
   sudo rsync -iahHAXxvz --progress $file ${INSTALL_DIR}/
fi

# Validate the target before dpkg unpacks any camera files.
# FORCE_INSTALL_EG_CAMS is an installation-time override, not a build option.
rm -f /tmp/preinst
cat > /tmp/preinst <<EOT
#!/bin/bash
set -e
EXPECTED_L4T="${L4T_VERSION}"
EXPECTED_KERNEL_VERSION="${KERNEL_VERSION}"
EOT
cat >> /tmp/preinst <<'EOT'

case "$1" in
    install|upgrade)
        if [[ ! -f /etc/nv_tegra_release ]]; then
            echo "Error: /etc/nv_tegra_release not found." >&2
            exit 1
        fi
        NV_MAJOR=$(sed -n 's/.*# R\([0-9]*\) .*/\1/p' /etc/nv_tegra_release | head -1)
        NV_REVISION=$(sed -n 's/.*REVISION: \([0-9.]*\).*/\1/p' /etc/nv_tegra_release | head -1)
        if [[ -z "$NV_MAJOR" || -z "$NV_REVISION" ]]; then
            echo "Error: Could not parse L4T version from /etc/nv_tegra_release." >&2
            exit 1
        fi
        RUNNING_L4T="${NV_MAJOR}.${NV_REVISION}"
        if [[ -n "${FORCE_INSTALL_EG_CAMS:-}" ]]; then
            RUNNING_KERNEL=$(uname -r)
            if [[ "${RUNNING_KERNEL%-eg}" != "${EXPECTED_KERNEL_VERSION%-eg}" ]]; then
                echo "Error: Kernel version mismatch (FORCE_INSTALL_EG_CAMS set)." >&2
                echo "  Package kernel: ${EXPECTED_KERNEL_VERSION}" >&2
                echo "  Running kernel: ${RUNNING_KERNEL}" >&2
                exit 1
            fi
            echo "FORCE_INSTALL_EG_CAMS: accepting L4T ${RUNNING_L4T} with matching kernel ${RUNNING_KERNEL}."
        else
            NCOMP=$(echo "$EXPECTED_L4T" | awk -F'.' '{print NF}')
            RUNNING_L4T_CMP=$(echo "$RUNNING_L4T" | cut -d'.' -f1-${NCOMP})
            if [[ "$RUNNING_L4T_CMP" != "$EXPECTED_L4T" ]]; then
                echo "Error: Incompatible L4T version." >&2
                echo "  Package L4T: ${EXPECTED_L4T}" >&2
                echo "  Running L4T: ${RUNNING_L4T}" >&2
                exit 1
            fi
        fi
        ;;
esac
EOT

rm -f /tmp/postinst

tee -a /tmp/postinst > /dev/null <<EOT
depmod
grep DEFAULT /boot/extlinux/extlinux.conf | grep JetsonIO > /dev/null
if [ \$? -ne 0 ]
then
   python /opt/nvidia/jetson-io/config-by-hardware.py -n 2="Exosens Cameras"
fi
EOT

rm -f /tmp/postrm
tee -a /tmp/postrm > /dev/null <<EOT
depmod
EOT

if [[ x${3} = x ]]
then
   # Automatic tag version
   PACKAGE_VERSION="$GIT_TAG"
else
   # Manual version
   PACKAGE_VERSION="$3"
fi
echo PACKAGE_VERSION ${PACKAGE_VERSION}

# if fpm is not installed : https://fpm.readthedocs.io/en/v1.15.0/installation.html
fpm -v ${PACKAGE_VERSION} -C ${PACKAGE_NAME} \
   -a arm64 \
   -s dir \
   -t deb \
   -n ${PACKAGE_NAME} \
   --before-install /tmp/preinst \
   --after-install /tmp/postinst \
   --after-remove /tmp/postrm \
   --description "Xenics Exosens MIPI camera package" \
   .
