#!/bin/bash
#******************************************************************************
# l4t_make.sh - Master orchestration script for L4T build system
#
# This script provides a unified interface to run multiple L4T build steps
# across multiple versions, vendors, and carrier-boards with wildcard support.
#
# Usage:
#   ./l4t_make.sh [options] [steps]
#
# Version/Vendor/Carrier Selection:
#   -v, --l4t-version PATTERN   Version filter (supports wildcards: 36.*, 35.6.*)
#   -V, --vendor VENDOR         Vendor filter: generic, forecr (default: all)
#   -c, --carrier-board BOARD   Carrier board filter (default: all for vendor)
#
# Build Steps (at least one required):
#   --prepare                   Run l4t_prepare.sh (download and extract)
#   --copy-sources              Run l4t_copy_sources.sh (copies and patches)
#   --patch-sources             Run l4t_patch_sources.sh (patches only, exclusive with --copy-sources)
#   --build                     Run l4t_build.sh
#   --gen-package               Run l4t_gen_delivery_package.sh
#   --all                       Run: prepare, copy-sources, build, gen-package
#
# Execution Options:
#   --from-scratch              Delete existing build directory before prepare
#   --abort-on-error            Stop immediately on first error (default)
#   --continue-on-error         Continue with next configuration on error
#   --dry-run                   Show what would be executed without running
#   -p, --package-version VER   Package version for delivery (passed to gen-package)
#   -s, --standalone            Force standalone build
#
# Other:
#   --list                      List all matching configurations and exit
#   -h, --help                  Show this help message
#
# Examples:
#   ./l4t_make.sh -v 36.4.3 --all                    # All steps for 36.4.3 generic
#   ./l4t_make.sh -v "36.*" -V forecr --build       # Build all 36.x forecr versions
#   ./l4t_make.sh --prepare --copy-sources          # Prepare and copy all versions
#   ./l4t_make.sh -v 35.6.* --all --abort-on-error  # All 35.6.x, stop on error
#   ./l4t_make.sh --list                             # List all configurations
#   ./l4t_make.sh -v "36.*" -V forecr --list        # List 36.x forecr configs
#******************************************************************************

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Source unified environment (provides enumeration functions)
. "$SCRIPT_DIR/l4t_environment.sh"

#******************************************************************************
# Default values
#******************************************************************************
VERSION_FILTER=""
VENDOR_FILTER=""
CARRIER_FILTER=""
PACKAGE_VERSION=""
STANDALONE_OPT=""

DO_PREPARE=0
DO_COPY_SOURCES=0
DO_PATCH_SOURCES=0
DO_BUILD=0
DO_GEN_PACKAGE=0

FROM_SCRATCH=0
CONTINUE_ON_ERROR=0
DRY_RUN=0
LIST_ONLY=0

#******************************************************************************
# Colors
#******************************************************************************
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

#******************************************************************************
# Help function
#******************************************************************************
show_help() {
    head -42 "$0" | tail -n +2 | sed 's/^#//' | sed 's/^\*//g'
    echo ""
    local all_versions=$(get_all_versions)
    echo "Available versions: $all_versions"
    echo ""
    echo "Version-vendor support:"
    for v in $all_versions; do
        local vendors=$(get_vendors_for_version "$v")
        echo "  $v: $vendors"
    done
}

#******************************************************************************
# Parse arguments
#******************************************************************************
while [[ $# -gt 0 ]]; do
    case "$1" in
        -v|--l4t-version)
            VERSION_FILTER="$2"
            shift 2
            ;;
        -V|--vendor)
            VENDOR_FILTER="$2"
            shift 2
            ;;
        -c|--carrier-board)
            CARRIER_FILTER="$2"
            shift 2
            ;;
        -p|--package-version)
            PACKAGE_VERSION="$2"
            shift 2
            ;;
        -s|--standalone)
            STANDALONE_OPT="-s"
            shift
            ;;
        --prepare)
            DO_PREPARE=1
            shift
            ;;
        --copy-sources)
            DO_COPY_SOURCES=1
            shift
            ;;
        --patch-sources)
            DO_PATCH_SOURCES=1
            shift
            ;;
        --build)
            DO_BUILD=1
            shift
            ;;
        --gen-package)
            DO_GEN_PACKAGE=1
            shift
            ;;
        --all)
            DO_PREPARE=1
            DO_COPY_SOURCES=1
            DO_BUILD=1
            DO_GEN_PACKAGE=1
            shift
            ;;
        --from-scratch)
            FROM_SCRATCH=1
            shift
            ;;
        --continue-on-error)
            CONTINUE_ON_ERROR=1
            shift
            ;;
        --abort-on-error)
            CONTINUE_ON_ERROR=0
            shift
            ;;
        --dry-run)
            DRY_RUN=1
            shift
            ;;
        --list)
            LIST_ONLY=1
            shift
            ;;
        -h|--help)
            show_help
            exit 0
            ;;
        *)
            echo "Error: Unknown argument: $1"
            echo "Use --help for usage information."
            exit 1
            ;;
    esac
