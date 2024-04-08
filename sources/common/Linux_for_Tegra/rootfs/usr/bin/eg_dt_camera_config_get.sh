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

boardtype=$(cat /proc/device-tree/chosen/ids |awk -F"-" '{print $1}')
if [[ $boardtype == 3668 ]]
then
   echo board type $boardtype : Xavier NX
fi
if [[ $boardtype == 3448 ]]
then
   echo board type $boardtype : Nano
fi
if [[ $boardtype == 3701 ]]
then
   echo board type $boardtype : AGX Orin
fi

if [[ $boardtype == 3668 || $boardtype == 3448 ]] # Xavier NX or Nano
then
   cam=None
   dione_dev=/proc/device-tree/cam_i2cmux/i2c@0/xenics_dione_ir_a@0e
   eg_ec_dev=/proc/device-tree/cam_i2cmux/i2c@0/eg_ec_a@16
   if [[ -d $dione_dev && -d $eg_ec_dev ]]
   then
      get_cam_dt $dione_dev $eg_ec_dev
      echo "Camera port 0 configuration : $cam"
   fi

   cam=None
   dione_dev=/proc/device-tree/cam_i2cmux/i2c@1/xenics_dione_ir_c@0e
   eg_ec_dev=/proc/device-tree/cam_i2cmux/i2c@1/eg_ec_c@16
   if [[ -d $dione_dev && -d $eg_ec_dev ]]
   then
      get_cam_dt $dione_dev $eg_ec_dev
      echo "Camera port 1 configuration : $cam"
   fi
elif [[ $boardtype == 3701 ]] # AGX Orin
then
   cam=None
   dione_dev=/proc/device-tree/i2c@c240000/xenics_dione_ir_g@0e
   eg_ec_dev=/proc/device-tree/i2c@c240000/eg_ec_g@16
   if [[ -d $dione_dev && -d $eg_ec_dev ]]
   then
      get_cam_dt $dione_dev $eg_ec_dev
      echo "Camera port AB configuration : $cam"
   else
      echo "Camera port AB configuration missing"
   fi

   cam=None
   dione_dev=/proc/device-tree/i2c@31e0000/xenics_dione_ir_a@0e
   eg_ec_dev=/proc/device-tree/i2c@31e0000/eg_ec_a@16
   if [[ -d $dione_dev && -d $eg_ec_dev ]]
   then
      get_cam_dt $dione_dev $eg_ec_dev
      echo "Camera port CD configuration : $cam"
   else
      echo "Camera port CD configuration missing"
   fi
else
   echo "Unknown board type $boardtype"
fi
