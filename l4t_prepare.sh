#!/bin/bash
#******************************************************************************
# l4t_prepare.sh - Prepare L4T environment for Exosens camera builds
#
# This script downloads and extracts the NVIDIA L4T BSP, toolchain, and
# kernel sources.
#
# Usage:
#   ./l4t_prepare.sh -v <version> [-V <vendor>] [-c <carrier-board>]
#
# Examples:
#   ./l4t_prepare.sh -v 36.4.3
#   ./l4t_prepare.sh -v 36.4.3 -V forecr
#   ./l4t_prepare.sh --l4t-version 36.4.3 --vendor forecr --carrier-board dsboard_ornx
#
# Performance:
#   Install parallel decompression tools for faster extraction:
#     sudo apt install lbzip2 pigz
#******************************************************************************

. l4t_environment.sh
l4t_init "$@"

#******************************************************************************
# Optimized tar extraction using parallel decompression when available
# Usage: fast_tar_extract <archive_file>
#******************************************************************************
fast_tar_extract() {
    local archive="$1"
    local ext="${archive##*.}"

    case "$ext" in
        tbz2|bz2)
            # Use parallel bzip2 if available (lbzip2 is fastest)
            if command -v lbzip2 &>/dev/null; then
                tar -I lbzip2 -xf "$archive"
            elif command -v pbzip2 &>/dev/null; then
                tar -I pbzip2 -xf "$archive"
            else
                tar -xjf "$archive"
            fi
            ;;
        tgz|gz)
            # Use parallel gzip if available
            if command -v pigz &>/dev/null; then
                tar -I pigz -xf "$archive"
            else
                tar -xzf "$archive"
            fi
            ;;
        xz)
            # Use parallel xz if available
            if command -v pixz &>/dev/null; then
                tar -I pixz -xf "$archive"
            else
                tar -xJf "$archive"
            fi
            ;;
        *)
            tar -xf "$archive"
            ;;
    esac
}

# Show which decompression tools are available
echo "Decompression tools: $(command -v lbzip2 >/dev/null && echo 'lbzip2' || echo 'bzip2') | $(command -v pigz >/dev/null && echo 'pigz' || echo 'gzip')"

update_status "Initializing..."
mkdir -p $JETSON_DIR

# PKG_ARCHIVE_DIR may include a SoM subdir (e.g. archives/32.7.1/t186/)
# when the version ships separate BSP packages per SoM (sources_by_som).
mkdir -p "$PKG_ARCHIVE_DIR"

#----------------------#
# Get the Nvidia SDK   #
#----------------------#
cd ${JETSON_DIR}

if [[ ! -f $PKG_ARCHIVE_DIR/${L4T_RELEASE_PACKAGE} ]]; then
   update_status "Downloading BSP..."
   wget -q $L4T_RELEASE_PACKAGE_URL -O $PKG_ARCHIVE_DIR/${L4T_RELEASE_PACKAGE}
fi
if [[ ! -f $PKG_ARCHIVE_DIR/${SAMPLE_FS_PACKAGE} ]]; then
   update_status "Downloading rootfs..."
   wget -q $SAMPLE_FS_PACKAGE_URL -O $PKG_ARCHIVE_DIR/${SAMPLE_FS_PACKAGE}
fi
if [[ ! -f $PKG_ARCHIVE_DIR/${JETSON_PUBLIC_SOURCES} ]]; then
   update_status "Downloading sources..."
   wget -q $JETSON_PUBLIC_SOURCES_URL -O $PKG_ARCHIVE_DIR/${JETSON_PUBLIC_SOURCES}
fi

if [[ -f $JETSON_DIR/$LINUX_FOR_TEGRA_DIR/.bsp_done ]]; then
   update_status "BSP already set up, skipping"
else
   # Clean up any partial previous attempt
   sudo rm -rf $JETSON_DIR/tmp_$LINUX_FOR_TEGRA_DIR
   if [[ ! -d $JETSON_DIR/$LINUX_FOR_TEGRA_DIR ]]; then
      mkdir $JETSON_DIR/tmp_$LINUX_FOR_TEGRA_DIR
      cd $JETSON_DIR/tmp_$LINUX_FOR_TEGRA_DIR
      update_status "Extracting BSP..."
      fast_tar_extract "$PKG_ARCHIVE_DIR/${L4T_RELEASE_PACKAGE}"
      sudo mv Linux_for_Tegra $JETSON_DIR/$LINUX_FOR_TEGRA_DIR
      cd $JETSON_DIR
      sudo rm -rf tmp_$LINUX_FOR_TEGRA_DIR
   fi
   cd ${JETSON_DIR}/${LINUX_FOR_TEGRA_DIR}/rootfs/
   update_status "Extracting rootfs..."
   sudo tar -I lbzip2 -xpf "$PKG_ARCHIVE_DIR/${SAMPLE_FS_PACKAGE}" 2>/dev/null \
      || sudo tar -xpjf "$PKG_ARCHIVE_DIR/${SAMPLE_FS_PACKAGE}"
   cd ..
   update_status "Applying binaries..."
   sudo ./apply_binaries.sh > /dev/null 2>&1
   touch $JETSON_DIR/$LINUX_FOR_TEGRA_DIR/.bsp_done
