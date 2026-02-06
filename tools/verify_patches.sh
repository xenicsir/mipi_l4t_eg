#!/bin/bash
#******************************************************************************
# verify_patches.sh - Verify Exosens modifications are properly patched
#
# This script performs two types of verification:
#
# 1. SOURCE VERIFICATION:
#    Verifies that all Exosens source files have been correctly copied/patched
#    into the Linux_for_Tegra directories. Sources are applied in order
#    (later overrides earlier):
#      - sources/common/Linux_for_Tegra
#      - sources/$VERSION/Linux_for_Tegra
#      - sources/common/source/hardware_* and nvidia-oot (based on L4T version)
#      - sources/$VERSION/Linux_for_Tegra_$VENDOR (for vendor-specific targets)
#
# 2. PATCH VERIFICATION:
#    Verifies that patch files in patches/$VERSION_$VENDOR/ correctly represent
#    the git diff of the corresponding $VERSION/Linux_for_Tegra*/ directories.
#    This ensures patches stay in sync with the actual modifications.
#
# Directory naming conventions:
#   - patches/$VERSION_$VENDOR/ (e.g., patches/36.4.3_forecr/)
#   - sources/$VERSION/Linux_for_Tegra_$VENDOR/ (e.g., sources/36.4.3/Linux_for_Tegra_forecr/)
#   - $VERSION/Linux_for_Tegra_${VENDOR}_${CARRIER}/ (e.g., 36.4.3/Linux_for_Tegra_forecr_dsboard_ornx/)
#
# Usage:
#   ./tools/verify_patches.sh [options] [version_filter]
#
# Options:
#   -r, --repo DIR      Repository to verify (default: current directory)
#   -v, --verbose       Show detailed file comparisons and differences
#   -h, --help          Show this help message
#
# Examples:
#   ./tools/verify_patches.sh                    # Verify all versions
#   ./tools/verify_patches.sh 35.6.2             # Verify specific version (exact match)
#   ./tools/verify_patches.sh "36.4*"            # Verify 36.4, 36.4.3, 36.4.4 (glob pattern)
#   ./tools/verify_patches.sh -v 36.4            # Verbose output for 36.4 only
#******************************************************************************

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

# Default values
REPO_DIR="$ROOT_DIR"
VERSION_FILTER=""
VERBOSE=0

# Parse options
while [[ $# -gt 0 ]]; do
    case "$1" in
        -r|--repo)
            REPO_DIR="$2"
            shift 2
            ;;
        -v|--verbose)
            VERBOSE=1
            shift
            ;;
        -h|--help)
            head -38 "$0" | tail -n +2 | sed 's/^#//' | sed 's/^\*//g'
            exit 0
            ;;
        -*)
            echo "Unknown option: $1" >&2
            exit 1
            ;;
        *)
            VERSION_FILTER="$1"
            shift
            ;;
    esac
done

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo "============================================"
echo "Verifying Exosens patches"
echo "  Repository: $REPO_DIR"
echo "============================================"
echo ""

#******************************************************************************
# Function: Check if version matches filter (exact match or glob pattern)
# Usage: version_matches "36.4.3" "36.4*" -> returns 0 (match)
#        version_matches "36.4.3" "36.4"  -> returns 1 (no match)
#******************************************************************************
version_matches() {
    local version="$1"
    local filter="$2"

    # Empty filter matches everything
    [[ -z "$filter" ]] && return 0

    # If filter contains glob characters, use pattern matching
    if [[ "$filter" == *'*'* ]] || [[ "$filter" == *'?'* ]]; then
        [[ "$version" == $filter ]] && return 0
    else
        # Exact match only
        [[ "$version" == "$filter" ]] && return 0
    fi

    return 1
}

#******************************************************************************
# Function: Get L4T major version from version string
#******************************************************************************
get_major_version() {
    echo "$1" | cut -d'.' -f1
}

