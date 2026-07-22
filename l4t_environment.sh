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
L4T_CONFIG_FILE="${L4T_CONFIG_FILE:-$L4T_ENV_DIR/eg_config.yaml}"
_EGCFG="python3 $L4T_ENV_DIR/tools/egcfg.py"

if [[ ! -f "$L4T_CONFIG_FILE" ]]; then
    echo "Error: Configuration file not found: $L4T_CONFIG_FILE"
    exit 1
fi

#******************************************************************************
# SECTION 1: Configuration Reading Functions
#******************************************************************************

# Get all supported L4T versions (sorted)
get_all_versions() {
    $_EGCFG versions "$L4T_CONFIG_FILE"
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
    $_EGCFG "version.$version.vendors" "$L4T_CONFIG_FILE" 2>/dev/null
}

# Get all defined vendors
get_all_vendors() {
    $_EGCFG vendors "$L4T_CONFIG_FILE"
}

# Get carriers for a specific vendor
get_carriers_for_vendor() {
    local vendor="$1"
    $_EGCFG "vendor.$vendor.carriers" "$L4T_CONFIG_FILE" 2>/dev/null
}

# Get all defined carriers
get_all_carriers() {
    $_EGCFG carriers "$L4T_CONFIG_FILE"
}

# Get default carrier for a vendor
get_default_carrier() {
    local vendor="$1"
    $_EGCFG "vendor.$vendor.default_carrier" "$L4T_CONFIG_FILE"
}

# Whether a vendor ships a precompiled kernel/nvidia-oot we don't control
# (no source available for our framework patches). Reads
# vendors.$vendor.pristine_kernel from eg_config.yaml. Echoes "1" or "".
get_vendor_pristine_kernel() {
    local vendor="$1"
    local pristine=$($_EGCFG "vendor.$vendor.pristine_kernel" "$L4T_CONFIG_FILE" 2>/dev/null)
    [[ "$pristine" == "true" ]] && echo "1" || echo ""
}

# Check if configuration requires standalone build
# Args: version, vendor, carrier
# Reads from versions.$version.standalone.$vendor.$carrier in JSON config
config_requires_standalone() {
    local version="$1"
    local vendor="$2"
    local carrier="$3"

    # Check version-specific standalone config: versions.$version.standalone.$vendor.$carrier
    local standalone=$($_EGCFG "version.$version.standalone.$vendor.$carrier" "$L4T_CONFIG_FILE" 2>/dev/null)
    [[ "$standalone" == "true" ]]
}

# Get kernel defconfig for a carrier
get_carrier_defconfig() {
    local carrier="$1"
    $_EGCFG "carrier.$carrier.defconfig" "$L4T_CONFIG_FILE"
}

# Get directory suffix for a carrier
get_carrier_dir_suffix() {
    local carrier="$1"
    $_EGCFG "carrier.$carrier.dir_suffix" "$L4T_CONFIG_FILE"
}

# Get all defined SoMs
get_all_soms() {
    $_EGCFG soms "$L4T_CONFIG_FILE" 2>/dev/null || echo ""
}

# Get directory suffix for a SoM
get_som_dir_suffix() {
    local som="$1"
    [[ -z "$som" ]] && echo "" && return
    $_EGCFG "som.$som.dir_suffix" "$L4T_CONFIG_FILE" 2>/dev/null || echo ""
}

# Get defconfig for a SoM
get_som_defconfig() {
    local som="$1"
    [[ -z "$som" ]] && echo "" && return
    $_EGCFG "som.$som.defconfig" "$L4T_CONFIG_FILE" 2>/dev/null || echo ""
}

# Get SoMs for a specific version+vendor combination.
# If the version defines vendor_soms.<vendor>, returns that list.
# Otherwise returns empty string (no SoM for this version+vendor).
get_soms_for_version_vendor() {
    local version="$1"
    local vendor="$2"
    $_EGCFG "version.$version.vendor_soms.$vendor" "$L4T_CONFIG_FILE" 2>/dev/null || echo ""
}

#******************************************************************************
# SECTION 2: Version Matching and Enumeration Functions
#******************************************************************************

