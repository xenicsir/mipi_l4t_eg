#!/bin/bash
#******************************************************************************
# l4t_copy_sources.sh - Copy Exosens camera sources and generate patches
#
# This script copies source files to the L4T environment and automatically
# generates patch files for all modifications.
#
# The script is FULLY GENERIC:
#   - Git repo is created automatically if it doesn't exist
#   - .gitignore is generated dynamically based on copied files
#   - Patches are generated dynamically based on modified directories
#
# After generating patches, this script validates them by:
#   1. Resetting git to clean state
#   2. Applying patches using l4t_patch_sources.sh
#   3. Verifying the result matches the original source copy
#
# Usage:
#   ./l4t_copy_sources.sh -v <version> [-V <vendor>] [-c <carrier-board>]
#
# Examples:
#   ./l4t_copy_sources.sh -v 36.4.3
#   ./l4t_copy_sources.sh -v 36.4.3 -V forecr
#******************************************************************************

. l4t_environment.sh
l4t_init "$@"

if [[ ! -d $L4T_VERSION/${LINUX_FOR_TEGRA_DIR} ]]; then
   echo "Error : $L4T_VERSION/${LINUX_FOR_TEGRA_DIR} folder doesn't exist"
   exit 1
fi

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

L4T_DIR="$JETSON_DIR/${LINUX_FOR_TEGRA_DIR}"

# Temporary file to collect all destination paths
DEST_PATHS_FILE=$(mktemp)
trap "rm -f $DEST_PATHS_FILE" EXIT

# Note: VENDOR_SOURCE_DIR is set by environment (e.g., Linux_for_Tegra_forecr)

#******************************************************************************
# Function: Copy files with rsync and track destination paths
# Args: source_dir dest_dir dest_prefix verbose
#******************************************************************************
rsync_copy() {
   local src_dir="$1"
   local dest_dir="$2"
   local dest_prefix="$3"  # Prefix for tracking (relative to L4T_DIR)
   local verbose="$4"

   if [[ ! -d "$src_dir" ]]; then
      return
   fi

   [[ "$verbose" == "1" ]] && echo "Copying from $src_dir..."

   # Get list of files that will be copied (use itemize to get actual files)
   local files=$(rsync -a --dry-run --itemize-changes "$src_dir/" "$dest_dir/" 2>/dev/null | grep "^>f" | sed 's/^[^ ]* //')

   # Track destination paths
   for f in $files; do
      if [[ -n "$dest_prefix" ]]; then
         echo "${dest_prefix}/${f}" >> "$DEST_PATHS_FILE"
      else
         echo "$f" >> "$DEST_PATHS_FILE"
      fi
   done

   # Actually copy
   if [[ "$verbose" == "1" ]]; then
      sudo rsync -iahHAXxvz --progress "$src_dir/" "$dest_dir/"
   else
      sudo rsync -a "$src_dir/" "$dest_dir/" 2>/dev/null
   fi
}

#******************************************************************************
# Step 1: Analyze source files to copy (dry-run to get file list)
#******************************************************************************

update_status "Analyzing sources..."
echo "============================================"
echo "Analyzing Exosens sources for L4T ${L4T_VERSION_EXTENDED}"
echo "  Vendor: $VENDOR"
echo "  Carrier board: $CARRIER_BOARD"
echo "============================================"

# Function to analyze what files will be copied (list source files)
analyze_copy() {
   local src_dir="$1"
   local dest_prefix="$2"

   if [[ ! -d "$src_dir" ]]; then
      return
   fi

   # List all files and symlinks in source directory
   find "$src_dir" \( -type f -o -type l \) | while read -r filepath; do
      # Get relative path from source dir
      local relpath="${filepath#$src_dir/}"
      if [[ -n "$dest_prefix" ]]; then
         echo "${dest_prefix}/${relpath}" >> "$DEST_PATHS_FILE"
      else
         echo "$relpath" >> "$DEST_PATHS_FILE"
      fi
   done
}

# Analyze all source directories
analyze_copy "$ROOT_DIR/sources/common/Linux_for_Tegra" ""
analyze_copy "$ROOT_DIR/sources/$L4T_VERSION/Linux_for_Tegra" ""

if [[ $L4T_VERSION_MAJOR -ge 36 ]]; then
   analyze_copy "$ROOT_DIR/sources/common/source/hardware_36+" "source/hardware"
   analyze_copy "$ROOT_DIR/sources/common/source/nvidia-oot" "source/nvidia-oot"
