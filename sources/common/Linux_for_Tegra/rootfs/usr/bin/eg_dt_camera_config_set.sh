#!/bin/bash

if (( $# % 2 ))
then
   echo "Error. Arguments number must be a multiple of 2 : pairs port_number camera_type"
   exit
fi

BOARD=$(./detect_jetson_board.sh --short)

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

arguments=( "$@" )
dtboarg=()

for (( i=0; i<${#arguments[@]}; i=i+2 )); do
	port_number=${arguments[$i]}
	camera_type=${arguments[(($i+1))]}
	
	if [[ $port_number != 0 && $port_number != 1 && $port_number != 2 && $port_number != 3 && $port_number != 4 && $port_number != 5 && $port_number != 6 && $port_number != 7 ]]
	then
	   echo "Error : invalid port number $port_number"
	   exit
	fi
	
	case $camera_type in
	Dione)
	   ;;
	MicroCube640)
	   dtboarg+=("2=Exosens Cameras. CAM$port_number:EC_1_lane")
	   ;;
	SmartIR640|Crius1280)
	   dtboarg+=("2=Exosens Cameras. CAM$port_number:EC_2_lanes")
	   ;;
	*)
	   echo "Unknown camera type $camera_type. Dione, MicroCube640, SmartIR640 or Crius1280 are supported"
	   exit
	   ;;
	esac

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

