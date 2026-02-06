#!/bin/bash
#******************************************************************************
# l4t_environment.sh - Unified L4T Configuration and Environment
#
# This file provides:
#   - Configuration loading from l4t_versions.json
#   - Version/vendor/carrier enumeration with wildcard support
#   - Shared argument parsing for all l4t_* scripts
#   - Version-specific configuration (URLs, toolchains, etc.)
#
# Usage (from other scripts):
#   . l4t_environment.sh "$@"
#
# Arguments:
#   -v, --l4t-version VERSION      L4T version (required for individual scripts)
#   -V, --vendor VENDOR            Vendor: generic, forecr (default: generic)
#   -c, --carrier-board BOARD      Carrier board (default: depends on vendor)
#   -p, --package-version VERSION  Package version for delivery (optional)
#   -s, --standalone               Build standalone kernel with -eg suffix
#
# Configuration Enumeration (for l4t_make.sh):
#   get_all_versions              List all supported versions
#   match_versions "pattern"      Match versions with wildcards (36.*, 35.6.*)
#   enumerate_configs             Generate valid version:vendor:carrier combinations
#******************************************************************************

#******************************************************************************
# Script directory and configuration file
#******************************************************************************
L4T_ENV_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
L4T_CONFIG_FILE="${L4T_CONFIG_FILE:-$L4T_ENV_DIR/l4t_versions.json}"

#******************************************************************************
# Check dependencies
#******************************************************************************
if ! command -v jq >/dev/null 2>&1; then
    echo "Error: jq is required but not installed."
    echo "Install with: sudo apt-get install jq"
    exit 1
fi

if [[ ! -f "$L4T_CONFIG_FILE" ]]; then
    echo "Error: Configuration file not found: $L4T_CONFIG_FILE"
    exit 1
fi

#******************************************************************************
# SECTION 1: Configuration Reading Functions
#******************************************************************************

# Get all supported L4T versions (sorted)
get_all_versions() {
    jq -r '.versions | keys[]' "$L4T_CONFIG_FILE" | sort -V | tr '\n' ' ' | sed 's/ $//'
}

# Cache for performance (avoid repeated jq calls)
_L4T_ALL_VERSIONS=""
_l4t_ensure_versions_cache() {
    if [[ -z "$_L4T_ALL_VERSIONS" ]]; then
        _L4T_ALL_VERSIONS=$(get_all_versions)
    fi
}

# Get vendors supported for a specific version
get_vendors_for_version() {
    local version="$1"
    jq -r ".versions[\"$version\"].vendors[]?" "$L4T_CONFIG_FILE" 2>/dev/null | tr '\n' ' ' | sed 's/ $//'
}

# Get all defined vendors
get_all_vendors() {
    jq -r '.vendors | keys[]' "$L4T_CONFIG_FILE" | tr '\n' ' ' | sed 's/ $//'
}

# Get carriers for a specific vendor
get_carriers_for_vendor() {
    local vendor="$1"
    jq -r ".vendors[\"$vendor\"].carriers[]?" "$L4T_CONFIG_FILE" 2>/dev/null | tr '\n' ' ' | sed 's/ $//'
}

# Get all defined carriers
get_all_carriers() {
    jq -r '.carriers | keys[]' "$L4T_CONFIG_FILE" | tr '\n' ' ' | sed 's/ $//'
}

# Get default carrier for a vendor
get_default_carrier() {
    local vendor="$1"
    jq -r ".vendors[\"$vendor\"].default_carrier // empty" "$L4T_CONFIG_FILE"
}

# Check if configuration requires standalone build
# Args: version, vendor, carrier
# Reads from versions.$version.standalone.$vendor.$carrier in JSON config
config_requires_standalone() {
    local version="$1"
    local vendor="$2"
    local carrier="$3"

    # Check version-specific standalone config: versions.$version.standalone.$vendor.$carrier
    local standalone=$(jq -r ".versions[\"$version\"].standalone[\"$vendor\"][\"$carrier\"] // false" "$L4T_CONFIG_FILE")
    [[ "$standalone" == "true" ]]
}