#******************************************************************************
# Function: Extract vendor from directory name
# Linux_for_Tegra -> ""
# Linux_for_Tegra_forecr -> "forecr"
# Linux_for_Tegra_forecr_dsboard_ornx -> "forecr"
#******************************************************************************
extract_vendor() {
    local dir_name="$1"

    if [[ "$dir_name" == "Linux_for_Tegra" ]]; then
        echo ""
        return
    fi

    # Remove Linux_for_Tegra_ prefix
    local suffix="${dir_name#Linux_for_Tegra_}"

    # Extract vendor (first part before underscore or entire string)
    echo "${suffix%%_*}"
}

#******************************************************************************
# Function: Find matching L4T directory for a patch directory
# Handles: patches/36.4.3_forecr -> 36.4.3/Linux_for_Tegra_forecr_* or Linux_for_Tegra_forecr
#******************************************************************************
find_matching_l4t_dir() {
    local version="$1"
    local vendor="$2"  # Empty for generic

    if [[ -z "$vendor" ]]; then
        # Generic - look for Linux_for_Tegra
        if [[ -d "$REPO_DIR/$version/Linux_for_Tegra" ]]; then
            echo "$REPO_DIR/$version/Linux_for_Tegra"
            return 0
        fi
    else
        # Vendor - first try Linux_for_Tegra_${vendor}_*
        for dir in "$REPO_DIR/$version"/Linux_for_Tegra_${vendor}_*/; do
            if [[ -d "$dir" ]]; then
                echo "${dir%/}"
                return 0
            fi
        done

        # Fallback to Linux_for_Tegra_${vendor}
        if [[ -d "$REPO_DIR/$version/Linux_for_Tegra_${vendor}" ]]; then
            echo "$REPO_DIR/$version/Linux_for_Tegra_${vendor}"
            return 0
        fi
    fi

    return 1
}

#******************************************************************************
# Function: Verify a file exists and matches in target
#******************************************************************************
verify_file() {
    local src_file="$1"
    local target_file="$2"

    # Check if target exists (use -e OR -L to handle broken symlinks)
    if [[ ! -e "$target_file" ]] && [[ ! -L "$target_file" ]]; then
        echo "MISSING"
        return 1
    fi

    # Both are symlinks
    if [[ -L "$src_file" ]] && [[ -L "$target_file" ]]; then
        local src_link=$(readlink "$src_file")
        local target_link=$(readlink "$target_file")
        if [[ "$src_link" == "$target_link" ]]; then
            echo "OK"
            return 0
        else
            echo "DIFFERENT"
            return 1
        fi
    # Both are regular files
    elif [[ -f "$src_file" ]] && [[ ! -L "$src_file" ]] && [[ -f "$target_file" ]] && [[ ! -L "$target_file" ]]; then
        if diff -q "$src_file" "$target_file" >/dev/null 2>&1; then
            echo "OK"
            return 0
        else
            echo "DIFFERENT"
            return 1
        fi
    else
        echo "TYPE_MISMATCH"
        return 1
    fi
}

#******************************************************************************
# Function: Build merged file map from multiple sources
#******************************************************************************
build_file_map() {
    local target_dir="$1"
    shift
    local source_dirs=("$@")

    local map_file=$(mktemp)

    for src_info in "${source_dirs[@]}"; do
        local src_path="${src_info%%:*}"
        local dest_subpath="${src_info#*:}"
        [[ "$dest_subpath" == "$src_info" ]] && dest_subpath=""

        if [[ ! -d "$src_path" ]]; then
            continue
        fi

        while IFS= read -r src_file; do
            [[ -z "$src_file" ]] && continue

            local rel_file="${src_file#$src_path/}"
            local target_rel
            if [[ -n "$dest_subpath" ]]; then
                target_rel="$dest_subpath/$rel_file"
            else
                target_rel="$rel_file"
            fi

            sed -i "\|^${target_rel}:|d" "$map_file" 2>/dev/null || true
            echo "${target_rel}:${src_file}" >> "$map_file"

        done < <(find "$src_path" \( -type f -o -type l \) 2>/dev/null)
    done

    echo "$map_file"
}

