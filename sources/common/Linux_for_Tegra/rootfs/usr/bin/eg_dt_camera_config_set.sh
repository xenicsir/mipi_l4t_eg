#!/bin/bash

# Camera database: camera_name -> MIPI lane overlay suffix (empty = no overlay needed)
declare -A CAMERA_LANES=(
	[Dione]=""
	[MicroCube640]="EC_1_lane"
	[MicroCube]="EC_1_lane"
	[SmartIR640]="EC_2_lanes"
	[Crius1280]="EC_2_lanes"
	[iLumos]="iLumos"
	[ilumos]="iLumos"
	[Microlynx]="Microlynx"
	[microlynx]="Microlynx"
)

# Cameras requiring x4 MIPI lanes
declare -A CAMERA_X4=(
	[iLumos]=1
	[ilumos]=1
)

SUPPORTED_CAMERAS=$(IFS=,; echo "${!CAMERA_LANES[*]}" | tr ' ' '\n' | sort | paste -sd', ')

DEFAULT_CAMERA="Dione"

usage() {
	echo "Usage: $(basename "$0") [<port/camera_type>] ..."
	echo ""
	echo "Configure Exosens camera device tree overlays on Jetson boards."
	echo ""
	echo "Arguments:"
	echo "  port/camera_type  Pair of port number and camera type separated by '/'"
	echo ""
	echo "Without arguments, all detected ports are configured with $DEFAULT_CAMERA."
	echo ""
	echo "Supported cameras: $SUPPORTED_CAMERAS"
	echo ""
	echo "Examples:"
	echo "  $(basename "$0")                                              # all ports with $DEFAULT_CAMERA"
	echo "  $(basename "$0") 0/Dione"
	echo "  $(basename "$0") 0/MicroCube 1/SmartIR640"
	echo "  $(basename "$0") 0/Dione 1/MicroCube 2/SmartIR640 3/iLumos"
}

if [[ "$1" == "-h" || "$1" == "--help" ]]; then
	usage
	exit 0
fi

BOARD=$(detect_jetson_board.sh --short)

# Detect number of camera ports from device tree
CAMERA_PORTS=$(detect_jetson_board.sh --camera-ports 2>/dev/null)
if [[ -z "$CAMERA_PORTS" || "$CAMERA_PORTS" -eq 0 ]] 2>/dev/null; then
	echo "Warning: could not detect camera port count, defaulting to 8"
	CAMERA_PORTS=8
fi
MAX_PORT=$(( CAMERA_PORTS - 1 ))

# Default: all ports with DEFAULT_CAMERA
if [[ $# -eq 0 ]]; then
	args=()
	for port in $(seq 0 $MAX_PORT); do
		args+=("$port/$DEFAULT_CAMERA")
	done
	set -- "${args[@]}"
fi

case "$BOARD" in
  dsboard-*|milboard-*|raiboard-*)
	  echo "Forecr board detected: $BOARD"
	  ;;
  nvidia-*)
	  echo "Nvidia official board"
	  ;;
  connecttech-*|auvidea-*)
	  echo "Third-party board: $BOARD"
	  ;;
esac

disable_imx219_arg=""
if [[ x$BOARD == xdsboard-ornxs ]]; then
   base_devicetree="Exosens Cameras for DSBOARD-ORNXS"
elif grep -q 'nvidia,tegra234' /proc/device-tree/compatible 2>/dev/null; then
   # tegra234 (Orin family) — IMX219 and global-DTBO logic only applies here
   if [[ -n "$(find -L /proc/device-tree -name "rbpcv2_imx219*" -type d 2>/dev/null | head -1)" ]]; then
      # IMX219 nodes present in base DTB (e.g. Auvidea 35.x/36.4/36.4.3): use per-channel DTBO + disable IMX219
      base_devicetree="Exosens Cameras"
      disable_imx219_dtbo="/boot/tegra234-p3737-camera-eg-cams-disable-imx219.dtbo"
      if [[ ! -f "$disable_imx219_dtbo" ]]; then
         echo "Error: IMX219 nodes found in device tree but DTBO not installed: $disable_imx219_dtbo" >&2
         exit 1
      fi
      disable_imx219_arg="2=Exosens Cameras. Disable imx219"
   elif [[ -f "/boot/tegra234-p3737-camera-eg-cams-dione-global.dtbo" ]]; then
      # No IMX219, global DTBO present: base DTB uses global NVCSI endpoint numbering (35.x NVIDIA std / Auvidea 35.4.1+)
      base_devicetree="Exosens Cameras (global)"
   else
      base_devicetree="Exosens Cameras"
   fi
else
   # Other SoCs (e.g. tegra194 Xavier NX): IMX219 nodes may be present in base DTB
   # but do not conflict with EG camera overlays — no disable needed
   base_devicetree="Exosens Cameras"
fi

dtboarg=()