# Get kernel defconfig for a carrier
get_carrier_defconfig() {
    local carrier="$1"
    jq -r ".carriers[\"$carrier\"].defconfig // empty" "$L4T_CONFIG_FILE"
}

# Get directory suffix for a carrier
get_carrier_dir_suffix() {
    local carrier="$1"
    jq -r ".carriers[\"$carrier\"].dir_suffix // empty" "$L4T_CONFIG_FILE"
}

#******************************************************************************
# SECTION 2: Version Matching and Enumeration Functions
#******************************************************************************

# Match versions against a pattern (supports wildcards)
# Args: pattern (e.g., "36.4", "36.*", "36.4*")
# Returns: Space-separated list of matching versions
match_versions() {
    local pattern="$1"
    local result=""

    _l4t_ensure_versions_cache

    # Empty pattern matches all
    if [[ -z "$pattern" ]]; then
        echo "$_L4T_ALL_VERSIONS"
        return
    fi

    for version in $_L4T_ALL_VERSIONS; do
        # If pattern contains wildcards, use glob matching
        if [[ "$pattern" == *'*'* ]] || [[ "$pattern" == *'?'* ]]; then
            if [[ "$version" == $pattern ]]; then
                result="$result $version"
            fi
        else
            # Exact match only
            if [[ "$version" == "$pattern" ]]; then
                result="$result $version"
            fi
        fi
    done

    echo "$result" | xargs  # Trim leading/trailing spaces
}

# Check if a version+vendor combination is valid
is_valid_version_vendor() {
    local version="$1"
    local vendor="$2"
    local vendors=$(get_vendors_for_version "$version")
    [[ " $vendors " =~ " $vendor " ]]
}

# Check if a vendor+carrier combination is valid
is_valid_vendor_carrier() {
    local vendor="$1"
    local carrier="$2"
    local carriers=$(get_carriers_for_vendor "$vendor")
    [[ " $carriers " =~ " $carrier " ]]
}

# Enumerate all valid configurations
# Args: version_filter vendor_filter carrier_filter
# Returns: List of "version:vendor:carrier" configurations, one per line
enumerate_configs() {
    local version_filter="$1"
    local vendor_filter="$2"
    local carrier_filter="$3"

    _l4t_ensure_versions_cache

    # Get versions to process
    local versions
    if [[ -z "$version_filter" ]]; then
        versions="$_L4T_ALL_VERSIONS"
    else
        versions=$(match_versions "$version_filter")
    fi

    if [[ -z "$versions" ]]; then
        echo "Error: No versions match pattern '$version_filter'" >&2
        return 1
    fi

    for version in $versions; do
        # Get vendors for this version
        local vendors=$(get_vendors_for_version "$version")

        # Apply vendor filter
        if [[ -n "$vendor_filter" ]]; then
            if [[ " $vendors " =~ " $vendor_filter " ]]; then
                vendors="$vendor_filter"
            else
                # Skip this version if vendor filter doesn't match
                continue
            fi
        fi

        for vendor in $vendors; do
            # Get carriers for this vendor
            local carriers=$(get_carriers_for_vendor "$vendor")

            # Apply carrier filter
            if [[ -n "$carrier_filter" ]]; then
                if [[ " $carriers " =~ " $carrier_filter " ]]; then
                    carriers="$carrier_filter"
                else
                    # Skip this vendor if carrier filter doesn't match
                    continue
                fi
            fi

            for carrier in $carriers; do
                echo "${version}:${vendor}:${carrier}"
            done
        done
    done
}

# Parse a configuration string "version:vendor:carrier"
# Args: config_string var_prefix
# Sets: ${var_prefix}_VERSION, ${var_prefix}_VENDOR, ${var_prefix}_CARRIER
parse_config() {
    local config="$1"
    local prefix="${2:-CFG}"

    local version vendor carrier
    IFS=':' read -r version vendor carrier <<< "$config"

    eval "${prefix}_VERSION='$version'"
    eval "${prefix}_VENDOR='$vendor'"
    eval "${prefix}_CARRIER='$carrier'"
}

