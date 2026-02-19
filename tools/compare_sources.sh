#!/bin/bash
#******************************************************************************
# compare_sources.sh - Compare source directories between two repos
#
# This script compares Linux_for_Tegra source directories between two repositories,
# excluding build artifacts (.o, .ko, .cmd, .dtb, etc.) and handling different
# naming conventions:
#   - Linux_for_Tegra (generic)
#   - Linux_for_Tegra_forecr (old vendor naming)
#   - Linux_for_Tegra_forecr_dsboard_ornx (new vendor_carrier naming)
#
# Matching logic for forecr:
#   - If only Linux_for_Tegra_forecr exists in both repos, compare them
#   - If one has Linux_for_Tegra_forecr and other has Linux_for_Tegra_forecr_*,
#     they are matched and compared
#   - If both have Linux_for_Tegra_forecr_*, compare the first one found in each
#
# Usage:
#   ./tools/compare_sources.sh [options] [version_filter]
#
# Options:
#   -a, --repo-a DIR    First repository (default: ../mipi_l4t_eg-a)
#   -b, --repo-b DIR    Second repository (default: ../mipi_l4t_eg-b)
#   -v, --verbose       Show all differences (default: truncate to 20)
#   -w, --ignore-whitespace  Ignore whitespace differences (tabs/spaces)
#   -h, --help          Show this help message
#
# Examples:
#   ./tools/compare_sources.sh                              # Compare all versions
#   ./tools/compare_sources.sh 32.7.1                       # Compare specific version (exact match)
#   ./tools/compare_sources.sh "36.4*"                      # Compare 36.4, 36.4.3, 36.4.4 (glob pattern)
#   ./tools/compare_sources.sh -a ../repo1 -b ../repo2 35   # Custom repos, version 35 only
#******************************************************************************

# Get script directory to compute default paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(dirname "$SCRIPT_DIR")"
PARENT_DIR="$(dirname "$BASE_DIR")"

# Default values
REPO_A="$PARENT_DIR/mipi_l4t_eg-a"
REPO_B="$PARENT_DIR/mipi_l4t_eg-b"
VERSION_FILTER=""
VERBOSE=0
IGNORE_WHITESPACE=0

# Parse options
while [[ $# -gt 0 ]]; do
    case "$1" in
        -a|--repo-a)
            REPO_A="$2"
            shift 2
            ;;
        -b|--repo-b)
            REPO_B="$2"
            shift 2
            ;;
        -v|--verbose)
            VERBOSE=1
            shift
            ;;
        -w|--ignore-whitespace)
            IGNORE_WHITESPACE=1
            shift
            ;;
        -h|--help)
            head -28 "$0" | tail -n +2 | sed 's/^#//' | sed 's/^\*//g'
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
NC='\033[0m' # No Color

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

echo "============================================"
echo "Comparing source directories"
echo "  Repo A: $REPO_A"
echo "  Repo B: $REPO_B"
echo "============================================"
echo ""

#******************************************************************************
# Function: Find forecr directory in a version directory
# Returns the best match for forecr directory (handles naming convention changes)
#******************************************************************************
find_forecr_dir() {
    local version_dir="$1"

    # First try: Linux_for_Tegra_forecr_* (new naming with carrier board)
    for dir in "$version_dir"/Linux_for_Tegra_forecr_*/; do
        if [[ -d "$dir" ]]; then
            basename "${dir%/}"
            return 0
        fi
    done

    # Fallback: Linux_for_Tegra_forecr (old naming)
    if [[ -d "$version_dir/Linux_for_Tegra_forecr" ]]; then
        echo "Linux_for_Tegra_forecr"
        return 0
    fi

    return 1
}

#******************************************************************************
# Function: Get all Linux_for_Tegra* directories grouped by type
# Returns: generic, forecr (matched between repos)
#******************************************************************************
get_l4t_dirs() {
    local repo_a_version="$1"
    local repo_b_version="$2"

    local dirs=()

    # Always include Linux_for_Tegra (generic) if it exists in either
    if [[ -d "$repo_a_version/Linux_for_Tegra" ]] || [[ -d "$repo_b_version/Linux_for_Tegra" ]]; then
        dirs+=("Linux_for_Tegra")
    fi

    # Handle forecr directories (match old and new naming)
    local forecr_a=$(find_forecr_dir "$repo_a_version")
    local forecr_b=$(find_forecr_dir "$repo_b_version")

    if [[ -n "$forecr_a" ]] || [[ -n "$forecr_b" ]]; then
        # Use the name from repo A if available, otherwise from repo B
        if [[ -n "$forecr_a" ]]; then
            dirs+=("$forecr_a")
        else
            dirs+=("$forecr_b")
        fi
    fi

    echo "${dirs[@]}"
}

# Find all 32.x, 35.x and 36.x versions in main repo
versions=()
for dir in "$REPO_A"/32.* "$REPO_A"/35.* "$REPO_A"/36.*; do
    if [[ -d "$dir" ]]; then
        version=$(basename "$dir")
        # Apply version filter if specified (exact match or glob pattern)
        if version_matches "$version" "$VERSION_FILTER"; then
            versions+=("$version")
        fi
    fi
