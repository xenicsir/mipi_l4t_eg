#!/bin/bash
#******************************************************************************
# l4t_gen_delivery_package.sh - Generate Debian package for Exosens cameras
#
# Usage:
#   ./l4t_gen_delivery_package.sh $L4T_VERSION [carrier_board] [package_version]
#
# Examples:
#   ./l4t_gen_delivery_package.sh 36.4.3
#   ./l4t_gen_delivery_package.sh 36.4.3 forecr
#   ./l4t_gen_delivery_package.sh 36.4.3 generic 2.0.0
#******************************************************************************

. environment $@

if [[ ! -d $JETSON_DIR ]]; then
   echo "Error : $JETSON_DIR folder doesn't exist"
   exit 1
fi

cd $JETSON_DIR

#******************************************************************************
# Configuration
#******************************************************************************
KERNEL_VERSION=$(ls $JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/rootfs/lib/modules/)
PACKAGE_NAME=jetson-l4t-${L4T_VERSION_EXTENDED}-eg-cams
ROOTFS_DIR=$JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/rootfs

# Clean previous package
sudo rm -rf ${PACKAGE_NAME}

echo "============================================"
echo "Generating package: ${PACKAGE_NAME}"
echo "  Kernel version: ${KERNEL_VERSION}"
echo "============================================"

#******************************************************************************
# Function: Copy from sources directory to package
# Automatically handles common/, $VERSION/, and $VERSION/$CARRIER_DIR/
#******************************************************************************
copy_from_sources() {
   local src_subpath="$1"    # e.g., "rootfs/usr" or "rootfs/opt/eg"
   local dest_subpath="$2"   # e.g., "usr" or "opt/eg"

   local dest_dir="${PACKAGE_NAME}/${dest_subpath}"
   mkdir -p "$dest_dir"

   # Copy from common/
   local src="$ROOT_DIR/sources/common/Linux_for_Tegra/${src_subpath}"
   if [[ -d "$src" ]]; then
      echo "  Copying ${src_subpath} from common/"
      sudo rsync -a --links "$src/" "$dest_dir/"
   fi

   # Copy from $VERSION/ (overrides common)
   src="$ROOT_DIR/sources/$L4T_VERSION/Linux_for_Tegra/${src_subpath}"
   if [[ -d "$src" ]]; then
      echo "  Copying ${src_subpath} from $L4T_VERSION/"
      sudo rsync -a --links "$src/" "$dest_dir/"
   fi

   # Copy from $VERSION/$CARRIER_DIR/ (overrides version-specific)
   if [[ -n "$CARRIER_BOARD" ]]; then
      src="$ROOT_DIR/sources/$L4T_VERSION/Linux_for_Tegra_${CARRIER_BOARD}/${src_subpath}"
      if [[ -d "$src" ]]; then
         echo "  Copying ${src_subpath} from $L4T_VERSION/$CARRIER_BOARD/"
         sudo rsync -a --links "$src/" "$dest_dir/"
      fi
   fi
}

#******************************************************************************
# Function: Copy file from build rootfs to package
#******************************************************************************
copy_from_rootfs() {
   local src_path="$1"       # Path relative to rootfs/
   local dest_subpath="$2"   # Destination in package

   local src="$ROOTFS_DIR/$src_path"
   local dest_dir="${PACKAGE_NAME}/${dest_subpath}"

   if [[ -e "$src" ]]; then
      mkdir -p "$dest_dir"
      sudo rsync -a --links "$src" "$dest_dir/"
      return 0
   fi
   return 1
}

#******************************************************************************
# Function: Copy kernel module to package
#******************************************************************************
copy_module() {
   local module_path="$1"    # Path relative to lib/modules/$KERNEL_VERSION/
   local module_name="$2"    # Module filename (e.g., dione_ir.ko)

   local src="$ROOTFS_DIR/lib/modules/${KERNEL_VERSION}/${module_path}/${module_name}"
   local dest_dir="${PACKAGE_NAME}/lib/modules/${KERNEL_VERSION}/${module_path}"

   if [[ -f "$src" ]]; then
      mkdir -p "$dest_dir"
      sudo cp "$src" "$dest_dir/"
      echo "  Added module: ${module_path}/${module_name}"
      return 0
   fi
   return 1
}

#******************************************************************************
# Step 1: Copy files from sources/
#******************************************************************************
echo ""
echo "Copying Exosens sources..."

copy_from_sources "rootfs/usr" "usr"
copy_from_sources "rootfs/opt/eg" "opt/eg"

