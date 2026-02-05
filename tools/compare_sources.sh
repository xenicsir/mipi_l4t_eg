#!/bin/bash
#******************************************************************************
# compare_sources.sh - Compare source directories between two repos
#
# This script compares Linux_for_Tegra directories between two repositories,
# handling different naming conventions:
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
#   -h, --help          Show this help message
#
# Examples:
#   ./tools/compare_sources.sh                              # Compare all versions
#   ./tools/compare_sources.sh 32.7.1                       # Compare specific version
#   ./tools/compare_sources.sh -a ../repo1 -b ../repo2 35   # Custom repos, 35.x only
#******************************************************************************

# Get script directory to compute default paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(dirname "$SCRIPT_DIR")"
PARENT_DIR="$(dirname "$BASE_DIR")"

# Default values
REPO_A="$PARENT_DIR/mipi_l4t_eg-a"
REPO_B="$PARENT_DIR/mipi_l4t_eg-b"
VERSION_FILTER=""

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
        # Apply version filter if specified (exact match or prefix match)
        if [[ -z "$VERSION_FILTER" ]] || [[ "$version" == "$VERSION_FILTER" ]] || [[ "$version" == $VERSION_FILTER* ]]; then
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
            # Compare directories (excluding .git files)
            diff_output=$(diff -rq "$source_a" "$source_b" 2>&1 | grep -v "\.git" | grep -v "\.gitignore")

            if [[ -z "$diff_output" ]]; then
                echo -e "      ${GREEN}[OK] Identical (excluding .git)${NC}"
            else
                echo -e "      ${RED}[DIFF] Differences found:${NC}"
                echo "$diff_output" | sed 's/^/      /' | head -20
                diff_count=$(echo "$diff_output" | wc -l)
                if [[ $diff_count -gt 20 ]]; then
                    echo "      ... and $((diff_count - 20)) more differences"
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
