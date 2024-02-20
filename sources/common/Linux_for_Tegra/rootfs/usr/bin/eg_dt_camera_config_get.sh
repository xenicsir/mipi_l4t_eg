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


cam=None
get_cam_dt /proc/device-tree/cam_i2cmux/i2c@0/xenics_dione_ir_a@0e /proc/device-tree/cam_i2cmux/i2c@0/eg_ec_a@16
echo "Camera port 0 configuration : $cam"

cam=None
get_cam_dt /proc/device-tree/cam_i2cmux/i2c@1/xenics_dione_ir_c@0e /proc/device-tree/cam_i2cmux/i2c@1/eg_ec_c@16
echo "Camera port 1 configuration : $cam"



