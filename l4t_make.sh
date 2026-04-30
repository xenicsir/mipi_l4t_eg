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
# Version/Vendor/SoM/Carrier Selection:
#   -v, --l4t-version PATTERN   Version filter: exact (35.5.0), wildcard ("36.*"), or .x shorthand (36.x, 35.6.x)
#   -V, --vendor VENDOR         Vendor filter: generic, forecr (default: all)
#   -s, --som SOM               SoM filter: t210, t186 (for 32.x only)
#   -c, --carrier-board BOARD   Carrier board filter (default: all for vendor)
#
# Build Steps (at least one required):
#   --prepare                   Run l4t_prepare.sh (download and extract)
#   --copy-sources              Run l4t_copy_sources.sh (copies sources + generates patch)
#   --patch-sources             Run l4t_patch_sources.sh (applies pre-generated patch)
#   --build                     Run l4t_build.sh
#   --gen-package               Run l4t_gen_delivery_package.sh
#
# Execution Options:
#   --from-scratch              Delete existing build directory before prepare
#   --abort-on-error            Stop immediately on first error (default)
#   --continue-on-error         Continue with next configuration on error
#   --dry-run                   Show what would be executed without running
#   -j, --jobs N                Run N configurations in parallel (default=0=auto)
#   -p, --package-version VER   Package version for delivery (passed to gen-package)
#   --standalone                Force standalone build
#   --no-verify-dtsi            Skip DTSI structure verification (useful during DT development)
#   --archive-dir DIR           Archive directory for BSP downloads (passed to prepare)
#   --delivery-dir DIR          Delivery directory for packages (passed to gen-package)
#
# Other:
#   --list                      List all matching configurations and exit
#   -h, --help                  Show this help message
#
# Examples:
#   ./l4t_make.sh -v 36.4.3                            # All steps for 36.4.3 generic
#   ./l4t_make.sh -v 36.x -V forecr --build            # Build all 36.x forecr versions
#   ./l4t_make.sh --prepare --copy-sources             # Prepare and copy all versions
#   ./l4t_make.sh -v 35.6.x --continue-on-error        # All 35.6.x, continue on error
#   ./l4t_make.sh --prepare -j 4                       # Prepare all versions, 4 in parallel
#   ./l4t_make.sh --prepare -j 0                       # Prepare all versions, auto parallelism
#   ./l4t_make.sh --list                               # List all configurations
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
SOM_FILTER=""
CARRIER_FILTER=""
PACKAGE_VERSION=""
STANDALONE_OPT=""
ARCHIVE_DIR_OPT=""
DELIVERY_DIR_OPT=""
NO_VERIFY_DTSI_OPT=""

NO_ARGS=0
[[ $# -eq 0 ]] && NO_ARGS=1

DO_PREPARE=0
DO_COPY_SOURCES=0
DO_PATCH_SOURCES=0
DO_BUILD=0
DO_GEN_PACKAGE=0

FROM_SCRATCH=0
CONTINUE_ON_ERROR=0
DRY_RUN=0
LIST_ONLY=0
PARALLEL_JOBS=0

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
    echo "Supported configurations:"
    printf "  %-12s %-10s %-8s %s\n" "VERSION" "VENDOR" "SOM" "CARRIER"
    echo "  ------------------------------------------------"
    local configs=$(enumerate_configs "" "" "" "")
    for config in $configs; do
        parse_config "$config"
        printf "  %-12s %-10s %-8s %s\n" "$CFG_VERSION" "$CFG_VENDOR" "${CFG_SOM:--}" "$CFG_CARRIER"
    done
    echo ""
    echo "  (use --list to see the build arguments for each configuration)"
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
        -s|--som)
            SOM_FILTER="$2"
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
        --standalone)
            STANDALONE_OPT="--standalone"
            shift
            ;;
        --no-verify-dtsi)
            NO_VERIFY_DTSI_OPT="--no-verify-dtsi"
            shift
            ;;
        --archive-dir)
            ARCHIVE_DIR_OPT="--archive-dir $2"
            shift 2
            ;;
        --delivery-dir)
            DELIVERY_DIR_OPT="--delivery-dir $2"
            shift 2
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
        -j|--jobs)
            PARALLEL_JOBS="$2"
            shift 2
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
if ! validate_filters "$VERSION_FILTER" "$VENDOR_FILTER" "$SOM_FILTER" "$CARRIER_FILTER"; then
    exit 1