# Match versions against a pattern (supports wildcards)
# Args: pattern (e.g., "36.4", "36.*", "36.x", "35.x.1", "36.4*")
#   .x is accepted as an alias for .* (e.g. 36.x == 36.*, 35.x.1 == 35.*.1)
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

    # Normalize .x → .* so users can write 36.x instead of "36.*"
    pattern="${pattern//.x/.*}"

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
# Args: version_filter vendor_filter som_filter carrier_filter
# Returns: List of "version:vendor:som:carrier" configurations, one per line
#          (som is empty for versions without vendor_soms)
enumerate_configs() {
    local version_filter="$1"
    local vendor_filter="$2"
    local som_filter="$3"
    local carrier_filter="$4"

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
                continue
            fi
        fi

        for vendor in $vendors; do
            # Check if this version+vendor has SoM variants
            local soms=$(get_soms_for_version_vendor "$version" "$vendor")

            if [[ -n "$soms" ]]; then
                # Version+vendor has SoM variants — enumerate by SoM
                if [[ -n "$som_filter" ]]; then
                    if [[ " $soms " =~ " $som_filter " ]]; then
                        soms="$som_filter"
                    else
                        continue
                    fi
                fi

                for som in $soms; do
                    local carriers=$(get_carriers_for_vendor "$vendor")
                    if [[ -n "$carrier_filter" ]]; then
                        if [[ " $carriers " =~ " $carrier_filter " ]]; then
                            carriers="$carrier_filter"
                        else
                            continue
                        fi
                    fi
                    for carrier in $carriers; do
                        echo "${version}:${vendor}:${som}:${carrier}"
                    done
                done
            else
                # No SoM for this version+vendor
                if [[ -n "$som_filter" ]]; then
                    continue  # Skip: this version doesn't have SoMs
                fi

                local carriers=$(get_carriers_for_vendor "$vendor")
                if [[ -n "$carrier_filter" ]]; then
                    if [[ " $carriers " =~ " $carrier_filter " ]]; then
                        carriers="$carrier_filter"
                    else
                        continue
                    fi
                fi
                for carrier in $carriers; do
                    echo "${version}:${vendor}::${carrier}"
                done
            fi
        done
    done
}

# Parse a configuration string "version:vendor:som:carrier"
# Args: config_string var_prefix
# Sets: ${var_prefix}_VERSION, ${var_prefix}_VENDOR, ${var_prefix}_SOM, ${var_prefix}_CARRIER
parse_config() {
    local config="$1"
    local prefix="${2:-CFG}"

    local version vendor som carrier
    IFS=':' read -r version vendor som carrier <<< "$config"

    eval "${prefix}_VERSION='$version'"
    eval "${prefix}_VENDOR='$vendor'"
    eval "${prefix}_SOM='$som'"
    eval "${prefix}_CARRIER='$carrier'"
}

# Build command-line arguments from configuration
# Args: version vendor som carrier [extra_args...]
# Returns: String of arguments for l4t_* scripts
build_args() {
    local version="$1"
    local vendor="$2"
    local som="$3"
    local carrier="$4"
    shift 4
    local extra_args="$*"

    local args="-v $version"

    # Always include -V and -c so generated arguments are unambiguous
    # (omitting -V generic would select all vendors when multiple exist for a version)
    args="$args -V $vendor"

    if [[ -n "$som" ]]; then
        args="$args -s $som"
    fi

    args="$args -c $carrier"

    if [[ -n "$extra_args" ]]; then
        args="$args $extra_args"
    fi

    echo "$args"
}

# Count configurations
count_configs() {
    local version_filter="$1"
    local vendor_filter="$2"
    local som_filter="$3"
    local carrier_filter="$4"

    enumerate_configs "$version_filter" "$vendor_filter" "$som_filter" "$carrier_filter" 2>/dev/null | wc -l
}