#******************************************************************************
# Function: Verify sources are patched into target directory
#******************************************************************************
verify_target() {
    local version="$1"
    local target_dir="$2"
    shift 2
    local source_dirs=("$@")

    local target_name=$(basename "$target_dir")
    local total_files=0
    local ok_files=0
    local missing_files=0
    local different_files=0
    local missing_list=()
    local different_list=()

    local map_file=$(build_file_map "$target_dir" "${source_dirs[@]}")

    while IFS=':' read -r target_rel src_file; do
        [[ -z "$target_rel" ]] && continue

        local target_file="$target_dir/$target_rel"
        total_files=$((total_files + 1))

        local result=$(verify_file "$src_file" "$target_file")

        case "$result" in
            OK)
                ok_files=$((ok_files + 1))
                ;;
            MISSING)
                missing_files=$((missing_files + 1))
                missing_list+=("$target_rel")
                ;;
            DIFFERENT|TYPE_MISMATCH)
                different_files=$((different_files + 1))
                different_list+=("$target_rel (from ${src_file#$REPO_DIR/})")
                ;;
        esac
    done < "$map_file"

    rm -f "$map_file"

    if [[ $total_files -eq 0 ]]; then
        echo -e "      ${YELLOW}[SKIP] No source files found${NC}"
        return 0
    fi

    if [[ $missing_files -eq 0 ]] && [[ $different_files -eq 0 ]]; then
        echo -e "      ${GREEN}[OK] $ok_files/$total_files files verified${NC}"
        return 0
    else
        echo -e "      ${RED}[FAIL] $ok_files/$total_files OK, $missing_files missing, $different_files different${NC}"

        if [[ $VERBOSE -eq 1 ]]; then
            if [[ ${#missing_list[@]} -gt 0 ]]; then
                echo -e "        ${RED}Missing files:${NC}"
                for f in "${missing_list[@]:0:10}"; do
                    echo "          - $f"
                done
                [[ ${#missing_list[@]} -gt 10 ]] && echo "          ... and $((${#missing_list[@]} - 10)) more"
            fi

            if [[ ${#different_list[@]} -gt 0 ]]; then
                echo -e "        ${YELLOW}Different files:${NC}"
                for f in "${different_list[@]:0:10}"; do
                    echo "          - $f"
                done
                [[ ${#different_list[@]} -gt 10 ]] && echo "          ... and $((${#different_list[@]} - 10)) more"
            fi
        fi

        return 1
    fi
}

#******************************************************************************
# Ordered list of patch patterns
#******************************************************************************
PATCH_ORDER=(
    "source_nvidia-oot_drivers_media_i2c:^source/nvidia-oot/drivers/media/i2c/"
    "source_nvidia-oot_drivers_media_platform:^source/nvidia-oot/drivers/media/platform/"
    "source_nvidia-oot_include_media:^source/nvidia-oot/include/media/"
    "source_nvidia-oot:^source/nvidia-oot/"
    "source_public_kernel_nvidia_drivers_media_i2c:^source/public/kernel/nvidia/drivers/media/i2c/"
    "source_public_kernel_nvidia_drivers_media_platform:^source/public/kernel/nvidia/drivers/media/platform/"
    "source_public_kernel_nvidia_include_media:^source/public/kernel/nvidia/include/media/"
    "source_public_kernel:^source/public/kernel/"
    "source_public_hardware:^source/public/hardware/"
    "source_hardware:^source/hardware/"
    "source_kernel:^source/kernel/"
    "rootfs_opt_eg:^rootfs/opt/eg/"
    "rootfs_opt_nvidia:^rootfs/opt/nvidia/"
    "rootfs_usr_bin:^rootfs/usr/bin/"
    "rootfs_usr:^rootfs/usr/"
    "rootfs_opt:^rootfs/opt/"
    "rootfs:^rootfs/"
    "source:^source/[^/]+$"
)

#******************************************************************************
# Function: Generate diff for a single file
#******************************************************************************
generate_file_diff() {
    local l4t_dir="$1"
    local file="$2"
    local output_file="$3"

    (
        cd "$l4t_dir"

        if git cat-file -e "HEAD:$file" 2>/dev/null; then
            git diff HEAD -- "$file" >> "$output_file" 2>/dev/null
        else
            if [[ -L "$file" ]]; then
                local link_target=$(readlink "$file")
                {
                    echo "diff --git a/$file b/$file"
                    echo "new file mode 120000"
                    echo "index 0000000..$(echo -n "$link_target" | git hash-object --stdin 2>/dev/null | cut -c1-7)"
                    echo "--- /dev/null"
                    echo "+++ b/$file"
                    echo "@@ -0,0 +1 @@"
                    echo "+$link_target"
                    echo "\\ No newline at end of file"
                } >> "$output_file"
            elif [[ -f "$file" ]]; then
                {
                    echo "diff --git a/$file b/$file"
                    echo "new file mode 100644"
                    echo "index 0000000..$(git hash-object "$file" 2>/dev/null | cut -c1-7)"
                    echo "--- /dev/null"
                    echo "+++ b/$file"
                    local line_count=$(wc -l < "$file")
                    echo "@@ -0,0 +1,$line_count @@"
                    sed 's/^/+/' "$file"
                } >> "$output_file"
            fi
        fi
    )
}

#******************************************************************************
# Function: Verify patch files match current git diff
#******************************************************************************
verify_patch_files() {
    local patch_dir="$1"
    local l4t_dir="$2"

    local patch_dir_name=$(basename "$patch_dir")
    local total_patches=0
    local ok_patches=0
    local different_patches=0
    local different_list=()

    if [[ ! -d "$l4t_dir/.git" ]]; then
        echo -e "      ${YELLOW}[SKIP] Not a git repository${NC}"
        return 0
    fi

    local patch_files=()
    for pf in "$patch_dir"/*.patch; do
        [[ -f "$pf" ]] && patch_files+=("$pf")
    done

    if [[ ${#patch_files[@]} -eq 0 ]]; then
        echo -e "      ${YELLOW}[SKIP] No patch files found${NC}"
        return 0
    fi

    local tmp_dir=$(mktemp -d)

    local tracked_files=$(cd "$l4t_dir" && git diff HEAD --name-only 2>/dev/null)
    local untracked_items=$(cd "$l4t_dir" && git status --porcelain -uall 2>/dev/null | grep "^??" | sed 's/^?? //')

    echo "$tracked_files" > "$tmp_dir/all_files.txt"
    echo "$untracked_items" >> "$tmp_dir/all_files.txt"

    cp "$tmp_dir/all_files.txt" "$tmp_dir/remaining_files.txt"

    for entry in "${PATCH_ORDER[@]}"; do
        local entry_name="${entry%%:*}"
        local entry_pattern="${entry#*:}"

        local patch_file="$patch_dir/${entry_name}.patch"
        [[ ! -f "$patch_file" ]] && continue

        total_patches=$((total_patches + 1))

        local generated_patch="$tmp_dir/${entry_name}_generated.patch"
        > "$generated_patch"

        local matching_files=$(grep -E "$entry_pattern" "$tmp_dir/remaining_files.txt" 2>/dev/null | grep -v "^$" || true)

        if [[ -n "$matching_files" ]]; then
            while IFS= read -r file; do
                [[ -z "$file" ]] && continue
                generate_file_diff "$l4t_dir" "$file" "$generated_patch"
            done <<< "$matching_files"

            grep -v -E "$entry_pattern" "$tmp_dir/remaining_files.txt" > "$tmp_dir/remaining_files.tmp" 2>/dev/null || true
            mv "$tmp_dir/remaining_files.tmp" "$tmp_dir/remaining_files.txt"
        fi

        local saved_files=$(grep "^diff --git" "$patch_file" 2>/dev/null | sed 's|diff --git a/||' | sed 's| b/.*||' | sort -u)
        local generated_files=$(grep "^diff --git" "$generated_patch" 2>/dev/null | sed 's|diff --git a/||' | sed 's| b/.*||' | sort -u)

        local saved_count=$(echo "$saved_files" | grep -v "^$" | wc -l)
        local generated_count=$(echo "$generated_files" | grep -v "^$" | wc -l)

        if [[ $saved_count -eq 0 ]] && [[ $generated_count -eq 0 ]]; then
            ok_patches=$((ok_patches + 1))
        elif [[ "$saved_files" == "$generated_files" ]]; then
            ok_patches=$((ok_patches + 1))
        else
            different_patches=$((different_patches + 1))
            different_list+=("$entry_name.patch (saved: $saved_count files, current: $generated_count files)")
        fi
    done

    rm -rf "$tmp_dir"

    if [[ $total_patches -eq 0 ]]; then
        echo -e "      ${YELLOW}[SKIP] No patches to verify${NC}"
        return 0
    fi

    if [[ $different_patches -eq 0 ]]; then
        echo -e "      ${GREEN}[OK] $ok_patches/$total_patches patches verified${NC}"
        return 0
    else
        echo -e "      ${RED}[DIFF] $ok_patches/$total_patches OK, $different_patches different${NC}"

        if [[ $VERBOSE -eq 1 ]]; then
            echo -e "        ${YELLOW}Different patches:${NC}"
            for p in "${different_list[@]}"; do
                echo "          - $p"
            done
        fi

        return 1
    fi
}

# Find all versions
versions=()
for dir in "$REPO_DIR"/32.* "$REPO_DIR"/35.* "$REPO_DIR"/36.*; do
    if [[ -d "$dir" ]]; then
        version=$(basename "$dir")
        if version_matches "$version" "$VERSION_FILTER"; then
            versions+=("$version")
        fi
    fi
done

IFS=$'\n' sorted_versions=($(sort -V <<< "${versions[*]}")); unset IFS

echo "Versions to verify: ${sorted_versions[*]}"
echo ""

# Summary arrays
declare -a passed_versions
declare -a failed_versions

# Verify each version
for version in "${sorted_versions[@]}"; do
    echo "----------------------------------------"
    echo "Version: $version"
    echo "----------------------------------------"

    major_version=$(get_major_version "$version")
    version_passed=1

    # Find all Linux_for_Tegra* directories
    for l4t_dir in "$REPO_DIR/$version"/Linux_for_Tegra*; do
        [[ ! -d "$l4t_dir" ]] && continue

        l4t_name=$(basename "$l4t_dir")
        vendor=$(extract_vendor "$l4t_name")

        echo "  $l4t_name:"

        # Build list of source directories to check
        source_dirs=()

        # 1. Common Linux_for_Tegra
        source_dirs+=("$REPO_DIR/sources/common/Linux_for_Tegra")

        # 2. Version-specific Linux_for_Tegra
        source_dirs+=("$REPO_DIR/sources/$version/Linux_for_Tegra")

        # 3. Hardware and driver sources (based on L4T version)
        if [[ $major_version -ge 36 ]]; then
            source_dirs+=("$REPO_DIR/sources/common/source/hardware_36+:source/hardware")
            source_dirs+=("$REPO_DIR/sources/common/source/nvidia-oot:source/nvidia-oot")
        else
            source_dirs+=("$REPO_DIR/sources/common/source/hardware_32+:source/public/hardware")
            source_dirs+=("$REPO_DIR/sources/common/source/nvidia-oot/drivers:source/public/kernel/nvidia/drivers")
        fi

        # 4. Vendor-specific sources (uses vendor name, not full dir name)
        if [[ -n "$vendor" ]]; then
            vendor_src="$REPO_DIR/sources/$version/Linux_for_Tegra_${vendor}"
            if [[ -d "$vendor_src" ]]; then
                source_dirs+=("$vendor_src")
            fi
        fi

        if ! verify_target "$version" "$l4t_dir" "${source_dirs[@]}"; then
            version_passed=0
        fi
    done

    if [[ $version_passed -eq 1 ]]; then
        passed_versions+=("$version")
    else
        failed_versions+=("$version")
    fi

    echo ""
done

#******************************************************************************
# Verify patch files
#******************************************************************************
echo ""
echo "============================================"
echo "Verifying patch files"
echo "============================================"
echo ""

declare -a passed_patch_versions
declare -a failed_patch_versions

for patch_dir in "$REPO_DIR"/patches/32.* "$REPO_DIR"/patches/35.* "$REPO_DIR"/patches/36.*; do
    [[ ! -d "$patch_dir" ]] && continue

    patch_dir_name=$(basename "$patch_dir")

    # Parse patch directory name: VERSION or VERSION_VENDOR
    if [[ "$patch_dir_name" == *_* ]]; then
        version="${patch_dir_name%%_*}"
        vendor="${patch_dir_name#*_}"
    else
        version="$patch_dir_name"
        vendor=""
    fi

    # Apply version filter
    if ! version_matches "$version" "$VERSION_FILTER"; then
        continue
    fi

    # Find matching L4T directory
    l4t_dir=$(find_matching_l4t_dir "$version" "$vendor")

    echo "----------------------------------------"
    echo "Patches: $patch_dir_name"
    echo "----------------------------------------"

    if [[ -z "$l4t_dir" ]] || [[ ! -d "$l4t_dir" ]]; then
        echo -e "  ${YELLOW}[SKIP] Target directory not found${NC}"
        continue
    fi

    echo "  Target: $version/$(basename "$l4t_dir")"

    patch_passed=1
    if ! verify_patch_files "$patch_dir" "$l4t_dir"; then
        patch_passed=0
    fi

    if [[ $patch_passed -eq 1 ]]; then
        passed_patch_versions+=("$patch_dir_name")
    else
        failed_patch_versions+=("$patch_dir_name")
    fi

    echo ""
done

# Print patch verification summary
echo ""
echo "============================================"
echo "PATCH VERIFICATION SUMMARY"
echo "============================================"
echo ""

echo -e "${GREEN}Passed patch sets (${#passed_patch_versions[@]}):${NC}"
if [[ ${#passed_patch_versions[@]} -gt 0 ]]; then
    printf '  %s\n' "${passed_patch_versions[@]}"
else
    echo "  (none)"
fi
echo ""

echo -e "${RED}Failed patch sets (${#failed_patch_versions[@]}):${NC}"
if [[ ${#failed_patch_versions[@]} -gt 0 ]]; then
    printf '  %s\n' "${failed_patch_versions[@]}"
else
    echo "  (none)"
fi
echo ""

# Print summary
echo ""
echo "============================================"
echo "SOURCE VERIFICATION SUMMARY"
echo "============================================"
echo ""

echo -e "${GREEN}Passed versions (${#passed_versions[@]}):${NC}"
if [[ ${#passed_versions[@]} -gt 0 ]]; then
    printf '  %s\n' "${passed_versions[@]}"
else
    echo "  (none)"
fi
echo ""

echo -e "${RED}Failed versions (${#failed_versions[@]}):${NC}"
if [[ ${#failed_versions[@]} -gt 0 ]]; then
    printf '  %s\n' "${failed_versions[@]}"
else
    echo "  (none)"
fi
echo ""

# Exit code based on results
if [[ ${#failed_versions[@]} -gt 0 ]] || [[ ${#failed_patch_versions[@]} -gt 0 ]]; then
    exit 1
fi
exit 0