done

# Sort versions
IFS=$'\n' sorted_versions=($(sort -V <<< "${versions[*]}")); unset IFS

echo "Versions to compare: ${sorted_versions[*]}"
echo ""

# Summary arrays
declare -a identical_versions
declare -a different_versions

# Compare each version
for version in "${sorted_versions[@]}"; do
    echo "----------------------------------------"
    echo "Version: $version"
    echo "----------------------------------------"

    version_has_diff=0
    dir_index=0

    # Get list of L4T directories to compare
    l4t_dirs=($(get_l4t_dirs "$REPO_A/$version" "$REPO_B/$version"))

    for l4t_name in "${l4t_dirs[@]}"; do
        dir_index=$((dir_index + 1))

        # Determine actual directory names in each repo
        source_a=""
        source_b=""
        display_name="$l4t_name"

        if [[ "$l4t_name" == "Linux_for_Tegra" ]]; then
            # Generic - same name in both repos
            source_a="$REPO_A/$version/Linux_for_Tegra/source"
            source_b="$REPO_B/$version/Linux_for_Tegra/source"
        else
            # Forecr - may have different names
            forecr_a=$(find_forecr_dir "$REPO_A/$version")
            forecr_b=$(find_forecr_dir "$REPO_B/$version")

            if [[ -n "$forecr_a" ]]; then
                source_a="$REPO_A/$version/$forecr_a/source"
            fi
            if [[ -n "$forecr_b" ]]; then
                source_b="$REPO_B/$version/$forecr_b/source"
            fi

            # Update display name to show both if different
            if [[ -n "$forecr_a" ]] && [[ -n "$forecr_b" ]] && [[ "$forecr_a" != "$forecr_b" ]]; then
                display_name="$forecr_a (A) vs $forecr_b (B)"
            elif [[ -n "$forecr_a" ]]; then
                display_name="$forecr_a"
            elif [[ -n "$forecr_b" ]]; then
                display_name="$forecr_b"
            fi
        fi

        echo "  [$dir_index] $display_name/source:"

        # Check if directories exist
        if [[ -z "$source_a" ]] && [[ -z "$source_b" ]]; then
            echo -e "      ${YELLOW}[SKIP] Not found in either repo${NC}"
        elif [[ ! -d "$source_a" ]] && [[ -n "$source_a" ]]; then
            echo -e "      ${YELLOW}[INFO] Only in Repo B${NC}"
        elif [[ ! -d "$source_b" ]] && [[ -n "$source_b" ]]; then
            echo -e "      ${YELLOW}[MISSING] Only in Repo A${NC}"
            version_has_diff=1
        elif [[ -z "$source_a" ]]; then
            echo -e "      ${YELLOW}[INFO] Only in Repo B${NC}"
        elif [[ -z "$source_b" ]]; then
            echo -e "      ${YELLOW}[MISSING] Only in Repo A${NC}"
            version_has_diff=1
        else
            # Build version-specific exclude options and output filters
            # Note: diff --exclude only matches names, not paths, so we filter output for paths
            version_major=$(echo "$version" | cut -d. -f1)
            EXTRA_EXCLUDES=""
            OUTPUT_FILTER=""
            if [[ "$version_major" == "32" ]] || [[ "$version_major" == "35" ]]; then
                # Exclude build and modules directories (build artifacts under source/public/)
                EXTRA_EXCLUDES="--exclude=build --exclude=modules"
                # Filter out source/hardware (empty artifact from kernel build path bug)
                OUTPUT_FILTER="grep -v '/source/hardware' | grep -v '/source: hardware'"
            elif [[ "$version_major" == "36" ]]; then
                # Filter out kernel/Makefile (patched for LOCALVERSION_SUFFIX during build)
                OUTPUT_FILTER="grep -v '/source/kernel/Makefile'"
            fi

            # Compare directories (excluding .git and build artifacts)
            diff_options="-rq"
            [[ $IGNORE_WHITESPACE -eq 1 ]] && diff_options="$diff_options -w"
            diff_output=$(diff $diff_options $EXTRA_EXCLUDES \
                --exclude='.git' \
                --exclude='.gitignore' \
                --exclude='*.o' \
                --exclude='*.o.d' \
                --exclude='*.ko' \
                --exclude='*.a' \
                --exclude='*.cmd' \
                --exclude='*.mod' \
                --exclude='*.mod.c' \
                --exclude='*.order' \
                --exclude='*.symvers' \
                --exclude='.tmp_*' \
                --exclude='*.tmp' \
                --exclude='modules.order' \
                --exclude='Module.symvers' \
                --exclude='.config' \
                --exclude='*.dtb' \
                --exclude='*.dtb.d.*' \
                --exclude='*.dtbo' \
                --exclude='Image' \
                --exclude='Image.gz' \
                --exclude='vmlinux' \
                --exclude='vmlinux.o' \
                --exclude='vmlinux.lds' \
                --exclude='System.map' \
                --exclude='.cache.mk' \
                --exclude='*.builtin' \
                --exclude='.*.d' \
                --exclude='generated' \
                --exclude='*.so' \
                --exclude='*.so.dbg' \
                --exclude='*.lds' \
                --exclude='*.pem' \
                --exclude='*.x509' \
                --exclude='*.asn1.c' \
                --exclude='*.asn1.h' \
                --exclude='asm-offsets.s' \
                --exclude='gen-*' \
                --exclude='signing_key*' \
                --exclude='x509.genkey' \
                --exclude='x509_certificate_list' \
                --exclude='*-core.S' \
                --exclude='hyp-reloc.S' \
                --exclude='vdso.lds' \
                --exclude='config' \
                --exclude='*.dtb.S' \
                --exclude='bounds.s' \
                --exclude='config_data' \
                --exclude='config_data.gz' \
                --exclude='conmakehash' \
                --exclude='consolemap_deftbl.c' \
                --exclude='defkeymap.c' \
                --exclude='scsi_devinfo_tbl.c' \
                --exclude='crc32table.h' \
                --exclude='gen_crc32table' \
                --exclude='oid_registry_data.c' \
                --exclude='int*.c' \
                --exclude='neon*.c' \
                --exclude='tables.c' \
                --exclude='mktables' \
                --exclude='timeconst.h' \
                --exclude='offsets.h' \
                --exclude='cpustr.h' \
                --exclude='machtypes.h' \
                --exclude='selinux_av_perms.h' \
                --exclude='flask.h' \
                --exclude='av_permissions.h' \
                --exclude='*.lex.c' \
                --exclude='*.tab.c' \
                --exclude='*.tab.h' \
                --exclude='parse-events-bison.output' \
                --exclude='pmu-events.c' \
                --exclude='fixdep' \
                --exclude='sorttable' \
                --exclude='objtool' \
                --exclude='modules.builtin.modinfo' \
                --exclude='shipped-certs.c' \
                --exclude='asn1_compiler' \
                --exclude='dtc' \
                --exclude='fdtoverlay' \
                --exclude='fdtget' \
                --exclude='fdtput' \
                --exclude='extract-cert' \
                --exclude='genksyms' \
                --exclude='kallsyms' \
                --exclude='conf' \
                --exclude='mconf' \
                --exclude='nconf' \
                --exclude='modpost' \
                --exclude='genheaders' \
                --exclude='mdp' \
                --exclude='sign-file' \
                --exclude='gen_init_cpio' \
                --exclude='initramfs_data.cpio' \
                --exclude='initramfs_inc_data' \
                --exclude='devicetable-offsets.*' \
                --exclude='elfconfig.h' \
                --exclude='mk_elfconfig' \
                --exclude='recordmcount' \
                --exclude='basic' \
                --exclude='bin2c' \
                --exclude='unifdef' \
                --exclude='.version' \
                --exclude='dtbs' \
                --exclude='conftest' \
                --exclude='nv_compiler.h' \
                --exclude='*_binary' \
                --exclude='_out' \
                --exclude='out' \
                "$source_a" "$source_b" 2>&1)

            # Apply version-specific output filter
            if [[ -n "$OUTPUT_FILTER" && -n "$diff_output" ]]; then
                diff_output=$(echo "$diff_output" | eval "$OUTPUT_FILTER")
            fi

            if [[ -z "$diff_output" ]]; then
                echo -e "      ${GREEN}[OK] Identical (excluding .git and build artifacts)${NC}"
            else
                echo -e "      ${RED}[DIFF] Differences found:${NC}"
                diff_count=$(echo "$diff_output" | wc -l)
                if [[ $VERBOSE -eq 1 ]]; then
                    echo "$diff_output" | sed 's/^/      /'
                else
                    echo "$diff_output" | sed 's/^/      /' | head -20
                    if [[ $diff_count -gt 20 ]]; then
                        echo "      ... and $((diff_count - 20)) more differences"
                    fi
                fi
                version_has_diff=1
            fi
        fi
    done

    # Track version status
    if [[ $version_has_diff -eq 0 ]]; then
        identical_versions+=("$version")
    else
        different_versions+=("$version")
    fi

    echo ""
done

# Print summary
echo ""
echo "============================================"
echo "SUMMARY"
echo "============================================"
echo ""

echo -e "${GREEN}Identical versions (${#identical_versions[@]}):${NC}"
if [[ ${#identical_versions[@]} -gt 0 ]]; then
    printf '  %s\n' "${identical_versions[@]}"
else
    echo "  (none)"
fi
echo ""

echo -e "${RED}Different versions (${#different_versions[@]}):${NC}"
if [[ ${#different_versions[@]} -gt 0 ]]; then
    printf '  %s\n' "${different_versions[@]}"
else
    echo "  (none)"
fi
echo ""

# Exit code based on results
if [[ ${#different_versions[@]} -gt 0 ]]; then
    exit 1
fi
exit 0