# Validate configuration filters and report errors
validate_filters() {
    local version_filter="$1"
    local vendor_filter="$2"
    local som_filter="$3"
    local carrier_filter="$4"

    local errors=0
    local all_versions=$(get_all_versions)
    local all_vendors=$(get_all_vendors)
    local all_soms=$(get_all_soms)
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

    # Check SoM filter is valid
    if [[ -n "$som_filter" ]]; then
        if [[ ! " $all_soms " =~ " $som_filter " ]]; then
            echo "Error: Invalid SoM '$som_filter'" >&2
            echo "Available SoMs: $all_soms" >&2
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
        local count=$(count_configs "$version_filter" "$vendor_filter" "$som_filter" "$carrier_filter")
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

            if [[ -n "$version_filter" && -n "$som_filter" ]]; then
                local matched_versions=$(match_versions "$version_filter")
                for v in ${matched_versions:-""}; do
                    local valid_soms=$(get_soms_for_version_vendor "$v" "${vendor_filter:-generic}")
                    if [[ -n "$valid_soms" && ! " $valid_soms " =~ " $som_filter " ]]; then
                        echo "  - Version $v does not support SoM '$som_filter' for vendor '${vendor_filter:-generic}' (supports: $valid_soms)" >&2
                    fi
                done
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
  -s, --som SOM                  SoM variant (e.g. t210, t186; for 32.x only)
  -c, --carrier-board BOARD      Carrier board (default depends on vendor)
  -p, --package-version VERSION  Package version for delivery package
  --standalone                   Build standalone kernel with -eg suffix
                                   (auto per eg_config.yaml)
  --archive-dir DIR              Archive directory relative to ROOT_DIR
                                   (default: archives)
  --delivery-dir DIR             Delivery directory relative to ROOT_DIR
                                   (default: delivery)
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
    SOM_BOARD=""
    CARRIER_BOARD=""
    PACKAGE_VERSION=""
    STANDALONE_BUILD=0
    ARCHIVE_DIR_ARG=""
    DELIVERY_DIR_ARG=""
    NO_VERIFY_DTSI=0

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
            -s|--som)
                SOM_BOARD="$2"
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
            --standalone)
                STANDALONE_BUILD=1
                shift
                ;;
            --archive-dir)
                ARCHIVE_DIR_ARG="$2"
                shift 2
                ;;
            --delivery-dir)
                DELIVERY_DIR_ARG="$2"
                shift 2
                ;;
            --no-verify-dtsi)
                NO_VERIFY_DTSI=1
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

    # Validate SoM if provided
    if [[ -n "$SOM_BOARD" ]]; then
        local all_soms=$(get_all_soms)
        if [[ ! " $all_soms " =~ " $SOM_BOARD " ]]; then
            echo "Error: Invalid SoM '$SOM_BOARD'. Valid values: $all_soms"
            exit 1
        fi
        local valid_soms=$(get_soms_for_version_vendor "$L4T_VERSION" "$VENDOR")
        if [[ -z "$valid_soms" ]]; then
            echo "Error: L4T $L4T_VERSION with vendor '$VENDOR' does not support SoM variants"
            exit 1
        fi
        if [[ ! " $valid_soms " =~ " $SOM_BOARD " ]]; then
            echo "Error: SoM '$SOM_BOARD' is not valid for L4T $L4T_VERSION / vendor '$VENDOR'"
            echo "Supported SoMs: $valid_soms"
            exit 1
        fi
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
    local valid_carriers=$(get_carriers_for_vendor "$VENDOR")
    if [[ ! " $valid_carriers " =~ " $CARRIER_BOARD " ]]; then
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

    # Determine source package prefix.
    # For versions with per-SoM BSP packages (e.g. 32.x: t210 vs t186),
    # use sources_by_som.<som> if defined; otherwise fall back to sources.
    local src_prefix="version.$version.sources"
    ARCHIVE_SOM_SUBDIR=""
    if [[ -n "$SOM_BOARD" ]]; then
        local _sbs_test
        _sbs_test=$($_EGCFG "version.$version.sources_by_som.$SOM_BOARD.public.filename" "$L4T_CONFIG_FILE" 2>/dev/null)
        if [[ $? -eq 0 && -n "$_sbs_test" ]]; then
            src_prefix="version.$version.sources_by_som.$SOM_BOARD"
            ARCHIVE_SOM_SUBDIR="$SOM_BOARD"
        fi
    fi

    # JetPack version
    JETPACK_VERSION=$($_EGCFG "version.$version.jetpack" "$L4T_CONFIG_FILE" 2>/dev/null || echo "")

    # Source packages
    JETSON_PUBLIC_SOURCES=$($_EGCFG "$src_prefix.public.filename" "$L4T_CONFIG_FILE")
    JETSON_PUBLIC_SOURCES_URL=$($_EGCFG "$src_prefix.public.url" "$L4T_CONFIG_FILE")

    L4T_RELEASE_PACKAGE=$($_EGCFG "$src_prefix.release.filename" "$L4T_CONFIG_FILE")
    L4T_RELEASE_PACKAGE_URL=$($_EGCFG "$src_prefix.release.url" "$L4T_CONFIG_FILE")

    SAMPLE_FS_PACKAGE=$($_EGCFG "$src_prefix.sample_fs.filename" "$L4T_CONFIG_FILE")
    SAMPLE_FS_PACKAGE_URL=$($_EGCFG "$src_prefix.sample_fs.url" "$L4T_CONFIG_FILE")

    # Toolchain
    JETSON_TOOLCHAIN_ARCHIVE=$($_EGCFG "version.$version.toolchain.archive" "$L4T_CONFIG_FILE")
    JETSON_TOOLCHAIN_ARCHIVE_URL=$($_EGCFG "version.$version.toolchain.url" "$L4T_CONFIG_FILE")
    TOOLCHAIN_DIR=$($_EGCFG "version.$version.toolchain.dir" "$L4T_CONFIG_FILE")
    local toolchain_prefix=$($_EGCFG "version.$version.toolchain.prefix" "$L4T_CONFIG_FILE")

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

    # Kernel source subdirectory and family label (per L4T family).
    # OOT families (>=36) use nvidia-oot; in-tree families (32/35) use Kconfig/defconfig.
    case "$L4T_VERSION_MAJOR" in
        32) KERNEL_SUBDIR="kernel-4.9";       L4T_FAMILY="32.x" ;;
        35) KERNEL_SUBDIR="kernel-5.10";      L4T_FAMILY="35.x" ;;
        36) KERNEL_SUBDIR="kernel-jammy-src"; L4T_FAMILY="36.x" ;;
        39) KERNEL_SUBDIR="kernel-noble";     L4T_FAMILY="39.x" ;;
        *)  KERNEL_SUBDIR="kernel-noble";     L4T_FAMILY="${L4T_VERSION_MAJOR}.x" ;;
    esac

    # Directory paths
    ROOT_DIR=$(pwd)
    ARCHIVE_DIR=${ARCHIVE_DIR_ARG:+$ROOT_DIR/$ARCHIVE_DIR_ARG}
    ARCHIVE_DIR=${ARCHIVE_DIR:-$ROOT_DIR/archives}
    DELIVERY_DIR=${DELIVERY_DIR_ARG:+$ROOT_DIR/$DELIVERY_DIR_ARG}
    DELIVERY_DIR=${DELIVERY_DIR:-$ROOT_DIR/delivery}

    # Git information
    GIT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
    GIT_EXACT_TAG=$(git describe --tags --exact-match HEAD 2>/dev/null || echo "")
    GIT_COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")

    # SoM directory suffix and source layer
    local som_suffix=$(get_som_dir_suffix "$SOM_BOARD")
    SOM_SOURCE_DIR=""
    if [[ -n "$som_suffix" ]]; then
        SOM_SOURCE_DIR=Linux_for_Tegra_${som_suffix}
    fi

    # Carrier directory suffix and source layer
    local carrier_suffix=$(get_carrier_dir_suffix "$CARRIER_BOARD")
    CARRIER_SOURCE_DIR=""
    if [[ -n "$carrier_suffix" ]]; then
        CARRIER_SOURCE_DIR=Linux_for_Tegra_${carrier_suffix}
    fi

    # Directory naming based on vendor/SoM/carrier
    if [[ "$VENDOR" == "generic" ]]; then
        if [[ -n "$som_suffix" ]]; then
            # e.g. generic + t210 → Linux_for_Tegra_t210
            LINUX_FOR_TEGRA_DIR=Linux_for_Tegra_${som_suffix}
        else
            LINUX_FOR_TEGRA_DIR=Linux_for_Tegra
        fi
        VENDOR_SOURCE_DIR=""
        L4T_VERSION_EXTENDED=${L4T_VERSION}
    else
        if [[ -n "$carrier_suffix" ]]; then
            LINUX_FOR_TEGRA_DIR=Linux_for_Tegra_${VENDOR}_${carrier_suffix}
        else
            LINUX_FOR_TEGRA_DIR=Linux_for_Tegra_${VENDOR}
        fi
        VENDOR_SOURCE_DIR=Linux_for_Tegra_${VENDOR}
        L4T_VERSION_EXTENDED=${L4T_VERSION}_${VENDOR}
    fi

    # PRISTINE_KERNEL: vendor ships a precompiled kernel/nvidia-oot we don't
    # control (e.g. cti). Exported so l4t_copy_sources.sh and l4t_build.sh
    # can skip/gate the nvidia-oot framework patches accordingly.
    PRISTINE_KERNEL=$(get_vendor_pristine_kernel "$VENDOR")
    export PRISTINE_KERNEL

    # Kernel defconfig: SoM takes priority over carrier
    KERNEL_DEFCONFIG=$(get_som_defconfig "$SOM_BOARD")
    if [[ -z "$KERNEL_DEFCONFIG" ]]; then
        KERNEL_DEFCONFIG=$(get_carrier_defconfig "$CARRIER_BOARD")
    fi

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

    # Package archive directory.
    # When the version uses per-SoM BSP packages (sources_by_som), archives
    # are stored in a SoM-specific subdir to avoid filename clashes (e.g.
    # t210 and t186 both ship public_sources.tbz2).
    # ARCHIVE_SOM_SUBDIR is set by load_version_config.
    PKG_ARCHIVE_DIR="$ARCHIVE_DIR/$L4T_VERSION${ARCHIVE_SOM_SUBDIR:+/$ARCHIVE_SOM_SUBDIR}"
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

#******************************************************************************
# Status reporting for parallel execution monitoring
# If L4T_STATUS_FILE is set (by l4t_make.sh), writes status to that file
# for live monitoring. Always prints to stdout as well.
# Usage: update_status "message"
#******************************************************************************
update_status() {
    local msg="$1"
    echo "$msg"
    if [[ -n "$L4T_STATUS_FILE" ]]; then
        echo "$msg" > "$L4T_STATUS_FILE"
    fi
}

# Export the initialization function for scripts that need full setup
l4t_init() {
    parse_l4t_args "$@"
    compute_derived_vars
}
