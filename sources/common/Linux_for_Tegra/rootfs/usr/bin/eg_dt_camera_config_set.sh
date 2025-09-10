#!/bin/bash

if (( $# % 2 ))
then
   echo "Error. Arguments number must be a multiple of 2 : pairs port_number camera_type"
   exit
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

cmd="python /opt/nvidia/jetson-io/config-by-hardware.py -n"

if [[ ${#dtboarg[@]} == 0 ]]
then
   sudo $cmd "2=Exosens Cameras"
elif [[ ${#dtboarg[@]} == 1 ]]
then
   sudo $cmd "2=Exosens Cameras" "${dtboarg[0]}"
elif [[ ${#dtboarg[@]} == 2 ]]
then
   sudo $cmd "2=Exosens Cameras" "${dtboarg[0]}" "${dtboarg[1]}"
elif [[ ${#dtboarg[@]} == 3 ]]
then
   sudo $cmd "2=Exosens Cameras" "${dtboarg[0]}" "${dtboarg[1]}" "${dtboarg[2]}"
elif [[ ${#dtboarg[@]} == 4 ]]
then
   sudo $cmd "2=Exosens Cameras" "${dtboarg[0]}" "${dtboarg[1]}" "${dtboarg[2]}" "${dtboarg[3]}"
elif [[ ${#dtboarg[@]} == 5 ]]
then
   sudo $cmd "2=Exosens Cameras" "${dtboarg[0]}" "${dtboarg[1]}" "${dtboarg[2]}" "${dtboarg[3]}" "${dtboarg[4]}"
elif [[ ${#dtboarg[@]} == 6 ]]
then
   sudo $cmd "2=Exosens Cameras" "${dtboarg[0]}" "${dtboarg[1]}" "${dtboarg[2]}" "${dtboarg[3]}" "${dtboarg[4]}" "${dtboarg[5]}"
elif [[ ${#dtboarg[@]} == 7 ]]
then
   sudo $cmd "2=Exosens Cameras" "${dtboarg[0]}" "${dtboarg[1]}" "${dtboarg[2]}" "${dtboarg[3]}" "${dtboarg[4]}" "${dtboarg[5]}" "${dtboarg[6]}"
elif [[ ${#dtboarg[@]} == 8 ]]
then
   sudo $cmd "2=Exosens Cameras" "${dtboarg[0]}" "${dtboarg[1]}" "${dtboarg[2]}" "${dtboarg[3]}" "${dtboarg[4]}" "${dtboarg[5]}" "${dtboarg[6]}" "${dtboarg[6]}"
else
   echo "Too many camera configurations"
fi

