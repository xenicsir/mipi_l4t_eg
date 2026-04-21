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
#   [iLumos]=1
#   [ilumos]=1
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

# Returns 0 (true) if any node matching PATTERN is active in the given DTB file.
# A node is considered active if it does not have an explicit status = "disabled".
# Per the DT spec, absence of status property means "okay" (active).
# Usage: _camera_node_active_in_dtb <dtb_file> <node_pattern>
# Example: _camera_node_active_in_dtb merged.dtb "rbpcv2_imx219"
_camera_node_active_in_dtb() {
    local dtb="$1"
    local pattern="$2"
    command -v dtc &>/dev/null || return 1
    dtc -I dtb -O dts "$dtb" 2>/dev/null | awk -v pat="$pattern" '
        $0 ~ (pat "[^{]*{") { p=1; d=1; disabled=0 }
        p && $0 !~ pat && /{/ { d++ }
        p && /status = "disabled"/ { disabled=1 }
        p && /}/ { d--; if (d<=0) { if (!disabled) found=1; p=0 } }
        END { exit !found }
    '
}

BOARD=$(detect_jetson_board.sh --short)

# Detect number of camera ports from device tree
CAMERA_PORTS=$(detect_jetson_board.sh --camera-ports 2>/dev/null)
if [[ -z "$CAMERA_PORTS" || "$CAMERA_PORTS" -eq 0 ]] 2>/dev/null; then
	echo "Warning: could not detect camera port count, defaulting to 8"
	CAMERA_PORTS=8
fi
MAX_PORT=$(( CAMERA_PORTS - 1 ))