# Build command-line arguments from configuration
# Args: version vendor carrier [extra_args...]
# Returns: String of arguments for l4t_* scripts
build_args() {
    local version="$1"
    local vendor="$2"
    local carrier="$3"
    shift 3
    local extra_args="$*"

    local args="-v $version"

    if [[ "$vendor" != "generic" ]]; then
        args="$args -V $vendor"
    fi

    if [[ "$carrier" != "generic" ]]; then
        args="$args -c $carrier"
    fi

    if [[ -n "$extra_args" ]]; then
        args="$args $extra_args"
    fi

    echo "$args"
}

# Count configurations
count_configs() {
    local version_filter="$1"
    local vendor_filter="$2"
    local carrier_filter="$3"

    enumerate_configs "$version_filter" "$vendor_filter" "$carrier_filter" 2>/dev/null | wc -l
}

# Validate configuration filters and report errors
validate_filters() {
    local version_filter="$1"
    local vendor_filter="$2"
    local carrier_filter="$3"

    local errors=0
    local all_versions=$(get_all_versions)
    local all_vendors=$(get_all_vendors)
    local all_carriers=$(get_all_carriers)

    # Check version filter produces results
    if [[ -n "$version_filter" ]]; then
        local matched=$(match_versions "$version_filter")
        if [[ -z "$matched" ]]; then
            echo "Error: No versions match pattern '$version_filter'" >&2
            echo "Available versions: $all_versions" >&2
            errors=1
        fi
    fi

    # Check vendor filter is valid
    if [[ -n "$vendor_filter" ]]; then
        if [[ ! " $all_vendors " =~ " $vendor_filter " ]]; then
            echo "Error: Invalid vendor '$vendor_filter'" >&2
            echo "Available vendors: $all_vendors" >&2
            errors=1
        fi
    fi

    # Check carrier filter is valid
    if [[ -n "$carrier_filter" ]]; then
        if [[ ! " $all_carriers " =~ " $carrier_filter " ]]; then
            echo "Error: Invalid carrier-board '$carrier_filter'" >&2
            echo "Available carrier-boards: $all_carriers" >&2
            errors=1
        fi
    fi

    # Check that the combination produces at least one valid config
    if [[ $errors -eq 0 ]]; then
        local count=$(count_configs "$version_filter" "$vendor_filter" "$carrier_filter")
        if [[ $count -eq 0 ]]; then
            echo "Error: No valid configurations for the specified filters" >&2

            # Provide helpful error messages
            if [[ -n "$version_filter" && -n "$vendor_filter" ]]; then
                local matched_versions=$(match_versions "$version_filter")
                for v in $matched_versions; do
                    local valid_vendors=$(get_vendors_for_version "$v")
                    if [[ ! " $valid_vendors " =~ " $vendor_filter " ]]; then
                        echo "  - Version $v does not support vendor '$vendor_filter' (supports: $valid_vendors)" >&2
                    fi
                done
            fi

            if [[ -n "$vendor_filter" && -n "$carrier_filter" ]]; then
                local valid_carriers=$(get_carriers_for_vendor "$vendor_filter")
                if [[ ! " $valid_carriers " =~ " $carrier_filter " ]]; then
                    echo "  - Vendor '$vendor_filter' does not support carrier-board '$carrier_filter' (supports: $valid_carriers)" >&2
                fi
            fi

            errors=1
        fi
    fi

    return $errors
}

#******************************************************************************
# SECTION 3: Argument Parsing
#******************************************************************************

# Help function
show_l4t_help() {
    local all_versions=$(get_all_versions)
    local all_vendors=$(get_all_vendors)

    cat << EOF
L4T Build System - Common Arguments

Usage:
  ./l4t_<script>.sh [options]

Required:
  -v, --l4t-version VERSION      L4T version (e.g., 36.4.3, 35.6.2, 32.7.1)

Optional:
  -V, --vendor VENDOR            Vendor: $(echo $all_vendors | tr ' ' ', ') (default: generic)
  -c, --carrier-board BOARD      Carrier board (default depends on vendor)
  -p, --package-version VERSION  Package version for delivery package
  -s, --standalone               Build standalone kernel with -eg suffix
                                   (auto per l4t_versions.json)
  -h, --help                     Show this help message

Supported L4T versions:
  $all_versions

Version-vendor support:
EOF
    for v in $all_versions; do
        local vendors=$(get_vendors_for_version "$v")
        echo "  $v: $vendors"
    done
}