fi

# If no steps are selected, do all
if [[ $DO_PREPARE -eq 0 && $DO_COPY_SOURCES -eq 0 && $DO_BUILD -eq 0 && $DO_GEN_PACKAGE -eq 0 ]]; then
    DO_PREPARE=1
    DO_COPY_SOURCES=1
    DO_BUILD=1
    DO_GEN_PACKAGE=1
fi

# Check that --from-scratch requires --prepare
if [[ $FROM_SCRATCH -eq 1 && $DO_PREPARE -eq 0 ]]; then
    echo "Error: --from-scratch requires --prepare"
    exit 1
fi

# Note: package version is now fully handled by l4t_gen_delivery_package.sh
# (auto-detects from git tag or branch if -p is not specified)

# Handle parallel jobs (0 = auto = nproc)
if [[ "$PARALLEL_JOBS" == "0" || "$PARALLEL_JOBS" == "auto" ]]; then
    PARALLEL_JOBS=$(nproc 2>/dev/null || echo 4)
    echo -e "${CYAN}Auto-detected $PARALLEL_JOBS parallel jobs${NC}"
fi

#******************************************************************************
# Get configurations to process
#******************************************************************************
configs=$(enumerate_configs "$VERSION_FILTER" "$VENDOR_FILTER" "$SOM_FILTER" "$CARRIER_FILTER")
config_count=$(echo "$configs" | wc -l)

#******************************************************************************
# List mode
#******************************************************************************
if [[ $LIST_ONLY -eq 1 ]]; then
    echo "Matching configurations ($config_count):"
    echo ""
    printf "%-12s %-12s %-8s %-15s %s\n" "VERSION" "VENDOR" "SOM" "CARRIER" "ARGUMENTS"
    echo "-----------------------------------------------------------------------"
    for config in $configs; do
        parse_config "$config"
        args=$(build_args "$CFG_VERSION" "$CFG_VENDOR" "$CFG_SOM" "$CFG_CARRIER")
        printf "%-12s %-12s %-8s %-15s %s\n" "$CFG_VERSION" "$CFG_VENDOR" "${CFG_SOM:--}" "$CFG_CARRIER" "$args"
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
[[ $PARALLEL_JOBS -gt 1 ]] && echo "Parallel jobs: $PARALLEL_JOBS"
[[ -n "$ARCHIVE_DIR_OPT" ]] && echo "Archive dir: ${ARCHIVE_DIR_OPT#--archive-dir }"
[[ -n "$DELIVERY_DIR_OPT" ]] && echo "Delivery dir: ${DELIVERY_DIR_OPT#--delivery-dir }"
[[ $DRY_RUN -eq 1 ]] && echo -e "${YELLOW}Mode: DRY RUN (no commands executed)${NC}"
echo ""

#******************************************************************************
# Execute builds
#******************************************************************************
total_success=0
total_failed=0
declare -a failed_configs

# Create temp directory for parallel logs
LOG_DIR=$(mktemp -d)
trap "rm -rf $LOG_DIR" EXIT

