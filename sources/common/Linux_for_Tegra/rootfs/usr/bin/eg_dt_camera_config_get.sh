#/bin/bash

DIONE_CFG="Dione"
ONE_MIPI_LANE_CFG="MicroCube640"
TWO_MIPI_LANES_CFG="SmartIR640 and Crius1280"

function get_cam_dt {
   if [[ ! -f ${1}/status ]]
   then
      cam=$DIONE_CFG
   else
      if [[ $(tr -d '\0' < ${1}/status) == "okay" ]]
      then
         cam=$DIONE_CFG
      fi
   fi

   if [[ $cam == "None" ]]
   then
      if [[ ! -f ${2}/status ]]
      then
         num_lanes=$(tr -d '\0' < ${2}/mode0/num_lanes)
         if [[ $num_lanes == 1 ]]
         then
            cam=$ONE_MIPI_LANE_CFG
         else
            cam=$TWO_MIPI_LANES_CFG
         fi
      else
         if [[ $(tr -d '\0' < ${2}/status) == "okay" ]]
         then
            num_lanes=$(tr -d '\0' < ${2}/mode0/num_lanes)
            if [[ $num_lanes == 1 ]]
            then
               cam=$ONE_MIPI_LANE_CFG
            else
               cam=$TWO_MIPI_LANES_CFG
            fi
         fi
      fi
   fi
}

board_found=0
for boardtype in "Jetson Nano" "Jetson Xavier NX" "Jetson AGX Orin" "Jetson Orin NX" "Jetson Orin Nano"
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

echo board type $boardtype

if [[ -d /proc/device-tree/bus@0 ]]
then
   bus0="/bus@0"
else
   bus0=""
fi

if [[ $boardtype == "Jetson Xavier NX" ]]
then
   cam=None
   dione_dev=/proc/device-tree$bus0/cam_i2cmux/i2c@0/xenics_dione_ir_a@0e
   eg_ec_dev=/proc/device-tree$bus0/cam_i2cmux/i2c@0/eg_ec_a@16
   if [[ -d $dione_dev && -d $eg_ec_dev ]]
   then
      get_cam_dt $dione_dev $eg_ec_dev
      echo "Camera port 0 configuration : $cam"
   fi

   cam=None
   dione_dev=/proc/device-tree$bus0/cam_i2cmux/i2c@1/xenics_dione_ir_c@0e
   eg_ec_dev=/proc/device-tree$bus0/cam_i2cmux/i2c@1/eg_ec_c@16
   if [[ -d $dione_dev && -d $eg_ec_dev ]]
   then
      get_cam_dt $dione_dev $eg_ec_dev
      echo "Camera port 1 configuration : $cam"
   fi
elif [[ $boardtype == "Jetson Nano" ]]
then
   cam=None
   dione_dev=/proc/device-tree$bus0/cam_i2cmux/i2c@0/xenics_dione_ir_a@0e
   eg_ec_dev=/proc/device-tree$bus0/cam_i2cmux/i2c@0/eg_ec_a@16
   if [[ -d $dione_dev && -d $eg_ec_dev ]]
   then
      get_cam_dt $dione_dev $eg_ec_dev
      echo "Camera port 0 configuration : $cam"
   fi

   cam=None
   dione_dev=/proc/device-tree$bus0/cam_i2cmux/i2c@1/xenics_dione_ir_e@0e
   eg_ec_dev=/proc/device-tree$bus0/cam_i2cmux/i2c@1/eg_ec_e@16
   if [[ -d $dione_dev && -d $eg_ec_dev ]]
   then
      get_cam_dt $dione_dev $eg_ec_dev
      echo "Camera port 1 configuration : $cam"
   fi
elif [[ $boardtype == "Jetson AGX Orin" ]]
then

   cam=None
   dione_dev=/proc/device-tree$bus0/i2c@31e0000/xenics_dione_ir_a@0e
   eg_ec_dev=/proc/device-tree$bus0/i2c@31e0000/eg_ec_a@16
   if [[ -d $dione_dev && -d $eg_ec_dev ]]
   then
      get_cam_dt $dione_dev $eg_ec_dev
      echo "Camera port 0 configuration : $cam"
   else
      echo "Camera port 0 configuration missing"
   fi

   cam=None
   dione_dev=/proc/device-tree$bus0/i2c@c240000/xenics_dione_ir_g@0e
   eg_ec_dev=/proc/device-tree$bus0/i2c@c240000/eg_ec_g@16
   if [[ -d $dione_dev && -d $eg_ec_dev ]]
   then
      get_cam_dt $dione_dev $eg_ec_dev
      echo "Camera port 1 configuration : $cam"
   else
      echo "Camera port 1 configuration missing"
   fi

   cam=None
   dione_dev=/proc/device-tree$bus0/i2c@c250000/xenics_dione_ir_e@0e
   eg_ec_dev=/proc/device-tree$bus0/i2c@c250000/eg_ec_e@16
   if [[ -d $dione_dev && -d $eg_ec_dev ]]
   then
      get_cam_dt $dione_dev $eg_ec_dev
      echo "Camera port 2 configuration : $cam"
   else
      echo "Camera port 2 configuration missing"
   fi

   cam=None
   dione_dev=/proc/device-tree$bus0/i2c@3180000/xenics_dione_ir_c@0e
   eg_ec_dev=/proc/device-tree$bus0/i2c@3180000/eg_ec_c@16
   if [[ -d $dione_dev && -d $eg_ec_dev ]]
   then
      get_cam_dt $dione_dev $eg_ec_dev
      echo "Camera port 3 configuration : $cam"
   else
      echo "Camera port 3 configuration missing"
   fi

elif [[ $boardtype == "Jetson Orin NX" || $boardtype == "Jetson Orin Nano" ]]
then
   cam=None
   dione_dev=/proc/device-tree$bus0/cam_i2cmux/i2c@0/xenics_dione_ir_b@0e
   eg_ec_dev=/proc/device-tree$bus0/cam_i2cmux/i2c@0/eg_ec_b@16
   if [[ -d $dione_dev && -d $eg_ec_dev ]]
   then
      get_cam_dt $dione_dev $eg_ec_dev
      echo "Camera port 0 configuration : $cam"
   fi

   cam=None
   dione_dev=/proc/device-tree$bus0/cam_i2cmux/i2c@1/xenics_dione_ir_c@0e
   eg_ec_dev=/proc/device-tree$bus0/cam_i2cmux/i2c@1/eg_ec_c@16
   if [[ -d $dione_dev && -d $eg_ec_dev ]]
   then
      get_cam_dt $dione_dev $eg_ec_dev
      echo "Camera port 1 configuration : $cam"
   fi
fi