else
   analyze_copy "$ROOT_DIR/sources/common/source/hardware_32+" "source/public/hardware"
   analyze_copy "$ROOT_DIR/sources/common/source/nvidia-oot/drivers" "source/public/kernel/nvidia/drivers"
fi

# Vendor-specific sources
if [[ -n "$VENDOR_SOURCE_DIR" ]]; then
   analyze_copy "$ROOT_DIR/sources/${L4T_VERSION}/$VENDOR_SOURCE_DIR" ""
fi

FILE_COUNT=$(wc -l < "$DEST_PATHS_FILE" 2>/dev/null || echo 0)
echo "  Found $FILE_COUNT files to copy"

#******************************************************************************
# Step 2: Generate dynamic .gitignore based on files to copy
#******************************************************************************

update_status "Generating .gitignore..."
echo ""
echo -e "${BLUE}Generating dynamic .gitignore...${NC}"

cd "$L4T_DIR"

# Extract unique directory paths that need to be tracked
TRACKED_PATHS=$(mktemp)

# For each file, add all parent directories
while IFS= read -r filepath; do
   [[ -z "$filepath" ]] && continue

   # Add the file itself
   echo "$filepath" >> "$TRACKED_PATHS"

   # Add all parent directories
   dir=$(dirname "$filepath")
   while [[ "$dir" != "." && -n "$dir" ]]; do
      echo "${dir}/" >> "$TRACKED_PATHS"
      dir=$(dirname "$dir")
   done
done < "$DEST_PATHS_FILE"

# Sort and deduplicate
sort -u "$TRACKED_PATHS" -o "$TRACKED_PATHS"

# Generate gitignore: ignore everything, then whitelist tracked paths
sudo bash -c "cat > .gitignore << 'GITIGNORE_EOF'
#=============================================================================
# Gitignore for Linux_for_Tegra - Auto-generated by l4t_copy_sources.sh
# Only tracks directories where Exosens files are copied
#=============================================================================

# Ignore everything by default
*

# Track .gitignore itself
!.gitignore

GITIGNORE_EOF"

# Add exceptions for tracked paths (directories first, then files)
while IFS= read -r path; do
   [[ -z "$path" ]] && continue
   sudo bash -c "echo '!$path' >> .gitignore"
done < "$TRACKED_PATHS"

rm -f "$TRACKED_PATHS"

#******************************************************************************
# Function: Copy all Exosens sources to L4T directory
# Args: verbose (1 or 0)
#******************************************************************************
copy_exosens_sources() {
   local verbose="$1"

   # Copy common Linux_for_Tegra files
   rsync_copy "$ROOT_DIR/sources/common/Linux_for_Tegra" "$L4T_DIR" "" "$verbose"

   # Copy version-specific Linux_for_Tegra files
   rsync_copy "$ROOT_DIR/sources/$L4T_VERSION/Linux_for_Tegra" "$L4T_DIR" "" "$verbose"

   # Copy common source files based on L4T major version
   if [[ $L4T_VERSION_MAJOR -ge 36 ]]; then
      # L4T 36.x structure
      rsync_copy "$ROOT_DIR/sources/common/source/hardware_36+" "$L4T_DIR/source/hardware" "source/hardware" "$verbose"
      rsync_copy "$ROOT_DIR/sources/common/source/nvidia-oot" "$L4T_DIR/source/nvidia-oot" "source/nvidia-oot" "$verbose"
   else
      # L4T 32.x/35.x structure
      rsync_copy "$ROOT_DIR/sources/common/source/hardware_32+" "$L4T_DIR/source/public/hardware" "source/public/hardware" "$verbose"
      rsync_copy "$ROOT_DIR/sources/common/source/nvidia-oot/drivers" "$L4T_DIR/source/public/kernel/nvidia/drivers" "source/public/kernel/nvidia/drivers" "$verbose"
   fi

   # Copy vendor-specific files
   if [[ -n "$VENDOR_SOURCE_DIR" ]]; then
      rsync_copy "$ROOT_DIR/sources/${L4T_VERSION}/$VENDOR_SOURCE_DIR" "$L4T_DIR" "" "$verbose"
   fi
}

TRACKED_COUNT=$(grep -c '^!' .gitignore)
echo "  Generated .gitignore with $TRACKED_COUNT tracked paths"

#******************************************************************************
# Step 3: Initialize or update git repository (BEFORE copying sources)
#******************************************************************************

update_status "Preparing git repository..."
echo ""
echo -e "${BLUE}Preparing git repository...${NC}"