for arg in "$@"; do
	if [[ "$arg" != */* ]]; then
		echo "Error: invalid argument '$arg'. Expected format: port_number/camera_type"
		echo ""
		usage
		exit 1
	fi

	port_number="${arg%%/*}"
	camera_type="${arg#*/}"

	if [[ ! "$port_number" =~ ^[0-9]+$ ]] || [[ "$port_number" -gt "$MAX_PORT" ]]; then
		echo "Error: invalid port number '$port_number' (from argument '$arg'). Must be 0-$MAX_PORT."
		exit 1
	fi

	if [[ -z "${CAMERA_LANES[$camera_type]+x}" ]]; then
		echo "Error: unknown camera type '$camera_type' (from argument '$arg')."
		echo "Supported cameras: $SUPPORTED_CAMERAS"
		exit 1
	fi

	# x4 cameras on port 0 require proper CSI0_CLK routing (Forecr boards only)
	if [[ -n "${CAMERA_X4[$camera_type]+x}" ]] && [[ "$port_number" -eq 0 ]]; then
		case "$BOARD" in
			dsboard-*|milboard-*|raiboard-*)
				;; # Forecr boards support x4 on port 0 (CSI0_CLK correctly routed)
			*)
				echo "Error: $camera_type requires 4 MIPI lanes (x4) which is not supported on port 0 of $BOARD."
				echo "On Nvidia devkit, CAM0 (J20) has a lane swap and uses CSI1_CLK, limiting it to x2."
				echo "Use port 1 (CAM1/J21) which supports x4 via CSI2_CLK."
				exit 1
				;;
		esac
	fi

	lanes="${CAMERA_LANES[$camera_type]}"
	if [[ -n "$lanes" ]]; then
		dtboarg+=("2=Exosens Cameras. CAM$port_number:$lanes")
	fi

    echo "Port number : $port_number"
    echo "Camera type : $camera_type"

done

for (( i=0; i<${#dtboarg[@]}; i++ )); do
	echo overlay ${dtboarg[$i]}
done

cmd="python /opt/eg/jetson-io/config-by-hardware.py -n"

# Build command arguments dynamically
cmd_args=("2=$base_devicetree")
[[ -n "$disable_imx219_arg" ]] && cmd_args+=("$disable_imx219_arg")
cmd_args+=("${dtboarg[@]}")

# Debug: Show all command arguments
#echo "Number of arguments: ${#cmd_args[@]}"
#for (( i=0; i<${#cmd_args[@]}; i++ )); do
#	echo "  cmd_args[$i] : ${cmd_args[$i]}"
#done

# Execute the command with all arguments
# Capture output and errors
output=$(sudo $cmd "${cmd_args[@]}" 2>&1)
exit_code=$?

# Display captured output (including errors)
echo "$output"

# Check if execution failed
if [ $exit_code -ne 0 ]; then
    echo "Error: Failed to configure camera device tree." >&2
    echo "Exit code: $exit_code" >&2
    exit $exit_code
fi

# Verify the DTB file was actually created (35.x / fdtoverlay-on-apply path)
dtb_file=$(echo "$output" | sed -n 's/Configuration saved to \(.*\)\./\1/p')
if [ -n "$dtb_file" ] && [ ! -f "$dtb_file" ]; then
    echo "Error: DTB file was not created despite success message." >&2
    echo "Expected file: $dtb_file" >&2
    echo "This usually indicates a permission issue with /boot directory." >&2
    echo "Try running: sudo ls -ld /boot" >&2
    exit 1
fi

# In 36.x, jetson-io writes an OVERLAYS line to extlinux.conf and the
# bootloader applies fdtoverlay at boot time — there is no apply-time
# validation.  Perform a dry-run fdtoverlay check here so that a corrupt
# or incompatible DTBO is caught before the next reboot.
if echo "$output" | grep -q "extlinux.conf to add following DTBO"; then
    extlinux_conf="/boot/extlinux/extlinux.conf"
    base_dtb=$(grep -A30 '^LABEL JetsonIO' "$extlinux_conf" \
               | grep -oP '^\s*FDT\s+\K\S+' | head -1)
    overlays_line=$(grep -A30 '^LABEL JetsonIO' "$extlinux_conf" \
                    | grep -oP '^\s*OVERLAYS\s+\K\S+' | head -1)

    if [[ -z "$base_dtb" || -z "$overlays_line" ]]; then
        echo "Warning: could not parse FDT/OVERLAYS from $extlinux_conf — skipping fdtoverlay check." >&2
    else
        IFS=',' read -ra _dtbos <<< "$overlays_line"
        _tmpout=$(mktemp /tmp/eg_dtcheck_XXXXXX.dtb)
        _errtmp=$(mktemp /tmp/eg_dtcheck_err_XXXXXX.txt)

        echo ""
        echo "Validating DTBOs with fdtoverlay (dry-run)..."
        if fdtoverlay -i "$base_dtb" -o "$_tmpout" "${_dtbos[@]}" 2>"$_errtmp"; then
            rm -f "$_tmpout" "$_errtmp"
            echo "fdtoverlay validation: OK"
        else
            _err_msg=$(cat "$_errtmp")
            rm -f "$_tmpout" "$_errtmp"
            echo "" >&2
            echo "ERROR: fdtoverlay validation FAILED!" >&2
            echo "The following DTBOs were written to extlinux.conf but cannot be applied:" >&2
            for _dtbo in "${_dtbos[@]}"; do
                echo "  $_dtbo" >&2
            done
            echo "" >&2
            echo "fdtoverlay error output:" >&2
            echo "$_err_msg" >&2
            echo "" >&2
            echo "WARNING: The system will likely FAIL TO BOOT with this configuration." >&2
            echo "Please fix the invalid DTBO(s) and re-run this script before rebooting." >&2
            echo "The previous extlinux.conf was backed up as: ${extlinux_conf}.jetson-io-backup" >&2
            exit 1
        fi
    fi
fi

