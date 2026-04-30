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

. l4t_environment.sh
l4t_init "$@"

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

# For 32.x the SoM (t210/t186) is not included in L4T_VERSION_EXTENDED — add it explicitly
PATCH_NAME="${L4T_VERSION_EXTENDED}${SOM_BOARD:+_${SOM_BOARD}}"
PATCH_FILE="$ROOT_DIR/patches/${PATCH_NAME}.patch"

if [[ ! -f "$PATCH_FILE" ]]; then
   echo "Error: Patch file not found: $PATCH_FILE"
   echo "Run l4t_copy_sources.sh first to generate the patch."
   exit 1
fi

echo "============================================"
echo "Applying Exosens camera patch for L4T ${L4T_VERSION_EXTENDED}"
echo "  Vendor: $VENDOR"
echo "  Carrier board: $CARRIER_BOARD"
echo "  Patch: $PATCH_FILE"
echo "============================================"

cd "$L4T_DIR"

file_count=$(grep -c "^diff --git" "$PATCH_FILE" 2>/dev/null || echo 0)
printf "  [APPLY] %s.patch (%s files)\n" "${PATCH_NAME}" "$file_count"

# Apply patch (sudo needed: L4T files are root-owned in a fresh environment)
if sudo patch -p1 --forward --batch < "$PATCH_FILE" > /dev/null 2>&1; then
   echo -e "           -> ${GREEN}Success${NC}"
else
   # Check if already applied
   if sudo patch -p1 --forward --batch --dry-run < "$PATCH_FILE" > /dev/null 2>&1; then
      echo -e "           -> ${YELLOW}Already applied${NC}"
   else
      echo -e "           -> ${RED}ERROR: Patch does not apply cleanly${NC}"
      echo "           -> Try running on a fresh L4T environment (re-run l4t_prepare.sh)"
      exit 1
   fi
fi

echo ""
echo "============================================"
echo -e "${GREEN}Patch applied successfully!${NC}"

echo ""
echo "Next steps:"
echo "  1. Build the kernel and drivers:"
echo "     ./l4t_build.sh -v $L4T_VERSION${VENDOR:+ -V $VENDOR}"
echo ""
echo "  2. Generate the delivery package:"
echo "     ./l4t_gen_delivery_package.sh -v $L4T_VERSION${VENDOR:+ -V $VENDOR} [-p <version>]"
echo "============================================"
