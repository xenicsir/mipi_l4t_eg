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

# Package naming: jetson-l4t-36.4.3-jp6.2-forecr-dsboard-ornxs-eg-cams
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

# EG kernel and dtbo (Image + initrd-eg). Skipped for PRISTINE_KERNEL vendors
# (e.g. cti): their kernel/nvidia-oot is precompiled and not ours to replace,
# so we never ship our own-built Image/initrd — the target keeps booting its
# own vendor kernel (see config-by-hardware.py's os.path.exists check).
if [[ "$PRISTINE_KERNEL" != "1" ]]; then
   if [[ -d "$ROOTFS_DIR/boot/eg" ]]; then
      mkdir -p "${PACKAGE_NAME}/boot/eg"
      sudo rsync -a "$ROOTFS_DIR/boot/eg/"* "${PACKAGE_NAME}/boot/eg/"
      echo "  Added /boot/eg/"
   fi
else
   echo "  Skipped /boot/eg/ (PRISTINE_KERNEL vendor: not shipping our own kernel Image)"
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
   # 36.x (out-of-tree nvidia-oot) installs modules under .../updates/..., while
   # 32.x/35.x (in-tree) uses .../kernel/... — matches l4t_verify_packages.sh,
   # which already made this same distinction.
   if [[ $L4T_VERSION_MAJOR -ge 36 ]]; then
      I2C_DRIVER_DIR="updates/drivers/media/i2c"
   else
      I2C_DRIVER_DIR="kernel/drivers/media/i2c"
   fi
   EG_MODULES=()

   # Collect Exosens .c source basenames: any .c file under sources/*/drivers/media/i2c/
   EG_SRCS=()
   while IFS= read -r f; do
      EG_SRCS+=("$(basename "$f" .c)")
   done < <(find "$ROOT_DIR/sources/common" "$ROOT_DIR/sources/$L4T_VERSION/Linux_for_Tegra" \
                  -path "*/drivers/media/i2c/*.c" 2>/dev/null)

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

      # Resolve ifdef/ifndef PRISTINE_KERNEL / else / endif for THIS vendor's
      # actual PRISTINE_KERNEL value before parsing, so e.g. ilumos/microlynx
      # (guarded out for cti) are never mistaken for modules to package just
      # because their obj-m line is still textually present in the Makefile.
      # Other conditionals (ifeq/ifneq/ifdef of anything else) are left as
      # opaque text — both their branches are kept, matching prior behavior.
      RESOLVED_MAKEFILE=$(PRISTINE_KERNEL="$PRISTINE_KERNEL" python3 - "$I2C_MAKEFILE" <<'PYEOF'
import os, re, sys

path = sys.argv[1]
pristine = os.environ.get("PRISTINE_KERNEL") == "1"

IFDEF  = re.compile(r'^\s*ifdef\s+(\S+)')
IFNDEF = re.compile(r'^\s*ifndef\s+(\S+)')
ELSE   = re.compile(r'^\s*else\b')
ENDIF  = re.compile(r'^\s*endif\b')

out = []
stack = []  # each frame: [tracked: bool, keep: bool]
for line in open(path):
    m = IFNDEF.match(line)
    if m:
        tracked = m.group(1) == "PRISTINE_KERNEL"
        stack.append([tracked, (not pristine) if tracked else True])
        continue
    m = IFDEF.match(line)
    if m:
        tracked = m.group(1) == "PRISTINE_KERNEL"
        stack.append([tracked, pristine if tracked else True])
        continue
    if ELSE.match(line):
        if stack and stack[-1][0]:
            stack[-1][1] = not stack[-1][1]
        continue
    if ENDIF.match(line):
        if stack:
            stack.pop()
        continue
    if any(tracked and not keep for tracked, keep in stack):
        continue
    out.append(line)
sys.stdout.write("".join(out))
PYEOF
)

      # Join backslash-continuation lines for easier parsing
      MAKEFILE_JOINED=$(awk '{if(/\\$/) {printf "%s ", substr($0,1,length($0)-1)} else {print}}' <<< "$RESOLVED_MAKEFILE")

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
        EXPECTED_VERSION_EXTENDED=$(echo "$PACKAGE_VERSION_LINE" | sed 's/^jetson-l4t-\(.*\)_eg .*/\1/')

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
            # L4T version check: compare only as many components as EXPECTED has.
            # JP7.x (L4T 39.x) reports REVISION as "2.0" → RUNNING=39.2.0 but EXPECTED=39.2.
            NCOMP=$(echo "$EXPECTED_L4T" | awk -F'.' '{print NF}')
            RUNNING_L4T_CMP=$(echo "$RUNNING_L4T" | cut -d'.' -f1-${NCOMP})
            if [[ "$EXPECTED_L4T" != "$RUNNING_L4T_CMP" ]]; then
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
   _EG_FORCE_BOARD="${CARRIER_BOARD//_/-}"
cat >> "$_POSTINST" << EOT
export EG_FORCE_BOARD="${_EG_FORCE_BOARD}"
EOT
fi