#******************************************************************************
# Function: Run all steps for a single configuration
# Args: $1=config, $2=log_file, $3=status_file (optional)
# Returns 0 on success, 1 on failure
#******************************************************************************
run_config() {
    local config="$1"
    local log_file="$2"
    local status_file="$3"

    # Export status file for child scripts
    if [[ -n "$status_file" ]]; then
        export L4T_STATUS_FILE="$status_file"
        echo "Starting..." > "$status_file"
    fi

    parse_config "$config"
    local base_args=$(build_args "$CFG_VERSION" "$CFG_VENDOR" "$CFG_SOM" "$CFG_CARRIER" "$STANDALONE_OPT" $ARCHIVE_DIR_OPT $DELIVERY_DIR_OPT $NO_VERIFY_DTSI_OPT)
    local config_failed=0

    # Handle --from-scratch
    if [[ $FROM_SCRATCH -eq 1 && $DO_PREPARE -eq 1 ]]; then
        local som_suffix=$(get_som_dir_suffix "$CFG_SOM")
        local carrier_suffix=$(get_carrier_dir_suffix "$CFG_CARRIER")
        if [[ "$CFG_VENDOR" == "generic" ]]; then
            if [[ -n "$som_suffix" ]]; then
                build_dir="$SCRIPT_DIR/$CFG_VERSION/Linux_for_Tegra_${som_suffix}"
            else
                build_dir="$SCRIPT_DIR/$CFG_VERSION/Linux_for_Tegra"
            fi
        else
            if [[ -n "$carrier_suffix" ]]; then
                build_dir="$SCRIPT_DIR/$CFG_VERSION/Linux_for_Tegra_${CFG_VENDOR}_${carrier_suffix}"
            else
                build_dir="$SCRIPT_DIR/$CFG_VERSION/Linux_for_Tegra_${CFG_VENDOR}"
            fi
        fi
        if [[ -d "$build_dir" ]]; then
            [[ -n "$status_file" ]] && echo "Deleting old build..." > "$status_file"
            echo "[from-scratch] Deleting $build_dir"
            sudo rm -rf "$build_dir"
        fi
    fi

    # Run selected steps
    if [[ $DO_PREPARE -eq 1 ]]; then
        [[ -n "$status_file" ]] && echo "Preparing..." > "$status_file"
        echo "[prepare] l4t_prepare.sh $base_args"
        if ! "$SCRIPT_DIR/l4t_prepare.sh" $base_args; then
            [[ -n "$status_file" ]] && echo "FAILED" > "$status_file"
            echo "[FAILED] l4t_prepare.sh"
            return 1
        fi
    fi

    if [[ $DO_COPY_SOURCES -eq 1 ]]; then
        [[ -n "$status_file" ]] && echo "Copying sources..." > "$status_file"
        echo "[copy-sources] l4t_copy_sources.sh $base_args"
        if ! "$SCRIPT_DIR/l4t_copy_sources.sh" $base_args; then
            [[ -n "$status_file" ]] && echo "FAILED" > "$status_file"
            echo "[FAILED] l4t_copy_sources.sh"
            return 1
        fi
    fi

    if [[ $DO_PATCH_SOURCES -eq 1 ]]; then
        [[ -n "$status_file" ]] && echo "Patching sources..." > "$status_file"
        echo "[patch-sources] l4t_patch_sources.sh $base_args"
        if ! "$SCRIPT_DIR/l4t_patch_sources.sh" $base_args; then
            [[ -n "$status_file" ]] && echo "FAILED" > "$status_file"
            echo "[FAILED] l4t_patch_sources.sh"
            return 1
        fi
    fi

    if [[ $DO_BUILD -eq 1 ]]; then
        [[ -n "$status_file" ]] && echo "Building..." > "$status_file"
        echo "[build] l4t_build.sh $base_args"
        if ! "$SCRIPT_DIR/l4t_build.sh" $base_args; then
            [[ -n "$status_file" ]] && echo "FAILED" > "$status_file"
            echo "[FAILED] l4t_build.sh"
            return 1
        fi
    fi

    if [[ $DO_GEN_PACKAGE -eq 1 ]]; then
        [[ -n "$status_file" ]] && echo "Generating package..." > "$status_file"
        local pkg_args="$base_args"
        [[ -n "$PACKAGE_VERSION" ]] && pkg_args="$pkg_args -p $PACKAGE_VERSION"
        echo "[gen-package] l4t_gen_delivery_package.sh $pkg_args"
        if ! "$SCRIPT_DIR/l4t_gen_delivery_package.sh" $pkg_args; then
            [[ -n "$status_file" ]] && echo "FAILED" > "$status_file"
            echo "[FAILED] l4t_gen_delivery_package.sh"
            return 1
        fi
    fi

    [[ -n "$status_file" ]] && echo "Done" > "$status_file"
    echo "[SUCCESS]"
    return 0
}