fi

# Get toolchain
# The toolchain is shared across all vendor builds for a given L4T version.
# Use a version-scoped lock to avoid races when multiple vendors run --prepare
# in parallel (e.g. generic + forecr for the same version).
cd $JETSON_DIR
if [[ ! -f $ARCHIVE_DIR/$L4T_VERSION/${JETSON_TOOCHAIN_ARCHIVE} ]]; then
   update_status "Downloading toolchain..."
   wget -q $JETSON_TOOCHAIN_ARCHIVE_URL -O $ARCHIVE_DIR/$L4T_VERSION/${JETSON_TOOCHAIN_ARCHIVE}
fi
(
   flock -x 200
   if [[ -f $JETSON_DIR/.toolchain_done ]]; then
      update_status "Toolchain already extracted, skipping"
   else
      rm -rf $JETSON_DIR/$TOOLCHAIN_DIR
      mkdir $JETSON_DIR/$TOOLCHAIN_DIR
      cd $JETSON_DIR/$TOOLCHAIN_DIR
      update_status "Extracting toolchain..."
      fast_tar_extract "$ARCHIVE_DIR/$L4T_VERSION/$JETSON_TOOCHAIN_ARCHIVE"
      cd $JETSON_DIR
      touch .toolchain_done
   fi
) 200>"$JETSON_DIR/.toolchain_lock"

# Decompress Linux sources
cd $JETSON_DIR

if [[ -f $JETSON_DIR/$LINUX_FOR_TEGRA_DIR/.public_sources_done ]]; then
   update_status "Public sources already extracted, skipping"
else
   sudo rm -rf tmp_$LINUX_FOR_TEGRA_DIR
   mkdir tmp_$LINUX_FOR_TEGRA_DIR
   cd tmp_$LINUX_FOR_TEGRA_DIR
   update_status "Extracting public sources..."
   fast_tar_extract "$PKG_ARCHIVE_DIR/${JETSON_PUBLIC_SOURCES}"
   update_status "Copying sources..."
   rsync -aHAX Linux_for_Tegra/* ../${LINUX_FOR_TEGRA_DIR}/
   cd $JETSON_DIR
   sudo rm -rf tmp_$LINUX_FOR_TEGRA_DIR
   touch $JETSON_DIR/$LINUX_FOR_TEGRA_DIR/.public_sources_done
fi

cd $ROOT_DIR
# Re-initialize to update L4T_SRC path after extraction
. l4t_environment.sh
l4t_init "$@"
cd $L4T_SRC
mkdir -p build
mkdir -p modules

if [[ -f .kernel_src_done ]]; then
   update_status "Kernel sources already extracted, skipping"
else
   rm -rf kernel
   update_status "Extracting kernel sources..."
   fast_tar_extract kernel_src.tbz2
   touch .kernel_src_done
fi

if [[ -f kernel_oot_modules_src.tbz2 ]]; then
   if [[ -f .kernel_oot_done ]]; then
      update_status "OOT modules already extracted, skipping"
   else
      rm -rf nvidia-oot kernel-devicetree
      update_status "Extracting OOT modules..."
      fast_tar_extract kernel_oot_modules_src.tbz2
      touch .kernel_oot_done
   fi
fi
if [[ -f nvidia_kernel_display_driver_source.tbz2 ]]; then
   if [[ -f .nvidia_display_driver_done ]]; then
      update_status "Display driver already extracted, skipping"
   else
      rm -rf nvdisplay
      update_status "Extracting display driver..."
      fast_tar_extract nvidia_kernel_display_driver_source.tbz2
      touch .nvidia_display_driver_done
   fi
fi

update_status "Done"
echo ""
echo "============================================"
echo "L4T ${L4T_VERSION_EXTENDED} environment prepared successfully"
echo "============================================"
echo ""
echo "Next steps:"
echo "  1. Copy Exosens sources:"
echo "     ./l4t_copy_sources.sh -v $L4T_VERSION${VENDOR:+ -V $VENDOR}${CARRIER_BOARD:+ -c $CARRIER_BOARD}"
echo ""
# NOTE: patch-sources step is disabled (patches/ directory removed).
# echo "  2. Or apply patches directly:"
# echo "     ./l4t_patch_sources.sh -v $L4T_VERSION${VENDOR:+ -V $VENDOR}${CARRIER_BOARD:+ -c $CARRIER_BOARD}"
echo "============================================"
