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

# Package naming: jetson-l4t-36.4.3-jp6.2-forecr-dsboard-ornx-eg-cams
#                 jetson-l4t-32.7.1-jp4.6.1-t210-eg-cams
JP_INFIX=""
[[ -n "$JETPACK_VERSION" ]] && JP_INFIX="-jp${JETPACK_VERSION}"
if [[ "$VENDOR" == "generic" ]]; then
   if [[ -n "$SOM_BOARD" ]]; then
      PACKAGE_NAME=jetson-l4t-${L4T_VERSION}${JP_INFIX}-${SOM_BOARD}-eg-cams
      CANONICAL_NAME="jetson-eg-cams-${SOM_BOARD}"
   else
      PACKAGE_NAME=jetson-l4t-${L4T_VERSION}${JP_INFIX}-eg-cams
      CANONICAL_NAME="jetson-eg-cams"
   fi
else
   # Replace underscores with hyphens for Debian package naming convention
   CARRIER_BOARD_DEB=$(echo "$CARRIER_BOARD" | tr '_' '-')
   PACKAGE_NAME=jetson-l4t-${L4T_VERSION}${JP_INFIX}-${VENDOR}-${CARRIER_BOARD_DEB}-eg-cams
   CANONICAL_NAME="jetson-eg-cams-${VENDOR}-${CARRIER_BOARD_DEB}"
fi

ROOTFS_DIR=$JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/rootfs

# Clean previous package
sudo rm -rf ${PACKAGE_NAME}

echo "============================================"
echo "Generating package: ${PACKAGE_NAME}"
echo "  Vendor: $VENDOR"
[[ -n "$SOM_BOARD" ]] && echo "  SoM: $SOM_BOARD"
echo "  Carrier board: $CARRIER_BOARD"
echo "  Kernel version: ${KERNEL_VERSION}"
if [[ $STANDALONE_BUILD -eq 1 ]]; then
   echo "  Mode: standalone (all modules + initramfs)"
else
   echo "  Mode: standard (camera modules only)"
fi
echo "============================================"

#******************************************************************************
# Sanitize a version string for Debian compatibility
# - Replaces invalid characters (/, _) with hyphens
# - Prepends 0~ if the version doesn't start with a digit (Debian requirement)
#******************************************************************************
sanitize_debian_version() {
   local ver="$1"
   # Replace / and _ with hyphens
   ver="${ver//\//-}"
   ver="${ver//_/-}"
   # Remove any remaining invalid characters (keep alphanumeric, ., +, ~, -)
   ver=$(echo "$ver" | sed 's/[^a-zA-Z0-9.+~-]/-/g; s/-\+/-/g; s/-$//')
   # Debian: version must start with a digit
   if [[ ! "$ver" =~ ^[0-9] ]]; then
      ver="0~${ver}"
   fi
   echo "$ver"
}

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
# Step 2: Determine package version
#******************************************************************************
update_status "Determining package version..."

if [[ -n "$PACKAGE_VERSION" ]]; then
   # -p specified: use it + git commit for traceability
   DEB_VERSION="$(sanitize_debian_version "$PACKAGE_VERSION")+g${GIT_COMMIT}"
elif [[ -n "$GIT_EXACT_TAG" ]]; then
   # On an exact tag: clean release version
   DEB_VERSION="$(sanitize_debian_version "$GIT_EXACT_TAG")"
else
   # No -p, no tag: use branch name + git commit
   DEB_VERSION="$(sanitize_debian_version "$GIT_BRANCH")+g${GIT_COMMIT}"
fi

# Final safety: Debian version must start with a digit
if [[ ! "$DEB_VERSION" =~ ^[0-9] ]]; then
   DEB_VERSION="0~${DEB_VERSION}"
fi

echo "  Debian version: ${DEB_VERSION}"

#******************************************************************************
# Step 3: Generate version info
#******************************************************************************
update_status "Generating version info..."
mkdir -p "${PACKAGE_NAME}/etc"
echo "jetson-l4t-${L4T_VERSION_EXTENDED}_eg ${DEB_VERSION} (${GIT_BRANCH}, ${GIT_COMMIT})" > "${PACKAGE_NAME}/etc/version_eg_cams"

