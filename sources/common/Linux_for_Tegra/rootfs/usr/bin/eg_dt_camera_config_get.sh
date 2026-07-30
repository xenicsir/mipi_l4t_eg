#!/bin/bash
#******************************************************************************
# eg_dt_camera_config_get.sh - Get Exosens camera configuration from device tree
#
# This script detects which Exosens cameras are configured in the device tree
# and which ones are actually connected (physically present).
#
# Returns:
#   0 - Success
#   1 - Error or unsupported board
#
# Usage:
#   ./eg_dt_camera_config_get.sh              # Human-readable output
#   ./eg_dt_camera_config_get.sh --json       # JSON output
#   ./eg_dt_camera_config_get.sh -v           # Verbose output
#******************************************************************************

#******************************************************************************
# CAMERA DATABASE - Add new camera types here
#******************************************************************************
# Format: CATEGORY:I2C_ADDR:DT_NODE_PATTERN:DISPLAY_NAME:MIPI_LANES
#
# Fields:
#   CATEGORY         - Internal category name (used for grouping similar cameras)
#   I2C_ADDR         - I2C address in hex (without 0x prefix, e.g., "0e" for 0x0e)
#   DT_NODE_PATTERN  - Device tree node regex pattern (use ([a-h]) for port letter)
#   DISPLAY_NAME     - Human-readable camera name for output
#   MIPI_LANES       - Number of MIPI lanes: 0 (Dione), 1, or 2
#
# To add a new camera type:
#   1. Add a new line with the camera specifications
#   2. Ensure the device tree pattern matches your camera's node naming
#   3. The I2C address must match your camera's hardware address
#
CAMERA_DATABASE=(
    "dione:0e:xenics_dione_ir_([a-h])@0e:Dione:0"
    "ec_1lane:16:eg_ec_([a-h])@16:MicroCube:1"
    "ec_2lanes:16:eg_ec_([a-h])@16:SmartIR640 or Crius1280:2"
    "ilumos:30:ilumos_([a-h])@30:iLumos:4"
    "microlynx:51:microlynx_([a-h])@51:Microlynx:2"
)

# Output mode
VERBOSE=0
JSON_OUTPUT=0

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        -v|--verbose)
            VERBOSE=1
            shift
            ;;
        --json)
            JSON_OUTPUT=1
            shift
            ;;
        -h|--help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  -v, --verbose    Print detailed information"
            echo "  --json          Output in JSON format"
            echo "  -h, --help      Show this help message"
            echo ""
            echo "Exit codes:"
            echo "  0 - Success"
            echo "  1 - Error or unsupported board"
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            exit 1
            ;;
    esac
done