# Git config for automated commits
git config --global user.email "build@exosens.com" 2>/dev/null || true
git config --global user.name "Exosens Build System" 2>/dev/null || true
sudo git config --global user.email "build@exosens.com" 2>/dev/null || true
sudo git config --global user.name "Exosens Build System" 2>/dev/null || true

# Add safe.directory
git config --global --add safe.directory "$L4T_DIR" 2>/dev/null || true
sudo git config --global --add safe.directory "$L4T_DIR" 2>/dev/null || true

if [[ ! -d "$L4T_DIR/.git" ]]; then
   echo "  Creating new git repository..."

   sudo git init
   sudo git add .gitignore
   sudo git commit -m "Initial gitignore"

   # Commit original BSP files that exist in tracked paths
   # This ensures patches for MODIFIED files show diffs (not "new file")
   echo "  Committing original BSP files in tracked paths..."
   sudo git add -A
   if ! sudo git diff --cached --quiet 2>/dev/null; then
      sudo git commit -m "Initial state - Nvidia L4T ${L4T_VERSION} BSP"
   fi
else
   echo "  Git repository already exists, resetting to initial state..."

   # Find "Initial state" commit (preferred) or "Initial gitignore" commit
   INITIAL_COMMIT=$(sudo git log --oneline | grep "Initial state - Nvidia L4T" | head -1 | cut -d' ' -f1)
   if [[ -z "$INITIAL_COMMIT" ]]; then
      INITIAL_COMMIT=$(sudo git log --oneline | grep "Initial gitignore" | head -1 | cut -d' ' -f1)
   fi

   if [[ -n "$INITIAL_COMMIT" ]]; then
      sudo git reset --hard "$INITIAL_COMMIT"
   else
      # Fallback: just clean up
      sudo git checkout -- . 2>/dev/null || true
      sudo git clean -fd 2>/dev/null || true
   fi

   # Update .gitignore if changed
   sudo git add .gitignore
   if ! sudo git diff --cached --quiet .gitignore 2>/dev/null; then
      sudo git commit -m "Update gitignore" 2>/dev/null || true
   fi

   # Ensure "Initial state" commit exists with original BSP files
   if ! sudo git log --oneline | grep -q "Initial state - Nvidia L4T"; then
      sudo git add -A
      if ! sudo git diff --cached --quiet 2>/dev/null; then
         sudo git commit -m "Initial state - Nvidia L4T ${L4T_VERSION} BSP"
      fi
   fi
fi

#******************************************************************************
# Step 3b: Merge Exosens defconfig into vendor sources (BEFORE copying)
#
# For vendor carrier boards on L4T 35.x, we need to merge any Exosens-specific
# CONFIG options from the generic defconfig into all vendor *_defconfig files
# in the sources/ directory BEFORE copying to the working directory.
#******************************************************************************