#******************************************************************************
# Step 4: Copy boot files (kernel, dtb, dtbo)
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
# Step 5: Copy kernel modules
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
      sudo rsync -a --exclude='build' --exclude='source' "$MODULES_SRC/" "$MODULES_DEST/"
      MODULE_COUNT=$(find "$MODULES_DEST" -name "*.ko" | wc -l)
      echo "  Copied $MODULE_COUNT kernel modules to ${KERNEL_VERSION}/"
   else
      echo "  Warning: No modules found in $MODULES_SRC"
   fi
else
   # Standard build: auto-detect Exosens camera modules by cross-referencing
   # the i2c Makefile with .c source files present in sources/ (Exosens-owned).
   # This automatically picks up any new module whose .c is added to sources/.
   I2C_DRIVER_DIR="kernel/drivers/media/i2c"
   EG_MODULES=()

   # Collect Exosens .c source basenames: any .c file under sources/*/drivers/media/i2c/
   EG_SRCS=()
   while IFS= read -r f; do
      EG_SRCS+=("$(basename "$f" .c)")
   done < <(find "$ROOT_DIR/sources" -path "*/drivers/media/i2c/*.c" 2>/dev/null)

   # The EG module list is always derived from the version-generic Makefile.
   # SoM/vendor/carrier layers contain NVIDIA stock Makefiles (no EG modules)
   # and must never override it.
   I2C_MAKEFILE=""
   for rel in "source/public/kernel/nvidia/drivers/media/i2c/Makefile" \
              "source/nvidia-oot/drivers/media/i2c/Makefile"; do
      candidate="$ROOT_DIR/sources/$L4T_VERSION/Linux_for_Tegra/$rel"
      [[ -f "$candidate" ]] && I2C_MAKEFILE="$candidate"
   done

   if [[ ${#EG_SRCS[@]} -gt 0 && -n "$I2C_MAKEFILE" ]]; then
      echo "  Using i2c Makefile: $I2C_MAKEFILE"

      # Join backslash-continuation lines for easier parsing
      MAKEFILE_JOINED=$(awk '{if(/\\$/) {printf "%s ", substr($0,1,length($0)-1)} else {print}}' "$I2C_MAKEFILE")

      # Build module→sources map from <mod>-objs and <mod>-y assignments
      declare -A _mod_srcs
      while IFS= read -r line; do
         line="${line%%#*}"
         if [[ "$line" =~ ^([a-zA-Z0-9_-]+)-[yo][^[:space:]=]*[[:space:]]*([:+]?=)[[:space:]]*(.*) ]]; then
            mod="${BASH_REMATCH[1]}"
            for tok in ${BASH_REMATCH[3]}; do
               [[ "$tok" == *.o ]] && _mod_srcs["$mod"]+=" $(basename "${tok%.o}")"
            done
         fi
      done <<< "$MAKEFILE_JOINED"

      # For each obj- module: check if any source file belongs to Exosens
      while IFS= read -r line; do
         line="${line%%#*}"
         if [[ "$line" =~ ^obj-[^+]*\+=[[:space:]]*([a-zA-Z0-9_-]+)\.o ]]; then
            mod="${BASH_REMATCH[1]}"
            srcs="${_mod_srcs[$mod]:-$mod}"
            for src in $srcs; do
               for eg in "${EG_SRCS[@]}"; do
                  if [[ "$src" == "$eg" ]]; then
                     EG_MODULES+=("${mod}.ko")
                     break 2
                  fi
               done
            done
         fi
      done <<< "$MAKEFILE_JOINED"
      unset _mod_srcs
   else
      [[ ${#EG_SRCS[@]} -eq 0 ]] && echo "  WARNING: No Exosens .c sources found under sources/"
      [[ -z "$I2C_MAKEFILE" ]] && echo "  WARNING: Could not find i2c Makefile in sources"
   fi

   if [[ ${#EG_MODULES[@]} -gt 0 ]]; then
      echo "  Auto-detected Exosens modules: ${EG_MODULES[*]}"
      for module in "${EG_MODULES[@]}"; do
         copy_module "$I2C_DRIVER_DIR" "$module"
      done
   else
      echo "  WARNING: No Exosens modules detected"
   fi
fi

#******************************************************************************
# Step 6: Create pre-install script
#******************************************************************************
update_status "Creating install scripts..."

# Use build-specific temp file names to avoid collisions when multiple
# builds run in parallel (e.g. generic and forecr for the same L4T version).
_BUILD_ID="${L4T_VERSION_EXTENDED}${SOM_BOARD:+_$SOM_BOARD}_${CARRIER_BOARD:-generic}"
_PREINST="/tmp/preinst_${_BUILD_ID}"
_POSTINST="/tmp/postinst_${_BUILD_ID}"
_POSTRM="/tmp/postrm_${_BUILD_ID}"

# The package's /etc/version_eg_cams is not yet on disk when preinst runs
# (dpkg unpacks files only after preinst succeeds), so we embed its content
# verbatim here at build time. The L4T version is then extracted from it to
# compare against the running system's /etc/nv_tegra_release.
cat > "$_PREINST" << 'EOT'
#!/bin/bash
set -e
EOT

# Embed the exact same string that Step 3 writes to /etc/version_eg_cams
cat >> "$_PREINST" << EOT
PACKAGE_VERSION_LINE="jetson-l4t-${L4T_VERSION_EXTENDED}_eg ${DEB_VERSION} (${GIT_BRANCH}, ${GIT_COMMIT})"
EXPECTED_KERNEL_VERSION="${KERNEL_VERSION}"
EOT

cat >> "$_PREINST" << 'EOT'

case "$1" in
    install|upgrade)
        # Extract the L4T version and vendor from the embedded version_eg_cams string:
        # Generic:  "jetson-l4t-35.6.2_eg ..." -> L4T=35.6.2, VENDOR=generic
        # Forecr:   "jetson-l4t-35.6.2_forecr_eg ..." -> L4T=35.6.2, VENDOR=forecr

        # Extract version_extended (35.6.2 or 35.6.2_forecr)
        EXPECTED_VERSION_EXTENDED=$(echo "$PACKAGE_VERSION_LINE" | sed 's/^jetson-l4t-\([^_]*\(_[^_]*\)\?\)_eg.*/\1/')

        # Extract L4T version (first part before vendor suffix)
        EXPECTED_L4T=$(echo "$EXPECTED_VERSION_EXTENDED" | sed 's/_.*$//')

        # Determine expected vendor: if version_extended contains underscore, it's forecr or other vendor
        if [[ "$EXPECTED_VERSION_EXTENDED" =~ _forecr$ ]]; then
            EXPECTED_VENDOR="forecr"
        else
            EXPECTED_VENDOR="generic"
        fi

        # Check /etc/nv_tegra_release
        if [[ ! -f /etc/nv_tegra_release ]]; then
            echo "Error: /etc/nv_tegra_release not found." >&2
            echo "This package requires NVIDIA Jetson Linux (L4T) ${EXPECTED_L4T}." >&2
            exit 1
        fi

        # Extract L4T version from running system
        NV_MAJOR=$(sed -n 's/.*# R\([0-9]*\) .*/\1/p' /etc/nv_tegra_release | head -1)
        NV_REVISION=$(sed -n 's/.*REVISION: \([0-9.]*\).*/\1/p' /etc/nv_tegra_release | head -1)

        if [[ -z "$NV_MAJOR" || -z "$NV_REVISION" ]]; then
            echo "Error: Could not parse L4T version from /etc/nv_tegra_release." >&2
            exit 1
        fi

        RUNNING_L4T="${NV_MAJOR}.${NV_REVISION}"

        if [[ -n "$FORCE_INSTALL_EG_CAMS" ]]; then
            # L4T check bypassed — verify kernel version matches instead
            RUNNING_KERNEL=$(uname -r | sed 's/-eg$//')
            EXPECTED_KERNEL_STRIPPED=$(echo "$EXPECTED_KERNEL_VERSION" | sed 's/-eg$//')
            if [[ "$RUNNING_KERNEL" != "$EXPECTED_KERNEL_STRIPPED" ]]; then
                echo "Error: Kernel version mismatch (FORCE_INSTALL_EG_CAMS set)." >&2
                echo "  This package contains modules for kernel ${EXPECTED_KERNEL_VERSION}." >&2
                echo "  Running kernel: $(uname -r)" >&2
                echo "  Rebuild the package for $(uname -r) or install the matching version." >&2
                exit 1
            fi
        else
            # Default: strict L4T version check
            if [[ "$EXPECTED_L4T" != "$RUNNING_L4T" ]]; then
                echo "Error: Incompatible L4T version." >&2
                echo "  This package was built for L4T ${EXPECTED_L4T}." >&2
                echo "  Running system: L4T ${RUNNING_L4T}" >&2
                echo "  Install the package matching your L4T version." >&2
                exit 1
            fi
        fi

        # Vendor check: only enforce for generic packages.
        # Forecr packages install unconditionally — Forecr board detection via
        # nvidia,dtsfilename is unreliable on JP6 (not all SoM SKUs have a
        # Forecr DTB in the BSP, e.g. p3767-0005).
        if [[ "$EXPECTED_VENDOR" != "forecr" ]]; then
            RUNNING_VENDOR="generic"

            # Method 1: active DTB (post-reboot)
            if [[ -f /proc/device-tree/nvidia,dtsfilename ]]; then
                DTB=$(cat /proc/device-tree/nvidia,dtsfilename 2>/dev/null | tr -d '\0')
                if [[ "$DTB" =~ (dsboard|milboard|raiboard) ]]; then
                    RUNNING_VENDOR="forecr"
                fi
            fi

            # Method 2: previously installed eg-cams package (pre-reboot upgrade path)
            if [[ "$RUNNING_VENDOR" == "generic" ]]; then
                if dpkg -l 2>/dev/null | grep -q '^ii.*jetson.*-forecr-.*-eg-cams'; then
                    RUNNING_VENDOR="forecr"
                fi
            fi

            # If RUNNING_VENDOR is still "generic" both detection methods found
            # nothing: genuine first install — allow any vendor package.
            if [[ "$RUNNING_VENDOR" != "generic" && "$RUNNING_VENDOR" != "$EXPECTED_VENDOR" ]]; then
                echo "Error: Board vendor mismatch." >&2
                echo "  This package was built for: $EXPECTED_VENDOR" >&2
                echo "  Running system: $RUNNING_VENDOR" >&2
                echo "  Install the package matching your board type." >&2
                exit 1
            fi
        fi
        ;;
esac
EOT

#******************************************************************************
# Step 7: Create post-install script
#******************************************************************************
cat > "$_POSTINST" << 'EOT'
#!/bin/bash
depmod
EOT

# Inject L4T version and package identity into postinst (unquoted EOT for variable expansion)
cat >> "$_POSTINST" << EOT

L4T_VERSION_MAJOR=$L4T_VERSION_MAJOR
CANONICAL_NAME="${CANONICAL_NAME}"
CURRENT_PKG="${PACKAGE_NAME//_/-}"
EOT

# For vendor packages, inject known board so postinst never calls detect_jetson_board.sh
if [[ "$VENDOR" != "generic" ]]; then
   # Convert underscores to hyphens (CARRIER_BOARD uses underscores internally; detect_jetson_board.sh uses hyphens).
   # Temporary: dsboard_ornx in eg_config.yaml is a typo for dsboard_ornxs (two different Forecr products).
   _EG_FORCE_BOARD="${CARRIER_BOARD//_/-}"
   [[ "$_EG_FORCE_BOARD" == "dsboard-ornx" ]] && _EG_FORCE_BOARD="dsboard-ornxs"
cat >> "$_POSTINST" << EOT
export EG_FORCE_BOARD="${_EG_FORCE_BOARD}"
EOT
fi

# Add Exosens camera overlay configuration (quoted EOT, no expansion)
cat >> "$_POSTINST" << 'EOT'

# Configure Exosens camera overlay if not already done
if ! grep -q "JetsonIO" /boot/extlinux/extlinux.conf 2>/dev/null; then
   # Fresh install: configure all ports with default camera (Dione)
   eg_dt_camera_config_set.sh
else
   # Upgrade: JetsonIO already configured

   # Re-apply camera configuration after package upgrade
   echo "Reading current camera configuration..."
   CONFIG_OUTPUT=$(eg_dt_camera_config_get.sh 2>/dev/null)

   if [[ -n "$CONFIG_OUTPUT" ]]; then
      CAMERA_ARGS=""
      while IFS= read -r line; do
         port=""
         cam_type=""

         # Old format: "Camera port 0 configuration : Dione"
         #             "Camera port 1 configuration : SmartIR640 and Crius1280"
         if [[ "$line" =~ Camera\ port\ ([0-9]+)\ configuration\ :\ (.+) ]]; then
            port="${BASH_REMATCH[1]}"
            cam_type="${BASH_REMATCH[2]}"

         # New format: "  Port 0: Dione (connected)"
         #             "  Port 1: SmartIR640 or Crius1280 (not connected)"
         elif [[ "$line" =~ Port\ ([0-9]+):\ ([^\(]+) ]]; then
            port="${BASH_REMATCH[1]}"
            cam_type="${BASH_REMATCH[2]}"
            cam_type="${cam_type% }"
         fi

         [[ -z "$port" ]] && continue

         # Normalize camera type names
         case "$cam_type" in
            *SmartIR640*)    cam_type="SmartIR640" ;;
            *Crius1280*)     cam_type="Crius1280" ;;
            *MicroCube640*)  cam_type="MicroCube640" ;;
            *MicroCube*)     cam_type="MicroCube640" ;;
            *iLumos*|*ilumos*) cam_type="iLumos" ;;
            *Microlynx*|*microlynx*) cam_type="Microlynx" ;;
            *Dione*)         cam_type="Dione" ;;
            *)               continue ;;
         esac

         CAMERA_ARGS="$CAMERA_ARGS $port/$cam_type"
      done <<< "$CONFIG_OUTPUT"

      if [[ -n "$CAMERA_ARGS" ]]; then
         echo "Re-applying camera configuration:$CAMERA_ARGS"
         eg_dt_camera_config_set.sh $CAMERA_ARGS
      else
         echo "No camera configuration found, applying defaults"
         eg_dt_camera_config_set.sh
      fi
   else
      echo "Could not read camera configuration, applying defaults"
      eg_dt_camera_config_set.sh
   fi

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

# Remove stale packages from the same hardware family (deferred to avoid dpkg lock)
_OLD_PKGS=$(dpkg-query -W --showformat='${Package}\t${Status}\t${Provides}\n' 2>/dev/null | \
    awk -F'\t' -v cn="$CANONICAL_NAME" -v cp="$CURRENT_PKG" \
    '$1 != cp && $2 == "install ok installed" && index($3, cn) > 0 {print $1}' | tr '\n' ' ')
if [[ -n "$_OLD_PKGS" ]]; then
    echo "Removing replaced package(s): $_OLD_PKGS"
    ( sleep 3 && dpkg --purge $_OLD_PKGS > /dev/null 2>&1 ) &
    disown $!
fi
EOT

#******************************************************************************
# Step 8: Create post-remove script
#******************************************************************************
cat > "$_POSTRM" << 'EOT'
#!/bin/bash
depmod
EOT

#******************************************************************************
# Step 9: Build Debian package with fpm
#******************************************************************************
update_status "Building Debian package..."

# Remove existing .deb package if it exists
# Note: fpm converts underscores to hyphens in package names (Debian convention)
DEB_PACKAGE_NAME="${PACKAGE_NAME//_/-}"
DEB_PACKAGE="${DEB_PACKAGE_NAME}_${DEB_VERSION}_arm64.deb"
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

fpm -v ${DEB_VERSION} \
   -C ${PACKAGE_NAME} \
   -a arm64 \
   -s dir \
   -t deb \
   -n ${PACKAGE_NAME} \
   --provides "${CANONICAL_NAME}" \
   --replaces "${CANONICAL_NAME}" \
   --before-install "$_PREINST" \
   --after-install "$_POSTINST" \
   --after-remove "$_POSTRM" \
   --description "Exosens MIPI camera drivers for NVIDIA Jetson (L4T ${L4T_VERSION_EXTENDED})" \
   .

if [[ $? -eq 0 ]]; then
   echo ""
   echo "============================================"
   echo "Package generated: ${DEB_PACKAGE}"
   echo "============================================"

   # Copy to delivery directory
   DELIVERY_SUBDIR="$DELIVERY_DIR/jetson-l4t-eg-${DEB_VERSION}"
   mkdir -p "$DELIVERY_SUBDIR"
   cp "$DEB_PACKAGE" "$DELIVERY_SUBDIR/"
   echo "Copied to: $DELIVERY_SUBDIR/$DEB_PACKAGE"
else
   echo ""
   echo "Error: Package generation failed"
   exit 1
fi

#******************************************************************************
# Step 10: Verify generated package
#******************************************************************************
update_status "Verifying package..."

VERIFY_ARGS="-v $L4T_VERSION"
[[ -n "$SOM_BOARD" ]] && VERIFY_ARGS="$VERIFY_ARGS -s $SOM_BOARD"
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
   exit 1
fi
