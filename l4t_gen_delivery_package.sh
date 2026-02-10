#!/bin/bash
#******************************************************************************
# l4t_gen_delivery_package.sh - Generate Debian package for Exosens cameras
#
# Usage:
#   ./l4t_gen_delivery_package.sh -v <version> [-V <vendor>] [-c <carrier-board>] [-p <package-version>]
#
# The script automatically detects if the kernel was built in standalone mode
# (with --standalone option) by checking for the presence of kernel modules
# with the -eg suffix.
#
# Examples:
#   ./l4t_gen_delivery_package.sh -v 36.4.3                    # Auto-detect mode
#   ./l4t_gen_delivery_package.sh -v 36.4.3 -V forecr          # Forecr build
#   ./l4t_gen_delivery_package.sh -v 36.4.3 -V forecr -p 2.0.0 # Forecr with version
#******************************************************************************

. l4t_environment.sh
l4t_init "$@"

if [[ ! -d $JETSON_DIR ]]; then
   echo "Error : $JETSON_DIR folder doesn't exist"
   exit 1
fi

cd $JETSON_DIR

#******************************************************************************
# Configuration
#******************************************************************************
# Auto-detect standalone build by checking for kernel modules with -eg suffix
# Standalone builds create modules in a directory like 5.15.148-tegra-eg
STANDALONE_BUILD=0
EG_KERNEL_VERSION=$(ls $JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/rootfs/lib/modules/ 2>/dev/null | grep -- '-eg$')
if [[ -n "$EG_KERNEL_VERSION" ]]; then
   STANDALONE_BUILD=1
   KERNEL_VERSION="$EG_KERNEL_VERSION"
else
   KERNEL_VERSION=$(ls $JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/rootfs/lib/modules/ | grep -v -- '-eg$' | head -1)
fi

# Package naming: jetson-l4t-36.4.3-forecr-dsboard-ornx-eg-cams
if [[ "$VENDOR" == "generic" ]]; then
   PACKAGE_NAME=jetson-l4t-${L4T_VERSION}-eg-cams
else
   # Replace underscores with hyphens for Debian package naming convention
   CARRIER_BOARD_DEB=$(echo "$CARRIER_BOARD" | tr '_' '-')
   PACKAGE_NAME=jetson-l4t-${L4T_VERSION}-${VENDOR}-${CARRIER_BOARD_DEB}-eg-cams
fi

ROOTFS_DIR=$JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/rootfs

# Clean previous package
sudo rm -rf ${PACKAGE_NAME}

echo "============================================"
echo "Generating package: ${PACKAGE_NAME}"
echo "  Vendor: $VENDOR"
echo "  Carrier board: $CARRIER_BOARD"
echo "  Kernel version: ${KERNEL_VERSION}"
if [[ $STANDALONE_BUILD -eq 1 ]]; then
   echo "  Mode: standalone (all modules + initramfs)"
else
   echo "  Mode: standard (camera modules only)"
fi
echo "============================================"

#******************************************************************************
# Function: Copy from sources directory to package
# Automatically handles common/, $VERSION/, and $VERSION/$VENDOR/
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

   # Copy from $VERSION/$VENDOR/ (overrides version-specific)
   if [[ -n "$VENDOR_SOURCE_DIR" ]]; then
      src="$ROOT_DIR/sources/$L4T_VERSION/${VENDOR_SOURCE_DIR}/${src_subpath}"
      if [[ -d "$src" ]]; then
         echo "  Copying ${src_subpath} from $L4T_VERSION/$VENDOR/"
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
update_status "Copying Exosens sources..."

copy_from_sources "rootfs/usr" "usr"
copy_from_sources "rootfs/opt/eg" "opt/eg"

#******************************************************************************
# Step 2: Copy version info from build
#******************************************************************************
update_status "Copying version info..."
copy_from_rootfs "etc/version_eg_cams" "etc/"

#******************************************************************************
# Step 3: Copy boot files (kernel, dtb, dtbo)
#******************************************************************************
update_status "Copying boot files..."

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
update_status "Copying kernel modules..."

if [[ $STANDALONE_BUILD -eq 1 ]]; then
   # Standalone build: Copy ALL kernel modules to ensure kernel/modules compatibility
   # Modules are installed in a separate directory (e.g., 5.15.148-tegra-eg) to preserve
   # the original kernel as a backup option.
   MODULES_SRC="$ROOTFS_DIR/lib/modules/${KERNEL_VERSION}"
   MODULES_DEST="${PACKAGE_NAME}/lib/modules/${KERNEL_VERSION}"

   if [[ -d "$MODULES_SRC" ]]; then
      mkdir -p "$MODULES_DEST"
      sudo rsync -a "$MODULES_SRC/" "$MODULES_DEST/"
      MODULE_COUNT=$(find "$MODULES_DEST" -name "*.ko" | wc -l)
      echo "  Copied $MODULE_COUNT kernel modules to ${KERNEL_VERSION}/"
   else
      echo "  Warning: No modules found in $MODULES_SRC"
   fi