# Argument parsing function
parse_l4t_args() {
    # Reset variables
    L4T_VERSION=""
    VENDOR="generic"
    CARRIER_BOARD=""
    PACKAGE_VERSION=""
    STANDALONE_BUILD=0

    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case "$1" in
            -v|--l4t-version)
                L4T_VERSION="$2"
                shift 2
                ;;
            -V|--vendor)
                VENDOR="$2"
                shift 2
                ;;
            -c|--carrier-board)
                CARRIER_BOARD="$2"
                shift 2
                ;;
            -p|--package-version)
                PACKAGE_VERSION="$2"
                shift 2
                ;;
            -s|--standalone)
                STANDALONE_BUILD=1
                shift
                ;;
            -h|--help)
                show_l4t_help
                exit 0
                ;;
            *)
                echo "Error: Unknown argument: $1"
                echo "Use --help for usage information."
                exit 1
                ;;
        esac
    done

    # Validate required arguments
    if [[ -z "$L4T_VERSION" ]]; then
        echo "Error: --l4t-version is required"
        echo "Use --help for usage information."
        exit 1
    fi

    # Validate version exists
    local all_versions=$(get_all_versions)
    if [[ ! " $all_versions " =~ " $L4T_VERSION " ]]; then
        echo "Error: Unsupported L4T version '$L4T_VERSION'"
        echo "Supported versions: $all_versions"
        exit 1
    fi

    # Validate vendor
    local all_vendors=$(get_all_vendors)
    if [[ ! " $all_vendors " =~ " $VENDOR " ]]; then
        echo "Error: Invalid vendor '$VENDOR'. Valid values: $all_vendors"
        exit 1
    fi

    # Validate vendor is supported for this version
    if ! is_valid_version_vendor "$L4T_VERSION" "$VENDOR"; then
        local valid_vendors=$(get_vendors_for_version "$L4T_VERSION")
        echo "Error: Vendor '$VENDOR' is not supported for L4T $L4T_VERSION"
        echo "Supported vendors: $valid_vendors"
        exit 1
    fi

    # Set default carrier-board based on vendor
    if [[ -z "$CARRIER_BOARD" ]]; then
        CARRIER_BOARD=$(get_default_carrier "$VENDOR")
    fi

    # Validate carrier-board
    local all_carriers=$(get_all_carriers)
    if [[ ! " $all_carriers " =~ " $CARRIER_BOARD " ]]; then
        echo "Error: Invalid carrier-board '$CARRIER_BOARD'. Valid values: $all_carriers"
        exit 1
    fi

    # Validate vendor + carrier-board combination
    if ! is_valid_vendor_carrier "$VENDOR" "$CARRIER_BOARD"; then
        local valid_carriers=$(get_carriers_for_vendor "$VENDOR")
        echo "Error: Vendor '$VENDOR' does not support carrier-board '$CARRIER_BOARD'"
        echo "Supported carrier-boards: $valid_carriers"
        exit 1
    fi

    # Check if configuration requires standalone build
    if config_requires_standalone "$L4T_VERSION" "$VENDOR" "$CARRIER_BOARD"; then
        STANDALONE_BUILD=1
    fi

    # Export STANDALONE_BUILD for use by other scripts
    export STANDALONE_BUILD
}

#******************************************************************************
# SECTION 4: Version-Specific Configuration Loading
#******************************************************************************

