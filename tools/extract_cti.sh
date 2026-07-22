#!/bin/bash
#******************************************************************************
# extract_cti.sh - Extract Connect Tech (CTI) precompiled kernel/nvidia-oot
# headers from a CTI BSP archive into sources/<L4T_VERSION>/Linux_for_Tegra_cti/
#
# CTI ships a precompiled kernel + nvidia-oot with no source available (see
# cti_pristine_kernel_porting.md / cti_bsp_orin_nx_analysis.md in shared memory).
# The BSP does provide two header-only .deb packages that we DO need to compile
# our own EG driver modules (dione_ir.ko, eg-ec-mipi.ko) against CTI's real
# kernel ABI, instead of our own generic-build kernel:
#
#   nvidia-l4t-kernel-headers      -> a real, configured kernel build directory
#                                     (.config, Module.symvers, scripts/) for
#                                     CTI's actual running kernel.
#   nvidia-l4t-kernel-oot-headers  -> nvidia-oot/hwpm/nvgpu headers + their real
#                                     Module.symvers (as CTI compiled them) —
#                                     headers only, no .c. Needed to resolve
#                                     symbols our drivers depend on
#                                     (tegracam_core, camera_common) via
#                                     KBUILD_EXTRA_SYMBOLS.
#
# This is NOT an EG source patch (we never modify these files) — it's a
# vendored binary/header blob, ~200MB, that must NEVER be committed to git
# (sources/*/Linux_for_Tegra_cti/cti-kdir/ and cti-oot-headers/ are
# .gitignore'd). It's regenerated on demand from the CTI archive, exactly like
# the NVIDIA BSP archives under archives/<version>/ are never committed either
# and get re-extracted by l4t_make.sh --prepare.
#
# Usage:
#   ./tools/extract_cti.sh <L4T_VERSION> [ARCHIVE_PATH]
#
# ARCHIVE_PATH (optional): exact path to the CTI archive to use — passed by
# l4t_prepare.sh, which resolves it from eg_config.yaml's
# version.<ver>.sources.cti entry (downloading it first if a `url` is
# configured there and the file isn't present yet). If omitted (manual /
# standalone use), falls back to globbing archives/CTI/*<L4T_VERSION>*.tgz
# (as placed by the user, mirroring the archives/<nvidia-version>/
# convention). Errors out clearly if the resolved archive doesn't exist.
#
# Example:
#   ./tools/extract_cti.sh 36.5.0
#   ./tools/extract_cti.sh 36.5.0 archives/CTI/CTI-L4T-ORIN-NX-NANO-36.5.0-V003.tgz
#
# Output:
#   sources/<L4T_VERSION>/Linux_for_Tegra_cti/cti-kdir/...         (kernel-headers payload)
#   sources/<L4T_VERSION>/Linux_for_Tegra_cti/cti-oot-headers/...  (kernel-oot-headers payload)
#******************************************************************************

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

