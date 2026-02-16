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

if [[ x$BOARD == xdsboard-ornxs ]]
then
   base_devicetree="Exosens Cameras for DSBOARD-ORNXS"
else
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
cmd_args=("2=$base_devicetree" "${dtboarg[@]}")

# Debug: Show all command arguments
#echo "Number of arguments: ${#cmd_args[@]}"
#for (( i=0; i<${#cmd_args[@]}; i++ )); do
#	echo "  cmd_args[$i] : ${cmd_args[$i]}"
#done

# Execute the command with all arguments
sudo $cmd "${cmd_args[@]}"