#******************************************************************************
# Function: Detect connected cameras and map them to physical ports
#******************************************************************************
detect_connected_cameras() {
    # Use global arrays (already declared in main)
    # Initialize - camera_port_map maps port_letter to camera info
    # Format: camera_port_map[port_letter]="category:display_name:i2c_bus:i2c_addr:driver_name"
    declare -gA camera_port_map

    # Build list of unique I2C addresses to scan
    declare -A i2c_addresses
    for camera_spec in "${CAMERA_DATABASE[@]}"; do
        IFS=':' read -r category i2c_addr dt_pattern display_name mipi_lanes <<< "$camera_spec"
        i2c_addresses["$i2c_addr"]=1
    done

    # Scan each unique I2C address
    for i2c_addr in "${!i2c_addresses[@]}"; do
        [[ $VERBOSE -eq 1 ]] && echo "[DEBUG] Scanning I2C address 0x$i2c_addr..." >&2

        # Check sysfs for devices at this I2C address
        for dev_path in /sys/bus/i2c/devices/*-00${i2c_addr}; do
            if [[ ! -d "$dev_path" ]]; then
                continue
            fi

            # Check if driver is bound
            if [[ ! -d "$dev_path/driver" ]]; then
                continue
            fi

            # Extract I2C bus number from device path (e.g., "9-000e" -> "9")
            local dev_name=$(basename "$dev_path")
            local i2c_bus="${dev_name%%-*}"

            # Get driver name
            local driver_name=""
            if [[ -L "$dev_path/driver" ]]; then
                driver_name=$(basename "$(readlink "$dev_path/driver")")
            fi

            [[ $VERBOSE -eq 1 ]] && echo "[DEBUG] Found device: $dev_name (bus=$i2c_bus, driver=$driver_name)" >&2

            # Get the device tree node via of_node symlink
            if [[ -L "$dev_path/of_node" ]]; then
                local of_node=$(readlink -f "$dev_path/of_node" 2>/dev/null)
                [[ $VERBOSE -eq 1 ]] && echo "[DEBUG] Camera found at: $of_node" >&2

                # Try to match against all camera patterns with this I2C address
                for camera_spec in "${CAMERA_DATABASE[@]}"; do
                    IFS=':' read -r category spec_i2c_addr dt_pattern display_name mipi_lanes <<< "$camera_spec"

                    # Skip if I2C address doesn't match
                    if [[ "$spec_i2c_addr" != "$i2c_addr" ]]; then
                        continue
                    fi

                    # Try to extract port letter from device tree path
                    if [[ "$of_node" =~ $dt_pattern ]]; then
                        local port_letter="${BASH_REMATCH[1]}"
                        camera_port_map["$port_letter"]="$category:$display_name:$i2c_bus:$i2c_addr:$driver_name"
                        [[ $VERBOSE -eq 1 ]] && echo "[DEBUG]   -> Port letter: $port_letter ($display_name, bus=$i2c_bus, driver=$driver_name)" >&2
                        break  # Found match, no need to try other patterns
                    fi
                done
            fi
        done
    done
}

#******************************************************************************
# Function: Find video device for a given I2C bus and address
# Returns: /dev/videoN path or empty string
#******************************************************************************
find_video_device() {
    local i2c_bus="$1"
    local i2c_addr="$2"
    local search_pattern="${i2c_bus}-00${i2c_addr}"

    for video_sys in /sys/class/video4linux/video*; do
        if [[ -f "$video_sys/name" ]]; then
            local video_name=$(cat "$video_sys/name" 2>/dev/null)
            if [[ "$video_name" == *"$search_pattern"* ]]; then
                echo "/dev/$(basename "$video_sys")"
                return 0
            fi
        fi
    done
    echo ""
    return 1
}

#******************************************************************************
# Function: Find custom I2C device for a camera
# Searches /dev for driver-specific character devices (e.g., /dev/eg-ec-mipi-*)
# Returns: device path or empty string
#******************************************************************************
find_i2c_chardev() {
    local i2c_bus="$1"
    local i2c_addr="$2"
    local driver_name="$3"

    # Search for devices matching the pattern /dev/<driver>*<bus>*<addr>*
    # Examples: /dev/eg-ec-mipi-10-0016, /dev/dioneir-i2c-9-000e-5b
    for dev in /dev/${driver_name}*; do
        if [[ -c "$dev" ]]; then
            local dev_name=$(basename "$dev")
            # Check if device name contains the bus and address
            if [[ "$dev_name" == *"-${i2c_bus}-"*"${i2c_addr}"* ]] || \
               [[ "$dev_name" == *"-${i2c_bus}-00${i2c_addr}"* ]]; then
                echo "$dev"
                return 0
            fi
        fi
    done
    echo ""
    return 1
}

#******************************************************************************
# Function: Check if a specific camera port is connected
# Sets camera_connected[$port] directly by checking physical port mapping
# Also populates camera_video_dev and camera_i2c_chardev arrays
#******************************************************************************
check_camera_connected() {
    local port_num="$1"
    local port_letter="$2"
    local configured_cam_type="$3"

    # Check if this port letter has a connected camera
    if [[ -n "${camera_port_map[$port_letter]}" ]]; then
        # Parse the camera info: "category:display_name:i2c_bus:i2c_addr:driver_name"
        IFS=':' read -r connected_category connected_display_name conn_i2c_bus conn_i2c_addr conn_driver <<< "${camera_port_map[$port_letter]}"

        # Find video device and I2C chardev for this camera
        camera_video_dev[$port_num]=$(find_video_device "$conn_i2c_bus" "$conn_i2c_addr")
        camera_i2c_chardev[$port_num]=$(find_i2c_chardev "$conn_i2c_bus" "$conn_i2c_addr" "$conn_driver")

        # Read camera details from sysfs and V4L2
        local sysfs_path="/sys/bus/i2c/devices/${conn_i2c_bus}-00${conn_i2c_addr}"
        camera_sysfs_paths[$port_num]="$sysfs_path"
        camera_model[$port_num]=$(cat "$sysfs_path/model" 2>/dev/null | tr -d '\n')
        camera_serial[$port_num]=$(cat "$sysfs_path/serial_number" 2>/dev/null | tr -d '\n')
        camera_fwver[$port_num]=$(cat "$sysfs_path/firmware_version" 2>/dev/null | tr -d '\n')

        # Read native resolution and pixel format from sysfs (preferred)
        camera_resolution[$port_num]=$(cat "$sysfs_path/resolution" 2>/dev/null | tr -d '\n')
        camera_pixfmt[$port_num]=$(cat "$sysfs_path/pixel_format" 2>/dev/null | tr -d '\n')

        # Fallback to V4L2 for resolution and pixel format
        if [[ -z "${camera_resolution[$port_num]}" ]] || [[ -z "${camera_pixfmt[$port_num]}" ]]; then
            if [[ -n "${camera_video_dev[$port_num]}" ]] && command -v v4l2-ctl &>/dev/null; then
                local v4l2_fmt
                v4l2_fmt=$(v4l2-ctl --device "${camera_video_dev[$port_num]}" --get-fmt-video 2>/dev/null)
                if [[ -n "$v4l2_fmt" ]]; then
                    if [[ -z "${camera_resolution[$port_num]}" ]]; then
                        local wh
                        wh=$(echo "$v4l2_fmt" | grep -oP 'Width/Height\s*:\s*\K[0-9]+/[0-9]+')
                        if [[ -n "$wh" ]]; then
                            camera_resolution[$port_num]="${wh}"
                        fi
                    fi
                    if [[ -z "${camera_pixfmt[$port_num]}" ]]; then
                        camera_pixfmt[$port_num]=$(echo "$v4l2_fmt" | grep -oP "Pixel Format\s*:\s*'\K[^']+")
                    fi
                fi
            fi
        fi

        [[ $VERBOSE -eq 1 ]] && echo "[DEBUG] Port $port_num: video=${camera_video_dev[$port_num]} i2c_chardev=${camera_i2c_chardev[$port_num]} model=${camera_model[$port_num]} serial=${camera_serial[$port_num]} res=${camera_resolution[$port_num]} fmt=${camera_pixfmt[$port_num]} fw=${camera_fwver[$port_num]}" >&2

        # Match the configured camera type with the connected camera
        # Check if the display name matches OR if they're in the same category
        if [[ "$configured_cam_type" == "$connected_display_name" ]]; then
            # Exact match - configured type matches detected type
            camera_connected[$port_num]="connected"
            [[ $VERBOSE -eq 1 ]] && echo "[DEBUG] Port $port_num (letter: $port_letter): $configured_cam_type connected (exact match)" >&2
            return 0
        else
            # Check if they share the same I2C address (e.g., both EC cameras)
            # This handles cases where device tree is configured for one EC type but another is connected
            for camera_spec in "${CAMERA_DATABASE[@]}"; do
                IFS=':' read -r category i2c_addr dt_pattern display_name mipi_lanes <<< "$camera_spec"

                if [[ "$display_name" == "$configured_cam_type" ]]; then
                    # Found the configured camera spec, check if connected camera has same I2C address
                    for connected_spec in "${CAMERA_DATABASE[@]}"; do
                        IFS=':' read -r conn_cat conn_i2c conn_dt conn_display conn_lanes <<< "$connected_spec"

                        if [[ "$conn_display" == "$connected_display_name" ]] && [[ "$conn_i2c" == "$i2c_addr" ]]; then
                            # Same I2C address - cameras are compatible
                            camera_connected[$port_num]="connected"
                            [[ $VERBOSE -eq 1 ]] && echo "[DEBUG] Port $port_num (letter: $port_letter): $connected_display_name connected (compatible with $configured_cam_type)" >&2
                            return 0
                        fi
                    done
                    break
                fi
            done
        fi
    fi

    camera_connected[$port_num]="not connected"
    camera_video_dev[$port_num]=""
    camera_i2c_chardev[$port_num]=""
    camera_model[$port_num]=""
    camera_serial[$port_num]=""
    camera_fwver[$port_num]=""
    camera_resolution[$port_num]=""
    camera_pixfmt[$port_num]=""
    [[ $VERBOSE -eq 1 ]] && echo "[DEBUG] Port $port_num (letter: $port_letter): not connected" >&2
    return 1
}

#******************************************************************************
# Function: Detect camera type from device tree node
# Returns camera display name from database based on device tree properties
#******************************************************************************
get_camera_type_from_node() {
    local dt_node_path="$1"

    # Check if node exists and is enabled
    if [[ ! -d "$dt_node_path" ]]; then
        echo "None"
        return 1
    fi

    # Check status (no status file = enabled, or status == "okay")
    local node_status="okay"  # Default if no status file
    if [[ -f "$dt_node_path/status" ]]; then
        node_status=$(tr -d '\0' < "$dt_node_path/status" 2>/dev/null)
    fi

    if [[ "$node_status" != "okay" ]]; then
        echo "None"
        return 1
    fi

    # Get node basename for pattern matching
    local node_name=$(basename "$dt_node_path")

    # Try to match against camera database patterns
    for camera_spec in "${CAMERA_DATABASE[@]}"; do
        IFS=':' read -r category i2c_addr dt_pattern display_name mipi_lanes <<< "$camera_spec"

        # Check if node name matches the pattern
        if [[ "$node_name" =~ $dt_pattern ]]; then
            # For EC cameras (I2C address 0x16), check MIPI lane count
            if [[ "$i2c_addr" == "16" ]] && [[ -f "$dt_node_path/mode0/num_lanes" ]]; then
                local num_lanes=$(tr -d '\0' < "$dt_node_path/mode0/num_lanes" 2>/dev/null)

                # Only return this camera type if MIPI lanes match
                if [[ "$num_lanes" == "$mipi_lanes" ]]; then
                    echo "$display_name"
                    return 0
                fi
            else
                # For non-EC cameras, no lane check needed
                echo "$display_name"
                return 0
            fi
        fi
    done

    echo "None"
    return 1
}

#******************************************************************************
# Function: Discover cameras in specific device tree locations
#******************************************************************************
discover_cameras() {
    local dt_base="/proc/device-tree"
    declare -gA camera_configs
    declare -gA camera_i2c_paths
    declare -gA camera_letters

    # Search locations for camera devices
    # Format: "port_number:path"
    # Port numbers are physical port indices for each carrier board.
    # For cam_i2cmux boards, port number = i2c@N index.
    # For AGX Orin direct I2C, port numbers follow the hardware mapping.
    local search_paths=(
        "0:$dt_base/cam_i2cmux/i2c@0"
        "1:$dt_base/cam_i2cmux/i2c@1"
        "2:$dt_base/cam_i2cmux/i2c@2"
        "3:$dt_base/cam_i2cmux/i2c@3"
        "0:$dt_base/bus@0/cam_i2cmux/i2c@0"
        "1:$dt_base/bus@0/cam_i2cmux/i2c@1"
        "2:$dt_base/bus@0/cam_i2cmux/i2c@2"
        "3:$dt_base/bus@0/cam_i2cmux/i2c@3"
        # Connect Tech Hadron DM: real PCA9540 chip mux (reg 0x70) on cam_i2c,
        # not a GPIO mux — see HADRON_DM_CAM_I2C_MUX in the camera dtsi.
        "0:$dt_base/bus@0/i2c@3180000/tca9540@70/i2c@0"
        "1:$dt_base/bus@0/i2c@3180000/tca9540@70/i2c@1"
        "0:$dt_base/bus@0/i2c@31e0000"
        "1:$dt_base/bus@0/i2c@c240000"
        "2:$dt_base/bus@0/i2c@c250000"
        "3:$dt_base/bus@0/i2c@3180000"
        "0:$dt_base/i2c@31e0000"
        "1:$dt_base/i2c@c240000"
        "2:$dt_base/i2c@c250000"
        "3:$dt_base/i2c@3180000"
    )

    # Build list of unique glob patterns from camera database
    declare -a glob_patterns
    for camera_spec in "${CAMERA_DATABASE[@]}"; do
        IFS=':' read -r category i2c_addr dt_pattern display_name mipi_lanes <<< "$camera_spec"

        # Convert regex pattern to glob pattern
        # xenics_dione_ir_([a-h])@0e -> xenics_dione_ir_*@0e
        # Note: Need to escape parens AND brackets for proper replacement
        local glob_pattern="${dt_pattern//\(\[a-h\]\)/*}"
        glob_patterns+=("$glob_pattern:$dt_pattern")
    done

    # Process each search path
    for search_entry in "${search_paths[@]}"; do
        # Extract port number and path from "port_num:path" format
        local port_num="${search_entry%%:*}"
        local search_path="${search_entry#*:}"

        if [[ ! -d "$search_path" ]]; then
            continue
        fi

        [[ $VERBOSE -eq 1 ]] && echo "[DEBUG] Searching in: $search_path (port $port_num)" >&2

        # Skip if this port is already configured
        if [[ -n "${camera_configs[$port_num]}" ]]; then
            [[ $VERBOSE -eq 1 ]] && echo "[DEBUG]   Port $port_num already configured, skipping" >&2
            continue
        fi

        # Look for all camera device nodes using patterns from database
        for pattern_info in "${glob_patterns[@]}"; do
            IFS=':' read -r glob_pattern regex_pattern <<< "$pattern_info"

            [[ $VERBOSE -eq 1 ]] && echo "[DEBUG]   Trying pattern: $glob_pattern" >&2

            # Search for devices matching this glob pattern
            for dev_node in "$search_path"/$glob_pattern; do
                # Check if glob expanded (bash keeps pattern if no match)
                if [[ ! -e "$dev_node" ]]; then
                    [[ $VERBOSE -eq 1 ]] && echo "[DEBUG]     No match for pattern" >&2
                    continue
                fi

                if [[ ! -d "$dev_node" ]]; then
                    continue
                fi

                [[ $VERBOSE -eq 1 ]] && echo "[DEBUG]     Found device: $dev_node" >&2

                # Extract port letter using regex (for connection detection)
                local node_name=$(basename "$dev_node")
                if [[ "$node_name" =~ $regex_pattern ]]; then
                    local port_letter="${BASH_REMATCH[1]}"

                    if [[ -z "$port_letter" ]]; then
                        continue
                    fi

                    [[ $VERBOSE -eq 1 ]] && echo "[DEBUG]       Port letter: $port_letter -> Port num: $port_num" >&2

                    # Get camera type from this device node
                    local cam_type=$(get_camera_type_from_node "$dev_node")

                    [[ $VERBOSE -eq 1 ]] && echo "[DEBUG]       Camera type: $cam_type" >&2

                    if [[ "$cam_type" != "None" ]]; then
                        camera_configs[$port_num]="$cam_type"
                        camera_i2c_paths[$port_num]="$search_path"
                        camera_letters[$port_num]="$port_letter"

                        if [[ $VERBOSE -eq 1 ]]; then
                            echo "[DEBUG] Port $port_num (letter: $port_letter): $cam_type" >&2
                            echo "[DEBUG]   Device: $dev_node" >&2
                            echo "[DEBUG]   I2C path: $search_path" >&2
                        fi
                        break 2  # Found camera for this port, move to next search_entry
                    fi
                fi
            done
        done
    done
}

#******************************************************************************
# Main
#******************************************************************************

# Detect board type using detect_jetson_board.sh
if command -v detect_jetson_board.sh &> /dev/null; then
    BOARD_INFO=$(detect_jetson_board.sh --json 2>/dev/null)
    if [[ $? -eq 0 ]]; then
        BOARD_TYPE=$(echo "$BOARD_INFO" | grep -oP '"board_type":\s*"\K[^"]+' 2>/dev/null)
        SOM_TYPE=$(echo "$BOARD_INFO" | grep -oP '"type":\s*"\K[^"]+' | head -1 2>/dev/null)
        TEGRA_SOC=$(echo "$BOARD_INFO" | grep -oP '"tegra":\s*"\K[^"]+' 2>/dev/null)
    else
        # Fallback to model string
        BOARD_TYPE=$(cat /proc/device-tree/model 2>/dev/null | tr -d '\0')
        SOM_TYPE="unknown"
        TEGRA_SOC="unknown"
    fi
else
    # Fallback to model string
    BOARD_TYPE=$(cat /proc/device-tree/model 2>/dev/null | tr -d '\0')
    SOM_TYPE="unknown"
    TEGRA_SOC="unknown"
fi

# Detect L4T major version to select the appropriate GStreamer display sink.
# - L4T ≤35.x (Ubuntu ≤20.04): nveglglessink is installed and has higher rank
#   than ximagesink; autovideosink picks it but it fails without an EGL display.
#   Use ximagesink directly.
# - L4T ≥36.x (Ubuntu ≥22.04): nveglglessink is not installed; autovideosink
#   selects waylandsink / ximagesink cleanly. On L4T ≥39.x (Ubuntu 24.04+),
#   ximagesink is additionally broken by an XInput2 device-ID bug, so
#   autovideosink is required there too.
_l4t_major=$(grep -oP 'R\K\d+' /etc/nv_tegra_release 2>/dev/null | head -1)
if [[ "${_l4t_major:-0}" -lt 36 ]]; then
    GST_DISPLAY_SINK="ximagesink"
else
    GST_DISPLAY_SINK="autovideosink"
fi

if [[ $VERBOSE -eq 1 ]]; then
    echo "Board Type: $BOARD_TYPE" >&2
    echo "SoM Type: $SOM_TYPE" >&2
    echo "Tegra SoC: $TEGRA_SOC" >&2
    echo "L4T major: ${_l4t_major:-unknown}  → GStreamer sink: $GST_DISPLAY_SINK" >&2
    echo "" >&2
fi

# Discover cameras in device tree
declare -A camera_configs
declare -A camera_i2c_paths
declare -A camera_letters
discover_cameras

# Detect connected cameras
declare -A camera_port_map
detect_connected_cameras

# Determine connection status for each port
declare -A camera_connected
declare -A camera_video_dev
declare -A camera_i2c_chardev
declare -A camera_model
declare -A camera_serial
declare -A camera_fwver
declare -A camera_resolution
declare -A camera_pixfmt
declare -A camera_sysfs_paths
for port in $(echo "${!camera_configs[@]}" | tr ' ' '\n' | sort -n); do
    cam_type="${camera_configs[$port]}"
    port_letter="${camera_letters[$port]}"
    check_camera_connected "$port" "$port_letter" "$cam_type"
done

# Output results
if [[ $JSON_OUTPUT -eq 1 ]]; then
    # JSON output
    echo "{"
    echo "  \"board\": {"
    echo "    \"type\": \"$BOARD_TYPE\","
    echo "    \"som\": \"$SOM_TYPE\","
    echo "    \"tegra\": \"$TEGRA_SOC\""
    echo "  },"
    echo "  \"cameras\": {"

    first=1
    for port in $(echo "${!camera_configs[@]}" | tr ' ' '\n' | sort -n); do
        [[ $first -eq 0 ]] && echo ","
        first=0

        cam_type="${camera_configs[$port]}"
        conn_status="${camera_connected[$port]}"
        video_dev="${camera_video_dev[$port]}"
        i2c_dev="${camera_i2c_chardev[$port]}"
        model="${camera_model[$port]}"
        serial="${camera_serial[$port]}"
        fwver="${camera_fwver[$port]}"
        resolution="${camera_resolution[$port]}"
        pixfmt="${camera_pixfmt[$port]}"

        echo -n "    \"port_$port\": {"
        echo -n "\"type\": \"$cam_type\", "
        echo -n "\"status\": \"$conn_status\""
        if [[ -n "$video_dev" ]]; then
            echo -n ", \"video_device\": \"$video_dev\""
        fi
        if [[ -n "$i2c_dev" ]]; then
            echo -n ", \"i2c_device\": \"$i2c_dev\""
        fi
        if [[ -n "$model" ]]; then
            echo -n ", \"model\": \"$model\""
        fi
        if [[ -n "$serial" ]]; then
            echo -n ", \"serial_number\": \"$serial\""
        fi
        if [[ -n "$fwver" ]]; then
            echo -n ", \"firmware_version\": \"$fwver\""
        fi
        if [[ -n "$resolution" ]]; then
            echo -n ", \"width/height\": \"$resolution\""
        fi
        if [[ -n "$pixfmt" ]]; then
            echo -n ", \"pixel_format\": \"$pixfmt\""
        fi
        echo -n "}"
    done

    echo ""
    echo "  },"
    echo "  \"camera_count\": ${#camera_configs[@]}"
    echo "}"
else
    # Human-readable output
    echo "=== Exosens Camera Configuration ==="
    echo ""
    echo "Board: $BOARD_TYPE ($SOM_TYPE, $TEGRA_SOC)"
    echo ""

    if [[ ${#camera_configs[@]} -eq 0 ]]; then
        echo "No cameras configured in device tree"
    else
        echo "Camera ports configuration:"
        for port in $(echo "${!camera_configs[@]}" | tr ' ' '\n' | sort -n); do
            cam_type="${camera_configs[$port]}"
            conn_status="${camera_connected[$port]}"
            video_dev="${camera_video_dev[$port]}"
            i2c_dev="${camera_i2c_chardev[$port]}"
            model="${camera_model[$port]}"
            serial="${camera_serial[$port]}"
            fwver="${camera_fwver[$port]}"
            resolution="${camera_resolution[$port]}"
            pixfmt="${camera_pixfmt[$port]}"
            sysfs_path="${camera_sysfs_paths[$port]}"

            display_name="$cam_type"
            if [[ "$conn_status" == "connected" ]] && [[ -n "$model" ]]; then
                display_name="$model"
            fi
            echo ""
            if [[ "$conn_status" == "connected" ]]; then
                echo "  Port $port: $display_name ("$'\033[32m'"$conn_status"$'\033[0m'")"
            else
                echo "  Port $port: $display_name ("$'\033[31m'"$conn_status"$'\033[0m'")"
            fi
            if [[ "$conn_status" == "connected" ]]; then
                [[ -n "$video_dev" ]] && echo "    Video device: $video_dev"
                [[ -n "$i2c_dev" ]] && echo "    I2C device:   $i2c_dev"
                [[ -n "$sysfs_path" ]] && echo "    Sysfs:        $sysfs_path"
                [[ -n "$serial" ]] && echo "    Serial:       $serial"
                [[ -n "$fwver" ]] && echo "    FW version:   $fwver"
                [[ -n "$resolution" ]] && echo "    Resolution:   $resolution"
                [[ -n "$pixfmt" ]] && echo "    Pixel format: $pixfmt"
                if [[ -n "$video_dev" ]] && [[ -n "$resolution" ]] && [[ -n "$pixfmt" ]]; then
                    _w="${resolution%%[x/]*}"
                    _h="${resolution##*[x/]}"
                    # Extract fourcc code between the two single-quotes:
                    # sysfs gives "'Y16 ' (desc)" or "'Y16 -BE' (desc)", V4L2 gives "Y16"
                    _raw="${pixfmt#\'}"        # strip leading '
                    _code="${_raw%%\'*}"       # take everything up to next '
                    _v4l2fmt="" ; _gstfmt=""
                    case "$_code" in
                        # GStreamer has no GRAY14_LE (no 14-bit raw video format exists in
                        # GstVideoFormat, any version) — leave _gstfmt empty so only the
                        # v4l2-ctl command is shown. Spoofing GRAY16_LE while the camera is
                        # actually in Y14 corrupts the capture (mismatched DT pix_clk_hz
                        # between the Y14/Y16 modes) — see microlynx_y14_colorfmt_gstreamer.
                        "Y14 "|"Y14") _v4l2fmt='"Y14 "' ;;
                        "Y16 "|"Y16") _v4l2fmt='"Y16 "' ; _gstfmt="GRAY16_LE" ;;
                        "Y16 -BE")    _v4l2fmt='"Y16 -BE"' ; _gstfmt="GRAY16_BE"  ;;
                        "AR24")       _v4l2fmt='"AR24"'  ; _gstfmt="BGRA"      ;;
                        "AB24")       _v4l2fmt='"AB24"'  ; _gstfmt="RGBA"      ;;
                        "YUYV")       _v4l2fmt='"YUYV"'  ; _gstfmt="YUY2"      ;;
                    esac
                    if [[ -n "$_v4l2fmt" ]]; then
                        if [[ "$TEGRA_SOC" == "t210" ]] && [[ "$_gstfmt" == GRAY16* ]]; then
                            echo "    Warning: 16-bit greyscale is not supported on Jetson Nano (t210). Use AR24 or YUYV."
                        else
                            # Each example is printed as ONE line, numbered, and — unlike the
                            # rest of this report — flush at column 0. Two deliberate choices:
                            #  * No backslash continuations: with them the reader has to work
                            #    out where one command ends and the next begins, and a partial
                            #    selection pastes as a silently truncated command. One line =
                            #    one command = one triple-click. Long lines just wrap.
                            #  * No leading indentation: Ubuntu defaults to
                            #    HISTCONTROL=ignoreboth (includes ignorespace), so a pasted
                            #    command that starts with a space is dropped from the shell
                            #    history and cannot be recalled with the up arrow or Ctrl-R.
                            #    The comment lines are flush too, so selecting the comment
                            #    plus its command still pastes cleanly.
                            _cmdno=0
                            _caps="\"video/x-raw, format=(string)$_gstfmt, width=$_w, height=$_h\""
                            echo "    Streaming (one command per line — triple-click to copy):"
                            _cmdno=$((_cmdno + 1))
                            echo "# $_cmdno. Capture only, no display — check the stream is alive:"
                            echo "v4l2-ctl -d $video_dev --stream-mmap --set-fmt-video=width=$_w,height=$_h,pixelformat=$_v4l2fmt"
                            # No -f/-W/-H needed: with no --fmt, rt_frame_monitor reads the
                            # device's currently active pixel format and resolution itself.
                            _cmdno=$((_cmdno + 1))
                            echo "# $_cmdno. Live display + frame-rate/drop monitoring:"
                            echo "rt_frame_monitor.py -d $video_dev --display"
                            if [[ -z "$_gstfmt" ]]; then
                                echo "    Note: GStreamer has no 14-bit greyscale format — use command 1 or 2"
                                echo "          above (rt_frame_monitor.py needs python3-opencv) to display Y14."
                            else
                                _cmdno=$((_cmdno + 1))
                                echo "# $_cmdno. Live display through GStreamer:"
                                echo "gst-launch-1.0 -v v4l2src device=$video_dev ! $_caps ! videoconvert ! $GST_DISPLAY_SINK sync=false"
                                if [[ "$cam_type" == "Microlynx" ]]; then
                                    _cmdno=$((_cmdno + 1))
                                    echo "# $_cmdno. Live display through GStreamer, first line only:"
                                    echo "gst-launch-1.0 -v v4l2src device=$video_dev ! $_caps ! videocrop top=0 bottom=$((_h - 1)) ! \"video/x-raw, width=$_w, height=1\" ! videoconvert ! $GST_DISPLAY_SINK sync=false"
                                fi
                            fi
                        fi
                    fi
                fi
            fi
        done
        echo ""
        echo "Total configured: ${#camera_configs[@]} camera(s)"
    fi
fi

exit 0
