#!/bin/bash

if [[ x$1 == x ]]
then
   echo "Error : please specify the camera port number : 0 or 1"
   exit
fi

if [[ $1 != "0" && $1 != "1"  ]]
then
   echo "Error : the camera port number must be 0 or 1"
   exit
fi


if [[ x$2 == x ]]
then
   echo "Error : please specify the camera type: Dione, MicroCube640, SmartIR640 or Crius1280"
   exit
fi

case $2 in
Dione)
   dtbofile=/boot/eg/tegra194-p3668-all-p3509-0000-eg-cam${1}-dione.dtbo
   ;;
MicroCube640)
   dtbofile=/boot/eg/tegra194-p3668-all-p3509-0000-eg-cam${1}-ec-1-lane.dtbo
   ;;
SmartIR640|Crius1280)
   dtbofile=/boot/eg/tegra194-p3668-all-p3509-0000-eg-cam${1}-ec-2-lanes.dtbo
   ;;
*)
   echo "Unknown camera type. Dione, MicroCube640, SmartIR640 or Crius1280 are supported"
   exit
   ;;
esac


dtbfile=/boot/eg/tegra194-p3668-0001-p3509-0000-eg-cams.dtb

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