done

#******************************************************************************
# Validate inputs
#******************************************************************************
# Validate filters
if ! validate_filters "$VERSION_FILTER" "$VENDOR_FILTER" "$CARRIER_FILTER"; then
    exit 1
fi

# Check that --copy-sources and --patch-sources are mutually exclusive
if [[ $DO_COPY_SOURCES -eq 1 && $DO_PATCH_SOURCES -eq 1 ]]; then
    echo "Error: --copy-sources and --patch-sources are mutually exclusive"
    echo "Use --copy-sources for fresh sources, or --patch-sources to apply patches only"
    exit 1
fi

# Check that --from-scratch requires --prepare
if [[ $FROM_SCRATCH -eq 1 && $DO_PREPARE -eq 0 ]]; then
    echo "Error: --from-scratch requires --prepare"
    exit 1
fi

# Check that at least one step is selected (unless listing)
if [[ $LIST_ONLY -eq 0 ]]; then
    if [[ $DO_PREPARE -eq 0 && $DO_COPY_SOURCES -eq 0 && $DO_PATCH_SOURCES -eq 0 && \
          $DO_BUILD -eq 0 && $DO_GEN_PACKAGE -eq 0 ]]; then
        echo "Error: At least one build step must be selected"
        echo "Use --prepare, --copy-sources, --patch-sources, --build, --gen-package, or --all"
        echo "Use --help for usage information."
        exit 1
    fi
fi

# Check package version for gen-package
if [[ $DO_GEN_PACKAGE -eq 1 && -z "$PACKAGE_VERSION" ]]; then
    echo "Error: --package-version is required when using --gen-package"
    exit 1
fi

#******************************************************************************
# Get configurations to process
#******************************************************************************
configs=$(enumerate_configs "$VERSION_FILTER" "$VENDOR_FILTER" "$CARRIER_FILTER")
config_count=$(echo "$configs" | wc -l)

#******************************************************************************
# List mode
#******************************************************************************
if [[ $LIST_ONLY -eq 1 ]]; then
    echo "Matching configurations ($config_count):"
    echo ""
    printf "%-12s %-12s %-15s %s\n" "VERSION" "VENDOR" "CARRIER" "ARGUMENTS"
    echo "---------------------------------------------------------------"
    for config in $configs; do
        parse_config "$config"
        args=$(build_args "$CFG_VERSION" "$CFG_VENDOR" "$CFG_CARRIER")
        printf "%-12s %-12s %-15s %s\n" "$CFG_VERSION" "$CFG_VENDOR" "$CFG_CARRIER" "$args"
    done
    exit 0
fi

#******************************************************************************
# Build selected steps list
#******************************************************************************
steps=""
[[ $DO_PREPARE -eq 1 ]] && steps="$steps prepare"
[[ $DO_COPY_SOURCES -eq 1 ]] && steps="$steps copy-sources"
[[ $DO_PATCH_SOURCES -eq 1 ]] && steps="$steps patch-sources"
[[ $DO_BUILD -eq 1 ]] && steps="$steps build"
[[ $DO_GEN_PACKAGE -eq 1 ]] && steps="$steps gen-package"
steps=$(echo "$steps" | xargs)  # Trim

#******************************************************************************
# Display execution plan
#******************************************************************************
echo "============================================"
echo -e "${CYAN}L4T Build System - Execution Plan${NC}"
echo "============================================"
echo ""
echo "Configurations: $config_count"
echo "Steps: $steps"
[[ $FROM_SCRATCH -eq 1 ]] && echo "From scratch: yes (will delete existing build directories)"
echo "Error handling: $([ $CONTINUE_ON_ERROR -eq 1 ] && echo 'continue-on-error' || echo 'abort-on-error')"
[[ $DRY_RUN -eq 1 ]] && echo -e "${YELLOW}Mode: DRY RUN (no commands executed)${NC}"
echo ""

#******************************************************************************
# Execute builds
#******************************************************************************
total_success=0
total_failed=0
declare -a failed_configs

run_step() {
    local script="$1"
    local args="$2"
    local step_name="$3"

    echo -e "    ${BLUE}[$step_name]${NC} $script $args"

    if [[ $DRY_RUN -eq 1 ]]; then
        return 0
    fi

    if "$SCRIPT_DIR/$script" $args; then
        return 0
    else
        return 1
    fi
}