# Remember whether the caller passed explicit ports (default expansion deferred until
# after 2-port detection, so MAX_PORT reflects the board's actual capabilities).
_default_all_ports=0
[[ $# -eq 0 ]] && _default_all_ports=1

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

# Select base overlay name
if [[ x$BOARD == xdsboard-ornxs ]]; then
   base_devicetree="Exosens Cameras for DSBOARD-ORNXS"
else
   base_devicetree="Exosens Cameras"
fi

# Resolve the primary boot DTB (the base kernel DTB that config-by-hardware.py
# applies overlays to at boot time). On tegra234 boards it is the authoritative
# source for IMX219/IMX477 and channel@N presence — more reliable than the live
# /proc/device-tree which reflects the currently-booted user-custom.dtb.
_primary_dtb=""
if grep -q 'nvidia,tegra234' /proc/device-tree/compatible 2>/dev/null; then
   _primary_dtb=$(awk '/^LABEL primary/{f=1} f && /^[[:space:]]*FDT /{print $2; exit}' \
                  /boot/extlinux/extlinux.conf 2>/dev/null)
fi

# 2-port overlay selection — Auvidea X230D on L4T 35.1 ships a kernel DTB that
# only exposes NVCSI channels 0 and 1 (csi_chan0_port0/1, csi_chan1_port0/1 in
# __symbols__). Using the regular 4-port overlay would silently fail at
# fdtoverlay time (FDT_ERR_NOTFOUND on csi_chan{2,3}_port* phandles).
# Gate: "Exosens Cameras" base + the 2ports DTBO is installed + channel@2 absent
# in the primary boot DTB.
if [[ $base_devicetree == "Exosens Cameras" ]] && \
   [[ -n "$_primary_dtb" ]] && \
   [[ -f "/boot/tegra234-p3737-camera-eg-cams-dione-2ports.dtbo" ]] && \
   command -v fdtget >/dev/null 2>&1 && \
   ! fdtget "$_primary_dtb" /host1x@13e00000/nvcsi@15a00000/channel@2 reg >/dev/null 2>&1 && \
   ! fdtget "$_primary_dtb" /bus@0/host1x@13e00000/nvcsi@15a00000/channel@2 reg >/dev/null 2>&1; then
   base_devicetree="Exosens Cameras - 2 ports"
   MAX_PORT=1
fi

# Default all-ports expansion — done here so MAX_PORT reflects 2-port detection above.
if [[ $_default_all_ports -eq 1 ]]; then
   args=()
   for port in $(seq 0 $MAX_PORT); do
      args+=("$port/$DEFAULT_CAMERA")
   done
   set -- "${args[@]}"
fi

# IMX219/IMX477 conflict detection — all boards
# Cache jetson-io overlay list once (avoid multiple sudo calls)
disable_imx219_arg=""
disable_imx477_arg=""
_jetson_io_overlays=$(sudo /opt/eg/jetson-io/config-by-hardware.py -l 2>/dev/null)

# IMX219/IMX477 detection: check both the live DT and the primary boot DTB.
# The live DT may not reflect active nodes if a previous user-custom.dtb already
# disabled them; the kernel DTB is the authoritative source for what will be in
# the new merged DTB.
_imx219_active=0
_imx477_active=0
if [[ -n "$(find -L /proc/device-tree -name "rbpcv2_imx219*" -type d 2>/dev/null | head -1)" ]]; then
   _imx219_active=1
fi
if [[ -n "$_primary_dtb" ]] && _camera_node_active_in_dtb "$_primary_dtb" "rbpcv2_imx219"; then
   _imx219_active=1
fi
if [[ $_imx219_active -eq 1 ]]; then
   # In 2-port mode the 2ports DTBO already folds the IMX219 disable for
   # cam0/cam1 directly into its fragments — a separate disable-imx219 DTBO
   # would target cam2/cam3 paths that don't exist on the 2-channel kernel DTB
   # and would fail fdtoverlay with FDT_ERR_NOTFOUND.
   if [[ $base_devicetree != "Exosens Cameras - 2 ports" ]] && \
      echo "$_jetson_io_overlays" | grep -q "Exosens Cameras. Disable imx219"; then
      disable_imx219_arg="2=Exosens Cameras. Disable imx219"
   fi
fi

if [[ -n "$(find -L /proc/device-tree -name "rbpcv3_imx477*" -type d 2>/dev/null | head -1)" ]]; then
   _imx477_active=1
fi
if [[ -n "$_primary_dtb" ]] && _camera_node_active_in_dtb "$_primary_dtb" "rbpcv3_imx477"; then
   _imx477_active=1
fi
if [[ $_imx477_active -eq 1 ]]; then
   if echo "$_jetson_io_overlays" | grep -q "Exosens Cameras. Disable imx477"; then
      disable_imx477_arg="2=Exosens Cameras. Disable imx477"
   fi
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

	if [[ $base_devicetree == "Exosens Cameras - 2 ports" ]] && [[ "$port_number" -ge 2 ]]; then
		echo "Error: port $port_number is not available on this board. Only CAM0 and CAM1 are supported on this L4T version."
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

# Upgrade to global DTBO on tegra234 when no per-port cam overlays are needed
# and no Disable overlay is needed. The global DTBO uses NVIDIA global NVCSI
# endpoint numbering (endpoint@2 in channel@1, etc.) — compatible with stock
# NVIDIA 35.x and Auvidea 35.4.1+ base DTBs when configuration is Dione-only.
# Per-port cam DTBOs (cam1-ilumos, cam2-ec-*, …) target endpoint@0 (per-channel
# numbering) and would fail fdtoverlay against a global base. Skip the upgrade
# whenever any per-port cam DTBO will be applied.
if [[ $base_devicetree == "Exosens Cameras" ]] && \
   [[ ${#dtboarg[@]} -eq 0 ]] && \
   [[ -z "$disable_imx219_arg" ]] && [[ -z "$disable_imx477_arg" ]] && \
   grep -q 'nvidia,tegra234' /proc/device-tree/compatible 2>/dev/null && \
   [[ -f "/boot/tegra234-p3737-camera-eg-cams-dione-global.dtbo" ]]; then
   base_devicetree="Exosens Cameras (global)"
fi

cmd="python /opt/eg/jetson-io/config-by-hardware.py -n"

# Build command arguments dynamically
cmd_args=("2=$base_devicetree")
[[ -n "$disable_imx219_arg" ]] && cmd_args+=("$disable_imx219_arg")
[[ -n "$disable_imx477_arg" ]] && cmd_args+=("$disable_imx477_arg")
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

# 35.x T234 p3737 (AGX Orin): remove NVCSI extra endpoints from the IMX
# reference design that break the EG configuration.
#
# On base DTBs with NVIDIA "global" endpoint numbering (NVIDIA std, Auvidea
# X230 35.4.1+), each NVCSI channel@N/ports/port@X contains an extra
# endpoint from the IMX reference design alongside the EG endpoint@{0,1}
# created by our overlays.
#
# port@1 side: endpoint@{3,5,7} are ORPHANED — their remote-endpoint phandles
#   pointed to /tegra-capture-vi/ports/port@{1,2,3}/endpoint but our DTSI
#   common redefines those VI nodes as rbpcv2_vi_in{1,2,3}, so DTC drops the
#   original phandles. At runtime, v4l2_fwnode_parse_link fails on them ->
#   tegra_vi_graph_build_one returns error -> subdev probe fails with -EIO.
#
# port@0 side: endpoint@{2,4,6} have valid (but disabled) remote-endpoints.
#   However, the CSI driver (csi.c:803) iterates ALL children of port@0
#   WITHOUT checking 'status', so chan->port[0] gets overwritten by the last
#   endpoint's port-index. With endpoint@{2,4,6} present (port-index=2/2/3),
#   our endpoint@0 port-index (6/4/2) is lost -> wrong csi_port -> wrong
#   stream_id -> "VI channel not found" at stream_open -> 2.5s timeout.
#
# No-op on base DTBs with per-channel numbering (Auvidea X230 35.1/35.3.1)
# where these endpoints don't exist. fdtoverlay cannot /delete-node/ inside
# a target-path="/" fragment, so we post-process the merged DTB here.
if [ -n "$dtb_file" ] && [ -f "$dtb_file" ] && command -v fdtput >/dev/null 2>&1 && \
   grep -q 'nvidia,tegra234' /proc/device-tree/compatible 2>/dev/null; then
    _nvcsi_prefix="/host1x@13e00000/nvcsi@15a00000"
    for _ep_path in \
        "${_nvcsi_prefix}/channel@1/ports/port@0/endpoint@2" \
        "${_nvcsi_prefix}/channel@2/ports/port@0/endpoint@4" \
        "${_nvcsi_prefix}/channel@3/ports/port@0/endpoint@6" \
        "${_nvcsi_prefix}/channel@1/ports/port@1/endpoint@3" \
        "${_nvcsi_prefix}/channel@2/ports/port@1/endpoint@5" \
        "${_nvcsi_prefix}/channel@3/ports/port@1/endpoint@7"; do
        sudo fdtput -r "$dtb_file" "$_ep_path" 2>/dev/null || true
    done
fi

# 35.x: check for active IMX219/IMX477 nodes in the merged DTB
if [ -n "$dtb_file" ] && [ -f "$dtb_file" ]; then
    if _camera_node_active_in_dtb "$dtb_file" "rbpcv2_imx219"; then
        echo "" >&2
        echo "Error: IMX219 camera node(s) are still active in the merged device tree." >&2
        echo "Exosens cameras may not work correctly." >&2
        echo "The 'Exosens Cameras. Disable imx219' overlay is not configured for this board." >&2
        exit 1
    fi
    if _camera_node_active_in_dtb "$dtb_file" "rbpcv3_imx477"; then
        echo "" >&2
        echo "Error: IMX477 camera node(s) are still active in the merged device tree." >&2
        echo "Exosens cameras may not work correctly." >&2
        echo "The 'Exosens Cameras. Disable imx477' overlay is not configured for this board." >&2
        exit 1
    fi
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
            # Check for active IMX219/IMX477 nodes in the merged device tree
            if _camera_node_active_in_dtb "$_tmpout" "rbpcv2_imx219"; then
                rm -f "$_tmpout" "$_errtmp"
                echo "" >&2
                echo "Error: IMX219 camera node(s) are still active in the merged device tree." >&2
                echo "Exosens cameras may not work correctly." >&2
                echo "The 'Exosens Cameras. Disable imx219' overlay is not configured for this board." >&2
                exit 1
            fi
            if _camera_node_active_in_dtb "$_tmpout" "rbpcv3_imx477"; then
                rm -f "$_tmpout" "$_errtmp"
                echo "" >&2
                echo "Error: IMX477 camera node(s) are still active in the merged device tree." >&2
                echo "Exosens cameras may not work correctly." >&2
                echo "The 'Exosens Cameras. Disable imx477' overlay is not configured for this board." >&2
                exit 1
            fi
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

