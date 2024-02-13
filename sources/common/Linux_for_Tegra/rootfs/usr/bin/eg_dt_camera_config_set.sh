#!/bin/bash

if [[ x$1 == x ]]
then
   echo "Error : please provide a DTB file path"
   exit
fi

if [[ ! -f $1 ]]
then
   echo "Error : $1 doesn't exist"
   exit
fi
if [[ x$2 == x ]]
then
   echo "Error : please provide a DTBO file path"
   exit
fi

if [[ ! -f $2 ]]
then
   echo "Error : $2 doesn't exist"
   exit
fi

sudo cp $1 $1.bak
sudo fdtoverlay -i $1.bak -o $1 $2