load_version_config() {
    local version="$1"

    # Source packages
    JETSON_PUBLIC_SOURCES=$(jq -r ".versions[\"$version\"].sources.public.filename" "$L4T_CONFIG_FILE")
    JETSON_PUBLIC_SOURCES_URL=$(jq -r ".versions[\"$version\"].sources.public.url" "$L4T_CONFIG_FILE")

    L4T_RELEASE_PACKAGE=$(jq -r ".versions[\"$version\"].sources.release.filename" "$L4T_CONFIG_FILE")
    L4T_RELEASE_PACKAGE_URL=$(jq -r ".versions[\"$version\"].sources.release.url" "$L4T_CONFIG_FILE")

    SAMPLE_FS_PACKAGE=$(jq -r ".versions[\"$version\"].sources.sample_fs.filename" "$L4T_CONFIG_FILE")
    SAMPLE_FS_PACKAGE_URL=$(jq -r ".versions[\"$version\"].sources.sample_fs.url" "$L4T_CONFIG_FILE")

    # Toolchain
    JETSON_TOOLCHAIN_ARCHIVE=$(jq -r ".versions[\"$version\"].toolchain.archive" "$L4T_CONFIG_FILE")
    JETSON_TOOLCHAIN_ARCHIVE_URL=$(jq -r ".versions[\"$version\"].toolchain.url" "$L4T_CONFIG_FILE")
    TOOLCHAIN_DIR=$(jq -r ".versions[\"$version\"].toolchain.dir" "$L4T_CONFIG_FILE")
    local toolchain_prefix=$(jq -r ".versions[\"$version\"].toolchain.prefix" "$L4T_CONFIG_FILE")

    # Build full toolchain prefix path
    TOOLCHAIN_PREFIX="$JETSON_DIR/$TOOLCHAIN_DIR/$toolchain_prefix"

    # Legacy variable names (for backward compatibility)
    JETSON_TOOCHAIN_ARCHIVE="$JETSON_TOOLCHAIN_ARCHIVE"
    JETSON_TOOCHAIN_ARCHIVE_URL="$JETSON_TOOLCHAIN_ARCHIVE_URL"
}

#******************************************************************************
# SECTION 5: Derived Variables
#******************************************************************************

compute_derived_vars() {
    # Version major number
    L4T_VERSION_MAJOR=$(echo $L4T_VERSION | awk -F '.' '{print $1}')

    # Directory paths
    ROOT_DIR=$(pwd)
    ARCHIVE_DIR=$ROOT_DIR/archives

    # Git information
    if [[ -f /usr/lib/git-core/git-sh-prompt ]]; then
        . /usr/lib/git-core/git-sh-prompt
        GIT_TAG=$(echo $(__git_ps1) | sed 's/[()]//g')
    else
        GIT_TAG=""
    fi
    GIT_COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")

    # Directory naming based on vendor/carrier-board
    if [[ "$VENDOR" == "generic" ]]; then
        LINUX_FOR_TEGRA_DIR=Linux_for_Tegra
        VENDOR_SOURCE_DIR=""
        L4T_VERSION_EXTENDED=${L4T_VERSION}
    else
        local carrier_suffix=$(get_carrier_dir_suffix "$CARRIER_BOARD")
        if [[ -n "$carrier_suffix" ]]; then
            LINUX_FOR_TEGRA_DIR=Linux_for_Tegra_${VENDOR}_${carrier_suffix}
        else
            LINUX_FOR_TEGRA_DIR=Linux_for_Tegra_${VENDOR}
        fi
        VENDOR_SOURCE_DIR=Linux_for_Tegra_${VENDOR}
        L4T_VERSION_EXTENDED=${L4T_VERSION}_${VENDOR}
    fi

    # Kernel defconfig based on carrier-board
    KERNEL_DEFCONFIG=$(get_carrier_defconfig "$CARRIER_BOARD")

    # Jetson directory
    JETSON_DIR=$ROOT_DIR/$L4T_VERSION

    # L4T source directory (varies by version)
    if [[ -d $JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/source/public ]]; then
        L4T_SRC=$JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/source/public
    else
        L4T_SRC=$JETSON_DIR/${LINUX_FOR_TEGRA_DIR}/source
    fi

    # Load version-specific configuration
    load_version_config "$L4T_VERSION"
}

#******************************************************************************
# SECTION 6: Main Entry Point
#******************************************************************************

# By default, do NOT parse arguments automatically.
# Scripts that need argument parsing should call:
#   parse_l4t_args "$@"
#   compute_derived_vars
#
# This allows l4t_make.sh and other orchestration scripts to source this file
# for enumeration functions without argument conflicts.
#
# For backward compatibility with existing l4t_*.sh scripts that source with:
#   . l4t_environment.sh "$@"
# They should be updated to explicitly call parse_l4t_args after sourcing.

# Export the initialization function for scripts that need full setup
l4t_init() {
    parse_l4t_args "$@"
    compute_derived_vars
}
