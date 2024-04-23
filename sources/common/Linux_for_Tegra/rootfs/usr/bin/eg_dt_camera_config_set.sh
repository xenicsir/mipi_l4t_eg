#!/bin/bash

boardtype=$(cat /proc/device-tree/chosen/ids |awk -F"-" '{print $1}')
echo Board type $boardtype

if [[ $boardtype == 3668 || $boardtype == 3448 ]] # Xavier NX or Nano
then
   port1="0"
   port2="1"
   dtboname=tegra194-p3668-all-p3509-0000-eg-cam${1}
   dtbfile=/boot/eg/tegra194-p3668-0001-p3509-0000-eg-cams.dtb
elif [[ $boardtype == 3701 ]] # AGX Orin
then
   port1="AB"
   port2="CD"
   dtboname=tegra234-p3701-all-p3737-0000-eg-auvidea-cam${1}
   dtbfile=/boot/eg/tegra234-p3701-0004-p3737-0000-eg-cams-auvidea.dtb
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
MicroCube640)
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

