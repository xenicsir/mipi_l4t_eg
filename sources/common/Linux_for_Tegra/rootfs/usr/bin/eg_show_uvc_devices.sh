#!/bin/bash

tty_devices=$(echo $(cd /dev/;ls tty*))
for tty_device in $tty_devices
do
   device_file=/sys/class/tty/$tty_device/device
   if [[ x$(ls $device_file 2> /dev/null) != x ]]
   then
      tty_usb_device=$(ls -l $device_file | awk '{print $NF}' | awk -F "/" '{print $NF}' | awk -F ":" '{print $1}')
      manufacturer_file=$device_file/subsystem/devices/$tty_usb_device/manufacturer
      if [[ x$(ls $manufacturer_file 2> /dev/null) != x ]]
      then
         manufacturer=$(cat $manufacturer_file)
         if [[ $manufacturer == "Xenics Exosens" ]]
         then
            serial=$(cat $device_file/subsystem/devices/$tty_usb_device/serial)
            echo "Manufacturer  : $manufacturer"
            echo "Product       : $(cat $device_file/subsystem/devices/$tty_usb_device/product)"
            echo "Serial Number : $serial"
            echo "Serial Port   : /dev/$tty_device"

            video_devices=$(echo $(cd /dev/;ls video*))
            for video_device in $video_devices
            do
               video_usb_device=$(ls -l /sys/class/video4linux/$video_device/device | awk '{print $NF}' | awk -F "/" '{print $NF}' | awk -F ":" '{print $1}')
               serial_video=$(cat /sys/class/video4linux/$video_device/device/subsystem/devices/$video_usb_device/serial)
               if [[ $serial_video == $serial ]]
               then
                  echo "Video device  : /dev/$video_device"
                  break
               fi
            done
            echo
         fi
      fi
   fi
done