# Add Exosens camera overlay configuration (quoted EOT, no expansion)
cat >> "$_POSTINST" << 'EOT'

# Configure Exosens camera overlay if not already done.
# Track the camera-config outcome so a FRESH install that fails to configure the
# cameras propagates as a non-zero postinst exit (dpkg reports failure) instead
# of silently succeeding with a broken/empty camera config. The upgrade
# re-application below stays best-effort: the previous working config is already
# in place, so a re-apply hiccup must not abort the package upgrade.
_CONFIG_RC=0
if ! grep -q "JetsonIO" /boot/extlinux/extlinux.conf 2>/dev/null; then
   # Fresh install: configure all ports with default camera (Dione)
   eg_dt_camera_config_set.sh || _CONFIG_RC=$?
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
         eg_dt_camera_config_set.sh $CAMERA_ARGS || \
            echo "Warning: camera config re-apply failed; keeping existing configuration" >&2
      else
         echo "No camera configuration found, applying defaults"
         eg_dt_camera_config_set.sh || \
            echo "Warning: camera config re-apply failed; keeping existing configuration" >&2
      fi
   else
      echo "Could not read camera configuration, applying defaults"
      eg_dt_camera_config_set.sh || \
         echo "Warning: camera config re-apply failed; keeping existing configuration" >&2
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

# Warn about missing optional runtime dependencies for the shipped camera tools.
# They are declared as Recommends/Suggests, which apt installs on its own -- but
# dpkg ignores those fields entirely, so `dpkg -i` leaves them missing with no
# diagnostic at all and the gap only shows up as "command not found" at the first
# streaming command. Pure echo, deliberately: a missing optional tool must never
# affect the exit code, so this block stays clear of _CONFIG_RC.
_MISSING=""
command -v v4l2-ctl > /dev/null 2>&1 || _MISSING="$_MISSING v4l-utils"
python3 -c 'import cv2' > /dev/null 2>&1 || _MISSING="$_MISSING python3-opencv"
if [[ -n "$_MISSING" ]]; then
   echo ""
   echo "WARNING: optional package(s) not installed:$_MISSING"
   for _p in $_MISSING; do
      case "$_p" in
         v4l-utils)
            echo "  v4l-utils      needed by eg_dt_camera_config_get.sh, read_nvcsi.py, rt_frame_monitor.py"
            ;;
         python3-opencv)
            echo "  python3-opencv needed by rt_frame_monitor.py --display"
            ;;
      esac
   done
   echo "  The camera drivers themselves are installed and fully functional."
   echo "  Install the missing tool(s) with:"
   echo ""
   echo "sudo apt install$_MISSING"
   echo ""
   echo "  (if that reports no candidate, the package lists are empty:"
   echo "   run 'sudo apt update' first -- a freshly flashed board has none."
   echo "   apt pulls these in by itself on a first install once the lists are"
   echo "   populated; 'dpkg -i' and 'apt install --reinstall' never do)"
   echo ""
fi

# Propagate a fresh-install camera-config failure. The best-effort cleanup above
# must not mask it; _CONFIG_RC is 0 on success and for best-effort upgrades.
exit $_CONFIG_RC
EOT

#******************************************************************************
# Step 8: Create post-remove script
#******************************************************************************
cat > "$_POSTRM" << 'EOT'
#!/bin/bash
# A standalone package (e.g. cti) owns its entire /lib/modules/<ver>-eg/ tree;
# removing it deletes that directory outright when it's the running kernel's,
# leaving nothing for depmod to scan. Skip rather than fail the removal.
if [ -d "/lib/modules/$(uname -r)" ]; then
    depmod
else
    echo "Warning: the running kernel's module directory was removed by this uninstall." >&2
    echo "Reboot into another kernel before running further module/dpkg operations." >&2
fi

case "$1" in
    remove|purge)
        # The JetsonIO entry's FDT/OVERLAYS point at this package's DTB/DTBOs
        # (see postinst); once those files are gone, JetsonIO can no longer
        # boot as configured. Point DEFAULT back at the first LABEL in the
        # file (the stock boot entry) so the system still boots normally.
        EXTLINUX_CONF="/boot/extlinux/extlinux.conf"
        if [ -f "$EXTLINUX_CONF" ]; then
            FIRST_LABEL=$(awk '/^LABEL /{print $2; exit}' "$EXTLINUX_CONF")
            CURRENT_DEFAULT=$(awk '/^DEFAULT /{print $2; exit}' "$EXTLINUX_CONF")
            if [[ -n "$FIRST_LABEL" && -n "$CURRENT_DEFAULT" && "$CURRENT_DEFAULT" != "$FIRST_LABEL" ]]; then
                sed -i "s/^DEFAULT .*/DEFAULT $FIRST_LABEL/" "$EXTLINUX_CONF"
                echo "Set DEFAULT boot entry to '$FIRST_LABEL' in $EXTLINUX_CONF (was '$CURRENT_DEFAULT')."
            fi
        fi
        ;;
esac
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

