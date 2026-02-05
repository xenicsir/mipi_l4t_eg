#!/bin/bash
#******************************************************************************
# l4t_patch_sources.sh - Apply Exosens camera patches to L4T environment
#
# This script applies pre-generated patches to a fresh L4T environment.
# Use this instead of l4t_copy_sources.sh when you want to apply patches
# without regenerating them.
#
# Usage:
#   ./l4t_patch_sources.sh -v <version> [-V <vendor>] [-c <carrier-board>]
#
# Examples:
#   ./l4t_patch_sources.sh -v 36.4.3
#   ./l4t_patch_sources.sh -v 36.4.3 -V forecr
#******************************************************************************

. environment "$@"

if [[ ! -d $L4T_VERSION/${LINUX_FOR_TEGRA_DIR} ]]; then
   echo "Error : $L4T_VERSION/${LINUX_FOR_TEGRA_DIR} folder doesn't exist"
   echo "Run l4t_prepare.sh first."
   exit 1
fi

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

L4T_DIR="$JETSON_DIR/${LINUX_FOR_TEGRA_DIR}"
PATCH_DIR=$ROOT_DIR/patches/${L4T_VERSION_EXTENDED}

if [[ ! -d "$PATCH_DIR" ]]; then
   echo "Error: Patch directory not found: $PATCH_DIR"
   echo "Run l4t_copy_sources.sh first to generate patches."
   exit 1
fi

echo "============================================"
echo "Applying Exosens camera patches for L4T ${L4T_VERSION_EXTENDED}"
echo "  Vendor: $VENDOR"
echo "  Carrier board: $CARRIER_BOARD"
echo "Patch directory: $PATCH_DIR"
echo "============================================"

cd "$L4T_DIR"

# Count patches
PATCH_COUNT=$(ls -1 "$PATCH_DIR"/*.patch 2>/dev/null | wc -l)
if [[ $PATCH_COUNT -eq 0 ]]; then
   echo "No patches found in $PATCH_DIR"
   exit 1
fi

echo ""
echo "Applying patches..."

APPLIED=0
FAILED=0

for patch_file in "$PATCH_DIR"/*.patch; do
   [[ ! -f "$patch_file" ]] && continue

   filename=$(basename "$patch_file")
   file_count=$(grep -c "^diff --git" "$patch_file" 2>/dev/null || echo 0)

   printf "  [APPLY] %s (%s files) to %s\n" "$filename" "$file_count" "$L4T_DIR"

   # Apply patch
   if sudo patch -p1 --forward --batch < "$patch_file" > /dev/null 2>&1; then
      echo "           -> Success"
      ((APPLIED++))
   else
      # Check if already applied
      if sudo patch -p1 --forward --batch --dry-run < "$patch_file" > /dev/null 2>&1; then
         echo "           -> Success (already partially applied)"
         sudo patch -p1 --forward --batch < "$patch_file" > /dev/null 2>&1 || true
         ((APPLIED++))
      else
         echo -e "           -> ${RED}ERROR: Patch does not apply cleanly${NC}"
         echo "           -> Try running on a fresh L4T environment (re-run l4t_prepare.sh)"
         ((FAILED++))
      fi
   fi
done

echo ""
echo "============================================"
if [[ $FAILED -eq 0 ]]; then
   echo -e "${GREEN}All patches applied successfully!${NC}"
   echo "  - Applied: $APPLIED patches"
else
   echo -e "${YELLOW}WARNING: $FAILED patch(es) failed to apply!${NC}"
   echo ""
   echo "This can happen if:"
   echo "  - The L4T environment was already modified"
   echo "  - The patches were generated for a different L4T version"
   echo ""
   echo "To fix, try:"
   echo "  1. Remove the L4T build directory: rm -rf $L4T_VERSION/"
   echo "  2. Re-run l4t_prepare.sh: ./l4t_prepare.sh -v $L4T_VERSION${VENDOR:+ -V $VENDOR}"
   echo "  3. Re-run this script: ./l4t_patch_sources.sh -v $L4T_VERSION${VENDOR:+ -V $VENDOR}"
   exit 1
fi

echo ""
echo "Next steps:"
echo "  1. Build the kernel and drivers:"
echo "     ./l4t_build.sh -v $L4T_VERSION${VENDOR:+ -V $VENDOR}"
echo ""
echo "  2. Generate the delivery package:"
echo "     ./l4t_gen_delivery_package.sh -v $L4T_VERSION${VENDOR:+ -V $VENDOR} -p <version>"
echo "============================================"