#******************************************************************************
# Step 2: Copy version info from build
#******************************************************************************
echo ""
echo "Copying version info..."
copy_from_rootfs "etc/version_eg_cams" "etc/"

#******************************************************************************
# Step 3: Copy boot files (kernel, dtb, dtbo)
#******************************************************************************
echo ""
echo "Copying boot files..."

# EG kernel and dtbo
if [[ -d "$ROOTFS_DIR/boot/eg" ]]; then
   mkdir -p "${PACKAGE_NAME}/boot/eg"
   sudo rsync -a "$ROOTFS_DIR/boot/eg/"* "${PACKAGE_NAME}/boot/eg/"
   echo "  Added /boot/eg/"
fi

# EG device tree blobs
for dtb in $ROOTFS_DIR/boot/*-eg-*.dtb*; do
   if [[ -f "$dtb" ]]; then
      mkdir -p "${PACKAGE_NAME}/boot/"
      sudo cp "$dtb" "${PACKAGE_NAME}/boot/"
      echo "  Added $(basename $dtb)"
   fi
done

#******************************************************************************
# Step 4: Copy kernel modules
#******************************************************************************
echo ""
echo "Copying kernel modules..."

# Determine driver directory based on L4T version
if [[ $L4T_VERSION_MAJOR -lt 36 ]]; then
   I2C_DRIVER_DIR="kernel/drivers/media/i2c"
else
   I2C_DRIVER_DIR="updates/drivers/media/i2c"
fi

# Camera I2C drivers
copy_module "$I2C_DRIVER_DIR" "dione_ir.ko"
copy_module "$I2C_DRIVER_DIR" "eg-ec-mipi.ko"
#copy_module "$I2C_DRIVER_DIR" "nv_imx219.ko"
#copy_module "$I2C_DRIVER_DIR" "nv_imx477.ko"

# Platform drivers (L4T 36.x)
copy_module "updates/drivers/video/tegra/camera" "tegra_camera_platform.ko"
copy_module "updates/drivers/media/platform/tegra/camera" "tegra-camera.ko"
copy_module "updates/drivers/video/tegra/host/nvcsi" "nvhost-nvcsi-t194.ko"

#******************************************************************************
# Step 5: Create post-install script
#******************************************************************************
cat > /tmp/postinst << 'EOT'
#!/bin/bash
depmod

# Configure Exosens camera overlay if not already done
if ! grep -q "JetsonIO" /boot/extlinux/extlinux.conf 2>/dev/null; then
   if [[ -x /opt/eg/jetson-io/config-by-hardware.py ]]; then
      python /opt/eg/jetson-io/config-by-hardware.py -n 2="Exosens Cameras"
   fi
fi
EOT

#******************************************************************************
# Step 6: Create post-remove script
#******************************************************************************
cat > /tmp/postrm << 'EOT'
#!/bin/bash
depmod
EOT

#******************************************************************************
# Step 7: Determine package version
#******************************************************************************
if [[ -n "$3" ]]; then
   PACKAGE_VERSION="$3"
else
   PACKAGE_VERSION="$GIT_TAG"
fi

if [[ -z "$PACKAGE_VERSION" ]]; then
   echo "Error: No package version specified and no git tag found"
   exit 1
fi

echo ""
echo "Package version: ${PACKAGE_VERSION}"

#******************************************************************************
# Step 8: Build Debian package with fpm
#******************************************************************************
echo ""
echo "Building Debian package..."

# Check if fpm is installed
if ! command -v fpm &> /dev/null; then
   echo "Error: fpm is not installed"
   echo "Install it with: gem install fpm"
   echo "See: https://fpm.readthedocs.io/en/v1.15.0/installation.html"
   exit 1
fi

fpm -v ${PACKAGE_VERSION} \
   -C ${PACKAGE_NAME} \
   -a arm64 \
   -s dir \
   -t deb \
   -n ${PACKAGE_NAME} \
   --after-install /tmp/postinst \
   --after-remove /tmp/postrm \
   --description "Exosens MIPI camera drivers for NVIDIA Jetson (L4T ${L4T_VERSION_EXTENDED})" \
   .

if [[ $? -eq 0 ]]; then
   echo ""
   echo "============================================"
   echo "Package generated: ${PACKAGE_NAME}_${PACKAGE_VERSION}_arm64.deb"
   echo "============================================"
else
   echo ""
   echo "Error: Package generation failed"
   exit 1
fi