config_index=0
for config in $configs; do
    config_index=$((config_index + 1))
    parse_config "$config"

    echo "----------------------------------------"
    echo -e "${CYAN}[$config_index/$config_count]${NC} Version: $CFG_VERSION, Vendor: $CFG_VENDOR, Carrier: $CFG_CARRIER"
    echo "----------------------------------------"

    # Build base arguments
    base_args=$(build_args "$CFG_VERSION" "$CFG_VENDOR" "$CFG_CARRIER" "$STANDALONE_OPT")

    config_failed=0

    # Handle --from-scratch: delete existing build directory before prepare
    if [[ $FROM_SCRATCH -eq 1 && $DO_PREPARE -eq 1 ]]; then
        if [[ "$CFG_VENDOR" == "generic" ]]; then
            build_dir="$SCRIPT_DIR/$CFG_VERSION/Linux_for_Tegra"
        else
            carrier_suffix=$(get_carrier_dir_suffix "$CFG_CARRIER")
            if [[ -n "$carrier_suffix" ]]; then
                build_dir="$SCRIPT_DIR/$CFG_VERSION/Linux_for_Tegra_${CFG_VENDOR}_${carrier_suffix}"
            else
                build_dir="$SCRIPT_DIR/$CFG_VERSION/Linux_for_Tegra_${CFG_VENDOR}"
            fi
        fi

        if [[ -d "$build_dir" ]]; then
            echo -e "    ${YELLOW}[from-scratch]${NC} Deleting $build_dir"
            if [[ $DRY_RUN -eq 0 ]]; then
                sudo rm -rf "$build_dir"
            fi
        fi
    fi

    # Run selected steps
    if [[ $DO_PREPARE -eq 1 ]]; then
        if ! run_step "l4t_prepare.sh" "$base_args" "prepare"; then
            echo -e "    ${RED}[FAILED] l4t_prepare.sh${NC}"
            config_failed=1
            if [[ $CONTINUE_ON_ERROR -eq 0 ]]; then
                echo -e "${RED}Aborting due to error${NC}"
                exit 1
            fi
        fi
    fi

    if [[ $config_failed -eq 0 && $DO_COPY_SOURCES -eq 1 ]]; then
        if ! run_step "l4t_copy_sources.sh" "$base_args" "copy-sources"; then
            echo -e "    ${RED}[FAILED] l4t_copy_sources.sh${NC}"
            config_failed=1
            if [[ $CONTINUE_ON_ERROR -eq 0 ]]; then
                echo -e "${RED}Aborting due to error${NC}"
                exit 1
            fi
        fi
    fi

    if [[ $config_failed -eq 0 && $DO_PATCH_SOURCES -eq 1 ]]; then
        if ! run_step "l4t_patch_sources.sh" "$base_args" "patch-sources"; then
            echo -e "    ${RED}[FAILED] l4t_patch_sources.sh${NC}"
            config_failed=1
            if [[ $CONTINUE_ON_ERROR -eq 0 ]]; then
                echo -e "${RED}Aborting due to error${NC}"
                exit 1
            fi
        fi
    fi

    if [[ $config_failed -eq 0 && $DO_BUILD -eq 1 ]]; then
        if ! run_step "l4t_build.sh" "$base_args" "build"; then
            echo -e "    ${RED}[FAILED] l4t_build.sh${NC}"
            config_failed=1
            if [[ $CONTINUE_ON_ERROR -eq 0 ]]; then
                echo -e "${RED}Aborting due to error${NC}"
                exit 1
            fi
        fi
    fi

    if [[ $config_failed -eq 0 && $DO_GEN_PACKAGE -eq 1 ]]; then
        pkg_args="$base_args -p $PACKAGE_VERSION"
        if ! run_step "l4t_gen_delivery_package.sh" "$pkg_args" "gen-package"; then
            echo -e "    ${RED}[FAILED] l4t_gen_delivery_package.sh${NC}"
            config_failed=1
            if [[ $CONTINUE_ON_ERROR -eq 0 ]]; then
                echo -e "${RED}Aborting due to error${NC}"
                exit 1
            fi
        fi
    fi

    if [[ $config_failed -eq 0 ]]; then
        echo -e "    ${GREEN}[SUCCESS]${NC}"
        total_success=$((total_success + 1))
    else
        echo -e "    ${RED}[FAILED] Skipping remaining steps${NC}"
        total_failed=$((total_failed + 1))
        failed_configs+=("$CFG_VERSION:$CFG_VENDOR:$CFG_CARRIER")
    fi

    echo ""
done

#******************************************************************************
# Summary
#******************************************************************************
echo "============================================"
echo -e "${CYAN}SUMMARY${NC}"
echo "============================================"
echo ""
echo -e "${GREEN}Successful: $total_success${NC}"
echo -e "${RED}Failed: $total_failed${NC}"

if [[ $total_failed -gt 0 ]]; then
    echo ""
    echo "Failed configurations:"
    for fc in "${failed_configs[@]}"; do
        echo "  - $fc"
    done
    exit 1
fi

exit 0