elif [[ $L4T_VERSION_MAJOR -ge 36 ]]; then
   # L4T 36.x+ standard build: Copy only Exosens camera modules (OOT)
   I2C_DRIVER_DIR="updates/drivers/media/i2c"

   copy_module "$I2C_DRIVER_DIR" "dione_ir.ko"
   copy_module "$I2C_DRIVER_DIR" "eg-ec-mipi.ko"
   copy_module "updates/drivers/video/tegra/camera" "tegra_camera_platform.ko"
   copy_module "updates/drivers/media/platform/tegra/camera" "tegra-camera.ko"
   copy_module "updates/drivers/video/tegra/host/nvcsi" "nvhost-nvcsi-t194.ko"
else
   # L4T 35.x and earlier standard build: Copy only Exosens camera modules (in-tree)
   I2C_DRIVER_DIR="kernel/drivers/media/i2c"

   copy_module "$I2C_DRIVER_DIR" "dione_ir.ko"
   copy_module "$I2C_DRIVER_DIR" "eg-ec-mipi.ko"
fi

#******************************************************************************
# Step 5: Create post-install script
#******************************************************************************
update_status "Creating install scripts..."
cat > /tmp/postinst << 'EOT'
#!/bin/bash
depmod
EOT

# Add Exosens camera overlay configuration
cat >> /tmp/postinst << 'EOT'

# Configure Exosens camera overlay if not already done
if ! grep -q "JetsonIO" /boot/extlinux/extlinux.conf 2>/dev/null; then
   eg_dt_camera_config_set.sh 0 Dione 1 Dione
else
   # Check if /boot/eg/Image is a standalone kernel (version ends with -eg)
   if [[ -f /boot/eg/Image ]]; then
      KERNEL_VERSION=$(strings /boot/eg/Image | grep "Linux version" | head -1 | awk '{print $3}')

      if [[ "$KERNEL_VERSION" == *-eg ]]; then
         # Standalone kernel: requires initrd-eg
         if [[ ! -f /boot/eg/initrd-eg ]]; then
            echo "ERROR: Standalone kernel detected ($KERNEL_VERSION) but /boot/eg/initrd-eg is missing!"
            exit 1
         fi
         INITRD_PATH="/boot/eg/initrd-eg"
      else
         # Standard kernel: use standard initrd
         INITRD_PATH="/boot/initrd"
      fi

      # Update INITRD in JetsonIO section if different
      CURRENT_INITRD=$(sed -n '/LABEL JetsonIO/,/^LABEL /{s/.*INITRD \(.*\)/\1/p}' /boot/extlinux/extlinux.conf | head -1)
      if [[ "$CURRENT_INITRD" != "$INITRD_PATH" ]]; then
         echo "Updating JetsonIO INITRD to $INITRD_PATH..."
         sed -i "/LABEL JetsonIO/,/^LABEL /{s|INITRD .*|INITRD $INITRD_PATH|}" /boot/extlinux/extlinux.conf
      fi
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
if [[ -z "$PACKAGE_VERSION" ]]; then
   PACKAGE_VERSION="$GIT_TAG"
fi

if [[ -z "$PACKAGE_VERSION" ]]; then
   echo "Error: No package version specified and no git tag found"
   echo "Use -p <version> to specify a package version"
   exit 1
fi

echo ""
echo "Package version: ${PACKAGE_VERSION}"

#******************************************************************************
# Step 8: Build Debian package with fpm
#******************************************************************************
update_status "Building Debian package..."

# Remove existing .deb package if it exists
# Note: fpm converts underscores to hyphens in package names (Debian convention)
DEB_PACKAGE_NAME="${PACKAGE_NAME//_/-}"
DEB_PACKAGE="${DEB_PACKAGE_NAME}_${PACKAGE_VERSION}_arm64.deb"
if [[ -f "$DEB_PACKAGE" ]]; then
   echo "Removing existing package: $DEB_PACKAGE"
   rm -f "$DEB_PACKAGE"
fi

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
   echo "Package generated: ${DEB_PACKAGE}"
   echo "============================================"

   # Copy to delivery directory if it exists
   DELIVERY_DIR="$ROOT_DIR/delivery"
   if [[ -d "$DELIVERY_DIR" ]]; then
      DELIVERY_SUBDIR="$DELIVERY_DIR/jetson-l4t-eg-${PACKAGE_VERSION}"
      mkdir -p "$DELIVERY_SUBDIR"
      cp "$DEB_PACKAGE" "$DELIVERY_SUBDIR/"
      echo "Copied to: $DELIVERY_SUBDIR/$DEB_PACKAGE"
   fi
else
   echo ""
   echo "Error: Package generation failed"
   exit 1
fi

#******************************************************************************
# Step 9: Verify generated package
#******************************************************************************
update_status "Verifying package..."

VERIFY_ARGS="-v $L4T_VERSION"
[[ "$VENDOR" != "generic" ]] && VERIFY_ARGS="$VERIFY_ARGS -V $VENDOR -c $CARRIER_BOARD"

cd $ROOT_DIR
if ./l4t_verify_packages.sh $VERIFY_ARGS; then
   update_status "Done"
   echo ""
   echo "============================================"
   echo "Package verified successfully"
   echo "============================================"
else
   update_status "Done (with warnings)"
   echo ""
   echo "Warning: Package verification found issues"
   echo "Review the errors above before distributing the package"
fi