#******************************************************************************
# Function: Display live status of all parallel jobs
# Uses global arrays: job_configs, job_status, job_pids
#******************************************************************************
display_status() {
    local num_jobs=${#job_configs[@]}
    local i

    # Move cursor up to overwrite previous status lines
    if [[ $DISPLAY_INITIALIZED -eq 1 ]]; then
        printf "\033[${num_jobs}A"
    fi
    DISPLAY_INITIALIZED=1

    for i in "${!job_configs[@]}"; do
        local config="${job_configs[$i]}"
        local status_file="${job_status[$i]}"
        local pid="${job_pids[$i]}"

        parse_config "$config"

        # Format SoM+carrier display (truncate if too long)
        local som_display="${CFG_SOM:--}"
        local carrier_display="$CFG_CARRIER"
        if [[ ${#carrier_display} -gt 15 ]]; then
            carrier_display="${carrier_display:0:12}..."
        fi

        # Check if job is still running
        if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
            local status=$(cat "$status_file" 2>/dev/null || echo "...")
            status="${status:0:30}"
            printf "\033[K  ${BLUE}[Running]${NC} %-12s %-10s %-6s %-15s %s\n" "$CFG_VERSION" "$CFG_VENDOR" "$som_display" "$carrier_display" "$status"
        else
            # Job finished or finishing - check result
            local status=$(cat "$status_file" 2>/dev/null || echo "")
            if [[ "$status" == "Done" ]]; then
                printf "\033[K  ${GREEN}[Done]${NC}    %-12s %-10s %-6s %-15s\n" "$CFG_VERSION" "$CFG_VENDOR" "$som_display" "$carrier_display"
            elif [[ "$status" == "FAILED" ]]; then
                printf "\033[K  ${RED}[Failed]${NC}  %-12s %-10s %-6s %-15s\n" "$CFG_VERSION" "$CFG_VENDOR" "$som_display" "$carrier_display"
            elif [[ -z "$status" ]]; then
                printf "\033[K  ${YELLOW}[Pending]${NC} %-12s %-10s %-6s %-15s\n" "$CFG_VERSION" "$CFG_VENDOR" "$som_display" "$carrier_display"
            else
                # Process died but status file has intermediate message
                # Check log file for final result (may still be writing)
                local log_file="${job_logs[$i]}"
                if grep -q "\[SUCCESS\]" "$log_file" 2>/dev/null; then
                    printf "\033[K  ${GREEN}[Done]${NC}    %-12s %-10s %-6s %-15s\n" "$CFG_VERSION" "$CFG_VENDOR" "$som_display" "$carrier_display"
                elif grep -q "\[FAILED\]" "$log_file" 2>/dev/null; then
                    printf "\033[K  ${RED}[Failed]${NC}  %-12s %-10s %-6s %-15s\n" "$CFG_VERSION" "$CFG_VENDOR" "$som_display" "$carrier_display"
                else
                    # Still finishing, show as running with last known status
                    status="${status:0:30}"
                    printf "\033[K  ${BLUE}[Running]${NC} %-12s %-10s %-6s %-15s %s\n" "$CFG_VERSION" "$CFG_VENDOR" "$som_display" "$carrier_display" "$status"
                fi
            fi
        fi
    done
}

#******************************************************************************
# Execute builds (unified: handles both sequential and parallel)
#******************************************************************************
echo -e "${CYAN}Starting execution ($PARALLEL_JOBS parallel job(s))...${NC}"
echo ""

if [[ $DRY_RUN -eq 1 ]]; then
    for config in $configs; do
        parse_config "$config"
        base_args=$(build_args "$CFG_VERSION" "$CFG_VENDOR" "$CFG_SOM" "$CFG_CARRIER" "$STANDALONE_OPT" $ARCHIVE_DIR_OPT $DELIVERY_DIR_OPT $NO_VERIFY_DTSI_OPT)
        som_label="${CFG_SOM:+/$CFG_SOM}"
        echo -e "${CYAN}$CFG_VERSION / $CFG_VENDOR${som_label} / $CFG_CARRIER:${NC}"
        [[ $DO_PREPARE -eq 1 ]] && echo -e "    ${BLUE}[prepare]${NC} l4t_prepare.sh $base_args"
        [[ $DO_COPY_SOURCES -eq 1 ]] && echo -e "    ${BLUE}[copy-sources]${NC} l4t_copy_sources.sh $base_args"
        [[ $DO_PATCH_SOURCES -eq 1 ]] && echo -e "    ${BLUE}[patch-sources]${NC} l4t_patch_sources.sh $base_args"
        [[ $DO_BUILD -eq 1 ]] && echo -e "    ${BLUE}[build]${NC} l4t_build.sh $base_args"
        if [[ $DO_GEN_PACKAGE -eq 1 ]]; then
            dry_pkg_args="$base_args"
            [[ -n "$PACKAGE_VERSION" ]] && dry_pkg_args="$dry_pkg_args -p $PACKAGE_VERSION"
            echo -e "    ${BLUE}[gen-package]${NC} l4t_gen_delivery_package.sh $dry_pkg_args"
        fi
    done
    total_success=$config_count
else
    # Arrays to track jobs (used by display_status as globals)
    declare -a job_pids=()
    declare -a job_configs=()
    declare -a job_logs=()
    declare -a job_status=()

    DISPLAY_INITIALIZED=0

    # First pass: register all configs and create status files
    for config in $configs; do
        parse_config "$config"
        cfg_som_part="${CFG_SOM:+_$CFG_SOM}"
        log_file="$LOG_DIR/${CFG_VERSION}_${CFG_VENDOR}${cfg_som_part}_${CFG_CARRIER}.log"
        status_file="$LOG_DIR/${CFG_VERSION}_${CFG_VENDOR}${cfg_som_part}_${CFG_CARRIER}.status"

        job_configs+=("$config")
        job_logs+=("$log_file")
        job_status+=("$status_file")
        job_pids+=("")  # Empty pid = not started yet
    done

    # Print initial status lines (header + one per job)
    echo "Jobs status:"
    printf "  %-10s %-12s %-10s %-6s %-15s %s\n" "STATUS" "VERSION" "VENDOR" "SOM" "CARRIER" "STEP"
    for config in "${job_configs[@]}"; do
        echo ""  # Placeholder line for each job
    done
    DISPLAY_INITIALIZED=1

    # Initial display
    display_status

    # Start jobs (respecting PARALLEL_JOBS limit)
    aborted=0
    for i in "${!job_configs[@]}"; do
        config="${job_configs[$i]}"
        log_file="${job_logs[$i]}"
        status_file="${job_status[$i]}"

        # Wait if we've reached max parallel jobs
        while true; do
            running=0
            for pid in "${job_pids[@]}"; do
                [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null && running=$((running + 1))
            done
            [[ $running -lt $PARALLEL_JOBS ]] && break
            display_status
            sleep 0.5
        done

        # Check for failures before starting next job (abort-on-error)
        if [[ $CONTINUE_ON_ERROR -eq 0 ]]; then
            for j in "${!job_pids[@]}"; do
                if [[ -n "${job_pids[$j]}" ]] && ! kill -0 "${job_pids[$j]}" 2>/dev/null; then
                    if grep -q "\[FAILED\]" "${job_logs[$j]}" 2>/dev/null; then
                        aborted=1
                        break 2
                    fi
                fi
            done
        fi

        # Start new job in background
        (
            run_config "$config" "$log_file" "$status_file" > "$log_file" 2>&1
            exit $?
        ) &
        job_pids[$i]=$!
    done

    # Monitor jobs with live status display
    while [[ $aborted -eq 0 ]]; do
        # Check if any jobs are still running
        running=0
        for pid in "${job_pids[@]}"; do
            [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null && running=$((running + 1))
        done

        # Display current status
        display_status

        # Exit loop when all jobs are done
        [[ $running -eq 0 ]] && break

        # Check for failures during monitoring (abort-on-error)
        if [[ $CONTINUE_ON_ERROR -eq 0 ]]; then
            for j in "${!job_pids[@]}"; do
                if [[ -n "${job_pids[$j]}" ]] && ! kill -0 "${job_pids[$j]}" 2>/dev/null; then
                    if grep -q "\[FAILED\]" "${job_logs[$j]}" 2>/dev/null; then
                        aborted=1
                        break
                    fi
                fi
            done
        fi

        sleep 1
    done

    # If aborted, kill remaining running jobs
    if [[ $aborted -eq 1 ]]; then
        for pid in "${job_pids[@]}"; do
            [[ -n "$pid" ]] && kill "$pid" 2>/dev/null || true
        done
    fi

    # Wait for all jobs to fully complete
    wait 2>/dev/null

    # Final display
    display_status
    echo ""

    # Check results
    echo ""
    echo "Results:"
    for i in "${!job_configs[@]}"; do
        parse_config "${job_configs[$i]}"
        log_file="${job_logs[$i]}"
        som_label="${CFG_SOM:+/$CFG_SOM}"

        if grep -q "\[SUCCESS\]" "$log_file" 2>/dev/null; then
            echo -e "  ${GREEN}[OK]${NC} $CFG_VERSION / $CFG_VENDOR${som_label} / $CFG_CARRIER"
            total_success=$((total_success + 1))
        elif [[ -z "${job_pids[$i]}" ]]; then
            # Job was never started (aborted before reaching it)
            echo -e "  ${YELLOW}[Skipped]${NC} $CFG_VERSION / $CFG_VENDOR${som_label} / $CFG_CARRIER"
        else
            echo -e "  ${RED}[FAILED]${NC} $CFG_VERSION / $CFG_VENDOR${som_label} / $CFG_CARRIER"
            total_failed=$((total_failed + 1))
            failed_configs+=("${job_configs[$i]}")
        fi
    done
fi

#******************************************************************************
# Run integration tests (only in "do all" mode, after successful build)
#******************************************************************************
if [[ $NO_ARGS -eq 1 && $total_failed -eq 0 ]]; then
    echo ""
    echo "============================================"
    echo -e "${CYAN}Running integration tests...${NC}"
    echo "============================================"
    if [[ $DRY_RUN -eq 1 ]]; then
        echo -e "    ${BLUE}[test]${NC} bash test/run_all.sh"
    else
        if ! bash "$SCRIPT_DIR/test/run_all.sh"; then
            echo -e "${RED}Integration tests FAILED${NC}"
            exit 1
        fi
    fi
fi

#******************************************************************************
# Summary
#******************************************************************************
echo ""
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
        IFS=':' read -r version vendor som carrier <<< "$fc"
        som_label="${som:+/$som}"
        echo "  - $version / $vendor${som_label} / $carrier"
    done

    # Show logs for failed jobs
    if [[ ${#failed_configs[@]} -gt 0 ]]; then
        echo ""
        echo "============================================"
        echo -e "${RED}Error logs:${NC}"
        echo "============================================"
        for fc in "${failed_configs[@]}"; do
            IFS=':' read -r version vendor som carrier <<< "$fc"
            som_part="${som:+_$som}"
            log_file="$LOG_DIR/${version}_${vendor}${som_part}_${carrier}.log"
            if [[ -f "$log_file" ]]; then
                echo ""
                echo -e "${YELLOW}--- $version / $vendor${som:+/$som} / $carrier ---${NC}"
                tail -50 "$log_file"
            fi
        done
    fi
    exit 1
fi

exit 0