if [[ "$VENDOR" == "forecr" && $L4T_VERSION_MAJOR -lt 36 ]]; then
   update_status "Merging defconfigs..."
   echo ""
   echo "============================================"
   echo "Merging Exosens defconfig into ${VENDOR} sources"
   echo "============================================"

   # Paths for L4T 35.x
   KERNEL_SUBDIR="kernel-5.10"
   NVIDIA_DEFCONFIG="$ROOT_DIR/sources/$L4T_VERSION/Linux_for_Tegra/source/public/kernel/$KERNEL_SUBDIR/arch/arm64/configs/defconfig"
   SOURCE_CONFIGS_DIR="$ROOT_DIR/sources/$L4T_VERSION/$VENDOR_SOURCE_DIR/source/public/kernel/$KERNEL_SUBDIR/arch/arm64/configs"
   VENDOR_REF="$SOURCE_CONFIGS_DIR/defconfig.vendor_reference"

   if [[ -f "$NVIDIA_DEFCONFIG" && -d "$SOURCE_CONFIGS_DIR" ]]; then
      echo "  Generic defconfig: $NVIDIA_DEFCONFIG"
      echo "  Vendor sources dir: $SOURCE_CONFIGS_DIR"

      # Check if vendor reference exists
      if [[ -f "$VENDOR_REF" ]]; then
         echo "  Vendor reference: $VENDOR_REF"
         echo ""

         # Extract Exosens-specific CONFIG options
         # (present in generic but not in vendor reference)
         EXOSENS_CONFIGS=()
         while IFS= read -r line; do
            [[ -z "$line" ]] && continue
            [[ "$line" =~ ^# ]] && continue
            if [[ "$line" =~ ^CONFIG_ ]]; then
               config_name=$(echo "$line" | cut -d'=' -f1)
               if ! grep -q "^${config_name}=" "$VENDOR_REF" 2>/dev/null; then
                  EXOSENS_CONFIGS+=("$line")
               fi
            fi
         done < "$NVIDIA_DEFCONFIG"

         if [[ ${#EXOSENS_CONFIGS[@]} -gt 0 ]]; then
            echo "  Exosens CONFIG options to merge:"
            for config in "${EXOSENS_CONFIGS[@]}"; do
               echo "    $config"
            done
            echo ""

            # Apply to all *_defconfig files in sources/
            merged_count=0
            total_configs_added=0

            for defconfig_file in "$SOURCE_CONFIGS_DIR"/*_defconfig; do
               [[ ! -f "$defconfig_file" ]] && continue
               [[ "$(basename "$defconfig_file")" == "defconfig.vendor_reference" ]] && continue

               filename=$(basename "$defconfig_file")
               configs_added=0

               for config in "${EXOSENS_CONFIGS[@]}"; do
                  config_name=$(echo "$config" | cut -d'=' -f1)
                  if ! grep -q "^${config_name}=" "$defconfig_file" 2>/dev/null; then
                     echo "$config" >> "$defconfig_file"
                     configs_added=$((configs_added + 1))
                  fi
               done

               if [[ $configs_added -gt 0 ]]; then
                  echo "  MERGED: $filename (+$configs_added configs)"
                  merged_count=$((merged_count + 1))
                  total_configs_added=$((total_configs_added + configs_added))
               fi
            done

            echo ""
            if [[ $merged_count -gt 0 ]]; then
               echo -e "${GREEN}  Defconfig merge complete: $merged_count files updated ($total_configs_added configs added)${NC}"
            else
               echo -e "${GREEN}  All vendor defconfigs are already up to date${NC}"
            fi
         else
            echo "  No new Exosens CONFIG options to merge."
         fi
      else
         echo -e "${YELLOW}  WARNING: Vendor reference not found: $VENDOR_REF${NC}"
         echo "  Run extract_forecr_sources.sh first to create the vendor reference."
      fi
   fi
fi

#******************************************************************************
# Step 4: Copy Exosens sources (after git init with original state)
#******************************************************************************

update_status "Copying Exosens sources..."
echo ""
echo "============================================"
echo "Copying Exosens sources for L4T ${L4T_VERSION_EXTENDED}"
echo "============================================"

copy_exosens_sources "1"

echo ""
echo "  Copy complete"

#******************************************************************************
# Step 5: Generate patches dynamically based on modified directories
#******************************************************************************

PATCH_DIR=$ROOT_DIR/patches/${L4T_VERSION_EXTENDED}
mkdir -p $PATCH_DIR

# Clean old patches
rm -f $PATCH_DIR/*.patch

update_status "Generating patches..."
echo ""
echo "============================================"
echo "Generating patches in $PATCH_DIR"
echo "============================================"

cd "$L4T_DIR"

# Stage all changes
sudo git add -A

# Get list of all modified files
MODIFIED_FILES=$(sudo git diff --cached --name-only HEAD 2>/dev/null)

if [[ -z "$MODIFIED_FILES" ]]; then
   echo "No modifications detected."
   sudo git reset --quiet HEAD 2>/dev/null || true
   exit 0
fi

echo ""
echo "Modified components:"
TOTAL_PATCHES=0

# Function to generate patch for files matching a pattern
generate_patch() {
   local patch_name=$1
   local pattern=$2
   local patch_file="$PATCH_DIR/${patch_name}.patch"

   local files=$(echo "$MODIFIED_FILES" | grep -E "$pattern" || true)

   if [[ -n "$files" ]]; then
      echo "$files" | sudo xargs git diff --cached --no-color HEAD -- > "$patch_file" 2>/dev/null

      if [[ -s "$patch_file" ]]; then
         local lines=$(wc -l < "$patch_file")
         local file_count=$(echo "$files" | wc -l)
         echo "  [OK] ${patch_name}.patch ($file_count files, $lines lines)"
         ((TOTAL_PATCHES++))
         # Remove matched files from MODIFIED_FILES to avoid duplicates
         MODIFIED_FILES=$(echo "$MODIFIED_FILES" | grep -v -E "$pattern" || true)
         return 0
      else
         rm -f "$patch_file"
      fi
   fi
   return 1
}

# Generate patches with patterns ordered by specificity (most specific first)
# Each pattern is tried in order; files matching earlier patterns are removed

# Source: nvidia-oot deep paths (L4T 36.x)
generate_patch "source_nvidia-oot_drivers_media_i2c" "^source/nvidia-oot/drivers/media/i2c/"
generate_patch "source_nvidia-oot_drivers_media_platform" "^source/nvidia-oot/drivers/media/platform/"
generate_patch "source_nvidia-oot_include_media" "^source/nvidia-oot/include/media/"
generate_patch "source_nvidia-oot" "^source/nvidia-oot/"

# Source: public deep paths (L4T 32.x/35.x)
generate_patch "source_public_kernel_nvidia_drivers_media_i2c" "^source/public/kernel/nvidia/drivers/media/i2c/"
generate_patch "source_public_kernel_nvidia_drivers_media_platform" "^source/public/kernel/nvidia/drivers/media/platform/"
generate_patch "source_public_kernel_nvidia_include_media" "^source/public/kernel/nvidia/include/media/"
generate_patch "source_public_kernel" "^source/public/kernel/"
generate_patch "source_public_hardware" "^source/public/hardware/"

# Source: other directories
generate_patch "source_hardware" "^source/hardware/"
generate_patch "source_kernel" "^source/kernel/"

# Rootfs paths
generate_patch "rootfs_opt_eg" "^rootfs/opt/eg/"
generate_patch "rootfs_opt_nvidia" "^rootfs/opt/nvidia/"
generate_patch "rootfs_usr_bin" "^rootfs/usr/bin/"
generate_patch "rootfs_usr" "^rootfs/usr/"
generate_patch "rootfs_opt" "^rootfs/opt/"
generate_patch "rootfs" "^rootfs/"

# Source root files (like source/Makefile)
generate_patch "source" "^source/[^/]+$"

# Catch-all for any remaining source/* directories not matched above
for subdir in $(echo "$MODIFIED_FILES" | grep "^source/" | cut -d'/' -f1-2 | sort -u); do
   [[ -z "$subdir" ]] && continue
   patch_name=$(echo "$subdir" | tr '/' '_')
   generate_patch "$patch_name" "^${subdir}/"
done

# Catch-all for any remaining top-level directories
for toplevel in $(echo "$MODIFIED_FILES" | cut -d'/' -f1 | sort -u); do
   [[ -z "$toplevel" ]] && continue
   [[ "$toplevel" == "source" || "$toplevel" == "rootfs" ]] && continue
   generate_patch "$toplevel" "^${toplevel}/"
done

# Reset staging area
sudo git reset --quiet HEAD 2>/dev/null || true

# Generate README
cat > $PATCH_DIR/README.txt << EOF
Exosens MIPI Camera Patches for L4T ${L4T_VERSION_EXTENDED}
============================================================

These patches were automatically generated by l4t_copy_sources.sh.
They represent all modifications made to the original Nvidia L4T $L4T_VERSION BSP
to add support for Exosens cameras.

Vendor: $VENDOR
Carrier board: $CARRIER_BOARD

Total patches: $TOTAL_PATCHES

Patch files:
EOF

for patch_file in $PATCH_DIR/*.patch; do
   if [[ -f "$patch_file" ]]; then
      filename=$(basename "$patch_file")
      lines=$(wc -l < "$patch_file")
      file_count=$(grep -c "^diff --git" "$patch_file" || echo 0)
      echo "  - $filename ($file_count files, $lines lines)" >> $PATCH_DIR/README.txt
   fi
done

cat >> $PATCH_DIR/README.txt << EOF

Usage:
  To apply these patches instead of using l4t_copy_sources.sh, run:
  ./l4t_patch_sources.sh -v $L4T_VERSION${VENDOR:+ -V $VENDOR}${CARRIER_BOARD:+ -c $CARRIER_BOARD}

  The patches are applied to the L4T environment prepared by l4t_prepare.sh.
EOF

echo ""
echo "============================================"
echo "Generated $TOTAL_PATCHES patches in $PATCH_DIR"
echo "============================================"
ls -la $PATCH_DIR/

#******************************************************************************
# Step 6: Verify patches by applying them to a clean state
#******************************************************************************

update_status "Verifying patches..."
echo ""
echo "============================================"
echo "Verifying patches..."
echo "============================================"

# Re-read modified files for verification (we consumed them during patch generation)
cd "$L4T_DIR"
sudo git add -A
EXPECTED_FILES=$(sudo git diff --cached --name-only HEAD 2>/dev/null | sort)
sudo git reset --quiet HEAD 2>/dev/null || true

# Reset to clean state
echo "Resetting git to clean state..."
sudo git checkout -- . 2>/dev/null || true
sudo git clean -fd 2>/dev/null || true

# Apply patches using l4t_patch_sources.sh
echo ""
echo "Applying patches with l4t_patch_sources.sh..."
cd "$ROOT_DIR"

# Build the argument list for l4t_patch_sources.sh (same as original call)
PATCH_ARGS="-v $L4T_VERSION"
[[ "$VENDOR" != "generic" ]] && PATCH_ARGS="$PATCH_ARGS -V $VENDOR"
[[ "$CARRIER_BOARD" != "generic" ]] && PATCH_ARGS="$PATCH_ARGS -c $CARRIER_BOARD"

if ! "$ROOT_DIR/l4t_patch_sources.sh" $PATCH_ARGS; then
   echo ""
   echo -e "${RED}ERROR: l4t_patch_sources.sh failed!${NC}"
   echo "Patches were generated but could not be applied."
   exit 1
fi

# Verify the result
echo ""
echo "Verifying patch coverage..."
cd "$L4T_DIR"

sudo git add -A
ACTUAL_FILES=$(sudo git diff --cached --name-only HEAD 2>/dev/null | sort)
sudo git reset --quiet HEAD 2>/dev/null || true

# Compare expected vs actual
MISSING=$(comm -23 <(echo "$EXPECTED_FILES") <(echo "$ACTUAL_FILES") | grep -v "^$" || true)
EXTRA=$(comm -13 <(echo "$EXPECTED_FILES") <(echo "$ACTUAL_FILES") | grep -v "^$" || true)

ERRORS=0

if [[ -n "$MISSING" ]]; then
   missing_count=$(echo "$MISSING" | grep -c "." 2>/dev/null || echo 0)
   echo -e "${RED}Files expected but NOT applied by patches ($missing_count):${NC}"
   echo "$MISSING" | head -10 | while read f; do
      [[ -n "$f" ]] && echo "  - $f"
   done
   [[ $missing_count -gt 10 ]] && echo "  ... and $((missing_count - 10)) more"
   ERRORS=$((ERRORS + missing_count))
fi

if [[ -n "$EXTRA" ]]; then
   extra_count=$(echo "$EXTRA" | grep -c "." 2>/dev/null || echo 0)
   echo -e "${YELLOW}Extra files applied by patches but not in sources ($extra_count):${NC}"
   echo "$EXTRA" | head -10 | while read f; do
      [[ -n "$f" ]] && echo "  - $f"
   done
   [[ $extra_count -gt 10 ]] && echo "  ... and $((extra_count - 10)) more"
fi

echo ""
echo "============================================"
if [[ $ERRORS -eq 0 ]]; then
   echo -e "${GREEN}SUCCESS: All patches verified!${NC}"
   echo ""
   echo "  Patches generated: $TOTAL_PATCHES"
   echo "  Files covered:     $(echo "$EXPECTED_FILES" | grep -c "." 2>/dev/null || echo 0)"
else
   echo -e "${RED}VERIFICATION FAILED!${NC}"
   echo ""
   echo "  Errors: $ERRORS files not covered by patches"
   echo ""
   echo "This indicates a bug in patch generation."
   exit 1
fi
echo "============================================"

#******************************************************************************
# Step 7: Show summary of Exosens modifications
#******************************************************************************

echo ""
echo "============================================"
echo "Exosens modifications ($(echo "$ACTUAL_FILES" | grep -c '.' 2>/dev/null || echo 0) files):"
echo "============================================"
echo "$ACTUAL_FILES" | head -20
FILE_COUNT=$(echo "$ACTUAL_FILES" | grep -c '.' 2>/dev/null || echo 0)
if [[ $FILE_COUNT -gt 20 ]]; then
   echo "... and $((FILE_COUNT - 20)) more files"
fi

update_status "Done"
echo ""
echo "Next steps:"
echo "  1. Build the kernel and drivers:"
echo "     ./l4t_build.sh -v $L4T_VERSION${VENDOR:+ -V $VENDOR}"
echo ""
echo "  2. Generate the delivery package:"
echo "     ./l4t_gen_delivery_package.sh -v $L4T_VERSION${VENDOR:+ -V $VENDOR} -p <version>"
echo "============================================"
