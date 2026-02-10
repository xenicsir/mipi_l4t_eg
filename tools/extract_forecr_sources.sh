#!/bin/bash
#******************************************************************************
# extract_forecr_sources.sh - Extract Forecr-specific files from vendor kernel
#
# This script compares a Forecr vendor kernel repository against the original
# Nvidia BSP sources and extracts only the files that are new or modified.
# The extracted files are placed in the sources/ directory structure ready
# for use with l4t_copy_sources.sh.
#
# Supports both L4T 35.x and 36.x directory structures:
#   - L4T 35.x: source/public/ contains hardware/, kernel/
#   - L4T 36.x: source/ contains hardware/, kernel/, nvidia-oot/, kernel-devicetree/, etc.
#
# Usage:
#   ./tools/extract_forecr_sources.sh <L4T_VERSION> <FORECR_KERNEL_PATH>
#
# Examples:
#   ./tools/extract_forecr_sources.sh 35.6.0 ~/jetson/forecr_xavier_kernel
#   ./tools/extract_forecr_sources.sh 36.4.4 ~/jetson/forecr_xavier_kernel-6.2.1
#
# Prerequisites:
#   1. Original Nvidia BSP must be extracted in one of:
#      - $ROOT_DIR/$L4T_VERSION/Linux_for_Tegra_forecr_*/source/
#      - $ROOT_DIR/$L4T_VERSION/Linux_for_Tegra_forecr/source/
#   2. Forecr vendor kernel must contain relevant source directories
#
# Output:
#   Files are copied to:
#   - $ROOT_DIR/sources/$L4T_VERSION/Linux_for_Tegra_forecr/source/[public/]
#
#******************************************************************************

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

#******************************************************************************
# Parse arguments
#******************************************************************************