# Optional runtime dependencies for the tools shipped in /usr/bin. Deliberately
# NOT Depends: a missing tool must never stop the drivers from installing, and a
# hard dependency would make dpkg leave the package unconfigured -- the postinst
# would never run, so no DTB, no JetsonIO entry, no camera at all.
#   - Recommends (v4l-utils, python3-opencv): apt installs them automatically and
#     skips them with a note if unavailable. Note python3-opencv (Ubuntu, 4.2.0)
#     and NOT libopencv-python (NVIDIA repo, 4.5.4), which would pull a second
#     OpenCV alongside the libopencv-*4.2 already on the board.
#   - Suggests (ecswctrl): private package, in no public repo. Suggests documents
#     the link without apt warning about it on every install. It ships alongside
#     the driver in the delivery directory and is named explicitly on the apt
#     command line at install time (see DEPENDENCIES.txt there, and the README).
# dpkg honours neither field, so the postinst warns when the tools are missing.
fpm -v ${DEB_VERSION} \
   -C ${PACKAGE_NAME} \
   -a arm64 \
   -s dir \
   -t deb \
   -n ${PACKAGE_NAME} \
   --provides "${CANONICAL_NAME}" \
   --replaces "${CANONICAL_NAME}" \
   --deb-recommends v4l-utils \
   --deb-recommends python3-opencv \
   --deb-suggests ecswctrl \
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

   #***************************************************************************
   # Delivery-only extras: private dependency packages and their manifest.
   #
   # This runs AFTER fpm on purpose. Nothing here can influence the driver .deb,
   # so the same commit produces a byte-identical package whether or not the
   # private packages are available locally. Their absence is the normal case
   # for a public rebuild.
   #
   # One copy of each private package, and one manifest, serve the whole
   # delivery directory: it accumulates one driver package per L4T version AND
   # per carrier board (30+), while the private packages carry no L4T version at
   # all -- verified, their binaries need only GLIBC_2.17 / GLIBCXX_3.4.21 (the
   # aarch64 baseline), so a single copy is valid from Ubuntu 18.04 to 24.04.
   #
   # Deliberately NO installer script here: the user copies one driver package
   # plus these three onto the board and names them explicitly on the apt
   # command line (see README). An auto-detecting installer would have to
   # duplicate the preinst's L4T version comparison, and two copies of that rule
   # drifting apart is exactly how install-time bugs appear.
   #
   # The manifest is rewritten identically by every build -- idempotent.
   #***************************************************************************
   DEP_PKG_DIR="$ARCHIVE_DIR/dependency_packages"
   DEP_MANIFEST="$DELIVERY_SUBDIR/DEPENDENCIES.txt"
   _DEP_COPIED=""

   {
      echo "Optional private dependency packages"
      echo "===================================="
      echo ""
      echo "Delivery : jetson-l4t-eg-${DEB_VERSION}"
      echo "Generated: $(date '+%Y-%m-%d %H:%M:%S %z')"
      echo ""
      echo "These packages are NOT required to build or use the MIPI camera drivers."
      echo "The driver package is identical with or without them."
      echo ""
      echo "Copy them onto the board next to the ONE driver package matching its"
      echo "L4T version, then install them together in a single apt transaction:"
      echo ""
      echo "  sudo apt install ./<driver-package>.deb \\"
      echo "      ./libecctrl-i2c_*_arm64.deb ./libecctrl-uart_*_arm64.deb ./ecswctrl_*_arm64.deb"
      echo ""
   } > "$DEP_MANIFEST"

   if [[ -d "$DEP_PKG_DIR" ]]; then
      for _dep in "$DEP_PKG_DIR"/libecctrl-i2c_*_arm64.deb \
                  "$DEP_PKG_DIR"/libecctrl-uart_*_arm64.deb \
                  "$DEP_PKG_DIR"/ecswctrl_*_arm64.deb; do
         [[ -f "$_dep" ]] || continue
         cp "$_dep" "$DELIVERY_SUBDIR/"
         _DEP_COPIED="$_DEP_COPIED $(basename "$_dep")"
         {
            echo "File: $(basename "$_dep")"
            dpkg-deb -f "$_dep" Package Version Architecture Depends 2>/dev/null | sed 's/^/  /'
            echo "  MD5: $(md5sum "$_dep" | cut -d' ' -f1)"
            echo ""
         } >> "$DEP_MANIFEST"
      done
   fi

   if [[ -n "$_DEP_COPIED" ]]; then
      echo "Private dependency packages copied:$_DEP_COPIED"
   else
      echo "" >> "$DEP_MANIFEST"
      echo "None included in this delivery." >> "$DEP_MANIFEST"
      echo "Note: no private dependency package found in $DEP_PKG_DIR"
      echo "      (expected for a public build -- the driver package is unaffected)"
   fi
else
   echo ""
   echo "Error: Package generation failed"
   exit 1
fi

#******************************************************************************
# Step 10: Verify generated package
#******************************************************************************
update_status "Verifying package..."

VERIFY_ARGS="-v $L4T_VERSION -V $VENDOR -c $CARRIER_BOARD"
[[ -n "$SOM_BOARD" ]] && VERIFY_ARGS="$VERIFY_ARGS -s $SOM_BOARD"

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