if [[ $# -lt 1 ]]; then
   echo "Usage: $0 <L4T_VERSION> [ARCHIVE_PATH]"
   echo ""
   echo "Example:"
   echo "  $0 36.5.0"
   echo "  $0 36.5.0 archives/CTI/CTI-L4T-ORIN-NX-NANO-36.5.0-V003.tgz"
   echo ""
   echo "Without ARCHIVE_PATH, expects the CTI BSP archive at archives/CTI/*<L4T_VERSION>*.tgz"
   exit 1
fi

L4T_VERSION="$1"
ARCHIVE_PATH_ARG="$2"

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ARCHIVE_DIR="$ROOT_DIR/archives/CTI"
DEST="$ROOT_DIR/sources/$L4T_VERSION/Linux_for_Tegra_cti"

if [[ -n "$ARCHIVE_PATH_ARG" ]]; then
   CTI_ARCHIVE="$ARCHIVE_PATH_ARG"
   if [[ ! -f "$CTI_ARCHIVE" ]]; then
      echo -e "${RED}Error: CTI archive not found: $CTI_ARCHIVE${NC}"
      exit 1
   fi
else
   CTI_ARCHIVE=$(ls "$ARCHIVE_DIR"/*"$L4T_VERSION"*.tgz 2>/dev/null | head -1)
   if [[ -z "$CTI_ARCHIVE" ]]; then
      echo -e "${RED}Error: no CTI archive found for L4T $L4T_VERSION${NC}"
      echo "  Expected: $ARCHIVE_DIR/*${L4T_VERSION}*.tgz"
      echo "  Place the CTI BSP release archive there first (e.g. CTI-L4T-ORIN-NX-NANO-${L4T_VERSION}-V00X.tgz)."
      exit 1
   fi
fi

echo "============================================"
echo "Extracting CTI headers for L4T $L4T_VERSION"
echo "============================================"
echo "  Archive:     $(basename "$CTI_ARCHIVE")"
echo "  Destination: ${DEST#$ROOT_DIR/}"
echo ""

# Pull just the 2 needed .deb members out of the archive (it also contains the
# bootloader, kernel Image, dtbs... ~200MB we don't need here).
KHDR_MEMBER=$(tar tzf "$CTI_ARCHIVE" 2>/dev/null | grep -m1 'kernel/nvidia-l4t-kernel-headers_.*\.deb$')
OOTHDR_MEMBER=$(tar tzf "$CTI_ARCHIVE" 2>/dev/null | grep -m1 'kernel/nvidia-l4t-kernel-oot-headers_.*\.deb$')

if [[ -z "$KHDR_MEMBER" || -z "$OOTHDR_MEMBER" ]]; then
   echo -e "${RED}Error: could not find kernel-headers/kernel-oot-headers .deb inside $CTI_ARCHIVE${NC}"
   echo "  Looked for: */kernel/nvidia-l4t-kernel-headers_*.deb and */kernel/nvidia-l4t-kernel-oot-headers_*.deb"
   exit 1
fi

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

echo -e "${BLUE}Extracting .deb members from archive...${NC}"
tar xzf "$CTI_ARCHIVE" -C "$TMP" "$KHDR_MEMBER" "$OOTHDR_MEMBER"

rm -rf "$DEST/cti-kdir" "$DEST/cti-oot-headers"
mkdir -p "$DEST/cti-kdir" "$DEST/cti-oot-headers"

echo -e "${BLUE}Extracting kernel-headers...${NC}"
dpkg-deb -x "$TMP/$KHDR_MEMBER" "$DEST/cti-kdir"

echo -e "${BLUE}Extracting kernel-oot-headers...${NC}"
dpkg-deb -x "$TMP/$OOTHDR_MEMBER" "$DEST/cti-oot-headers"

# Sanity check: locate the real, configured kernel build dir inside cti-kdir
# (the actual target for KERNEL_OUTPUT/KDIR — has .config + Module.symvers).
KDIR_REAL=$(find "$DEST/cti-kdir/usr/src" -maxdepth 1 -mindepth 1 -type d -iname "linux-headers-*" 2>/dev/null | head -1)
if [[ -z "$KDIR_REAL" ]]; then
   echo -e "${YELLOW}Warning: could not locate usr/src/linux-headers-* under cti-kdir — layout may have changed for this CTI BSP version.${NC}"
else
   BUILD_LINK=$(find "$KDIR_REAL" -maxdepth 4 -type d -iname "kernel-source" 2>/dev/null | head -1)
   if [[ -n "$BUILD_LINK" && -f "$BUILD_LINK/Module.symvers" ]]; then
      echo -e "${GREEN}OK${NC}: configured kernel build dir found at:"
      echo "  ${BUILD_LINK#$ROOT_DIR/}"
   else
      echo -e "${YELLOW}Warning: expected a configured kernel-source dir with Module.symvers under $KDIR_REAL — verify manually.${NC}"
   fi
fi

if [[ ! -f "$DEST/cti-oot-headers/usr/src/nvidia/nvidia-oot/Module.symvers" ]]; then
   echo -e "${YELLOW}Warning: usr/src/nvidia/nvidia-oot/Module.symvers not found under cti-oot-headers — layout may have changed.${NC}"
else
   echo -e "${GREEN}OK${NC}: nvidia-oot/Module.symvers found (real CTI-built export symbols)."
fi

echo ""
echo "Done. These files will be picked up by l4t_copy_sources.sh's vendor layer"
echo "the next time you run --copy-sources for -V cti."