if [[ $# -lt 2 ]]; then
    echo "Usage: $0 <L4T_VERSION> <FORECR_KERNEL_PATH>"
    echo ""
    echo "Arguments:"
    echo "  L4T_VERSION        L4T version (e.g., 35.6.0, 36.4.4)"
    echo "  FORECR_KERNEL_PATH Path to Forecr vendor kernel repository"
    echo ""
    echo "Examples:"
    echo "  $0 35.6.0 ~/jetson/forecr_xavier_kernel"
    echo "  $0 36.4.4 ~/jetson/forecr_xavier_kernel-6.2.1"
    echo ""
    echo "Supported directory structures:"
    echo "  L4T 35.x: hardware/, kernel/"
    echo "  L4T 36.x: hardware/, kernel/, nvidia-oot/, kernel-devicetree/, hwpm/, nvdisplay/, nvethernetrm/, nvgpu/"
    exit 1
fi

L4T_VERSION="$1"
FORECR_SRC="$2"

# Expand ~ in path
FORECR_SRC="${FORECR_SRC/#\~/$HOME}"

# Determine root directory (parent of tools/)
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

# Extract major version number
L4T_MAJOR=$(echo "$L4T_VERSION" | cut -d'.' -f1)

#******************************************************************************
# Find Nvidia BSP directory (supports both naming conventions)
#******************************************************************************
find_nvidia_bsp_dir() {
    local version_dir="$ROOT_DIR/$L4T_VERSION"

    # First try: Linux_for_Tegra_forecr_* (new naming with carrier board)
    for dir in "$version_dir"/Linux_for_Tegra_forecr_*/; do
        if [[ -d "$dir" ]]; then
            echo "$dir"
            return 0
        fi
    done

    # Fallback: Linux_for_Tegra_forecr (old naming)
    if [[ -d "$version_dir/Linux_for_Tegra_forecr" ]]; then
        echo "$version_dir/Linux_for_Tegra_forecr"
        return 0
    fi

    return 1
}

#******************************************************************************
# Determine paths based on L4T version
#******************************************************************************

# Find Nvidia BSP directory
NVIDIA_BSP_DIR=$(find_nvidia_bsp_dir)
if [[ -z "$NVIDIA_BSP_DIR" ]]; then
    echo -e "${RED}ERROR: Nvidia BSP not found${NC}"
    echo ""
    echo "Expected one of:"
    echo "  - $ROOT_DIR/$L4T_VERSION/Linux_for_Tegra_forecr_*/"
    echo "  - $ROOT_DIR/$L4T_VERSION/Linux_for_Tegra_forecr/"
    echo ""
    echo "Please ensure the original Nvidia BSP is extracted."
    echo "Run: ./l4t_prepare.sh -v $L4T_VERSION -V forecr"
    exit 1
fi

# Remove trailing slash if present
NVIDIA_BSP_DIR="${NVIDIA_BSP_DIR%/}"

if [[ $L4T_MAJOR -ge 36 ]]; then
    # L4T 36.x structure: source/ (no public subdirectory)
    NVIDIA_SRC="$NVIDIA_BSP_DIR/source"
    DEST="$ROOT_DIR/sources/$L4T_VERSION/Linux_for_Tegra_forecr/source"

    # Directories to process for L4T 36.x
    SUBDIRS=(
        "hardware"
        "kernel"
        "kernel-devicetree"
        "nvidia-oot"
        "hwpm"
        "nvdisplay"
        "nvethernetrm"
        "nvgpu"
    )
else
    # L4T 35.x and earlier structure: source/public/
    NVIDIA_SRC="$NVIDIA_BSP_DIR/source/public"
    DEST="$ROOT_DIR/sources/$L4T_VERSION/Linux_for_Tegra_forecr/source/public"

    # Directories to process for L4T 35.x
    SUBDIRS=(
        "hardware"
        "kernel"
    )
fi

#******************************************************************************
# Validate inputs
#******************************************************************************

echo -e "${BLUE}=============================================="
echo "Extract Forecr Sources for L4T $L4T_VERSION"
echo -e "==============================================${NC}"
echo ""
echo -e "${CYAN}L4T Major Version: $L4T_MAJOR${NC}"
echo ""

# Check Forecr source exists
if [[ ! -d "$FORECR_SRC" ]]; then
    echo -e "${RED}ERROR: Forecr kernel path does not exist: $FORECR_SRC${NC}"
    exit 1
fi

# Check that at least one expected directory exists in Forecr source
found_subdir=0
for subdir in "${SUBDIRS[@]}"; do
    if [[ -d "$FORECR_SRC/$subdir" ]]; then
        found_subdir=1
        break
    fi
done

if [[ $found_subdir -eq 0 ]]; then
    echo -e "${RED}ERROR: Forecr kernel path must contain at least one of: ${SUBDIRS[*]}${NC}"
    exit 1
fi

# Check Nvidia BSP exists
if [[ ! -d "$NVIDIA_SRC" ]]; then
    echo -e "${RED}ERROR: Nvidia BSP source not found at: $NVIDIA_SRC${NC}"
    echo ""
    echo "Please ensure the original Nvidia BSP is extracted."
    echo "Run: ./l4t_prepare.sh -v $L4T_VERSION -V forecr"
    exit 1
fi

echo "Forecr source:  $FORECR_SRC"
echo "Nvidia BSP:     $NVIDIA_SRC"
echo "Destination:    $DEST"
echo ""
echo "Directories to process: ${SUBDIRS[*]}"
echo ""

#******************************************************************************
# Create destination directory
#******************************************************************************

mkdir -p "$DEST"

#******************************************************************************
# Counters
#******************************************************************************

TOTAL_NEW=0
TOTAL_MODIFIED=0

#******************************************************************************
# Function: Check if a path contains a symlink component in reference directory
#
# This prevents copying files that are accessible via symlinks (duplicates).
# For example, if scripts/dtc/include-prefixes/arm64 is a symlink to
# arch/arm64/boot/dts, we should only copy from arch/arm64/boot/dts, not
# from the symlink path.
#
# Args: $1 = relative path, $2 = reference directory (Nvidia BSP)
# Returns: 0 if path contains symlink, 1 if path is clean
#******************************************************************************
path_contains_symlink() {
    local rel_path="$1"
    local ref_dir="$2"

    # Check each component of the path
    local current_path=""
    IFS='/' read -ra path_parts <<< "$rel_path"

    for part in "${path_parts[@]}"; do
        [[ -z "$part" ]] && continue
        if [[ -z "$current_path" ]]; then
            current_path="$part"
        else
            current_path="$current_path/$part"
        fi

        # Check if this path component is a symlink in the reference directory
        if [[ -L "$ref_dir/$current_path" ]]; then
            return 0  # Path contains symlink
        fi
    done

    return 1  # Path is clean
}

#******************************************************************************
# Function: Copy new files (only in Forecr, not in Nvidia)
#******************************************************************************

copy_new_files() {
    local subdir="$1"
    local count=0

    if [[ ! -d "$FORECR_SRC/$subdir" ]]; then
        return 0
    fi

    if [[ ! -d "$NVIDIA_SRC/$subdir" ]]; then
        # Entire directory is new - copy everything
        echo -e "${YELLOW}  Copying entire new directory: $subdir${NC}"
        mkdir -p "$DEST/$subdir"
        cp -r "$FORECR_SRC/$subdir"/* "$DEST/$subdir/" 2>/dev/null || true
        count=$(find "$DEST/$subdir" -type f 2>/dev/null | wc -l)
        echo "    Copied $count files (entire directory is new)"
        TOTAL_NEW=$((TOTAL_NEW + count))
        return 0
    fi

    # Compare and copy only new files
    while IFS= read -r line; do
        [[ -z "$line" ]] && continue

        dir=$(echo "$line" | sed "s|Only in $FORECR_SRC/||; s|: .*||")
        filename=$(echo "$line" | sed 's|.*: ||')
        src_file="$FORECR_SRC/$dir/$filename"
        dest_file="$DEST/$dir/$filename"

        # Skip if it's a directory (will be handled recursively by diff)
        if [[ -d "$src_file" ]]; then
            continue
        fi

        # Skip if path goes through a symlink in Nvidia BSP (avoid duplicates)
        local rel_path_for_check="$dir/$filename"
        rel_path_for_check="${rel_path_for_check#$subdir/}"  # Remove subdir prefix if present
        if path_contains_symlink "$subdir/$rel_path_for_check" "$NVIDIA_SRC"; then
            echo "    SKIP (symlink path): $dir/$filename"
            continue
        fi

        mkdir -p "$(dirname "$dest_file")"
        cp "$src_file" "$dest_file"
        echo "    NEW: $dir/$filename"
        count=$((count + 1))
    done < <(diff -rq "$FORECR_SRC/$subdir" "$NVIDIA_SRC/$subdir" 2>/dev/null | grep "^Only in $FORECR_SRC" || true)

    TOTAL_NEW=$((TOTAL_NEW + count))
    return 0
}

#******************************************************************************
# Function: Copy modified files (exist in both, but different)
#******************************************************************************

copy_modified_files() {
    local subdir="$1"
    local count=0

    if [[ ! -d "$FORECR_SRC/$subdir" ]] || [[ ! -d "$NVIDIA_SRC/$subdir" ]]; then
        return 0
    fi

    while IFS= read -r line; do
        [[ -z "$line" ]] && continue

        src_file=$(echo "$line" | sed 's|Files ||; s| and .*||')
        rel_path=$(echo "$src_file" | sed "s|$FORECR_SRC/||")
        dest_file="$DEST/$rel_path"

        # Skip if path goes through a symlink in Nvidia BSP (avoid duplicates)
        if path_contains_symlink "$rel_path" "$NVIDIA_SRC"; then
            echo "    SKIP (symlink path): $rel_path"
            continue
        fi

        # Determine path to Exosens generic file
        if [[ $L4T_MAJOR -ge 36 ]]; then
            exosens_file="$ROOT_DIR/sources/$L4T_VERSION/Linux_for_Tegra/source/$rel_path"
        else
            exosens_file="$ROOT_DIR/sources/$L4T_VERSION/Linux_for_Tegra/source/public/$rel_path"
        fi

        # Use Nvidia Forecr BSP file as base (since file is modified in Forecr)
        nvidia_bsp_file="$NVIDIA_SRC/$rel_path"

        mkdir -p "$(dirname "$dest_file")"

        # Check if this file also has Exosens modifications
        if [[ -f "$exosens_file" ]] && [[ -f "$nvidia_bsp_file" ]]; then
            # Check if Exosens file differs from Nvidia Forecr BSP (has Exosens modifications)
            if ! diff -q "$exosens_file" "$nvidia_bsp_file" &>/dev/null; then
                # 3-way merge needed: Base=Nvidia Forecr BSP, Ours=Exosens, Theirs=Forecr kernel
                echo "    MERGED: $rel_path (Exosens + Forecr)"

                # Use git merge-file for 3-way merge
                cp "$exosens_file" "$dest_file"
                if git merge-file -q "$dest_file" "$nvidia_bsp_file" "$src_file" 2>/dev/null; then
                    # Merge succeeded without conflicts
                    :
                else
                    # Merge had conflicts - keep merged file with conflict markers
                    echo "      WARNING: Merge conflicts detected, review $dest_file"
                fi
                count=$((count + 1))
                TOTAL_MODIFIED=$((TOTAL_MODIFIED + 1))
                continue
            fi
        fi

        # No merge needed, just copy Forecr file
        cp "$src_file" "$dest_file"
        echo "    MODIFIED: $rel_path"
        count=$((count + 1))
    done < <(diff -rq "$FORECR_SRC/$subdir" "$NVIDIA_SRC/$subdir" 2>/dev/null | grep "^Files.*differ" || true)

    TOTAL_MODIFIED=$((TOTAL_MODIFIED + count))
    return 0
}

#******************************************************************************
# Function: Merge Exosens defconfig changes into Forecr defconfig files
#******************************************************************************

merge_exosens_defconfig() {
    echo -e "${BLUE}=============================================="
    echo "Merging Exosens defconfig changes"
    echo -e "==============================================${NC}"
    echo ""

    # Determine kernel version directory pattern
    if [[ $L4T_MAJOR -ge 36 ]]; then
        KERNEL_SUBDIR="kernel-jammy-src"
        FORECR_VENDOR_DEFCONFIG="$FORECR_SRC/kernel/$KERNEL_SUBDIR/arch/arm64/configs/defconfig"
        NVIDIA_DEFCONFIG="$ROOT_DIR/sources/$L4T_VERSION/Linux_for_Tegra/source/kernel/$KERNEL_SUBDIR/arch/arm64/configs/defconfig"
        DEST_CONFIGS_DIR="$DEST/kernel/$KERNEL_SUBDIR/arch/arm64/configs"
    else
        KERNEL_SUBDIR="kernel-5.10"
        FORECR_VENDOR_DEFCONFIG="$FORECR_SRC/kernel/$KERNEL_SUBDIR/arch/arm64/configs/defconfig"
        NVIDIA_DEFCONFIG="$ROOT_DIR/sources/$L4T_VERSION/Linux_for_Tegra/source/public/kernel/$KERNEL_SUBDIR/arch/arm64/configs/defconfig"
        DEST_CONFIGS_DIR="$DEST/kernel/$KERNEL_SUBDIR/arch/arm64/configs"
    fi

    # Check if Nvidia BSP defconfig exists
    if [[ ! -f "$NVIDIA_DEFCONFIG" ]]; then
        echo -e "${YELLOW}WARNING: Nvidia BSP defconfig not found: $NVIDIA_DEFCONFIG${NC}"
        echo "Skipping defconfig merge."
        return 0
    fi

    echo "Nvidia BSP defconfig: $NVIDIA_DEFCONFIG"

    if [[ -f "$FORECR_VENDOR_DEFCONFIG" ]]; then
        echo "Forecr vendor defconfig: $FORECR_VENDOR_DEFCONFIG"
        echo ""

        EXOSENS_CONFIGS=()
        while IFS= read -r line; do
            [[ -z "$line" ]] && continue
            [[ "$line" =~ ^# ]] && continue
            if [[ "$line" =~ ^CONFIG_ ]]; then
                config_name=$(echo "$line" | cut -d'=' -f1)
                if ! grep -q "^${config_name}=" "$FORECR_VENDOR_DEFCONFIG" 2>/dev/null; then
                    EXOSENS_CONFIGS+=("$line")
                fi
            fi
        done < "$NVIDIA_DEFCONFIG"

        if [[ ${#EXOSENS_CONFIGS[@]} -eq 0 ]]; then
            echo -e "${YELLOW}No additional Exosens CONFIG options found to merge.${NC}"
            return 0
        fi

        echo "Exosens CONFIG options to merge:"
        for config in "${EXOSENS_CONFIGS[@]}"; do
            echo "  $config"
        done
        echo ""
    else
        echo "Forecr vendor defconfig: Not found (using all configs from Nvidia BSP)"
        echo ""

        echo -e "${YELLOW}WARNING: Cannot determine Exosens-specific configs automatically${NC}"
        echo "Using known Exosens camera driver configs as fallback"
        echo ""

        EXOSENS_CONFIGS=(
            "CONFIG_VIDEO_DIONE_IR=m"
            "CONFIG_VIDEO_EG_EC_MIPI=m"
            "CONFIG_VIDEO_EG_MICROLYNX=m"
        )

        echo "Fallback CONFIG options to merge:"
        for config in "${EXOSENS_CONFIGS[@]}"; do
            echo "  $config"
        done
        echo ""
    fi

    # Check if destination configs directory exists
    if [[ ! -d "$DEST_CONFIGS_DIR" ]]; then
        echo -e "${YELLOW}WARNING: Destination configs directory not found: $DEST_CONFIGS_DIR${NC}"
        echo "Skipping defconfig merge."
        return 0
    fi

    # Find all *_defconfig files
    local merged_count=0
    for defconfig_file in "$DEST_CONFIGS_DIR"/*_defconfig; do
        [[ ! -f "$defconfig_file" ]] && continue

        local filename=$(basename "$defconfig_file")
        local configs_added=0

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
        else
            echo "  SKIPPED: $filename (configs already present)"
        fi
    done

    echo ""
    echo -e "${GREEN}Defconfig merge complete: $merged_count files updated${NC}"
    echo ""

    # Save vendor defconfig as reference for future merges
    if [[ -f "$FORECR_VENDOR_DEFCONFIG" ]]; then
        VENDOR_REF="$DEST_CONFIGS_DIR/defconfig.vendor_reference"
        cp "$FORECR_VENDOR_DEFCONFIG" "$VENDOR_REF"
        echo "  Saved vendor defconfig reference: $VENDOR_REF"
        echo ""
    fi
}

#******************************************************************************
# Process each subdirectory
#******************************************************************************

for subdir in "${SUBDIRS[@]}"; do
    if [[ -d "$FORECR_SRC/$subdir" ]]; then
        echo -e "${BLUE}Processing $subdir/ directory...${NC}"
        echo ""
        echo "  Copying NEW files..."
        copy_new_files "$subdir"
        echo ""
        echo "  Copying MODIFIED files..."
        copy_modified_files "$subdir"
        echo ""
    else
        echo -e "${YELLOW}Skipping $subdir/ (not present in Forecr source)${NC}"
        echo ""
    fi
done

#******************************************************************************
# Merge Exosens defconfig changes into Forecr defconfig files
#******************************************************************************

merge_exosens_defconfig

#******************************************************************************
# Fix Makefile NPROC syntax
#******************************************************************************

fix_makefile_nproc() {
    echo -e "${BLUE}=============================================="
    echo "Fixing Makefile NPROC syntax"
    echo -e "==============================================${NC}"
    echo ""

    local makefile="$DEST/kernel/Makefile"

    if [[ ! -f "$makefile" ]]; then
        echo -e "${YELLOW}No kernel/Makefile found, skipping NPROC fix${NC}"
        echo ""
        return 0
    fi

    if grep -q 'NPROC ?= \$(($(shell nproc)-1))' "$makefile" 2>/dev/null; then
        echo "  Found invalid NPROC syntax in: $makefile"
        sed -i 's/NPROC ?= \$(($(shell nproc)-1))/NPROC ?= $(shell expr $(shell nproc) - 1)/' "$makefile"
        echo -e "  ${GREEN}FIXED: NPROC syntax corrected${NC}"
    else
        echo "  NPROC syntax already correct or not present"
    fi
    echo ""
}

fix_makefile_nproc

#******************************************************************************
# Fix LOCALVERSION in kernel Makefile
#******************************************************************************

fix_makefile_localversion() {
    echo -e "${BLUE}=============================================="
    echo "Adding LOCALVERSION_SUFFIX support to Makefile"
    echo -e "==============================================${NC}"
    echo ""

    local makefile="$DEST/kernel/Makefile"

    if [[ ! -f "$makefile" ]]; then
        echo -e "${YELLOW}No kernel/Makefile found, skipping LOCALVERSION fix${NC}"
        echo ""
        return 0
    fi

    if grep -q 'LOCALVERSION_SUFFIX' "$makefile" 2>/dev/null; then
        echo "  LOCALVERSION_SUFFIX already present"
    elif grep -q '# LOCALVERSION : -tegra or -rt-tegra' "$makefile" 2>/dev/null; then
        echo "  Adding LOCALVERSION_SUFFIX support..."
        sed -i 's/# LOCALVERSION : -tegra or -rt-tegra/# LOCALVERSION : -tegra or -rt-tegra, with optional suffix (e.g., -eg for Exosens)\nLOCALVERSION_SUFFIX ?=/' "$makefile"
        sed -i 's/echo "-rt-tegra" || echo "-tegra")/echo "-rt-tegra$(LOCALVERSION_SUFFIX)" || echo "-tegra$(LOCALVERSION_SUFFIX)")/' "$makefile"
        echo -e "  ${GREEN}FIXED: LOCALVERSION_SUFFIX support added${NC}"
    else
        echo -e "${YELLOW}  LOCALVERSION definition not found in expected format${NC}"
    fi
    echo ""
}

fix_makefile_localversion

#******************************************************************************
# Generate summary
#******************************************************************************

echo -e "${GREEN}=============================================="
echo "SUMMARY"
echo -e "==============================================${NC}"
echo ""

TOTAL_FILES=$(find "$DEST" -type f 2>/dev/null | wc -l)

echo "Total files extracted: $TOTAL_FILES"
echo "  - New files:      $TOTAL_NEW"
echo "  - Modified files: $TOTAL_MODIFIED"
echo ""

echo "Breakdown by directory:"
for subdir in "${SUBDIRS[@]}"; do
    if [[ -d "$DEST/$subdir" ]]; then
        count=$(find "$DEST/$subdir" -type f 2>/dev/null | wc -l)
        echo "  - $subdir/: $count files"
    fi
done
echo ""

echo "Files saved to: $DEST"
echo ""

if [[ $TOTAL_FILES -eq 0 ]]; then
    echo -e "${YELLOW}WARNING: No files were extracted. This could mean:${NC}"
    echo "  - Forecr kernel is identical to Nvidia BSP"
    echo "  - Paths are incorrect"
    echo "  - Nvidia BSP is not properly extracted"
    exit 1
fi

echo -e "${GREEN}SUCCESS: Forecr sources extracted for L4T $L4T_VERSION${NC}"
echo ""
echo "Next steps:"
echo "  1. Review extracted files"
echo "  2. Test with: ./l4t_copy_sources.sh -v $L4T_VERSION -V forecr"
echo "  3. Build with: ./l4t_build.sh -v $L4T_VERSION -V forecr"
