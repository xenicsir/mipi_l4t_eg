#!/bin/bash

board_found=0
for boardtype in "Jetson Nano" "Jetson Xavier NX" "Jetson AGX Orin"
do
   grep "$boardtype" /proc/device-tree/model >> /dev/null
   if [[ $? == 0 ]]
   then
      board_found=1
      break
   fi
done

if [[ board_found == 0 ]]
then
   echo "Unsupported board type $(cat /proc/device-tree/model)"
   exit
fi

# Get device tree filename. Must be part of the eg-cams label, which must be the default one
dtbfile=$(grep -A 5  "LABEL eg-cams" /boot/extlinux/extlinux.conf |grep FDT | awk '{print $2}')

if [[ $boardtype == "Jetson Xavier NX" ]]
then
   port1="0"
   port2="1"
   dtboname=tegra194-p3668-all-p3509-0000-eg-cam${1}
elif [[ $boardtype == "Jetson Nano" ]]
then
   port1="0"
   port2="1"
   dtboname=tegra210-p3448-all-p3449-0000-eg-cam${1}
elif [[ $boardtype == "Jetson AGX Orin" ]]
then
   port1="AB"
   port2="CD"
   dtboname=tegra234-p3701-all-p3737-0000-eg-auvidea-cam${1}
else
   echo "Unknown board type $boardtype"
fi


if [[ x$1 == x ]]
then
   echo "Error : please specify the camera port number : $port1 or $port2"
   exit
fi

if [[ $1 != $port1 && $1 != $port2  ]]
then
   echo "Error : the camera port number must be $port1 or $port2"
   exit
fi


if [[ x$2 == x ]]
then
   echo "Error : please specify the camera type: Dione, MicroCube640, SmartIR640 or Crius1280"
   exit
fi

case $2 in
Dione)
   dtbofile=/boot/eg/${dtboname}-dione.dtbo
   ;;
MicroCube640|nanovizir)
   dtbofile=/boot/eg/${dtboname}-ec-1-lane.dtbo
   ;;
SmartIR640|Crius1280)
   dtbofile=/boot/eg/${dtboname}-ec-2-lanes.dtbo
   ;;
*)
   echo "Unknown camera type. Dione, MicroCube640, SmartIR640 or Crius1280 are supported"
   exit
   ;;
esac

if [[ ! -f $dtbfile ]]
then
   echo "Error : $dtbfile doesn't exist"
   exit
fi

if [[ ! -f $dtbofile ]]
then
   echo "Error : $dtbofile doesn't exist"
   exit
fi

echo Patching overlay $dtbofile to $dtbfile

sudo cp $dtbfile $dtbfile.bak
sudo fdtoverlay -i $dtbfile.bak -o $dtbfile $dtbofile

